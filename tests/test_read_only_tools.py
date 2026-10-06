"""T2 offline execution: canonical facts only, fake inputs, no model calls."""

import ast
from dataclasses import FrozenInstanceError
from datetime import timedelta
import io
import json
import logging
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch

from fishery_ai.contracts import Freshness, WaterQualityReading, parse_time
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelToolCall, ModelToolDefinition
from fishery_ai.telemetry.current import CurrentWaterQualityReader
from fishery_ai.telemetry.snapshot import CurrentSnapshotStore
from fishery_ai.tools import (ToolDefinition, ToolError, ToolErrorCode, ToolExecutionResult,
                             ToolExecutor, ToolRegistry, ToolStatus)


NOW = parse_time("2026-10-05T02:00:00Z")
NAME = "get_current_water_quality"


def call(arguments="{}", name=NAME, identifier="call_t2"):
    return ModelToolCall(identifier, name, arguments)


def corrupted_call(arguments):
    # T1 rejects these at construction. Defensively test a corrupted inbound
    # object without weakening that public protocol contract.
    value = object.__new__(ModelToolCall)
    for key, item in {"id": "call_t2", "function_name": NAME,
                      "arguments_json": arguments, "type": "function"}.items():
        object.__setattr__(value, key, item)
    return value


class ReadOnlyToolTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("T2 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        self.now = NOW
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: self.now)
        self.diagnosis = DiagnosisService()
        self.registry = ToolRegistry(self.reader, self.diagnosis)
        self.executor = ToolExecutor(self.registry)

    def reading(self, **changes):
        return WaterQualityReading.from_raw({"temp": 28, "ph": 7.5, "oxygen": 6, **changes},
            observed_at=NOW, retrieved_at=NOW, source="fake:sensor", stale_after_s=300)

    def result_for(self, reading):
        self.store.set_current(reading)
        return self.executor.execute(call())

    def assert_error(self, result, code):
        self.assertEqual(result.status, ToolStatus.ERROR)
        self.assertEqual(result.error_code.value, code)
        self.assertEqual(json.loads(result.to_json()), {"status": "ERROR", "error_code": code})

    def test_registry_is_single_static_definition(self):
        definitions = self.registry.model_definitions()
        self.assertEqual([item.name for item in definitions], [NAME, "score_current_water_quality"])
        self.assertIsInstance(definitions[0], ModelToolDefinition)
        self.assertEqual(definitions[0].parameters_dict(),
            {"type": "object", "properties": {}, "additionalProperties": False})
        with self.assertRaises(TypeError):
            self.registry._entries["shell"] = self.registry.lookup(NAME)
        self.assertFalse(hasattr(self.registry, "register"))

    def test_registry_unknown_rejected(self):
        with self.assertRaises(ToolError) as caught:
            self.registry.lookup("set_current")
        self.assertEqual(caught.exception.code, ToolErrorCode.UNKNOWN_TOOL)

    def test_executor_unknown_rejected_without_handler(self):
        with patch.object(self.reader, "query") as query:
            self.assert_error(self.executor.execute(call(name="shell")), "UNKNOWN_TOOL")
            query.assert_not_called()

    def test_empty_arguments_no_data(self):
        result = self.executor.execute(call())
        self.assertEqual(result.status, ToolStatus.NO_DATA)
        self.assertEqual(result.payload, {"status": "NO_DATA", "water_quality": None, "findings": []})
        self.assertEqual(result.tool_call_id, "call_t2")

    def test_whitespace_empty_object_allowed(self):
        self.assertEqual(self.executor.execute(call(" \n{ } ")).status, ToolStatus.NO_DATA)

    def test_non_object_arguments_rejected(self):
        for arguments in ("[]", "null", '"text"', "1", "true"):
            with self.subTest(arguments=arguments):
                self.assert_error(ToolExecutor(self.registry).execute(corrupted_call(arguments)),
                                  "INVALID_TOOL_ARGUMENTS")

    def test_malformed_arguments_rejected(self):
        for arguments in ("{", "{} trailing", "NaN", "[" * 1500):
            with self.subTest(length=len(arguments)):
                self.assert_error(ToolExecutor(self.registry).execute(corrupted_call(arguments)),
                                  "INVALID_TOOL_ARGUMENTS")

    def test_extra_arguments_rejected(self):
        with patch.object(self.reader, "query") as query:
            for arguments in ('{"path":"fake"}', '{"stale_after_s":0}', '{"value":null}'):
                self.assert_error(ToolExecutor(self.registry).execute(call(arguments)), "INVALID_TOOL_ARGUMENTS")
            query.assert_not_called()

    def test_argument_size_budget(self):
        self.assert_error(self.executor.execute(call('{"unused":"' + "a" * 4096 + '"}')),
                          "INVALID_TOOL_ARGUMENTS")

    def test_normal_values_metadata(self):
        result = self.result_for(self.reading())
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(result.payload["water_quality"], {
            "temperature_c": 28, "ph": 7.5, "dissolved_oxygen_mg_l": 6,
            "quality": "valid", "freshness": "fresh", "observed_at": NOW.isoformat(),
            "retrieved_at": NOW.isoformat(), "source": "fake:sensor"})
        self.assertEqual(result.payload["evaluated_at"], NOW.isoformat())
        self.assertEqual(result.payload["findings"], [])

    def test_low_oxygen(self):
        result = self.result_for(self.reading(oxygen=2.2))
        self.assertEqual([item["code"] for item in result.payload["findings"]], ["OXYGEN_CRITICAL_LOW"])

    def test_high_temperature_low_oxygen(self):
        result = self.result_for(self.reading(temp=34, oxygen=2.2))
        self.assertEqual([item["code"] for item in result.payload["findings"]],
                         ["TEMP_CRITICAL_HIGH", "OXYGEN_CRITICAL_LOW"])

    def test_partial_is_successful_read(self):
        result = self.result_for(self.reading(ph=None))
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertIsNone(result.payload["water_quality"]["ph"])
        self.assertEqual(result.payload["water_quality"]["quality"], "partial")
        self.assertEqual(result.payload["findings"][0]["code"], "SENSOR_PARTIAL")

    def test_invalid_is_successful_read(self):
        result = self.result_for(self.reading(ph="invalid"))
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(result.payload["water_quality"]["quality"], "invalid")
        self.assertEqual(result.payload["findings"][0]["code"], "SENSOR_INVALID")

    def test_all_missing_snapshot_is_not_no_data(self):
        result = self.result_for(self.reading(temp=None, ph=None, oxygen=None))
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(result.payload["water_quality"]["quality"], "invalid")

    def test_query_time_stale_preserves_store(self):
        original = self.reading()
        self.now += timedelta(hours=1)
        result = self.result_for(original)
        self.assertEqual(result.payload["water_quality"]["freshness"], "stale")
        self.assertEqual(result.payload["evaluated_at"], self.now.isoformat())
        self.assertEqual(result.payload["water_quality"]["retrieved_at"], NOW.isoformat())
        self.assertEqual(result.payload["findings"][0]["code"], "SENSOR_STALE")
        self.assertIs(self.store.get_current(), original)
        self.assertEqual(original.freshness, Freshness.FRESH)

    def test_partial_and_stale_are_independent(self):
        self.now += timedelta(seconds=301)
        result = self.result_for(self.reading(ph=None))
        self.assertEqual(result.payload["water_quality"]["quality"], "partial")
        self.assertEqual([item["code"] for item in result.payload["findings"]],
                         ["SENSOR_PARTIAL", "SENSOR_STALE"])

    def test_freshness_threshold_boundary(self):
        self.now += timedelta(seconds=300)
        result = self.result_for(self.reading())
        self.assertEqual(result.payload["water_quality"]["freshness"], "fresh")

    def test_findings_and_rule_version_from_diagnosis(self):
        original = self.reading(temp=34, oxygen=2.2)
        expected = self.diagnosis.diagnose(original)
        result = self.result_for(original)
        self.assertEqual(result.payload["rule_version"], self.diagnosis.RULE_VERSION)
        self.assertEqual(result.payload["findings"], [
            {"code": item.code, "severity": item.severity, "message": item.message,
             "facts_used": list(item.facts_used), "rule_version": item.rule_version} for item in expected])

    def test_reader_once_and_diagnosis_uses_query_view(self):
        original = self.reading()
        self.store.set_current(original)
        self.now += timedelta(hours=1)
        with patch.object(self.reader, "query", wraps=self.reader.query) as query, \
             patch.object(self.diagnosis, "diagnose", wraps=self.diagnosis.diagnose) as diagnose:
            self.executor.execute(call())
        query.assert_called_once_with()
        view_reading = diagnose.call_args.args[0]
        self.assertEqual(view_reading.freshness, Freshness.STALE)
        self.assertIsNot(view_reading, original)
        self.assertIs(self.store.get_current(), original)

    def test_result_json_round_trip_and_detached_payload(self):
        result = self.result_for(self.reading())
        result.payload["water_quality"]["ph"] = 0
        self.assertEqual(result.payload["water_quality"]["ph"], 7.5)
        self.assertEqual(json.loads(json.dumps(result.to_dict()))["result"], result.payload)
        message = ModelMessage("tool", result.to_json(), tool_call_id=result.tool_call_id)
        self.assertEqual(message.tool_call_id, "call_t2")
        with self.assertRaises(FrozenInstanceError):
            result.status = ToolStatus.ERROR

    def test_handler_exception_is_redacted_and_not_logged(self):
        fake = "fake-secret-for-t2-test"
        stream = io.StringIO()
        log_handler = logging.StreamHandler(stream)
        logging.getLogger().addHandler(log_handler)
        self.addCleanup(logging.getLogger().removeHandler, log_handler)
        definition = ToolDefinition(self.registry.lookup(NAME).model_definition,
                                    Mock(side_effect=RuntimeError(fake + " private-path")))
        with patch.object(self.registry, "lookup", return_value=definition):
            result = self.executor.execute(call())
        self.assert_error(result, "TOOL_EXECUTION_ERROR")
        public = result.to_json() + json.dumps(result.to_dict()) + repr(result) + stream.getvalue()
        self.assertNotIn(fake, public)
        self.assertNotIn("private-path", public)
        self.assertNotIn("Traceback", public)

    def test_unserializable_result_is_safe_error(self):
        for payload in ({"status": "OK", "value": object()}, {"status": "OK", "value": float("nan")},
                        {"status": "INVALID"}, None):
            with self.subTest(payload_type=type(payload).__name__):
                definition = ToolDefinition(self.registry.lookup(NAME).model_definition, Mock(return_value=payload))
                with patch.object(self.registry, "lookup", return_value=definition):
                    self.assert_error(ToolExecutor(self.registry).execute(call()), "TOOL_EXECUTION_ERROR")

    def test_result_size_limit(self):
        definition = ToolDefinition(self.registry.lookup(NAME).model_definition,
                                    Mock(return_value={"status": "OK", "value": "中" * 100}))
        with patch.object(self.registry, "lookup", return_value=definition):
            result = ToolExecutor(self.registry, max_result_bytes=256).execute(call())
        self.assert_error(result, "TOOL_RESULT_TOO_LARGE")
        self.assertLessEqual(len(result.to_json().encode("utf-8")), 256)

    def test_duplicate_call_never_executes_twice(self):
        with patch.object(self.reader, "query", wraps=self.reader.query) as query:
            self.executor.execute(call())
            self.assert_error(self.executor.execute(call()), "TOOL_CALL_ALREADY_EXECUTED")
        self.assertEqual(query.call_count, 1)

    def test_default_one_call_budget(self):
        with patch.object(self.reader, "query", wraps=self.reader.query) as query:
            self.executor.execute(call())
            self.assert_error(self.executor.execute(call(identifier="second")), "TOOL_CALL_LIMIT")
        self.assertEqual(query.call_count, 1)

    def test_explicit_finite_budget_not_an_autonomous_loop(self):
        executor = ToolExecutor(self.registry, max_calls=2)
        self.assertEqual(executor.execute(call()).status, ToolStatus.NO_DATA)
        self.assertEqual(executor.execute(call(identifier="second")).status, ToolStatus.NO_DATA)
        self.assert_error(executor.execute(call(identifier="third")), "TOOL_CALL_LIMIT")

    def test_invalid_attempt_consumes_budget(self):
        self.assert_error(self.executor.execute(call('{"unused":1}')), "INVALID_TOOL_ARGUMENTS")
        self.assert_error(self.executor.execute(call(identifier="second")), "TOOL_CALL_LIMIT")

    def test_budget_configuration_validated(self):
        for value in (0, 9, True, 1.5):
            with self.assertRaises(ValueError):
                ToolExecutor(self.registry, max_calls=value)
        for value in (0, 255, True, 262145):
            with self.assertRaises(ValueError):
                ToolExecutor(self.registry, max_result_bytes=value)

    def test_cancel_before_execution(self):
        handle = RequestHandle()
        with request_scope(handle), patch.object(self.reader, "query") as query:
            handle.cancel()
            with self.assertRaises(GatewayError) as caught:
                self.executor.execute(call())
        self.assertEqual(caught.exception.code, "USER_CANCELLED")
        query.assert_not_called()

    def test_cancel_during_handler_does_not_return_partial_result(self):
        handle = RequestHandle()
        def handler():
            handle.cancel()
            return {"status": "OK"}
        definition = ToolDefinition(self.registry.lookup(NAME).model_definition, handler)
        with request_scope(handle), patch.object(self.registry, "lookup", return_value=definition):
            with self.assertRaises(GatewayError) as caught:
                self.executor.execute(call())
        self.assertEqual(caught.exception.code, "USER_CANCELLED")

    def test_cancelled_handler_exception_does_not_become_tool_error(self):
        handle = RequestHandle()
        def handler():
            handle.cancel()
            raise RuntimeError("fake internal error")
        definition = ToolDefinition(self.registry.lookup(NAME).model_definition, handler)
        with request_scope(handle), patch.object(self.registry, "lookup", return_value=definition):
            with self.assertRaises(GatewayError) as caught:
                self.executor.execute(call())
        self.assertEqual(caught.exception.code, "USER_CANCELLED")

    def test_cancel_during_serialization_is_checked_before_return(self):
        handle = RequestHandle()
        make_result = ToolExecutionResult.from_payload
        def serialize(*args):
            result = make_result(*args)
            handle.cancel()
            return result
        with request_scope(handle), patch.object(ToolExecutionResult, "from_payload", side_effect=serialize):
            with self.assertRaises(GatewayError) as caught:
                self.executor.execute(call())
        self.assertEqual(caught.exception.code, "USER_CANCELLED")

    def test_no_io_mutation_discovery_or_other_execution_dependencies(self):
        root = Path(__file__).resolve().parents[1] / "src/fishery_ai/tools"
        forbidden_modules = {"os", "pathlib", "subprocess", "socket", "httpx", "openai", "importlib",
                             "credentials", "repositories", "web", "application", "scenario_templates"}
        forbidden_calls = {"eval", "exec", "compile", "__import__", "open", "set_current", "apply"}
        for path in root.rglob("*.py"):
            # Policy persists fixed-path permissions; handlers/execution never do I/O.
            if path.name == "policy.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    modules = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    self.assertFalse(any(set(module.split(".")) & forbidden_modules for module in modules), path.name)
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    self.assertNotIn(name, forbidden_calls, path.name)

    def test_network_guard_active(self):
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("offline.invalid", 443)
        with self.assertRaises(AssertionError):
            socket.create_connection(("127.0.0.1", 11434))


if __name__ == "__main__":
    unittest.main()
