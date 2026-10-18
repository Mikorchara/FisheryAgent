"""Management HTTP -> independent 2/2/3 scope -> original Runtime. Fake Provider only."""

from dataclasses import replace
import json
from unittest.mock import patch
import unittest

from apps.ai_service.runtime.assistant import AssistantService, MULTI_ROUND_SYSTEM_INSTRUCTION
from apps.ai_service.runtime.sources import SourceRequirement, requirement_satisfied_by_ledger
from apps.ai_backend.execution import current_handle
from apps.ai_backend.model_gateway import ModelResponse, ModelToolCall
from apps.ai_service.service import ManagementAssistantService, PRESETS
from apps.ai_service.execution import load_execution_config
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
import apps.management_web.tests.test_assistant as fixture


WATER='get_current_water_quality'
KNOWLEDGE='search_fishery_knowledge'


def tool(name=WATER, identifier='water', arguments='{}'):
    return ModelResponse(None,tool_calls=(ModelToolCall(identifier,name,arguments),),finish_reason='tool_calls')


class DecisionGateway(fixture.RecordingGateway):
    def __init__(self,decide):
        super().__init__();self.decide=decide;self.runtimes=[];self.handles=[]

    def complete(self,request,runtime):
        self.runtimes.append(runtime);self.handles.append(current_handle())
        self._responses=iter((self.decide(len(self.requests)+1,request),))
        return super().complete(request,runtime)


