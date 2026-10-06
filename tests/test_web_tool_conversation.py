"""T4 Web integration: shared current store, offline Mock, existing Stop controls."""

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from fishery_ai.contracts import Status, parse_time
from fishery_ai.credentials import CredentialStore, CredentialSnapshot, CredentialStatus
from fishery_ai.model_gateway import ModelCapabilities, ModelProfile
from fishery_ai.model_options import Support
from fishery_ai.providers import AuthSpec
from fishery_ai.presets import preset_profiles
from fishery_ai.repositories import MockRepository
from fishery_ai.telemetry.scenario_templates import ScenarioTemplateStore
from fishery_ai.tool_conversation import MockToolGateway, ToolCallingService
from fishery_ai.web import create_app


NOW = parse_time("2026-10-05T02:00:00Z")


class WebToolConversationTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("T4 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root, self.now = Path(directory.name), NOW
        self.real_factory = Mock(side_effect=AssertionError("real gateway forbidden"))
        self.fast_mock = patch("fishery_ai.web.MockToolGateway", side_effect=lambda **_: MockToolGateway())
        self.fast_mock.start()
        self.addCleanup(self.fast_mock.stop)
        self.app = self.make_app()
        self.client = self.app.test_client()
        self.token = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin":"http://localhost", "X-CSRF-Token":self.token}
        self.store = self.app.extensions["fishery_snapshot_store"]
        self.reader = self.app.extensions["fishery_current_water_quality_reader"]

    def make_app(self):
        return create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", manual_experiments_dir=self.root / "experiments",
            scenario_templates_dir=self.root / "templates", credential_store=CredentialStore(process_env={}),
            scenario_clock=lambda:self.now, real_gateway_factory=self.real_factory)

    def prepare(self):
        data = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        return {"request_id":data["request_id"], "control_token":data["control_token"]}

    def run_tool(self, **changes):
        return self.client.post("/api/tool-conversation", json={"target":"mock", "response_mode":"normal",
            "question":"现在水质怎么样？", **self.prepare(), **changes}, headers=self.headers)

    def apply(self, identifier):
        response = self.client.post("/api/water-quality/apply", json={"template_id":identifier}, headers=self.headers)
        self.assertEqual(response.status_code, 200)

    def test_page_has_independent_normal_mock_entry(self):
        html = self.client.get("/").get_data(as_text=True)
        for name in ("tool-conversation-panel", "tool-question", "tool-run", "tool-stop", "tool-trace", "tool-answer"):
            self.assertIn('id="' + name + '"', html)
        self.assertIn("Mock Tool Calling · 完全离线", html)

    def test_initial_html_hides_experiment_workspace_and_has_normal_entry_and_return(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="development-workspace" hidden', html)
        self.assertIn('id="tool-conversation-panel" class="advanced-settings" hidden', html)
        self.assertIn('id="use-development"', html)
        self.assertIn('id="return-normal"', html)
        self.assertIn('id="tool-origin-target"', html)
        self.assertIn("更新快照状态显示", html)
        self.assertNotIn("当前选中 Runtime · 受能力门禁保护", html)

    def test_snapshot_display_read_does_not_apply_or_mutate(self):
        self.apply("normal")
        original = self.store.get_current()
        self.now += timedelta(hours=1)
        with patch("fishery_ai.web.apply_scenario_template", side_effect=AssertionError("display must not apply")), \
             patch.object(self.reader, "query", wraps=self.reader.query) as query:
            response = self.client.get("/api/water-quality/current")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["snapshot"]["freshness"], "stale")
        query.assert_called_once_with()
        self.assertIs(self.store.get_current(), original)
        self.assertEqual(original.freshness.value, "fresh")

    def test_no_data_still_gets_second_model_explanation(self):
        response = self.run_tool()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]
        self.assertEqual(result["snapshot_status"], "NO_DATA")
        self.assertEqual(result["tool_result"]["status"], "NO_DATA")
        self.assertEqual(result["request_2"]["outcome"], "final_answer")
        self.assertIn("没有当前水质数据", result["generated_text"])
        self.assertIsNone(self.store.get_current())
        self.real_factory.assert_not_called()

    def test_normal_available_trace_and_final(self):
        self.apply("normal")
        original = self.store.get_current()
        result = self.run_tool().get_json()["result"]
        self.assertEqual(result["snapshot_status"], "AVAILABLE")
        self.assertEqual(result["tool_call"]["name"], "get_current_water_quality")
        self.assertEqual(result["tool_call"]["arguments"], {})
        self.assertEqual(result["tool_result"]["status"], "OK")
        self.assertEqual(result["tool_result"]["water_quality"]["freshness"], "fresh")
        self.assertEqual(result["tool_result"]["findings"], [])
        self.assertEqual(result["status"], "completed")
        self.assertIs(self.store.get_current(), original)

    def test_concept_direct_answer_without_tool_or_reader(self):
        with patch.object(self.reader, "query") as query:
            result = self.run_tool(question="什么是溶氧？").get_json()["result"]
        self.assertIsNone(result["tool_call"])
        self.assertIsNone(result["tool_result"])
        self.assertEqual(result["request_2"]["outcome"], "not_started")
        self.assertIn("水中溶解的氧气", result["generated_text"])
        query.assert_not_called()

    def test_low_oxygen_result_reaches_final(self):
        self.apply("low_oxygen")
        result = self.run_tool().get_json()["result"]
        self.assertIn("OXYGEN_CRITICAL_LOW", [f["code"] for f in result["tool_result"]["findings"]])
        self.assertIn("2.2", result["generated_text"])

    def test_query_time_stale_without_mutating_store(self):
        self.apply("normal")
        original = self.store.get_current()
        self.now += timedelta(hours=1)
        result = self.run_tool().get_json()["result"]
        self.assertEqual(result["tool_result"]["water_quality"]["freshness"], "stale")
        self.assertIn("SENSOR_STALE", [f["code"] for f in result["tool_result"]["findings"]])
        self.assertIs(self.store.get_current(), original)
        self.assertEqual(original.freshness.value, "fresh")

    def test_invalid_snapshot_is_successful_read(self):
        template = {"schema_version":"scenario-template-v1", "id":"invalid-fixture", "display_name":"Invalid",
            "observed_age_s":0, "water_quality":{
                "temperature_c":{"state":"INVALID"}, "ph":{"state":"NORMAL","value":7.5},
                "dissolved_oxygen_mg_l":{"state":"NORMAL","value":2.2}}}
        response = self.client.post("/api/water-quality/apply", json={"template":template}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        result = self.run_tool().get_json()["result"]
        self.assertEqual(result["tool_result"]["status"], "OK")
        self.assertEqual(result["tool_result"]["water_quality"]["quality"], "invalid")
        self.assertIn("SENSOR_INVALID", [f["code"] for f in result["tool_result"]["findings"]])

    def test_custom_34_c_low_oxygen_applied_via_existing_api(self):
        template = {"schema_version":"scenario-template-v1", "id":"temporary", "display_name":"34 C",
            "device_id":"fake-device", "observed_age_s":0, "water_quality":{
                "temperature_c":{"state":"NORMAL","value":34}, "ph":{"state":"NORMAL","value":7.5},
                "dissolved_oxygen_mg_l":{"state":"NORMAL","value":2.2}}}
        response = self.client.post("/api/water-quality/apply", json={"template":template}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        result = self.run_tool().get_json()["result"]
        self.assertEqual(result["tool_result"]["water_quality"]["temperature_c"], 34)
        self.assertEqual([f["code"] for f in result["tool_result"]["findings"]],
                         ["TEMP_CRITICAL_HIGH", "OXYGEN_CRITICAL_LOW"])

    def test_only_existing_reader_and_t3_are_used(self):
        self.apply("low_oxygen")
        original = ToolCallingService.converse
        readers = []
        def converse(service, *args):
            readers.append(service.registry.lookup("get_current_water_quality").handler.keywords["reader"])
            return original(service, *args)
        with patch.object(ToolCallingService, "converse", new=converse), \
             patch.object(MockRepository, "water_quality", side_effect=AssertionError("no fallback")), \
             patch.object(ScenarioTemplateStore, "get_template", side_effect=AssertionError("no scenarios")), \
             patch.object(self.reader, "query", wraps=self.reader.query) as query:
            self.assertEqual(self.run_tool().status_code, 200)
        self.assertEqual(readers, [self.reader])
        query.assert_called_once_with()

    def test_scenario_or_raw_transport_injection_rejected_without_apply(self):
        for field in ("scenario", "template", "reading", "tools", "body", "base_url"):
            with self.subTest(field=field):
                response = self.run_tool(**{field:"normal"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error_code"], "INVALID_REQUEST")
        self.assertIsNone(self.store.get_current())

    def test_streaming_rejected_before_gateway(self):
        with patch.object(ToolCallingService, "converse") as converse:
            response = self.run_tool(response_mode="streaming")
        self.assertEqual(response.get_json()["error_code"], "TOOL_STREAMING_NOT_IMPLEMENTED")
        self.assertEqual(response.status_code, 400)
        converse.assert_not_called()

    def test_unpublished_current_profiles_remain_gated(self):
        config = self.client.get("/api/config").get_json()
        published = {p.profile_id for p in preset_profiles() if p.capabilities.tool_calling == Support.SUPPORTED}
        for profile in config["profiles"]:
            if profile["runtime_type"] == "mock" or profile["profile_id"] in published:
                continue
            response = self.run_tool(target="selected", profile_id=profile["profile_id"], confirm_network=True)
            self.assertIn(response.get_json()["error_code"], ("OPTION_UNKNOWN", "OPTION_UNSUPPORTED"))
        self.real_factory.assert_not_called()

    def test_published_ollama_enters_existing_tool_path_with_offline_gateway(self):
        profile = next(p for p in preset_profiles() if p.model == "qwen3.5:4b" and p.preset_variant == "off")
        self.real_factory.side_effect = None
        self.real_factory.return_value = MockToolGateway()
        response = self.run_tool(target="selected", profile_id=profile.profile_id, confirm_network=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["result"]["tool_result"]["status"], "NO_DATA")
        self.assertEqual(response.get_json()["result"]["request_2"]["outcome"], "final_answer")
        self.real_factory.assert_called_once_with()

    def test_mock_fixture_does_not_change_profile_or_evidence(self):
        before = self.client.get("/api/config").get_json()
        self.run_tool()
        self.assertEqual(self.client.get("/api/config").get_json(), before)
        self.assertFalse((self.root / "evidence").exists())

    def test_selected_fixture_exact_capability_gate_and_confirmation(self):
        # Synthetic profiles only; a fake factory never opens HTTP or resolves a real key.
        for support, model, expected in (
                (Support.UNKNOWN, "fixture-model", "OPTION_UNKNOWN"),
                (Support.UNSUPPORTED, "fixture-model", "OPTION_UNSUPPORTED"),
                (Support.SUPPORTED, "fixture-model", None)):
            profile = ModelProfile("t4-fixture", "T4 Offline Fixture", "local", "http://fixture.invalid/v1",
                "fixture-model", auth_spec=AuthSpec.NONE, max_retries=0, capabilities=ModelCapabilities(
                    tool_calling=support, service_id="custom", adapter_id="generic_openai_chat",
                    base_url="http://fixture.invalid/v1", model_id=model))
            self.real_factory.reset_mock()
            self.real_factory.side_effect = None
            self.real_factory.return_value = MockToolGateway()
            with self.subTest(support=support, model=model), \
                 patch("fishery_ai.web._builtin_profiles", return_value=(profile,)), \
                 patch("fishery_ai.web.CapabilityStore.apply", side_effect=lambda value:value):
                app = self.make_app()
                client = app.test_client()
                token = client.get("/api/credential-session").get_json()["csrf_token"]
                headers = {"Origin":"http://localhost", "X-CSRF-Token":token}
                def send(confirm):
                    handle = client.post("/api/requests", json={}, headers=headers).get_json()
                    return client.post("/api/tool-conversation", headers=headers, json={"target":"selected",
                        "profile_id":profile.profile_id, "confirm_network":confirm, "question":"现在水质怎么样？",
                        "request_id":handle["request_id"], "control_token":handle["control_token"]})
                if expected:
                    self.assertEqual(send(True).get_json()["error_code"], expected)
                    self.real_factory.assert_not_called()
                else:
                    self.assertEqual(send(False).get_json()["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
                    self.real_factory.assert_not_called()
                    self.assertEqual(send(True).get_json()["result"]["tool_result"]["status"], "NO_DATA")
                    self.real_factory.assert_called_once_with()

    def test_tool_errors_are_safe_and_visible(self):
        captured = []
        original = ToolCallingService.converse
        def capture(service, *args):
            result = original(service, *args)
            captured.append(result)
            return result
        with patch.object(ToolCallingService, "converse", new=capture):
            self.assertEqual(self.run_tool().status_code, 200)
        for code in ("UNKNOWN_TOOL","INVALID_TOOL_ARGUMENTS","TOOL_EXECUTION_ERROR","TOOL_CALL_LIMIT","TOOL_ROUND_LIMIT"):
            failure = replace(captured[0], status=Status.FAILED, generated_text="", error_code=code)
            with self.subTest(code=code), patch.object(ToolCallingService, "converse", return_value=failure):
                response = self.run_tool()
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.get_json()["result"]["error_code"], code)

    def test_unclassified_exception_never_exposes_details(self):
        with patch.object(ToolCallingService, "converse", side_effect=RuntimeError("fake-private-exception")):
            response = self.run_tool()
        self.assertEqual(response.get_json()["error_code"], "INTERNAL_ERROR")
        self.assertNotIn("fake-private-exception", response.get_data(as_text=True))

    def test_required_request_handle_csrf_and_origin(self):
        response = self.client.post("/api/tool-conversation", json={"question":"现在水质怎么样？"})
        self.assertEqual(response.get_json()["error_code"], "ORIGIN_NOT_ALLOWED")
        response = self.client.post("/api/tool-conversation", json={"question":"现在水质怎么样？"}, headers={"Origin":"http://localhost"})
        self.assertEqual(response.get_json()["error_code"], "CSRF_INVALID")
        response = self.client.post("/api/tool-conversation", json={"question":"现在水质怎么样？"}, headers=self.headers)
        self.assertEqual(response.get_json()["error_code"], "REQUEST_NOT_FOUND")

    def test_cancel_existing_handle_prevents_follow_up(self):
        started, release = threading.Event(), threading.Event()
        seen = []
        class SlowMock(MockToolGateway):
            def complete(self, request, runtime):
                seen.append(request)
                started.set()
                if not release.wait(3):
                    raise AssertionError("test release missing")
                return super().complete(request, runtime)
        payload = {"target":"mock", "question":"现在水质怎么样？", **self.prepare()}
        cookie = self.client.get_cookie("fishery_local_session").value
        responses = []
        def run():
            worker = self.app.test_client()
            worker.set_cookie("fishery_local_session", cookie)
            responses.append(worker.post("/api/tool-conversation", json=payload, headers=self.headers))
        with patch("fishery_ai.web.MockToolGateway", side_effect=lambda **_:SlowMock()):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(3))
                self.client.post(f"/api/requests/{payload['request_id']}/cancel",
                    json={"control_token":payload["control_token"]}, headers=self.headers)
            finally:
                release.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(seen), 1)
        self.assertEqual(responses[0].get_json()["result"]["error_code"], "USER_CANCELLED")
        state = self.client.post(f"/api/requests/{payload['request_id']}/status",
            json={"control_token":payload["control_token"]}, headers=self.headers).get_json()
        self.assertEqual(state["state"], "CANCELLED")

    def test_public_response_omits_credential_paths_and_internal_prompt(self):
        self.apply("normal")
        public = self.run_tool().get_data(as_text=True)
        for field in ("api_key", "credential_ref", "Authorization", "base_url", "_content_json", "SYSTEM_INSTRUCTION"):
            self.assertNotIn(field, public)
        self.assertNotIn("source", json.loads(public)["result"]["tool_result"]["water_quality"])

    def test_echoed_fictional_credential_is_redacted_from_public_result(self):
        fake = "fictional-t4-credential-never-real"
        original = ToolCallingService.converse
        def echoed(service, *args):
            result = original(service, *args)
            return replace(result, generated_text=fake)
        snapshot = CredentialSnapshot(fake, CredentialStatus("PRESENT", "PROCESS_ENV", False))
        with patch.object(CredentialStore, "resolve", return_value=snapshot), \
             patch.object(ToolCallingService, "converse", new=echoed):
            response = self.run_tool()
        self.assertEqual(response.get_json()["result"]["generated_text"], "[REDACTED]")
        self.assertNotIn(fake, response.get_data(as_text=True))
        self.assertNotIn(fake, (self.root / "trace.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
