"""Internal Assistant 2/2/3 integration, scripted sources and whole-Turn deadline."""

from dataclasses import replace
import json
from unittest.mock import patch

from fishery_ai.assistant import (AssistantError, AssistantRequest, AssistantService,
    MULTI_ROUND_PROMPT_ID, MULTI_ROUND_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION)
from fishery_ai.assistant_sources import SourceRequirement, requirement_satisfied_by_ledger
from fishery_ai.contracts import Status, Usage, UsageSource
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, current_handle, request_scope
from fishery_ai.model_gateway import GatewayError
from fishery_ai.tool_conversation import ToolCallingService, ToolExecutionMode, ToolExecutionStep
from fishery_ai.tools import ToolExecutor, ToolRegistry
from fishery_ai.tools.policy import ToolPolicy
from tests.assistant.test_assistant import (AssistantFixture, FakeKnowledgeService, LOCAL,
    QUERY, SCORE, KNOWLEDGE, RecordingGateway, call, final)


class AssistantMultiRoundTests(AssistantFixture):
    def setUp(self):
        super().setUp()
        self.registry = ToolRegistry(self.reader, DiagnosisService(),
            knowledge=FakeKnowledgeService())

    def multi(self, gateway, *, timeout=None):
        coordinator = ToolCallingService(gateway, self.registry, self.traces,
            policy=ToolPolicy("assistant", True, (QUERY, SCORE, KNOWLEDGE)),
            execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)
        return AssistantService(coordinator, execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND,
                                turn_timeout_s=timeout)

    def run_multi(self, gateway, *, request=None, timeout=None, handle=None):
        handle = handle or RequestHandle()
        handle.start()
        with request_scope(handle):
            result = self.multi(gateway, timeout=timeout).send(request or self.request(), self.runtime)
        return result, handle

    def assert_failed(self, result, code):
        self.assertEqual(result.error_code, code)
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(result.final_text, "")
        self.assertIsNone(result.completed_at)

    def test_explicit_mode_and_versioned_prompt_required(self):
        service = self.multi(RecordingGateway(final()))
        self.assertEqual(service.prompt_id, MULTI_ROUND_PROMPT_ID)
        with self.assertRaises(AssistantError):
            AssistantService(service.coordinator)
        with self.assertRaises(AssistantError):
            AssistantService(self.service(RecordingGateway(final())).coordinator,
                             execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)
        for timeout in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(AssistantError):
                self.multi(RecordingGateway(final()), timeout=timeout)
        self.assertNotEqual(SYSTEM_INSTRUCTION, MULTI_ROUND_SYSTEM_INSTRUCTION)
        for sentence in SYSTEM_INSTRUCTION.split("。"):
            if sentence and not sentence.startswith("如需Tool"):
                self.assertIn(sentence, MULTI_ROUND_SYSTEM_INSTRUCTION)

    def test_direct_final_and_internal_owned_handle(self):
        gateway = RecordingGateway(final())
        result = self.multi(gateway).send(self.request("什么是溶氧？"), self.runtime)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(len(gateway.requests), 1)
        self.assertEqual(gateway.requests[0].messages[0].content, MULTI_ROUND_SYSTEM_INSTRUCTION)
        self.assertFalse(result.source_ledger.entries)
        self.assertIsNone(current_handle())
        self.assertEqual(result.to_dict()["activity"]["budget"]["model_requests"], 3)

    def test_early_final_does_not_spend_remaining_budget(self):
        gateway = RecordingGateway(call(), final(), call(SCORE, call_id="unused"))
        result, handle = self.run_multi(gateway)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(len(gateway.requests), 2)
        self.assertEqual(gateway.requests[1].tool_choice, "auto")
        self.assertEqual(len(result.source_ledger.entries), 1)
        self.assertEqual(handle.state, "COMPLETED")

    def test_two_tools_real_payloads_reach_next_request_ledger_and_serialization(self):
        self.store.set_current(self.reading(oxygen=2.2))
        def inspect(index, request, runtime):
            self.assertIs(runtime, self.runtime)
            if index == 1:
                self.assertFalse(any(m.role == "tool" for m in request.messages))
            if index == 2:
                payload = json.loads(request.messages[-1].content)
                self.assertEqual(payload["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                self.assertEqual(request.messages[-1].tool_call_id, "first")
                self.store.set_current(self.reading(oxygen=6.4))
            if index == 3:
                self.assertEqual(request.tool_choice, "none")
                self.assertEqual([m.tool_call_id for m in request.messages if m.role == "tool"], ["first", "second"])
        gateway = RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final(), callback=inspect)
        with patch("fishery_ai.tool_conversation.ToolExecutor", wraps=ToolExecutor) as executor:
            result, handle = self.run_multi(gateway)
        self.assertEqual(executor.call_count, 1)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual([e.receipt.tool_name for e in result.source_ledger.entries], [QUERY, SCORE])
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION, result.source_ledger))
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_OBSERVATION_QUERY, result.source_ledger))
        public = result.to_dict()
        self.assertFalse(public["legacy_projection_available"])
        self.assertIsNone(public["tool_activity"])
        self.assertIsNone(public["request_1"])
        self.assertEqual(len(public["activity"]["steps"]), 5)
        self.assertEqual(public["activity"]["steps"], handle.public_info()["activity"]["steps"])
        with self.assertRaises(ValueError):
            _ = result.source_receipt
        for forbidden in ("arguments_json", "fictional:sensor", '"water_quality":', "source_ledger"):
            self.assertNotIn(forbidden, json.dumps(public))

    def test_no_data_no_match_and_requirement_gate(self):
        gateway = RecordingGateway(call(call_id="first"),
            call(KNOWLEDGE, '{"query":"fictional"}', "second"), final())
        request = replace(self.request(), source_requirement=SourceRequirement.PROJECT_KNOWLEDGE_SEARCH)
        result, _ = self.run_multi(gateway, request=request)
        receipts = [e.receipt for e in result.source_ledger.entries]
        self.assertEqual([r.tool_status.value for r in receipts], ["NO_DATA", "NO_MATCH"])
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertFalse(receipts[-1].has_project_evidence)
        failed, _ = self.run_multi(RecordingGateway(call(), final()), request=request)
        self.assert_failed(failed, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")

    def test_partial_not_scorable_receipts_stay_independent(self):
        self.store.set_current(self.reading(ph=None))
        result, _ = self.run_multi(RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final()))
        self.assertEqual(len(result.source_ledger.entries), 2)
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION, result.source_ledger))
        self.assertTrue(result.source_ledger.entries[-1].receipt.has_score)  # PARTIAL still has an experimental score.
        self.store.set_current(self.reading(ph=None, oxygen=None, temp=None))
        result, _ = self.run_multi(RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final()))
        self.assertEqual(result.source_ledger.entries[-1].receipt.tool_status.value, "NOT_SCORABLE")
        self.assertFalse(result.source_ledger.entries[-1].receipt.has_score)

    def test_second_tool_provider_failure_retains_ledger_but_never_history_success(self):
        for failing_request, expected_ledger in ((2, 1), (3, 2)):
            def fail(index, *_):
                if index == failing_request:
                    raise GatewayError("HTTP_ERROR")
            gateway = RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final(), callback=fail)
            result, handle = self.run_multi(gateway)
            self.assert_failed(result, "HTTP_ERROR")
            self.assertEqual(len(result.source_ledger.entries), expected_ledger)
            self.assertEqual(handle.state, "FAILED")

    def test_second_tool_error_retains_first_ledger(self):
        result, _ = self.run_multi(RecordingGateway(call(call_id="first"),
                                                    call(KNOWLEDGE, '{"bad":true}', "second")))
        self.assert_failed(result, "INVALID_TOOL_ARGUMENTS")
        self.assertEqual(len(result.source_ledger.entries), 2)  # ERROR Receipt grants no sources.
        self.assertFalse(result.source_ledger.entries[-1].receipt.project_search_completed)

    def test_third_call_and_duplicate_requests_rejected(self):
        for second, third, code in ((call(SCORE, call_id="second"), call(KNOWLEDGE, '{"query":"x"}', "third"), "TOOL_ROUND_LIMIT"),
                                    (call(call_id="second"), final(), "TOOL_REQUEST_ALREADY_EXECUTED")):
            gateway = RecordingGateway(call(call_id="first"), second, third)
            result, _ = self.run_multi(gateway)
            self.assert_failed(result, code)
            self.assertLessEqual(len(gateway.requests), 3)

    def test_multiple_calls_rejected_before_any_execution(self):
        response = replace(call(call_id="first"), tool_calls=(call(call_id="first").tool_calls[0],
                                                             call(SCORE, call_id="second").tool_calls[0]))
        with patch.object(self.reader, "query") as query:
            result, _ = self.run_multi(RecordingGateway(response))
        self.assert_failed(result, "TOOL_CALL_LIMIT")
        self.assertFalse(result.source_ledger.entries)
        query.assert_not_called()

    def test_deadline_after_tool_preserves_receipt_but_blocks_request_two(self):
        ticks = [0.0]
        handle = RequestHandle()
        report = handle.report_steps
        def observe(steps, **kwargs):
            report(steps, **kwargs)
            if isinstance(steps[-1], ToolExecutionStep) and steps[-1].result:
                ticks[0] = 2.0
        gateway = RecordingGateway(call(), final())
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]), \
                patch.object(handle, "report_steps", observe):
            result, _ = self.run_multi(gateway, timeout=1, handle=handle)
        self.assert_failed(result, "TOTAL_TIMEOUT")
        self.assertEqual(len(result.source_ledger.entries), 1)
        self.assertEqual(len(gateway.requests), 1)

    def test_coordinator_trace_failure_blocks_final_assistant_commit(self):
        with patch.object(self.traces, "record_tool_conversation", side_effect=OSError("fictional")):
            result, _ = self.run_multi(RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final()))
        self.assert_failed(result, "TRACE_WRITE_ERROR")
        self.assertEqual(len(result.source_ledger.entries), 2)

    def test_usage_all_three_requests_and_safe_trace(self):
        usage = Usage(input_tokens=2, output_tokens=1, total_tokens=3, source=UsageSource.PROVIDER)
        responses = [replace(call(call_id="first"), usage=usage), replace(call(SCORE, call_id="second"), usage=usage), final(usage=usage)]
        result, _ = self.run_multi(RecordingGateway(*responses))
        self.assertEqual(result.execution.usage.usage.total_tokens, 9)
        self.assertEqual(result.execution.usage.request_count, 3)
        trace = [json.loads(row) for row in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(trace[0]["steps"]), 5)
        self.assertIsNone(trace[0]["tool_name"])
        self.assertEqual(trace[-1]["status"], "completed")
        self.assertEqual(len(trace[-1]["activity"]["steps"]), 5)

    def test_history_keeps_final_pair_only_with_same_projection_and_trimming(self):
        history = self.history(8)
        result, _ = self.run_multi(RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final()),
                                   request=self.request(history=history))
        self.assertEqual(result.context.history_turns_sent, 6)
        next_request = self.request(history=(*history[-5:],
            type(history[0])("new", result.final_text, result.completed_at)))
        gateway = RecordingGateway(final())
        self.run_multi(gateway, request=next_request)
        transcript = json.loads(gateway.requests[0].messages[1].content)
        self.assertEqual(len(transcript["turns"]), 6)
        self.assertFalse(any(m.role == "tool" or m.tool_calls for m in gateway.requests[0].messages))
        self.assertNotIn("source_ledger", json.dumps(transcript))

    def test_stop_at_each_model_boundary(self):
        for stop_index in (1, 2, 3):
            handle = RequestHandle()
            def cancel(index, *_):
                if index == stop_index:
                    handle.cancel()
            gateway = RecordingGateway(call(call_id="first"), call(SCORE, call_id="second"), final(), callback=cancel)
            result, handle = self.run_multi(gateway, handle=handle)
            self.assert_failed(result, "USER_CANCELLED")
            self.assertEqual(handle.state, "CANCELLED")
            self.assertEqual(len(gateway.requests), stop_index)
            self.assertEqual(len(result.source_ledger.entries), stop_index - 1)

    def test_deadline_is_shared_and_stop_has_priority(self):
        for stop in (False, True):
            ticks = [0.0]
            handle = RequestHandle()
            def advance(index, *_):
                ticks[0] += 0.6
                if stop and index == 2:
                    handle.cancel()
            gateway = RecordingGateway(call(), final(), callback=advance)
            with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]):
                result, handle = self.run_multi(gateway, timeout=1, handle=handle)
            self.assert_failed(result, "USER_CANCELLED" if stop else "TOTAL_TIMEOUT")
            self.assertEqual(len(gateway.requests), 2)
            self.assertEqual(len(result.source_ledger.entries), 1)
            self.assertEqual(handle.state, "CANCELLED" if stop else "FAILED")

    def test_deadline_during_local_tool_blocks_followup(self):
        ticks = [0.0]
        def slow_query():
            ticks[0] = 2.0
            return None
        gateway = RecordingGateway(call(), final())
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]), \
                patch.object(self.reader, "query", side_effect=slow_query):
            result, _ = self.run_multi(gateway, timeout=1)
        self.assert_failed(result, "TOTAL_TIMEOUT")
        self.assertEqual(len(gateway.requests), 1)

    def test_deadline_during_context_build_sends_no_gateway_request(self):
        from fishery_ai.assistant import AssistantContextBuilder
        ticks = [0.0]
        build = AssistantContextBuilder.build
        def slow_build(builder, *args, **kwargs):
            context = build(builder, *args, **kwargs)
            ticks[0] = 2.0
            return context
        gateway = RecordingGateway(final())
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]), \
                patch.object(AssistantContextBuilder, "build", slow_build):
            result, _ = self.run_multi(gateway, timeout=1)
        self.assert_failed(result, "TOTAL_TIMEOUT")
        self.assertFalse(gateway.requests)

    def test_trace_failure_or_deadline_never_commits_success(self):
        with patch.object(self.traces, "record_assistant", side_effect=OSError("fictional-secret-path")):
            result, _ = self.run_multi(RecordingGateway(final()))
        self.assert_failed(result, "TRACE_WRITE_ERROR")
        ticks = [0.0]
        record = self.traces.record_assistant
        def delayed_record(*args, **kwargs):
            record(*args, **kwargs)
            ticks[0] = 2.0
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]), \
                patch.object(self.traces, "record_assistant", delayed_record):
            result, handle = self.run_multi(RecordingGateway(final()), timeout=1)
        self.assert_failed(result, "TOTAL_TIMEOUT")
        self.assertEqual(handle.public_info()["activity"]["state"], "FAILED")
        last = json.loads(self.trace.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last["error_code"], "TOTAL_TIMEOUT")

    def test_default_still_single_round_and_web_cannot_enable(self):
        gateway = RecordingGateway(call(), call(SCORE, call_id="second"), final())
        result = self.service(gateway, (QUERY, SCORE)).send(self.request(), self.runtime)
        self.assert_failed(result, "TOOL_ROUND_LIMIT")
        self.assertEqual(len(gateway.requests), 2)
        self.assertEqual(gateway.requests[0].messages[0].content, SYSTEM_INSTRUCTION)
        for key in ("execution_mode", "turn_timeout_s", "budget", "prompt_id"):
            with self.subTest(key=key), self.assertRaises(AssistantError):
                AssistantRequest.from_dict({"preset_id": LOCAL, "question": "test", key: "bounded"})
