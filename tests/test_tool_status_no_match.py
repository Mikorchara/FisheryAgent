"""Step 3 offline tests: ToolStatus.NO_MATCH is a non-error business result.

Proves the whole chain: reliable error_code mapping, Executor passthrough, second
model request, Assistant completion, safe Trace, and safe UI projection - while the
five pre-existing statuses keep their exact meaning. No network, no real model.
"""

from dataclasses import replace
from importlib.resources import files
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fishery_ai.assistant import ALLOWED_PRESET_IDS, AssistantRequest, AssistantService, assistant_profile
from fishery_ai.contracts import Status, Usage, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.model_gateway import MockGateway, ModelResponse, ModelToolCall, ProfileRegistry
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tool_conversation import ToolCallingService
from fishery_ai.tools import (ToolDefinition, ToolErrorCode, ToolExecutionResult, ToolExecutor,
                              ToolRegistry, ToolStatus)
from fishery_ai.tools.policy import ToolPolicy


NOW = parse_time("2026-10-09T02:00:00Z")
QUERY = "get_current_water_quality"
LOCAL = ALLOWED_PRESET_IDS[2]
QUESTION = "鳗鱼缺氧有什么表现？"

NO_MATCH_PAYLOAD = {"status": "NO_MATCH", "retrieval_mode": "tfidf",
                    "retrieval_version": "fixture", "result_count": 0, "evidence": []}


class RecordingGateway(MockGateway):
    """Scripted responses plus the exact requests the coordinator sent."""

    def __init__(self, *responses):
        super().__init__(responses=responses)
        self.requests = []

    def complete(self, request, runtime):
        self.requests.append(request)
        return super().complete(request, runtime)


def tool_turn(call_id="no_match_call", name=QUERY):
    return ModelResponse(None, tool_calls=(ModelToolCall(call_id, name, "{}"),),
                         finish_reason="tool_calls")


def final(text="项目资料里没有相关记载。", finish="stop"):
    return ModelResponse(text, usage=Usage(), finish_reason=finish)


