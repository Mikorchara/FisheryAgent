"""Offline checks for A3.1.6 Profile runtime defaults and safe fallback."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import socket
import unittest

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.model_options import ReasoningMode, Support
from fishery_ai.model_gateway import ModelResponse
from fishery_ai.web import _builtin_profiles, create_app


def no_network(*_args, **_kwargs):
    raise AssertionError("network is forbidden in A3.1.6 tests")


class RuntimeDefaultsTests(unittest.TestCase):
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

    def fields(self, **overrides):
        return {"display_name": "Local preference", "service_id": "custom",
                "model_family": "unknown", "adapter_id": "generic_openai_chat",
                "base_url": "http://127.0.0.1:18888/v1", "model": "local-model",
                "secret_env": "", "provider_kind": "local",
                "default_thinking_mode": "on", "default_response_mode": "streaming",
                **overrides}

    def app(self, *, gateway_factory=None):
        return create_app(trace_path=self.root / "trace.jsonl",
                          custom_profiles_dir=self.root / "profiles",
                          capability_evidence_dir=self.root / "evidence",
                          real_gateway_factory=gateway_factory or (lambda: None))

    def test_custom_defaults_persist_but_unknown_capabilities_resolve_safely(self):
        store = CustomProfileStore(self.root / "profiles")
        profile = store.create(self.fields())
        data = json.loads(next((self.root / "profiles").glob("custom-*.json")).read_text("utf-8"))
        self.assertEqual(data["default_thinking_mode"], "on")
        self.assertEqual(data["default_response_mode"], "streaming")
        self.assertNotIn("api_key", data)
        loaded = store.load()[0]
        self.assertEqual(loaded.default_reasoning.mode, ReasoningMode.ON)
        self.assertEqual(loaded.default_response_mode, "streaming")

        client = self.app().test_client()
        public = next(item for item in client.get("/api/config").get_json()["profiles"]
                      if item["profile_id"] == profile.profile_id)
        self.assertEqual(public["default_reasoning_mode"], "auto")
        self.assertEqual(public["default_response_mode"], "normal")
        self.assertEqual(set(public["runtime_default_warnings"]),
                         {"THINKING_DEFAULT_FALLBACK", "RESPONSE_DEFAULT_FALLBACK"})
        detail = client.get(f"/api/profiles/{profile.profile_id}").get_json()
        self.assertEqual(detail["fields"]["default_thinking_mode"], "on")
        self.assertEqual(detail["fields"]["default_response_mode"], "streaming")

    def test_unknown_preferences_still_run_normal_with_safe_runtime_snapshot(self):
        profile = CustomProfileStore(self.root / "profiles").create(self.fields())
        snapshots = []

        class Gateway:
            def complete(self, request, runtime):
                snapshots.append((runtime.default_reasoning.mode, runtime.default_response_mode,
                                  request.reasoning))
                return ModelResponse('{"inference":"ok","recommendations":[],"uncertainty":[]}')

        client = self.app(gateway_factory=Gateway).test_client()
        response = client.post("/api/analyze", json={"profile_id": profile.profile_id,
            "scenario": "normal", "question": "offline check", "confirm_network": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(snapshots, [(ReasoningMode.AUTO, "normal", None)])

    def test_builtin_runtime_defaults_are_readonly_and_preserved(self):
        local = next(item for item in _builtin_profiles()
                     if item.profile_id == "ollama-qwen35-4b-local")
        self.assertEqual((local.default_reasoning.mode, local.default_response_mode),
                         (ReasoningMode.OFF, "normal"))
        client = self.app().test_client()
        detail = client.get(f"/api/profiles/{local.profile_id}").get_json()
        self.assertFalse(detail["editable"])
        self.assertEqual(detail["fields"]["default_thinking_mode"], "off")
        denied = client.put(f"/api/profiles/{local.profile_id}", json=self.fields())
        self.assertEqual(denied.status_code, 403)

    def test_explicit_defaults_conflicting_with_recorded_unsupported_are_rejected(self):
        store = CustomProfileStore(self.root / "profiles")
        profile = store.create(self.fields(default_thinking_mode="auto",
            default_response_mode="normal", service_id="ollama", model_family="qwen",
            adapter_id="generic_openai_chat", base_url="http://127.0.0.1:11434/v1",
            model="qwen3.5:4b"))
        evidence = CapabilityStore(self.root / "evidence")
        evidence.save_thinking_probe(profile, ReasoningMode.OFF, Support.UNSUPPORTED,
                                     "2026-09-30T00:00:00Z")
        evidence.save_streaming(profile, Support.UNSUPPORTED, "2026-09-30T00:01:00Z")
        client = self.app().test_client()
        exact_identity = {"service_id": "ollama", "model_family": "qwen",
                          "adapter_id": "generic_openai_chat",
                          "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3.5:4b"}

        thinking = client.put(f"/api/profiles/{profile.profile_id}", json=self.fields(
            default_thinking_mode="off", default_response_mode="normal", **exact_identity))
        self.assertEqual(thinking.status_code, 400, thinking.get_json())
        self.assertEqual(thinking.get_json()["error_code"], "PROFILE_DEFAULT_CONFLICT")
        self.assertEqual(thinking.get_json()["field"], "default_thinking_mode")

        streaming = client.put(f"/api/profiles/{profile.profile_id}", json=self.fields(
            default_thinking_mode="auto", default_response_mode="streaming", **exact_identity))
        self.assertEqual(streaming.status_code, 400)
        self.assertEqual(streaming.get_json()["error_code"], "PROFILE_DEFAULT_CONFLICT")
        self.assertEqual(streaming.get_json()["field"], "default_response_mode")


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from tests.support.historical_model_fixtures import install as _install_history
_install_history(globals())
