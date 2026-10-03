"""Clean-room startup uses real empty catalogs, never historical fixture overlays."""

from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

import test_execution
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.credentials import CredentialStore
from fishery_ai.evidence_resolver import project_evidence
from fishery_ai.model_gateway import ModelEvent, ModelResponse, ProfileRegistry
from fishery_ai.model_options import CapabilitySource, ReasoningMode, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.official_capabilities import DECLARATIONS
from fishery_ai.presets import preset_profiles
from fishery_ai.protocol_specs import protocol_for
from fishery_ai.web import _builtin_profiles, create_app


class CleanRoomTests(unittest.TestCase):
    def setUp(self):
        test_execution.ExecutionTests.setUp(self)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.custom = CustomProfileStore(self.root / 'profiles')
        self.env = self.root / 'private' / '.env'
        self.env.parent.mkdir()
        self.credentials = CredentialStore(self.env, process_env={})

    def new_profile(self, service='dashscope', model='qwen-plus', url=None):
        return self.custom.create(dict(display_name='First clean model', service_id=service,
            adapter_id='openai_chat', model_family='unknown', provider_kind='cloud',
            base_url=url or 'https://dashscope.aliyuncs.com/compatible-mode/v1/', model=model,
            secret_env='TEST_API_KEY', auth_spec='REQUIRED_BEARER'))

    def client(self, gateway=None):
        return create_app(trace_path=self.root / 'trace.jsonl',
            custom_profiles_dir=self.root / 'profiles', capability_evidence_dir=self.root / 'evidence',
            credential_store=self.credentials, real_gateway_factory=lambda: gateway).test_client()

    def test_old_catalogs_stay_empty_first_fresh_publication_and_mock_load(self):
        self.assertEqual(DECLARATIONS, {})
        released = preset_profiles(include_candidates=True)
        self.assertEqual({p.model for p in released}, {'qwen3.8-flash', 'deepseek-flash', 'qwen3.5:4b'})
        self.assertEqual({p.preset_id for p in released},
                         {'dashscope-qwen38-flash-r1', 'deepseek-flash-r1', 'ollama-qwen35-4b-r1'})
        self.assertEqual([p.profile_id for p in _builtin_profiles()], ['mock-demo'])
        client = self.client()
        self.assertEqual(client.get('/').status_code, 200)
        config = client.get('/api/config').get_json()
        self.assertEqual([p['profile_id'] for p in config['profiles']],
                         ['mock-demo'] + [p.profile_id for p in released])
        self.assertTrue(config['presets'])  # Provider connection presets remain, not model Presets.

    def test_previous_exact_models_have_no_maintained_evidence_or_preferences(self):
        examples = [('dashscope', 'qwen-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1'),
                    ('deepseek_api', 'deepseek-flash', 'https://api.deepseek.com'),
                    ('ollama', 'qwen3.5:4b', 'http://127.0.0.1:11434/v1')]
        base = self.new_profile()
        for service, model, url in examples:
            profile = replace(base, service_id=service, provider_id=service, model=model, base_url=url,
                              adapter_id='generic_openai_chat' if service == 'ollama' else 'openai_chat')
            self.assertEqual(project_evidence(profile), [])
            resolved = CapabilityStore(self.root / 'evidence').apply(profile)
            for name in ('streaming', 'reasoning_on', 'reasoning_off', 'thinking_streaming_combination',
                         'reasoning_effort', 'structured_output', 'tool_calling'):
                self.assertEqual(getattr(resolved.capabilities, name), Support.UNKNOWN, name)
            self.assertIsNone(resolved.capabilities.thinking_default)
            self.assertEqual(resolved.default_reasoning.mode, ReasoningMode.AUTO)
            self.assertEqual(resolved.default_response_mode, 'normal')

    def test_archived_probe_and_defaults_are_not_recursively_loaded(self):
        profile = self.new_profile()
        archived = self.root / 'archive' / 'previous-evidence'
        CapabilityStore(archived).save_thinking_probe(profile, ReasoningMode.ON,
                                                     Support.SUPPORTED, '2026-10-02')
        self.assertEqual(CapabilityStore(self.root / 'evidence').apply(profile).capabilities.reasoning_on,
                         Support.UNKNOWN)
        self.assertEqual(len(self.custom.load()), 1)

    def test_normal_auto_works_unknown_and_secret_stays_out_of_response(self):
        profile = self.new_profile()
        self.env.write_text('TEST_API_KEY=fictional-clean-room-only\n', encoding='utf-8')
        seen = []
        class Fake:
            def complete(_, request, runtime):
                seen.append((request, runtime))
                return ModelResponse('{"inference":"mock inference","recommendations":[],"uncertainty":[]}')
        response = self.client(Fake()).post('/api/analyze', json=dict(profile_id=profile.profile_id,
            scenario='normal', question='test', confirm_network=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1].capabilities.streaming, Support.UNKNOWN)
        self.assertEqual(seen[0][1].credential.status.source, 'PROJECT_ENV')
        self.assertNotIn('fictional-clean-room-only', response.get_data(as_text=True))
        self.assertNotIn('fictional-clean-room-only', (self.root / 'trace.jsonl').read_text())

    def test_new_probe_resolves_only_requested_exact_capability(self):
        profile = self.new_profile()
        self.env.write_text('TEST_API_KEY=fictional-probe-only\n', encoding='utf-8')
        calls = []
        class Fake:
            def stream(_, request, runtime):
                OpenAICompatibleAdapter._kwargs(request, runtime, stream=True)
                calls.append(runtime)
                self.assertEqual(runtime.max_retries, 0)
                yield ModelEvent(delta='OK')
        client = self.client(Fake())
        denied = client.post('/api/analyze/stream', json=dict(profile_id=profile.profile_id,
            scenario='normal', question='test', confirm_network=True))
        self.assertIn('OPTION_UNKNOWN', denied.get_data(as_text=True))
        self.assertEqual(calls, [])
        response = client.post(f'/api/profiles/{profile.profile_id}/probe',
            json=dict(capability='streaming', confirm_network=True))
        self.assertEqual(response.status_code, 200)
        loaded = CapabilityStore(self.root / 'evidence').apply(profile)
        self.assertEqual(loaded.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(loaded.capabilities.source_for('streaming'), CapabilitySource.USER_VERIFIED)
        self.assertEqual(loaded.capabilities.reasoning_on, Support.UNKNOWN)
        self.assertEqual(CapabilityStore(self.root / 'evidence').apply(
            replace(profile, model=profile.model + '-other')).capabilities.streaming, Support.UNKNOWN)

    def test_first_connection_model_list_and_save_do_not_grant_capabilities(self):
        self.env.write_text('TEST_API_KEY=fictional-list-only\n', encoding='utf-8')
        class Fake:
            def list_models(_, runtime, **kwargs):
                return [{'id':'qwen-plus'}]
        client = self.client(Fake())
        fields = dict(display_name='First saved connection', service_id='dashscope',
            adapter_id='openai_chat', model_family='unknown', provider_kind='cloud',
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', model='qwen-plus',
            secret_env='TEST_API_KEY', auth_spec='REQUIRED_BEARER')
        tested = client.post('/api/profiles/test', json={**fields, 'method':'models',
                                                       'confirm_network':True})
        self.assertEqual(tested.status_code, 200)
        created = client.post('/api/profiles', json={**fields, 'test_id':tested.get_json()['test_id']})
        self.assertEqual(created.status_code, 201)
        profile = self.custom.load()[0]
        self.assertEqual(project_evidence(profile), [])
        self.assertEqual(profile.capabilities.streaming, Support.UNKNOWN)
        self.assertEqual(profile.default_reasoning.mode, ReasoningMode.AUTO)
        self.assertEqual(profile.credential_ref, 'TEST_API_KEY')
        self.assertNotIn('fictional-list-only', created.get_data(as_text=True))

    def test_protocol_knowledge_survives_without_support(self):
        profile = self.new_profile()
        for service, model, encoding in [('dashscope', 'qwen-plus', 'enable_thinking'),
                                        ('deepseek_api', 'deepseek-flash', 'thinking_type'),
                                        ('ollama', 'qwen3.5:4b', 'effort_high_none')]:
            target = replace(profile, service_id=service, model=model,
                             provider_kind='local' if service == 'ollama' else 'cloud')
            self.assertEqual(protocol_for(target).thinking_encoding, encoding)
            self.assertEqual(project_evidence(target), [])

    def test_credential_priority_hot_reload_no_legacy_fallback(self):
        profile = self.new_profile()
        legacy = self.root / '.env'
        legacy.write_text('TEST_API_KEY=fictional-legacy-only\n', encoding='utf-8')
        runtime = ProfileRegistry([profile], self.credentials).snapshot(profile.profile_id)
        self.assertEqual(runtime.credential.status.availability, 'MISSING')
        self.env.write_text('TEST_API_KEY=fictional-first\n', encoding='utf-8')
        before = self.credentials.resolve(profile.credential_ref, profile.auth_spec)
        self.env.write_text('TEST_API_KEY=fictional-second\n', encoding='utf-8')
        after = self.credentials.resolve(profile.credential_ref, profile.auth_spec)
        self.assertEqual(before._for_adapter(), 'fictional-first')
        self.assertEqual(after._for_adapter(), 'fictional-second')
        external = CredentialStore(self.env, process_env={'TEST_API_KEY':'fictional-process'})
        self.assertEqual(external.resolve(profile.credential_ref, profile.auth_spec).status.source, 'PROCESS_ENV')

    def test_mock_analysis_and_stream_still_run_without_credentials(self):
        client = self.client()
        payload = dict(profile_id='mock-demo', scenario='low_oxygen', question='test')
        normal = client.post('/api/analyze', json=payload)
        self.assertEqual(normal.status_code, 200)
        self.assertTrue(normal.get_json()['result']['structured_parse_ok'])
        stream = client.post('/api/analyze/stream', json=payload)
        self.assertIn('event: completed', stream.get_data(as_text=True))
        self.assertFalse(self.env.exists())

    def test_real_validation_historical_profile_is_explicitly_inactive(self):
        from fishery_ai import real_validation
        with patch.object(real_validation, 'private_project_location') as location, redirect_stdout(StringIO()) as output:
            result = real_validation.run_real_validation(check='basic', scenario='normal', confirm_network=True,
                                                        credential_store=self.credentials)
        self.assertEqual(result, 2)
        location.assert_not_called()
        self.assertIn('INACTIVE_VALIDATION_PROFILE', output.getvalue())
