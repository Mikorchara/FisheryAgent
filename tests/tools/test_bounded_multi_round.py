"""Explicit internal 2/2/3 runtime; scripted model decisions, no Provider I/O."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fishery_ai.assistant import AssistantError, AssistantService
from fishery_ai.assistant_sources import (SourceRequirement, TurnSourceLedger,
    ledger_from_execution, requirement_satisfied_by_ledger)
from fishery_ai.contracts import Mode, Status, Usage, UsageSource, WaterQualityReading, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import (GatewayError, ModelCapabilities, ModelMessage, ModelProfile,
    ModelRequest, ModelResponse, ModelToolCall, MockGateway, ProfileRegistry)
from fishery_ai.model_options import Support
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.providers import AuthSpec
from fishery_ai.telemetry.current import CurrentWaterQualityReader
from fishery_ai.telemetry.snapshot import CurrentSnapshotStore
from fishery_ai.tool_conversation import (BOUNDED_MULTI_ROUND_BUDGET, SINGLE_ROUND_BUDGET,
    ModelExecutionStep, ToolCallingService, ToolExecutionMode, ToolExecutionStep, ToolTurnBudget)
from fishery_ai.tools import ToolExecutor, ToolRegistry
from fishery_ai.tools.policy import ToolPolicy
from fishery_ai.tools.registry import CURRENT_WATER_QUALITY as WATER, WATER_QUALITY_SCORE as SCORE, SEARCH_FISHERY_KNOWLEDGE as KNOWLEDGE


NOW = parse_time("2026-10-12T02:00:00Z")


def call(name=WATER, call_id="first", arguments="{}", usage=None, finish_reason="tool_calls"):
    return ModelResponse(None, usage or Usage(), tool_calls=(ModelToolCall(call_id, name, arguments),),
                         finish_reason=finish_reason)


def final(text="scripted final", usage=None, finish_reason="stop"):
    return ModelResponse(text, usage or Usage(), finish_reason=finish_reason)


class EmptyKnowledge:
    backend = "portable"

    def search(self, query, **kwargs):
        return ()


class ScriptedGateway(MockGateway):
    def __init__(self, *responses, decide=None):
        super().__init__()
        self.responses, self.decide = responses, decide
        self.requests, self.runtimes = [], []

    def complete(self, request, runtime):
        super().complete(request, runtime)
        self.requests.append(request)
        self.runtimes.append(runtime)
        if self.decide:
            return self.decide(len(self.requests), request, runtime)
        response = self.responses[len(self.requests) - 1]
        if isinstance(response, Exception):
            raise response
        return response


class BoundedMultiRoundTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "socket.getaddrinfo", "socket.socket.connect",
                     "socket.socket.connect_ex", "socket.socket.sendto"):
            guard = patch(name, side_effect=AssertionError("offline scripted tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.trace_path = Path(directory.name) / "trace.jsonl"
        self.traces = JsonlTraceSink(self.trace_path)
        self.now = NOW
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: self.now)
        self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=EmptyKnowledge())
        self.policy = ToolPolicy("assistant", True, (WATER, SCORE, KNOWLEDGE))
        profile = ModelProfile("scripted", "Offline", "local", "http://mock.invalid/v1", "fictional",
            auth_spec=AuthSpec.NONE, max_retries=0, capabilities=ModelCapabilities(
                tool_calling=Support.SUPPORTED, service_id="custom", adapter_id="generic_openai_chat",
                base_url="http://mock.invalid/v1", model_id="fictional"))
        self.runtime = ProfileRegistry([profile], CredentialStore(process_env={})).snapshot("scripted")
        self.request = ModelRequest(Mode.CHAT, (ModelMessage("system", "scripted test instruction"),
                                               ModelMessage("user", "scripted question")))

    def reading(self, **changes):
        return WaterQualityReading.from_raw({"temp":28, "ph":7.5, "oxygen":6.4, **changes},
            observed_at=self.now, retrieved_at=self.now, source="fictional:sensor", stale_after_s=300)

    def service(self, gateway, **kwargs):
        return ToolCallingService(gateway, self.registry, self.traces, policy=self.policy,
            execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND, clock=lambda: self.now, **kwargs)

    def run_turn(self, *responses, **kwargs):
        gateway = ScriptedGateway(*responses)
        result = self.service(gateway).run_request(self.request, self.runtime, **kwargs)
        return result, gateway

    def tools(self, result):
        return [item for item in result.steps if isinstance(item, ToolExecutionStep)]

    def trace(self):
        return json.loads(self.trace_path.read_text(encoding="utf-8").splitlines()[-1])

    def test_request_one_direct_final_spends_no_tool_budget(self):
        with patch.object(self.reader, "query") as query, patch("fishery_ai.tool_conversation.ToolExecutor") as execute:
            result, gateway = self.run_turn(final())
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(len(gateway.requests), 1)
        self.assertEqual(result.steps[0].result.outcome, "final_answer")
        self.assertEqual(ledger_from_execution(result), TurnSourceLedger())
        query.assert_not_called()
        execute.assert_not_called()

    def test_tool_then_early_final_despite_remaining_budget(self):
        result, gateway = self.run_turn(call(), final(), call(SCORE, "never"))
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(len(gateway.requests), 2)
        self.assertEqual([item.tool_choice for item in gateway.requests], ["auto", "auto"])
        self.assertEqual(len(self.tools(result)), 1)
        self.assertEqual(self.tools(result)[0].result.status.value, "NO_DATA")

    def test_real_result_controls_next_model_decision_and_can_end_early(self):
        for oxygen, expected_requests in ((2.2, 3), (6.4, 2)):
            with self.subTest(oxygen=oxygen):
                self.store.set_current(self.reading(oxygen=oxygen))
                def decide(index, request, runtime):
                    if index == 1:
                        self.assertFalse(any(item.role == "tool" for item in request.messages))
                        return call()
                    if index == 2:
                        payload = json.loads(request.messages[-1].content)
                        self.assertEqual(payload["water_quality"]["dissolved_oxygen_mg_l"], oxygen)
                        self.assertEqual(request.messages[-1].tool_call_id, "first")
                        self.assertEqual(request.messages[-2].tool_calls[0].function_name, WATER)
                        return call(SCORE, "second") if payload["water_quality"]["dissolved_oxygen_mg_l"] < 3 else final()
                    self.assertEqual(request.tool_choice, "none")
                    self.assertEqual([item.tool_call_id for item in request.messages if item.role == "tool"], ["first", "second"])
                    return final()
                gateway = ScriptedGateway(decide=decide)
                with patch("fishery_ai.tool_conversation.ToolExecutor", wraps=ToolExecutor) as executor:
                    result = self.service(gateway).run_request(self.request, self.runtime)
                self.assertEqual(result.status, Status.COMPLETED)
                self.assertEqual(len(gateway.requests), expected_requests)
                executor.assert_called_once()
                self.assertEqual([step.tool_name for step in self.tools(result)],
                                 [WATER, SCORE] if oxygen < 3 else [WATER])

    def test_frozen_runtime_credential_and_policy_across_all_requests(self):
        service = None
        def decide(index, request, runtime):
            self.assertIs(runtime, self.runtime)
            self.assertIs(runtime.credential, self.runtime.credential)
            if index == 1:
                service.policy = ToolPolicy("assistant", False, ())
                return call()
            self.assertEqual(tuple(tool.name for tool in request.tools), self.policy.exposed_tools)
            return call(SCORE, "second") if index == 2 else final()
        gateway = ScriptedGateway(decide=decide)
        service = self.service(gateway)
        result = service.run_request(self.request, self.runtime)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(len(gateway.requests), 3)

    def test_two_results_and_ordered_receipts_keep_distinct_observation_times(self):
        self.store.set_current(self.reading(oxygen=2.2))
        def decide(index, request, runtime):
            if index == 1:
                return call()
            if index == 2:
                self.now += timedelta(minutes=1)
                self.store.set_current(self.reading(oxygen=6.4))
                return call(SCORE, "second")
            return final()
        result = self.service(ScriptedGateway(decide=decide)).run_request(self.request, self.runtime)
        ledger = ledger_from_execution(result)
        self.assertEqual([entry.execution_seq for entry in ledger.entries], [2, 4])
        self.assertEqual([entry.model_request_index for entry in ledger.entries], [1, 2])
        self.assertEqual([entry.tool_round for entry in ledger.entries], [1, 2])
        self.assertNotEqual(ledger.entries[0].receipt.observed_at, ledger.entries[1].receipt.observed_at)
        self.assertNotEqual(ledger.entries[0].receipt.evaluated_at, ledger.entries[1].receipt.evaluated_at)
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION, ledger))
        with self.assertRaises(ValueError):
            _ = result.tool_result

    def test_third_request_is_final_only_and_no_fourth_request(self):
        result, gateway = self.run_turn(call(), call(SCORE, "second"), call(KNOWLEDGE, "third", '{"query":"x"}'), final())
        self.assertEqual(result.error_code, "TOOL_ROUND_LIMIT")
        self.assertEqual(len(gateway.requests), 3)
        self.assertEqual(gateway.requests[-1].tool_choice, "none")
        self.assertEqual(len(self.tools(result)), 2)
        self.assertEqual(len(result.steps), BOUNDED_MULTI_ROUND_BUDGET.max_steps)
        self.assertEqual(result.generated_text, "")

    def test_multiple_calls_in_either_open_round_are_rejected_as_a_batch(self):
        multiple = ModelResponse(None, tool_calls=(ModelToolCall("x", WATER, "{}"),
            ModelToolCall("y", SCORE, "{}")), finish_reason="tool_calls")
        for responses, executions in (((multiple,), 0), ((call(), multiple), 1)):
            with self.subTest(round=len(responses)), patch.object(self.reader, "query", wraps=self.reader.query) as query:
                result, gateway = self.run_turn(*responses)
                self.assertEqual(result.error_code, "TOOL_CALL_LIMIT")
                self.assertEqual(query.call_count, executions)
                self.assertEqual(len(gateway.requests), len(responses))
                self.assertEqual(len(self.tools(result)), executions)

    def test_duplicate_call_id_and_logical_parameterless_call_are_not_executed_twice(self):
        for second, code in ((call(SCORE, "first"), "TOOL_CALL_ALREADY_EXECUTED"),
                             (call(WATER, "different", "{ }"), "TOOL_REQUEST_ALREADY_EXECUTED")):
            with self.subTest(code=code), patch.object(self.reader, "query", wraps=self.reader.query) as query:
                result, gateway = self.run_turn(call(), second, final())
                self.assertEqual(result.error_code, code)
                self.assertEqual(len(gateway.requests), 2)
                self.assertEqual(query.call_count, 1)
                receipts = ledger_from_execution(result).entries
                self.assertTrue(receipts[0].receipt.observation_query_completed)
                self.assertFalse(receipts[1].receipt.observation_query_completed)

    def test_normalized_query_dedup_validates_once_without_trace_query(self):
        definition = self.registry.lookup(KNOWLEDGE)
        validator = Mock(wraps=definition.validate_arguments)
        handler = Mock(wraps=definition.handler)
        controlled = replace(definition, handler=handler, validate_arguments=validator)
        original_lookup = self.registry.lookup
        def lookup(name):
            return controlled if name == KNOWLEDGE else original_lookup(name)
        with patch.object(self.registry, "lookup", side_effect=lookup):
            result, gateway = self.run_turn(call(KNOWLEDGE, "first", '{"query":" confidential-query "}'),
                call(KNOWLEDGE, "second", '{ "query" : "confidential-query" }'), final())
        self.assertEqual(result.error_code, "TOOL_REQUEST_ALREADY_EXECUTED")
        self.assertEqual(validator.call_count, 2)
        handler.assert_called_once()
        self.assertNotIn("confidential-query", self.trace_path.read_text(encoding="utf-8") + repr(result))
        self.assertEqual(len(gateway.requests), 2)

    def test_different_normalized_queries_are_allowed_after_no_match_without_auto_rewrite(self):
        result, gateway = self.run_turn(call(KNOWLEDGE, "first", '{"query":"one"}'),
            call(KNOWLEDGE, "second", '{"query":"two"}'), final())
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(len(gateway.requests), 3)
        ledger = ledger_from_execution(result)
        self.assertEqual([entry.receipt.tool_status.value for entry in ledger.entries], ["NO_MATCH", "NO_MATCH"])
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.PROJECT_KNOWLEDGE_SEARCH, ledger))
        self.assertFalse(any(entry.receipt.has_project_evidence for entry in ledger.entries))

    def test_negative_business_results_keep_existing_source_semantics(self):
        for reading, score_status in ((None, "NO_DATA"), (self.reading(ph="bad"), "NOT_SCORABLE"),
                                      (self.reading(ph=None), "PARTIAL")):
            with self.subTest(status=score_status):
                if reading:
                    self.store.set_current(reading)
                else:
                    self.assertIsNone(self.store.get_current())
                result, gateway = self.run_turn(call(SCORE), call(KNOWLEDGE, "second", '{"query":"x"}'), final())
                self.assertEqual(result.status, Status.COMPLETED)
                ledger = ledger_from_execution(result)
                self.assertEqual(ledger.entries[0].receipt.tool_status.value, score_status)
                self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION, ledger))
                self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_OBSERVATION_QUERY, ledger))
                self.assertEqual(ledger.entries[0].receipt.has_score, score_status == "PARTIAL")
                self.assertTrue(ledger.entries[1].receipt.project_search_completed)
                self.assertFalse(ledger.entries[1].receipt.has_project_evidence)
                self.assertEqual(len(gateway.requests), 3)

    def test_no_data_allows_model_final_without_reapplying_or_requerying(self):
        with patch.object(self.reader, "query", wraps=self.reader.query) as query:
            result, gateway = self.run_turn(call(), final())
        query.assert_called_once_with()
        self.assertIsNone(self.store.get_current())
        self.assertEqual(len(gateway.requests), 2)
        receipt = ledger_from_execution(result).entries[0].receipt
        self.assertTrue(receipt.observation_query_completed)
        self.assertFalse(receipt.has_observation)

    def test_second_tool_error_preserves_first_receipt_but_not_final_success(self):
        for response, code in ((call("shell", "second"), "UNKNOWN_TOOL"),
                               (call(SCORE, "second", '{"extra":1}'), "INVALID_TOOL_ARGUMENTS")):
            with self.subTest(code=code):
                result, gateway = self.run_turn(call(), response, final())
                self.assertEqual(result.error_code, code)
                self.assertEqual(result.status, Status.FAILED)
                self.assertEqual(result.generated_text, "")
                self.assertEqual(len(gateway.requests), 2)
                ledger = ledger_from_execution(result)
                self.assertTrue(ledger.entries[0].receipt.observation_query_completed)
                self.assertFalse(ledger.entries[1].receipt.score_evaluation_completed)

    def test_unauthorized_second_tool_and_handler_exception_fail_closed(self):
        self.policy = ToolPolicy("assistant", True, (WATER,))
        result, gateway = self.run_turn(call(), call(SCORE, "second"), final())
        self.assertEqual(result.error_code, "TOOL_NOT_ALLOWED")
        self.assertEqual(len(gateway.requests), 2)
        self.policy = ToolPolicy("assistant", True, (WATER, SCORE))
        definition = self.registry.lookup(SCORE)
        original_lookup = self.registry.lookup
        def lookup(name):
            return replace(definition, handler=Mock(side_effect=RuntimeError("fake-private-secret"))) if name == SCORE else original_lookup(name)
        with patch.object(self.registry, "lookup", side_effect=lookup):
            result, _ = self.run_turn(call(), call(SCORE, "second"), final())
        self.assertEqual(result.error_code, "TOOL_EXECUTION_ERROR")
        self.assertTrue(ledger_from_execution(result).entries[0].receipt.observation_query_completed)
        self.assertNotIn("fake-private-secret", self.trace_path.read_text(encoding="utf-8") + repr(result))

    def test_provider_failure_on_later_requests_keeps_completed_receipts(self):
        for responses, receipt_count in (((call(), GatewayError("READ_TIMEOUT")), 1),
                                        ((call(), call(SCORE, "second"), GatewayError("HTTP_ERROR")), 2)):
            with self.subTest(request=len(responses)):
                result, gateway = self.run_turn(*responses)
                self.assertEqual(result.status, Status.FAILED)
                self.assertEqual(len(gateway.requests), len(responses))
                self.assertEqual(len(ledger_from_execution(result).entries), receipt_count)
                self.assertEqual(result.generated_text, "")

    def test_malformed_and_truncated_tool_calls_do_not_execute_or_repair(self):
        broken = object.__new__(ModelToolCall)
        for key, value in {"id":"broken", "function_name":SCORE, "arguments_json":"{", "type":"function"}.items():
            object.__setattr__(broken, key, value)
        malformed = ModelResponse(None, tool_calls=(broken,), finish_reason="tool_calls")
        for second, code in ((malformed, "MODEL_TOOL_CALL_MALFORMED"),
                             (call(SCORE, "second", finish_reason="length"), "MODEL_TOOL_CALL_INCOMPLETE")):
            with self.subTest(code=code), patch.object(self.reader, "query", wraps=self.reader.query) as query:
                result, gateway = self.run_turn(call(), second)
                self.assertEqual(result.error_code, code)
                self.assertEqual(query.call_count, 1)
                self.assertEqual(len(ledger_from_execution(result).entries), 1)
                self.assertEqual(len(gateway.requests), 2)

    def test_final_empty_truncated_or_incomplete_is_not_a_success(self):
        for response, code in ((final(""), "MODEL_RESPONSE_EMPTY"),
                               (final(finish_reason="length"), "MODEL_RESPONSE_TRUNCATED"),
                               (final(finish_reason="content_filter"), "MODEL_RESPONSE_INCOMPLETE")):
            with self.subTest(code=code):
                result, _ = self.run_turn(call(), call(SCORE, "second"), response)
                self.assertEqual(result.error_code, code)
                self.assertEqual(result.status, Status.FAILED)
                self.assertEqual(result.generated_text, "")
                self.assertEqual(len(ledger_from_execution(result).entries), 2)

    def test_cancel_before_each_model_request_prevents_the_next_transport(self):
        for phase, requests, tools in (("REQUEST_1", 0, 0), ("REQUEST_2", 1, 1), ("REQUEST_3", 2, 2)):
            with self.subTest(phase=phase):
                handle = RequestHandle()
                def progress(value):
                    handle.report_phase(value)
                    if value == phase:
                        handle.cancel()
                gateway = ScriptedGateway(call(), call(SCORE, "second"), final())
                with request_scope(handle):
                    result = self.service(gateway).run_request(self.request, self.runtime, on_progress=progress)
                self.assertEqual(result.status, Status.CANCELLED)
                self.assertEqual(result.error_code, "USER_CANCELLED")
                self.assertEqual(len(gateway.requests), requests)
                self.assertEqual(len(ledger_from_execution(result).entries), tools)

    def test_cancel_after_each_model_response_prevents_tool_or_success(self):
        for cancel_at, tools in ((1, 0), (2, 1), (3, 2)):
            with self.subTest(request=cancel_at):
                handle = RequestHandle()
                def decide(index, request, runtime):
                    if index == cancel_at:
                        handle.cancel()
                    return call() if index == 1 else call(SCORE, "second") if index == 2 else final()
                gateway = ScriptedGateway(decide=decide)
                with request_scope(handle):
                    result = self.service(gateway).run_request(self.request, self.runtime)
                self.assertEqual(result.status, Status.CANCELLED)
                self.assertEqual(len(gateway.requests), cancel_at)
                self.assertEqual(len(ledger_from_execution(result).entries), tools)
                self.assertEqual(result.generated_text, "")

    def test_cancel_after_either_tool_preserves_receipts_and_stops_next_request(self):
        execute = ToolExecutor.execute
        for cancel_round in (1, 2):
            with self.subTest(round=cancel_round):
                handle = RequestHandle()
                calls = []
                def cancel_after(executor, invocation):
                    returned = execute(executor, invocation)
                    calls.append(invocation)
                    if len(calls) == cancel_round:
                        handle.cancel()
                    return returned
                gateway = ScriptedGateway(call(), call(SCORE, "second"), final())
                with request_scope(handle), patch.object(ToolExecutor, "execute", new=cancel_after):
                    result = self.service(gateway).run_request(self.request, self.runtime)
                self.assertEqual(result.status, Status.CANCELLED)
                self.assertEqual(len(gateway.requests), cancel_round)
                self.assertEqual(len(ledger_from_execution(result).entries), cancel_round)

    def test_three_usage_records_aggregate_and_missing_usage_is_not_zero(self):
        one, two, three = (Usage(3, 2, 5, source=UsageSource.PROVIDER),
                           Usage(5, 4, 9, source=UsageSource.PROVIDER),
                           Usage(7, 6, 13, source=UsageSource.PROVIDER))
        result, _ = self.run_turn(call(usage=one), call(SCORE, "second", usage=two), final(usage=three))
        self.assertEqual(result.usage.request_count, 3)
        self.assertEqual(result.usage.reported_count, 3)
        self.assertEqual(result.usage.usage.total_tokens, 27)
        self.assertEqual([step.result.usage for step in result.steps if isinstance(step, ModelExecutionStep)], [one, two, three])
        result, _ = self.run_turn(call(usage=one), call(SCORE, "second"), final(usage=three))
        self.assertEqual(result.usage.request_count, 3)
        self.assertEqual(result.usage.reported_count, 2)
        self.assertIsNone(result.usage.usage.total_tokens)
        self.assertEqual(result.usage.usage.source, UsageSource.UNAVAILABLE)

    def test_final_instruction_is_only_added_to_forced_final_request(self):
        result, gateway = self.run_turn(call(), call(SCORE, "second"), final(),
            final_response_instruction="scripted final format")
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(gateway.requests[1].messages[-1].role, "tool")
        self.assertNotIn("scripted final format", [item.content for item in gateway.requests[1].messages])
        self.assertEqual(gateway.requests[2].messages[-1], ModelMessage("user", "scripted final format"))
        self.assertNotIn("scripted final format", self.trace_path.read_text(encoding="utf-8"))

    def test_cancel_at_tool_start_never_executes_pending_handler(self):
        for stop_round in (1, 2):
            with self.subTest(round=stop_round):
                handle = RequestHandle()
                rounds = []
                def progress(phase):
                    handle.report_phase(phase)
                    if phase == "RUNNING_TOOL":
                        rounds.append(phase)
                        if len(rounds) == stop_round:
                            handle.cancel()
                gateway = ScriptedGateway(call(), call(SCORE, "second"), final())
                with request_scope(handle), patch.object(self.reader, "query", wraps=self.reader.query) as query:
                    result = self.service(gateway).run_request(self.request, self.runtime, on_progress=progress)
                self.assertEqual(result.error_code, "USER_CANCELLED")
                self.assertEqual(query.call_count, stop_round - 1)
                self.assertEqual(len(gateway.requests), stop_round)
                self.assertEqual(len(ledger_from_execution(result).entries), stop_round - 1)
                self.assertIsNone(self.tools(result)[-1].result)

    def test_default_single_round_request_encoding_and_stop_parity(self):
        gateway = ScriptedGateway(call(), final(), call(SCORE, "never"))
        service = ToolCallingService(gateway, self.registry, self.traces, policy=self.policy)
        result = service.run_request(self.request, self.runtime, final_response_instruction="fixed final format")
        self.assertEqual(service.execution_mode, ToolExecutionMode.SINGLE_ROUND)
        self.assertEqual(service.budget, SINGLE_ROUND_BUDGET)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual([item.tool_choice for item in gateway.requests], ["auto", "none"])
        self.assertEqual(gateway.requests[1].messages[:2], self.request.messages)
        self.assertEqual(gateway.requests[1].messages[2].tool_calls[0], ModelToolCall("first", WATER, "{}"))
        self.assertEqual(gateway.requests[1].messages[3].content, result.tool_result.to_json())
        self.assertEqual(gateway.requests[1].messages[-1].content, "fixed final format")
        self.assertEqual(result.request_1.outcome, "tool_calls")
        self.assertEqual(result.request_2.outcome, "final_answer")
        self.assertEqual(result.usage.request_count, 2)

    def test_empty_policy_direct_answer_never_opens_executor_or_extra_requests(self):
        self.policy = ToolPolicy("assistant", False, ())
        with patch("fishery_ai.tool_conversation.ToolExecutor") as executor:
            result, gateway = self.run_turn(final())
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(gateway.requests[0].tools, ())
        self.assertIsNone(gateway.requests[0].tool_choice)
        self.assertEqual(len(gateway.requests), 1)
        executor.assert_not_called()

    def test_trace_preserves_five_ordered_steps_without_raw_data(self):
        result, _ = self.run_turn(call(), call(KNOWLEDGE, "second", '{"query":"private-query"}'), final("private-final"))
        trace = self.trace()
        self.assertEqual([step["kind"] for step in trace["steps"]], ["model", "tool", "model", "tool", "model"])
        self.assertEqual([step["seq"] for step in trace["steps"]], [1, 2, 3, 4, 5])
        self.assertEqual([step["request_index"] for step in trace["steps"] if step["kind"] == "model"], [1, 2, 3])
        self.assertFalse(trace["legacy_projection_available"])
        text = json.dumps(trace) + repr(result)
        for forbidden in ("private-query", "private-final", "scripted question", "arguments_json", "_content_json"):
            self.assertNotIn(forbidden, text)

    def test_trace_write_failure_cannot_be_a_successful_turn(self):
        with patch.object(self.traces, "record_tool_conversation", side_effect=OSError("private path")):
            result, _ = self.run_turn(call(), call(SCORE, "second"), final())
        self.assertEqual(result.error_code, "TRACE_WRITE_ERROR")
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(len(ledger_from_execution(result).entries), 2)
        self.assertEqual(result.generated_text, "")

    def test_explicit_internal_mode_cannot_change_budgets_or_retry(self):
        service = self.service(ScriptedGateway())
        self.assertEqual(service.budget, ToolTurnBudget(2, 2, 3))
        for budget in (ToolTurnBudget(3, 3, 4), SINGLE_ROUND_BUDGET):
            with self.assertRaises(ValueError):
                self.service(ScriptedGateway(), budget=budget)
        with self.assertRaises(ValueError):
            ToolCallingService(ScriptedGateway(), self.registry, self.traces, budget=BOUNDED_MULTI_ROUND_BUDGET)
        with self.assertRaises(FrozenInstanceError):
            service.budget.max_model_requests = 4
        with self.assertRaises(AttributeError):
            service.execution_mode = ToolExecutionMode.SINGLE_ROUND
        with self.assertRaises(ValueError):
            service.converse("legacy prompt", self.runtime)
        with self.assertRaises(AssistantError):
            AssistantService(service)
        gateway = ScriptedGateway(final())
        result = self.service(gateway).run_request(self.request, replace(self.runtime, max_retries=1))
        self.assertEqual(result.error_code, "TOOL_RETRY_NOT_ALLOWED")
        self.assertEqual(len(gateway.requests), 0)

    def test_unknown_capability_still_blocks_before_transport(self):
        gateway = ScriptedGateway(call())
        runtime = replace(self.runtime, capabilities=replace(self.runtime.capabilities, tool_calling=Support.UNKNOWN))
        result = self.service(gateway).run_request(self.request, runtime)
        self.assertEqual(result.error_code, "OPTION_UNKNOWN")
        self.assertEqual(len(gateway.requests), 0)
        self.assertEqual(ledger_from_execution(result), TurnSourceLedger())

    def test_internal_final_does_not_override_source_requirement_commit_gate(self):
        result, _ = self.run_turn(final("[调用工具] 已评分"))
        ledger = ledger_from_execution(result)
        self.assertTrue(requirement_satisfied_by_ledger(SourceRequirement.AUTO, ledger))
        self.assertFalse(requirement_satisfied_by_ledger(SourceRequirement.CURRENT_SCORE_EVALUATION, ledger))
        self.assertFalse(ledger.entries)
