"""R0 golden contracts captured before the R1 credential migration; fully offline."""

from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import socket
import unittest

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.contracts import Mode
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.model_gateway import (ModelMessage, ModelProfile, ModelRequest,
                                     ProfileRegistry, effective_runtime_defaults)
from fishery_ai.model_options import ReasoningMode, ReasoningOptions, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import _builtin_profiles, _profile_public


BASELINE = json.loads((Path(__file__).parent / "fixtures/r0_runtime_baseline.json").read_text(
    encoding="utf-8"))


def deny_network(*_args, **_kwargs):
    raise AssertionError("R0 compatibility tests must remain offline")


class CredentialCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, name, deny_network)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(socket, "getaddrinfo", deny_network)
        guard.start()
        self.addCleanup(guard.stop)

    def test_builtin_public_profiles_and_runtime_metadata_match_checkpoint(self):
        profiles = {p.profile_id: p for p in _builtin_profiles()}
        self.assertEqual(set(profiles), {p["public"]["profile_id"] for p in BASELINE["builtin_profiles"]})
        for item in BASELINE["builtin_profiles"]:
            with self.subTest(profile_id=item["public"]["profile_id"]):
                profile = profiles[item["public"]["profile_id"]]
                actual = _profile_public(profile, "built_in")
                def frozen_fields(value, expected):
                    if isinstance(expected, dict):
                        return {key: frozen_fields(value[key], child) for key, child in expected.items()}
                    return value
                # R4 adds evidence dates/reasons; all historical fields stay frozen.
                self.assertEqual(frozen_fields(actual, item["public"]), item["public"])
                runtime = ProfileRegistry([profile]).snapshot(profile.profile_id, {})
                public_runtime = asdict(runtime.public_info())
                # Preserve all frozen R0/R2 fields; access-mode metadata is additive.
                self.assertEqual({key: public_runtime[key] for key in item["runtime_public"]}, item["runtime_public"])
                self.assertEqual(public_runtime["access_mode"], "managed_custom")
                self.assertIsNone(public_runtime["preset_contract_version"])

    def test_adapter_body_matches_all_checkpoint_payloads(self):
        profiles = {p.profile_id: p for p in _builtin_profiles()}
        for case in BASELINE["request_payloads"]:
            with self.subTest(profile=case["profile_id"], mode=case["thinking_mode"],
                              streaming=case["streaming"], effort=case.get("effort")):
                profile = profiles[case["profile_id"]]
                # Golden wire-body fixture, not production capability evidence.
                profile = replace(profile, capabilities=replace(profile.capabilities,
                    thinking_off_streaming_combination=Support.SUPPORTED))
                runtime = ProfileRegistry([profile]).snapshot(profile.profile_id, {})
                request = ModelRequest(Mode.CHAT, (ModelMessage("user", "只回复 OK"),),
                    reasoning=ReasoningOptions(ReasoningMode(case["thinking_mode"]), case.get("effort")))
                self.assertEqual(OpenAICompatibleAdapter._kwargs(request, runtime,
                    stream=case["streaming"]), case["body"])

    def test_legacy_identity_adapter_and_secret_env_are_preserved(self):
        for provider, service, adapter in (("qwen", "dashscope", "openai_chat"),
            ("deepseek", "deepseek_api", "openai_chat"), ("custom", "custom", "generic_openai_chat")):
            with self.subTest(provider=provider):
                profile = ModelProfile.from_dict(dict(profile_id="legacy", display_name="Legacy",
                    provider_kind="cloud", base_url="https://example.invalid/v1/", model="model-id",
                    provider_id=provider, adapter_id=adapter, secret_env="TEST_FAKE_KEY"))
                self.assertEqual(profile.service_id, service)
                self.assertEqual(profile.adapter_id, adapter)
                self.assertEqual(profile.secret_env, "TEST_FAKE_KEY")
                runtime = ProfileRegistry([profile]).snapshot("legacy", {"TEST_FAKE_KEY": "fake-secret-123"})
                self.assertEqual(runtime.api_key, "fake-secret-123")
                self.assertNotIn("fake-secret-123", repr(runtime))
                self.assertNotIn("fake-secret-123", json.dumps(asdict(runtime.public_info())))

    def test_legacy_custom_json_is_read_without_disk_rewrite(self):
        directory = self.root / "custom_profiles"
        directory.mkdir()
        profile_id = "custom-" + "a" * 32
        payload = dict(profile_id=profile_id, profile_status="custom", max_retries=0,
            display_name="Legacy Local", provider_id="custom", adapter_id="generic_openai_chat",
            base_url="http://127.0.0.1:8000/v1", model="old-local-model", secret_env="LOCAL_FAKE_KEY",
            provider_kind="local", default_thinking_mode="off", default_response_mode="streaming")
        path = directory / f"{profile_id}.json"
        original = json.dumps(payload, indent=2).encode("utf-8")
        path.write_bytes(original)
        profile, = CustomProfileStore(directory).load()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(profile.secret_env, "LOCAL_FAKE_KEY")
        self.assertEqual(profile.default_reasoning.mode, ReasoningMode.OFF)
        self.assertEqual(profile.default_response_mode, "streaming")
        safe_thinking, safe_response, warnings = effective_runtime_defaults(profile)
        self.assertEqual(safe_thinking.mode, ReasoningMode.AUTO)
        self.assertEqual(safe_response, "normal")
        self.assertEqual(set(warnings), {"THINKING_DEFAULT_FALLBACK", "RESPONSE_DEFAULT_FALLBACK"})
        runtime = ProfileRegistry([profile]).snapshot(profile_id, {"LOCAL_FAKE_KEY": "test-local-key"})
        self.assertEqual(runtime.api_key, "test-local-key")

    def test_exact_user_evidence_survives_reload_and_identity_isolation(self):
        profile = next(p for p in _builtin_profiles() if p.service_id == "dashscope")
        store = CapabilityStore(self.root / "evidence")
        verified = store.save_streaming(profile, Support.SUPPORTED, "2026-09-28T00:00:00Z")
        loaded = CapabilityStore(store.directory).apply(profile)
        self.assertEqual(loaded.capabilities, verified.capabilities)
        self.assertEqual(loaded.capabilities.source_for("streaming").value, "USER_VERIFIED")
        self.assertIn("OFFICIAL_DOCS", [item.value for item in loaded.capabilities.sources_for("streaming")])
        changed = ModelProfile(profile_id="other", display_name="Other", provider_kind="cloud",
            base_url=profile.base_url, model="different-exact-model", adapter_id=profile.adapter_id,
            provider_id=profile.provider_id, service_id=profile.service_id, secret_env=profile.secret_env)
        self.assertEqual(store.apply(changed).capabilities.streaming, Support.UNKNOWN)

    def test_cloud_missing_and_builtin_ollama_no_real_credential(self):
        profiles = _builtin_profiles()
        cloud = next(p for p in profiles if p.service_id == "dashscope")
        self.assertIsNone(ProfileRegistry([cloud]).snapshot(cloud.profile_id, {}).api_key)
        ollama = next(p for p in profiles if p.service_id == "ollama")
        runtime = ProfileRegistry([ollama]).snapshot(ollama.profile_id, {})
        self.assertIsNone(runtime.api_key)
        self.assertEqual(runtime.default_reasoning.mode, ReasoningMode.OFF)
        self.assertEqual(runtime.default_response_mode, "normal")


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
