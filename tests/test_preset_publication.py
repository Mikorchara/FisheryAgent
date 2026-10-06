"""Offline checks for the first fresh, developer-owned Preset publication."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import test_execution
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.credentials import CredentialStore
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelRequest, MockGateway, ProfileRegistry
from fishery_ai.model_options import ReasoningMode, ReasoningOptions, Support
from fishery_ai.contracts import Mode
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.presets import _catalog, default_preset_id, preset_profiles
from fishery_ai.web import create_app


class PublicationTests(unittest.TestCase):
    def setUp(self):
        test_execution.ExecutionTests.setUp(self)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.credentials = CredentialStore(self.root / 'private.env', process_env={})
        self.profiles = preset_profiles()
        self.off, self.on = [p for p in self.profiles if p.model == 'qwen3.8-flash']
        self.request = ModelRequest(Mode.CHAT, (ModelMessage('user', 'OK'),))

    def client(self, gateway=None):
        return create_app(trace_path=self.root / 'trace.jsonl',
            custom_profiles_dir=self.root / 'profiles', capability_evidence_dir=self.root / 'evidence',
            credential_store=self.credentials, real_gateway_factory=lambda: gateway).test_client()

    def make_runtime(self, profile):
        return ProfileRegistry([profile], self.credentials).snapshot(profile.profile_id)

    def test_exact_models_and_only_directly_validated_combinations_per_contract(self):
        self.assertEqual({p.model for p in self.profiles},
                         {'qwen3.8-flash', 'deepseek-flash', 'qwen3.5:4b'})
        self.assertEqual({p.model: p.preset_contract_version for p in self.profiles},
                         {'qwen3.8-flash': '1.0.2', 'deepseek-flash': '1.0.2', 'qwen3.5:4b': '1.0.2'})
        for model in ('qwen3.8-flash', 'deepseek-flash', 'qwen3.5:4b'):
            self.assertEqual({(p.preset_variant, r) for p in self.profiles if p.model == model
                              for r in p.preset_response_modes},
                             {('off', 'normal'), ('off', 'streaming'), ('on', 'normal'), ('on', 'streaming')})
        self.assertTrue(self.off.preset_is_default)
        self.assertFalse(self.on.preset_is_default)

    def test_fixed_encoding_and_snapshot_are_pinned(self):
        for profile in (self.off, self.on):
            runtime = self.make_runtime(profile)
            with patch('fishery_ai.protocol_specs.protocol_for', side_effect=AssertionError('dynamic selection')):
                kwargs = OpenAICompatibleAdapter._kwargs(self.request, runtime, stream=False)
            self.assertEqual(kwargs['extra_body'], {'enable_thinking': profile.preset_variant == 'on'})
            self.assertNotIn('reasoning_effort', kwargs)
            self.assertIs(runtime.protocol_spec, profile.preset_protocol_spec)
            self.assertEqual(runtime.max_retries, 0)
        kwargs = OpenAICompatibleAdapter._kwargs(self.request, self.make_runtime(self.on), stream=True)
        self.assertTrue(kwargs['stream'])
        self.assertEqual(kwargs['stream_options'], {'include_usage': True})

    def test_off_streaming_is_published_but_variant_thinking_cannot_be_overridden(self):
        for model in ('qwen3.8-flash', 'deepseek-flash', 'qwen3.5:4b'):
            off = next(p for p in self.profiles if p.model == model and p.preset_variant == 'off')
            body = OpenAICompatibleAdapter._kwargs(self.request, self.make_runtime(off), stream=True)
            self.assertTrue(body['stream'])
            with self.assertRaises(GatewayError) as caught:
                OpenAICompatibleAdapter._kwargs(replace(self.request, reasoning=ReasoningOptions(ReasoningMode.ON)),
                                                self.make_runtime(off), stream=False)
            self.assertEqual(caught.exception.code, 'PRESET_OPTION_LOCKED')
        with self.assertRaises(GatewayError) as caught:
            MockGateway().complete(replace(self.request, reasoning=ReasoningOptions(ReasoningMode.AUTO)),
                                   self.make_runtime(self.off))
        self.assertEqual(caught.exception.code, 'PRESET_OPTION_LOCKED')

    def test_deepseek_and_ollama_fixed_wire_encoding(self):
        for profile in self.profiles:
            if profile.model == 'qwen3.8-flash':
                continue
            runtime = self.make_runtime(profile)
            with patch('fishery_ai.protocol_specs.protocol_for', side_effect=AssertionError('dynamic selection')):
                kwargs = OpenAICompatibleAdapter._kwargs(self.request, runtime, stream=False)
            if profile.model == 'deepseek-flash':
                self.assertEqual(kwargs['extra_body'], {'thinking': {
                    'type': 'enabled' if profile.preset_variant == 'on' else 'disabled'}})
                self.assertNotIn('reasoning_effort', kwargs)
            else:
                self.assertEqual(kwargs['reasoning_effort'], 'high' if profile.preset_variant == 'on' else 'none')
                self.assertNotIn('extra_body', kwargs)
            self.assertIs(runtime.protocol_spec, profile.preset_protocol_spec)
            self.assertEqual(runtime.max_retries, 0)
            if profile.preset_variant == 'off':
                streaming = OpenAICompatibleAdapter._kwargs(self.request, runtime, stream=True)
                self.assertTrue(streaming['stream'])
                if profile.model == 'deepseek-flash':
                    self.assertEqual(streaming['extra_body'], {'thinking': {'type': 'disabled'}})
            elif profile.preset_variant == 'on':
                streaming = OpenAICompatibleAdapter._kwargs(self.request, runtime, stream=True)
                self.assertTrue(streaming['stream'])
                if profile.model == 'deepseek-flash':
                    self.assertEqual(streaming['stream_options'], {'include_usage': True})
                else:
                    self.assertNotIn('stream_options', streaming)

    def test_exact_identity_auth_and_bounded_timeouts(self):
        for profile in self.profiles:
            if profile.model == 'deepseek-flash':
                self.assertEqual((profile.service_id, profile.adapter_id, profile.base_url),
                                 ('deepseek_api', 'openai_chat', 'https://api.deepseek.com'))
                self.assertEqual(profile.credential_ref, 'DEEPSEEK_API_KEY')
                self.assertEqual(profile.auth_spec.value, 'REQUIRED_BEARER')
            elif profile.model == 'qwen3.5:4b':
                self.assertEqual((profile.service_id, profile.adapter_id, profile.base_url),
                                 ('ollama', 'generic_openai_chat', 'http://127.0.0.1:11434/v1'))
                self.assertIsNone(profile.credential_ref)
                self.assertEqual(profile.auth_spec.value, 'NONE')
                self.assertEqual((profile.connect_timeout_s, profile.read_timeout_s, profile.total_timeout_s),
                                 (5, 120, 180))
        self.assertFalse(any(p.model == 'deepseek-v4-pro' for p in self.profiles))
        self.assertEqual(default_preset_id(), 'dashscope-qwen38-flash-r1')

    def test_all_contracts_bypass_evidence_and_resolver(self):
        evidence = CapabilityStore(self.root / 'evidence')
        for profile in self.profiles:
            managed = replace(profile, access_mode='managed_custom', preset_id=None, preset_variant=None,
                              preset_contract_version=None, preset_response_modes=(), preset_protocol_spec=None)
            evidence.save_thinking_probe(managed, profile.default_reasoning.mode, Support.UNSUPPORTED,
                                         '2026-10-03')
        original = CapabilityStore.apply
        def apply(store, profile):
            self.assertNotEqual(profile.access_mode, 'preset')
            return original(store, profile)
        with patch.object(CapabilityStore, 'apply', apply):
            config = self.client().get('/api/config').get_json()
        self.assertEqual(len([p for p in config['profiles'] if p['source'] == 'preset']), 6)
        for profile in preset_profiles():
            self.assertEqual(profile.capabilities.reasoning_on, Support.SUPPORTED)
            self.assertEqual(profile.capabilities.reasoning_off, Support.SUPPORTED)
            self.assertEqual(profile.capability_evidence, ())

    def test_new_contracts_missing_cloud_secret_and_local_none(self):
        gateway = MockGateway()
        client = self.client(gateway)
        for model in ('deepseek-flash', 'qwen3.5:4b'):
            off = next(p for p in self.profiles if p.model == model and p.preset_variant == 'off')
            payload = dict(profile_id=off.profile_id, scenario='low_oxygen', question='OK', confirm_network=True)
            normal = client.post('/api/analyze', json=payload)
            if model == 'deepseek-flash':
                self.assertEqual(normal.get_json()['error_code'], 'SECRET_MISSING')
                self.assertEqual(gateway.calls, [])
            else:
                self.assertEqual(normal.status_code, 200)
                on = next(p for p in self.profiles if p.model == model and p.preset_variant == 'on')
                stream = client.post('/api/analyze/stream', json={**payload, 'profile_id': on.profile_id})
                self.assertIn('event: completed', stream.get_data(as_text=True))
            stream_off = client.post('/api/analyze/stream', json=payload)
            if model=='qwen3.5:4b':
                self.assertIn('event: completed',stream_off.get_data(as_text=True))
            else:
                self.assertEqual(stream_off.get_json()['error_code'], 'SECRET_MISSING')

    def test_new_release_maintenance_is_exact_and_not_legacy(self):
        for template in _catalog()['templates']:
            self.assertEqual(template['contract_version'],
                             '1.0.2')
            records = template['maintenance']['evidence_summary']
            recorded = {r.get('capability') for r in records if r.get('capability')}
            self.assertTrue(recorded.issubset({'reasoning_on', 'reasoning_off', 'streaming',
                                               'thinking_streaming_combination',
                                               'thinking_off_streaming_combination'}))
            self.assertTrue(all(r.get('status') == 'supported' and r.get('source') == 'USER_VERIFIED'
                                for r in records if r.get('capability')))
            self.assertNotIn('OFF + Streaming', template['maintenance']['not_published'])
            publication = template['maintenance']['off_streaming_publication']
            self.assertEqual(publication['contract_version'], '1.0.1')
            if template['connection']['model'] in ('qwen3.8-flash', 'deepseek-flash'):
                self.assertEqual(publication['validation_source'], 'USER_CONFIRMED_MANUAL_VALIDATION')
                self.assertEqual(publication['request_attempts_by_codex'], 0)
            else:
                self.assertIn('R5', publication['validation_source'])
                self.assertEqual(publication['request_attempts'], 1)
            self.assertIn('AUTO', template['maintenance']['not_published'])

    def test_evidence_cannot_modify_contract_or_enter_resolver(self):
        evidence = CapabilityStore(self.root / 'evidence')
        managed = replace(self.off, access_mode='managed_custom', preset_id=None, preset_variant=None,
                          preset_contract_version=None, preset_response_modes=(), preset_protocol_spec=None)
        evidence.save_thinking_probe(managed, ReasoningMode.OFF, Support.UNSUPPORTED, '2026-10-03')
        original = CapabilityStore.apply
        def apply(store, profile):
            self.assertNotEqual(profile.access_mode, 'preset')
            return original(store, profile)
        with patch.object(CapabilityStore, 'apply', apply):
            public = self.client().get('/api/config').get_json()
        self.assertEqual(preset_profiles()[0].capabilities.reasoning_off, Support.SUPPORTED)
        self.assertEqual(public['default_preset_id'], self.off.preset_id)

    def test_user_catalog_has_no_connection_or_evidence_fields(self):
        config = self.client().get('/api/config').get_json()
        fixed = [p for p in config['profiles'] if p['source'] == 'preset']
        self.assertEqual(len(fixed), 6)
        for profile in fixed:
            for field in ('base_url', 'capabilities', 'credential_ref', 'secret_env', 'protocol_spec', 'service_id'):
                self.assertNotIn(field, profile)
        for model in ('qwen3.8-flash', 'deepseek-flash', 'qwen3.5:4b'):
            off = next(p for p in fixed if p['model'] == model and p['preset_variant'] == 'off')
            self.assertEqual(set(off['preset_response_modes']), {'normal', 'streaming'})

    def test_missing_credentials_fail_before_gateway_for_published_off_streaming(self):
        gateway = MockGateway()
        client = self.client(gateway)
        payload = dict(profile_id=self.off.profile_id, scenario='normal', question='OK', confirm_network=True)
        self.assertEqual(client.post('/api/analyze', json=payload).get_json()['error_code'], 'SECRET_MISSING')
        self.assertEqual(client.post('/api/analyze/stream', json=payload).get_json()['error_code'],
                         'SECRET_MISSING')
        self.assertEqual(gateway.calls, [])
        payload['profile_id'] = 'preset-dashscope-qwen38-flash-r1-auto'
        self.assertEqual(client.post('/api/analyze', json=payload).get_json()['error_code'], 'INVALID_REQUEST')

    def test_fake_credential_normal_and_streaming_keep_shared_analysis(self):
        self.credentials = CredentialStore(process_env={'DASHSCOPE_API_KEY': 'fictional-preset-only'})
        client = self.client(MockGateway())
        normal = client.post('/api/analyze', json=dict(profile_id=self.off.profile_id,
            scenario='low_oxygen', question='OK', confirm_network=True))
        self.assertEqual(normal.status_code, 200)
        streaming = client.post('/api/analyze/stream', json=dict(profile_id=self.on.profile_id,
            scenario='normal', question='OK', confirm_network=True))
        self.assertIn('event: completed', streaming.get_data(as_text=True))
        self.assertNotIn('fictional-preset-only', normal.get_data(as_text=True))
        self.assertNotIn('fictional-preset-only', (self.root / 'trace.jsonl').read_text(encoding='utf-8'))

    def test_no_default_keeps_catalog_valid_and_unknown_default_fails(self):
        catalog = _catalog()
        catalog['default_preset_id'] = None
        with patch('fishery_ai.presets._catalog', return_value=catalog):
            self.assertIsNone(default_preset_id())
            self.assertIsNone(self.client().get('/api/config').get_json()['default_preset_id'])
        catalog['default_preset_id'] = 'not-published'
        with patch('fishery_ai.presets._catalog', return_value=catalog), self.assertRaises(ValueError):
            default_preset_id()

    def test_bad_combinations_or_protocol_fail_closed(self):
        for modify in (lambda c: c['templates'][0]['defaults'].update(thinking='auto'),
                       lambda c: c['templates'][0]['protocol_spec'].update(thinking_encoding='thinking_type'),
                       lambda c: c['templates'][0]['capabilities'].update(thinking_streaming_combination='unknown')):
            catalog = _catalog()
            modify(catalog)
            with patch('fishery_ai.presets._catalog', return_value=catalog), self.assertRaises(ValueError):
                preset_profiles()


    def test_off_streaming_fixed_contract_does_not_read_managed_evidence(self):
        store=CapabilityStore(self.root/'evidence')
        for model in ('qwen3.8-flash', 'deepseek-flash', 'qwen3.5:4b'):
            off=next(p for p in self.profiles if p.model==model and p.preset_variant=='off')
            self.assertEqual(off.preset_contract_version,'1.0.2')
            self.assertIn('streaming',off.preset_response_modes)
            self.assertEqual(off.capabilities.thinking_off_streaming_combination,Support.SUPPORTED)
            managed=replace(off,access_mode='managed_custom',preset_id=None,preset_variant=None,
                            preset_response_modes=(),preset_protocol_spec=None)
            store.save_probe(managed,'thinking_off_streaming_combination',Support.UNSUPPORTED,'2026-10-04')
            self.assertIs(store.apply(off),off)
            body=OpenAICompatibleAdapter._kwargs(self.request,self.make_runtime(off),stream=True)
            self.assertTrue(body['stream'])
            if model == 'deepseek-flash':
                self.assertEqual(body['extra_body'], {'thinking': {'type': 'disabled'}})
            elif model == 'qwen3.8-flash':
                self.assertEqual(body['extra_body'], {'enable_thinking': False})
            else:
                self.assertEqual(body['reasoning_effort'], 'none')
        catalog=_catalog()
        qwen=next(t for t in catalog['templates'] if t['connection']['model']=='qwen3.8-flash')
        qwen['capabilities']['thinking_off_streaming_combination']='unknown'
        with patch('fishery_ai.presets._catalog',return_value=catalog), self.assertRaises(ValueError):
            preset_profiles()
