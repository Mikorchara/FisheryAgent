"""T5 offline diagnostic and Web tests; all stores and credentials are fictional."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import httpx
from openai import BadRequestError
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.credentials import CredentialStore, CredentialFileError
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ModelResponse, ModelToolCall, ProfileRegistry
from fishery_ai.model_options import CapabilitySource, Support
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tool_capability_probe import run_tool_calling_probe
from fishery_ai.tool_conversation import MockToolGateway, ToolCallingService
from fishery_ai.tools import ToolRegistry
from fishery_ai.web import create_app


class ToolCapabilityProbeTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                     "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(name, side_effect=AssertionError("T5 offline: network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.credentials = CredentialStore(process_env={"FAKE_TEST_KEY":"fictional-t5-secret"})
        self.profile = CustomProfileStore(self.root / "profiles").create({"display_name":"DS_1 fixture",
            "service_id":"deepseek_api", "adapter_id":"openai_chat", "model_family":"unknown",
            "base_url":"https://fake.invalid", "model":"fake-model", "secret_env":"FAKE_TEST_KEY",
            "provider_kind":"cloud"})
        self.runtime = ProfileRegistry([self.profile], self.credentials).snapshot(self.profile.profile_id)
        self.registry = ToolRegistry(CurrentWaterQualityReader(CurrentSnapshotStore(), stale_after_s=300), DiagnosisService())
        self.traces = JsonlTraceSink(self.root / "trace.jsonl")
        self.evidence = CapabilityStore(self.root / "evidence")
        self.gateway = MockToolGateway()

    def probe(self, gateway=None, runtime=None):
        return run_tool_calling_probe(gateway or self.gateway, self.profile, self.registry,
                                     self.traces, runtime=runtime or self.runtime)

    def web(self, gateway=None):
        self.factory = Mock(return_value=gateway or self.gateway)
        app = create_app(credential_store=self.credentials, trace_path=self.root / "web-trace.jsonl",
            custom_profiles_dir=self.root / "profiles", capability_evidence_dir=self.root / "evidence",
            manual_experiments_dir=self.root / "experiments", scenario_templates_dir=self.root / "templates",
            real_gateway_factory=self.factory)
        self.client = app.test_client()
        token = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin":"http://localhost", "X-CSRF-Token":token}

    def send(self, confirm=True, profile_id=None):
        handle = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        return self.client.post(f"/api/profiles/{profile_id or self.profile.profile_id}/tool-probe",
            headers=self.headers, json={"confirm_network":confirm, "request_id":handle["request_id"],
                                      "control_token":handle["control_token"]})

    def test_unknown_probe_success_but_ordinary_request_stays_blocked(self):
        ordinary = ToolCallingService(self.gateway, self.registry, self.traces).converse("现在水质？", self.runtime)
        self.assertEqual(ordinary.error_code, "OPTION_UNKNOWN")
        result = self.probe()
        self.assertEqual((result["verdict"], result["model_requests"], result["tool_result_status"]),
                         ("SUPPORTED", 2, "NO_DATA"))
        self.assertIs(self.runtime.capabilities.tool_calling, Support.UNKNOWN)
        self.assertFalse((self.root / "evidence").exists())

    def test_success_writes_explicit_probe_and_resolves_exact_identity(self):
        self.web()
        response = self.send()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue(result["evidence_written"])
        cap = result["profile"]["capabilities"]["tool_calling"]
        self.assertEqual((cap["status"], cap["source"]), ("supported", "explicit_probe"))
        reloaded = self.evidence.apply(self.profile)
        self.assertIs(reloaded.capabilities.tool_calling, Support.SUPPORTED)
        self.assertIs(reloaded.capabilities.source_for("tool_calling"), CapabilitySource.EXPLICIT_PROBE)
        other = replace(self.profile, model="other-exact-model", capabilities=replace(
            self.profile.capabilities, model_id="other-exact-model"), capability_basis=None)
        self.assertIs(self.evidence.apply(other).capabilities.tool_calling, Support.UNKNOWN)

    def test_timeout_auth_rate_limit_network_and_malformed_remain_unknown(self):
        for code in ("CONNECT_TIMEOUT", "READ_TIMEOUT", "HTTP_401", "HTTP_403", "HTTP_429",
                     "HTTP_503", "TLS_ERROR", "MODEL_TOOL_CALL_MALFORMED", "USER_CANCELLED"):
            with self.subTest(code=code):
                gateway = Mock(complete=Mock(side_effect=GatewayError(code)))
                self.web(gateway)
                result = self.send().get_json()
                self.assertEqual(result["verdict"], "UNKNOWN")
                self.assertFalse(result["evidence_written"])
                self.assertFalse((self.root / "evidence").exists())
                gateway.complete.assert_called_once()

    def test_no_tool_call_does_not_retry_or_grant_support(self):
        gateway = Mock(complete=Mock(return_value=ModelResponse("没有调用工具", finish_reason="stop")))
        result = self.probe(gateway)
        self.assertEqual((result["verdict"], result["error_code"], result["model_requests"]),
                         ("UNKNOWN", "NO_TOOL_CALL", 1))
        gateway.complete.assert_called_once()

    def test_second_failure_remains_unknown(self):
        first = ModelResponse(None, tool_calls=(ModelToolCall("call-fixture", "get_current_water_quality", "{}"),))
        gateway = Mock(complete=Mock(side_effect=[first, GatewayError("READ_TIMEOUT")]))
        result = self.probe(gateway)
        self.assertEqual(result["verdict"], "UNKNOWN")
        self.assertEqual(result["model_requests"], 2)
        self.assertEqual(result["tool_result_status"], "NO_DATA")

    def test_explicit_unsupported_is_only_negative_evidence(self):
        self.web(Mock(complete=Mock(side_effect=GatewayError("TOOL_UNSUPPORTED"))))
        result = self.send().get_json()
        self.assertEqual(result["verdict"], "UNSUPPORTED")
        self.assertTrue(result["evidence_written"])
        self.assertIs(self.evidence.apply(self.profile).capabilities.tool_calling, Support.UNSUPPORTED)

    def test_retry_zero_and_no_defaults_credentials_immutable(self):
        seen = []
        class Capture(MockToolGateway):
            def complete(gateway, request, runtime):
                seen.append((request, runtime))
                return super().complete(request, runtime)
        self.probe(Capture())
        self.assertEqual(len(seen), 2)
        for request, runtime in seen:
            self.assertEqual(runtime.max_retries, 0)
            self.assertIs(runtime.credential, self.runtime.credential)
            self.assertEqual(runtime.default_reasoning.mode.value, "auto")
            self.assertEqual(runtime.default_response_mode, "normal")
            self.assertEqual(runtime.default_generation.max_output_tokens, 256)
        self.assertEqual(seen[1][0].tool_choice, "none")
        self.assertNotIn("water_quality", seen[0][0].messages[0].content)

    def test_cancelled_before_probe_sends_nothing_and_writes_no_evidence(self):
        handle = RequestHandle()
        gateway = Mock()
        with request_scope(handle):
            handle.cancel()
            result = self.probe(gateway)
        self.assertEqual(result["verdict"], "UNKNOWN")
        self.assertEqual(result["model_requests"], 0)
        gateway.complete.assert_not_called()

    def test_different_runtime_identity_rejected(self):
        with self.assertRaises(GatewayError) as failure:
            self.probe(runtime=replace(self.runtime, model="other"))
        self.assertEqual(failure.exception.code, "PROFILE_IDENTITY_CHANGED")

    def test_cancel_after_first_response_does_not_send_second(self):
        handle = RequestHandle()
        class Cancel(MockToolGateway):
            def complete(gateway, request, runtime):
                response = super().complete(request, runtime)
                handle.cancel()
                return response
        with request_scope(handle):
            result = self.probe(Cancel())
        self.assertEqual((result["verdict"], result["model_requests"], result["request_2"]),
                         ("UNKNOWN", 1, "not_started"))

    def test_local_tool_error_does_not_grant_support(self):
        with patch("fishery_ai.tool_conversation.ToolExecutor.execute", side_effect=RuntimeError("fake private error")):
            result = self.probe()
        self.assertEqual(result["verdict"], "UNKNOWN")
        self.assertEqual(result["model_requests"], 1)
        self.assertNotIn("fake private error", json.dumps(result))

    def test_missing_credential_blocks_before_gateway_and_does_not_write_evidence(self):
        self.credentials = CredentialStore(process_env={})
        self.web()
        self.assertEqual(self.send().get_json()["error_code"], "SECRET_MISSING")
        self.factory.assert_not_called()
        self.assertFalse((self.root / "evidence").exists())

    def test_private_store_access_error_stops_before_real_request(self):
        self.web()
        with patch.object(self.credentials, "resolve", side_effect=CredentialFileError()):
            result = self.send().get_json()
        self.assertEqual(result["error_code"], "CREDENTIAL_FILE_ERROR")
        self.factory.assert_not_called()
        self.assertFalse((self.root / "evidence").exists())

    def test_unknown_tool_bad_args_multiple_and_second_tool_are_unknown(self):
        good = ModelToolCall("c1", "get_current_water_quality", "{}")
        cases = [(ModelToolCall("c1", "other", "{}"),),
                 (ModelToolCall("c1", "get_current_water_quality", '{"extra":1}'),),
                 (good, ModelToolCall("c2", "get_current_water_quality", "{}"))]
        for calls in cases:
            gateway = Mock(complete=Mock(return_value=ModelResponse(None, tool_calls=calls)))
            self.assertEqual(self.probe(gateway)["verdict"], "UNKNOWN")
            gateway.complete.assert_called_once()
        gateway = Mock(complete=Mock(side_effect=[ModelResponse(None, tool_calls=(good,))]*2))
        self.assertEqual(self.probe(gateway)["error_code"], "TOOL_ROUND_LIMIT")
        self.assertEqual(gateway.complete.call_count, 2)

    def test_network_confirmation_csrf_and_preset_read_only(self):
        self.web()
        self.assertEqual(self.send(False).get_json()["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        preset = next(p for p in self.client.get("/api/config").get_json()["profiles"] if p["access_mode"] == "preset")
        self.assertEqual(self.send(profile_id=preset["profile_id"]).get_json()["error_code"], "CAPABILITY_PROBE_UNSUPPORTED")
        self.assertEqual(self.client.post(f"/api/profiles/{self.profile.profile_id}/tool-probe",
                                         json={"confirm_network":True}).status_code, 403)
        self.factory.assert_not_called()

    def test_secret_not_in_json_trace_evidence_or_repr(self):
        self.web()
        result = self.send()
        serialized = result.get_data(as_text=True) + repr(self.runtime)
        serialized += (self.root / "web-trace.jsonl").read_text(encoding="utf-8")
        serialized += "".join(p.read_text(encoding="utf-8") for p in (self.root / "evidence").glob("*.json"))
        self.assertNotIn("fictional-t5-secret", serialized)
        self.assertNotIn("Authorization", serialized)

    def test_only_explicit_structured_model_rejection_maps_unsupported(self):
        for status, message, expected in ((400,"Tool calling is not supported by this model",True),
                (401,"Tool calling is not supported by this model",False),
                (429,"Tool calling is not supported by this model",False),
                (400,"Tool arguments schema is unsupported",False),
                (400,"Invalid tools parameter",False)):
            error = BadRequestError(message, response=httpx.Response(status, request=httpx.Request("POST", "https://fake.invalid")),
                                    body={"error":{"message":message}})
            self.assertEqual(OpenAICompatibleAdapter._is_explicit_tool_unsupported(error), expected)


if __name__ == "__main__":
    unittest.main()