class ManagementMultiRoundTests(unittest.TestCase):
    setUp=fixture.ManagementAssistantTests.setUp
    batch=fixture.ManagementAssistantTests.batch
    envelope=fixture.ManagementAssistantTests.envelope
    send=fixture.ManagementAssistantTests.send

    def start_trial(self,*,config=None,names=(WATER,KNOWLEDGE)):
        previous=self.backend
        self.backend=ManagementAssistantService(self.monitoring,knowledge=previous.knowledge,credentials=previous.credentials,
            traces=previous.traces,policy_directory=self.root/'policies',gateway_factory=lambda:self.gateway,
            execution_config=config or load_execution_config(enable_trial=True))
        selections=self.backend.policy_store.default_selections()
        selections['modes']['assistant']['selected_tools']=list(names)
        self.backend.policy_store.save(selections)
        self.ai=ManagementAssistant(self.backend)
        self.app=create_app(data_service=self.monitoring,ai=self.ai);self.client=self.app.test_client()
        self.refresh()

    def refresh(self):
        self.config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.headers={'X-Management-AI':self.config['browser_token']}

    def captured_send(self,**kwargs):
        runs=[];original=AssistantService.send
        def record(service,request,runtime):
            result=original(service,request,runtime);runs.append(result);return result
        with patch.object(AssistantService,'send',new=record):response=self.send(**kwargs)
        return response.get_json()['result'],runs[0]

    def two_tool_gateway(self,*,continue_if_low=True,third=None):
        def decide(index,request):
            if index==1:
                self.assertEqual(request.messages[0].content,MULTI_ROUND_SYSTEM_INSTRUCTION)
                self.assertFalse(any(m.role=='tool' for m in request.messages))
                return tool()
            payloads=[json.loads(m.content) for m in request.messages if m.role=='tool']
            self.assertEqual(payloads[0]['device_id'],'pond-a')
            if index==2:
                self.assertEqual(len(payloads),1)
                self.assertNotEqual(request.tool_choice,'none')
                if continue_if_low and payloads[0]['water_quality']['dissolved_oxygen_mg_l']<3:
                    return tool(KNOWLEDGE,'knowledge','{"query":"fixture-low-oxygen"}')
                return fixture.final('early final')
            self.assertEqual(index,3);self.assertEqual(len(payloads),2)
            self.assertEqual(payloads[1]['status'],'NO_MATCH')
            self.assertEqual(request.tool_choice,'none')
            return third or fixture.final('final after actual results')
        return DecisionGateway(decide)

    def assert_failed(self,public,code):
        self.assertEqual(public['error_code'],code)
        self.assertFalse(public['successful_turn']);self.assertEqual(public['final_text'],'')
        self.assertIsNone(public['completed_at'])

    def test_three_paths_direct_early_and_two_tools_decided_from_actual_water_result(self):
        for path in ('direct','normal','low'):
            with self.subTest(path=path):
                batch=self.batch(oxygen=2.2 if path=='low' else 6.4)
                self.start_trial()
                self.gateway=fixture.RecordingGateway(fixture.final()) if path=='direct' else self.two_tool_gateway()
                with patch.object(self.backend.knowledge,'search',return_value=()) as search:
                    public,run=self.captured_send()
                self.assertTrue(public['successful_turn'])
                count={'direct':1,'normal':2,'low':3}[path]
                self.assertEqual(len(self.gateway.requests),count)
                self.assertEqual(public['activity']['counts']['tools_executed'],count-1)
                self.assertEqual(public['execution']['release_status'],'local_experimental')
                if path!='direct':self.assertEqual(self.gateway.runtimes[0].max_retries,0)
                if path!='direct':
                    p=json.loads(next(m.content for m in self.gateway.requests[1].messages if m.role=='tool'))
                    self.assertEqual(p['batch_id'],batch['batch_id'])
                    self.assertTrue(all(runtime is self.gateway.runtimes[0] for runtime in self.gateway.runtimes))
                    self.assertTrue(all(handle is self.gateway.handles[0] for handle in self.gateway.handles))
                if path=='low':
                    self.assertEqual([s['kind'] for s in public['activity']['steps']],['model','tool','model','tool','model'])
                    self.assertEqual(len(run.source_ledger.entries),2)
                    self.assertTrue(run.source_ledger.entries[0].receipt.observation_query_completed)
                    self.assertTrue(run.source_ledger.entries[1].receipt.project_search_completed)
                    self.assertFalse(run.source_ledger.entries[1].receipt.has_observation)
                    for requirement in (SourceRequirement.CURRENT_OBSERVATION_QUERY,SourceRequirement.PROJECT_KNOWLEDGE_SEARCH):
                        self.assertTrue(requirement_satisfied_by_ledger(requirement,run.source_ledger))
                    self.assertFalse(public['legacy_projection_available'])
                    search.assert_called_once_with('fixture-low-oxygen',top_k=3)
                else:search.assert_not_called()

    def test_device_frozen_and_usage_aggregated_across_three_requests(self):
        self.batch(oxygen=2.2);self.batch('pond-b',oxygen=6.4);self.start_trial()
        gateway=self.two_tool_gateway();old_decide=gateway.decide
        from apps.ai_backend.contracts import Usage,UsageSource
        def decide(index,request):
            self.client.get('/api/monitoring?device=pond-b')
            return replace(old_decide(index,request),usage=Usage(2,3,5,source=UsageSource.PROVIDER))
        gateway.decide=decide;self.gateway=gateway
        with patch.object(self.backend.knowledge,'search',return_value=()):public,run=self.captured_send()
        self.assertTrue(public['successful_turn'])
        self.assertEqual(public['activity']['aggregate_usage']['total_tokens'],15)
        self.assertEqual(public['device_id'],'pond-a')

    def test_policy_scope_mismatch_rejected_before_credentials_or_gateway(self):
        for names in ((WATER,),(),(KNOWLEDGE,)):
            self.start_trial(names=names)
            self.assertFalse(self.config['presets'][0]['execution']['can_send'])
            with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credential access')):
                response=self.send()
            self.assertEqual(response.get_json()['error_code'],'ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH')
            self.assertEqual(self.gateway.requests,[])

    def test_exact_identity_protocol_prompt_history_binding_and_model_scopes_isolated(self):
        raw=json.loads((__import__('pathlib').Path(__file__).parents[2]/'ai_service/resources/assistant_execution.json').read_text(encoding='utf-8'))
        from apps.ai_service.execution import ManagementExecutionConfig
        for field in ('identity','protocol_spec','prompt_sha256','history_version','tool_definitions_sha256','data_bindings'):
            data=json.loads(json.dumps(raw));data['multi_round_enabled']=True
            scope=data['releases'][0]['scope'];runtime=scope['runtime']
            if field=='identity':runtime[field][-1]+='-different'
            elif field=='protocol_spec':runtime[field]['version']='different'
            elif field=='data_bindings':scope[field]['water']='different'
            else:runtime[field]='different'
            self.start_trial(config=ManagementExecutionConfig.from_dict(data))
            self.assertFalse(self.config['presets'][0]['execution']['can_send'],field)
            self.assertTrue(self.config['presets'][1]['execution']['can_send'],field)
            self.assertEqual(self.send().get_json()['error_code'],'ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH')
        self.assertEqual(self.gateway.requests,[])

    def test_revision_changed_and_browser_cannot_override_mode_budget_prompt(self):
        self.start_trial();value=self.envelope()
        selections=self.backend.policy_store.default_selections();self.backend.policy_store.save(selections)
        response=self.client.post('/api/ai/messages',headers=self.headers,json=value)
        self.assertEqual(response.get_json()['error_code'],'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.start_trial()
        for field in ('execution_mode','budget','turn_timeout_s','prompt_id','execution_config'):
            self.assertEqual(self.send(**{field:'override'}).get_json()['error_code'],'INVALID_ASSISTANT_REQUEST')
        self.assertEqual(self.gateway.requests,[])

    def test_limit_three_requests_never_four_and_multiple_calls_never_execute(self):
        self.batch(oxygen=2.2);self.start_trial()
        self.gateway=self.two_tool_gateway(third=tool(identifier='third'))
        with patch.object(self.backend.knowledge,'search',return_value=()):public,run=self.captured_send()
        self.assert_failed(public,'TOOL_ROUND_LIMIT');self.assertEqual(len(self.gateway.requests),3)
        self.assertEqual(len(run.source_ledger.entries),2)
        response=ModelResponse(None,tool_calls=(ModelToolCall('a',WATER,'{}'),ModelToolCall('b',KNOWLEDGE,'{"query":"x"}')),finish_reason='tool_calls')
        self.gateway=fixture.RecordingGateway(response)
        with patch.object(self.monitoring,'capture_water') as capture,patch.object(self.backend.knowledge,'search') as search:
            public,run=self.captured_send()
        self.assert_failed(public,'TOOL_CALL_LIMIT');capture.assert_not_called();search.assert_not_called()
        self.assertEqual(run.source_ledger.entries,())

    def test_invalid_args_and_local_error_preserve_existing_audit_no_success(self):
        self.batch(oxygen=2.2);self.start_trial()
        for response,code in ((tool(arguments='{"extra":1}'),'INVALID_TOOL_ARGUMENTS'),
                              (tool(KNOWLEDGE,'knowledge','{}'),'INVALID_TOOL_ARGUMENTS')):
            self.gateway=fixture.RecordingGateway(response)
            with patch.object(self.monitoring,'capture_water') as capture,patch.object(self.backend.knowledge,'search') as search:
                public,run=self.captured_send()
            self.assert_failed(public,code);capture.assert_not_called();search.assert_not_called()
        self.gateway=self.two_tool_gateway()
        with patch.object(self.backend.knowledge,'search',side_effect=RuntimeError('fictional-private')):
            public,run=self.captured_send()
        self.assert_failed(public,'TOOL_EXECUTION_ERROR');self.assertEqual(len(self.gateway.requests),2)
        self.assertTrue(run.source_ledger.entries[0].receipt.observation_query_completed)
        self.assertFalse(run.source_ledger.entries[1].receipt.project_search_completed)
        self.assertNotIn('fictional-private',json.dumps(public))

    def test_cancel_and_whole_turn_deadline_after_first_result_block_followup(self):
        self.batch(oxygen=2.2);self.start_trial()
        original=self.monitoring.capture_water
        for stop in (True,False):
            clock=[100.0]
            def capture(*args):
                result=original(*args)
                if stop:current_handle().cancel()
                else:clock[0]+=1000
                return result
            self.gateway=fixture.RecordingGateway(tool(),fixture.final())
            with patch('apps.ai_backend.execution.time.monotonic',side_effect=lambda:clock[0]), \
                 patch.object(self.monitoring,'capture_water',side_effect=capture):
                public,run=self.captured_send()
            self.assert_failed(public,'USER_CANCELLED' if stop else 'TOTAL_TIMEOUT')
            self.assertEqual(len(self.gateway.requests),1)

    def test_history_success_only_and_rollback_to_single_round(self):
        self.batch(oxygen=2.2);self.start_trial();self.gateway=self.two_tool_gateway()
        with patch.object(self.backend.knowledge,'search',return_value=()):first,run=self.captured_send()
        self.gateway=fixture.RecordingGateway(fixture.final('concept'))
        second,run=self.captured_send(history=[{'user':'old question','assistant':first['final_text'],'completed_at':first['completed_at']}])
        self.assertTrue(second['successful_turn']);self.assertEqual(second['history_turns_sent'],1)
        self.assertFalse(any(m.role=='tool' or m.tool_calls for m in self.gateway.requests[0].messages))
        self.assertEqual(run.source_ledger.entries,())
        previous_epoch=self.config['epoch']
        self.start_trial(config=load_execution_config())
        self.assertNotEqual(self.config['epoch'],previous_epoch)
        self.assertEqual(self.config['max_model_requests'],2)
        self.assertEqual(self.config['presets'][0]['execution']['mode'],'SINGLE_ROUND')
        self.gateway=fixture.RecordingGateway(tool(),tool(KNOWLEDGE,'knowledge','{"query":"x"}'))
        public,run=self.captured_send();self.assert_failed(public,'TOOL_ROUND_LIMIT')
        self.assertEqual(len(self.gateway.requests),2)

    def test_ollama_own_trial_scope_and_no_streaming_inherited(self):
        self.batch(oxygen=2.2);self.start_trial();self.gateway=self.two_tool_gateway()
        with patch.object(self.backend.knowledge,'search',return_value=()):
            public,run=self.captured_send(preset_id=PRESETS[1],revision=self.config['presets'][1]['revision'])
        self.assertTrue(public['successful_turn']);self.assertEqual(public['transport'],'normal')
        self.assertEqual(public['execution']['release_status'],'local_experimental')

    def test_unauthorized_tool_cannot_read_old_snapshot_or_gain_source(self):
        self.start_trial();self.gateway=fixture.RecordingGateway(tool('score_current_water_quality'))
        with patch.object(self.monitoring,'capture_water') as capture:
            public,run=self.captured_send()
        self.assertFalse(public['successful_turn']);capture.assert_not_called()
        self.assertTrue(all(not e.receipt.sources for e in run.source_ledger.entries))
        self.assertFalse(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION,run.source_ledger))
        self.assertEqual(len(self.gateway.requests),1)

    def test_trace_failure_after_two_tools_prevents_successful_commit(self):
        self.batch(oxygen=2.2);self.start_trial();self.gateway=self.two_tool_gateway()
        with patch.object(self.backend.knowledge,'search',return_value=()), \
             patch.object(self.backend.traces,'record_assistant',side_effect=OSError('fictional-private')):
            public,run=self.captured_send()
        self.assert_failed(public,'TRACE_WRITE_ERROR')
        self.assertEqual(len(run.source_ledger.entries),2)
        self.assertEqual(len(self.gateway.requests),3)
        self.assertNotIn('fictional-private',json.dumps(public))

    def test_cli_trial_is_explicit_and_never_executes_provider(self):
        from apps.management_web.__main__ import main
        import io
        with patch('sys.argv',['management_web','--assistant-multi-round-trial']), \
             patch('sys.stderr',new_callable=io.StringIO), \
             patch('apps.management_web.ai_adapter.ManagementAssistant.local') as adapter:
            with self.assertRaises(SystemExit):main()
        adapter.assert_not_called()
        with patch('sys.argv',['management_web','--enable-assistant','--assistant-multi-round-trial']), \
             patch('apps.monitoring.repository.MonitoringRepository'), \
             patch('apps.monitoring.service.MonitoringService'), \
             patch('apps.management_web.ai_adapter.ManagementAssistant.local') as adapter, \
             patch('apps.management_web.__main__.create_app') as factory,patch('builtins.print'):
            main()
        self.assertTrue(adapter.call_args.kwargs['multi_round_trial'])
        self.assertFalse(factory.return_value.run.call_args.kwargs['load_dotenv'])
