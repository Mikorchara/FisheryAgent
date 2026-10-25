"""Management HTTP/SSE -> formal Streaming Runtime -> Monitoring + Knowledge. Offline SDK."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from apps.ai_service.runtime.assistant import AssistantService,MULTI_ROUND_SYSTEM_INSTRUCTION
from apps.ai_service.runtime.sources import SourceRequirement,requirement_satisfied_by_ledger
from apps.ai_backend.assistant_events import AssistantEventChannel
from apps.ai_backend.execution import current_handle
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_service.service import ManagementAssistantService,PRESETS
from apps.ai_service.streaming import load_streaming_config,ManagementStreamingConfig
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
import apps.management_web.tests.test_assistant as fixture
import apps.ai_backend.tests.test_execution as execution_fixture
from apps.ai_backend.tests.test_assembler import chunk,delta
from apps.ai_backend.tests.support import tool_chunks,final_chunks

WATER='get_current_water_quality'
KNOWLEDGE='search_fishery_knowledge'
BLOCK=object()


def trial_config():
    # Exercise the actual CLI opt-in and publication, using only an offline SDK.
    return load_streaming_config(enable_trial=True)


class ManagementStreamingTests(unittest.TestCase):
    batch=fixture.ManagementAssistantTests.batch
    envelope=fixture.ManagementAssistantTests.envelope

    def setUp(self):
        fixture.ManagementAssistantTests.setUp(self)
        execution_fixture.ExecutionTests.setUp(self)  # Only Windows asyncio wake-up socket is allowed.
        self.clients,self.bodies,self.runtimes,self.controls,self.responses=[],[],[],[],[]
        self.service_handles=[];self.blocked=threading.Event();self.frames=[final_chunks()]
        self.addCleanup(self.finish_workers)

    def setup_stream(self,frames=None,*,config=None,names=(WATER,KNOWLEDGE),close_error=False):
        self.frames=[final_chunks()] if frames is None else frames
        owner=self
        class Stream:
            def __init__(self,items):self.items,self.closed=items,False
            def __aiter__(self):return self.events()
            async def events(self):
                for item in self.items:
                    if item is BLOCK:
                        owner.blocked.set();await asyncio.Event().wait()
                    if isinstance(item,Exception):raise item
                    item.model=PRESET_MODEL
                    yield item
                    await asyncio.sleep(0)
            async def close(self):
                self.closed=True
                if close_error:raise RuntimeError('fictional-private-cleanup')
        class Client:
            def __init__(self,index):
                self.index,self.closed,self.stream=index,False,None
                self.chat=NS(completions=NS(create=self.create))
            async def create(self,**body):
                owner.bodies.append(body)
                items=owner.frames(self.index,body) if callable(owner.frames) else owner.frames[self.index-1]
                self.stream=Stream(items);return self.stream
            async def close(self):self.closed=True
        def factory(runtime,remaining):
            self.runtimes.append(runtime)
            client=Client(len(self.clients)+1);self.clients.append(client);return client
        def gateway():
            self.service_handles.append(current_handle())
            from apps.ai_backend.sdk_resources import SDKResourceBudget
            return OpenAICompatibleAdapter(async_client_factory=factory,resource_budget=SDKResourceBudget())
        old=self.backend
        self.backend=ManagementAssistantService(self.monitoring,knowledge=old.knowledge,credentials=old.credentials,traces=old.traces,
            policy_directory=self.root/'policies',gateway_factory=gateway,
            streaming_config=config if config is not None else trial_config())
        policy=self.backend.policy_store.default_selections()
        policy['modes']['assistant']['selected_tools']=list(names);self.backend.policy_store.save(policy)
        self.ai=ManagementAssistant(self.backend)
        self.app=create_app(data_service=self.monitoring,ai=self.ai);self.client=self.app.test_client()
        self.config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.headers={'X-Management-AI':self.config['browser_token']}
        from apps.ai_service.runtime.assistant import assistant_profile
        PRESET_MODEL=assistant_profile(PRESETS[0]).model

    def send_stream(self,**changes):
        self.sent=self.envelope(**{'revision':self.config['presets'][0]['streaming']['revision'],**changes})
        self.controls.append(self.ai.handle(self.sent))
        response=self.client.post('/api/ai/messages/stream',headers=self.headers,json=self.sent,buffered=False)
        if response.mimetype!='text/event-stream':self.ai.handle(self.sent).cancel()
        self.responses.append(response);return response

    def rows(self,response):
        self.assertEqual(response.status_code,200)
        self.assertIn('text/event-stream',response.content_type)
        rows=[json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith('data: ')]
        self.assertEqual([r['seq'] for r in rows],list(range(1,len(rows)+1)))
        self.assertEqual(rows[0]['kind'],'start')
        self.assertTrue(all(r['request_id']==self.sent['request_id'] and r['epoch']==self.config['epoch'] for r in rows))
        self.assertEqual(sum(r['kind'] in ('final','error','cancelled') for r in rows),1)
        return rows

    def finish_workers(self):
        for response in self.responses:response.close()
        for handle in self.controls:handle.cancel()
        until=time.monotonic()+3
        while time.monotonic()<until and any(h._event_channel is not None for h in self.controls):time.sleep(.005)
        self.assertTrue(all(h._event_channel is None for h in self.controls),'worker still owns channel')

    def assert_final(self,rows,requests,tools):
        self.assertEqual(rows[-1]['kind'],'final');result=rows[-1]['result']
        self.assertTrue(result['successful_turn']);self.assertTrue(result['trace_recorded'])
        self.assertEqual(result['activity']['state'],'COMPLETED')
        self.assertEqual(result['transport'],'streaming');self.assertEqual(result['device_id'],'pond-a')
        self.assertEqual(result['usage']['request_count'],requests)
        self.assertEqual(result['activity']['counts']['tools_executed'],tools)
        self.assertEqual(len(self.bodies),requests)
        self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))
        self.assertTrue(all(b['max_tokens']==512 and b['stream'] for b in self.bodies))
        self.assertTrue(all(r is self.runtimes[0] for r in self.runtimes))
        self.assertEqual(self.runtimes[0].total_timeout_s,120);self.assertEqual(self.runtimes[0].max_retries,0)
        self.assertEqual(self.runtimes[0].default_response_mode,'normal')
        self.assertEqual(self.runtimes[0].transport_output_token_limit,512)
        self.assertIs(self.service_handles[0],self.ai.handle(self.sent))

    def assert_error(self,rows,code):
        self.assertEqual(rows[-1]['kind'],'cancelled' if code=='USER_CANCELLED' else 'error')
        result=rows[-1].get('result',{})
        self.assertEqual(result.get('error_code',rows[-1].get('error_code')),code)
        self.assertFalse(result.get('successful_turn',False));self.assertFalse(result.get('final_text'))
        self.assertIsNone(result.get('completed_at'))

    def test_direct_final_preview_commit_usage_and_actual_budget(self):
        self.setup_stream();rows=self.rows(self.send_stream());self.assert_final(rows,1,0)
        self.assertTrue(any(r['kind']=='preview' and r['provisional'] for r in rows))
        self.assertEqual(rows[-1]['result']['usage']['usage']['total_tokens'],5)
        self.assertEqual(self.bodies[0]['messages'][0]['content'],MULTI_ROUND_SYSTEM_INSTRUCTION)
        self.assertFalse(any(m['role']=='tool' for m in self.bodies[0]['messages']))
        self.assertEqual(rows[0]['max_output_tokens'],512)

    def test_real_http_fake_sdk_events_reach_browser_parser_and_commit_one_turn(self):
        """Actual formal Runtime -> SSE bytes -> actual frontend parser / workspace."""
        for count in (0,1,2):
            with self.subTest(tools=count):
                self.clients.clear();self.bodies.clear();self.runtimes.clear();self.service_handles.clear()
                self.batch(oxygen=2.2)
                frames=([tool_chunks()] if count else [])+(
                    [tool_chunks(KNOWLEDGE,'knowledge','{"query":"x"}')] if count==2 else [])+[final_chunks()]
                self.setup_stream(frames)
                response=self.send_stream()
                rows=self.rows(response);self.assert_final(rows,count+1,count)
                config={**self.config,'browser_token':'offline-browser-token'}
                payload={'config':config,'frames':response.get_data(as_text=True),
                    'request_id':self.sent['request_id'],'tools':count,'requests':count+1}
                bridge=Path(__file__).with_name('stream-browser-bridge.mjs')
                result=subprocess.run(['node',str(bridge)],input=json.dumps(payload),capture_output=True,
                    text=True,encoding='utf-8',timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue(json.loads(result.stdout)['completed'])

    def test_water_result_same_batch_and_device_enters_followup_after_cleanup(self):
        batch=self.batch(oxygen=2.2);self.batch('pond-b',oxygen=6.4)
        def decide(index,body):
            if index==1:return tool_chunks()
            self.assertTrue(self.clients[0].closed and self.clients[0].stream.closed)
            payload=json.loads(next(m['content'] for m in body['messages'] if m['role']=='tool'))
            self.assertEqual(payload['device_id'],'pond-a');self.assertEqual(payload['batch_id'],batch['batch_id'])
            self.assertEqual(payload['water_quality']['dissolved_oxygen_mg_l'],2.2)
            return final_chunks()
        self.setup_stream(decide)
        with patch.object(self.monitoring,'capture_water',wraps=self.monitoring.capture_water) as capture:
            rows=self.rows(self.send_stream())
        capture.assert_called_once_with('pond-a');self.assert_final(rows,2,1)
        steps=[s for r in rows if r['kind']=='activity' and r.get('activity') for s in r['activity']['steps'] if s['kind']=='tool']
        self.assertTrue(any(s['state']=='RUNNING' and s['handler_started'] for s in steps))
        self.assertTrue(any(s['state']=='COMPLETED' for s in steps))
        self.assertTrue(any(r['kind']=='preview_reset' for r in rows))

    def test_two_tools_decided_from_result_then_both_results_and_ledger_reach_final(self):
        self.batch(oxygen=2.2);captured=[];original=AssistantService.send
        def capture(service,*args):
            result=original(service,*args);captured.append(result);return result
        def decide(index,body):
            payloads=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
            if index==1:return tool_chunks()
            self.assertEqual(payloads[0]['water_quality']['dissolved_oxygen_mg_l'],2.2)
            if index==2:
                self.assertEqual(len(payloads),1)
                # Only this subsequent model response selects Knowledge, after seeing Water Result.
                return tool_chunks(KNOWLEDGE,'knowledge','{"query":"fictional-private-search"}')
            self.assertEqual(index,3);self.assertEqual(len(payloads),2)
            self.assertEqual(payloads[1]['status'],'NO_MATCH');self.assertEqual(body['tool_choice'],'none')
            return final_chunks()
        self.setup_stream(decide)
        with patch.object(self.backend.knowledge,'search',return_value=()),patch.object(AssistantService,'send',capture):
            rows=self.rows(self.send_stream())
        self.assert_final(rows,3,2);ledger=captured[0].source_ledger
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_OBSERVATION_QUERY,ledger))
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.PROJECT_KNOWLEDGE_SEARCH,ledger))
        self.assertFalse(ledger.entries[1].receipt.has_observation)
        self.assertEqual(rows[-1]['result']['usage']['usage']['total_tokens'],15)
        self.assertNotIn('fictional-private-search',json.dumps(rows))
        self.assertFalse(rows[-1]['result']['legacy_projection_available'])

    def test_no_data_is_successful_read_and_can_be_explained(self):
        self.setup_stream([tool_chunks(),final_chunks()])
        rows=self.rows(self.send_stream());self.assert_final(rows,2,1)
        payload=json.loads(next(m['content'] for m in self.bodies[1]['messages'] if m['role']=='tool'))
        self.assertEqual(payload['status'],'NO_DATA');self.assertIsNone(payload['water_quality'])

    def test_default_off_candidate_even_when_enabled_and_ollama_not_allowed(self):
        trial=trial_config()
        candidate=replace(trial,releases=tuple(replace(r,runtime=replace(r.runtime,status='candidate')) for r in trial.releases))
        for config in (load_streaming_config(),candidate):
            self.setup_stream(config=config)
            self.assertFalse(self.config['presets'][0]['streaming']['can_send'])
            self.assertEqual(self.send_stream().get_json()['error_code'],'ASSISTANT_STREAMING_NOT_RELEASED')
        self.setup_stream()
        p=self.config['presets'][1]
        self.assertFalse(p['streaming']['can_send'])
        self.assertEqual(self.send_stream(preset_id=PRESETS[1],revision=p['streaming']['revision']).get_json()['error_code'],'ASSISTANT_STREAMING_NOT_RELEASED')
        self.assertEqual(self.bodies,[])

    def test_trial_scope_policy_and_unapproved_presets_refuse_before_credentials(self):
        self.setup_stream()
        self.assertTrue(self.config['presets'][0]['streaming']['can_send'])
        self.assertEqual(self.config['presets'][0]['streaming']['release_status'],'local_experimental')
        self.assertEqual(self.config['presets'][0]['execution']['mode'],'SINGLE_ROUND')
        with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credentials')):
            response=self.send_stream(preset_id='deepseek-flash-r1')
        self.assertEqual(response.get_json()['error_code'],'ASSISTANT_PRESET_NOT_ALLOWED')
        for names in ((),(WATER,),(KNOWLEDGE,),('score_current_water_quality',)):
            self.setup_stream(names=names)
            before=self.backend.policy_store.effective()['assistant']
            self.assertFalse(self.config['presets'][0]['streaming']['can_send'])
            self.assertEqual(self.config['presets'][0]['streaming']['mode_reason'],'scope_not_published')
            with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credentials')):
                response=self.send_stream()
            self.assertEqual(response.get_json()['error_code'],'ASSISTANT_STREAMING_NOT_RELEASED')
            self.assertEqual(before,self.backend.policy_store.effective()['assistant'])
        self.assertEqual(self.bodies,[])

    def test_trial_rollback_rejects_old_epoch_and_fresh_stream_before_io(self):
        self.setup_stream();old=self.envelope(revision=self.config['presets'][0]['streaming']['revision'])
        self.setup_stream(config=load_streaming_config())
        with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credentials')):
            response=self.client.post('/api/ai/messages/stream',headers=self.headers,json=old)
            self.assertEqual(response.get_json()['error_code'],'ASSISTANT_SESSION_EXPIRED')
            self.assertEqual(self.send_stream().get_json()['error_code'],'ASSISTANT_STREAMING_NOT_RELEASED')
        self.assertEqual(self.config['presets'][0]['execution']['mode'],'SINGLE_ROUND')
        self.assertEqual(self.bodies,[])

    def test_scope_identity_protocol_prompt_history_tool_and_binding_mismatch_preflight(self):
        from apps.ai_service.streaming import ManagementStreamingRelease
        for field in ('identity','protocol_spec','prompt_sha256','history_version','tool_definitions_sha256','data_bindings'):
            config=trial_config();record=config.releases[0];scope=json.loads(record.runtime.scope_json)
            binding=json.loads(record.data_bindings_json)
            if field=='identity':scope[field][-1]+='-different'
            elif field=='protocol_spec':scope[field]['version']='different'
            elif field=='data_bindings':binding['water']='different'
            else:scope[field]='different'
            changed=ManagementStreamingRelease(replace(record.runtime,scope_json=json.dumps(scope)),json.dumps(binding))
            self.setup_stream(config=replace(config,releases=(changed,)))
            with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credentials')):
                self.assertEqual(self.send_stream().get_json()['error_code'],'ASSISTANT_STREAMING_NOT_RELEASED',field)
        self.assertEqual(self.bodies,[])

    def test_policy_revision_epoch_confirmation_and_browser_overrides_block_before_io(self):
        self.setup_stream()
        cases=[({'revision':self.config['presets'][0]['revision']},'ASSISTANT_EXECUTION_PROFILE_CHANGED'),
            ({'epoch':'old'},'ASSISTANT_SESSION_EXPIRED'),({'confirm_network':False},'NETWORK_CONFIRMATION_REQUIRED')]
        cases += [({field:1},'INVALID_ASSISTANT_REQUEST') for field in ('transport','mode','budget','deadline','max_output_tokens','source_requirement')]
        for changes,code in cases:
            self.assertEqual(self.send_stream(**changes).get_json()['error_code'],code)
        old=self.config['presets'][0]['streaming']['revision']
        policy=self.backend.policy_store.default_selections();self.backend.policy_store.save(policy)
        self.assertEqual(self.send_stream().get_json()['error_code'],'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        self.config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.assertNotEqual(old,self.config['presets'][0]['streaming']['revision'])
        self.assertEqual(self.send_stream().get_json()['error_code'],'ASSISTANT_STREAMING_NOT_RELEASED')
        self.assertEqual(self.bodies,[])

    def test_duplicate_while_running_does_not_spawn_or_cancel_original(self):
        self.setup_stream([[chunk(content='pending'),BLOCK]])
        response=self.send_stream();self.assertTrue(self.blocked.wait(2))
        duplicate=self.client.post('/api/ai/messages/stream',headers=self.headers,json=self.sent)
        self.assertEqual(duplicate.get_json()['error_code'],'REQUEST_ALREADY_EXECUTED')
        self.assertEqual(len(self.bodies),1);self.assertEqual(self.ai.handle(self.sent).state,'RUNNING')
        self.ai.handle(self.sent).cancel();self.assert_error(self.rows(response),'USER_CANCELLED')

    def test_stop_at_each_request_preserves_steps_without_success(self):
        for index in (1,2,3):
            self.clients.clear();self.bodies.clear();self.runtimes.clear();self.service_handles.clear();self.blocked.clear()
            frames=([tool_chunks()] if index>1 else [])+([tool_chunks(KNOWLEDGE,'k','{"query":"x"}')] if index>2 else [])+[[chunk(content='provisional'),BLOCK]]
            self.setup_stream(frames)
            with patch.object(self.backend.knowledge,'search',return_value=()):
                response=self.send_stream();self.assertTrue(self.blocked.wait(2))
                control={k:self.sent[k] for k in ('request_id','control_token')}
                self.client.post('/api/ai/cancel',headers=self.headers,json=control)
                rows=self.rows(response)
            self.assert_error(rows,'USER_CANCELLED');self.assertEqual(len(self.bodies),index)
            self.assertEqual(rows[-1]['result']['activity']['counts']['tools_executed'],index-1)
            self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))

    def test_disconnect_before_reading_cancels_io_no_followup(self):
        self.setup_stream([[chunk(content='provisional'),BLOCK]])
        response=self.send_stream();self.assertTrue(self.blocked.wait(2));response.close()
        self.finish_workers()
        handle=self.ai.handle(self.sent)
        self.assertEqual(handle.state,'CANCELLED');self.assertEqual(handle.error_code,'USER_CANCELLED')
        self.assertEqual(len(self.bodies),1);self.assertTrue(self.clients[0].closed)

    def test_truncation_broken_stream_and_cleanup_failure_never_execute_or_commit(self):
        for frames,code,cleanup in (([chunk(content='provisional',finish='length')],'STREAM_TRUNCATED',False),
            ([chunk(content='provisional')],'STREAM_INTERRUPTED',False),
            (tool_chunks(),'SDK_CLEANUP_FAILED',True)):
            self.clients.clear();self.bodies.clear()
            self.setup_stream([frames],close_error=cleanup)
            with patch.object(self.monitoring,'capture_water') as capture:
                rows=self.rows(self.send_stream())
            self.assert_error(rows,code);capture.assert_not_called();self.assertEqual(len(self.bodies),1)
            self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))

    def test_timeout_and_trace_failure_never_final(self):
        self.setup_stream([[chunk(content='pending'),BLOCK]])
        original=AssistantService.send
        def shorter(service,*args):
            service._turn_timeout_s=.04;return original(service,*args)
        with patch.object(AssistantService,'send',shorter):rows=self.rows(self.send_stream())
        self.assert_error(rows,'TOTAL_TIMEOUT');self.assertTrue(self.clients[0].closed)
        self.clients.clear();self.bodies.clear();self.setup_stream()
        with patch.object(self.backend.traces,'record_assistant',side_effect=OSError('fictional-private')):
            rows=self.rows(self.send_stream())
        self.assert_error(rows,'TRACE_WRITE_ERROR');self.assertNotIn('fictional-private',json.dumps(rows))

    def test_thread_start_and_event_overflow_finalize_handle_without_io(self):
        self.setup_stream()
        with patch('apps.management_web.streaming.threading.Thread.start',side_effect=RuntimeError('fictional-private')):
            response=self.send_stream()
        self.assertEqual(response.get_json()['error_code'],'AI_SERVICE_UNAVAILABLE')
        self.assertEqual(self.ai.handle(self.sent).state,'FAILED');self.assertEqual(self.bodies,[])
        with patch.object(AssistantEventChannel,'MAX_EVENTS',2):rows=self.rows(self.send_stream())
        self.assert_error(rows,'ASSISTANT_EVENT_LIMIT');self.assertEqual(self.bodies,[])

    def test_committed_before_disconnect_stays_completed_and_no_regeneration(self):
        self.setup_stream();ready,release=threading.Event(),threading.Event();emit=AssistantEventChannel.emit
        def pause(channel,kind,payload,**kwargs):
            if kind=='final':ready.set();release.wait(2)
            return emit(channel,kind,payload,**kwargs)
        with patch.object(AssistantEventChannel,'emit',pause):
            response=self.send_stream();self.assertTrue(ready.wait(2))
            response.close();self.assertEqual(self.ai.handle(self.sent).state,'COMPLETED');release.set()
            self.finish_workers()
        self.assertEqual(len(self.bodies),1)

    def test_secret_reasoning_arguments_results_and_traceback_never_event_fields(self):
        secret='fictional-management-test-value'
        self.setup_stream([[chunk(content='safe '+secret[:9]),chunk(content=secret[9:]+' end',reasoning='fictional-reasoning',finish='stop')]])
        rows=self.rows(self.send_stream());self.assert_final(rows,1,0)
        text=json.dumps(rows)+self.traces.read_text(encoding='utf-8')
        for private in (secret,secret[:9],'fictional-reasoning','arguments_json','Authorization','credential_ref','system_instruction'):
            self.assertNotIn(private,text)
        self.assertIn('[REDACTED]',text)

    def test_get_access_and_oversized_requests_are_rejected(self):
        self.setup_stream()
        self.assertEqual(self.client.get('/api/ai/messages/stream').status_code,405)
        body=self.envelope()
        for headers in ({},{**self.headers,'Origin':'http://untrusted.invalid'}):
            self.assertEqual(self.client.post('/api/ai/messages/stream',headers=headers,json=body).status_code,403)
        self.assertEqual(self.client.post('/api/ai/messages/stream',headers=self.headers,json=body,environ_overrides={'REMOTE_ADDR':'10.0.0.1'}).status_code,403)
        self.assertEqual(self.client.post('/api/ai/messages/stream',headers=self.headers,data='x'*33000,content_type='application/json').status_code,413)
        self.assertEqual(self.bodies,[])


    def test_budget_multiple_calls_and_bad_arguments_never_bypass_executor(self):
        self.setup_stream([tool_chunks(),tool_chunks(KNOWLEDGE,'k','{"query":"x"}'),tool_chunks(identifier='third')])
        with patch.object(self.backend.knowledge,'search',return_value=()):rows=self.rows(self.send_stream())
        self.assert_error(rows,'TOOL_ROUND_LIMIT');self.assertEqual(len(self.bodies),3)
        for frames in ([chunk([delta('{}',name=WATER,identifier='a',call_type='function'),
                               delta('{}',name=KNOWLEDGE,identifier='b',call_type='function',index=1)])],
                       tool_chunks(arguments='{"device_id":"fictional-private"}')):
            self.clients.clear();self.bodies.clear();self.setup_stream([frames])
            with patch.object(self.monitoring,'capture_water') as capture,patch.object(self.backend.knowledge,'search') as search:
                rows=self.rows(self.send_stream())
            self.assertEqual(rows[-1]['kind'],'error');capture.assert_not_called();search.assert_not_called()
            self.assertFalse(rows[-1]['result']['successful_turn']);self.assertEqual(len(self.bodies),1)

    def test_source_gate_unmet_cannot_commit_even_with_full_model_stream(self):
        from apps.ai_service.runtime.assistant import AssistantRequest
        original=AssistantRequest.from_dict
        def requirement(value):
            return replace(original(value),source_requirement=SourceRequirement.PROJECT_KNOWLEDGE_SEARCH)
        self.setup_stream()
        with patch.object(AssistantRequest,'from_dict',side_effect=requirement):rows=self.rows(self.send_stream())
        self.assert_error(rows,'ASSISTANT_SOURCE_REQUIREMENT_UNMET')

    def test_history_from_completed_stream_is_only_text_pair_in_next_normal_request(self):
        self.setup_stream();rows=self.rows(self.send_stream());self.assert_final(rows,1,0)
        first=rows[-1]['result'];normal=fixture.RecordingGateway(fixture.final('normal after streaming'))
        self.backend.gateway_factory=lambda:normal
        payload=self.envelope(history=[{'user':'previous question','assistant':first['final_text'],'completed_at':first['completed_at']}])
        result=self.client.post('/api/ai/messages',headers=self.headers,json=payload).get_json()['result']
        self.assertTrue(result['successful_turn']);self.assertEqual(result['transport'],'normal')
        self.assertEqual(result['history_turns_sent'],1)
        self.assertFalse(any(m.role=='tool' or m.tool_calls for m in normal.requests[0].messages))
        self.assertEqual(len(self.bodies),1)

    def test_disconnect_or_timeout_before_worker_prevents_credentials_and_model_io(self):
        for timeout in (False,True):
            self.setup_stream();pending=[];clock=[100.0]
            def deferred(**kwargs):return NS(start=lambda:pending.append(kwargs['target']))
            with patch('apps.ai_backend.execution.time.monotonic',side_effect=lambda:clock[0]), \
                 patch('apps.management_web.streaming.threading.Thread',side_effect=deferred):
                response=self.send_stream()
                self.assertEqual(len(pending),1)
                if timeout:clock[0]+=121
                else:response.close()
                with patch.object(self.backend.credentials,'resolve',side_effect=AssertionError('no credential access')):
                    pending[0]()
            handle=self.ai.handle(self.sent)
            self.assertEqual(handle.error_code,'TOTAL_TIMEOUT' if timeout else 'USER_CANCELLED')
            if timeout:self.assert_error(self.rows(response),'TOTAL_TIMEOUT')
            self.assertEqual(self.bodies,[]);self.assertIsNone(handle._event_channel)


    def test_budget_and_device_changes_invalidate_revision_and_config_is_not_reloaded(self):
        self.setup_stream();before=self.config['presets'][0]['streaming']['revision']
        other=self.client.get('/api/ai/bootstrap?device=pond-b').get_json()['presets'][0]['streaming']['revision']
        self.assertNotEqual(before,other)
        config=trial_config();record=config.releases[0]
        changed=replace(config,releases=(replace(record,runtime=replace(record.runtime,max_output_tokens=256)),))
        self.setup_stream(config=changed)
        # Different epoch already invalidates old confirmation; compare cost changes within one epoch too.
        from apps.ai_service.streaming import resolve_streaming
        profile,policy,current,registry=self.backend._configuration(PRESETS[0],'pond-a')
        selected=self.backend.policy_store.effective()['assistant']
        normal_budget=resolve_streaming(config,profile,selected,policy,registry,self.backend.knowledge,device_id='pond-a',epoch=self.backend.epoch)
        lower_budget=resolve_streaming(changed,profile,selected,policy,registry,self.backend.knowledge,device_id='pond-a',epoch=self.backend.epoch)
        self.assertNotEqual(normal_budget.profile.revision,lower_budget.profile.revision)
        with patch('apps.ai_service.service.load_streaming_config',side_effect=AssertionError('epoch frozen')):
            prepared=self.backend.prepare_turn({k:v for k,v in self.envelope(revision=lower_budget.profile.revision).items() if k not in ('request_id','control_token')},
                transport=lower_budget.model_transport)
        self.assertEqual(prepared.execution.max_output_tokens,256)

    def test_policy_changes_after_start_cannot_change_the_frozen_turn(self):
        self.batch(oxygen=2.2)
        def decide(index,body):
            if index==1:
                policy=self.backend.policy_store.default_selections();self.backend.policy_store.save(policy)
                self.client.get('/api/ai/bootstrap?device=pond-b')
                return tool_chunks()
            self.assertEqual([d['function']['name'] for d in body['tools']],[WATER,KNOWLEDGE])
            payload=json.loads(next(m['content'] for m in body['messages'] if m['role']=='tool'))
            self.assertEqual(payload['device_id'],'pond-a')
            if index==2:return tool_chunks(KNOWLEDGE,'knowledge','{"query":"x"}')
            return final_chunks()
        self.setup_stream(decide)
        with patch.object(self.backend.knowledge,'search',return_value=()):rows=self.rows(self.send_stream())
        self.assert_final(rows,3,2)


    def test_delivery_failure_after_commit_does_not_rewrite_completed_handle(self):
        self.setup_stream();emit=AssistantEventChannel.emit
        def fail_delivery(channel,kind,payload,**kwargs):
            if kind=='final':raise RuntimeError('fictional-private-delivery')
            return emit(channel,kind,payload,**kwargs)
        with patch.object(AssistantEventChannel,'emit',fail_delivery):rows=self.rows(self.send_stream())
        self.assert_error(rows,'AI_SERVICE_UNAVAILABLE')
        self.assertEqual(self.ai.handle(self.sent).state,'COMPLETED')
        self.assertEqual(len(self.bodies),1);self.assertNotIn('fictional-private-delivery',json.dumps(rows))
