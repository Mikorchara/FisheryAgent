"""Application streaming stays offline through Flask's in-process client."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import socket
import unittest

from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.model_gateway import GatewayError, ModelEvent
from fishery_ai.model_options import Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
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

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "offline-fixture"}):
            response = self.client(lambda: OpenAICompatibleAdapter(forbidden_client)).post(
                "/api/analyze/stream", json=self.payload(
                    "deepseek-v4-flash-experimental", confirm_network=True))
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
        self.assertEqual(qwen.profile_status.value, "experimental")
        self.assertEqual(profiles["deepseek-v4-flash-experimental"].capabilities.streaming,
                         Support.UNKNOWN)

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
