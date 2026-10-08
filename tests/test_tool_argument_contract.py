"""Step 2 offline tests: the server-side tool argument contract.

Framework-level only: no model, no network, no real Knowledge or water data.
Legacy parameterless tools must behave exactly as before.
"""

from dataclasses import FrozenInstanceError
from functools import partial
import json
import unittest
from unittest.mock import Mock, patch

from fishery_ai.contracts import parse_time
from fishery_ai.domain import DiagnosisService
from fishery_ai.model_gateway import ModelToolCall
from fishery_ai.telemetry.current import CurrentWaterQualityReader
from fishery_ai.telemetry.snapshot import CurrentSnapshotStore
from fishery_ai.tools import ToolDefinition, ToolExecutor, ToolRegistry, ToolStatus


NOW = parse_time("2026-10-08T00:00:00Z")
NAME = "get_current_water_quality"


def call(arguments="{}", identifier="call_step2"):
    return ModelToolCall(identifier, NAME, arguments)


def corrupted_call(arguments, identifier="call_step2"):
    # ModelToolCall rejects non-object JSON at construction; test the Executor's
    # defensive path with a crafted inbound object, as test_read_only_tools does.
    value = object.__new__(ModelToolCall)
    for key, item in {"id": identifier, "function_name": NAME,
                      "arguments_json": arguments, "type": "function"}.items():
        object.__setattr__(value, key, item)
    return value


class ToolArgumentContractTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Step 2 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: NOW)
        self.registry = ToolRegistry(self.reader, DiagnosisService())
        self.model_definition = self.registry.lookup(NAME).model_definition

    def definition(self, handler, validate=None):
        if validate is None:
            return ToolDefinition(self.model_definition, handler)
        return ToolDefinition(self.model_definition, handler, validate)

    def execute_with(self, definition, arguments="{}", *, model_call=None, **kwargs):
        with patch.object(self.registry, "lookup", return_value=definition):
            return ToolExecutor(self.registry, **kwargs).execute(model_call or call(arguments))

    def assert_error(self, result, code):
        self.assertEqual(result.status, ToolStatus.ERROR)
        self.assertEqual(result.error_code.value, code)
        self.assertEqual(json.loads(result.to_json()), {"status": "ERROR", "error_code": code})

    # -- legacy parameterless contract is unchanged -------------------------

    def test_legacy_tool_still_rejects_any_argument(self):
        handler = Mock(return_value={"status": "OK"})
        self.assert_error(self.execute_with(self.definition(handler), '{"query":"x"}'),
                          "INVALID_TOOL_ARGUMENTS")
        handler.assert_not_called()

    def test_legacy_tool_is_invoked_without_arguments(self):
        seen = []

        def handler():
            seen.append(True)
            return {"status": "OK"}

        result = self.execute_with(self.definition(handler))
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(seen, [True])

    def test_registry_handlers_keep_their_partial_shape(self):
        handler = self.registry.lookup(NAME).handler
        self.assertIsInstance(handler, partial)
        self.assertEqual(handler.keywords["reader"], self.reader)

    def test_definition_stays_immutable(self):
        definition = self.definition(Mock(return_value={"status": "OK"}))
        with self.assertRaises(FrozenInstanceError):
            definition.validate_arguments = lambda _arguments: {}

    # -- declared parameter contract ---------------------------------------

    def test_declared_contract_receives_normalized_arguments(self):
        received = []

        def validate(arguments):
            return {"query": arguments["q"].strip()}

        def handler(arguments):
            received.append(arguments)
            return {"status": "OK", "query": arguments["query"]}

        result = self.execute_with(self.definition(handler, validate), '{"q":"  缺氧  "}')
        self.assertEqual(received, [{"query": "缺氧"}])
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(result.payload["query"], "缺氧")
        self.assertNotIn("q", result.payload)

    def test_declared_contract_may_accept_an_empty_object(self):
        result = self.execute_with(self.definition(lambda arguments: {"status": "OK"},
                                                   lambda arguments: {"arguments": dict(arguments)}))
        self.assertEqual(result.status, ToolStatus.OK)

    def test_validator_rejection_is_safe_and_handler_never_runs(self):
        def validate(_arguments):
            raise ValueError("undeclared field")

        handler = Mock(return_value={"status": "OK"})
        self.assert_error(self.execute_with(self.definition(handler, validate), '{"extra":1}'),
                          "INVALID_TOOL_ARGUMENTS")
        handler.assert_not_called()

    def test_validator_unexpected_error_is_redacted(self):
        def validate(_arguments):
            raise RuntimeError("fake-secret-step2 private-path")

        handler = Mock(return_value={"status": "OK"})
        # ValueError/TypeError mean "arguments rejected"; any other exception is a
        # framework failure. Both must stay redacted and never reach the handler.
        result = self.execute_with(self.definition(handler, validate))
        self.assert_error(result, "TOOL_EXECUTION_ERROR")
        handler.assert_not_called()
        public = result.to_json() + json.dumps(result.to_dict()) + repr(result)
        self.assertNotIn("fake-secret-step2", public)
        self.assertNotIn("private-path", public)

    def test_validator_must_return_an_object(self):
        handler = Mock(return_value={"status": "OK"})
        for value in (["query"], "query", None, 1):
            with self.subTest(returned=type(value).__name__):
                self.assert_error(self.execute_with(self.definition(handler, lambda _a, _v=value: _v)),
                                  "INVALID_TOOL_ARGUMENTS")
        handler.assert_not_called()

    # -- shared Executor boundaries still apply ----------------------------

    def test_argument_size_limit_applies_before_validation(self):
        validate = Mock(side_effect=AssertionError("validator must not run"))
        definition = self.definition(Mock(return_value={"status": "OK"}), validate)
        oversized = '{"q":"' + "测" * 1400 + '"}'
        self.assertGreater(len(oversized.encode("utf-8")), 4096)
        self.assert_error(self.execute_with(definition, oversized), "INVALID_TOOL_ARGUMENTS")
        validate.assert_not_called()

    def test_non_object_arguments_are_rejected_before_validation(self):
        validate = Mock(side_effect=AssertionError("validator must not run"))
        definition = self.definition(Mock(return_value={"status": "OK"}), validate)
        result = self.execute_with(definition, model_call=corrupted_call("[1,2]"))
        self.assert_error(result, "INVALID_TOOL_ARGUMENTS")
        validate.assert_not_called()

    def test_result_size_limit_still_applies_to_parameterized_tools(self):
        definition = self.definition(lambda _arguments: {"status": "OK", "value": "中" * 100},
                                     lambda _arguments: {})
        self.assert_error(self.execute_with(definition, max_result_bytes=256), "TOOL_RESULT_TOO_LARGE")

    def test_unsupported_status_from_parameterized_tool_is_safe_error(self):
        definition = self.definition(lambda _arguments: {"status": "NOT_A_STATUS"},
                                     lambda _arguments: {})
        self.assert_error(self.execute_with(definition), "TOOL_EXECUTION_ERROR")

    def test_rejected_arguments_still_consume_the_call_budget(self):
        executor = ToolExecutor(self.registry, max_calls=1)
        definition = self.definition(Mock(return_value={"status": "OK"}))
        with patch.object(self.registry, "lookup", return_value=definition):
            self.assert_error(executor.execute(call('{"query":"x"}')), "INVALID_TOOL_ARGUMENTS")
            self.assert_error(executor.execute(call(identifier="second")), "TOOL_CALL_LIMIT")


if __name__ == "__main__":
    unittest.main()
