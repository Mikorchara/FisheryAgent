"""Targeted, offline coverage for exact Ollama Qwen reasoning controls."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from types import SimpleNamespace

from fishery_ai.contracts import Mode
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.model_gateway import (GatewayError, ModelEvent, ModelMessage, ModelProfile,
                                      ModelRequest, ModelResponse, ProfileRegistry)
from fishery_ai.model_options import ReasoningMode, ReasoningOptions, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import _builtin_profiles, create_app


OLLAMA_FIELDS = {
    "display_name": "Ollama Qwen3.5 4B",
    "service_id": "custom",
    "model_family": "unknown",
    "adapter_id": "generic_openai_chat",
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "qwen3.5:4b",
    "secret_env": "",
    "provider_kind": "local",
}


def make_request(mode: ReasoningMode) -> ModelRequest:
    return ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),),
                        reasoning=ReasoningOptions(mode))


class OllamaReasoningAdapterTests(unittest.TestCase):
    def setUp(self):
        self.profile = next(profile for profile in _builtin_profiles()
                            if profile.profile_id == "ollama-qwen35-4b-local")
        self.runtime = ProfileRegistry([self.profile]).snapshot(self.profile.profile_id, {})

    def test_auto_omits_reasoning_control_and_off_sends_explicit_none(self):
        automatic = OpenAICompatibleAdapter._kwargs(
            make_request(ReasoningMode.AUTO), self.runtime, stream=False)
        disabled = OpenAICompatibleAdapter._kwargs(
            make_request(ReasoningMode.OFF), self.runtime, stream=False)
        self.assertNotIn("reasoning_effort", automatic)
        self.assertEqual(disabled["reasoning_effort"], "none")
        self.assertNotIn("think", disabled)
        self.assertNotIn("extra_body", disabled)

    def test_complete_passes_off_control_to_sdk_call_without_network(self):
        sdk_calls = []

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        sdk_calls.append(kwargs)
                        message = SimpleNamespace(content="OK", reasoning_content=None)
                        choice = SimpleNamespace(message=message)
                        return SimpleNamespace(choices=[choice], usage=None, model="qwen3.5:4b")

            @staticmethod
            def close():
                pass

        adapter = OpenAICompatibleAdapter(lambda _runtime, _timeout: FakeClient())
        response = adapter.complete(make_request(ReasoningMode.OFF), self.runtime)
        self.assertEqual(response.text, "OK")
        self.assertEqual(sdk_calls[0]["reasoning_effort"], "none")
        self.assertNotIn("stream", sdk_calls[0])

    def test_on_requests_thinking_only_for_exact_local_ollama_model(self):
        enabled = OpenAICompatibleAdapter._kwargs(
            make_request(ReasoningMode.ON), self.runtime, stream=False)
        self.assertEqual(enabled["reasoning_effort"], "high")

        other_model = ModelProfile(
            profile_id="other-local", display_name="Other local model",
            provider_kind="local", base_url=OLLAMA_FIELDS["base_url"],
            model="llama3.2:3b", adapter_id="generic_openai_chat", provider_id="custom",
            service_id="custom")
        other_runtime = ProfileRegistry([other_model]).snapshot(other_model.profile_id, {})
        with self.assertRaises(GatewayError) as caught:
            OpenAICompatibleAdapter._kwargs(make_request(ReasoningMode.OFF), other_runtime,
                                            stream=False)
        self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")

    def test_reasoning_control_does_not_mark_streaming_supported(self):
        self.assertEqual(self.runtime.capabilities.streaming, Support.UNKNOWN)
        with self.assertRaises(GatewayError) as caught:
            OpenAICompatibleAdapter._kwargs(make_request(ReasoningMode.OFF), self.runtime,
                                            stream=True)
        self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")
        self.assertEqual(caught.exception.option, "streaming")

    def test_local_timeout_defaults_are_finite_and_cloud_defaults_stay_unchanged(self):
        self.assertEqual((self.profile.read_timeout_s, self.profile.total_timeout_s), (120, 180))
        cloud_fields = {**OLLAMA_FIELDS, "display_name": "Cloud test", "service_id": "custom",
                        "adapter_id": "generic_openai_chat", "base_url": "https://example.com/v1",
                        "model": "example-model", "secret_env": "EXAMPLE_API_KEY",
                        "provider_kind": "cloud"}
        cloud, _ = CustomProfileStore.build(cloud_fields, "custom-cloud")
        self.assertEqual((cloud.read_timeout_s, cloud.total_timeout_s), (30, 120))

        with TemporaryDirectory() as directory:
            store = CustomProfileStore(Path(directory))
            store.create(OLLAMA_FIELDS)
            loaded = store.load()[0]
            self.assertEqual((loaded.read_timeout_s, loaded.total_timeout_s), (120, 180))
            saved = next(Path(directory).glob("custom-*.json"))
            self.assertNotIn("read_timeout_s", json.loads(saved.read_text(encoding="utf-8")))
            self.assertNotIn("api_key", saved.read_text(encoding="utf-8").lower())


class OllamaReasoningWebTests(unittest.TestCase):
    def test_ui_advertises_exact_controls_and_analysis_preserves_selected_mode(self):
        captured = []

        class FakeGateway:
            def complete(self, request, runtime):
                captured.append((request, runtime))
                return ModelResponse(json.dumps({
                    "inference": "mocked", "recommendations": [], "uncertainty": []
                }), returned_model=runtime.model)

            def stream(self, request, runtime):
                captured.append((request, runtime))
                yield ModelEvent(delta=json.dumps({
                    "inference": "mocked", "recommendations": [], "uncertainty": []
                }))

        with TemporaryDirectory() as directory:
            profiles_dir = Path(directory) / "profiles"
            store = CustomProfileStore(profiles_dir)
            profile = next(profile for profile in _builtin_profiles()
                           if profile.profile_id == "ollama-qwen35-4b-local")
            client = create_app(
                trace_path=Path(directory) / "trace.jsonl",
                custom_profiles_dir=profiles_dir,
                capability_evidence_dir=Path(directory) / "capabilities",
                real_gateway_factory=FakeGateway,
            ).test_client()

            public_profiles = {item["profile_id"]: item for item in
                               client.get("/api/config").get_json()["profiles"]}
            public = public_profiles[profile.profile_id]
            self.assertEqual(public["reasoning_modes"], ["auto", "on", "off"])
            self.assertEqual(public["capabilities"]["streaming"], "unknown")
            response = client.post("/api/analyze", json={
                "profile_id": profile.profile_id, "scenario": "low_oxygen",
                "question": "当前水质怎么样？", "confirm_network": True,
                "reasoning_mode": "off",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured[0][0].reasoning, ReasoningOptions(ReasoningMode.OFF))
            streamed = client.post("/api/analyze/stream", json={
                "profile_id": profile.profile_id, "scenario": "low_oxygen",
                "question": "当前水质怎么样？", "confirm_network": True,
                "reasoning_mode": "off",
            })
            self.assertEqual(streamed.status_code, 200)
            self.assertIn("event: completed", streamed.get_data(as_text=True))
            self.assertEqual(captured[1][0].reasoning, ReasoningOptions(ReasoningMode.OFF))

    def test_reasoning_mode_cannot_be_requested_for_unrelated_custom_profile(self):
        with TemporaryDirectory() as directory:
            profiles_dir = Path(directory) / "profiles"
            store = CustomProfileStore(profiles_dir)
            fields = {**OLLAMA_FIELDS, "display_name": "Other compatible local",
                      "base_url": "http://127.0.0.1:8080/v1", "model": "other-model"}
            profile = store.create(fields)
            client = create_app(custom_profiles_dir=profiles_dir,
                                trace_path=Path(directory) / "trace.jsonl",
                                capability_evidence_dir=Path(directory) / "capabilities",
                                real_gateway_factory=lambda: self.fail("must not create gateway"))
            response = client.test_client().post("/api/analyze", json={
                "profile_id": profile.profile_id, "scenario": "low_oxygen",
                "question": "test", "confirm_network": True, "reasoning_mode": "off",
            })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error_code"], "OPTION_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
