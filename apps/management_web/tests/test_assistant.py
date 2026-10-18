"""Management HTTP → formal Assistant → Executor → same SQLite; all sockets blocked."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.sources import SourceRequirement, requirement_satisfied_by_ledger
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import current_handle
from apps.ai_backend.model_gateway import GatewayError, ModelResponse, ModelToolCall
from apps.ai_backend.observability import JsonlTraceSink
from apps.management_web.ai_adapter import ManagementAssistant
from apps.ai_service.service import ManagementAssistantService, PRESETS
from apps.ai_service.business_tools.current_water_quality import water_payload
from apps.management_web.app import create_app
from apps.monitoring.analysis import reading_from_row
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


QUERY = 'get_current_water_quality'


def call(name=QUERY, arguments='{}'):
    return ModelResponse(None, tool_calls=(ModelToolCall('management_call', name, arguments),), finish_reason='tool_calls')


def final(text='离线测试最终回答', reason='stop'):
    return ModelResponse(text, finish_reason=reason)


from apps.ai_backend.tests.support import ScriptedGateway as MockGateway


class RecordingGateway(MockGateway):
    def __init__(self, *responses, callback=None):
        super().__init__(responses=responses)
        self.requests = []
        self.callback = callback

    def complete(self, request, runtime):
        self.requests.append(request)
        if self.callback:
            self.callback(len(self.requests), request, runtime)
        return super().complete(request, runtime)


class ManagementAssistantTests(unittest.TestCase):
    def test_parameter_rejection_reports_safe_reason_without_monitoring_read_or_followup(self):
        self.gateway = RecordingGateway(call(arguments='{"device_id":"fictional-private-argument"}'), final())
        with patch.object(self.monitoring, 'capture_water') as snapshot:
            result = self.send().get_json()['result']
        snapshot.assert_not_called()
        self.assertFalse(result['successful_turn'])
        self.assertEqual(result['final_text'], '')
        self.assertEqual(result['error_code'], 'INVALID_TOOL_ARGUMENTS')
        self.assertEqual(len(self.gateway.requests), 1)
        activity = result['activity']
        self.assertEqual(activity['counts']['tools_executed'], 0)
        self.assertEqual(activity['steps'][-1]['argument_diagnostic'], {
            'schema_version': 1, 'stage': 'definition', 'reason': 'UNEXPECTED_ARGUMENTS',
            'argument_bytes': 42, 'object_member_count': 1})
        public = json.dumps(activity) + self.traces.read_text(encoding='utf-8')
        self.assertNotIn('fictional-private-argument', public)
        self.assertNotIn('device_id', public)

    def setUp(self):
        knowledge=patch('apps.management_web.__main__.knowledge_content')
        self.knowledge_factory=knowledge.start();self.addCleanup(knowledge.stop)
        for name in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.sendto', 'socket.getaddrinfo'):
            guard = patch(name, side_effect=AssertionError('No Provider requests in integration tests'))
            guard.start(); self.addCleanup(guard.stop)
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        self.repository = MonitoringRepository(self.root/'monitor.sqlite3')
        self.monitoring = MonitoringService(self.repository, clock=lambda: self.now,
            device_names={'pond-a': '池 A', 'pond-b': '池 B'})
        self.generators = {device: Simulator(start=self.now, session_id=device, device_id=device)
                           for device in ('pond-a', 'pond-b')}
        self.gateway = RecordingGateway(call(), final())
        self.traces = self.root/'assistant.jsonl'
        ref = assistant_profile(PRESETS[0]).credential_ref
        self.backend = ManagementAssistantService(self.monitoring,
            credentials=CredentialStore(process_env={ref: 'fictional-management-test-value'}),
            traces=JsonlTraceSink(self.traces,tool_names=(QUERY,'search_fishery_knowledge')), policy_directory=self.root/'policies',
            gateway_factory=lambda: self.gateway)
        self.ai = ManagementAssistant(self.backend)
        self.app = create_app(data_service=self.monitoring, ai=self.ai)
        self.client = self.app.test_client()
        self.config = self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.headers = {'X-Management-AI': self.config['browser_token']}

    def batch(self, device='pond-a', oxygen=2.2):
        batch = self.generators[device].advance()
        self.now = max(self.now, datetime.fromisoformat(batch['timestamp']))
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen, min=oxygen, max=oxygen, latest=oxygen)
        self.monitoring.ingest(batch)
        return batch

    def envelope(self, **changes):
        control = self.client.post('/api/ai/requests', headers=self.headers,
            json={'epoch': self.config['epoch']}).get_json()
        return {**control, 'preset_id': PRESETS[0], 'device_id': 'pond-a',
            'question': '现在水质怎么样？', 'history': [], 'epoch': self.config['epoch'],
            'revision': self.config['presets'][0]['revision'], 'confirm_network': True, **changes}

    def send(self, **changes):
        value = self.envelope(**changes)
        response = self.client.post('/api/ai/messages', headers=self.headers, json=value)
        if response.get_json().get('error_code'):
            self.client.post('/api/ai/cancel', headers=self.headers,
                json={k:value[k] for k in ('request_id', 'control_token')})
        return response

    def tool_payload(self):
        return json.loads(next(m.content for m in self.gateway.requests[1].messages if m.role == 'tool'))

    def test_same_sqlite_device_analysis_times_and_rules(self):
        self.batch(); self.batch('pond-b', 6.4)
        expected = json.loads(json.dumps(self.monitoring.analysis('pond-a').to_dict()))
        web = self.client.get('/api/monitoring?device=pond-a').get_json()
        result = self.send().get_json()['result']
        self.assertTrue(result['successful_turn'])
        payload = self.tool_payload()
        self.assertEqual(payload['device_id'], 'pond-a')
        self.assertEqual(payload['water_quality']['dissolved_oxygen_mg_l'], 2.2)
        self.assertNotIn('analysis', payload)
        self.assertEqual(payload['data_quality'], expected['data_quality'])
        self.assertEqual(payload['evaluated_at'], expected['evaluated_at'])
        expected_findings = [{k:v for k,v in f.items() if k not in ('observation', 'rule_version')}
                             for f in expected['findings']]
        self.assertEqual(payload['findings'], expected_findings)
        self.assertEqual([f['code'] for f in payload['findings'] if f['state']=='HIT'],
                         [f['code'] for f in web['findings']])
        self.assertEqual(payload['batch_id'], web['batch_id'])
        self.assertEqual(payload['water_quality']['observed_at'], web['observed_at'])
        self.assertEqual(payload['window'], web['window'])
        self.assertTrue(any(f['rule']['publication_status'] == 'PROTOTYPE' for f in payload['findings']))
        self.assertEqual(self.gateway.requests[1].tool_choice, 'none')
        self.assertFalse(any('2.2' in (m.content or '') for m in self.gateway.requests[0].messages))
        self.assertEqual(result['activity']['counts']['tools_executed'], 1)

    def test_no_data_not_replaced_by_demo_snapshot(self):
        result = self.send().get_json()['result']
        self.assertTrue(result['successful_turn'])
        self.assertEqual(self.tool_payload()['status'], 'NO_DATA')
        self.assertIsNone(self.tool_payload()['water_quality'])

    def test_stale_offline_invalid_partial_do_not_become_normal(self):
        self.batch()
        self.now += timedelta(seconds=91)
        self.send()
        payload = self.tool_payload()
        self.assertEqual(payload['water_quality']['freshness'], 'stale')
        self.assertEqual(payload['connectivity'], 'offline')
        self.assertFalse(any(f['kind'] == 'WATER_QUALITY' for f in payload['findings']))
        for invalid in (0, 1):
            b = self.generators['pond-a'].advance()
            self.now += timedelta(seconds=10)
            stat = b['water']['metrics']['dissolved_oxygen_mg_l']
            stat.update(mean=None, min=None, max=None, latest=None, valid_samples=0, invalid_samples=invalid)
            self.monitoring.ingest(b)
            payload = water_payload(self.monitoring, 'pond-a')
            self.assertEqual(payload['water_quality']['quality'], 'invalid' if invalid else 'partial')
            self.assertIsNone(payload['water_quality']['dissolved_oxygen_mg_l'])
            self.assertFalse(any(f['code'] == 'LOW_OXYGEN' for f in payload['findings']))
            canonical = reading_from_row(self.repository.read('pond-a', 'water'))
            self.assertEqual(payload['water_quality']['quality'], canonical.quality.value)
            self.gateway = RecordingGateway(call(), final())
            result = self.send().get_json()['result']
            self.assertTrue(result['successful_turn'])
            self.assertEqual(self.tool_payload()['water_quality']['quality'], canonical.quality.value)

    def test_frozen_device_even_when_another_page_queries_other_device(self):
        self.batch(); self.batch('pond-b', 6.4)
        self.gateway.callback = lambda index, *_: self.client.get('/api/monitoring?device=pond-b') if index == 1 else None
        self.send()
        self.assertEqual(self.tool_payload()['device_id'], 'pond-a')
        self.assertEqual(self.tool_payload()['water_quality']['dissolved_oxygen_mg_l'], 2.2)

    def test_concept_history_and_no_eager_water_read(self):
        self.gateway = RecordingGateway(final())
        history = [{'user': '先前问题', 'assistant': '先前回答', 'completed_at': self.now.isoformat()}]
        with patch.object(self.monitoring, 'capture_water', side_effect=AssertionError('no eager read')):
            result = self.send(question='什么是溶氧？', history=history).get_json()['result']
        self.assertTrue(result['successful_turn'])
        self.assertEqual(result['history_turns_received'], 1)
        self.assertEqual(result['activity']['counts']['tools_executed'], 0)
        self.assertTrue(any('先前回答' in (m.content or '') for m in self.gateway.requests[0].messages))

    def test_policy_restriction_and_reconfirmation_never_changes_user_file(self):
        value = self.backend.policy_store.default_selections()
        value['modes']['assistant']['selected_tools'] = []
        self.backend.policy_store.save(value)
        before = self.backend.policy_store.path.read_bytes()
        response = self.send()
        self.assertEqual(response.get_json()['error_code'], 'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.assertEqual(len(self.gateway.requests), 0)
        self.config = self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.gateway = RecordingGateway(final())
        self.send()
        self.assertEqual(self.gateway.requests[0].tools, ())
        self.assertEqual(before, self.backend.policy_store.path.read_bytes())

    def test_tool_projection_version_change_invalidates_old_confirmation_before_provider(self):
        with patch('apps.ai_service.business_tools.current_water_quality.WATER_TOOL_PROJECTION', 'management-current-water@2'):
            response = self.send()
        self.assertEqual(response.get_json()['error_code'], 'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.assertEqual(self.gateway.requests, [])

    def test_models_normal_budget_and_web_cannot_override_contract(self):
        self.assertEqual([p['preset_id'] for p in self.config['presets']], list(PRESETS))
        self.assertEqual(self.config['max_model_requests'], 2)
        for fields in ({'preset_id': 'deepseek-flash-r1'}, {'mode': 'streaming'}, {'source_requirement': 'AUTO'},
                       {'deadline': 999}, {'device_id': 'outside'}, {'confirm_network': False}, {'epoch': 'old'}, {'revision': 'old'}):
            self.assertGreaterEqual(self.send(**fields).status_code, 400)
        self.assertEqual(len(self.gateway.requests), 0)
        self.gateway = RecordingGateway(final())
        result = self.send(preset_id=PRESETS[1], revision=self.config['presets'][1]['revision']).get_json()['result']
        self.assertTrue(result['successful_turn'])

    def test_local_access_and_cross_origin_fail_before_execution(self):
        value = self.envelope()
        for kwargs in ({}, {'headers': {'X-Management-AI': 'wrong'}},
            {'headers': {**self.headers, 'Origin': 'http://evil.invalid'}},
            {'headers': self.headers, 'environ_overrides': {'REMOTE_ADDR': '10.0.0.1'}}):
            self.assertEqual(self.client.post('/api/ai/messages', json=value, **kwargs).status_code, 403)
        self.assertEqual(len(self.gateway.requests), 0)
        self.assertEqual(self.client.post('/api/ingestion/batches', data='x'*9000).status_code, 413)

    def test_cancel_before_and_after_tool_never_commits_or_sends_follow_up(self):
        for at in ('before', 'after'):
            self.gateway = RecordingGateway(call(), final())
            value = self.envelope()
            if at == 'before':
                self.client.post('/api/ai/cancel', headers=self.headers,
                    json={k:value[k] for k in ('request_id', 'control_token')})
                response = self.client.post('/api/ai/messages', headers=self.headers, json=value)
                self.assertEqual(response.get_json()['error_code'], 'USER_CANCELLED')
                self.assertEqual(len(self.gateway.requests), 0)
            else:
                original = self.monitoring.capture_water
                def cancel_after_read(*args, **kwargs):
                    data = original(*args, **kwargs); current_handle().cancel(); return data
                with patch.object(self.monitoring, 'capture_water', side_effect=cancel_after_read):
                    result = self.client.post('/api/ai/messages', headers=self.headers, json=value).get_json()['result']
                self.assertFalse(result['successful_turn'])
                self.assertEqual(result['error_code'], 'USER_CANCELLED')
                self.assertEqual(result['final_text'], '')
                self.assertEqual(len(self.gateway.requests), 1)

    def test_request_replay_truncation_and_safe_errors(self):
        self.gateway = RecordingGateway(final('incomplete', 'length'))
        value = self.envelope()
        result = self.client.post('/api/ai/messages', headers=self.headers, json=value).get_json()['result']
        self.assertFalse(result['successful_turn']); self.assertEqual(result['final_text'], '')
        retry = self.client.post('/api/ai/messages', headers=self.headers, json=value)
        self.assertEqual(retry.get_json()['error_code'], 'REQUEST_ALREADY_EXECUTED')
        self.assertEqual(len(self.gateway.requests), 1)
        text = json.dumps(result) + self.traces.read_text(encoding='utf-8')
        for forbidden in ('fictional-management-test-value', 'control_token', 'raw_result', 'temperature_c'):
            self.assertNotIn(forbidden, text)

    def test_tool_error_unauthorized_and_second_round_fail_safe(self):
        for first, second, expected in ((call('score_current_water_quality'), final(), 'UNKNOWN_TOOL'),
            (call(arguments='{"extra":1}'), final(), 'INVALID_TOOL_ARGUMENTS'),
            (call(), call(), 'TOOL_ROUND_LIMIT')):
            self.gateway = RecordingGateway(first, second)
            result = self.send().get_json()['result']
            self.assertFalse(result['successful_turn']); self.assertEqual(result['error_code'], expected)
        self.gateway = RecordingGateway(call(), final())
        with patch.object(self.monitoring, 'capture_water', side_effect=RuntimeError('private/path/never-echo')):
            result = self.send().get_json()['result']
        self.assertEqual(result['error_code'], 'TOOL_EXECUTION_ERROR')
        self.assertNotIn('private/path', json.dumps(result))

    def test_missing_credential_trace_failure_and_epoch_reset(self):
        self.backend.credentials = CredentialStore(process_env={})
        response = self.send()
        self.assertEqual(response.get_json()['error_code'], 'SECRET_MISSING')
        self.assertEqual(len(self.gateway.requests), 0)
        self.gateway = RecordingGateway(final())
        with patch.object(self.backend.traces, '_append', side_effect=OSError('private path')):
            result = self.send(preset_id=PRESETS[1], revision=self.config['presets'][1]['revision']).get_json()['result']
        self.assertFalse(result['successful_turn']); self.assertEqual(result['final_text'], '')
        value = self.envelope()
        self.backend.epoch = 'restarted'
        self.assertEqual(self.client.post('/api/ai/messages', headers=self.headers, json=value).get_json()['error_code'], 'ASSISTANT_SESSION_EXPIRED')

    def test_stop_during_second_model_request_and_safe_status_polling(self):
        entered, released = threading.Event(), threading.Event()
        outcome = []
        def pause(index, *_):
            if index == 2:
                entered.set()
                if not released.wait(3):
                    raise AssertionError('test synchronization timeout')
                current_handle().check()
        self.gateway.callback = pause
        value = self.envelope()
        control = {k:value[k] for k in ('request_id', 'control_token')}
        def worker():
            with self.app.test_client() as client:
                outcome.append(client.post('/api/ai/messages', headers=self.headers, json=value).get_json())
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            public = self.client.post('/api/ai/request-state', headers=self.headers, json=control).get_json()
            self.assertEqual(public['phase'], 'REQUEST_2')
            self.assertEqual(public['activity']['counts']['tools_executed'], 1)
            self.assertNotIn('"water_quality":', json.dumps(public))
            self.client.post('/api/ai/cancel', headers=self.headers, json=control)
        finally:
            released.set(); thread.join(4)
        self.assertFalse(thread.is_alive())
        result = outcome[0]['result']
        self.assertEqual(result['error_code'], 'USER_CANCELLED')
        self.assertFalse(result['successful_turn']); self.assertEqual(result['final_text'], '')

    def test_receipt_gate_preserved_for_no_data_and_governed_water_payload(self):
        from apps.ai_service.runtime.assistant import AssistantService
        original = AssistantService.send
        captured = []
        def collect(service, request, runtime):
            result = original(service, request, runtime)
            captured.append(result)
            return result
        with patch.object(AssistantService, 'send', new=collect):
            self.send()
            self.batch()
            self.gateway = RecordingGateway(call(), final())
            self.send()
        for result in captured:
            self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_OBSERVATION_QUERY,
                result.source_ledger))
        self.assertFalse(captured[0].source_receipt.has_observation)
        self.assertTrue(captured[1].source_receipt.has_observation)
        self.assertEqual(captured[1].source_receipt.quality.value, 'valid')

    def test_compact_payload_retains_receipt_semantics_for_partial_invalid_stale_offline(self):
        from apps.ai_service.runtime.assistant import AssistantService
        original = AssistantService.send
        captured = []
        def collect(service, request, runtime):
            result = original(service, request, runtime)
            captured.append(result)
            return result
        for state in ('partial', 'invalid', 'stale', 'offline'):
            b = self.generators['pond-a'].advance()
            self.now = max(self.now, datetime.fromisoformat(b['timestamp']))
            if state in ('partial', 'invalid'):
                b['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=None,min=None,max=None,latest=None,
                    valid_samples=0,invalid_samples=1 if state=='invalid' else 0)
            self.monitoring.ingest(b)
            if state in ('stale', 'offline'): self.now += timedelta(seconds=31 if state=='stale' else 91)
            self.gateway = RecordingGateway(call(), final())
            with patch.object(AssistantService, 'send', new=collect):
                result = self.send().get_json()['result']
            self.assertTrue(result['successful_turn'])
            payload = self.tool_payload()
            self.assertNotIn('analysis', payload)
            receipt = captured[-1].source_receipt
            self.assertTrue(receipt.observation_query_completed)
            self.assertEqual(receipt.quality.value, payload['water_quality']['quality'])
            self.assertEqual(receipt.freshness.value, payload['water_quality']['freshness'])
            self.assertFalse(receipt.has_score); self.assertFalse(receipt.has_project_evidence)

    def test_runtime_capability_gate_and_unexpected_error_do_not_leak(self):
        from dataclasses import replace
        from apps.ai_backend.model_options import Support
        p = assistant_profile(PRESETS[0])
        with patch('apps.ai_service.service.assistant_profile', return_value=replace(p,
            capabilities=replace(p.capabilities, tool_calling=Support.UNKNOWN))):
            self.config = self.ai.bootstrap('pond-a')
            response = self.send()
        self.assertEqual(response.get_json()['error_code'], 'ASSISTANT_PRESET_NOT_ALLOWED')
        self.assertEqual(len(self.gateway.requests), 0)
        self.config = self.ai.bootstrap('pond-a')
        with patch.object(self.backend, 'gateway_factory', side_effect=RuntimeError('private-path-and-secret')):
            value = self.envelope()
            response = self.client.post('/api/ai/messages', headers=self.headers, json=value)
        self.assertEqual(response.get_json(), {'error_code': 'AI_SERVICE_UNAVAILABLE'})
        state = self.client.post('/api/ai/request-state', headers=self.headers,
            json={k:value[k] for k in ('request_id', 'control_token')}).get_json()
        self.assertEqual(state['error_code'], 'AI_SERVICE_UNAVAILABLE')

    def test_cli_opt_in_never_starts_model_request_and_legacy_demo_rejected(self):
        from apps.management_web.__main__ import main
        with patch('sys.argv', ['management_web', '--enable-assistant']), \
            patch('apps.monitoring.repository.MonitoringRepository'), \
            patch('apps.monitoring.service.MonitoringService') as monitoring, \
            patch('apps.management_web.ai_adapter.ManagementAssistant.local') as adapter, \
            patch('apps.management_web.__main__.create_app') as factory, patch('builtins.print'):
            main()
        self.assertIs(adapter.call_args.args[0], monitoring.return_value)
        self.assertIs(factory.call_args.kwargs['ai'], adapter.return_value)
        self.assertFalse(factory.return_value.run.call_args.kwargs['load_dotenv'])
        import io
        with patch('sys.argv', ['management_web', '--legacy-demo', '--enable-assistant']), \
            patch('sys.stderr', new_callable=io.StringIO), \
            patch('apps.management_web.ai_adapter.ManagementAssistant.local') as adapter:
            with self.assertRaises(SystemExit): main()
        adapter.assert_not_called()

    def test_history_old_value_is_not_the_next_query_source(self):
        self.batch(oxygen=2.2)
        first = self.send().get_json()['result']
        old_payload = self.tool_payload()
        self.batch(oxygen=6.4)
        self.gateway = RecordingGateway(call(), final())
        result = self.send(question='现在仍然是旧值吗？', history=[{'user':'现在水质？',
            'assistant':'旧记录 DO=2.2，仅历史语境', 'completed_at':first['completed_at']}]).get_json()['result']
        self.assertTrue(result['successful_turn'])
        payload = self.tool_payload()
        self.assertEqual(payload['water_quality']['dissolved_oxygen_mg_l'], 6.4)
        self.assertNotEqual(old_payload['batch_id'], payload['batch_id'])
        self.assertEqual(result['activity']['counts']['tools_executed'], 1)


if __name__ == '__main__':
    unittest.main()
