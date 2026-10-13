"""Offline Web 2/2/3 + real Registry/Handler/Activity integration; no Provider sockets."""

from dataclasses import FrozenInstanceError, replace
import json
from unittest.mock import patch

from fishery_ai.assistant import ALLOWED_PRESET_IDS, AssistantError, assistant_profile
from fishery_ai.assistant_execution import (AssistantExecutionConfig, AssistantMultiRoundRelease,
    load_assistant_execution_config, release_scope, resolve_execution_profile)
from fishery_ai.credentials import CredentialStore
from fishery_ai.history_projection import DEFAULT_HISTORY_PROJECTION, ProjectionId
from fishery_ai.model_gateway import GatewayError
from fishery_ai.tool_conversation import ToolExecutionMode
from fishery_ai.tools import ToolRegistry
from fishery_ai.domain import DiagnosisService
from fishery_ai.tools.policy import ToolPolicy
from tests.assistant.test_assistant import (AssistantFixture, AssistantWebFixture, FakeKnowledgeService,
    QUERY, KNOWLEDGE, SCORE, RecordingGateway, call, final)

QWEN = ALLOWED_PRESET_IDS[0]
NAMES = (QUERY, KNOWLEDGE)


def offline_config(*, enabled=True, released=True):
    """Temporary test fixture, never persisted or mistaken for a real qualification."""
    candidate = load_assistant_execution_config().releases[0]
    record = replace(candidate, status="released" if released else "candidate",
        qualification_id="OFFLINE_TEST_FIXTURE_ONLY" if released else None,
        validated_at="2026-10-13T00:00:00Z" if released else None)
    return AssistantExecutionConfig(enabled, (record,))


