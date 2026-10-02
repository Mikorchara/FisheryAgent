"""Offline integration tests for reviewed Cloud declarations and explicit single probes."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import socket
import unittest

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.contracts import AnalysisRequest, Mode, Usage, UsageSource
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.model_gateway import (GatewayError, ModelEvent, ModelMessage, ModelProfile,
                                     ModelRequest, ModelResponse, ProfileRegistry)
from fishery_ai.model_options import (CapabilitySource, GenerationOptions, ModelCapabilities,
    OptionValidationError, ReasoningMode, ReasoningOptions, Support, validate_options)
from fishery_ai.official_capabilities import apply_official_capabilities
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import _builtin_profiles, _effective_runtime_defaults, create_app


def forbidden(*_args, **_kwargs):
    raise AssertionError("offline test cannot access network")


class CloudCapabilityTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, name, forbidden)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(socket, "getaddrinfo", forbidden)
        guard.start()
        self.addCleanup(guard.stop)

    def profile(self, model="qwen-plus", service="dashscope", url=None):
        return ModelProfile(profile_id="test-profile", display_name="test", provider_kind="cloud",
            adapter_id="openai_chat", provider_id="custom", service_id=service, model=model,
            base_url=url or ("https://api.deepseek.com" if service == "deepseek_api"
                            else "https://dashscope.aliyuncs.com/compatible-mode/v1"))

    def app(self, gateway):
        return create_app(trace_path=self.root / "trace.jsonl",
            custom_profiles_dir=self.root / "profiles", capability_evidence_dir=self.root / "evidence",
            real_gateway_factory=lambda: gateway).test_client()

    def unknown_cloud_identity(self):
        return CustomProfileStore(self.root / "profiles").create({"display_name": "Unknown Qwen",
            "service_id": "dashscope", "model_family": "qwen", "adapter_id": "openai_chat",
            "base_url": "http://localhost:8812/v1/", "model": "qwen-plus", "secret_env": "",
            "provider_kind": "local"})

    def test_exact_official_model_matrix(self):
        for service, model, default, effort in (
            ("dashscope", "qwen-plus", False, ()),
            ("dashscope", "qwen3.8-flash", True, ("low", "medium", "xhigh")),
            ("dashscope", "qwen3.8-omni-flash", True, ("low", "medium", "xhigh")),
            ("deepseek_api", "deepseek-flash", True, ("low", "high", "max"))):
            with self.subTest(model=model):
                cap = apply_official_capabilities(self.profile(model, service)).capabilities
                self.assertEqual(cap.thinking_default, default)
                self.assertEqual(cap.effort_values, effort)
                for name in ("streaming", "reasoning_on", "reasoning_off", "streaming_usage",
                             "thinking_streaming_combination"):
                    self.assertEqual(getattr(cap, name), Support.SUPPORTED)
                    self.assertEqual(cap.source_for(name), CapabilitySource.OFFICIAL_DOCS)

    def test_official_declaration_never_inherits_by_name_or_family(self):
        p = self.profile()
        for changed in (replace(p, service_id="custom"), replace(p, model="qwen-plus-latest"),
                        replace(p, base_url="https://other.invalid/v1"),
                        replace(p, adapter_id="generic_openai_chat", service_id="custom")):
            self.assertEqual(apply_official_capabilities(changed).capabilities.reasoning_on, Support.UNKNOWN)
        self.assertEqual(apply_official_capabilities(replace(p, base_url=p.base_url + "/"))
                         .capabilities.reasoning_on, Support.SUPPORTED)

    def kwargs(self, profile, mode, effort=None, stream=False):
        runtime = ProfileRegistry([apply_official_capabilities(profile)]).snapshot(profile.profile_id, {})
        return OpenAICompatibleAdapter._kwargs(ModelRequest(Mode.CHAT, (ModelMessage("user", "OK"),),
            reasoning=ReasoningOptions(mode, effort)), runtime, stream=stream)

    def test_qwen_plus_auto_on_off_mapping(self):
        self.assertEqual(set(self.kwargs(self.profile(), ReasoningMode.AUTO)), {"model", "messages"})
        for mode in (ReasoningMode.ON, ReasoningMode.OFF):
            self.assertEqual(self.kwargs(self.profile(), mode)["extra_body"],
                             {"enable_thinking": mode == ReasoningMode.ON})

    def test_qwen_flash_exact_effort_mapping(self):
        kwargs = self.kwargs(self.profile("qwen3.8-flash"), ReasoningMode.ON, "medium", True)
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["extra_body"], {"enable_thinking": True})
        self.assertEqual(kwargs["stream_options"], {"include_usage": True})

    def test_qwen_omni_has_its_own_switch_mapping(self):
        p = self.profile("qwen3.8-omni-flash")
        self.assertEqual(self.kwargs(p, ReasoningMode.OFF)["reasoning_effort"], "none")
        self.assertEqual(self.kwargs(p, ReasoningMode.ON)["reasoning_effort"], "xhigh")
        self.assertEqual(self.kwargs(p, ReasoningMode.ON, "low")["reasoning_effort"], "low")
        self.assertNotIn("extra_body", self.kwargs(p, ReasoningMode.OFF))

    def test_deepseek_auto_on_off_and_effort_mapping(self):
        p = self.profile("deepseek-flash", "deepseek_api")
        self.assertNotIn("extra_body", self.kwargs(p, ReasoningMode.AUTO))
        self.assertEqual(self.kwargs(p, ReasoningMode.OFF)["extra_body"], {"thinking": {"type": "disabled"}})
        kwargs = self.kwargs(p, ReasoningMode.ON, "max", True)
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual(kwargs["reasoning_effort"], "max")
        with self.assertRaises(GatewayError) as caught:
            self.kwargs(p, ReasoningMode.OFF, "high")
        self.assertEqual(caught.exception.code, "OPTION_CONFLICT")

    def test_combination_requires_separate_capability_including_auto_default_on(self):
        caps = ModelCapabilities(streaming=Support.SUPPORTED, reasoning_on=Support.SUPPORTED,
                                 thinking_default=True)
        for mode in (ReasoningMode.AUTO, ReasoningMode.ON):
            with self.assertRaises(OptionValidationError) as caught:
                validate_options(GenerationOptions(), ReasoningOptions(mode), caps, streaming=True)
            self.assertEqual(caught.exception.option, "thinking_streaming_combination")

    def test_user_verification_retains_official_sources_after_restart(self):
        p = apply_official_capabilities(self.profile())
        store = CapabilityStore(self.root / "evidence")
        p = store.save_thinking_probe(p, ReasoningMode.ON, Support.SUPPORTED, "2026-10-01")
        loaded = store.apply(self.profile())
        self.assertEqual(loaded.capabilities.source_for("reasoning_on"), CapabilitySource.USER_VERIFIED)
        self.assertEqual(set(loaded.capabilities.sources_for("reasoning_on")),
                         {CapabilitySource.USER_VERIFIED, CapabilitySource.OFFICIAL_DOCS})
        self.assertEqual(loaded.capabilities.source_for("reasoning_off"), CapabilitySource.OFFICIAL_DOCS)

    def test_unknown_saved_defaults_preserved_but_snapshot_is_safe_and_immutable(self):
        p = replace(self.profile(url="http://localhost:8812/v1"),
            default_reasoning=ReasoningOptions(ReasoningMode.OFF), default_response_mode="streaming")
        runtime = ProfileRegistry([p]).snapshot(p.profile_id, {})
        self.assertEqual((runtime.default_reasoning.mode, runtime.default_response_mode),
                         (ReasoningMode.AUTO, "normal"))
        self.assertEqual(p.default_reasoning.mode, ReasoningMode.OFF)
        with self.assertRaises(FrozenInstanceError):
            runtime.model = "other"

    def test_thinking_probes_allow_unknown_and_record_on_off_independently(self):
        p = self.unknown_cloud_identity()
        calls = []
        class Fake:
            def complete(_, request, runtime):
                calls.append((request.reasoning.mode, runtime.max_retries, len(request.messages)))
                return ModelResponse("OK")
        client = self.app(Fake())
        denied = client.post("/api/analyze", json={"profile_id": p.profile_id, "scenario": "normal",
            "question": "test", "reasoning_mode": "on", "confirm_network": True})
        self.assertEqual(denied.get_json()["error_code"], "OPTION_UNKNOWN")
        self.assertFalse(calls)
        for mode in ("on", "off"):
            response = client.post(f"/api/profiles/{p.profile_id}/thinking-probe",
                                  json={"mode": mode, "confirm_network": True})
            self.assertEqual(response.status_code, 200)
            cap = response.get_json()["capability"]
            self.assertEqual(cap["thinking_" + mode]["source"], "USER_VERIFIED")
            self.assertEqual(cap["streaming"], "unknown")
            if mode == "on":
                self.assertEqual(cap["thinking_off"]["status"], "unknown")
        self.assertEqual(calls, [(ReasoningMode.ON, 0, 1), (ReasoningMode.OFF, 0, 1)])

    def test_thinking_network_failure_does_not_create_unsupported_record(self):
        p = self.unknown_cloud_identity()
        class Fake:
            def complete(_, request, runtime):
                raise GatewayError("READ_TIMEOUT")
        response = self.app(Fake()).post(f"/api/profiles/{p.profile_id}/thinking-probe",
            json={"mode": "off", "confirm_network": True})
        self.assertEqual(response.get_json()["error_code"], "READ_TIMEOUT")
        self.assertFalse((self.root / "evidence").exists())

    def test_explicit_thinking_refusal_records_only_requested_mode(self):
        p = self.unknown_cloud_identity()
        class Fake:
            def complete(_, request, runtime):
                raise GatewayError("THINKING_UNSUPPORTED")
        response = self.app(Fake()).post(f"/api/profiles/{p.profile_id}/thinking-probe",
            json={"mode": "off", "confirm_network": True}).get_json()
        self.assertEqual(response["status"], "unsupported")
        self.assertEqual(response["capability"]["thinking_off"]["status"], "unsupported")
        self.assertEqual(response["capability"]["thinking_on"]["status"], "unknown")

    def test_stream_probe_metrics_do_not_send_saved_thinking_default(self):
        p = self.unknown_cloud_identity()
        calls = []
        class Fake:
            def stream(_, request, runtime):
                calls.append((request.reasoning.mode, runtime.max_retries))
                yield ModelEvent(reasoning_delta="private debug")
                yield ModelEvent(delta="O")
                yield ModelEvent(delta="K", usage=Usage(2, 3, 5, 1, None, UsageSource.PROVIDER))
        result = self.app(Fake()).post(f"/api/profiles/{p.profile_id}/probe",
            json={"capability": "streaming", "confirm_network": True}).get_json()
        self.assertEqual((result["delta_count"], result["reasoning_delta_count"]), (2, 1))
        self.assertIsNotNone(result["ttft_ms"])
        self.assertEqual(result["usage"]["total_tokens"], 5)
        self.assertEqual(calls, [(ReasoningMode.AUTO, 0)])
        text = "".join(path.read_text(encoding="utf-8") for path in (self.root / "evidence").glob("*.json"))
        self.assertNotIn("private debug", text)
        self.assertEqual(result["capability"]["thinking_on"]["status"], "unknown")

    def test_combination_probe_success_without_reasoning_text_is_valid(self):
        p = self.unknown_cloud_identity()
        store = CapabilityStore(self.root / "evidence")
        p = store.save_streaming(p, Support.SUPPORTED, "now")
        store.save_thinking_probe(p, ReasoningMode.ON, Support.SUPPORTED, "now")
        calls = []
        class Fake:
            def stream(_, request, runtime):
                calls.append((request.reasoning.mode, runtime.max_retries))
                yield ModelEvent(delta="OK")
        result = self.app(Fake()).post(f"/api/profiles/{p.profile_id}/probe",
            json={"capability": "thinking_streaming_combination", "confirm_network": True}).get_json()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["reasoning_delta_count"], 0)
        self.assertEqual(result["capability"]["thinking_streaming_combination"]["source"], "USER_VERIFIED")
        self.assertEqual(result["capability"]["thinking_off"]["status"], "unknown")
        self.assertEqual(calls, [(ReasoningMode.ON, 0)])

    def test_combination_prerequisites_block_before_request(self):
        p = self.unknown_cloud_identity()
        result = self.app(None).post(f"/api/profiles/{p.profile_id}/probe",
            json={"capability": "thinking_streaming_combination", "confirm_network": True})
        self.assertEqual(result.get_json()["error_code"], "OPTION_CONFLICT")

    def test_combination_rejection_changes_neither_independent_capability(self):
        p = self.unknown_cloud_identity()
        store = CapabilityStore(self.root / "evidence")
        p = store.save_streaming(p, Support.SUPPORTED, "now")
        store.save_thinking_probe(p, ReasoningMode.ON, Support.SUPPORTED, "now")
        class Fake:
            def stream(_, request, runtime):
                raise GatewayError("THINKING_UNSUPPORTED")
                yield
        result = self.app(Fake()).post(f"/api/profiles/{p.profile_id}/probe",
            json={"capability": "thinking_streaming_combination", "confirm_network": True}).get_json()
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["capability"]["thinking_streaming_combination"]["status"], "unsupported")
        self.assertEqual(result["capability"]["streaming"], "supported")
        self.assertEqual(result["capability"]["thinking_on"]["status"], "supported")

    def test_probe_requires_confirmation_and_reverification_is_explicit(self):
        p = self.unknown_cloud_identity()
        client = self.app(None)
        self.assertEqual(client.post(f"/api/profiles/{p.profile_id}/thinking-probe",
            json={"mode": "on"}).status_code, 403)
        self.assertEqual(client.post(f"/api/profiles/{p.profile_id}/thinking-probe",
            json={"mode": "on", "confirm_network": True, "reverify": True})
            .get_json()["error_code"], "CAPABILITY_NOT_VERIFIED")

    def test_unknown_generic_thinking_mapping_is_not_guessed(self):
        p = CustomProfileStore(self.root / "profiles").create({"display_name": "generic Qwen",
            "service_id": "custom", "model_family": "qwen", "adapter_id": "generic_openai_chat",
            "base_url": "http://localhost:8812/v1", "model": "qwen-plus", "secret_env": "",
            "provider_kind": "local"})
        client = self.app(None)
        result = client.post(f"/api/profiles/{p.profile_id}/thinking-probe",
            json={"mode": "on", "confirm_network": True}).get_json()
        self.assertEqual(result["error_code"], "CAPABILITY_PROBE_UNSUPPORTED")
        cap = next(item for item in client.get("/api/config").get_json()["profiles"]
                   if item["profile_id"] == p.profile_id)
        self.assertFalse(cap["thinking_probe_available"])
        self.assertEqual(cap["capabilities"]["thinking_on"]["status"], "unknown")

    def test_sdk_thinking_refusal_is_narrow_and_never_exposes_provider_body(self):
        import httpx
        from openai import APIStatusError
        profile = replace(self.profile(), secret_env="TEST_FAKE_KEY")
        runtime = ProfileRegistry([apply_official_capabilities(profile)]).snapshot(
            "test-profile", {"TEST_FAKE_KEY": "fake-secret-123"})
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "OK"),), reasoning=ReasoningOptions(ReasoningMode.OFF))
        for message, expected in (("enable_thinking is unsupported for this model", "THINKING_UNSUPPORTED"),
                                  ("unknown model", "HTTP_400")):
            def fail(**_kwargs):
                response = httpx.Response(400, request=httpx.Request("POST", "http://offline.invalid"))
                raise APIStatusError("private provider exception", response=response,
                                     body={"error": {"message": message}})
            class Client:
                chat = SimpleNamespace(completions=SimpleNamespace(create=fail))
                def close(self): pass
            with self.assertRaises(GatewayError) as caught:
                OpenAICompatibleAdapter(lambda *_: Client()).complete(request, runtime)
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn("private", str(caught.exception))

    def test_reasoning_and_final_content_separate_through_sdk_and_application(self):
        final = json.dumps({"inference": "final inference", "recommendations": [], "uncertainty": []})
        def sdk_create(**kwargs):
            if kwargs.get("stream"):
                return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                    content=None, reasoning_content="debug reasoning"))], usage=None),
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                        content=final, reasoning_content=None))], usage=None)])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=final, reasoning_content="debug reasoning"))], usage=None, model="qwen-plus")
        class Client:
            chat = SimpleNamespace(completions=SimpleNamespace(create=sdk_create))
            def close(self): pass
        adapter = OpenAICompatibleAdapter(lambda *_: Client())
        client = self.app(adapter)
        with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "offline-placeholder"}):
            payload = {"profile_id": "qwen-plus-experimental", "scenario": "normal", "question": "test",
                       "confirm_network": True}
            normal = client.post("/api/analyze", json=payload).get_json()["result"]
            wire = client.post("/api/analyze/stream", json=payload).data.decode("utf-8")
        self.assertEqual(normal["inference"], "final inference")
        self.assertEqual(normal["reasoning_content"], "debug reasoning")
        self.assertIn("event: reasoning_delta", wire)
        self.assertIn("event: content_delta", wire)
        self.assertIn('"structured_parse_ok":true', wire)
        trace = (self.root / "trace.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("debug reasoning", trace)
        self.assertNotIn("offline-placeholder", trace)
        self.assertNotIn("offline-placeholder", wire)

    def test_ordinary_generic_normal_auto_remains_usable(self):
        p = ModelProfile("custom", "generic", "local", "http://localhost:9911/v1", "qwen-plus")
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "OK"),))
        kwargs = OpenAICompatibleAdapter._kwargs(request, ProfileRegistry([p]).snapshot(p.profile_id, {}), stream=False)
        self.assertEqual(set(kwargs), {"model", "messages"})


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
