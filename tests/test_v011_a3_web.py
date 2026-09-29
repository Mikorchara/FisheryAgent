"""Developer UI tests use Flask's in-process client; external sockets are forbidden."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import socket
import unittest

from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.model_gateway import GatewayError, ModelResponse
from fishery_ai.web import create_app


def _deny_network(*_args, **_kwargs):
    raise AssertionError("network is forbidden in UI tests")


class WebUITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace_path = Path(self.temp.name) / "web-traces.jsonl"
        self.socket_patch = patch.object(socket.socket, "connect", _deny_network)
        self.dns_patch = patch.object(socket, "getaddrinfo", _deny_network)
        self.socket_patch.start()
        self.dns_patch.start()
        self.addCleanup(self.socket_patch.stop)
        self.addCleanup(self.dns_patch.stop)

    def _client(self, gateway_factory=None):
        kwargs = {"trace_path": self.trace_path,
                  "custom_profiles_dir": Path(self.temp.name) / "custom_profiles"}
        if gateway_factory is not None:
            kwargs["real_gateway_factory"] = gateway_factory
        return create_app(**kwargs).test_client()

    @staticmethod
    def _payload(profile="mock-demo", **kwargs):
        return {"profile_id": profile, "scenario": "low_oxygen",
                "question": "当前水质怎么样？", **kwargs}

    def test_app_page_assets_and_safe_profile_config(self):
        client = self._client()
        self.assertEqual(client.get("/").status_code, 200)
        self.assertIn("开发验证台", client.get("/").get_data(as_text=True))
        self.assertEqual(client.get("/assets/app.css").status_code, 200)
        self.assertEqual(client.get("/assets/app.js").status_code, 200)
        self.assertEqual(client.get("/assets/unknown").status_code, 404)
        response = client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        config = response.get_json()
        self.assertEqual({item["provider"] for item in config["profiles"]},
                         {"mock", "qwen", "deepseek"})
        self.assertEqual({item["model"] for item in config["profiles"]},
                         {"offline-mock", "qwen-plus", "deepseek-flash"})
        self.assertEqual({item["profile_status"] for item in config["profiles"]
                          if item["runtime_type"] == "cloud"}, {"experimental"})
        self.assertIn("partial_stale", config["scenarios"])
        self.assertEqual({item["id"] for item in config["presets"]},
                         {"qwen", "deepseek", "custom"})
        self.assertIn("DASHSCOPE_API_KEY", response.get_data(as_text=True))
        self.assertNotIn("api_key", response.get_data(as_text=True))

    def test_mock_analyze_uses_existing_flow_and_unavailable_usage(self):
        with patch("fishery_ai.web.OpenAICompatibleAdapter") as adapter:
            client = self._client()
            response = client.post("/api/analyze", json=self._payload())
        adapter.assert_not_called()
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        result = payload["result"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["runtime"]["profile_id"], "mock-demo")
        self.assertEqual(result["observed_facts"]["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
        self.assertIn("OXYGEN_CRITICAL_LOW", [item["code"] for item in result["rule_results"]])
        self.assertTrue(result["evidence"])
        self.assertTrue(result["generated_text"])
        self.assertTrue(result["structured_parse_ok"])
        self.assertIsNone(result["usage"]["total_tokens"])
        self.assertEqual(result["usage"]["source"], "unavailable")
        self.assertGreaterEqual(payload["total_latency_ms"], 0)
        trace = self.trace_path.read_text(encoding="utf-8")
        self.assertNotIn("messages", trace)
        self.assertNotIn("api_key", trace)

    def test_profile_switch_keeps_provider_logic_out_of_web_flow(self):
        calls = []

        class FakeGateway:
            def complete(self, _request, runtime):
                calls.append((runtime.profile_id, runtime.provider_id, runtime.model))
                return ModelResponse(
                    json.dumps({"inference": "测试", "recommendations": ["检查"],
                                "uncertainty": []}, ensure_ascii=False),
                    Usage(4, 2, 6, source=UsageSource.PROVIDER),
                    returned_model=runtime.model)

        client = self._client(FakeGateway)
        self.assertEqual(client.post("/api/analyze", json=self._payload()).status_code, 200)
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "SENTINEL_SECRET",
                                     "DEEPSEEK_API_KEY": "SENTINEL_SECRET"}):
            for profile_id, expected_model in (("qwen-plus-experimental", "qwen-plus"),
                                               ("deepseek-v4-flash-experimental", "deepseek-flash")):
                response = client.post("/api/analyze", json=self._payload(
                    profile_id, confirm_network=True))
                self.assertEqual(response.status_code, 200)
                result = response.get_json()["result"]
                self.assertEqual(result["runtime"]["model"], expected_model)
                self.assertEqual(result["usage"]["total_tokens"], 6)
                self.assertNotIn("SENTINEL_SECRET", response.get_data(as_text=True))
        self.assertEqual([item[1] for item in calls], ["qwen", "deepseek"])
        self.assertNotIn("SENTINEL_SECRET", self.trace_path.read_text(encoding="utf-8"))

    def test_real_requests_need_confirmation_and_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            client = self._client(lambda: self.fail("gateway must not be created"))
            response = client.post("/api/analyze", json=self._payload(
                "qwen-plus-experimental"))
            self.assertEqual(response.get_json()["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
            response = client.post("/api/analyze", json=self._payload(
                "qwen-plus-experimental", confirm_network=True))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error_code"], "SECRET_MISSING")
            self.assertFalse(self.trace_path.exists())

    def test_gateway_and_unexpected_errors_are_safe(self):
        class FailedGateway:
            def complete(self, _request, _runtime):
                raise GatewayError("CONNECT_TIMEOUT")

        class BrokenGateway:
            def complete(self, _request, _runtime):
                raise RuntimeError("SENTINEL_SECRET")

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "SENTINEL_SECRET"}):
            client = self._client(FailedGateway)
            response = client.post("/api/analyze", json=self._payload(
                "qwen-plus-experimental", confirm_network=True))
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.get_json()["result"]["error_code"], "CONNECT_TIMEOUT")
            self.assertNotIn("SENTINEL_SECRET", response.get_data(as_text=True))
            broken = self._client(BrokenGateway)
            response = broken.post("/api/analyze", json=self._payload(
                "qwen-plus-experimental", confirm_network=True))
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.get_json()["error_code"], "INTERNAL_ERROR")
            self.assertNotIn("SENTINEL_SECRET", response.get_data(as_text=True))

    def test_bad_inputs_do_not_start_analysis(self):
        client = self._client(lambda: self.fail("gateway must not be created"))
        for body in ({"profile_id": "unknown", "scenario": "normal", "question": "test"},
                     self._payload(scenario="unknown"), self._payload(question="")):
            response = client.post("/api/analyze", json=body)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error_code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