class ExecutionReleaseTests(AssistantFixture):
    def setUp(self):
        super().setUp()
        self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=FakeKnowledgeService())
        self.policy = ToolPolicy("assistant", True, NAMES)
        self.profile = assistant_profile(QWEN)

    def effective(self, config, profile=None, policy=None, projection=DEFAULT_HISTORY_PROJECTION, epoch="offline"):
        return resolve_execution_profile(config, profile or self.profile, policy or self.policy, self.registry,
                                         projection=projection, epoch=epoch)

    def test_packaged_local_trial_scopes_have_distinct_qualification_states(self):
        config = load_assistant_execution_config()
        self.assertTrue(config.multi_round_enabled)
        self.assertEqual(len(config.releases), 3)
        self.assertEqual([r.status for r in config.releases], ["released", "local_experimental", "local_experimental"])
        self.assertTrue(config.releases[0].qualification_id)
        for record in config.releases[1:]:
            self.assertIsNone(record.qualification_id)
            self.assertIsNone(record.validated_at)
        self.assertEqual(json.loads(config.releases[0].scope_json),
                         release_scope(self.profile, self.policy, self.registry, DEFAULT_HISTORY_PROJECTION))
        self.assertEqual(self.effective(config).mode, ToolExecutionMode.BOUNDED_MULTI_ROUND)
        self.assertEqual(self.effective(offline_config(released=False)).mode, ToolExecutionMode.SINGLE_ROUND)
        self.assertEqual(self.effective(offline_config(enabled=False)).mode, ToolExecutionMode.SINGLE_ROUND)

    def test_only_exact_qualified_scope_selects_multi(self):
        config = offline_config()
        self.assertEqual(self.effective(config).mode, ToolExecutionMode.BOUNDED_MULTI_ROUND)
        for change in ({"preset_id": ALLOWED_PRESET_IDS[1]}, {"preset_contract_version": "1.0.3"},
                       {"preset_variant": "on"}, {"model": "qwen-unpublished"},
                       {"service_id": "other-service"}, {"adapter_id": "other-adapter"},
                       {"base_url": "https://example.invalid/v1"}):
            # Isolate matching without creating an invalid ModelProfile contract.
            from types import SimpleNamespace
            profile = SimpleNamespace(**self.profile.__dict__)
            for key, value in change.items(): setattr(profile, key, value)
            self.assertEqual(self.effective(config, profile).mode, ToolExecutionMode.SINGLE_ROUND)
        for names in ((QUERY,), (KNOWLEDGE,), (QUERY, KNOWLEDGE, SCORE), ()):
            self.assertEqual(self.effective(config, policy=ToolPolicy("assistant", True, names)).mode,
                             ToolExecutionMode.SINGLE_ROUND)
        self.assertEqual(self.effective(config, projection=ProjectionId.CURRENT_NATIVE).mode, ToolExecutionMode.SINGLE_ROUND)

    def test_protocol_prompt_history_and_schema_fingerprints_are_pinned(self):
        config = offline_config()
        for field, value in (("prompt_id", "different@1"), ("prompt_sha256", "0" * 64),
                             ("history_version", "2"), ("tool_definitions_sha256", "0" * 64)):
            scope = json.loads(config.releases[0].scope_json); scope[field] = value
            changed = replace(config, releases=(replace(config.releases[0], scope_json=json.dumps(scope)),))
            self.assertEqual(self.effective(changed).mode, ToolExecutionMode.SINGLE_ROUND)
        scope = json.loads(config.releases[0].scope_json); scope["protocol_spec"]["version"] = "2"
        self.assertEqual(self.effective(replace(config, releases=(replace(config.releases[0], scope_json=json.dumps(scope)),))).mode,
                         ToolExecutionMode.SINGLE_ROUND)

    def test_release_without_qualification_and_bad_flag_fail_closed(self):
        candidate = load_assistant_execution_config().releases[0]
        with self.assertRaises(AssistantError): replace(candidate, status="released", qualification_id=None)
        with self.assertRaises(AssistantError): replace(candidate, status="local_experimental")
        with self.assertRaises(AssistantError): AssistantExecutionConfig("true", ())
        with self.assertRaises(FrozenInstanceError): candidate.status = "released"

    def test_revision_binds_epoch_config_policy_runtime_and_system(self):
        config = offline_config()
        original = self.effective(config)
        self.assertEqual(original, self.effective(config))
        self.assertNotEqual(original.revision, self.effective(config, epoch="restarted").revision)
        self.assertNotEqual(original.revision, self.effective(replace(config, multi_round_enabled=False)).revision)
        self.assertNotEqual(original.revision, self.effective(config, policy=ToolPolicy("assistant", True, (QUERY,))).revision)
        self.assertNotEqual(original.revision, self.effective(config, replace(self.profile, total_timeout_s=60)).revision)
        self.assertEqual(set(original.public()), {"mode", "max_model_requests", "revision", "release_status", "mode_reason"})

    def test_all_three_scopes_are_exact_and_roll_back_without_inheriting_qualification(self):
        config = load_assistant_execution_config()
        self.assertFalse(AssistantExecutionConfig().multi_round_enabled)
        for identifier, record in zip(ALLOWED_PRESET_IDS, config.releases):
            profile = assistant_profile(identifier)
            self.assertEqual(json.loads(record.scope_json), release_scope(profile, self.policy, self.registry, DEFAULT_HISTORY_PROJECTION))
            active = self.effective(config, profile)
            self.assertEqual(active.mode, ToolExecutionMode.BOUNDED_MULTI_ROUND)
            self.assertEqual(active.public()["release_status"], record.status)
            self.assertEqual(active.public()["mode_reason"], "active")
            # Only the other models' records cannot authorize this exact identity.
            others = replace(config, releases=tuple(r for r in config.releases if r != record))
            self.assertEqual(self.effective(others, profile).mode, ToolExecutionMode.SINGLE_ROUND)
            for names in ((), (QUERY,), (KNOWLEDGE,), (QUERY, KNOWLEDGE, SCORE)):
                fallback = self.effective(config, profile, policy=ToolPolicy("assistant", True, names))
                self.assertEqual(fallback.mode, ToolExecutionMode.SINGLE_ROUND)
                self.assertEqual(fallback.mode_reason, "scope_not_published")
            rollback = self.effective(replace(config, multi_round_enabled=False), profile)
            self.assertEqual(rollback.mode, ToolExecutionMode.SINGLE_ROUND)
            self.assertEqual(rollback.mode_reason, "flag_disabled")
            self.assertNotEqual(active.revision, rollback.revision)


