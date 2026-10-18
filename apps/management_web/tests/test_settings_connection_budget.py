"""R2D-4B: real HTTP/SDK encoding with isolated files and fictional keys only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
import json
import logging
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

import httpx
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError, InternalServerError
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tests.support import FakeSDK, sdk_final
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_service import output_budget
from apps.ai_service.settings_store import PreferencesStore
from apps.management_web.tests import test_settings as fixture


class ConnectionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ManagementSettingsTests('runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.client,self.service,self.backend=self.f.client,self.f.service,self.f.f.backend
        self.headers=self.f.headers

    def probe(self,secret='fictional-tested-key',provider='dashscope',source='input',**changes):
        current=self.service.credential_status(provider)
        body={'epoch':self.backend.epoch,'provider':provider,'source':source,
            'secret':secret if source=='input' else None,
            'revision':current['revision' if source=='input' else 'credential_revision'],'confirm_network':True,**changes}
        return self.client.post('/api/settings/credentials/test',headers=self.headers,json=body)

    def save(self,proof,secret='fictional-tested-key',provider='dashscope',**changes):
        return self.client.post('/api/settings/credentials',headers=self.headers,json={
            'epoch':self.backend.epoch,'provider':provider,'action':'save','revision':self.service.credential_status(provider)['revision'],
            'secret':secret,'confirm_clear':False,'test_token':proof,**changes})

    def budget(self,value,transport='normal',action='save',current=None,**changes):
        current=current or self.f.read()
        return self.client.post('/api/settings/budgets',headers=self.headers,json={
            'epoch':current['epoch'],'revision':current['revision'],'preset_id':output_budget.PRESET,
            'transport':transport,'action':action,'max_output_tokens':value,**changes})

    def test_new_key_test_is_one_bounded_request_no_write_and_save_is_bound(self):
        path=self.backend.credentials.project_env_path
        proof=self.probe().get_json()['test'];self.assertTrue(proof['success'],proof)
        self.assertEqual(proof['request_count'],1)
        self.assertFalse(path.exists())
        body=self.f.probe_sdk.bodies[-1]
        self.assertEqual(body['max_tokens'],8);self.assertNotIn('tools',body);self.assertNotIn('stream',body)
        self.assertTrue(all(c.closed for c in self.f.probe_sdk.clients))
        self.assertEqual(self.save(proof['test_token'],secret='fictional-changed-key').get_json()['error_code'],'CREDENTIAL_TEST_REQUIRED')
        self.assertFalse(path.exists())
        self.assertEqual(self.save(None).get_json()['error_code'],'CREDENTIAL_TEST_REQUIRED')
        proof=self.probe().get_json()['test']['test_token']
        self.assertEqual(self.save(proof,provider='deepseek').get_json()['error_code'],'CREDENTIAL_TEST_REQUIRED')
        self.assertFalse(path.exists())
        proof=self.probe().get_json()['test']['test_token']
        self.assertEqual(self.save(proof).status_code,200)
        self.assertEqual(self.save(proof).get_json()['error_code'],'CREDENTIAL_TEST_REQUIRED')

    def test_auth_timeout_network_rate_limit_provider_failure_never_overwrite_or_leak(self):
        self.f.change();before=self.backend.credentials.project_env_path.read_bytes()
        request=httpx.Request('POST','https://example.invalid')
        def status(cls,code):return cls('fictional-private-key-in-error',response=httpx.Response(code,request=request),body={})
        cases=[(status(AuthenticationError,401),'AUTHENTICATION_FAILED'),(APITimeoutError(request),'TIMEOUT'),
            (APIConnectionError(message='fictional-private-key-in-error',request=request),'NETWORK_ERROR'),
            (status(RateLimitError,429),'RATE_LIMITED'),(status(InternalServerError,503),'PROVIDER_ERROR')]
        logs=io.StringIO();handler=logging.StreamHandler(logs);logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler,handler)
        for error,expected in cases:
            with self.subTest(expected=expected):
                sdk=FakeSDK([error],model=self.f.f.profile.model)
                self.service.connection_tests.gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=sdk.factory)
                result=self.probe().get_json()['test']
                self.assertFalse(result['success']);self.assertEqual(result['code'],expected)
                self.assertEqual(result['request_count'],1);self.assertEqual(len(sdk.bodies),1)
                self.assertTrue(sdk.clients[0].closed)
                self.assertEqual(before,self.backend.credentials.project_env_path.read_bytes())
                self.assertNotIn('fictional-private-key-in-error',json.dumps(result)+logs.getvalue())

    def test_saved_key_and_process_env_are_read_only_and_do_not_enable_new_key_save(self):
        self.backend.credentials._process_env[self.f.ref]='fictional-process-key'
        observed=[];sdk=FakeSDK([sdk_final(model=self.f.f.profile.model)],model=self.f.f.profile.model)
        def factory(runtime,remaining):
            observed.append((runtime.credential._for_adapter(),runtime.max_retries,runtime.total_timeout_s))
            return sdk.factory(runtime,remaining)
        self.service.connection_tests.gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=factory)
        self.assertEqual(self.probe().get_json()['error_code'],'CREDENTIAL_READ_ONLY')
        result=self.probe(source='saved').get_json()['test']
        self.assertTrue(result['success'],result);self.assertNotIn('test_token',result)
        self.assertEqual(observed,[('fictional-process-key',0,20)])
        self.assertFalse(self.backend.credentials.project_env_path.exists())
        self.assertNotIn('fictional-process-key',json.dumps(self.f.read()))

    def test_both_cloud_providers_use_the_input_key_then_saved_private_snapshot(self):
        observed=[]
        sdk=FakeSDK(lambda _i,body:sdk_final(model=body['model']))
        def factory(runtime,remaining):
            observed.append((runtime.service_id,runtime.credential._for_adapter()))
            return sdk.factory(runtime,remaining)
        self.service.connection_tests.gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=factory)
        for provider in ('dashscope','deepseek'):
            secret='fictional-'+provider+'-key'
            result=self.probe(secret=secret,provider=provider).get_json()['test']
            self.assertTrue(result['success'],result)
            self.assertEqual(self.save(result['test_token'],secret,provider).status_code,200)
            before=self.backend.credentials.project_env_path.read_bytes()
            result=self.probe(provider=provider,source='saved').get_json()['test']
            self.assertTrue(result['success'],result);self.assertNotIn('test_token',result)
            self.assertEqual(before,self.backend.credentials.project_env_path.read_bytes())
            self.assertEqual(observed[-1][1],secret)
        self.assertEqual([row[0] for row in observed],['dashscope','dashscope','deepseek_api','deepseek_api'])
        self.assertTrue(all(body['max_tokens']==8 for body in sdk.bodies))

    def test_stale_receipt_expiry_concurrent_save_and_explicit_network_gate(self):
        self.assertEqual(self.probe(confirm_network=False).get_json()['error_code'],'INVALID_CREDENTIAL_TEST')
        for secret in ('','line\nkey','fictional-\ud800-key','x'*4097):
            self.assertEqual(self.probe(secret=secret).get_json()['error_code'],'INVALID_CREDENTIAL_VALUE')
        token=self.probe().get_json()['test']['test_token']
        with self.service.connection_tests._lock:
            self.service.connection_tests._receipts[token]['expires']=0
        self.assertEqual(self.save(token).get_json()['error_code'],'CREDENTIAL_TEST_REQUIRED')
        first=self.probe().get_json()['test']['test_token']
        second=self.probe().get_json()['test']['test_token']
        revision=self.service.credential_status('dashscope')['revision']
        self.assertEqual(self.save(first).status_code,200)
        self.assertEqual(self.save(second,revision=revision).get_json()['error_code'],'ENV_REVISION_CONFLICT')
        token=self.probe().get_json()['test']['test_token'];revision=self.service.credential_status('dashscope')['revision']
        value={'epoch':self.backend.epoch,'provider':'dashscope','action':'save','revision':revision,
            'secret':'fictional-tested-key','confirm_clear':False,'test_token':token}
        def write(_):
            try:self.service.change_credential(value);return 'ok'
            except Exception as e:return e.code
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(write,range(2)))
        self.assertEqual(results.count('ok'),1);self.assertEqual(results.count('CREDENTIAL_TEST_REQUIRED'),1)

    def test_probe_concurrency_and_revision_change_during_network(self):
        entered=threading.Event();release=threading.Event()
        original=self.f.probe_sdk.factory
        def factory(runtime,remaining):
            entered.set();release.wait(2);return original(runtime,remaining)
        self.service.connection_tests.gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=factory)
        status=self.service.credential_status('dashscope')
        value={'epoch':self.backend.epoch,'provider':'dashscope','source':'input','secret':'fictional-tested-key',
            'revision':status['revision'],'confirm_network':True}
        with ThreadPoolExecutor(1) as pool:
            pending=pool.submit(self.service.connection_tests.run,value)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.probe().get_json()['error_code'],'CREDENTIAL_TEST_BUSY')
            # A different authorized writer changes the file during the test.
            self.service.writer.mutate(self.f.ref,self.f.f.profile.auth_spec,action='create',
                expected_revision=status['revision'],secret='fictional-concurrent-key')
            release.set()
            with self.assertRaisesRegex(Exception,'CREDENTIAL_TEST_STALE'):pending.result(3)

    def test_qwen_budget_recommendations_custom_integers_and_isolated_modes(self):
        self.assertEqual(self.service.store.document()['budget_revision'],0)
        for value in (512,1024,2048,4096,1537,1):
            self.assertEqual(self.budget(value).status_code,200)
            current=self.f.read()['models'][0]['modes']
            self.assertEqual(current['normal']['max_output_tokens'],value)
            self.assertEqual(current['streaming']['max_output_tokens'],512)
        self.assertEqual(self.budget(3073,'streaming').status_code,200)
        self.assertEqual(PreferencesStore(self.service.store.path).document()['output_budgets'][output_budget.key(output_budget.PRESET,'streaming')],3073)
        for value in (True,False,0,-1,4097,512.0,'512',None,[],{}):
            with self.subTest(value=value):
                self.assertEqual(self.budget(value).status_code,409)
        self.assertEqual(self.budget(2048,preset_id='ollama-qwen35-4b-r1').status_code,409)
        self.assertEqual(self.budget(2048,transport='unknown').status_code,409)
        self.assertEqual(self.budget(None,action='reset').get_json()['models'][0]['modes']['normal']['max_output_tokens'],1024)
        self.assertEqual(self.budget(None,'streaming',action='reset').get_json()['models'][0]['modes']['streaming']['max_output_tokens'],512)

    def send(self,names=(),streaming=False):
        self.f.f.sdk=FakeSDK(self.f.f.plans(names,streaming),model=self.f.f.profile.model)
        envelope=self.f.f.envelope(streaming)
        response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),json=envelope,headers=self.headers)
        if streaming:
            raw_frames=response.get_data(as_text=True)
            frames=[json.loads(line[6:]) for line in raw_frames.splitlines() if line.startswith('data: ')]
            result=frames[-1].get('result',frames[-1])
            child=subprocess.run(['node',str(Path(__file__).with_name('stream-browser-bridge.mjs'))],
                input=json.dumps({'config':self.f.f.config,'frames':raw_frames,'request_id':envelope['request_id'],
                    'tools':len(names),'requests':len(names)+1}),text=True,encoding='utf-8',capture_output=True,timeout=15)
            self.assertEqual(child.returncode,0,child.stderr)
        else:result=response.get_json().get('result',response.get_json())
        response.close();return result

    def test_real_normal_streaming_encoding_single_double_tools_and_commit(self):
        self.f.change()
        for streaming,value in ((False,1537),(False,2048),(True,4096)):
            self.assertEqual(self.budget(value,'streaming' if streaming else 'normal').status_code,200)
            for names in ((),('get_water_quality_history',),('get_current_water_quality','get_water_quality_history')):
                with self.subTest(streaming=streaming,names=names):
                    result=self.send(names,streaming)
                    self.assertTrue(result['successful_turn'],result)
                    self.assertEqual(len(self.f.f.sdk.bodies),len(names)+1)
                    self.assertTrue(all(b['max_tokens']==value for b in self.f.f.sdk.bodies))
                    self.assertTrue(all(c.closed and (not c.stream or c.stream.closed) for c in self.f.f.sdk.clients))

    def test_scope_revision_stale_confirmation_and_prepared_vs_running_budget(self):
        self.f.change()
        old=self.f.f.envelope();self.assertEqual(self.budget(2048).status_code,200)
        failed=self.client.post('/api/ai/messages',headers=self.headers,json=old).get_json()
        self.assertEqual(failed['error_code'],'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        body=self.f.f.envelope();prepared=self.backend.prepare_turn({k:v for k,v in body.items() if k not in ('request_id','control_token')})
        self.assertEqual(self.budget(3072).status_code,200)
        with self.assertRaisesRegex(Exception,'ASSISTANT_EXECUTION_PROFILE_CHANGED'):
            self.backend.claim_turn(prepared,self.f.f.web.handle(body))
        self.budget(2048)
        def update(index):
            if index==0:self.assertEqual(self.budget(4096).status_code,200)
        self.f.f.sdk=FakeSDK(self.f.f.plans(('get_current_water_quality','get_water_quality_history')),model=self.f.f.profile.model,on_close=update)
        result=self.client.post('/api/ai/messages',headers=self.headers,json=self.f.f.envelope()).get_json()['result']
        self.assertTrue(result['successful_turn'],result)
        self.assertTrue(all(b['max_tokens']==2048 for b in self.f.f.sdk.bodies))
        self.assertEqual(self.f.read()['models'][0]['modes']['normal']['max_output_tokens'],4096)

    def test_disabled_trial_scope_and_legacy_adapter_limits_cannot_be_bypassed(self):
        self.backend._unified_config=replace(self.backend._unified_config,normal_enabled=False,streaming_enabled=False)
        self.backend._streaming_config=replace(self.backend._streaming_config,enabled=False)
        self.assertEqual(self.budget(4096,'streaming').get_json()['error_code'],'SETTINGS_MODE_UNAVAILABLE')
        profile=self.f.f.profile
        from apps.ai_backend.model_gateway import ModelRequest,ModelMessage,ProfileRegistry
        from apps.ai_backend.contracts import Mode
        runtime=ProfileRegistry([profile],self.backend.credentials).snapshot(profile.profile_id,environ={profile.credential_ref:'fictional-key'})
        adapter=OpenAICompatibleAdapter()
        request=ModelRequest(Mode.CHAT,(ModelMessage('user','offline'),))
        for limit in (1025,4096):
            with self.assertRaisesRegex(Exception,'INVALID_NORMAL_OUTPUT_BUDGET'):
                adapter._kwargs(request,replace(runtime,transport_output_token_limit=limit),stream=False)
        with self.assertRaisesRegex(Exception,'INVALID_STREAMING_OUTPUT_BUDGET'):
            adapter._kwargs(request,replace(runtime,transport_output_token_limit=513),stream=True,_assemble_tools=True)
        for ceiling in (True,4097,0):
            with self.assertRaisesRegex(Exception,'INVALID_TRANSPORT_OUTPUT_CEILING'):
                adapter._kwargs(request,replace(runtime,transport_output_token_limit=512,transport_output_token_ceiling=ceiling),stream=False)
