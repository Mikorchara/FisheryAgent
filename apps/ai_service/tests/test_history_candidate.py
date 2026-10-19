"""Closed publication gate + offline admission stub over actual management HTTP."""

from apps.knowledge.tests.support import reference_knowledge
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.ai_backend.tests import test_execution as offline_guard
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final, tool_chunks, final_chunks
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_service import service as composition
from apps.ai_service.history_execution import HISTORY_PROFILE, HistoryCandidateConfig, load_history_config
from apps.ai_service.business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES, FORMAL_TOOL_NAMES, WATER_QUALITY_SCORE
from apps.ai_service.runtime import assistant, sources
from apps.ai_service.tests import test_water_history_tool as fixtures
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app

HISTORY=fixtures.HISTORY


class HistoryCandidateTests(unittest.TestCase):
    make_monitoring=fixtures.WaterHistoryToolTests.make_monitoring

    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temporary=TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name); self.now=datetime(2026,10,17,tzinfo=timezone.utc)
        self.monitoring_index=0
        self.configure('sparse')

    def configure(self,case,*,candidate=True,trial=False):
        self.monitoring=self.make_monitoring(case)
        self.profile=assistant.assistant_profile(assistant.ALLOWED_PRESET_IDS[0])
        self.sdk=FakeSDK([sdk_tool(HISTORY,arguments=fixtures.ARGS),sdk_final()],model=self.profile.model)
        self.backend=composition.ManagementAssistantService(self.monitoring,
            knowledge=reference_knowledge(),
            credentials=CredentialStore(process_env={self.profile.credential_ref:'fictional-history-http-key'}),
            traces=JsonlTraceSink(self.root/'trace.jsonl',tool_names=HISTORY_CANDIDATE_TOOL_NAMES),
            policy_directory=self.root/('policy-'+str(self.monitoring_index)),
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=self.sdk.factory),
            history_config=HistoryCandidateConfig(load_history_config().scope_json) if candidate else
                           load_history_config(enable_trial=trial))
        self.web=ManagementAssistant(self.backend)
        self.client=create_app(data_service=self.monitoring,ai=self.web).test_client()
        self.headers={'X-Management-AI':self.web.browser_token}

    def policy(self,names):
        current=self.client.get('/api/ai/tool-policy').get_json()
        return self.client.post('/api/ai/tool-policy',json={'epoch':current['epoch'],
            'revision':current['revision'],'selected_tools':names},headers=self.headers)

    def envelope(self,**overrides):
        config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        control=self.client.post('/api/ai/requests',json={'epoch':config['epoch']},headers=self.headers).get_json()
        return {'preset_id':self.profile.preset_id,'device_id':'pond-a','question':'隔离历史测试',
            'epoch':config['epoch'],'history':[],'confirm_network':True,
            'revision':config['history_query']['revision'],'action':'history_query',
            **control,**overrides}

    def admission(self):
        # Explicitly stub ONLY unpublished admission, never Scope/Policy/runtime.
        # Offline socket guard + injected FakeSDK prohibit real Provider transport.
        original=composition.resolve_history_candidate
        def permit(*args,**kwargs):
            decision=original(*args,**kwargs)
            return replace(decision,can_send=decision.profile.mode_reason=='HISTORY_CANDIDATE_NOT_RELEASED')
        return patch.object(composition,'resolve_history_candidate',side_effect=permit)

    def send(self,**overrides):
        return self.client.post('/api/ai/messages',json=self.envelope(**overrides),headers=self.headers)

    def test_default_publication_remains_closed_even_after_policy_opt_in(self):
        self.assertFalse(self.backend.management_policy.path.exists())
        self.assertEqual(self.send().get_json()['error_code'],'HISTORY_TOOL_NOT_AUTHORIZED')
        self.assertEqual(self.policy([*FORMAL_TOOL_NAMES,HISTORY]).status_code,200)
        self.assertEqual(self.send().get_json()['error_code'],'HISTORY_CANDIDATE_NOT_RELEASED')
        self.assertEqual(self.sdk.bodies,[])
        for status,enabled in (('released',False),('local_experimental',1),('candidate',True),('candidate',1)):
            with self.assertRaises(GatewayError):
                HistoryCandidateConfig(self.backend._history_config.scope_json,status,enabled)

    def test_http_history_final_status_matrix_and_sources(self):
        for case,status,reliable in (('no_data','NO_DATA',False),('sparse','PARTIAL',True),
                ('complete','OK',True),('unavailable','PARTIAL',False)):
            with self.subTest(case=case):
                self.configure(case); self.policy([HISTORY])
                results=[]; original=assistant.AssistantService.send
                def capture(service,*args,**kwargs):
                    result=original(service,*args,**kwargs);results.append(result);return result
                with self.admission(),patch.object(assistant.AssistantService,'send',capture):
                    response=self.send()
                result=response.get_json()['result']
                self.assertEqual(response.status_code,200,result)
                self.assertTrue(result['successful_turn']); self.assertEqual(len(self.sdk.bodies),2)
                self.assertEqual([d['function']['name'] for d in self.sdk.bodies[0]['tools']],[HISTORY])
                payload=json.loads(next(m['content'] for m in self.sdk.bodies[1]['messages'] if m['role']=='tool'))
                self.assertEqual((payload['status'],payload['device_id']),(status,'pond-a'))
                receipt=results[0].source_receipt
                self.assertTrue(receipt.history_query_completed)
                self.assertEqual(receipt.has_historical_observations,reliable)
                self.assertFalse(sources.requirement_satisfied(sources.SourceRequirement.CURRENT_OBSERVATION_QUERY,receipt))
                self.assertEqual(result['execution']['max_model_requests'],2)
                self.assertTrue(all(client.closed for client in self.sdk.clients))
                safe=json.dumps(result)
                self.assertNotIn('requested_range',safe)
                self.assertNotIn('representative',safe)

    def test_policy_http_access_cas_epoch_and_restart(self):
        self.assertEqual(self.client.post('/api/ai/tool-policy',json={}).status_code,403)
        self.assertEqual(self.client.get('/api/ai/tool-policy',environ_base={'REMOTE_ADDR':'10.0.0.1'}).status_code,403)
        self.assertEqual(self.client.get('/api/ai/tool-policy',headers={'Origin':'http://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/ai/tool-policy',headers={'Host':'evil.example'}).status_code,403)
        old=self.client.get('/api/ai/tool-policy').get_json()
        saved=self.policy([*FORMAL_TOOL_NAMES,HISTORY]);self.assertEqual(saved.status_code,200)
        for epoch,revision in ((old['epoch'],old['revision']),('old-epoch',saved.get_json()['revision'])):
            result=self.client.post('/api/ai/tool-policy',json={'epoch':epoch,'revision':revision,
                'selected_tools':[]},headers=self.headers)
            self.assertEqual(result.status_code,409)
        from apps.ai_service.management_policy import ManagementToolPolicyStore
        restarted=ManagementToolPolicyStore(self.backend.policy_store.directory,self.backend.policy_store)
        self.assertEqual(restarted.public()['revision'],saved.get_json()['revision'])

    def test_revocation_invalidates_confirmation_and_unclaimed_turn(self):
        self.policy([HISTORY])
        with self.admission():
            body=self.envelope()
            prepared=self.web._prepare(body)[0]
            self.policy([])
            self.assertEqual(self.client.post('/api/ai/messages',json=body,headers=self.headers).get_json()['error_code'],
                             'ASSISTANT_EXECUTION_PROFILE_CHANGED')
            with self.assertRaisesRegex(GatewayError,'ASSISTANT_EXECUTION_PROFILE_CHANGED'):
                self.backend.execute_turn(prepared,RequestHandle())
            self.assertEqual(self.send().get_json()['error_code'],'HISTORY_TOOL_NOT_AUTHORIZED')
        self.assertEqual(self.sdk.bodies,[])

    def test_claimed_turn_retains_frozen_policy_and_device(self):
        self.policy([HISTORY])
        with self.admission():
            value=self.envelope()
            prepared=self.web._prepare(value)[0]
            execute=self.backend.claim_turn(prepared,self.web.handle(value))
            self.policy([])
            self.backend.bootstrap('pond-b')
            result=execute()
        self.assertTrue(result['successful_turn'])
        payload=json.loads(next(m['content'] for m in self.sdk.bodies[1]['messages'] if m['role']=='tool'))
        self.assertEqual(payload['device_id'],'pond-a')
        self.assertNotIn(HISTORY,self.backend.management_policy.snapshot().selected_tools)

    def test_policy_opt_in_never_assembles_history_in_default_request(self):
        self.policy([*FORMAL_TOOL_NAMES,HISTORY])
        config=self.backend.bootstrap('pond-a')
        value=self.envelope();value.pop('action');value['revision']=config['presets'][0]['revision']
        with patch.object(self.monitoring,'query_water_history') as query:
            result=self.client.post('/api/ai/messages',json=value,headers=self.headers).get_json()['result']
        self.assertFalse(result['successful_turn']);query.assert_not_called()
        self.assertEqual([d['function']['name'] for d in self.sdk.bodies[0]['tools']],list(FORMAL_TOOL_NAMES))
        self.assertEqual(len(self.sdk.bodies),1)

    def test_strict_candidate_scope_and_regular_registry_isolation(self):
        self.policy([*FORMAL_TOOL_NAMES,HISTORY,WATER_QUALITY_SCORE])
        bootstrap=self.backend.bootstrap('pond-a')
        normal=bootstrap['presets'][0]
        self.assertNotEqual(normal['revision'],bootstrap['history_candidate']['revision'])
        self.assertEqual(bootstrap['tools'],list(FORMAL_TOOL_NAMES))
        self.assertEqual(self.backend.formal_registry.registered_names(),FORMAL_TOOL_NAMES)
        self.assertNotIn(WATER_QUALITY_SCORE,self.backend.history_registry.registered_names())
        _,_,_,registry=self.backend._configuration(self.profile.preset_id,'pond-b',execution_profile=HISTORY_PROFILE)
        self.assertEqual(registry.model_definitions(),self.backend.history_registry.model_definitions())
        self.assertIs(registry.lookup(FORMAL_TOOL_NAMES[1]),self.backend.formal_registry.lookup(FORMAL_TOOL_NAMES[1]))
        for preset,transport in ((composition.PRESETS[1],None),(composition.PRESETS[0],'streaming')):
            with self.admission():
                _,_,decision,_=self.backend._configuration(preset,'pond-a',execution_profile=HISTORY_PROFILE,
                    transport=ToolModelTransport.STREAMING if transport else ToolModelTransport.NORMAL)
                self.assertFalse(decision.can_send)
                body=self.envelope(preset_id=preset,revision=decision.profile.revision)
                if transport:
                    response=self.client.post('/api/ai/messages/stream',json=body,headers=self.headers)
                else:
                    response=self.client.post('/api/ai/messages',json=body,headers=self.headers)
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.get_json()['error_code'],'HISTORY_CANDIDATE_SCOPE_MISMATCH')
        changed=json.loads(self.backend._history_config.scope_json); changed['source_version']='unexpected@2'
        self.backend._history_config=HistoryCandidateConfig(json.dumps(changed))
        with self.admission():
            self.assertEqual(self.send().get_json()['error_code'],'HISTORY_CANDIDATE_SCOPE_MISMATCH')
        self.assertEqual(self.sdk.bodies,[])

    def test_management_opt_in_preserves_two_tool_scopes_and_six_http_paths(self):
        from apps.ai_service.execution import load_execution_config, management_scope
        from apps.ai_service.streaming import load_streaming_config
        self.backend._execution_config=load_execution_config(enable_trial=True)
        self.backend._streaming_config=load_streaming_config(enable_trial=True)
        self.policy(list(FORMAL_TOOL_NAMES))
        before=self.backend.bootstrap('pond-a')
        profile,policy,_,registry=self.backend._configuration(self.profile.preset_id,'pond-a')
        before_scope=management_scope(profile,policy,registry,self.backend.knowledge)
        self.policy([*FORMAL_TOOL_NAMES,HISTORY])
        after=self.backend.bootstrap('pond-a')
        profile,policy,_,registry=self.backend._configuration(self.profile.preset_id,'pond-a')
        self.assertEqual(management_scope(profile,policy,registry,self.backend.knowledge),before_scope)
        self.assertNotEqual(before['presets'][0]['revision'],after['presets'][0]['revision'])
        self.assertNotEqual(before['presets'][0]['streaming']['revision'],after['presets'][0]['streaming']['revision'])
        for streaming in (False,True):
            for calls in ((),(FORMAL_TOOL_NAMES[0],),FORMAL_TOOL_NAMES):
                with self.subTest(streaming=streaming,calls=calls):
                    plans=[]
                    for i,name in enumerate(calls):
                        args='{}' if i==0 else '{"query":"鳗鲡低氧表现"}'
                        plans.append(tool_chunks(name,identifier='call-'+str(i),arguments=args) if streaming else
                                     sdk_tool(name,identifier='call-'+str(i),arguments=args))
                    plans.append(final_chunks() if streaming else sdk_final())
                    self.sdk=FakeSDK(plans,model=self.profile.model)
                    body=self.envelope();body.pop('action')
                    entry=after['presets'][0]
                    body['revision']=entry['streaming']['revision'] if streaming else entry['revision']
                    response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),
                        json=body,headers=self.headers)
                    if streaming:
                        frames=[json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith('data: ')]
                        result=next(frame['result'] for frame in frames if frame['kind']=='final')
                    else:
                        result=response.get_json()['result']
                    self.assertTrue(result['successful_turn'])
                    self.assertEqual(len(self.sdk.bodies),len(calls)+1)
                    self.assertEqual([s['tool_name'] for s in result['activity']['steps'] if s['kind']=='tool'],list(calls))
                    self.assertTrue(all(client.closed for client in self.sdk.clients))

    def test_invalid_args_no_handler_no_followup_and_unmet_source_gate(self):
        self.policy([HISTORY])
        for arguments in ('{}','{"lookback_minutes":true}','{"lookback_minutes":10,"device_id":"pond-b"}'):
            self.sdk=FakeSDK([sdk_tool(HISTORY,arguments=arguments)],model=self.profile.model)
            with self.admission(),patch.object(self.monitoring,'query_water_history') as query:
                result=self.send().get_json()['result']
            query.assert_not_called()
            self.assertFalse(result['successful_turn']); self.assertEqual(result['error_code'],'INVALID_TOOL_ARGUMENTS')
            self.assertEqual(len(self.sdk.bodies),1)
        self.sdk=FakeSDK([sdk_final('文字声称已查询历史')],model=self.profile.model)
        with self.admission(): result=self.send().get_json()['result']
        self.assertEqual(result['error_code'],'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
        self.assertFalse(result['successful_turn']);self.assertEqual(result['final_text'],'')

    def test_cancel_timeout_and_trace_failure_do_not_commit(self):
        self.policy([HISTORY])
        for error in ('USER_CANCELLED','TOTAL_TIMEOUT','TRACE_WRITE_ERROR'):
            self.sdk=FakeSDK([sdk_tool(HISTORY,arguments=fixtures.ARGS),sdk_final()],model=self.profile.model)
            with self.admission():
                body=self.envelope();handle=self.web.handle(body)
                if error=='USER_CANCELLED':
                    self.sdk.on_close=lambda _:handle.cancel()
                    context=patch.object(self.backend.credentials,'resolve',wraps=self.backend.credentials.resolve)
                elif error=='TOTAL_TIMEOUT':
                    clock=[1000.0]
                    self.sdk.on_close=lambda _:clock.__setitem__(0,1121.0)
                    context=patch('time.monotonic',side_effect=lambda:clock[0])
                else:
                    context=patch.object(self.backend.traces,'_append',side_effect=OSError('private trace detail'))
                with context:
                    response=self.client.post('/api/ai/messages',json=body,headers=self.headers)
            data=response.get_json()
            self.assertFalse(data.get('result',{}).get('successful_turn',False),data)
            self.assertEqual(data.get('result',{}).get('final_text',''),'')
            self.assertNotIn('private trace detail',json.dumps(data))
            self.assertEqual(data.get('result',data)['error_code'],error,data)

    def test_real_trial_admission_http_status_matrix_product_budget_and_source(self):
        for case,status,positive in (('complete','OK',True),('no_data','NO_DATA',False),
                                    ('sparse','PARTIAL',True),('unavailable','PARTIAL',False)):
            with self.subTest(case=case):
                self.configure(case,candidate=False,trial=True); self.policy([*FORMAL_TOOL_NAMES,HISTORY])
                public=self.backend.bootstrap('pond-a')['history_candidate']
                self.assertEqual(public['release_status'],'local_experimental')
                self.assertTrue(public['enabled']);self.assertTrue(public['can_send'])
                self.assertEqual(public['max_output_tokens'],1024)
                results=[]; original=assistant.AssistantService.send
                def capture(service,*args,**kwargs):
                    result=original(service,*args,**kwargs);results.append(result);return result
                with patch.object(assistant.AssistantService,'send',capture):
                    response=self.send()
                result=response.get_json()['result']
                self.assertTrue(result['successful_turn'],result)
                self.assertEqual(len(self.sdk.bodies),2)
                for body in self.sdk.bodies:
                    self.assertEqual(body['max_tokens'],1024);self.assertNotIn('stream',body)
                    self.assertEqual([d['function']['name'] for d in body['tools']],[HISTORY])
                    self.assertFalse(body['extra_body']['enable_thinking'])
                payload=json.loads(next(m['content'] for m in self.sdk.bodies[1]['messages'] if m['role']=='tool'))
                self.assertEqual((payload['status'],payload['device_id']),(status,'pond-a'))
                receipt=results[0].source_receipt
                self.assertTrue(receipt.history_query_completed)
                self.assertEqual(receipt.has_historical_observations,positive)
                self.assertFalse(sources.requirement_satisfied(sources.SourceRequirement.CURRENT_OBSERVATION_QUERY,receipt))
                self.assertTrue(result['trace_recorded']);self.assertTrue(all(c.closed for c in self.sdk.clients))
                self.assertEqual(result['execution']['max_model_requests'],2)

    def test_trial_default_off_opt_in_revocation_confirmation_and_profile_isolation(self):
        self.configure('sparse',candidate=False)
        self.assertEqual(self.send().get_json()['error_code'],'HISTORY_TOOL_NOT_AUTHORIZED')
        self.policy([HISTORY]);old=self.envelope()
        self.assertEqual(self.send().get_json()['error_code'],'HISTORY_TRIAL_DISABLED')
        self.assertFalse(self.sdk.bodies)
        self.backend._history_config=load_history_config(enable_trial=True)
        self.assertEqual(self.client.post('/api/ai/messages',json=old,headers=self.headers).get_json()['error_code'],
                         'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        prepared_body=self.envelope()
        prepared=self.web._prepare(prepared_body)[0]
        self.policy([])
        with self.assertRaisesRegex(GatewayError,'ASSISTANT_EXECUTION_PROFILE_CHANGED'):
            self.backend.execute_turn(prepared,RequestHandle())
        self.assertEqual(self.send().get_json()['error_code'],'HISTORY_TOOL_NOT_AUTHORIZED')
        self.assertFalse(self.sdk.bodies)
        self.policy([HISTORY])
        for preset,transport in ((composition.PRESETS[1],ToolModelTransport.NORMAL),
                                 (composition.PRESETS[0],ToolModelTransport.STREAMING)):
            _,_,decision,_=self.backend._configuration(preset,'pond-a',execution_profile=HISTORY_PROFILE,transport=transport)
            body=self.envelope(preset_id=preset,revision=decision.profile.revision)
            path='/api/ai/messages'+('/stream' if transport==ToolModelTransport.STREAMING else '')
            self.assertEqual(self.client.post(path,json=body,headers=self.headers).get_json()['error_code'],
                             'HISTORY_CANDIDATE_SCOPE_MISMATCH')
        self.assertFalse(self.sdk.bodies)

    def test_trial_scope_tamper_extra_web_controls_and_wrong_tool_rejected(self):
        self.configure('sparse',candidate=False,trial=True);self.policy([*FORMAL_TOOL_NAMES,HISTORY])
        original=self.backend._history_config
        for key in ('data_binding','source_version','budget','runtime'):
            scope=json.loads(original.scope_json);scope[key]='mismatch'
            self.backend._history_config=replace(original,scope_json=json.dumps(scope))
            self.assertEqual(self.send().get_json()['error_code'],'HISTORY_CANDIDATE_SCOPE_MISMATCH')
        self.backend._history_config=original
        for key in ('max_output_tokens','mode','budget','source_requirement'):
            self.assertEqual(self.send(**{key:1024}).get_json()['error_code'],'INVALID_ASSISTANT_REQUEST')
        self.assertFalse(self.sdk.bodies)
        # Each rejected browser submission owns an unclaimed control handle;
        # use a fresh page/registry for the separate unauthorized-call case.
        self.configure('sparse',candidate=False,trial=True);self.policy([*FORMAL_TOOL_NAMES,HISTORY])
        self.sdk=FakeSDK([sdk_tool(FORMAL_TOOL_NAMES[0])],model=self.profile.model)
        result=self.send().get_json()['result']
        self.assertFalse(result['successful_turn'])
        self.assertEqual(result['error_code'],'TOOL_NOT_ALLOWED')
        self.assertEqual(len(self.sdk.bodies),1)
        self.assertEqual(result['final_text'],'')

    def test_trial_stop_deadline_provider_truncation_trace_and_replay_never_commit(self):
        for error in ('USER_CANCELLED','USER_CANCELLED_2','TOTAL_TIMEOUT','TRACE_WRITE_ERROR','PROVIDER','PROVIDER_2','TRUNCATED'):
            self.configure('sparse',candidate=False,trial=True);self.policy([HISTORY])
            body=self.envelope();handle=self.web.handle(body)
            if error.startswith('USER_CANCELLED'):
                target=1 if error.endswith('_2') else 0
                self.sdk.on_close=lambda index:handle.cancel() if index==target else None
                context=patch.object(self.monitoring,'query_water_history',wraps=self.monitoring.query_water_history)
            elif error=='TOTAL_TIMEOUT':
                clock=[1000.0];self.sdk.on_close=lambda _:clock.__setitem__(0,1121.0)
                context=patch('time.monotonic',side_effect=lambda:clock[0])
            elif error=='TRACE_WRITE_ERROR':
                context=patch.object(self.backend.traces,'_append',side_effect=OSError('private trace detail'))
            elif error.startswith('PROVIDER'):
                plans=([sdk_tool(HISTORY,arguments=fixtures.ARGS)] if error.endswith('_2') else [])
                self.sdk=FakeSDK([*plans,RuntimeError('private provider detail')],model=self.profile.model)
                context=patch.object(self.monitoring,'query_water_history',wraps=self.monitoring.query_water_history)
            else:
                self.sdk=FakeSDK([sdk_tool(HISTORY,arguments=fixtures.ARGS),sdk_final('incomplete',finish='length')],model=self.profile.model)
                context=patch.object(self.monitoring,'query_water_history',wraps=self.monitoring.query_water_history)
            with context:
                data=self.client.post('/api/ai/messages',json=body,headers=self.headers).get_json()
            self.assertFalse(data.get('result',{}).get('successful_turn',False),data)
            self.assertEqual(data.get('result',{}).get('final_text',''),'')
            self.assertNotIn('private ',json.dumps(data));self.assertNotIn('incomplete',json.dumps(data))
        self.configure('sparse',candidate=False,trial=True);self.policy([HISTORY]);body=self.envelope()
        first=self.client.post('/api/ai/messages',json=body,headers=self.headers).get_json()['result']
        self.assertTrue(first['successful_turn'])
        self.assertEqual(self.client.post('/api/ai/messages',json=body,headers=self.headers).get_json()['error_code'],
                         'REQUEST_ALREADY_EXECUTED')
        self.assertEqual(len(self.sdk.bodies),2)

    def test_trial_claim_freezes_device_and_policy_and_restart_rolls_back(self):
        self.configure('sparse',candidate=False,trial=True);self.policy([HISTORY])
        body=self.envelope()
        prepared=self.web._prepare(body)[0]
        execute=self.backend.claim_turn(prepared,self.web.handle(body))
        self.policy([]);self.backend.bootstrap('pond-b')
        result=execute();self.assertTrue(result['successful_turn'])
        payload=json.loads(next(m['content'] for m in self.sdk.bodies[1]['messages'] if m['role']=='tool'))
        self.assertEqual(payload['device_id'],'pond-a')
        old_epoch=self.backend.epoch
        self.configure('sparse',candidate=False);self.policy([HISTORY])
        self.assertNotEqual(self.backend.epoch,old_epoch)
        self.assertEqual(self.send(epoch=old_epoch).get_json()['error_code'],'ASSISTANT_SESSION_EXPIRED')
        self.assertEqual(self.send().get_json()['error_code'],'HISTORY_TRIAL_DISABLED')
        self.assertFalse(self.sdk.bodies)