class AssistantExecutionWebTests(AssistantWebFixture):
    def make_app(self, credentials=None, **options):
        credentials = credentials or CredentialStore(process_env={"DASHSCOPE_API_KEY": "fictional-web-multi-key"})
        options.setdefault("assistant_execution_config", offline_config())
        return super().make_app(credentials, **options)

    def setUp(self):
        super().setUp()
        self.set_policy(NAMES)
        self.app.extensions["fishery_snapshot_store"].set_current(self.reading(oxygen=2.2))

    def set_policy(self, names):
        self.app.extensions["fishery_tool_policy_store"].save({"schema_version": 1, "modes": {
            "analysis": {"selected_tools": []}, "assistant": {"selected_tools": list(names)}}})

    def post(self, **changes):
        return super().post(**{"preset_id": QWEN, **changes})

    def plan(self):
        data = self.client.get("/api/assistant/bootstrap").get_json()
        return next(p["execution_profile"] for p in data["presets"] if p["preset_id"] == QWEN)

    def prepare(self):
        return self.client.post("/api/requests", json={}, headers=self.headers).get_json()

    def status(self, control):
        return self.client.post(f"/api/requests/{control['request_id']}/status",
            json={"control_token": control["control_token"]}, headers=self.headers).get_json()

    def test_bootstrap_is_safe_and_candidate_or_disabled_stays_single(self):
        data = self.client.get("/api/assistant/bootstrap").get_json()
        self.assertEqual(self.plan()["max_model_requests"], 3)
        self.assertEqual(data["presets"][1]["execution_profile"]["max_model_requests"], 2)
        for marker in ("fictional-web-multi-key", "prompt_id", "protocol_spec", "identity", "credential_ref"):
            self.assertNotIn(marker, json.dumps(data))
        for config in (offline_config(enabled=False), offline_config(released=False)):
            app = self.make_app(assistant_execution_config=config)
            boot = app.test_client().get("/api/assistant/bootstrap").get_json()
            self.assertTrue(all(p["execution_profile"]["max_model_requests"] == 2 for p in boot["presets"]))

    def test_web_direct_and_early_final_use_actual_budget(self):
        for responses, count in (((final(),), 1), ((call(), final()), 2)):
            self.factory.return_value = RecordingGateway(*responses)
            response = self.post()
            self.assertEqual(response.status_code, 200)
            result = response.get_json()["result"]
            self.assertTrue(result["successful_turn"])
            self.assertEqual(result["usage"]["request_count"], count)
            self.assertEqual(result["activity"]["budget"]["model_requests"], 3)
            self.assertEqual(len(result["activity"]["steps"]), count * 2 - 1)

    def full_turn(self):
        control = self.prepare()
        observed = []
        def inspect(index, request, runtime):
            observed.append(self.status(control))
            if index == 2:
                self.assertEqual(request.messages[-1].role, "tool")
                self.assertEqual(json.loads(request.messages[-1].content)["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
            if index == 3:
                self.assertEqual(request.tool_choice, "none")
                self.assertEqual(len([m for m in request.messages if m.role == "tool"]), 2)
        gateway = RecordingGateway(call(call_id="query-1"), call(KNOWLEDGE, '{"query":"鳗鲡低氧表现"}', "knowledge-2"),
                                   final("离线最终回答"), callback=inspect)
        self.factory.return_value = gateway
        response = self.post(request_id=control["request_id"], control_token=control["control_token"])
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]
        self.assertEqual(len(result["activity"]["steps"]), 5)
        self.assertEqual([r["tool_name"] for r in result["activity"]["steps"] if r["kind"] == "tool"], list(NAMES))
        self.assertEqual([s["phase"] for s in observed], ["REQUEST_1", "REQUEST_2", "REQUEST_3"])
        self.assertEqual(result["activity"], self.status(control)["activity"])
        self.assertFalse(result["legacy_projection_available"])
        self.assertIsNone(result["tool_activity"])
        self.assertEqual(len(gateway.requests), 3)
        self.assertTrue(all(runtime is gateway.runtimes[0] for runtime in gateway.runtimes))
        for marker in ("鳗鲡低氧表现", "fictional-web-multi-key", "arguments_json", '"water_quality":', '"messages":'):
            self.assertNotIn(marker, json.dumps(result, ensure_ascii=False))
        return result, observed, control

    def test_actual_web_two_tool_turn_and_cumulative_status(self):
        self.full_turn()

    def test_revision_mismatch_before_credential_or_gateway_and_fresh_confirmation(self):
        revision = self.plan()["revision"]
        self.set_policy((QUERY,))
        control = self.prepare()
        response = self.post(execution_profile_revision=revision,
                             request_id=control["request_id"], control_token=control["control_token"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error_code"], "ASSISTANT_EXECUTION_PROFILE_CHANGED")
        self.assertEqual(self.status(control)["state"], "FAILED")
        self.factory.assert_not_called()
        self.assertEqual(self.plan()["max_model_requests"], 2)
        self.assertEqual(self.post().status_code, 200)

    def test_missing_and_forged_revision_release_handles_without_transport(self):
        for index in range(12):
            response = self.post(execution_profile_revision=None if index % 2 else "forged")
            self.assertEqual(response.status_code, 409)
        self.factory.assert_not_called()
        self.assertEqual(self.post().status_code, 200)

    def test_unpublished_tools_and_multiple_calls_cannot_bypass_executor(self):
        both = replace(call(), tool_calls=(call().tool_calls[0], call(KNOWLEDGE, '{"query":"x"}', "second").tool_calls[0]))
        for response, code in ((call(SCORE), "TOOL_NOT_ALLOWED"), (both, "TOOL_CALL_LIMIT"),
                               (call(KNOWLEDGE, '{"invalid":1}'), "INVALID_TOOL_ARGUMENTS")):
            self.factory.return_value = RecordingGateway(response)
            result = self.post().get_json()["result"]
            self.assertFalse(result["successful_turn"])
            self.assertEqual(result["error_code"], code)
            self.assertEqual(result["activity"]["counts"]["tools_executed"], 0)

    def test_final_round_limit_prevents_fourth_request(self):
        self.factory.return_value = RecordingGateway(call(call_id="first"),
            call(KNOWLEDGE, '{"query":"低氧"}', "second"), call(SCORE, call_id="third"), final())
        result = self.post().get_json()["result"]
        self.assertEqual(result["error_code"], "TOOL_ROUND_LIMIT")
        self.assertFalse(result["successful_turn"])
        self.assertEqual(len(self.factory.return_value.requests), 3)

    def test_captured_policy_stays_frozen_but_next_turn_requires_reconfirmation(self):
        original_revision = self.plan()["revision"]
        self.factory.return_value = RecordingGateway(call(call_id="first"),
            call(KNOWLEDGE, '{"query":"低氧"}', "second"), final(),
            callback=lambda index, *_: self.set_policy(()) if index == 1 else None)
        self.assertEqual(self.post(execution_profile_revision=original_revision).status_code, 200)
        self.factory.reset_mock()
        self.assertEqual(self.post(execution_profile_revision=original_revision).status_code, 409)
        self.factory.assert_not_called()

    def test_stop_each_request_never_commits_late_final(self):
        for stop_index in (1, 2, 3):
            control = self.prepare()
            def stop(index, *_):
                if index == stop_index:
                    self.client.post(f"/api/requests/{control['request_id']}/cancel",
                        json={"control_token": control["control_token"]}, headers=self.headers)
            self.factory.return_value = RecordingGateway(call(call_id="first"),
                call(KNOWLEDGE, '{"query":"低氧"}', "second"), final("late"), callback=stop)
            result = self.post(request_id=control["request_id"], control_token=control["control_token"]).get_json()["result"]
            self.assertFalse(result["successful_turn"])
            self.assertEqual(result["error_code"], "USER_CANCELLED")
            self.assertEqual(result["final_text"], "")
            self.assertEqual(self.status(control)["state"], "CANCELLED")
            self.assertEqual(len(self.factory.return_value.requests), stop_index)

    def test_turn_timeout_and_trace_failure_agree_with_status(self):
        control = self.prepare(); ticks = [0.0]
        def advance(index, *_): ticks[0] += 50
        self.factory.return_value = RecordingGateway(call(call_id="first"),
            call(KNOWLEDGE, '{"query":"低氧"}', "second"), final(), callback=advance)
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]):
            response = self.post(request_id=control["request_id"], control_token=control["control_token"])
        result = response.get_json()["result"]
        self.assertEqual(result["error_code"], "TOTAL_TIMEOUT")
        self.assertEqual(self.status(control)["error_code"], "TOTAL_TIMEOUT")
        self.assertFalse(result["successful_turn"])
        self.factory.return_value = RecordingGateway(call(call_id="first"),
            call(KNOWLEDGE, '{"query":"低氧"}', "second"), final())
        trace_control = self.prepare()
        with patch("fishery_ai.observability.JsonlTraceSink.record_assistant", side_effect=OSError("fictional-private")):
            result = self.post(request_id=trace_control["request_id"],
                               control_token=trace_control["control_token"]).get_json()["result"]
        self.assertEqual(result["error_code"], "TRACE_WRITE_ERROR")
        self.assertFalse(result["successful_turn"])
        self.assertEqual(len(result["activity"]["steps"]), 5)
        self.assertEqual(result["final_text"], "")
        self.assertEqual(self.status(trace_control)["error_code"], "TRACE_WRITE_ERROR")

    def test_startup_config_is_frozen_within_epoch(self):
        before = self.plan()
        with patch("fishery_ai.web.load_assistant_execution_config", return_value=offline_config(enabled=False)):
            self.assertEqual(self.plan(), before)
            restarted = self.make_app(assistant_execution_config=None)
        data = restarted.test_client().get("/api/assistant/bootstrap").get_json()
        self.assertTrue(all(p["execution_profile"]["max_model_requests"] == 2 for p in data["presets"]))
        self.assertNotEqual(data["epoch"], self.epoch)

    def test_restart_disabled_rolls_back_and_old_confirmation_cannot_execute(self):
        old_epoch, old_revision = self.epoch, self.plan()["revision"]
        self.app = self.make_app(assistant_execution_config=offline_config(enabled=False))
        self.client = self.app.test_client()
        csrf = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
        self.assertEqual(self.post().get_json()["error_code"], "ASSISTANT_SESSION_EXPIRED")
        self.epoch = self.client.get("/api/assistant/bootstrap").get_json()["epoch"]
        self.assertNotEqual(self.epoch, old_epoch)
        self.assertEqual(self.post(execution_profile_revision=old_revision).status_code, 409)
        self.assertEqual(self.plan()["max_model_requests"], 2)
        self.factory.assert_not_called()
        self.assertEqual(self.post().status_code, 200)

    def test_web_cannot_set_flag_mode_budget_prompt_or_deadline(self):
        for name in ("multi_round_enabled", "execution_mode", "mode", "budget", "deadline", "prompt_id", "turn_timeout_s"):
            self.assertEqual(self.post(**{name: "injected"}).status_code, 400)
        self.factory.assert_not_called()


class LocalTrialWebTests(AssistantWebFixture):
    """Packaged release configuration through real Flask routes, fake transport only."""

    def make_app(self, credentials=None, **options):
        credentials = credentials or CredentialStore(process_env={
            "DASHSCOPE_API_KEY": "fictional-trial-qwen", "DEEPSEEK_API_KEY": "fictional-trial-deepseek"})
        return super().make_app(credentials, **options)

    def setUp(self):
        super().setUp()
        self.app.extensions["fishery_tool_policy_store"].save({"schema_version": 1, "modes": {
            "analysis": {"selected_tools": [SCORE]}, "assistant": {"selected_tools": list(NAMES)}}})
        self.app.extensions["fishery_snapshot_store"].set_current(self.reading(oxygen=2.2))

    def bootstrap(self):
        return self.client.get("/api/assistant/bootstrap").get_json()

    def test_real_bootstrap_exposes_only_trial_labels_and_bound_three_request_budget(self):
        data = self.bootstrap()
        self.assertEqual([p["preset_id"] for p in data["presets"]], list(ALLOWED_PRESET_IDS))
        self.assertEqual([p["execution_profile"]["release_status"] for p in data["presets"]],
                         ["released", "local_experimental", "local_experimental"])
        self.assertTrue(all(p["execution_profile"]["mode"] == "BOUNDED_MULTI_ROUND"
                            and p["execution_profile"]["max_model_requests"] == 3 for p in data["presets"]))
        for marker in ("fictional-trial", "qualification_id", "base_url", "protocol_spec", "credential_ref", "prompt_id"):
            self.assertNotIn(marker, json.dumps(data))
        self.factory.assert_not_called()

    def test_all_three_web_presets_execute_same_bounded_loop_and_preserve_user_policy(self):
        store = self.app.extensions["fishery_tool_policy_store"]
        before = store.effective()
        for identifier in ALLOWED_PRESET_IDS:
            with self.subTest(preset=identifier):
                def inspect(index, request, runtime):
                    self.assertEqual(runtime.preset_id, identifier)
                    self.assertEqual(runtime.max_retries, 0)
                    if index == 2:
                        self.assertEqual(json.loads(request.messages[-1].content)["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                    if index == 3:
                        self.assertEqual(request.tool_choice, "none")
                        self.assertEqual(len([m for m in request.messages if m.role == "tool"]), 2)
                gateway = RecordingGateway(call(call_id="first"),
                    call(KNOWLEDGE, '{"query":"鳗鲡低氧表现"}', "second"), final("离线最终回答"), callback=inspect)
                self.factory.return_value = gateway
                response = self.post(preset_id=identifier)
                self.assertEqual(response.status_code, 200)
                result = response.get_json()["result"]
                self.assertTrue(result["successful_turn"])
                self.assertEqual(result["activity"]["budget"], {"tool_calls": 2, "tool_rounds": 2, "model_requests": 3})
                self.assertEqual(len(result["activity"]["steps"]), 5)
                self.assertEqual(result["activity"]["counts"]["tools_executed"], 2)
                self.assertEqual(result["activity"]["state"], "COMPLETED")
                self.assertTrue(all(r is gateway.runtimes[0] for r in gateway.runtimes))
                self.assertEqual(store.effective(), before)

    def test_fallback_requires_fresh_confirmation_and_does_not_run_transport(self):
        revisions = {p["preset_id"]: p["execution_profile"]["revision"] for p in self.bootstrap()["presets"]}
        self.app.extensions["fishery_tool_policy_store"].save({"schema_version": 1, "modes": {
            "analysis": {"selected_tools": [SCORE]}, "assistant": {"selected_tools": [QUERY, KNOWLEDGE, SCORE]}}})
        for p in self.bootstrap()["presets"]:
            self.assertEqual(p["execution_profile"]["mode"], "SINGLE_ROUND")
            self.assertEqual(p["execution_profile"]["mode_reason"], "scope_not_published")
            response = self.post(preset_id=p["preset_id"], execution_profile_revision=revisions[p["preset_id"]])
            self.assertEqual(response.status_code, 409)
        self.factory.assert_not_called()
        self.assertTrue(self.post(preset_id=ALLOWED_PRESET_IDS[1]).get_json()["result"]["successful_turn"])

    def test_flag_off_restart_returns_all_presets_to_single_without_fake_qualification(self):
        original = self.bootstrap()
        config = replace(load_assistant_execution_config(), multi_round_enabled=False)
        restarted = self.make_app(assistant_execution_config=config)
        data = restarted.test_client().get("/api/assistant/bootstrap").get_json()
        self.assertNotEqual(data["epoch"], original["epoch"])
        self.assertTrue(all(p["execution_profile"]["mode"] == "SINGLE_ROUND"
                            and p["execution_profile"]["mode_reason"] == "flag_disabled" for p in data["presets"]))
        self.assertIsNone(config.releases[1].qualification_id)
        self.assertIsNone(config.releases[2].validated_at)

    def test_experimental_label_cannot_be_requested_by_browser(self):
        for identifier in ALLOWED_PRESET_IDS:
            self.assertEqual(self.post(preset_id=identifier, release_status="local_experimental").status_code, 400)
        self.factory.assert_not_called()


def browser_fixture():
    """Replay only actual safe Web response/status into Node UI, no live HTTP server."""
    fixture = AssistantExecutionWebTests("test_actual_web_two_tool_turn_and_cumulative_status")
    fixture.setUp()
    try:
        bootstrap = fixture.client.get("/api/assistant/bootstrap").get_json()
        result, observed, control = fixture.full_turn()
        return {"bootstrap": bootstrap, "result": result, "statuses": observed,
                "request_id": control["request_id"]}  # Never include the control token or raw model requests.
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--browser-fixture"]:
        print(json.dumps(browser_fixture(), ensure_ascii=True))
    else:
        import unittest
        unittest.main()
