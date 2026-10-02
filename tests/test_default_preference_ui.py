"""Stored legacy preferences stay separate from resolved capabilities and runtime."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import socket
import unittest

from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.model_gateway import ModelResponse
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
            capability_evidence_dir=self.root/'evidence',real_gateway_factory=lambda:gateway).test_client()

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
