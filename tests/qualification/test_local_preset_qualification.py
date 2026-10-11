"""Qualification safety tests: fake transport only, no local/cloud API calls."""

import importlib.util
import json
from pathlib import Path
import unittest
from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from tempfile import TemporaryDirectory

import tests.security.test_execution as test_execution
from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.credentials import CredentialStore
from fishery_ai.manual import ManualResponse
from fishery_ai.model_gateway import GatewayError, ModelEvent, ModelProfile, ModelResponse, ProfileRegistry
from fishery_ai.model_options import ReasoningMode, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.providers import AuthSpec

from tests.support.paths import PROJECT_ROOT
spec = importlib.util.spec_from_file_location('local_qualification',
    PROJECT_ROOT/'scripts/qualification/qualify_local_preset_request.py')
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


class Fake:
    def __init__(self, *, finish='stop', reasoning=False, error=None):
        self.finish_reason=finish
        self.returned_model='qwen3.5:4b'
        self.reasoning_present=reasoning
        self.error=error
        self.request_attempts=0
        self.kwargs=None
        self.closed=False

    def complete(self, request, runtime):
        self.request_attempts+=1
        self.runtime=runtime
        self.kwargs=OpenAICompatibleAdapter._kwargs(request,runtime,stream=False)
        if self.error: raise GatewayError(self.error)
        return ModelResponse('fictional output not recorded', Usage(8,2,10,source=UsageSource.PROVIDER))

    def stream(self, request, runtime):
        self.request_attempts+=1
        self.runtime=runtime
        self.kwargs=OpenAICompatibleAdapter._kwargs(request,runtime,stream=True)
        try:
            if self.error: raise GatewayError(self.error)
            yield ModelEvent(delta='offline delta',usage=Usage(8,2,10,source=UsageSource.PROVIDER))
        finally: self.closed=True

    def manual_complete(self, request, runtime):
        self.request_attempts+=1
        self.runtime=runtime
        self.kwargs=json.loads(request.body_json)
        return ManualResponse({'model':runtime.model,'choices':[{'finish_reason':'stop',
            'message':{'content':'fictional manual output not recorded'}}]},
            Usage(8,2,10,source=UsageSource.PROVIDER))


