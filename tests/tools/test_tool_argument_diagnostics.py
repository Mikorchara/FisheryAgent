"""Finite rejection metadata only: no raw parameters, network or relaxed contracts."""

import json
import unittest
from unittest.mock import Mock, patch

from fishery_ai.model_gateway import GatewayError, ModelToolCall
from fishery_ai.tool_argument_diagnostics import (ArgumentStage, ArgumentRejection,
    ToolArgumentDiagnostic, ToolArgumentError, public_argument_diagnostic, rejection)
from fishery_ai.tools import ToolDefinition, ToolExecutor
import tests.tools.test_tool_argument_contract as contract_fixture
from tests.tools.test_tool_argument_contract import call, corrupted_call
from tests.assistant.test_assistant import AssistantFixture, RecordingGateway, final
from tests.assistant.test_assistant import call as response_call


class DiagnosticContractTests(unittest.TestCase):
    def test_allowlist_rejects_untyped_metadata_and_invalid_counts(self):
        self.assertIsNone(public_argument_diagnostic({'reason': 'fictional-private'}))
        for values in [('executor', ArgumentRejection.NOT_OBJECT, None, None),
                       (ArgumentStage.EXECUTOR, 'fictional-private', None, None),
                       (ArgumentStage.EXECUTOR, ArgumentRejection.NOT_OBJECT, True, None),
                       (ArgumentStage.EXECUTOR, ArgumentRejection.NOT_OBJECT, 65537, None),
                       (ArgumentStage.EXECUTOR, ArgumentRejection.NOT_OBJECT, None, 1025)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                ToolArgumentDiagnostic(*values)
        self.assertIsNone(GatewayError('INVALID_TOOL_CALL', argument_diagnostic={'raw': 'private'}).argument_diagnostic)

    def test_metadata_is_bounded_even_for_large_unicode_and_members(self):
        value = rejection(ArgumentStage.EXECUTOR, ArgumentRejection.ARGUMENTS_TOO_LARGE,
                          '测' * 100000, dict.fromkeys(range(2000)))
        self.assertEqual((value.argument_bytes, value.object_member_count), (65536, 1024))
        self.assertIsNone(value.with_context('\ud800').argument_bytes)

    def test_model_contract_keeps_value_error_compatibility_and_safe_reason(self):
        for text, reason in [('{', 'MALFORMED_JSON'), ('[1]', 'NOT_OBJECT'), ('null', 'NOT_OBJECT')]:
            with self.subTest(reason=reason), self.assertRaises(ValueError) as caught:
                ModelToolCall('call', 'get_current_water_quality', text)
            self.assertIsInstance(caught.exception, ToolArgumentError)
            self.assertEqual(str(caught.exception), reason)
            self.assertEqual(public_argument_diagnostic(caught.exception.argument_diagnostic)['stage'], 'model_contract')
        self.assertEqual(call().arguments_json, '{}')


class ExecutorDiagnosticTests(unittest.TestCase):
    # Reuse setup helpers without inheriting and collecting the old test methods.
    setUp = contract_fixture.ToolArgumentContractTests.setUp
    definition = contract_fixture.ToolArgumentContractTests.definition
    execute_with = contract_fixture.ToolArgumentContractTests.execute_with

    def test_empty_object_success_has_no_diagnostic(self):
        handler = Mock(return_value={'status': 'OK'})
        result = self.execute_with(self.definition(handler))
        self.assertIsNone(result.argument_diagnostic)
        handler.assert_called_once_with()

    def test_rejection_matrix_never_invokes_handler_and_payload_is_unchanged(self):
        for text, reason, stage in [
            ('{"device_id":"fictional-private"}', 'UNEXPECTED_ARGUMENTS', 'definition'),
            ('{"query":"fictional-private"}', 'UNEXPECTED_ARGUMENTS', 'definition'),
            ('{', 'MALFORMED_JSON', 'executor'), ('[]', 'NOT_OBJECT', 'executor'),
            ('{}' + ' ' * 4095, 'ARGUMENTS_TOO_LARGE', 'executor'),
            ('{"x":"\ud800"}', 'INVALID_ENCODING', 'executor')]:
            with self.subTest(reason=reason):
                handler = Mock(return_value={'status': 'OK'})
                result = self.execute_with(self.definition(handler), model_call=corrupted_call(text))
                self.assertEqual(result.to_json(), '{"status":"ERROR","error_code":"INVALID_TOOL_ARGUMENTS"}')
                diagnostic = public_argument_diagnostic(result.argument_diagnostic)
                self.assertEqual((diagnostic['reason'], diagnostic['stage']), (reason, stage))
                if stage == 'definition': self.assertEqual(diagnostic['object_member_count'], 1)
                handler.assert_not_called()
                public = json.dumps(diagnostic) + repr(result) + result.to_json()
                self.assertNotIn('fictional-private', public)
                self.assertNotIn('device_id', public)

    def test_parser_recursion_rejection_is_bounded(self):
        handler = Mock()
        executor, model_call = ToolExecutor(self.registry), call()
        with patch('fishery_ai.tools.executor.json.loads', side_effect=RecursionError), \
             patch('fishery_ai.tools.executor.ToolExecutionResult.from_payload') as report:
            with patch.object(self.registry, 'lookup', return_value=self.definition(handler)):
                executor.execute(model_call)
        diagnostic = report.call_args.kwargs['argument_diagnostic']
        self.assertEqual(diagnostic.reason, ArgumentRejection.ARGUMENTS_TOO_COMPLEX)
        handler.assert_not_called()

    def test_validator_rejection_return_type_and_exception_are_distinct_from_handler_failure(self):
        def reject(_): raise ValueError('fictional-private-validator-detail')
        def unexpected(_): raise RuntimeError('fictional-private-internal')
        for validator, code, reason in [(reject, 'INVALID_TOOL_ARGUMENTS', 'VALIDATOR_REJECTED'),
            (lambda _: [], 'INVALID_TOOL_ARGUMENTS', 'VALIDATOR_REJECTED'),
            (unexpected, 'TOOL_EXECUTION_ERROR', None)]:
            handler = Mock(return_value={'status': 'OK'})
            result = self.execute_with(self.definition(handler, validator))
            self.assertEqual(result.error_code.value, code)
            diagnostic = public_argument_diagnostic(result.argument_diagnostic)
            self.assertEqual(diagnostic['reason'] if diagnostic else None, reason)
            handler.assert_not_called()
            self.assertNotIn('fictional-private', json.dumps(diagnostic) + str(result))

    def test_cancellation_is_not_relabelled_as_parameter_rejection(self):
        def cancelled(_): raise GatewayError('USER_CANCELLED')
        handler = Mock()
        with self.assertRaises(GatewayError) as caught:
            self.execute_with(self.definition(handler, cancelled))
        self.assertEqual(caught.exception.code, 'USER_CANCELLED')
        handler.assert_not_called()


class AssistantDiagnosticTests(AssistantFixture):
    def test_rejection_activity_trace_no_followup_no_sources_no_success_history(self):
        gateway = RecordingGateway(response_call(arguments='{"device_id":"fictional-private-value"}'), final())
        with patch.object(self.reader, 'query') as handler:
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(len(gateway.requests), 1)
        handler.assert_not_called()
        self.assertFalse(result.to_dict()['successful_turn'])
        self.assertEqual(result.final_text, '')
        self.assertIsNone(result.completed_at)
        receipt = result.source_receipt
        self.assertFalse(receipt.sources)
        self.assertFalse(receipt.observation_query_completed)
        self.assertFalse(receipt.score_evaluation_completed)
        self.assertFalse(receipt.project_search_completed)
        activity = result.to_dict()['activity']
        self.assertEqual(activity['counts']['tools_executed'], 0)
        self.assertEqual(activity['steps'][-1]['argument_diagnostic']['reason'], 'UNEXPECTED_ARGUMENTS')
        public = self.trace.read_text(encoding='utf-8') + json.dumps(activity)
        self.assertNotIn('fictional-private-value', public)
        self.assertNotIn('device_id', public)
        traces = [json.loads(line) for line in self.trace.read_text(encoding='utf-8').splitlines()]
        execution = next(t for t in traces if t['kind'] == 'read_only_tool_conversation')
        self.assertEqual(execution['steps'][-1]['argument_diagnostic']['object_member_count'], 1)

    def test_model_argument_failure_is_safe_model_step_not_fake_tool_execution(self):
        error = GatewayError('INVALID_TOOL_CALL', argument_diagnostic=rejection(
            ArgumentStage.MODEL_CONTRACT, ArgumentRejection.MALFORMED_JSON, '{'))
        def fail(*_): raise error
        gateway = RecordingGateway(callback=fail)
        with patch.object(self.reader, 'query') as handler:
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(len(gateway.requests), 1)
        handler.assert_not_called()
        self.assertEqual(result.error_code, 'MODEL_TOOL_CALL_MALFORMED')
        self.assertFalse(result.to_dict()['successful_turn'])
        self.assertEqual(result.source_ledger.entries, ())
        step = result.to_dict()['activity']['steps'][0]
        self.assertEqual(step['argument_diagnostic']['reason'], 'MALFORMED_JSON')
        self.assertEqual(step['argument_diagnostic']['stage'], 'model_contract')
        traces = [json.loads(line) for line in self.trace.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(traces[0]['model_request_1']['argument_diagnostic'], step['argument_diagnostic'])
