"""Targeted offline checks for local metadata, exact evidence, and basic Custom calls."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import socket
import unittest

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.contracts import Mode
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.model_gateway import (ModelMessage, ModelRequest, ModelResponse,
                                      ProfileRegistry)
from fishery_ai.model_options import (CapabilitySource, ReasoningMode, Support,
                                      normalize_base_url)
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import _builtin_profiles, create_app


def no_network(*_args, **_kwargs):
    raise AssertionError("real network is forbidden")


class LocalProfileCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("connect", "connect_ex", "sendto"):
            patcher = patch.object(socket.socket, name, no_network)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(socket, "getaddrinfo", no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_builtin_local_is_readonly_normal_and_defaults_thinking_off(self):
        profile = next(p for p in _builtin_profiles() if p.profile_id == "ollama-qwen35-4b-local")
        self.assertEqual((profile.service_id, profile.adapter_id, profile.model),
                         ("ollama", "generic_openai_chat", "qwen3.5:4b"))
        self.assertEqual(profile.default_reasoning.mode, ReasoningMode.OFF)
        self.assertEqual(profile.capabilities.reasoning_off, Support.SUPPORTED)
        self.assertEqual(profile.capabilities.streaming, Support.UNKNOWN)
        self.assertTrue(profile.capabilities.thinking_default)
        app = create_app(trace_path=self.root / "trace.jsonl",
                         custom_profiles_dir=self.root / "profiles",
                         capability_evidence_dir=self.root / "evidence")
        client = app.test_client()
        public = next(p for p in client.get("/api/config").get_json()["profiles"]
                      if p["profile_id"] == profile.profile_id)
        self.assertEqual(public["default_reasoning_mode"], "off")
        self.assertEqual(public["capabilities"]["thinking_off"]["source"], "MODEL_METADATA")
        self.assertEqual(public["capabilities"]["streaming"], "unknown")
        self.assertEqual(public["capabilities"]["tool_calling"]["source"], "UNKNOWN")
        self.assertEqual(client.get(f"/api/profiles/{profile.profile_id}").get_json()["editable"], False)
        self.assertEqual(client.delete(f"/api/profiles/{profile.profile_id}").status_code, 403)

    def test_custom_unknown_allows_basic_unset_normal_request(self):
        fields = {"display_name": "Unknown local", "service_id": "custom",
                  "model_family": "unknown", "adapter_id": "generic_openai_chat",
                  "base_url": "http://127.0.0.1:18080/v1", "model": "qwen3.5:4b",
                  "secret_env": "", "provider_kind": "local"}
        profile, _ = CustomProfileStore.build(fields, "custom-unknown")
        runtime = ProfileRegistry([profile]).snapshot(profile.profile_id, {})
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "OK"),))
        kwargs = OpenAICompatibleAdapter._kwargs(request, runtime, stream=False)
        self.assertEqual(set(kwargs), {"model", "messages"})
        self.assertEqual(profile.capabilities.reasoning_off, Support.UNKNOWN)
        self.assertEqual(profile.capabilities.streaming, Support.UNKNOWN)

    def test_metadata_record_is_exact_and_does_not_inherit_after_model_change(self):
        profile = next(p for p in _builtin_profiles() if p.profile_id == "ollama-qwen35-4b-local")
        store = CapabilityStore(self.root / "evidence")
        saved = store.save_thinking_metadata(profile, [False, True], True, "2026-01-01T00:00:00Z")
        self.assertEqual(saved.capabilities.reasoning_off, Support.SUPPORTED)
        saved_record = json.loads(next((self.root / "evidence").glob("*.json")).read_text("utf-8"))
        self.assertEqual(saved_record["adapter_id"], "generic_openai_chat")
        self.assertNotIn("secret", saved_record)
        fields = {"display_name": "Other model", "service_id": "ollama",
                  "model_family": "unknown", "adapter_id": "generic_openai_chat",
                  "base_url": profile.base_url, "model": "qwen3.5:9b", "secret_env": "",
                  "provider_kind": "local"}
        other, _ = CustomProfileStore.build(fields, "custom-other")
        self.assertEqual(store.apply(other).capabilities.reasoning_off, Support.UNKNOWN)
        changed_adapter, _ = CustomProfileStore.build(
            {**fields, "adapter_id": "openai_chat", "model": profile.model}, "custom-adapter")
        self.assertEqual(store.apply(changed_adapter).capabilities.reasoning_off, Support.UNKNOWN)
        changed_url, _ = CustomProfileStore.build(
            {**fields, "base_url": "http://127.0.0.1:11435/v1", "model": profile.model},
            "custom-url")
        self.assertEqual(store.apply(changed_url).capabilities.reasoning_off, Support.UNKNOWN)
        changed_service, _ = CustomProfileStore.build(
            {**fields, "service_id": "custom", "model": profile.model}, "custom-service")
        self.assertEqual(store.apply(changed_service).capabilities.reasoning_off, Support.UNKNOWN)

    def test_url_trailing_slash_normalization_and_old_record_migration(self):
        self.assertEqual(normalize_base_url("HTTP://127.0.0.1:11434/v1/"),
                         "http://127.0.0.1:11434/v1")
        profile = next(p for p in _builtin_profiles() if p.profile_id == "ollama-qwen35-4b-local")
        directory = self.root / "evidence"
        directory.mkdir()
        legacy = {"service_id": "ollama", "adapter_id": "generic_openai_chat",
                  "base_url": "HTTP://127.0.0.1:11434/v1/", "model": "qwen3.5:4b",
                  "capability": "thinking", "values": [False, True], "default": True,
                  "source": "MODEL_METADATA"}
        (directory / "legacy-trailing-slash.json").write_text(
            json.dumps(legacy), encoding="utf-8")
        loaded = CapabilityStore(directory).apply(profile)
        self.assertEqual(loaded.capabilities.reasoning_on, Support.SUPPORTED)
        self.assertEqual(loaded.capabilities.reasoning_off, Support.SUPPORTED)
        self.assertTrue(loaded.capabilities.thinking_default)

    def test_thinking_probe_results_are_recorded_per_mode(self):
        profile = next(p for p in _builtin_profiles() if p.profile_id == "ollama-qwen35-4b-local")
        store = CapabilityStore(self.root / "evidence")
        verified_on = store.save_thinking_probe(
            profile, ReasoningMode.ON, Support.SUPPORTED, "2026-09-30T00:00:00Z")
        self.assertEqual(verified_on.capabilities.reasoning_on, Support.SUPPORTED)
        self.assertEqual(verified_on.capabilities.source_for("reasoning_on"),
                         CapabilitySource.USER_VERIFIED)
        self.assertEqual(verified_on.capabilities.source_for("reasoning_off"),
                         CapabilitySource.MODEL_METADATA)
        verified_off = store.save_thinking_probe(
            profile, ReasoningMode.OFF, Support.UNSUPPORTED, "2026-09-30T00:01:00Z")
        self.assertEqual(verified_off.capabilities.reasoning_on, Support.SUPPORTED)
        self.assertEqual(verified_off.capabilities.reasoning_off, Support.UNSUPPORTED)
        self.assertEqual(verified_off.default_reasoning.mode, ReasoningMode.AUTO)
        self.assertEqual(verified_off.capabilities.source_for("reasoning_off"),
                         CapabilitySource.USER_VERIFIED)

    def test_metadata_web_endpoint_requires_explicit_action_and_uses_fake_gateway(self):
        calls = []

        class FakeGateway:
            def fetch_ollama_thinking_metadata(self, runtime):
                calls.append((runtime.service_id, runtime.model))
                return (False, True), True

        client = create_app(trace_path=self.root / "trace.jsonl",
                            custom_profiles_dir=self.root / "profiles",
                            capability_evidence_dir=self.root / "evidence",
                            real_gateway_factory=FakeGateway).test_client()
        profile_id = "ollama-qwen35-4b-local"
        self.assertEqual(calls, [])
        denied = client.post(f"/api/profiles/{profile_id}/metadata", json={})
        self.assertEqual(denied.get_json()["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        self.assertEqual(calls, [])
        response = client.post(f"/api/profiles/{profile_id}/metadata",
                               json={"confirm_network": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [("ollama", "qwen3.5:4b")])
        self.assertEqual(response.get_json()["profile"]["capabilities"]["thinking_on"]["source"],
                         "MODEL_METADATA")

    def test_thinking_probe_temporarily_gates_one_mode_and_persists_only_that_mode(self):
        calls = []
        profile_dir = self.root / "profiles"
        custom = CustomProfileStore(profile_dir).create({
            "display_name": "Unknown Ollama exact model", "service_id": "ollama",
            "model_family": "qwen", "adapter_id": "generic_openai_chat",
            "base_url": "http://127.0.0.1:11434/v1/", "model": "qwen3.5:4b",
            "secret_env": "", "provider_kind": "local"})

        class FakeGateway:
            def complete(self, request, runtime):
                calls.append((request.reasoning.mode, runtime.max_retries,
                              runtime.capabilities.reasoning_on,
                              runtime.capabilities.reasoning_off))
                return ModelResponse("OK", returned_model=runtime.model)

        client = create_app(trace_path=self.root / "trace.jsonl",
                            custom_profiles_dir=profile_dir,
                            capability_evidence_dir=self.root / "evidence",
                            real_gateway_factory=FakeGateway).test_client()
        response = client.post(f"/api/profiles/{custom.profile_id}/thinking-probe",
                               json={"mode": "on", "confirm_network": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [(ReasoningMode.ON, 0, Support.SUPPORTED, Support.UNKNOWN)])
        capabilities = response.get_json()["capability"]
        self.assertEqual(capabilities["thinking_on"]["source"], "USER_VERIFIED")
        self.assertEqual(capabilities["thinking_off"]["status"], "unknown")

    def test_adapter_metadata_uses_exact_model_and_local_show_endpoint_without_network(self):
        profile = next(p for p in _builtin_profiles() if p.profile_id == "ollama-qwen35-4b-local")
        runtime = ProfileRegistry([profile]).snapshot(profile.profile_id, {})
        calls = []

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"thinking": {"values": [False, True], "default": True}}

        class FakeClient:
            def __init__(self, **kwargs):
                self.assert_options = kwargs

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def post(self, url, *, json):
                calls.append((url, json))
                return FakeResponse()

        with patch("fishery_ai.openai_compatible_adapter.httpx.Client", FakeClient):
            values, default = OpenAICompatibleAdapter.fetch_ollama_thinking_metadata(runtime)
        self.assertEqual((values, default), ((False, True), True))
        self.assertEqual(calls, [("http://127.0.0.1:11434/api/show", {"model": "qwen3.5:4b"})])


if __name__ == "__main__":
    unittest.main()