class LocalQualificationTests(unittest.TestCase):
    def setUp(self):
        test_execution.ExecutionTests.setUp(self)
        self.profile=ModelProfile('local-qualification','Local','local',qualification.IDENTITY[2],
            qualification.IDENTITY[3],service_id='ollama',provider_id='ollama',
            adapter_id='generic_openai_chat',auth_spec=AuthSpec.NONE,max_retries=1)
        self.runtime=ProfileRegistry([self.profile],CredentialStore(process_env={})).snapshot(self.profile.profile_id)

    def test_off_normal_single_bounded_request_and_exact_mapping(self):
        fake=Fake()
        result=qualification.qualify(fake,self.runtime,ReasoningMode.OFF,False)
        self.assertEqual(result['status'],'success')
        self.assertEqual(fake.request_attempts,1)
        self.assertEqual(fake.kwargs['reasoning_effort'],'none')
        self.assertEqual(fake.kwargs['max_tokens'],64)
        self.assertEqual(fake.runtime.max_retries,0)
        self.assertEqual(self.runtime.capabilities.reasoning_off,Support.UNKNOWN)
        self.assertNotIn('fictional output',json.dumps(result))

    def test_off_streaming_requires_delta_and_normal_finish(self):
        fake=Fake()
        result=qualification.qualify(fake,self.runtime,ReasoningMode.OFF,True)
        self.assertEqual(result['status'],'success')
        self.assertEqual(result['delta_count'],1)
        self.assertTrue(fake.kwargs['stream'])
        self.assertTrue(fake.closed)
        self.assertEqual(result['usage']['total_tokens'],10)

    def test_successful_transport_without_body_delta_does_not_qualify(self):
        class Empty(Fake):
            def stream(self, request, runtime):
                self.request_attempts+=1
                yield ModelEvent(usage=Usage(8,0,8,source=UsageSource.PROVIDER))
        fake=Empty()
        result=qualification.qualify(fake,self.runtime,ReasoningMode.OFF,True)
        self.assertEqual(result['status'],'failure')
        self.assertEqual(result['error_code'],'PROBE_NO_CONTENT')
        self.assertEqual(result['delta_count'],0)

    def test_on_maps_high_but_length_does_not_qualify(self):
        fake=Fake(finish='length')
        result=qualification.qualify(fake,self.runtime,ReasoningMode.ON,False)
        self.assertEqual(fake.kwargs['reasoning_effort'],'high')
        self.assertEqual(result['error_code'],'QUALIFICATION_NOT_COMPLETED')
        self.assertEqual(result['status'],'failure')

    def test_off_exposed_reasoning_never_qualifies(self):
        result=qualification.qualify(Fake(reasoning=True),self.runtime,ReasoningMode.OFF,False)
        self.assertEqual(result['error_code'],'UNEXPECTED_REASONING')

    def test_network_error_is_failure_without_retry_or_evidence(self):
        fake=Fake(error='READ_TIMEOUT')
        result=qualification.qualify(fake,self.runtime,ReasoningMode.OFF,True)
        self.assertEqual(result['status'],'failure')
        self.assertEqual(result['error_code'],'READ_TIMEOUT')
        self.assertEqual(fake.request_attempts,1)
        self.assertEqual(self.runtime.capabilities.streaming,Support.UNKNOWN)

    def test_manual_v1_same_target_raw_response_is_not_persisted(self):
        fake=Fake()
        result=qualification.qualify(fake,self.runtime,ReasoningMode.OFF,False,manual=True)
        self.assertEqual(result['status'],'success')
        self.assertTrue(result['manual_v1'])
        self.assertEqual(fake.kwargs['model'],self.runtime.model)
        self.assertNotIn('stream_options',fake.kwargs)
        self.assertNotIn('fictional manual output',json.dumps(result))

    def test_identity_auth_and_auto_cannot_bypass_fixed_diagnostic_scope(self):
        for runtime,mode in [(replace(self.runtime,model='another-model'),ReasoningMode.OFF),
                (replace(self.runtime,auth_spec=AuthSpec.REQUIRED_BEARER),ReasoningMode.OFF),
                (self.runtime,ReasoningMode.AUTO)]:
            fake=Fake()
            with self.assertRaises(GatewayError): qualification.qualify(fake,runtime,mode,False)
            self.assertEqual(fake.request_attempts,0)

    def test_cli_requires_confirmation_before_any_store_or_network(self):
        args=['qualify','--profile-id','offline','--thinking','off']
        with (patch('sys.argv',args), patch.object(qualification,'CustomProfileStore') as store,
                redirect_stdout(StringIO())):
            self.assertEqual(qualification.main(),2)
            store.assert_not_called()

    def test_cli_outside_project_does_not_read_connections_or_create_outputs(self):
        args=['qualify','--confirm-network','--profile-id','offline','--thinking','off']
        with (TemporaryDirectory() as temp, patch('sys.argv',args),
                patch.object(qualification.Path,'cwd',return_value=Path(temp)),
                patch.object(qualification,'CustomProfileStore') as store, redirect_stdout(StringIO())):
            self.assertEqual(qualification.main(),2)
            store.assert_not_called()
            self.assertFalse((Path(temp)/'outputs').exists())

    def test_cli_wrong_saved_identity_fails_before_credential_composition(self):
        args=['qualify','--confirm-network','--profile-id',self.profile.profile_id,'--thinking','off']
        wrong=replace(self.profile,model='another-model')
        with (patch('sys.argv',args), patch.object(qualification,'CustomProfileStore') as store,
                patch.object(qualification,'private_project_location') as location, redirect_stdout(StringIO())):
            store.return_value.load.return_value=[wrong]
            self.assertEqual(qualification.main(),2)
            location.assert_not_called()
