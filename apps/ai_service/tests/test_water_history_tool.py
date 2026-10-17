"""Candidate-only history Tool through real Runtime/Adapter and offline Fake SDK."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from apps.ai_backend.tests import test_execution as offline_guard
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle, request_scope
from apps.ai_backend.model_gateway import ProfileRegistry
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tool_conversation import ToolCallingService, ToolExecutionMode
from apps.ai_backend.tools import ToolExecutor
from apps.ai_backend.tools.policy import ToolPolicy, ToolPolicyError
from apps.ai_service.business_tools import water_quality_history as history
from apps.ai_service.business_tools.registry import (bind_tools, FORMAL_TOOL_NAMES,
    HISTORY_CANDIDATE_TOOL_NAMES, KNOWN_TOOL_NAMES, WATER_QUALITY_SCORE)
from apps.ai_service.runtime import assistant, sources, activity
from apps.ai_service.runtime.policy import UserToolPolicyStore
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.history import HistoryQueryError
from apps.simulator.generator import Simulator


HISTORY = history.WATER_QUALITY_HISTORY
WATER, KNOWLEDGE = FORMAL_TOOL_NAMES
DO = "dissolved_oxygen_mg_l"
ARGS = json.dumps({"lookback_minutes": 10, "metrics": [DO]})


class WaterHistoryToolTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.monitoring_index = 0
        self.monitoring = self.make_monitoring("sparse")
        self.knowledge = SimpleNamespace(search=Mock(return_value=[]), backend="portable",
                                        source_id="fixture", source_version="1")
        self.profile = assistant.assistant_profile(assistant.ALLOWED_PRESET_IDS[0])
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={
            self.profile.credential_ref: "fictional-history-test-key"})).snapshot(self.profile.profile_id)
        self.traces = JsonlTraceSink(self.root/"trace.jsonl", tool_names=HISTORY_CANDIDATE_TOOL_NAMES)

    def make_monitoring(self, case):
        self.monitoring_index += 1
        clock = [self.now]
        monitoring = MonitoringService(MonitoringRepository(self.root/(str(self.monitoring_index)+".sqlite3")),
            device_names={"pond-a": "A", "pond-b": "B"}, clock=lambda: clock[0])
        for device, oxygen in (("pond-a", 6.4), ("pond-b", 2.2)):
            if case == "no_data": continue
            start = self.now-timedelta(seconds=600 if case == "complete" else 605 if case == "boundary" else 10)
            sim = Simulator(start=start, device_id=device, session_id="fixture-"+device, seed=42)
            for _ in range(10 if case == "complete" else 1):
                batch = sim.advance(60 if case == "complete" else 10)
                batch["visual"] = None
                batch["water"]["metrics"][DO].update(mean=oxygen, min=oxygen, max=oxygen, latest=oxygen)
                if case in ("unavailable", "partial"):
                    batch["water"]["metrics"][DO].update(valid_samples=0 if case == "unavailable" else 5,
                        mean=None if case == "unavailable" else oxygen,
                        min=None if case == "unavailable" else oxygen,
                        max=None if case == "unavailable" else oxygen,
                        latest=None if case == "unavailable" else oxygen)
                clock[0] = datetime.fromisoformat(batch["timestamp"])
                monitoring.ingest(batch)
        clock[0] = self.now
        return monitoring

    def registry(self, device="pond-a", *, formal=None):
        return bind_tools(self.monitoring, device, self.knowledge, formal=formal, include_history=True)

    def send(self, plans, *, registry=None, requirement=sources.SourceRequirement.HISTORICAL_WATER_QUERY,
             allowed=(HISTORY,), mode=ToolExecutionMode.SINGLE_ROUND, handle=None, on_close=None, turns=()):
        sdk = FakeSDK(plans, model=self.profile.model, on_close=on_close)
        coordinator = ToolCallingService(OpenAICompatibleAdapter(async_client_factory=sdk.factory),
            registry or self.registry(), self.traces, policy=ToolPolicy("assistant", True, allowed), execution_mode=mode)
        handle = handle or RequestHandle(summarize_tool=activity.tool_summary)
        handle.start()
        with request_scope(handle):
            result = assistant.AssistantService(coordinator, execution_mode=mode).send(
                assistant.AssistantRequest(self.profile.preset_id, "隔离历史查询", turns, source_requirement=requirement), self.runtime)
        return result, sdk, handle

    def test_schema_default_metrics_and_canonicalization(self):
        schema = history.HISTORY_DEFINITION.parameters_dict()
        self.assertEqual(schema["required"], ["lookback_minutes"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["lookback_minutes"]["enum"], [10, 30, 60])
        self.assertEqual(history.validate_arguments({"lookback_minutes": 30})["metrics"], list(history.METRICS))
        self.assertEqual(history.validate_arguments({"lookback_minutes": 60, "metrics": [DO, "ph"]})["metrics"], ["ph", DO])
        result, sdk, _ = self.send([sdk_tool(HISTORY, arguments='{"lookback_minutes":10}'), sdk_final()])
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual(list(dict(result.source_receipt.history_reliable_windows)), list(history.METRICS))
        self.assertEqual([item["function"]["name"] for item in sdk.bodies[0]["tools"]], [HISTORY])
        step = next(item for item in result.to_dict()["activity"]["steps"] if item["kind"] == "tool")
        self.assertLessEqual(len(step["display_summary"]), 256)

    def test_strict_validator_rejects_invalid_types_unknown_fields_and_duplicate_metrics(self):
        cases = [None, [], {}, *({"lookback_minutes": value} for value in (True, 30.0, "30", 0, 11, None)),
            *({"lookback_minutes": 10, "metrics": value} for value in (None, (), [DO, DO], ["bad"], [True], [[]], "ph", [])),
            {"lookback_minutes": 10, "device_id": "pond-b"}, {"lookback_minutes": 10, "limit": 12}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                history.validate_arguments(value)

    def test_handler_delegates_once_and_returns_identical_monitoring_dto(self):
        value = self.monitoring.query_water_history("pond-a", lookback_minutes=10, metrics=[DO])
        monitoring = Mock()
        monitoring.query_water_history.return_value = value
        result = history.history_payload(history.validate_arguments(json.loads(ARGS)), monitoring=monitoring, device_id="pond-a")
        self.assertIs(result, value)
        monitoring.query_water_history.assert_called_once_with("pond-a", lookback_minutes=10, metrics=[DO])

    def test_default_registry_and_shared_policy_do_not_open_candidate_or_score(self):
        formal = bind_tools(self.monitoring, "pond-a", self.knowledge)
        self.assertEqual(tuple(d.name for d in formal.model_definitions()), FORMAL_TOOL_NAMES)
        self.assertNotIn(HISTORY, KNOWN_TOOL_NAMES)
        self.assertNotIn(WATER_QUALITY_SCORE, self.registry().registered_names())
        with patch.object(self.monitoring, "query_water_history") as query:
            with self.assertRaisesRegex(ToolPolicyError, "UNKNOWN_POLICY_TOOL"):
                ToolExecutor(formal, policy=ToolPolicy("assistant", True, (HISTORY,)))
            query.assert_not_called()
        store = UserToolPolicyStore(self.root/"policy", formal)
        baseline = store.default_selections(); store.save(baseline)
        before = store.path.read_bytes()
        candidate = deepcopy(baseline); candidate["modes"]["assistant"]["selected_tools"] = [HISTORY]
        with self.assertRaises(ToolPolicyError): store.save(candidate)
        self.assertEqual(store.path.read_bytes(), before)
        self.assertEqual(store.load(), baseline)

    def test_formal_and_turn_candidate_definitions_match_and_device_is_rebound(self):
        formal = self.registry()
        turn = self.registry("pond-b", formal=formal)
        self.assertEqual(formal.model_definitions(), turn.model_definitions())
        self.assertEqual(tuple(d.name for d in turn.model_definitions()), HISTORY_CANDIDATE_TOOL_NAMES)
        self.assertIs(turn.lookup(KNOWLEDGE), formal.lookup(KNOWLEDGE))
        self.assertIs(turn.lookup(HISTORY).model_definition, formal.lookup(HISTORY).model_definition)
        self.monitoring.snapshot("pond-a")
        result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()], registry=turn)
        payload = json.loads(sdk.bodies[1]["messages"][-1]["content"])
        self.assertEqual(payload["device_id"], "pond-b")
        self.assertEqual(payload["metrics"][DO]["first"]["window_mean"], 2.2)
        self.assertTrue(result.to_dict()["successful_turn"])
        with self.assertRaises(ValueError): bind_tools(self.monitoring, "pond-a", self.knowledge, formal=formal)
        with self.assertRaises(ValueError): self.registry(formal=bind_tools(self.monitoring, "pond-a", self.knowledge))
        with self.assertRaises(ValueError): bind_tools(self.monitoring, "pond-a", self.knowledge, include_history=1)

    def test_history_to_final_business_matrix_and_receipt_isolation(self):
        for case, status, reliable in (("no_data", "NO_DATA", False), ("boundary", "NO_DATA", False),
                ("sparse", "PARTIAL", True), ("complete", "OK", True),
                ("unavailable", "PARTIAL", False), ("partial", "PARTIAL", False)):
            with self.subTest(case=case):
                self.monitoring = self.make_monitoring(case)
                result, sdk, handle = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()])
                self.assertTrue(result.to_dict()["successful_turn"], result.error_code)
                self.assertEqual(len(sdk.bodies), 2)
                self.assertEqual(result.execution.budget.max_tool_calls, 1)
                self.assertEqual(sdk.bodies[1]["tool_choice"], "none")
                receipt = result.source_receipt
                self.assertTrue(receipt.history_query_completed)
                self.assertEqual(receipt.tool_status.value, status)
                self.assertEqual(receipt.has_historical_observations, reliable)
                self.assertFalse(receipt.has_observation or receipt.has_score or receipt.has_project_evidence)
                self.assertFalse(receipt.observation_query_completed)
                for requirement in (sources.SourceRequirement.CURRENT_OBSERVATION_QUERY,
                        sources.SourceRequirement.CURRENT_SCORE_EVALUATION, sources.SourceRequirement.PROJECT_KNOWLEDGE_SEARCH):
                    self.assertFalse(sources.requirement_satisfied(requirement, receipt))
                self.assertEqual(handle.state, "COMPLETED")
                self.assertTrue(all(c.closed for c in sdk.clients))
        self.monitoring = self.make_monitoring("unavailable")
        result, _, _ = self.send([sdk_tool(HISTORY, arguments='{"lookback_minutes":10}'), sdk_final()])
        available = dict(result.source_receipt.history_reliable_windows)
        self.assertEqual(available[DO], 0)
        self.assertEqual(available["temperature_c"], 1)
        self.assertTrue(result.source_receipt.has_historical_observations)
        self.assertFalse(result.source_receipt.has_observation)

    def test_invalid_protocol_arguments_reject_before_handler_or_second_request(self):
        for arguments in ('{}', '[]', '{bad', '{"lookback_minutes":true}', '{"lookback_minutes":30.0}',
                '{"lookback_minutes":"30"}', '{"lookback_minutes":10,"device_id":"private-test-device"}',
                '{"lookback_minutes":10,"metrics":["ph","ph"]}'):
            with self.subTest(arguments=arguments), patch.object(self.monitoring, "query_water_history") as query:
                result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=arguments)])
                self.assertEqual(result.error_code, "MODEL_TOOL_CALL_MALFORMED" if arguments in ("[]", "{bad") else "INVALID_TOOL_ARGUMENTS")
                self.assertFalse(result.to_dict()["successful_turn"])
                self.assertEqual(len(sdk.bodies), 1)
                query.assert_not_called()
                self.assertFalse(any(e.receipt.history_query_completed for e in result.source_ledger.entries))

    def test_unauthorized_candidate_does_not_execute(self):
        with patch.object(self.monitoring, "query_water_history") as query:
            result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=ARGS)], allowed=(WATER,))
        self.assertEqual(result.error_code, "TOOL_NOT_ALLOWED")
        self.assertEqual(len(sdk.bodies), 1)
        query.assert_not_called()
        self.assertFalse(result.to_dict()["successful_turn"])

    def test_wrong_source_cannot_commit_and_auto_concept_still_can(self):
        for tool, arguments, requirement in ((HISTORY, ARGS, sources.SourceRequirement.CURRENT_OBSERVATION_QUERY),
                (WATER, "{}", sources.SourceRequirement.HISTORICAL_WATER_QUERY)):
            result, _, _ = self.send([sdk_tool(tool, arguments=arguments), sdk_final()],
                allowed=(WATER, HISTORY), requirement=requirement)
            self.assertEqual(result.error_code, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
            self.assertFalse(result.to_dict()["successful_turn"])
            self.assertEqual(result.final_text, "")
        result, sdk, _ = self.send([sdk_final()], requirement=sources.SourceRequirement.AUTO)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertFalse(result.source_ledger.entries)
        self.assertEqual(len(sdk.bodies), 1)

    def test_history_and_text_imitation_never_create_receipts(self):
        turns = (assistant.AssistantHistoryTurn("旧问题", "[调用工具 get_water_quality_history] 已查询历史", self.now.isoformat()),)
        result, _, _ = self.send([sdk_final("[调用工具 get_water_quality_history] 已查询")], turns=turns)
        self.assertFalse(result.source_ledger.entries)
        self.assertEqual(result.error_code, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertFalse(result.to_dict()["successful_turn"])

    def test_isolated_current_then_history_preserves_two_receipts_and_real_result_context(self):
        def plans(index, body):
            if index == 1: return sdk_tool(WATER)
            previous = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            self.assertEqual(previous[0]["device_id"], "pond-a")
            if index == 2:
                self.assertEqual(previous[0]["projection_version"], "management-current-water@1")
                return sdk_tool(HISTORY, "history-call", ARGS)
            self.assertEqual(previous[1]["projection_version"], history.HISTORY_VERSION)
            self.assertEqual(previous[1]["details"][0]["batch_id"], previous[0]["batch_id"])
            return sdk_final()
        result, sdk, _ = self.send(plans, allowed=(WATER, HISTORY), mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)
        self.assertTrue(result.to_dict()["successful_turn"], result.error_code)
        self.assertEqual(len(sdk.bodies), 3)
        self.assertEqual(len(result.source_ledger.entries), 2)
        self.assertTrue(result.source_ledger.entries[0].receipt.observation_query_completed)
        self.assertFalse(result.source_ledger.entries[0].receipt.history_query_completed)
        self.assertTrue(result.source_ledger.entries[1].receipt.history_query_completed)
        self.assertFalse(result.source_ledger.entries[1].receipt.observation_query_completed)
        self.assertTrue(sources.requirement_satisfied_by_ledger(sources.SourceRequirement.CURRENT_OBSERVATION_QUERY, result.source_ledger))

    def test_single_round_never_allows_second_tool(self):
        result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_tool(WATER)], allowed=(HISTORY, WATER))
        self.assertEqual(result.error_code, "TOOL_ROUND_LIMIT")
        self.assertEqual(len(sdk.bodies), 2)
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(len(result.source_ledger.entries), 1)

    def test_stop_before_tool_and_during_final_never_commit(self):
        for cancel_at in (0, 1):
            handle = RequestHandle(summarize_tool=activity.tool_summary)
            with patch.object(self.monitoring, "query_water_history", wraps=self.monitoring.query_water_history) as query:
                result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()], handle=handle,
                    on_close=lambda index: handle.cancel() if index == cancel_at else None)
            self.assertEqual(result.error_code, "USER_CANCELLED")
            self.assertEqual(result.final_text, "")
            self.assertFalse(result.to_dict()["successful_turn"])
            self.assertEqual(query.call_count, cancel_at)
            self.assertEqual(len(sdk.bodies), cancel_at+1)

    def test_timeout_and_trace_failure_never_commit(self):
        handle = RequestHandle(summarize_tool=activity.tool_summary)
        result, _, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()], handle=handle,
            on_close=lambda index: setattr(handle, "_deadline", 0) if index == 1 else None)
        self.assertEqual(result.error_code, "TOTAL_TIMEOUT")
        self.assertFalse(result.to_dict()["successful_turn"])
        with patch.object(self.traces, "record_assistant", side_effect=OSError("private-test-path")):
            result, _, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()])
        self.assertEqual(result.error_code, "TRACE_WRITE_ERROR")
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(result.final_text, "")

    def test_history_service_failure_no_followup_or_positive_receipt(self):
        with patch.object(self.monitoring, "query_water_history", side_effect=HistoryQueryError("HISTORY_QUERY_BUDGET_EXCEEDED")):
            result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=ARGS)])
        self.assertEqual(result.error_code, "TOOL_EXECUTION_ERROR")
        self.assertEqual(len(sdk.bodies), 1)
        self.assertFalse(result.source_receipt.history_query_completed)
        self.assertFalse(result.source_receipt.has_historical_observations)

    def test_malformed_results_do_not_gain_operation_or_positive_source(self):
        original = self.monitoring.query_water_history("pond-a", lookback_minutes=10, metrics=[DO])
        for mutation in ("version", "completed", "count", "positive", "quality", "time", "sample_count", "reference"):
            value = deepcopy(original)
            if mutation == "version": value["projection_version"] = "untrusted"
            if mutation == "completed": value["query_completed"] = False
            if mutation == "count": value["counts"]["matching_windows"] = True
            if mutation == "positive": value["has_reliable_history"] = False
            if mutation == "quality": value["metrics"][DO]["quality_counts"]["valid"] = 0
            if mutation == "time": value["requested_range"]["end"] = (self.now+timedelta(minutes=1)).isoformat()
            if mutation == "sample_count": value["metrics"][DO]["sample_count"] = 0
            if mutation == "reference": value["metrics"][DO]["first"]["window_start"] = self.now.isoformat()
            with self.subTest(mutation=mutation), patch.object(self.monitoring, "query_water_history", return_value=value):
                result, _, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()])
                self.assertFalse(result.source_receipt.history_query_completed)
                self.assertFalse(result.source_receipt.has_historical_observations)
                self.assertEqual(result.error_code, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")

    def test_actual_handler_and_model_execution_are_required_for_receipt(self):
        result, _, _ = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()])
        for kind in ("handler", "model", "call_id"):
            steps = list(result.execution.steps)
            if kind == "handler": steps[1] = replace(steps[1], handler_started=False)
            if kind == "model": steps[0] = replace(steps[0], request_started=False)
            if kind == "call_id": steps[1] = replace(steps[1], tool_call_id="mismatch")
            ledger = sources.ledger_from_execution(replace(result.execution, steps=tuple(steps)))
            self.assertFalse(sources.requirement_satisfied_by_ledger(sources.SourceRequirement.HISTORICAL_WATER_QUERY, ledger))

    def test_old_normal_streaming_scopes_reject_history_and_assembled_revision_changes(self):
        from importlib.resources import files
        from fishery_ai.knowledge import KnowledgeService
        from apps.ai_service.execution import load_execution_config, resolve_execution
        from apps.ai_service.streaming import load_streaming_config, resolve_streaming
        knowledge = KnowledgeService(files("fishery_ai").joinpath("resources/knowledge/eel_knowledge.json"))
        formal = bind_tools(self.monitoring, "pond-a", knowledge)
        candidate = bind_tools(self.monitoring, "pond-a", knowledge, include_history=True)
        old_policy = ToolPolicy("assistant", True, FORMAL_TOOL_NAMES)
        candidate_policy = ToolPolicy("assistant", True, HISTORY_CANDIDATE_TOOL_NAMES)
        for resolver, config in ((resolve_execution, load_execution_config(enable_trial=True)),
                                 (resolve_streaming, load_streaming_config(enable_trial=True))):
            old = resolver(config, self.profile, old_policy, old_policy, formal, knowledge, device_id="pond-a", epoch="fixed")
            changed = resolver(config, self.profile, candidate_policy, candidate_policy, candidate, knowledge, device_id="pond-a", epoch="fixed")
            not_authorized = resolver(config, self.profile, old_policy, old_policy, candidate, knowledge, device_id="pond-a", epoch="fixed")
            self.assertTrue(old.can_send)
            self.assertFalse(changed.can_send)
            self.assertNotEqual(old.profile.revision, changed.profile.revision)
            self.assertNotEqual(old.profile.revision, not_authorized.profile.revision)

    def test_stop_inside_handler_never_commits_or_requests_final(self):
        handle = RequestHandle(summarize_tool=activity.tool_summary)
        query = self.monitoring.query_water_history
        def cancel_after_read(*args, **kwargs):
            value = query(*args, **kwargs)
            handle.cancel()
            return value
        with patch.object(self.monitoring, "query_water_history", side_effect=cancel_after_read):
            result, sdk, _ = self.send([sdk_tool(HISTORY, arguments=ARGS)], handle=handle)
        self.assertEqual(result.error_code, "USER_CANCELLED")
        self.assertEqual(len(sdk.bodies), 1)
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertFalse(any(e.receipt.history_query_completed for e in result.source_ledger.entries))

    def test_safe_activity_trace_and_success_history_are_finite(self):
        result, _, handle = self.send([sdk_tool(HISTORY, arguments=ARGS), sdk_final()])
        tool = next(step for step in result.to_dict()["activity"]["steps"] if step["kind"] == "tool")
        self.assertIn("历史水质 · simulator", tool["display_summary"])
        self.assertIn(DO+"=1", tool["display_summary"])
        self.assertLessEqual(len(tool["display_summary"]), 256)
        limited = result.to_dict()["tool_activity"]
        self.assertEqual(limited["source_type"], "historical_water")
        self.assertEqual(limited["reliable_windows"], {DO: 1})
        self.assertIn("history_range", limited)
        safe = json.dumps(result.to_dict()) + json.dumps(handle.public_info()) + self.traces.path.read_text(encoding="utf-8")
        for forbidden in ("window_mean", "requested_range", "private-test", "fictional-history-test-key", "SELECT ", "arguments_json"):
            self.assertNotIn(forbidden, safe)
        self.assertNotIn("freshness", tool)
        self.assertNotIn("observed_at", tool)
        records = [json.loads(line) for line in self.traces.path.read_text(encoding="utf-8").splitlines()]
        execution_trace = next(record for record in records if record["kind"] == "read_only_tool_conversation")
        self.assertEqual(next(step["tool_name"] for step in execution_trace["steps"] if step["kind"] == "tool"), HISTORY)
        pair = assistant.AssistantHistoryTurn("旧问题", result.final_text, result.completed_at)
        followup, sdk, _ = self.send([sdk_final()], requirement=sources.SourceRequirement.AUTO, turns=(pair,))
        self.assertTrue(followup.to_dict()["successful_turn"])
        history_message = sdk.bodies[0]["messages"][1]["content"]
        self.assertNotIn("role=tool", history_message)
        self.assertNotIn("history_reliable_windows", history_message)
        self.assertNotIn("window_mean", history_message)


class TwoToolBoundaryParityTests(unittest.TestCase):
    def test_original_six_http_paths_and_plan_fingerprints_match_pre_change_capture(self):
        from apps.ai_service.tests.capture_migration import capture
        from apps.ai_service.development.streaming_qualification import CASES, plan
        expected = json.loads((Path(__file__).with_name("fixtures")/"r2d1c_two_tools.json").read_text(encoding="utf-8"))
        self.assertEqual(capture(), expected["http_paths"])
        for case in CASES:
            actual = plan(case.case_id)
            self.assertEqual({key: actual[key] for key in expected["qualification"][case.case_id]},
                             expected["qualification"][case.case_id])


if __name__ == "__main__":
    unittest.main()
