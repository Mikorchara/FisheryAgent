"""Real management routes/SSE, formal composition and Fake SDK; no live Provider."""
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final, tool_chunks, final_chunks, chunk
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service import normal_selection as release
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.execution import load_execution_config
from apps.ai_service.streaming import load_streaming_config
from apps.ai_service.runtime import assistant, sources
from apps.ai_service.tests import test_history_candidate as fixture
from apps.management_web.app import create_app
from apps.management_web.ai_adapter import ManagementAssistant

WATER, KNOWLEDGE, HISTORY = release.HISTORY_CANDIDATE_TOOL_NAMES
ARGS={WATER:'{}', KNOWLEDGE:'{"query":"鳗鲡低氧表现"}', HISTORY:fixture.fixtures.ARGS}


class UnifiedToolsTests(unittest.TestCase):
    setUp=fixture.HistoryCandidateTests.setUp
    make_monitoring=fixture.HistoryCandidateTests.make_monitoring
    policy=fixture.HistoryCandidateTests.policy

    def configure(self,case='sparse',*,normal=True,streaming=True):
        fixture.HistoryCandidateTests.configure(self,case)
        old=self.backend
        self.backend=ManagementAssistantService(self.monitoring,credentials=old.credentials,traces=old.traces,
            policy_directory=old.policy_store.directory,
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=self.sdk.factory),
            execution_config=load_execution_config(enable_trial=True),streaming_config=load_streaming_config(enable_trial=True),
            unified_config=release.load_unified_tool_trials(normal=normal,streaming=streaming))
        self.web=ManagementAssistant(self.backend)
        self.client=create_app(data_service=self.monitoring,ai=self.web).test_client()
        self.headers={'X-Management-AI':self.web.browser_token}
        self.policy(list(release.HISTORY_CANDIDATE_TOOL_NAMES))

    def envelope(self,streaming=False,**overrides):
        self.config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        control=self.client.post('/api/ai/requests',json={'epoch':self.config['epoch']},headers=self.headers).get_json()
        entry=self.config['presets'][0]['streaming' if streaming else 'execution']
        return dict(preset_id=self.profile.preset_id,device_id='pond-a',question='同一个问题，由Fake模型自主选Tool',
            epoch=self.config['epoch'],revision=entry['revision'],history=[],confirm_network=True,**control,**overrides)

    def plans(self,names,streaming=False,*,finish='stop'):
        calls=[tool_chunks(n,'c'+str(i),ARGS[n]) if streaming else sdk_tool(n,'c'+str(i),ARGS[n],self.profile.model)
               for i,n in enumerate(names)]
        return [*calls,final_chunks('离线完整回答',finish) if streaming else sdk_final('离线完整回答',finish,self.profile.model)]

    def send(self,names=(),streaming=False,*,plans=None,context=None):
        self.sdk=FakeSDK(self.plans(names,streaming) if plans is None else plans,model=self.profile.model)
        body=self.envelope(streaming);self.last_body=body
        self.captured=[];original=assistant.AssistantService.send
        def capture(owner,*args,**kwargs):
            result=original(owner,*args,**kwargs);self.captured.append(result);return result
        with patch.object(assistant.AssistantService,'send',capture),context or nullcontext():
            response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),json=body,headers=self.headers)
            # Keep worker fault/capture patches alive through SSE terminal delivery.
            self.frames=response.get_data(as_text=True) if streaming else ''
        if streaming:
            rows=[json.loads(line[6:]) for line in self.frames.splitlines() if line.startswith('data: ')]
            self.assertEqual([r['seq'] for r in rows],list(range(1,len(rows)+1)))
            self.assertEqual(sum(r['kind'] in ('final','error','cancelled') for r in rows),1)
            value=rows[-1].get('result',rows[-1])
        else:value=response.get_json().get('result',response.get_json())
        response.close();return value

    def test_normal_all_selections_and_sequential_current_history(self):
        for names in ((),(WATER,),(HISTORY,),(KNOWLEDGE,),(WATER,HISTORY)):
            with self.subTest(names=names):
                self.configure();result=self.send(names)
                self.assertTrue(result['successful_turn'],result)
                self.assertEqual(result['execution']['release_status'],'local_experimental')
                self.assertEqual(len(self.sdk.bodies),len(names)+1)
                self.assertEqual([d['function']['name'] for d in self.sdk.bodies[0]['tools']],list(release.HISTORY_CANDIDATE_TOOL_NAMES))
                self.assertTrue(all(b['max_tokens']==1024 for b in self.sdk.bodies))
                self.assert_delivery_and_sources(names)

    def assert_delivery_and_sources(self,names):
        self.assertEqual(len(self.captured[0].source_ledger.entries),len(names))
        for index,body in enumerate(self.sdk.bodies):
            payloads=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
            self.assertEqual(len(payloads),index)
            self.assertTrue(all(p['device_id']=='pond-a' for p in payloads if 'device_id' in p))
        receipts=[entry.receipt for entry in self.captured[0].source_ledger.entries]
        self.assertEqual(sum(r.history_query_completed for r in receipts),names.count(HISTORY))
        self.assertEqual(sum(r.observation_query_completed for r in receipts),names.count(WATER))
        if names==(HISTORY,):
            self.assertFalse(sources.requirement_satisfied_by_ledger(sources.SourceRequirement.CURRENT_OBSERVATION_QUERY,
                                                                   self.captured[0].source_ledger))
        self.assertTrue(all(c.closed and (not c.stream or c.stream.closed) for c in self.sdk.clients))

    def test_streaming_history_and_two_results_reach_final_and_real_frontend_parser(self):
        for names in ((),(HISTORY,),(WATER,HISTORY)):
            with self.subTest(names=names):
                self.configure();result=self.send(names,True)
                self.assertTrue(result['successful_turn'],result)
                self.assertTrue(all(b['stream'] is True and b['max_tokens']==512 for b in self.sdk.bodies))
                self.assert_delivery_and_sources(names)
                payload=dict(config=self.config,frames=self.frames,request_id=self.last_body['request_id'],tools=len(names),requests=len(names)+1)
                bridge=Path(__file__).parents[2]/'management_web/tests/stream-browser-bridge.mjs'
                child=subprocess.run(['node',str(bridge)],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=15)
                self.assertEqual(child.returncode,0,child.stderr)

    def test_authorized_subsets_only_expose_allowed_tools_and_score_has_no_handler(self):
        for streaming in (False,True):
            for names in release.UNIFIED_TOOL_SETS:
                with self.subTest(streaming=streaming,tools=names):
                    self.configure();self.policy([*names,'score_current_water_quality'])
                    selected=(names[0],) if names else ()
                    result=self.send(selected,streaming)
                    self.assertTrue(result['successful_turn'],result)
                    sent=[d['function']['name'] for d in self.sdk.bodies[0].get('tools',[])]
                    self.assertEqual(sent,list(names))
                    self.assertNotIn('score_current_water_quality',self.backend.history_registry.registered_names())
                    if names!=(WATER,KNOWLEDGE):self.assertEqual(self.config['presets'][0]['streaming' if streaming else 'execution']['tools'],list(names))

    def test_revocation_rejects_old_confirmation_and_unauthorized_model_call(self):
        for streaming in (False,True):
            self.configure();stale=self.envelope(streaming);self.policy([WATER,HISTORY])
            response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),json=stale,headers=self.headers)
            self.assertEqual(response.get_json()['error_code'],'ASSISTANT_EXECUTION_PROFILE_CHANGED');self.assertFalse(self.sdk.bodies)
            result=self.send((KNOWLEDGE,),streaming)
            self.assertFalse(result.get('successful_turn',False));self.assertEqual(result['error_code'],
                'MODEL_TOOL_CALL_MALFORMED' if streaming else 'TOOL_NOT_ALLOWED')
            self.assertEqual(len(self.sdk.bodies),1)
            self.assertEqual(result['activity']['counts']['tools_executed'],0)

    def test_explicit_send_still_requires_exact_confirmation_and_revision_before_provider_io(self):
        for streaming in (False,True):
            for confirmation in (None,False,1,'true'):
                with self.subTest(streaming=streaming,confirmation=confirmation):
                    self.configure();body=self.envelope(streaming)
                    if confirmation is None:body.pop('confirm_network')
                    else:body['confirm_network']=confirmation
                    with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credentials before approval')):
                        response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),json=body,headers=self.headers)
                    self.assertEqual(response.get_json()['error_code'],'NETWORK_CONFIRMATION_REQUIRED')
                    self.assertFalse(self.sdk.bodies)
            self.configure();body=self.envelope(streaming);body['revision']='expired-ui-revision'
            with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credentials with stale revision')):
                response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),json=body,headers=self.headers)
            self.assertEqual(response.get_json()['error_code'],'ASSISTANT_EXECUTION_PROFILE_CHANGED')
            self.assertFalse(self.sdk.bodies)

    def test_three_sources_budget_rejects_third_call_without_fake_receipt_or_fourth_request(self):
        for streaming in (False,True):
            self.configure();result=self.send((WATER,HISTORY,KNOWLEDGE),streaming)
            self.assertFalse(result['successful_turn']);self.assertEqual(result['final_text'],'')
            self.assertEqual(result['error_code'],'TOOL_ROUND_LIMIT');self.assertEqual(len(self.sdk.bodies),3)
            self.assertEqual(result['activity']['counts']['tools_executed'],2)
            self.assertEqual(len(self.captured[0].source_ledger.entries),2)
            self.assertFalse(any(e.receipt.project_search_completed for e in self.captured[0].source_ledger.entries))

    def test_normal_and_streaming_same_round_multiple_calls_rejected_before_execution(self):
        for streaming in (False,True):
            self.configure()
            if streaming:
                from apps.ai_backend.tests.support import delta
                response=[chunk([delta(name=WATER,identifier='a',index=0),delta(name=HISTORY,identifier='b',index=1)]),chunk(finish='tool_calls')]
            else:
                response=sdk_tool(WATER,model=self.profile.model)
                response.choices[0].message.tool_calls+=sdk_tool(HISTORY,model=self.profile.model).choices[0].message.tool_calls
            result=self.send(streaming=streaming,plans=[response])
            self.assertFalse(result['successful_turn']);self.assertEqual(len(self.sdk.bodies),1)
            self.assertEqual(result['activity']['counts']['tools_executed'],0)

    def test_stream_stop_deadline_truncation_disconnect_trace_failure_never_commit(self):
        for error in ('USER_CANCELLED','TOTAL_TIMEOUT','STREAM_TRUNCATED','STREAM_INTERRUPTED','TRACE_WRITE_ERROR'):
            with self.subTest(error=error):
                self.configure();context=nullcontext()
                plans=self.plans((HISTORY,),True)
                if error=='STREAM_TRUNCATED':plans[-1]=final_chunks('半成品',finish='length')
                if error=='STREAM_INTERRUPTED':plans[-1]=[chunk(content='半成品')]
                if error in ('USER_CANCELLED','TOTAL_TIMEOUT'):
                    original_factory=self.backend.gateway_factory
                    clock=[1000.0]
                    def factory():
                        handle=self.web.handle(self.last_body)
                        self.sdk.on_close=lambda _:handle.cancel() if error=='USER_CANCELLED' else clock.__setitem__(0,1121.0)
                        return original_factory()
                    self.backend.gateway_factory=factory
                    if error=='TOTAL_TIMEOUT':context=patch('time.monotonic',side_effect=lambda:clock[0])
                if error=='TRACE_WRITE_ERROR':context=patch.object(self.backend.traces,'_append',side_effect=OSError('private trace text'))
                result=self.send(streaming=True,plans=plans,context=context)
                self.assertFalse(result.get('successful_turn',False));self.assertFalse(result.get('final_text'))
                self.assertEqual(result.get('error_code'),error)
                self.assertNotIn('private trace text',self.frames)

    def test_separate_transport_flags_rollback_other_presets_and_scope_mutation(self):
        for normal,streaming in ((False,False),(True,False),(False,True),(True,True)):
            self.configure(normal=normal,streaming=streaming)
            config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
            qwen,ollama=config['presets']
            self.assertEqual(HISTORY in qwen['execution']['tools'],normal)
            self.assertEqual(HISTORY in qwen['streaming']['tools'],streaming)
            self.assertNotIn(HISTORY,ollama['execution']['tools']);self.assertNotIn(HISTORY,ollama['streaming']['tools'])
        self.configure();old=self.backend._unified_config
        self.backend._unified_config=replace(old,normal_scope_json='{}',streaming_scope_json='{}')
        config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.assertFalse(config['presets'][0]['execution']['can_send']);self.assertFalse(config['presets'][0]['streaming']['can_send'])
        self.assertFalse(self.sdk.bodies)

    def test_trial_loader_cannot_accept_released_or_enabled_manifest(self):
        value=json.loads((Path(release.__file__).with_name('resources')/'assistant_unified_tools.json').read_text())
        for overrides in ({'status':'released'},{'enabled':True},{'qualification_id':'forged'}):
            with patch.object(Path,'read_bytes',return_value=json.dumps({**value,**overrides}).encode()),self.assertRaisesRegex(GatewayError,'INVALID_UNIFIED'):
                release.load_unified_tool_trials(normal=True)
