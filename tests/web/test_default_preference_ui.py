"""Stored legacy preferences stay separate from resolved capabilities and runtime."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import socket
import unittest

from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.model_gateway import ModelResponse, ModelEvent
from fishery_ai.credentials import CredentialStore
from fishery_ai.model_options import Support, ReasoningMode
from fishery_ai.web import create_app


class DefaultPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        def forbidden(*_, **__): raise AssertionError('offline only')
        for name in ('connect','connect_ex','sendto'):
            guard=patch.object(socket.socket,name,forbidden); guard.start(); self.addCleanup(guard.stop)
        guard=patch.object(socket,'getaddrinfo',forbidden);guard.start();self.addCleanup(guard.stop)
        self.store=CustomProfileStore(self.root/'profiles')
        self.profile=self.store.create(dict(display_name='Legacy preference',service_id='dashscope',model_family='unknown',
            adapter_id='openai_chat',base_url='http://localhost:18888/v1',model='unknown-model',
            secret_env='',auth_spec='NONE',provider_kind='local',default_thinking_mode='on',default_response_mode='normal'))
        self.path=next((self.root/'profiles').glob('*.json'))
        self.original=self.path.read_bytes()

    def client(self, gateway=None):
        return create_app(trace_path=self.root/'trace.jsonl',custom_profiles_dir=self.root/'profiles',
            capability_evidence_dir=self.root/'evidence',real_gateway_factory=lambda:gateway,
            credential_store=CredentialStore(self.root/'private'/'.env',process_env={})).test_client()

    def test_unknown_saved_on_is_retained_and_runtime_uses_auto(self):
        seen=[]
        class Fake:
            def complete(_,request,runtime):
                seen.append(runtime.default_reasoning.mode)
                return ModelResponse('{"inference":"ok","recommendations":[],"uncertainty":[]}')
        client=self.client(Fake())
        detail=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(detail['fields']['default_thinking_mode'],'on')
        self.assertEqual(detail['profile']['default_reasoning_mode'],'auto')
        self.assertEqual(detail['profile']['capabilities']['thinking_on']['status'],'unknown')
        response=client.post('/api/analyze',json=dict(profile_id=self.profile.profile_id,scenario='normal',question='test',confirm_network=True))
        self.assertEqual(response.status_code,200)
        self.assertEqual(seen,[ReasoningMode.AUTO]);self.assertEqual(self.path.read_bytes(),self.original)

    def test_probe_resolver_unlock_does_not_rewrite_saved_preference(self):
        class Fake:
            def complete(_,request,runtime):return ModelResponse('OK')
        client=self.client(Fake())
        response=client.post(f'/api/profiles/{self.profile.profile_id}/thinking-probe',json=dict(mode='on',confirm_network=True))
        self.assertEqual(response.status_code,200)
        detail=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(detail['profile']['capabilities']['thinking_on']['status'],'supported')
        self.assertEqual(detail['profile']['default_reasoning_mode'],'on')
        self.assertEqual(detail['profile']['capabilities']['thinking_off']['status'],'unknown')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_unsupported_preserves_history_and_safe_runtime_view(self):
        CapabilityStore(self.root/'evidence').save_thinking_probe(self.profile,ReasoningMode.ON,Support.UNSUPPORTED,'2026-10-03')
        detail=self.client().get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(detail['fields']['default_thinking_mode'],'on')
        self.assertEqual(detail['profile']['default_reasoning_mode'],'auto')
        self.assertEqual(detail['profile']['capabilities']['thinking_on']['status'],'unsupported')
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_on_off_and_stream_probe_publish_latest_resolved_state_without_rewriting_preferences(self):
        calls=[]
        class Fake:
            def complete(_,request,runtime):
                calls.append('thinking')
                self.assertEqual(runtime.max_retries,0)
                return ModelResponse('OK')
            def stream(_,request,runtime):
                calls.append('streaming')
                self.assertEqual(runtime.max_retries,0)
                yield ModelEvent(delta='OK')
        client=self.client(Fake())
        for mode in ('on','off'):
            response=client.post(f'/api/profiles/{self.profile.profile_id}/thinking-probe',
                json=dict(mode=mode,confirm_network=True))
            self.assertEqual(response.status_code,200)
            detail=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
            self.assertEqual(detail['profile']['capabilities']['thinking_'+mode]['status'],'supported')
            self.assertEqual(detail['fields']['default_thinking_mode'],'on')
        response=client.post(f'/api/profiles/{self.profile.profile_id}/probe',
            json=dict(capability='streaming',confirm_network=True))
        self.assertEqual(response.status_code,200)
        data=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(data['profile']['capabilities']['streaming'],'supported')
        self.assertEqual(data['profile']['capabilities']['thinking_on']['status'],'supported')
        self.assertEqual(data['profile']['capabilities']['thinking_off']['status'],'supported')
        self.assertEqual(calls,['thinking','thinking','streaming'])
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_legacy_streaming_default_is_retained_but_safe_response_is_normal(self):
        fields=self.client().get(f'/api/profiles/{self.profile.profile_id}').get_json()['fields']
        self.store.update(self.profile.profile_id,{**fields,'default_response_mode':'streaming'})
        before=self.path.read_bytes()
        detail=self.client().get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(detail['fields']['default_response_mode'],'streaming')
        self.assertEqual(detail['profile']['capabilities']['streaming'],'unknown')
        self.assertEqual(detail['profile']['default_response_mode'],'normal')
        self.assertEqual(self.path.read_bytes(),before)

    def test_draft_remains_client_local_until_put_then_new_identity_resolves_and_falls_back(self):
        evidence=CapabilityStore(self.root/'evidence')
        evidence.save_thinking_probe(self.profile,ReasoningMode.ON,Support.SUPPORTED,'2026-10-03')
        evidence.save_probe(self.profile,'streaming',Support.SUPPORTED,'2026-10-03')
        seen=[]
        class Fake:
            def complete(_,request,runtime):
                seen.append((runtime.model,runtime.default_reasoning.mode,runtime.default_response_mode))
                return ModelResponse('{"inference":"ok","recommendations":[],"uncertainty":[]}')
        client=self.client(Fake())
        before=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
        draft={**before['fields'],'model':'new-exact-model','default_response_mode':'streaming'}
        evidence_bytes={p.name:p.read_bytes() for p in (self.root/'evidence').glob('*.json')}
        self.assertEqual(self.path.read_bytes(),self.original)
        unchanged=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(unchanged['profile']['model'],self.profile.model)
        self.assertEqual(unchanged['profile']['capabilities']['thinking_on']['status'],'supported')
        saved=client.put(f'/api/profiles/{self.profile.profile_id}',json=draft)
        self.assertEqual(saved.status_code,200)
        after=client.get(f'/api/profiles/{self.profile.profile_id}').get_json()
        self.assertEqual(after['profile']['model'],'new-exact-model')
        self.assertEqual(after['profile']['capabilities']['thinking_on']['status'],'unknown')
        self.assertEqual(after['profile']['capabilities']['streaming'],'unknown')
        self.assertEqual(after['fields']['default_thinking_mode'],'on')
        self.assertEqual(after['fields']['default_response_mode'],'streaming')
        self.assertEqual(after['profile']['default_reasoning_mode'],'auto')
        self.assertEqual(after['profile']['default_response_mode'],'normal')
        response=client.post('/api/analyze',json=dict(profile_id=self.profile.profile_id,scenario='normal',
            question='test',confirm_network=True))
        self.assertEqual(response.status_code,200)
        self.assertEqual(seen,[('new-exact-model',ReasoningMode.AUTO,'normal')])
        self.assertEqual({p.name:p.read_bytes() for p in (self.root/'evidence').glob('*.json')},evidence_bytes)

    def test_same_identity_profiles_share_evidence_but_other_model_and_service_do_not(self):
        fields=self.client().get(f'/api/profiles/{self.profile.profile_id}').get_json()['fields']
        same=self.store.create({**fields,'display_name':'Same identity',
                               'base_url':'HTTP://LOCALHOST:18888/v1/'})
        other=self.store.create({**fields,'display_name':'Other model','model':'different-exact-model'})
        service=self.store.create({**fields,'display_name':'Other service','service_id':'deepseek_api'})
        evidence=CapabilityStore(self.root/'evidence')
        evidence.save_thinking_probe(self.profile,ReasoningMode.ON,Support.SUPPORTED,'2026-10-03')
        evidence.save_probe(self.profile,'streaming',Support.SUPPORTED,'2026-10-03')
        client=self.client()
        for profile,status in ((self.profile,'supported'),(same,'supported'),(other,'unknown'),(service,'unknown')):
            cap=client.get(f'/api/profiles/{profile.profile_id}').get_json()['profile']['capabilities']
            self.assertEqual(cap['thinking_on']['status'],status)
            self.assertEqual(cap['streaming'],status)
