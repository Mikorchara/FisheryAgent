"""Management HTTP -> formal Knowledge Handler/Executor/Source Gate; no network."""

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from apps.ai_service.runtime.assistant import AssistantService
from apps.ai_service.runtime.sources import SourceRequirement, requirement_satisfied_by_ledger
from fishery_ai.contracts import KnowledgeEvidence
from apps.ai_backend.execution import current_handle
from apps.ai_backend.model_gateway import ModelResponse, ModelToolCall
from apps.ai_service.business_tools.fishery_knowledge import SEARCH_FISHERY_KNOWLEDGE as KNOWLEDGE
from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY as WATER
from apps.ai_service.business_tools.registry import bind_tools
from apps.ai_backend.tools.registry import ToolRegistry
import apps.management_web.tests.test_assistant as fixture


QUERY_TEXT = 'fictional-query-do-not-log'
EVIDENCE_TEXT = 'fictional-evidence-body-do-not-log'


class ManagementKnowledgeTests(unittest.TestCase):
    setUp = fixture.ManagementAssistantTests.setUp
    batch = fixture.ManagementAssistantTests.batch
    envelope = fixture.ManagementAssistantTests.envelope
    send = fixture.ManagementAssistantTests.send
    tool_payload = fixture.ManagementAssistantTests.tool_payload

    def authorize(self, names=(WATER, KNOWLEDGE)):
        value = self.backend.policy_store.default_selections()
        value['modes']['assistant']['selected_tools'] = list(names)
        self.backend.policy_store.save(value)
        self.config = self.client.get('/api/ai/bootstrap?device=pond-a').get_json()

    def evidence(self):
        return (KnowledgeEvidence('fixture-knowledge', EVIDENCE_TEXT, 'water_quality', .9,
                                  'fixture-project-source', self.now, source_version='fixture-v1'),)

    def knowledge_call(self, arguments=None):
        return fixture.call(KNOWLEDGE, arguments if arguments is not None else json.dumps({'query': QUERY_TEXT}))

    def captured_send(self, **kwargs):
        captured = []
        original = AssistantService.send
        def record(service, request, runtime):
            result = original(service, request, runtime)
            captured.append(result)
            return result
        with patch.object(AssistantService, 'send', new=record):
            response = self.send(**kwargs)
        return response.get_json()['result'], captured[0]

    def assert_failure(self, public, run, code, requests=1):
        self.assertEqual(public['error_code'], code)
        self.assertFalse(public['successful_turn'])
        self.assertEqual(public['final_text'], '')
        self.assertIsNone(public['completed_at'])
        self.assertEqual(len(self.gateway.requests), requests)
        self.assertFalse(run.source_receipt.has_observation)
        self.assertFalse(run.source_receipt.has_score)

    def assert_safe(self, public):
        text = json.dumps(public) + self.traces.read_text(encoding='utf-8')
        for marker in (QUERY_TEXT, EVIDENCE_TEXT, 'fictional-management-test-value', 'fictional-internal-failure'):
            self.assertNotIn(marker, text)

    def test_defaults_do_not_authorize_or_write_new_tools(self):
        self.assertEqual(self.config['tools'], [WATER])
        self.assertFalse(self.backend.policy_store.path.exists())
        self.gateway = fixture.RecordingGateway(fixture.final())
        with patch.object(self.backend.knowledge, 'search') as search:
            public = self.send().get_json()['result']
        self.assertTrue(public['successful_turn']); search.assert_not_called()
        self.assertFalse(self.backend.policy_store.path.exists())
        self.assertEqual([d.name for d in self.gateway.requests[0].tools], [WATER])

    def test_formal_bindings_and_single_service_reused_without_score_handler(self):
        registry = bind_tools(self.monitoring, 'pond-a', self.backend.knowledge, formal=self.backend.formal_registry)
        knowledge = registry.lookup(KNOWLEDGE)
        self.assertIs(knowledge, self.backend.formal_registry.lookup(KNOWLEDGE))
        self.assertIs(knowledge.handler.keywords['service'], self.backend.knowledge)
        self.assertIs(registry.lookup(WATER).model_definition, self.backend.formal_registry.lookup(WATER).model_definition)
        self.assertEqual([d.name for d in registry.model_definitions()], [WATER, KNOWLEDGE])
        self.authorize((WATER, KNOWLEDGE, 'score_current_water_quality'))
        self.assertEqual(self.config['tools'], [WATER, KNOWLEDGE])
        before = self.backend.policy_store.path.read_bytes()
        self.gateway = fixture.RecordingGateway(fixture.final())
        with patch('apps.ai_service.service.KnowledgeService', side_effect=AssertionError('no second service')):
            self.ai.bootstrap('pond-a'); self.send()
        self.assertEqual(before, self.backend.policy_store.path.read_bytes())

    def test_real_project_knowledge_service_fake_provider_roundtrip(self):
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call('{"query":"  鳗鲡低氧表现  "}'), fixture.final('项目背景解释'))
        with patch.object(self.backend.knowledge, 'search', wraps=self.backend.knowledge.search) as search, \
             patch.object(self.monitoring, 'capture_water', side_effect=AssertionError('Knowledge is not a current read')):
            public, run = self.captured_send(question='请检索项目资料解释鳗鲡低氧表现')
        self.assertTrue(public['successful_turn'])
        search.assert_called_once_with('鳗鲡低氧表现', top_k=3)
        self.assertEqual(self.tool_payload()['status'], 'OK')
        self.assertGreater(run.source_receipt.evidence_count, 0)
        self.assertTrue(run.source_receipt.has_project_evidence)
        self.assertFalse(run.source_receipt.has_observation)
        self.assertEqual(self.gateway.requests[1].tool_choice, 'none')
        self.assertEqual(public['activity']['counts'], {'model_requests_started': 2, 'tool_attempts': 1, 'tools_executed': 1})
        self.assertEqual(public['activity']['budget'], {'tool_calls':1,'tool_rounds':1,'model_requests':2})

    def test_knowledge_evidence_never_satisfies_current_requirement_or_leaks_to_ui(self):
        self.batch()
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final())
        with patch.object(self.backend.knowledge, 'search', return_value=self.evidence()) as search, \
             patch.object(self.monitoring, 'capture_water') as capture:
            public, run = self.captured_send()
        capture.assert_not_called(); search.assert_called_once_with(QUERY_TEXT, top_k=3)
        self.assertTrue(run.source_receipt.project_search_completed)
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.PROJECT_KNOWLEDGE_SEARCH, run.source_ledger))
        self.assertFalse(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_OBSERVATION_QUERY, run.source_ledger))
        self.assertFalse(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION, run.source_ledger))
        self.assertNotIn('water_quality', self.tool_payload())
        tool = public['activity']['steps'][1]
        self.assertEqual(tool['tool_name'], KNOWLEDGE)
        self.assertEqual(tool['evidence_count'], 1)
        self.assertNotIn('freshness', tool)
        self.assert_safe(public)

    def test_no_match_completes_search_without_positive_evidence(self):
        self.authorize((KNOWLEDGE,))
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final('没有合格命中'))
        with patch.object(self.backend.knowledge, 'search', return_value=()):
            public, run = self.captured_send()
        self.assertTrue(public['successful_turn'])
        self.assertEqual(self.tool_payload()['status'], 'NO_MATCH')
        self.assertEqual(self.tool_payload()['evidence'], [])
        self.assertTrue(run.source_receipt.project_search_completed)
        self.assertFalse(run.source_receipt.has_project_evidence)
        self.assertFalse(run.source_receipt.has_observation)
        self.assertEqual(public['activity']['steps'][1]['evidence_count'], 0)
        self.assert_safe(public)

    def test_invalid_parameters_stop_before_retrieval_and_followup(self):
        self.authorize()
        for arguments in ('{}', '{"query":" "}', '{"query":7}',
                          '{"query":"fictional-query-do-not-log","top_k":9}'):
            self.gateway = fixture.RecordingGateway(self.knowledge_call(arguments), fixture.final())
            with patch.object(self.backend.knowledge, 'search') as search:
                public, run = self.captured_send()
            search.assert_not_called()
            self.assert_failure(public, run, 'INVALID_TOOL_ARGUMENTS')
            self.assertFalse(run.source_receipt.project_search_completed)
            self.assertFalse(run.source_receipt.sources)
            self.assertEqual(public['activity']['counts']['tools_executed'], 0)
            self.assertEqual(public['activity']['steps'][1]['argument_diagnostic']['reason'], 'VALIDATOR_REJECTED')
            self.assert_safe(public)

    def test_unapproved_knowledge_rejected_and_browser_cannot_grant_permission(self):
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final())
        with patch.object(self.backend.knowledge, 'search') as search:
            public, run = self.captured_send()
        self.assert_failure(public, run, 'TOOL_NOT_ALLOWED'); search.assert_not_called()
        self.assertFalse(run.source_receipt.project_search_completed)
        self.gateway = fixture.RecordingGateway()
        for override in ({'tools':[KNOWLEDGE]}, {'source_requirement':'PROJECT_KNOWLEDGE_SEARCH'}):
            self.assertEqual(self.send(**override).get_json()['error_code'], 'INVALID_ASSISTANT_REQUEST')
        self.assertEqual(self.gateway.requests, [])

    def test_retrieval_failure_is_error_not_no_match_no_success_no_source(self):
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final())
        with patch.object(self.backend.knowledge, 'search', side_effect=RuntimeError('fictional-internal-failure')):
            public, run = self.captured_send()
        self.assert_failure(public, run, 'TOOL_EXECUTION_ERROR')
        self.assertFalse(run.source_receipt.project_search_completed)
        self.assertFalse(run.source_receipt.has_project_evidence)
        self.assertTrue(public['activity']['steps'][1]['handler_started'])
        self.assert_safe(public)

    def test_trace_failure_after_search_retains_audit_but_never_commits_final_answer(self):
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final())
        with patch.object(self.backend.knowledge, 'search', return_value=self.evidence()), \
             patch.object(self.backend.traces, 'record_assistant', side_effect=OSError('fictional-internal-failure')):
            public, run = self.captured_send()
        self.assert_failure(public, run, 'TRACE_WRITE_ERROR', requests=2)
        self.assertTrue(run.source_receipt.project_search_completed)
        self.assertTrue(run.source_receipt.has_project_evidence)
        self.assert_safe(public)

    def test_multiple_calls_rejected_as_whole_before_either_handler(self):
        self.authorize()
        response = ModelResponse(None, tool_calls=(ModelToolCall('water', WATER, '{}'),
            ModelToolCall('knowledge', KNOWLEDGE, json.dumps({'query':QUERY_TEXT}))), finish_reason='tool_calls')
        self.gateway = fixture.RecordingGateway(response, fixture.final())
        with patch.object(self.monitoring, 'capture_water') as capture, patch.object(self.backend.knowledge, 'search') as search:
            public, run = self.captured_send()
        self.assert_failure(public, run, 'TOOL_CALL_LIMIT')
        capture.assert_not_called(); search.assert_not_called()
        self.assertEqual(run.source_ledger.entries, ())
        self.assertEqual(public['activity']['counts']['tools_executed'], 0)

    def test_second_round_rejected_existing_search_receipt_audited_no_third_request(self):
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.call(), fixture.final())
        with patch.object(self.backend.knowledge, 'search', return_value=()), patch.object(self.monitoring, 'capture_water') as capture:
            public, run = self.captured_send()
        self.assert_failure(public, run, 'TOOL_ROUND_LIMIT', requests=2)
        capture.assert_not_called()
        self.assertEqual(len(run.source_ledger.entries), 1)
        self.assertTrue(run.source_receipt.project_search_completed)

    def test_stop_before_or_during_search_does_not_commit_or_send_followup(self):
        self.authorize()
        for stage in ('before', 'during'):
            def callback(*_):
                if stage == 'before': current_handle().cancel()
            def search(*args, **kwargs):
                if stage == 'during': current_handle().cancel()
                return self.evidence()
            self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final(), callback=callback)
            with patch.object(self.backend.knowledge, 'search', side_effect=search) as retrieval:
                public, run = self.captured_send()
            self.assert_failure(public, run, 'USER_CANCELLED')
            self.assertEqual(retrieval.call_count, 0 if stage=='before' else 1)
            self.assertFalse(run.source_receipt.project_search_completed)
            self.assert_safe(public)

    def test_history_only_success_text_pairs_not_tool_protocol(self):
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final('背景解释'))
        with patch.object(self.backend.knowledge, 'search', return_value=self.evidence()):
            first = self.send().get_json()['result']
        self.gateway = fixture.RecordingGateway(fixture.final('概念解释'))
        with patch.object(self.backend.knowledge, 'search') as search:
            second, run = self.captured_send(history=[{'user':'旧问题','assistant':first['final_text'],
                'completed_at':first['completed_at']}])
        search.assert_not_called()
        self.assertTrue(second['successful_turn'])
        self.assertEqual(second['history_turns_sent'], 1)
        self.assertTrue(all(m.role!='tool' and not m.tool_calls for m in self.gateway.requests[0].messages))
        self.assertEqual(run.source_ledger.entries, ())

    def test_actual_definition_changes_invalidate_confirmation_before_gateway(self):
        self.authorize()
        original = self.backend.formal_registry.lookup
        for change in ('description','parameters'):
            def lookup(name):
                definition = original(name)
                if name != KNOWLEDGE: return definition
                model = definition.model_definition
                delta = {'description':model.description+' fixture revision'} if change=='description' else {
                    'parameters':{**model.parameters_dict(), 'title':'fixture revision'}}
                return replace(definition, model_definition=replace(model, **delta))
            with patch.object(self.backend.formal_registry, 'lookup', side_effect=lookup):
                response = self.send()
            self.assertEqual(response.get_json()['error_code'], 'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.assertEqual(self.gateway.requests, [])

    def test_assembled_tool_set_change_invalidates_old_confirmation(self):
        self.authorize()
        original = ToolRegistry.model_definitions
        with patch.object(ToolRegistry, 'model_definitions',
            lambda registry:tuple(d for d in original(registry) if d.name!=KNOWLEDGE)):
            response = self.send()
        self.assertEqual(response.get_json()['error_code'], 'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.assertEqual(self.gateway.requests, [])

    def test_policy_changes_require_reconfirmation_and_turn_keeps_frozen_permissions(self):
        self.authorize()
        self.gateway = fixture.RecordingGateway(self.knowledge_call(), fixture.final())
        def changed_by_user(index, *_):
            if index==1:
                value=self.backend.policy_store.default_selections()
                self.backend.policy_store.save(value)
        self.gateway.callback = changed_by_user
        with patch.object(self.backend.knowledge, 'search', return_value=()):
            public, run = self.captured_send()
        self.assertTrue(public['successful_turn'])
        self.assertTrue(run.source_receipt.project_search_completed)
        self.gateway = fixture.RecordingGateway()
        response = self.send()
        self.assertEqual(response.get_json()['error_code'], 'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.assertEqual(self.gateway.requests, [])