class NoMatchFixture(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Step 3 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.trace_path = Path(directory.name) / "trace.jsonl"
        self.traces = JsonlTraceSink(self.trace_path)
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: NOW)
        self.registry = ToolRegistry(self.reader, DiagnosisService())
        self.model_definition = self.registry.lookup(QUERY).model_definition
        self.profile = assistant_profile(LOCAL)
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={})).snapshot(
            self.profile.profile_id)

    def definition(self, payload=None, *, status="NO_MATCH"):
        body = dict(NO_MATCH_PAYLOAD if payload is None else payload)
        if payload is None and status != "NO_MATCH":
            body["status"] = status
        return ToolDefinition(self.model_definition, lambda: body)

    def execute(self, definition, **kwargs):
        with patch.object(self.registry, "lookup", return_value=definition):
            return ToolExecutor(self.registry, **kwargs).execute(ModelToolCall("no_match_call", QUERY, "{}"))

    def converse(self, definition, gateway):
        policy = ToolPolicy("assistant", True, (QUERY,))
        with patch.object(self.registry, "lookup", return_value=definition):
            service = ToolCallingService(gateway, self.registry, self.traces, policy=policy)
            return service.converse(QUESTION, self.runtime)

    def assistant_turn(self, definition, gateway):
        policy = ToolPolicy("assistant", True, (QUERY,))
        with patch.object(self.registry, "lookup", return_value=definition):
            service = AssistantService(ToolCallingService(gateway, self.registry, self.traces, policy=policy))
            return service.send(AssistantRequest(LOCAL, QUESTION, ()), self.runtime)

    def trace_entries(self):
        return [json.loads(line) for line in self.trace_path.read_text(encoding="utf-8").splitlines()]

    # -- 1. NO_MATCH is not an error ---------------------------------------

    def test_no_match_is_a_non_error_result(self):
        result = self.execute(self.definition())
        self.assertEqual(result.status, ToolStatus.NO_MATCH)
        self.assertIsNone(result.error_code)
        self.assertEqual(result.payload, NO_MATCH_PAYLOAD)
        self.assertEqual(json.loads(result.to_json())["status"], "NO_MATCH")
        self.assertEqual(result.to_dict()["status"], "NO_MATCH")

    def test_no_match_still_obeys_the_result_size_limit(self):
        oversized = {"status": "NO_MATCH", "evidence": [{"text": "中" * 400}]}
        result = self.execute(ToolDefinition(self.model_definition, lambda: oversized),
                              max_result_bytes=256)
        self.assertEqual(result.status, ToolStatus.ERROR)
        self.assertEqual(result.error_code, ToolErrorCode.TOOL_RESULT_TOO_LARGE)

    def test_value_domain_is_not_widened_beyond_no_match(self):
        for status in ("NO_RESULT", "NONE", "none", "no_match", ""):
            with self.subTest(status=status):
                result = self.execute(ToolDefinition(self.model_definition,
                                                     lambda s=status: {"status": s}))
                self.assertEqual(result.status, ToolStatus.ERROR)
                self.assertEqual(result.error_code, ToolErrorCode.TOOL_EXECUTION_ERROR)

    # -- 2. the five pre-existing statuses are unchanged -------------------

    def test_existing_statuses_keep_their_exact_meaning(self):
        cases = (("OK", None), ("PARTIAL", None), ("NOT_SCORABLE", None), ("NO_DATA", None),
                 ("ERROR", ToolErrorCode.TOOL_EXECUTION_ERROR))
        for status, code in cases:
            with self.subTest(status=status):
                payload = ({"status": "ERROR", "error_code": "TOOL_EXECUTION_ERROR"}
                           if status == "ERROR" else {"status": status})
                result = ToolExecutionResult.from_payload("fixture", QUERY, payload)
                self.assertEqual(result.status, ToolStatus(status))
                self.assertEqual(result.error_code, code)

    def test_no_data_and_no_match_are_distinct_members(self):
        self.assertNotEqual(ToolStatus.NO_DATA, ToolStatus.NO_MATCH)
        self.assertNotEqual(ToolStatus.NO_DATA.value, ToolStatus.NO_MATCH.value)

    # -- 3. the coordinator still sends Request #2 -------------------------

    def test_no_match_continues_to_request_2_and_completes(self):
        gateway = RecordingGateway(tool_turn(), final())
        result = self.converse(self.definition(), gateway)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertIsNone(result.error_code)
        self.assertEqual(result.request_1.outcome, "tool_calls")
        self.assertEqual(result.request_2.outcome, "final_answer")
        self.assertEqual(result.tool_result.status, ToolStatus.NO_MATCH)
        self.assertTrue(result.generated_text.strip())
        self.assertEqual(len(gateway.requests), 2)
        self.assertEqual(gateway.requests[1].tool_choice, "none")
        tool_messages = [message for message in gateway.requests[1].messages if message.role == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn('"status":"NO_MATCH"', tool_messages[0].content)

    def test_error_result_still_stops_before_request_2(self):
        error_definition = ToolDefinition(
            self.model_definition, lambda: {"status": "ERROR", "error_code": "TOOL_EXECUTION_ERROR"})
        gateway = RecordingGateway(tool_turn(), final())
        result = self.converse(error_definition, gateway)
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.error_code, "TOOL_EXECUTION_ERROR")
        self.assertEqual(result.request_2.outcome, "not_started")
        self.assertEqual(len(gateway.requests), 1)

    # -- 4. Assistant turn can still be COMPLETED --------------------------

    def test_assistant_turn_with_no_match_is_completed_and_public_safe(self):
        gateway = RecordingGateway(tool_turn(), final())
        result = self.assistant_turn(self.definition(), gateway)
        self.assertEqual(result.status, Status.COMPLETED)
        public = result.to_dict()
        self.assertTrue(public["successful_turn"])
        self.assertEqual(public["tool_activity"]["tool_status"], "NO_MATCH")
        self.assertTrue(public["tool_activity"]["used_tool"])
        self.assertNotIn("tool_result", public)
        # The raw NO_MATCH payload stays internal; only the projected status is public.
        self.assertNotIn("retrieval_mode", json.dumps(public))
        self.assertNotIn("retrieval_version", json.dumps(public))

    # -- 5. Trace records only safe metadata -------------------------------

    def test_trace_records_no_match_without_prompt_or_arguments(self):
        gateway = RecordingGateway(tool_turn(), final())
        self.converse(self.definition(), gateway)
        entry = self.trace_entries()[-1]
        self.assertEqual(entry["kind"], "read_only_tool_conversation")
        self.assertEqual(entry["tool_result_status"], "NO_MATCH")
        self.assertEqual(entry["status"], "completed")
        self.assertIsNone(entry["error_code"])
        self.assertEqual(entry["tool_name"], QUERY)
        self.assertNotIn("arguments", entry)
        raw = self.trace_path.read_text(encoding="utf-8")
        self.assertNotIn(QUESTION, raw)
        self.assertNotIn("evidence", raw)

    # -- 6. UI safe projection keeps NO_MATCH ------------------------------

    def test_ui_safe_projection_keeps_no_match(self):
        source = files("fishery_ai").joinpath("resources/web/app.js").read_text(encoding="utf-8")
        start = source.index("function safeAssistantActivity")
        block = source[start:source.index("]", source.index("tool_status", start))]
        for status in ("OK", "PARTIAL", "NOT_SCORABLE", "NO_DATA", "NO_MATCH", "ERROR"):
            with self.subTest(status=status):
                self.assertIn(f'"{status}"', block)


if __name__ == "__main__":
    unittest.main()
