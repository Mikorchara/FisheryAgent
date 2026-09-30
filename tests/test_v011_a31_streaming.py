"""Application streaming stays offline through Flask's in-process client."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
import socket
import unittest

from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.model_gateway import GatewayError, ModelEvent
from fishery_ai.model_options import Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.web import _builtin_profiles, create_app


def _no_network(*_args, **_kwargs):
    raise AssertionError("network is forbidden in streaming tests")


def events(response):
    frames = response.get_data(as_text=True).strip().split("\n\n")
    return [(frame.split("\n", 1)[0][7:], json.loads(frame.split("data: ", 1)[1]))
            for frame in frames]


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace_path = self.root / "trace.jsonl"
        for target in ("connect", "connect_ex", "sendto"):
            blocker = patch.object(socket.socket, target, _no_network)
            blocker.start()
            self.addCleanup(blocker.stop)
        dns = patch.object(socket, "getaddrinfo", _no_network)
        dns.start()
        self.addCleanup(dns.stop)

    def client(self, gateway_factory=None):
        kwargs = {"trace_path": self.trace_path,
                  "custom_profiles_dir": self.root / "profiles"}
        if gateway_factory is not None:
            kwargs["real_gateway_factory"] = gateway_factory
        return create_app(**kwargs).test_client()

    @staticmethod
    def payload(profile="mock-demo", **kwargs):
        return {"profile_id": profile, "scenario": "low_oxygen",
                "question": "当前水质情况怎么样？", **kwargs}

    def test_mock_stream_order_facts_rules_evidence_deltas_usage_result_trace(self):
        client = self.client()
        response = client.post("/api/analyze/stream", json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Accel-Buffering"], "no")
        received = events(response)
        kinds = [kind for kind, _ in received]
        self.assertEqual(kinds[:4], ["analysis_started", "facts_ready",
                                     "rules_ready", "evidence_ready"])
        self.assertEqual(kinds[-2:], ["usage", "completed"])
        self.assertEqual(kinds.count("content_delta"), 2)
        facts = received[1][1]["observed_facts"]["water_quality"]
        self.assertEqual(facts["dissolved_oxygen_mg_l"], 2.2)
        self.assertEqual([x["code"] for x in received[2][1]["rule_results"]],
                         ["OXYGEN_CRITICAL_LOW"])
        self.assertFalse(any(x["category"] == "disease" for x in received[3][1]["evidence"]))
        raw = "".join(data["delta"] for kind, data in received if kind == "content_delta")
        self.assertEqual(raw, received[-1][1]["result"]["generated_text"])
        self.assertTrue(received[-1][1]["result"]["structured_parse_ok"])
        self.assertEqual(received[-2][1]["usage"]["source"], "unavailable")
        self.assertIsNotNone(received[-1][1]["ttft_ms"])
        self.assertGreaterEqual(received[-1][1]["total_latency_ms"], received[-1][1]["ttft_ms"])
        trace = self.trace_path.read_text(encoding="utf-8")
        self.assertIn('"status":"completed"', trace)
        self.assertNotIn("messages", trace)

    def test_normal_route_remains_available(self):
        response = self.client().post("/api/analyze", json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["result"]["structured_parse_ok"])

    def test_provider_usage_is_forwarded_without_raw_error_or_secret(self):
        calls = []

        class FakeGateway:
            def stream(self, _request, runtime):
                calls.append(runtime.profile_id)
                yield ModelEvent(delta='{"inference":"正常",')
                yield ModelEvent(delta='"recommendations":[],"uncertainty":[]}')
                yield ModelEvent(usage=Usage(8, 5, 13, source=UsageSource.PROVIDER))

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            response = self.client(FakeGateway).post("/api/analyze/stream", json=self.payload(
                "qwen-plus-experimental", confirm_network=True))
            received = events(response)
        self.assertEqual(calls, ["qwen-plus-experimental"])
        self.assertEqual([kind for kind, _ in received][-2:], ["usage", "completed"])
        self.assertEqual(received[-2][1]["usage"]["total_tokens"], 13)
        self.assertEqual(received[-1][1]["result"]["inference"], "正常")
        self.assertNotIn("offline-fixture", response.get_data(as_text=True))
        self.assertNotIn("offline-fixture", self.trace_path.read_text(encoding="utf-8"))

    def test_failure_after_content_preserves_partial_and_never_regenerates(self):
        calls = []

        class FailedGateway:
            def stream(self, _request, _runtime):
                calls.append("one")
                yield ModelEvent(delta="partial")
                raise GatewayError("READ_TIMEOUT")

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            response = self.client(FailedGateway).post("/api/analyze/stream", json=self.payload(
                "qwen-plus-experimental", confirm_network=True))
            received = events(response)
        self.assertEqual(calls, ["one"])
        self.assertEqual(received[-1][0], "failed")
        self.assertEqual(received[-1][1]["error_code"], "READ_TIMEOUT")
        self.assertEqual(received[-1][1]["result"]["generated_text"], "partial")
        self.assertEqual(received[-1][1]["result"]["status"], "failed")

    def test_pre_output_failure_and_confirmation_gate_are_safe(self):
        class FailedGateway:
            def stream(self, _request, _runtime):
                raise GatewayError("CONNECT_TIMEOUT")
                yield  # pragma: no cover

        with patch.dict(os.environ, {}, clear=True):
            client = self.client(lambda: self.fail("gateway should not be created"))
            self.assertEqual(client.post("/api/analyze/stream", json=self.payload(
                "qwen-plus-experimental")).get_json()["error_code"],
                "NETWORK_CONFIRMATION_REQUIRED")
            self.assertEqual(client.post("/api/analyze/stream", json=self.payload(
                "qwen-plus-experimental", confirm_network=True)).get_json()["error_code"],
                "SECRET_MISSING")
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            response = self.client(FailedGateway).post("/api/analyze/stream", json=self.payload(
                "qwen-plus-experimental", confirm_network=True))
            received = events(response)
        self.assertEqual(received[-1][0], "failed")
        self.assertEqual(received[-1][1]["error_code"], "CONNECT_TIMEOUT")
        self.assertEqual(received[-1][1]["result"]["generated_text"], "")

    def test_unexpected_stream_error_is_redacted(self):
        class BrokenGateway:
            def stream(self, _request, _runtime):
                raise RuntimeError("offline-fixture")
                yield  # pragma: no cover

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            response = self.client(BrokenGateway).post("/api/analyze/stream", json=self.payload(
                "qwen-plus-experimental", confirm_network=True))
            received = events(response)
        self.assertEqual(received[-1][1]["error_code"], "INTERNAL_ERROR")
        self.assertNotIn("offline-fixture", response.get_data(as_text=True))

    def test_unverified_real_streaming_stops_before_transport(self):
        def forbidden_client(*_args):
            self.fail("SDK client must not be created for unknown streaming capability")

        store = CustomProfileStore(self.root / "profiles")
        profile = store.create({"display_name": "未验证服务", "service_id": "custom",
                                "model_family": "unknown", "adapter_id": "generic_openai_chat",
                                "base_url": "http://localhost:11434/v1", "model": "local-model",
                                "secret_env": "", "provider_kind": "local"})
        with patch.dict(os.environ, {}, clear=True):
            response = self.client(lambda: OpenAICompatibleAdapter(forbidden_client)).post(
                "/api/analyze/stream", json=self.payload(
                    profile.profile_id, confirm_network=True))
            received = events(response)
        self.assertEqual(received[-1][0], "failed")
        self.assertEqual(received[-1][1]["error_code"], "OPTION_UNKNOWN")
        self.assertNotIn("offline-fixture", response.get_data(as_text=True))

    def test_qwen_streaming_support_is_scoped_to_exact_experimental_profile(self):
        profiles = {profile.profile_id: profile for profile in _builtin_profiles()}
        qwen = profiles["qwen-plus-experimental"]
        self.assertEqual(qwen.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(qwen.capabilities.model_id, qwen.model)
        self.assertEqual(qwen.capabilities.base_url, qwen.base_url)
        self.assertEqual(qwen.capabilities.service_id, qwen.service_id)
        self.assertEqual(qwen.capabilities.source_for("streaming").value, "USER_VERIFIED")
        self.assertEqual((qwen.service_id, qwen.model_family), ("dashscope", "qwen"))
        self.assertEqual(qwen.profile_status.value, "experimental")
        self.assertEqual(profiles["deepseek-v4-flash-experimental"].capabilities.streaming,
                         Support.SUPPORTED)

    def test_config_exposes_actual_scoped_streaming_capability(self):
        response = self.client().get("/api/config")
        self.assertEqual(response.status_code, 200)
        profiles = {item["profile_id"]: item for item in response.get_json()["profiles"]}
        qwen = profiles["qwen-plus-experimental"]["capabilities"]
        self.assertEqual({key: qwen[key] for key in
                          ("streaming", "streaming_scope_matches", "source")},
                         {"streaming": "supported", "streaming_scope_matches": True,
                          "source": "USER_VERIFIED"})
        deepseek = profiles["deepseek-v4-flash-experimental"]["capabilities"]
        self.assertEqual(deepseek["streaming"], "supported")
        self.assertEqual(deepseek["streaming_scope_matches"], True)
        self.assertEqual(deepseek["source"], "OFFICIAL_DOCS")
        html = self.client().get("/").get_data(as_text=True)
        self.assertIn('id="streaming-capability"', html)
        self.assertNotIn("Qwen Plus 实验配置已完成一次 Streaming 验证", html)

    def test_qwen_supported_capability_survives_reload_and_passes_adapter_gate_offline(self):
        received_kwargs = []

        class FakeCompletions:
            def create(self, **kwargs):
                received_kwargs.append(kwargs)
                payload = '{"inference":"已收到","recommendations":[],"uncertainty":[]}'
                chunk = SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=payload, reasoning_content=None))], usage=None)
                return iter([chunk])

        class FakeClient:
            chat = SimpleNamespace(completions=FakeCompletions())

            def close(self):
                pass

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            response = self.client(lambda: OpenAICompatibleAdapter(
                lambda _runtime, _timeout: FakeClient())).post(
                    "/api/analyze/stream", json=self.payload(
                        "qwen-plus-experimental", confirm_network=True))
            received = events(response)
        self.assertEqual(received[-1][0], "completed",
                         msg=f"safe terminal event: {received[-1]}")
        self.assertEqual(received[-1][1]["result"]["status"], "completed")
        self.assertEqual(len(received_kwargs), 1)
        self.assertEqual(received_kwargs[0]["model"], "qwen-plus")
        self.assertTrue(received_kwargs[0]["stream"])
        self.assertNotIn("offline-fixture", response.get_data(as_text=True))

    def test_custom_streaming_capability_remains_unknown_at_adapter_gate(self):
        from fishery_ai.model_gateway import ModelProfile, ProfileRegistry
        from fishery_ai.contracts import Mode
        from fishery_ai.model_gateway import ModelMessage, ModelRequest

        custom = ModelProfile(profile_id="custom-offline", display_name="Custom",
                              provider_kind="local", base_url="http://localhost:11434/v1",
                              model="custom-model", adapter_id="generic_openai_chat",
                              provider_id="custom")
        runtime = ProfileRegistry([custom]).snapshot(custom.profile_id, {})
        adapter = OpenAICompatibleAdapter(lambda *_args: self.fail("transport must not open"))
        with self.assertRaises(GatewayError) as caught:
            list(adapter.stream(ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),)), runtime))
        self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")

    def test_browser_has_streaming_selector_and_utf8_reader(self):
        client = self.client()
        html = client.get("/").get_data(as_text=True)
        script = client.get("/assets/app.js").get_data(as_text=True)
        self.assertIn('id="response-mode"', html)
        self.assertIn('id="streaming-output"', html)
        self.assertIn('id="advanced-settings"', html)
        self.assertIn("new TextDecoder(\"utf-8\")", script)
        self.assertIn("/api/analyze/stream", script)
        self.assertIn("$(\"analyze\").disabled = true", script)

    def test_new_profile_clears_previous_values_and_preset_leaves_model_open(self):
        script = self.client().get("/assets/app.js").get_data(as_text=True)
        reset = script.split("function newProfile() {", 1)[1].split("async function editSelected()", 1)[0]
        preset = script.split("function selectPreset() {", 1)[1].split("function newProfile()", 1)[0]
        for field in ("provider-preset", "custom-name", "custom-url", "custom-model"):
            self.assertIn(f'$("{field}").value = ""', reset)
        self.assertIn('$("advanced-settings").open = false', reset)
        self.assertIn('$("custom-model").value = ""', preset)
        self.assertIn('preset.id === "custom" ? "" : preset.base_url', preset)


if __name__ == "__main__":
    unittest.main()
