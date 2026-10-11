"""R5 explicit unknown-model probes, fake SDK and temporary evidence only."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import socket
import unittest

from fishery_ai.capability_probe import run_capability_probe
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.contracts import Mode, Usage, UsageSource
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.credentials import CredentialStore
from fishery_ai.model_gateway import (ModelProfile, ModelRequest, ModelResponse, ModelEvent,
                                     ProfileRegistry, GatewayError)
from fishery_ai.model_options import ReasoningMode, ReasoningOptions, Support, CapabilitySource
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import create_app


def forbidden(*_args, **_kwargs):
    raise AssertionError("offline tests prohibit network")


class UnknownModelProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, name, forbidden)
            guard.start(); self.addCleanup(guard.stop)
        guard = patch.object(socket, "getaddrinfo", forbidden)
        guard.start(); self.addCleanup(guard.stop)
        self.store = CustomProfileStore(self.root / "profiles")

    def profile(self, service="dashscope", model="unknown-exact-model"):
        return self.store.create(dict(display_name="Fixture " + service, service_id=service,
            model_family="unknown", adapter_id="openai_chat" if service in ("dashscope", "deepseek_api") else "generic_openai_chat",
            base_url="http://localhost:8111/v1/", model=model, secret_env="", auth_spec="NONE", provider_kind="local"))

    def client(self, gateway):
        return create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", real_gateway_factory=lambda: gateway).test_client()

    def test_unknown_dashscope_on_off_probe_body_then_business_gate(self):
        p = self.profile()
        calls = []
        class Fake:
            def complete(_, request, runtime):
                calls.append(OpenAICompatibleAdapter._kwargs(request, runtime, stream=False))
                self.assertEqual(runtime.max_retries, 0)
                self.assertEqual(runtime.default_reasoning.mode, ReasoningMode.AUTO)
                self.assertLessEqual(runtime.total_timeout_s, 60)
                return ModelResponse("OK", Usage(1, 1, 2, source=UsageSource.PROVIDER))
        client = self.client(Fake())
        denied = client.post("/api/analyze", json=dict(profile_id=p.profile_id, scenario="normal",
            question="test", reasoning_mode="on", confirm_network=True))
        self.assertEqual(denied.get_json()["error_code"], "OPTION_UNKNOWN")
        self.assertFalse(calls)
        for mode in ("on", "off"):
            result = client.post(f"/api/profiles/{p.profile_id}/thinking-probe", json=dict(mode=mode, confirm_network=True))
            self.assertEqual(result.status_code, 200)
            data = result.get_json()
            self.assertEqual(data["capability"]["thinking_" + mode]["source"], "USER_VERIFIED")
            self.assertEqual(calls[-1]["extra_body"], {"enable_thinking": mode == "on"})
            self.assertEqual(set(calls[-1]), {"model", "messages", "extra_body"})
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.root / "trace.jsonl").exists())

    def test_unknown_deepseek_protocol_does_not_imply_model_support(self):
        p = self.profile("deepseek_api")
        runtime = ProfileRegistry([p]).snapshot(p.profile_id, {})
        self.assertEqual(runtime.capabilities.reasoning_off, Support.UNKNOWN)
        seen = []
        class Fake:
            def complete(_, request, runtime):
                seen.append(OpenAICompatibleAdapter._kwargs(request, runtime, stream=False))
                return ModelResponse("OK")
        result = run_capability_probe(Fake(), p, "reasoning_off", runtime=runtime)
        self.assertEqual(result["status"], "success")
        self.assertEqual(seen[0]["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(runtime.capabilities.reasoning_off, Support.UNKNOWN)

    def test_generic_and_other_ollama_thinking_not_guessed(self):
        for service in ("custom", "ollama"):
            p = self.profile(service)
            class Never:
                def complete(*_): self.fail("unmapped protocol must not generate")
            result = run_capability_probe(Never(), p, "reasoning_on")
            self.assertEqual(result["error_code"], "CAPABILITY_PROBE_UNSUPPORTED")

    def test_unknown_streaming_probe_success_is_exact_and_restartable(self):
        p = self.profile("custom")
        class Fake:
            def stream(_, request, runtime):
                body = OpenAICompatibleAdapter._kwargs(request, runtime, stream=True)
                self.assertEqual(body["stream"], True)
                self.assertNotIn("stream_options", body)
                self.assertEqual(runtime.max_retries, 0)
                yield ModelEvent(delta="OK")
        client = self.client(Fake())
        denied = client.post("/api/analyze/stream", json=dict(profile_id=p.profile_id, scenario="normal", question="test", confirm_network=True))
        self.assertIn("OPTION_UNKNOWN", denied.get_data(as_text=True))
        response = client.post(f"/api/profiles/{p.profile_id}/probe", json=dict(capability="streaming", confirm_network=True))
        self.assertEqual(response.get_json()["delta_count"], 1)
        loaded = CapabilityStore(self.root / "evidence").apply(p)
        self.assertEqual(loaded.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(loaded.capabilities.source_for("streaming"), CapabilitySource.USER_VERIFIED)
        other = replace(p, model="unknown-exact-model-v2")
        self.assertEqual(CapabilityStore(self.root / "evidence").apply(other).capabilities.streaming, Support.UNKNOWN)

    def test_transport_and_ambiguous_http_failure_create_no_negative_evidence(self):
        p = self.profile()
        for code in ("CONNECT_TIMEOUT", "READ_TIMEOUT", "TLS_ERROR", "PROXY_ERROR", "HTTP_400", "STREAM_INTERRUPTED"):
            class Fake:
                def complete(_, request, runtime): raise GatewayError(code)
            result = self.client(Fake()).post(f"/api/profiles/{p.profile_id}/thinking-probe", json=dict(mode="off", confirm_network=True))
            self.assertEqual(result.get_json()["status"], "failure")
            self.assertFalse((self.root / "evidence").exists())

    def test_explicit_refusal_only_records_requested_capability(self):
        p = self.profile()
        class Fake:
            def complete(_, request, runtime): raise GatewayError("THINKING_UNSUPPORTED")
        data = self.client(Fake()).post(f"/api/profiles/{p.profile_id}/thinking-probe", json=dict(mode="off", confirm_network=True)).get_json()
        self.assertEqual(data["capability"]["thinking_off"]["status"], "unsupported")
        self.assertEqual(data["capability"]["thinking_on"]["status"], "unknown")
        self.assertEqual(len(list((self.root / "evidence").glob("*.json"))), 1)

    def test_explicit_confirmation_is_required_before_gateway(self):
        p = self.profile()
        response = self.client(None).post(f"/api/profiles/{p.profile_id}/thinking-probe", json=dict(mode="on"))
        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.root / "evidence").exists())

    def test_stream_needs_real_content_delta_not_usage_or_reasoning_only(self):
        p = self.profile("custom")
        class Fake:
            def stream(_, request, runtime):
                yield ModelEvent(reasoning_delta="fake debug", usage=Usage(1, 1, 2, source=UsageSource.PROVIDER))
        result = run_capability_probe(Fake(), p, "streaming")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["error_code"], "PROBE_NO_CONTENT")

    def test_probe_does_not_write_fake_secret_to_response_evidence_or_trace(self):
        p = self.store.create(dict(display_name="Credential fixture", service_id="dashscope",
            model_family="unknown", adapter_id="openai_chat", base_url="http://localhost:8111/v1",
            model="unknown-exact-model", secret_env="TEST_FAKE_KEY", auth_spec="REQUIRED_BEARER", provider_kind="local"))
        fake_value = "fictional-r5-test-value"
        env = self.root / "temporary.env"
        env.write_text("TEST_FAKE_KEY=" + fake_value + "\n", encoding="utf-8")
        credentials = CredentialStore(project_env_path=env, process_env={})
        class Fake:
            def complete(_, request, runtime):
                self.assertEqual(runtime.credential._for_adapter(), fake_value)
                self.assertNotIn(fake_value, repr(runtime))
                return ModelResponse("OK")
        client = create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", credential_store=credentials,
            real_gateway_factory=lambda: Fake()).test_client()
        response = client.post(f"/api/profiles/{p.profile_id}/thinking-probe", json=dict(mode="off", confirm_network=True))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(fake_value, response.get_data(as_text=True))
        for path in (self.root / "evidence").glob("*.json"):
            self.assertNotIn(fake_value, path.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "trace.jsonl").exists())
