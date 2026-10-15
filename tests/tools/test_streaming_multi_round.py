"""Internal Streaming → shared runtime → real read-only Handlers; all Provider I/O fake."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import httpx
from openai import APIConnectionError

from fishery_ai.assistant import AssistantHistoryTurn, AssistantRequest, AssistantService, assistant_profile
from fishery_ai.assistant_sources import SourceRequirement, requirement_satisfied_by_ledger
from fishery_ai.contracts import KnowledgeEvidence, Mode, Status, Usage, UsageSource, WaterQualityReading, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelRequest, ProfileRegistry
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tool_conversation import ModelExecutionStep, ToolCallingService, ToolExecutionMode, ToolModelTransport
from fishery_ai.tools import ToolExecutor, ToolRegistry
from fishery_ai.tools.policy import ToolPolicy
from tests.assistant.test_assistant import LOCAL, QUERY, SCORE, KNOWLEDGE, RecordingGateway, call, final
from tests.providers.test_streaming_tool_assembler import chunk, delta
import tests.security.test_execution as execution_fixture


NOW = parse_time("2026-10-13T03:00:00Z")
BLOCK = object()
STATISTICS = NS(prompt_tokens=2, completion_tokens=3, total_tokens=5)


def tool_chunks(name=QUERY, identifier="call_1", arguments='{}'):
    midpoint = len(arguments) // 2
    return [chunk([delta(name=name[:5], identifier=identifier, call_type="function")]),
            chunk([delta(arguments[:midpoint], name=name[5:])]),
            chunk([delta(arguments[midpoint:])]), chunk(finish="tool_calls", usage=STATISTICS)]


def final_chunks():
    return [chunk(content="安全"), chunk(content="回答", finish="stop", usage=STATISTICS)]


class FixtureKnowledge:
    backend = "portable"
    def search(self, query, **kwargs):
        return (KnowledgeEvidence("fixture-evidence", "fictional-background-evidence", "water_quality",
            0.9, "fictional-knowledge-source", NOW, source_version="fixture-1"),)


class StreamingMultiRoundTests(unittest.TestCase):
    def test_extra_arguments_never_execute_or_followup_and_keep_safe_diagnostic(self):
        gateway = self.gateway([tool_chunks(arguments='{"device_id":"fictional-private-argument"}')])
        with patch.object(self.reader, 'query') as handler:
            result, handle = self.send(gateway)
        self.assert_failed(result, 'INVALID_TOOL_ARGUMENTS')
        handler.assert_not_called()
        self.assertEqual(len(self.bodies), 1)
        self.assert_closed()
        activity = result.to_dict()['activity']
        self.assertEqual(activity['steps'][-1]['argument_diagnostic']['reason'], 'UNEXPECTED_ARGUMENTS')
        self.assertEqual(activity['counts']['tools_executed'], 0)
        self.assertFalse(result.source_receipt.sources)
        public = json.dumps(activity) + self.trace_path.read_text(encoding='utf-8')
        self.assertNotIn('fictional-private-argument', public)
        self.assertNotIn('device_id', public)

    def setUp(self):
        execution_fixture.ExecutionTests.setUp(self)  # Offline guard + asyncio wakeup exception only.
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.trace_path = self.root / "trace.jsonl"
        self.traces = JsonlTraceSink(self.trace_path)
        self.now = NOW
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: self.now)
        self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=FixtureKnowledge())
        self.policy = ToolPolicy("assistant", True, (QUERY, SCORE, KNOWLEDGE))
        self.runtime = ProfileRegistry([assistant_profile(LOCAL)], CredentialStore(process_env={})).snapshot(assistant_profile(LOCAL).profile_id)
        self.bodies, self.runtimes, self.remaining, self.clients, self.lifecycle = [], [], [], [], []

    def reading(self, **changes):
        return WaterQualityReading.from_raw({"temp":28, "ph":7.5, "oxygen":2.2, **changes},
            observed_at=self.now, retrieved_at=self.now, source="fictional-sensor", stale_after_s=300)

    def gateway(self, plan, *, close_error_index=None, first_latency_s=0.0):
        fixture = self
        class Stream:
            def __init__(self, items, index): self.items, self.index, self.closed = items, index, False
            def __aiter__(self): return self.events()
            async def events(self):
                for item in self.items:
                    if item is BLOCK:
                        fixture.blocked.set(); await asyncio.Event().wait()
                    if isinstance(item, Exception): raise item
                    item.model = fixture.runtime.model
                    yield item
            async def close(self):
                self.closed = True; fixture.lifecycle.append(("stream_closed", self.index))
        class Client:
            def __init__(self, index):
                self.index, self.closed, self.stream = index, False, None
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **body):
                fixture.bodies.append(body)
                if self.index == 1 and first_latency_s:
                    await asyncio.sleep(first_latency_s)
                items = plan(self.index, body) if callable(plan) else plan[self.index - 1]
                self.stream = Stream(items, self.index)
                return self.stream
            async def close(self):
                self.closed = True; fixture.lifecycle.append(("client_closed", self.index))
                if self.index == close_error_index: raise RuntimeError("fictional-private-cleanup")
        def factory(runtime, remaining):
            fixture.runtimes.append(runtime); fixture.remaining.append(remaining)
            client = Client(len(fixture.clients) + 1); fixture.clients.append(client)
            return client
        self.blocked = threading.Event()
        return OpenAICompatibleAdapter(async_client_factory=factory)

    def coordinator(self, gateway, *, transport=ToolModelTransport.STREAMING, mode=ToolExecutionMode.BOUNDED_MULTI_ROUND):
        return ToolCallingService(gateway, self.registry, self.traces, policy=self.policy,
            execution_mode=mode, model_transport=transport)

    def send(self, gateway, *, request=None, handle=None, timeout=None):
        handle = handle or RequestHandle(); handle.start()
        service = AssistantService(self.coordinator(gateway), execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND,
            turn_timeout_s=timeout)
        with request_scope(handle):
            result = service.send(request or AssistantRequest(LOCAL, "离线多轮问题"), self.runtime)
        return result, handle

    def assert_closed(self):
        self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))

    def assert_failed(self, result, code):
        self.assertEqual(result.error_code, code)
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(result.final_text, "")
        self.assertIsNone(result.completed_at)

    def test_direct_final_does_not_execute_tools_or_spend_remaining_requests(self):
        gateway = self.gateway([final_chunks()])
        with patch.object(self.reader, "query") as query, patch("fishery_ai.tool_conversation.ToolExecutor") as executor:
            result, handle = self.send(gateway)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual(result.final_text, "安全回答")
        self.assertEqual((len(self.bodies), len(result.source_ledger.entries)), (1, 0))
        self.assertEqual(result.execution.model_transport, ToolModelTransport.STREAMING)
        self.assertEqual(handle.state, "COMPLETED")
        query.assert_not_called(); executor.assert_not_called(); self.assert_closed()

    def test_one_tool_then_early_final_preserves_unused_budget(self):
        gateway = self.gateway([tool_chunks(), final_chunks()])
        result, _ = self.send(gateway)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual([b["tool_choice"] for b in self.bodies], ["auto", "auto"])
        self.assertEqual(len(result.execution.steps), 3)
        self.assertEqual(result.source_ledger.entries[0].receipt.tool_status.value, "NO_DATA")
        self.assertEqual(len(self.bodies), 2); self.assert_closed()

    def test_real_tool_result_drives_second_stream_and_final_receives_both_results(self):
        self.store.set_current(self.reading())
        def decide(index, body):
            self.assertTrue(body["stream"])
            if index == 1:
                self.assertNotIn('"dissolved_oxygen_mg_l"', json.dumps(body["messages"]))
                return tool_chunks()
            tool_messages = [m for m in body["messages"] if m["role"] == "tool"]
            if index == 2:
                water = json.loads(tool_messages[-1]["content"])["water_quality"]
                self.assertEqual(water["dissolved_oxygen_mg_l"], 2.2)
                self.assertEqual(tool_messages[-1]["tool_call_id"], "call_1")
                # This fixture decision depends on the real Handler result; no program preplan.
                return tool_chunks(KNOWLEDGE, "call_2", '{"query":"fictional-low-oxygen"}') if water["dissolved_oxygen_mg_l"] < 3 else final_chunks()
            self.assertEqual(body["tool_choice"], "none")
            self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call_1", "call_2"])
            self.assertEqual(json.loads(tool_messages[-1]["content"])["evidence"][0]["id"], "fixture-evidence")
            return final_chunks()
        gateway = self.gateway(decide)
        original = self.reader.query
        def query():
            self.assert_closed()  # Stream/client both closed before the Handler begins.
            return original()
        with patch.object(self.reader, "query", side_effect=query), patch("fishery_ai.tool_conversation.ToolExecutor", wraps=ToolExecutor) as executor:
            result, _ = self.send(gateway)
        self.assertEqual(executor.call_count, 1)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual(len(self.bodies), 3)
        self.assertTrue(all(r is self.runtime for r in self.runtimes))
        self.assertEqual([e.receipt.tool_name for e in result.source_ledger.entries], [QUERY, KNOWLEDGE])
        self.assertTrue(result.source_ledger.entries[1].receipt.has_project_evidence)
        self.assertEqual(result.execution.usage.request_count, 3)
        self.assertEqual(result.execution.usage.usage.total_tokens, 15)
        self.assertEqual([s.result.usage.total_tokens for s in result.execution.steps if isinstance(s, ModelExecutionStep)], [5, 5, 5])
        self.assert_closed()
        trace = self.trace_path.read_text(encoding="utf-8")
        self.assertNotIn("fictional-low-oxygen", trace)
        self.assertNotIn("fictional-background-evidence", trace)
        self.assertNotIn("fictional-sensor", trace)
        self.assertTrue(all(row["model_transport"] == "STREAMING" for row in map(json.loads, trace.splitlines())))

    def test_normal_snapshot_result_allows_model_to_end_without_knowledge(self):
        self.store.set_current(self.reading(oxygen=6.4))
        def decide(index, body):
            if index == 1: return tool_chunks()
            payload = json.loads(next(m for m in reversed(body["messages"]) if m["role"] == "tool")["content"])
            self.assertEqual(payload["water_quality"]["dissolved_oxygen_mg_l"], 6.4)
            return final_chunks() if payload["water_quality"]["dissolved_oxygen_mg_l"] >= 3 else tool_chunks(KNOWLEDGE, "call_2", '{"query":"x"}')
        result, _ = self.send(self.gateway(decide))
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual(len(self.bodies), 2)
        self.assertEqual([e.receipt.tool_name for e in result.source_ledger.entries], [QUERY])

    def test_third_round_tool_is_rejected_without_fourth_request(self):
        plan = [tool_chunks(), tool_chunks(KNOWLEDGE, "call_2", '{"query":"x"}'), tool_chunks(SCORE, "call_3"), final_chunks()]
        result, _ = self.send(self.gateway(plan))
        self.assert_failed(result, "TOOL_ROUND_LIMIT")
        self.assertEqual(len(self.bodies), 3)
        self.assertEqual(self.bodies[-1]["tool_choice"], "none")
        self.assertEqual(len(result.source_ledger.entries), 2)

    def test_same_round_multiple_calls_are_rejected_before_any_handler(self):
        multiple = chunk([delta('{}', name=QUERY, identifier="one", call_type="function"),
            delta('{}', name=SCORE, identifier="two", call_type="function", index=1)])
        with patch.object(self.reader, "query") as query:
            result, _ = self.send(self.gateway([[multiple]]))
        self.assert_failed(result, "TOOL_CALL_LIMIT")
        self.assertEqual(len(result.source_ledger.entries), 0)
        self.assertEqual(len(self.bodies), 1); query.assert_not_called(); self.assert_closed()

    def test_argument_schema_validation_remains_in_executor(self):
        result, _ = self.send(self.gateway([tool_chunks(KNOWLEDGE, arguments='{"extra":1}')]))
        self.assert_failed(result, "INVALID_TOOL_ARGUMENTS")
        self.assertFalse(result.execution.steps[1].handler_started)
        self.assertFalse(requirement_satisfied_by_ledger(SourceRequirement.PROJECT_KNOWLEDGE_SEARCH, result.source_ledger))
        self.assertEqual(len(self.bodies), 1)

    def test_malformed_call_and_unexposed_name_never_execute(self):
        for frames in (tool_chunks(arguments='[]'), tool_chunks(name="shell")):
            self.bodies.clear(); self.clients.clear()
            with patch.object(self.reader, "query") as query:
                result, _ = self.send(self.gateway([frames]))
            self.assertFalse(result.to_dict()["successful_turn"])
            self.assertEqual(len(result.source_ledger.entries), 0)
            query.assert_not_called(); self.assert_closed()

    def test_duplicate_logical_request_is_not_reexecuted(self):
        result, _ = self.send(self.gateway([tool_chunks(), tool_chunks(QUERY, "call_2")]))
        self.assert_failed(result, "TOOL_REQUEST_ALREADY_EXECUTED")
        self.assertEqual([s.handler_started for s in result.execution.steps if hasattr(s, "handler_started")], [True, False])
        self.assertEqual(len(self.bodies), 2)

    def test_partial_usage_survives_disconnect_but_turn_cannot_commit(self):
        disconnected = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid/v1"))
        frames = [chunk(content="interim", usage=STATISTICS), disconnected]
        result, _ = self.send(self.gateway([tool_chunks(), frames]))
        self.assert_failed(result, "CONNECTION_ERROR")
        self.assertEqual(len(self.bodies), 2)
        self.assertEqual(result.execution.usage.request_count, 2)
        self.assertEqual(result.execution.usage.reported_count, 2)
        self.assertEqual(result.execution.usage.usage.total_tokens, 10)
        self.assertEqual(len(result.source_ledger.entries), 1)
        self.assert_closed()

    def test_first_stream_interrupt_cannot_become_tool_execution(self):
        with patch.object(self.reader, "query") as query:
            result, _ = self.send(self.gateway([tool_chunks()[:-1]]))
        self.assert_failed(result, "STREAM_INTERRUPTED")
        query.assert_not_called(); self.assertEqual(len(result.source_ledger.entries), 0); self.assert_closed()

    def test_truncated_final_retains_safe_finish_and_usage_but_not_success(self):
        frames = [chunk(content="incomplete", finish="length", usage=STATISTICS)]
        result, _ = self.send(self.gateway([tool_chunks(), frames]))
        self.assert_failed(result, "STREAM_TRUNCATED")
        self.assertEqual(result.execution.steps[-1].result.finish_reason, "length")
        self.assertEqual(result.execution.usage.usage.total_tokens, 10)
        self.assertEqual(len(result.source_ledger.entries), 1)

    def test_cleanup_error_retains_previous_receipt_and_never_executes_next_tool(self):
        gateway = self.gateway([tool_chunks(), tool_chunks(KNOWLEDGE, "call_2", '{"query":"x"}')], close_error_index=2)
        result, _ = self.send(gateway)
        self.assert_failed(result, "SDK_ERROR")
        self.assertEqual(len(result.source_ledger.entries), 1)
        self.assertEqual(result.execution.usage.usage.total_tokens, 10)
        self.assertNotIn("fictional-private-cleanup", self.trace_path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.bodies), 2)

    def test_source_gate_rejects_direct_final_without_required_current_query(self):
        request = AssistantRequest(LOCAL, "来源要求", source_requirement=SourceRequirement.CURRENT_OBSERVATION_QUERY)
        result, _ = self.send(self.gateway([final_chunks()]), request=request)
        self.assert_failed(result, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertEqual(len(result.source_ledger.entries), 0)

    def test_no_data_no_match_and_scoring_receipt_semantics_are_preserved(self):
        class EmptyKnowledge:
            backend = "portable"
            def search(self, *_, **__): return ()
        self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=EmptyKnowledge())
        request = AssistantRequest(LOCAL, "来源要求", source_requirement=SourceRequirement.PROJECT_KNOWLEDGE_SEARCH)
        result, _ = self.send(self.gateway([tool_chunks(), tool_chunks(KNOWLEDGE, "call_2", '{"query":"x"}'), final_chunks()]), request=request)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual([e.receipt.tool_status.value for e in result.source_ledger.entries], ["NO_DATA", "NO_MATCH"])
        self.assertFalse(result.source_ledger.entries[-1].receipt.has_project_evidence)
        for reading, expected in ((self.reading(oxygen="invalid"), "NOT_SCORABLE"), (self.reading(oxygen=None), "PARTIAL")):
            self.bodies.clear(); self.clients.clear(); self.store.set_current(reading)
            scored = AssistantRequest(LOCAL, "来源要求", source_requirement=SourceRequirement.CURRENT_SCORE_EVALUATION)
            result, _ = self.send(self.gateway([tool_chunks(SCORE), final_chunks()]), request=scored)
            self.assertTrue(result.to_dict()["successful_turn"])
            self.assertEqual(result.source_ledger.entries[0].receipt.tool_status.value, expected)

    def test_each_snapshot_receipt_preserves_its_own_observation_time(self):
        self.store.set_current(self.reading())
        def decide(index, body):
            if index == 1: return tool_chunks()
            if index == 2:
                self.now += timedelta(seconds=10); self.store.set_current(self.reading(oxygen=6.4))
                return tool_chunks(SCORE, "call_2")
            values = [json.loads(m["content"])["water_quality"]["dissolved_oxygen_mg_l"] for m in body["messages"] if m["role"] == "tool"]
            self.assertEqual(values, [2.2, 6.4])
            return final_chunks()
        result, _ = self.send(self.gateway(decide))
        self.assertTrue(result.to_dict()["successful_turn"])
        receipts = [e.receipt for e in result.source_ledger.entries]
        self.assertNotEqual(receipts[0].observed_at, receipts[1].observed_at)
        self.assertFalse(receipts[0].score_evaluation_completed)
        self.assertTrue(receipts[1].score_evaluation_completed)

    def test_cancel_during_each_model_stream_never_commits_late_success(self):
        for stop_index in (1, 2, 3):
            self.bodies.clear(); self.clients.clear()
            plans = [tool_chunks(), tool_chunks(KNOWLEDGE, "call_2", '{"query":"x"}'), final_chunks()]
            plans[stop_index - 1] = [chunk(content="pending", usage=STATISTICS), BLOCK]
            gateway = self.gateway(plans)
            handle = RequestHandle(); results = []
            worker = threading.Thread(target=lambda: results.append(self.send(gateway, handle=handle)[0]))
            worker.start(); self.assertTrue(self.blocked.wait(3)); handle.cancel(); worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assert_failed(results[0], "USER_CANCELLED")
            self.assertEqual(handle.state, "CANCELLED")
            self.assertEqual(len(self.bodies), stop_index)
            self.assertEqual(len(results[0].source_ledger.entries), stop_index - 1)
            self.assert_closed()

    def test_stop_before_tool_or_between_rounds_does_not_start_next_request(self):
        for after_tool in (False, True):
            self.bodies.clear(); self.clients.clear()
            gateway = self.gateway([tool_chunks(), final_chunks()])
            handle = RequestHandle(); original_phase = handle.report_phase; original_steps = handle.report_steps
            def phase(value):
                original_phase(value)
                if not after_tool and value == "RUNNING_TOOL": handle.cancel()
            def steps(value, **kwargs):
                original_steps(value, **kwargs)
                if after_tool and any(getattr(s, "result", None) is not None and hasattr(s, "handler_started") for s in value): handle.cancel()
            handle.report_phase = phase; handle.report_steps = steps
            result, _ = self.send(gateway, handle=handle)
            self.assert_failed(result, "USER_CANCELLED")
            self.assertEqual(len(self.bodies), 1)
            self.assertEqual(len(result.source_ledger.entries), int(after_tool)); self.assert_closed()

    def test_whole_turn_deadline_not_renewed_between_streams(self):
        gateway = self.gateway([tool_chunks(), [BLOCK]], first_latency_s=0.03)
        result, handle = self.send(gateway, timeout=0.5)
        self.assert_failed(result, "TOTAL_TIMEOUT")
        self.assertFalse(handle._cancel.is_set())
        self.assertEqual(len(self.bodies), 2)
        self.assertLess(self.remaining[1], self.remaining[0])
        self.assertEqual(len(result.source_ledger.entries), 1); self.assert_closed()

    def test_coordinator_alone_also_has_one_turn_deadline(self):
        runtime = replace(self.runtime, total_timeout_s=0.5)
        gateway = self.gateway([tool_chunks(), [BLOCK]], first_latency_s=0.03)
        result = self.coordinator(gateway).run_request(ModelRequest(Mode.CHAT, (ModelMessage("user", "offline"),)), runtime)
        self.assertEqual(result.error_code, "TOTAL_TIMEOUT")
        self.assertEqual(result.status, Status.FAILED)
        self.assertLess(self.remaining[1], self.remaining[0]); self.assert_closed()

    def test_trace_failure_cannot_commit_successful_assistant_turn(self):
        for method in ("record_tool_conversation", "record_assistant"):
            self.bodies.clear(); self.clients.clear()
            gateway = self.gateway([tool_chunks(), final_chunks()])
            with patch.object(self.traces, method, side_effect=OSError("fictional-private-path")):
                result, _ = self.send(gateway)
            self.assert_failed(result, "TRACE_WRITE_ERROR")
            self.assertEqual(len(result.source_ledger.entries), 1)
            self.assertEqual(len(self.bodies), 2)

    def test_late_cancel_or_deadline_during_tool_trace_corrects_execution_and_commit(self):
        original = self.traces.record_tool_conversation
        for stop in (False, True):
            self.bodies.clear(); self.clients.clear()
            handle = RequestHandle()
            def record(result, **kwargs):
                original(result, **kwargs)
                if result.status == Status.COMPLETED:
                    if stop: handle.cancel()
                    else: handle._deadline = 0.0
            with patch.object(self.traces, "record_tool_conversation", side_effect=record):
                result, _ = self.send(self.gateway([tool_chunks(), final_chunks()]), handle=handle)
            self.assert_failed(result, "USER_CANCELLED" if stop else "TOTAL_TIMEOUT")
            self.assertEqual(result.execution.status, result.status)
            traces = [json.loads(line) for line in self.trace_path.read_text(encoding="utf-8").splitlines()]
            corrected = [row for row in traces if row["request_id"] == result.execution.request_id
                         and row["kind"] == "read_only_tool_conversation"][-1]
            self.assertEqual(corrected["error_code"], result.error_code)
            self.assertEqual(len(result.source_ledger.entries), 1)
            self.assertEqual(len(self.bodies), 2)

    def test_normal_and_streaming_multi_round_have_equivalent_final_steps_ledger_and_usage(self):
        self.store.set_current(self.reading())
        streamed, _ = self.send(self.gateway([tool_chunks(), tool_chunks(KNOWLEDGE, "call_2", '{"query":"x"}'), final_chunks()]))
        usage = Usage(2, 3, 5, source=UsageSource.PROVIDER)
        normal_gateway = RecordingGateway(replace(call(call_id="call_1"), usage=usage),
            replace(call(KNOWLEDGE, '{"query":"x"}', "call_2"), usage=usage), final("安全回答", usage=usage))
        normal = AssistantService(self.coordinator(normal_gateway, transport=ToolModelTransport.NORMAL),
            execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND).send(AssistantRequest(LOCAL, "离线多轮问题"), self.runtime)
        self.assertEqual(streamed.status, normal.status)
        self.assertEqual(streamed.final_text, normal.final_text)
        self.assertEqual(streamed.execution.usage, normal.execution.usage)
        self.assertEqual(streamed.source_ledger, normal.source_ledger)
        self.assertEqual([s.result for s in streamed.execution.steps if isinstance(s, ModelExecutionStep)],
                         [s.result for s in normal.execution.steps if isinstance(s, ModelExecutionStep)])

    def test_history_next_turn_contains_only_final_text_pair_not_protocol_or_ledger(self):
        result, _ = self.send(self.gateway([tool_chunks(), final_chunks()]))
        request = AssistantRequest(LOCAL, "下一轮", (AssistantHistoryTurn("之前问题", result.final_text, result.completed_at),))
        self.bodies.clear(); self.clients.clear()
        next_result, _ = self.send(self.gateway([final_chunks()]), request=request)
        messages = self.bodies[0]["messages"]
        self.assertTrue(next_result.to_dict()["successful_turn"])
        self.assertEqual(next_result.context.history_turns_sent, 1)
        self.assertFalse(any(m["role"] == "tool" or m.get("tool_calls") for m in messages))
        text = json.dumps(messages, ensure_ascii=False)
        for marker in ("call_1", "observation_query_completed", '"water_quality"', '"NO_DATA"'): self.assertNotIn(marker, text)
        self.assertEqual(messages[-1]["content"], "下一轮")

    def test_missing_internal_gateway_is_blocked_not_silently_fallback_to_normal(self):
        gateway = RecordingGateway(final())
        result, _ = self.send(gateway)
        self.assert_failed(result, "TOOL_STREAM_TRANSPORT_NOT_IMPLEMENTED")
        self.assertEqual(gateway.requests, [])
        self.assertFalse(result.execution.steps[0].request_started)

    def test_internal_transport_is_typed_and_default_normal_is_unchanged(self):
        gateway = RecordingGateway(call(), final())
        coordinator = ToolCallingService(gateway, self.registry, self.traces, policy=self.policy)
        self.assertEqual(coordinator.model_transport, ToolModelTransport.NORMAL)
        with self.assertRaises(ValueError): self.coordinator(gateway, transport="STREAMING")
        result = coordinator.run_request(ModelRequest(Mode.CHAT, (ModelMessage("user", "offline"),)), self.runtime)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual([r.tool_choice for r in gateway.requests], ["auto", "none"])
        self.assertNotIn("model_transport", json.loads(self.trace_path.read_text(encoding="utf-8").splitlines()[-1]))

    def test_single_round_streaming_keeps_one_one_two_without_implicitly_upgrading(self):
        gateway = self.gateway([tool_chunks(), final_chunks()])
        coordinator = self.coordinator(gateway, mode=ToolExecutionMode.SINGLE_ROUND)
        result = coordinator.run_request(ModelRequest(Mode.CHAT, (ModelMessage("user", "offline"),)), self.runtime)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(result.budget.max_model_requests, 2)
        self.assertEqual([b["tool_choice"] for b in self.bodies], ["auto", "none"])

    def test_streaming_retry_config_and_product_stream_gate_cannot_be_relaxed(self):
        gateway = self.gateway([final_chunks()])
        result = self.coordinator(gateway).run_request(ModelRequest(Mode.CHAT, ()), replace(self.runtime, max_retries=1))
        self.assertEqual(result.error_code, "TOOL_RETRY_NOT_ALLOWED")
        self.assertEqual(self.bodies, [])
        with self.assertRaises(GatewayError) as error:
            list(gateway.stream(ModelRequest(Mode.CHAT, (), tools=self.registry.model_definitions()), self.runtime))
        self.assertEqual(error.exception.code, "TOOL_STREAMING_NOT_IMPLEMENTED")
        self.assertEqual(self.bodies, [])


if __name__ == "__main__":
    unittest.main()
