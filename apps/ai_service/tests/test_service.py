"""Headless AI application tests: no Flask/HTTP client, no external network."""

from apps.knowledge.tests.support import reference_knowledge

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle, current_handle
from apps.ai_backend.model_gateway import GatewayError, ModelResponse, ModelToolCall
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_service.service import ManagementAssistantService, PRESETS
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


from apps.ai_backend.tests.support import ScriptedGateway as MockGateway


from apps.ai_backend.tests.support import ScriptedGateway as MockGateway


class RecordingGateway(MockGateway):
    def __init__(self, *responses):
        super().__init__(responses=responses)
        self.requests, self.handles = [], []

    def complete(self, request, runtime):
        self.requests.append(request); self.handles.append(current_handle())
        return super().complete(request, runtime)


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.sendto',
                       'socket.getaddrinfo', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('Headless tests forbid network'))
            guard.start(); self.addCleanup(guard.stop)
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        self.monitoring = MonitoringService(MonitoringRepository(self.root/'monitoring.sqlite3'),
            device_names={'pond-a':'A', 'pond-b':'B'}, clock=lambda:self.now)
        ref = assistant_profile(PRESETS[0]).credential_ref
        self.gateway = RecordingGateway(ModelResponse('headless final', finish_reason='stop'))
        self.backend = ManagementAssistantService(self.monitoring,
            knowledge=reference_knowledge(),
            credentials=CredentialStore(process_env={ref:'fictional-headless-value'}),
            traces=JsonlTraceSink(self.root/'trace.jsonl',tool_names=(
                'get_current_water_quality','search_fishery_knowledge')), policy_directory=self.root/'policy',
            gateway_factory=lambda:self.gateway)

    def envelope(self, **overrides):
        config = self.backend.bootstrap('pond-a')
        return {'preset_id':PRESETS[0], 'question':'headless question', 'history':[],
            'device_id':'pond-a', 'epoch':config['epoch'], 'revision':config['presets'][0]['revision'],
            'confirm_network':True, **overrides}

    def batch(self, device, oxygen):
        b = Simulator(start=self.now, session_id=device, device_id=device).advance()
        self.now = datetime.fromisoformat(b['timestamp'])
        b['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen,min=oxygen,max=oxygen,latest=oxygen)
        self.monitoring.ingest(b)
        return b

    def test_package_dependency_direction_and_control_owner(self):
        package = Path(__file__).resolve().parents[1]
        for path in package.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            modules = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            modules += [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names]
            self.assertFalse(any(m.startswith(('flask','apps.management_web')) for m in modules), path.name)
        for attr in ('browser_token','requests','handle','prepare'):
            self.assertFalse(hasattr(self.backend,attr))

    def test_bootstrap_and_preparation_do_not_read_data_resolve_credentials_or_run_gateway(self):
        with patch.object(self.monitoring,'capture_water') as read, \
             patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('preflight only')), \
             patch.object(self.backend,'gateway_factory',side_effect=AssertionError('no model')):
            config = self.backend.bootstrap('pond-a')
            prepared = self.backend.prepare_turn(self.envelope())
        read.assert_not_called()
        self.assertNotIn('browser_token',config)
        self.assertEqual((config['max_tool_calls'],config['max_tool_rounds'],config['max_model_requests']),(1,1,2))
        self.assertEqual([p['preset_id'] for p in config['presets']], list(PRESETS))
        self.assertNotIn('headless question',repr(prepared))
        with self.assertRaises(FrozenInstanceError): prepared.device_id='pond-b'

    def test_direct_final_reuses_supplied_handle_and_commit_gate_without_http(self):
        handle = RequestHandle()
        result = self.backend.execute_turn(self.backend.prepare_turn(self.envelope()),handle)
        self.assertTrue(result['successful_turn'])
        self.assertEqual(result['final_text'],'headless final')
        self.assertEqual(result['transport'],'normal')
        self.assertEqual(handle.state,'COMPLETED')
        self.assertIs(self.gateway.handles[0],handle)
        self.assertEqual(result['activity']['counts']['tools_executed'],0)
        with self.assertRaises(GatewayError) as replay:
            self.backend.execute_turn(self.backend.prepare_turn(self.envelope()),handle)
        self.assertEqual(replay.exception.code,'REQUEST_ALREADY_EXECUTED')
        self.assertEqual(len(self.gateway.requests),1)

    def test_frozen_device_and_policy_use_monitoring_after_other_bootstrap_and_policy_change(self):
        old = self.batch('pond-a',2.2); self.batch('pond-b',6.4)
        prepared = self.backend.prepare_turn(self.envelope())
        value = self.backend.policy_store.default_selections()
        value['modes']['assistant']['selected_tools']=[]
        self.backend.policy_store.save(value)
        self.backend.bootstrap('pond-b')
        self.gateway = RecordingGateway(ModelResponse(None,tool_calls=(ModelToolCall('call','get_current_water_quality','{}'),),
            finish_reason='tool_calls'),ModelResponse('final',finish_reason='stop'))
        handle = RequestHandle()
        result = self.backend.execute_turn(prepared,handle)
        self.assertTrue(result['successful_turn'])
        tool = json.loads(next(m.content for m in self.gateway.requests[1].messages if m.role=='tool'))
        self.assertEqual(tool['device_id'],'pond-a')
        self.assertEqual(tool['batch_id'],old['batch_id'])
        self.assertEqual(tool['water_quality']['dissolved_oxygen_mg_l'],2.2)
        self.assertTrue(all(h is handle for h in self.gateway.handles))
        self.assertEqual(self.gateway.requests[1].tool_choice,'none')

    def test_epoch_invalidates_prepared_turn_without_network(self):
        prepared = self.backend.prepare_turn(self.envelope())
        self.backend.epoch='restarted'
        with self.assertRaises(GatewayError) as error:
            self.backend.execute_turn(prepared,RequestHandle())
        self.assertEqual(error.exception.code,'ASSISTANT_SESSION_EXPIRED')
        self.assertEqual(self.gateway.requests,[])

    def test_preflight_rejects_web_control_fields_and_non_business_overrides(self):
        for field in ('request_id','control_token','tools','mode','deadline','source_requirement','browser_token'):
            with self.subTest(field=field),self.assertRaises(GatewayError) as error:
                self.backend.prepare_turn(self.envelope(**{field:'fictional'}))
            self.assertEqual(error.exception.code,'INVALID_ASSISTANT_REQUEST')
        with self.assertRaises(GatewayError) as error:
            self.backend.prepare_turn(self.envelope(confirm_network=False))
        self.assertEqual(error.exception.code,'NETWORK_CONFIRMATION_REQUIRED')
        self.assertEqual(self.gateway.requests,[])

    def test_cancelled_handle_never_resolves_credentials_or_sends_model_request(self):
        prepared = self.backend.prepare_turn(self.envelope())
        handle = RequestHandle(); handle.cancel()
        with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('cancelled')),self.assertRaises(GatewayError) as error:
            self.backend.execute_turn(prepared,handle)
        self.assertEqual(error.exception.code,'USER_CANCELLED')
        self.assertEqual(self.gateway.requests,[])

    def test_local_composition_uses_daily_storage_without_private_access(self):
        location = SimpleNamespace(env_path=self.root/'not-read.env')
        with patch('apps.ai_service.runtime.locations.private_project_location',return_value=location) as locate, \
             patch('apps.ai_service.service.CredentialStore') as credentials:
            backend = ManagementAssistantService.local(self.monitoring,self.root,knowledge=self.backend.knowledge)
        locate.assert_called_once_with(self.root.resolve())
        credentials.assert_called_once_with(location.env_path,private_location=location)
        self.assertIs(backend.monitoring,self.monitoring)
        self.assertEqual(backend.traces.path,self.root/'apps/data/logs/assistant-traces.jsonl')
        self.assertEqual(backend.policy_store.directory,self.root/'apps/data/tool-policies')

    def test_local_streaming_opt_in_is_independent_of_normal_mode_and_creates_new_epoch(self):
        location=SimpleNamespace(env_path=self.root/'not-read.env')
        with patch('apps.ai_service.runtime.locations.private_project_location',return_value=location), \
             patch('apps.ai_service.service.CredentialStore'):
            trial=ManagementAssistantService.local(self.monitoring,self.root,streaming_trial=True,knowledge=self.backend.knowledge)
            rollback=ManagementAssistantService.local(self.monitoring,self.root,knowledge=self.backend.knowledge)
        self.assertTrue(trial._streaming_config.enabled)
        self.assertFalse(trial._execution_config.multi_round_enabled)
        self.assertFalse(rollback._streaming_config.enabled)
        self.assertNotEqual(trial.epoch,rollback.epoch)
        self.assertFalse((self.root/'apps/data/tool-policies').exists())
