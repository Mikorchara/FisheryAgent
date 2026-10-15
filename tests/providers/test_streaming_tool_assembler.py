"""Phase 5A protocol foundation: fake SDK only; no Tool execution or product opt-in."""

import asyncio
from dataclasses import replace
import json
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import httpx
from openai import APIConnectionError, AsyncOpenAI

from fishery_ai.contracts import Mode
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelRequest, ModelToolDefinition
from fishery_ai.model_options import Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter, _ToolCallStreamAssembler
import tests.security.test_execution as execution_tests


NAME = "search_fishery_knowledge"
OTHER = "get_current_water_quality"


def definition(name=NAME):
    return ModelToolDefinition(name, "Offline schema fixture", {"type": "object"})


def delta(arguments=None, *, name=None, identifier=None, call_type=None, index=0):
    return NS(index=index, id=identifier, type=call_type, function=NS(name=name, arguments=arguments))


def chunk(calls=None, *, content=None, reasoning=None, finish=None, usage=None, index=0, model="fixture-model"):
    return NS(id="fixture-response", model=model, usage=usage,
        choices=[NS(index=index, delta=NS(role="assistant", content=content,
            reasoning_content=reasoning, tool_calls=calls), finish_reason=finish)])


def first(arguments="{", name=NAME):
    return chunk([delta(arguments, name=name, identifier="fixture-call", call_type="function")])


def good_chunks():
    return [first(), chunk([delta('"query":"鳗鲡低氧表现"}')]), chunk(finish="tool_calls")]


class AssemblerTests(unittest.TestCase):
    def test_parameter_diagnostics_keep_existing_stream_rejection_codes(self):
        cases = [('{', 'INVALID_TOOL_ARGUMENTS', 'MALFORMED_JSON'),
            ('[]', 'INVALID_TOOL_ARGUMENTS', 'NOT_OBJECT'),
            ('{"x":1,"x":2}', 'INVALID_TOOL_ARGUMENTS', 'INVALID_JSON_VALUE'),
            ('{"x":NaN}', 'INVALID_TOOL_ARGUMENTS', 'INVALID_JSON_VALUE'),
            ('{"x":"\\ud800"}', 'INVALID_TOOL_ARGUMENTS', 'INVALID_ENCODING'),
            ('{"x":' + '[' * 20 + '0' + ']' * 20 + '}', 'INVALID_TOOL_ARGUMENTS', 'ARGUMENTS_TOO_COMPLEX'),
            (' ' * 4097, 'STREAM_BUFFER_LIMIT', 'ARGUMENTS_TOO_LARGE'),
            ('\ud800', 'INVALID_STREAM_EVENT', 'INVALID_ENCODING')]
        for text, code, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(GatewayError) as caught:
                self.assemble([first(text), chunk(finish='tool_calls')])
            self.assertEqual(caught.exception.code, code)
            diagnostic = caught.exception.argument_diagnostic
            self.assertEqual(diagnostic.reason.value, reason)
            self.assertEqual(diagnostic.stage.value, 'stream_assembler')
            if reason == 'ARGUMENTS_TOO_LARGE': self.assertEqual(diagnostic.argument_bytes, 4097)

    def assembler(self):
        return _ToolCallStreamAssembler((definition(), definition(OTHER)))

    def assemble(self, chunks):
        assembler = self.assembler()
        for item in chunks:
            assembler.push(item)
        return assembler.finish()

    def assert_code(self, code, chunks):
        with self.assertRaises(GatewayError) as error:
            self.assemble(chunks)
        self.assertEqual(error.exception.code, code)

    def test_fragmented_names_unicode_and_escaped_arguments_are_preserved(self):
        arguments = json.dumps({"query": '鳗鲡 "低氧"\n路径\\水质 🐟'}, ensure_ascii=False)
        pieces = [arguments[:9], arguments[9:13], arguments[13:19], arguments[19:]]
        response = self.assemble([first(None, name="search_fishery_"), chunk([delta(name="knowledge")]),
            *(chunk([delta(piece)]) for piece in pieces), chunk(finish="tool_calls")])
        self.assertIsNone(response.text)
        call = response.tool_calls[0]
        self.assertEqual((call.id, call.function_name), ("fixture-call", NAME))
        self.assertEqual(call.arguments_json, arguments)
        self.assertEqual(json.loads(call.arguments_json)["query"], '鳗鲡 "低氧"\n路径\\水质 🐟')
        self.assertNotIn(arguments, repr(call))

    def test_first_complete_call_is_still_not_published_until_finish(self):
        assembler = self.assembler()
        self.assertIsNone(assembler.push(first('{}')))
        self.assertIsNone(assembler.push(chunk(finish="tool_calls")))
        response = assembler.finish()
        self.assertEqual(response.tool_calls[0].arguments_json, '{}')
        with self.assertRaises(GatewayError) as error:
            assembler.finish()
        self.assertEqual(error.exception.code, "INVALID_STREAM_STATE")

    def test_empty_metadata_and_repeated_stable_metadata_do_not_duplicate_identity(self):
        response = self.assemble([first(), chunk([delta('}', name=NAME, identifier="fixture-call", call_type="function")]),
            chunk([delta(None, identifier="", call_type="")]), chunk(finish="tool_calls")])
        self.assertEqual(response.tool_calls[0].id, "fixture-call")
        self.assertEqual(response.tool_calls[0].function_name, NAME)

    def test_plain_final_and_separate_reasoning_become_one_response(self):
        response = self.assemble([chunk(reasoning="reason"), chunk(content="答"), chunk(content="案", finish="stop")])
        self.assertEqual(response.text, "答案")
        self.assertEqual(response.reasoning_content, "reason")
        self.assertTrue(response.reasoning_present)
        self.assertEqual(response.tool_calls, ())

    def test_mixed_text_and_call_are_separate_fields(self):
        response = self.assemble([chunk(content="temporary"), *good_chunks()])
        self.assertEqual(response.text, "temporary")
        self.assertEqual(len(response.tool_calls), 1)

    def test_stop_terminal_with_complete_tool_call_is_accepted(self):
        response = self.assemble([first('{}'), chunk(finish="stop")])
        self.assertEqual(response.tool_calls[0].function_name, NAME)

    def test_usage_only_and_finish_chunk_usage_are_supported_without_double_counting(self):
        usage = NS(prompt_tokens=7, completion_tokens=4, total_tokens=11,
            completion_tokens_details=NS(reasoning_tokens=1), prompt_tokens_details=NS(cached_tokens=2))
        for final_usage in (NS(choices=[], usage=usage), chunk(finish="tool_calls", usage=usage)):
            response = self.assemble([first('{}'), chunk(usage=usage), chunk(finish="tool_calls"), final_usage])
            self.assertEqual(response.usage.total_tokens, 11)
            self.assertEqual(response.usage.cached_input_tokens, 2)
            self.assertEqual(response.usage.reasoning_tokens, 1)

    def test_missing_usage_is_explicitly_unavailable(self):
        self.assertEqual(self.assemble(good_chunks()).usage.source.value, "unavailable")

    def test_cumulative_usage_is_latest_not_a_sum_and_cannot_decrease(self):
        before = NS(prompt_tokens=7, completion_tokens=1, total_tokens=8)
        after = NS(prompt_tokens=7, completion_tokens=4, total_tokens=11)
        result = self.assemble([first('{}'), chunk(usage=before), chunk(finish="tool_calls", usage=after)])
        self.assertEqual(result.usage.total_tokens, 11)
        self.assert_code("INVALID_STREAM_EVENT", [first('{}'), chunk(usage=after), chunk(usage=before)])

    def test_missing_finish_is_interrupted_even_with_valid_complete_arguments(self):
        self.assert_code("STREAM_INTERRUPTED", [first('{}')])
        self.assert_code("STREAM_INTERRUPTED", [])

    def test_length_and_filter_are_not_executable(self):
        self.assert_code("STREAM_TRUNCATED", [first('{}'), chunk(finish="length")])
        self.assert_code("INVALID_STREAM_EVENT", [first('{}'), chunk(finish="content_filter")])

    def test_data_or_conflicting_finish_after_terminal_is_rejected(self):
        for after in (chunk(content="late"), chunk([delta(' ')]), chunk(finish="stop")):
            self.assert_code("INVALID_STREAM_EVENT", [*good_chunks(), after])

    def test_conflicting_call_id_name_or_type_is_rejected(self):
        for item in (delta('}', identifier="different-call"), delta('}', name=OTHER), delta('}', call_type="custom")):
            self.assert_code("INVALID_TOOL_CALL", [first(), chunk([item])])

    def test_multiple_calls_are_rejected_as_a_whole(self):
        self.assert_code("TOOL_CALL_LIMIT", [chunk([delta('{}', name=NAME, identifier="one", call_type="function"),
            delta('{}', name=OTHER, identifier="two", call_type="function", index=1)])])
        self.assert_code("TOOL_CALL_LIMIT", [first(), chunk([delta('{}', index=1)])])

    def test_invalid_choice_and_call_indices_are_rejected(self):
        for index in (True, -1, "0"):
            self.assert_code("INVALID_TOOL_CALL", [chunk([delta('{}', index=index)])])
        self.assert_code("INVALID_STREAM_EVENT", [chunk(index=1)])
        self.assert_code("INVALID_STREAM_EVENT", [NS(choices=[chunk().choices[0], chunk().choices[0]], usage=None)])

    def test_missing_call_identity_type_name_arguments_or_unknown_name_is_rejected(self):
        for item in (delta('{}', name=NAME, call_type="function"),
                     delta('{}', name=NAME, identifier="one"),
                     delta('{}', identifier="one", call_type="function"),
                     delta(name=NAME, identifier="one", call_type="function"),
                     delta('{}', name="shell", identifier="one", call_type="function")):
            self.assert_code("INVALID_TOOL_CALL", [chunk([item]), chunk(finish="tool_calls")])

    def test_malformed_argument_json_nonobject_duplicates_and_nonfinite_are_rejected(self):
        for text in ('{"query":', '[]', 'null', '{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '{"x":"\\ud800"}'):
            self.assert_code("INVALID_TOOL_ARGUMENTS", [first(text), chunk(finish="tool_calls")])

    def test_wrong_delta_types_role_and_legacy_function_call_are_rejected(self):
        for item in (chunk(content=1), chunk(reasoning={}), chunk(calls={}), chunk([delta(arguments={})])):
            with self.assertRaises(GatewayError): self.assemble([item])
        value = chunk(); value.choices[0].delta.role = "system"
        self.assert_code("INVALID_STREAM_EVENT", [value])
        value = chunk(); value.choices[0].delta.function_call = NS(name=NAME, arguments='{}')
        self.assert_code("INVALID_TOOL_CALL", [value])

    def test_model_response_identity_and_usage_conflicts_fail_closed(self):
        self.assert_code("INVALID_STREAM_EVENT", [first(), chunk(model="another-model")])
        self.assert_code("INVALID_STREAM_EVENT", [chunk(usage=NS(prompt_tokens=-1))])
        self.assert_code("INVALID_STREAM_EVENT", [chunk(usage=NS(prompt_tokens="7"))])

    def test_chunk_buffer_argument_depth_and_node_limits(self):
        with patch.object(_ToolCallStreamAssembler, "MAX_CHUNKS", 1):
            self.assert_code("STREAM_CHUNK_LIMIT", [first(), chunk()])
        with patch.object(_ToolCallStreamAssembler, "MAX_BUFFER_BYTES", 32):
            self.assert_code("STREAM_BUFFER_LIMIT", [chunk(content="🐟" * 9)])
        self.assert_code("STREAM_BUFFER_LIMIT", [first('x' * 4097)])
        text = '{"x":' + '[' * 17 + '0' + ']' * 17 + '}'
        self.assert_code("INVALID_TOOL_ARGUMENTS", [first(text), chunk(finish="tool_calls")])
        with patch.object(_ToolCallStreamAssembler, "MAX_JSON_NODES", 2):
            self.assert_code("INVALID_TOOL_ARGUMENTS", [first('{"x":1}'), chunk(finish="tool_calls")])

    def test_failed_assembler_cannot_later_publish_and_repr_is_safe(self):
        assembler = self.assembler()
        with self.assertRaises(GatewayError) as error: assembler.push(first("fictional-private" * 500))
        self.assertNotIn("fictional-private", str(error.exception))
        self.assertNotIn("fictional-private", repr(assembler))
        with self.assertRaises(GatewayError) as failed: assembler.finish()
        self.assertEqual(failed.exception.code, "INVALID_STREAM_STATE")

    def test_no_calls_with_tool_finish_or_empty_final_is_invalid(self):
        self.assert_code("INVALID_TOOL_CALL", [chunk(finish="tool_calls")])
        self.assert_code("INVALID_RESPONSE", [chunk(finish="stop")])


class AssemblerTransportTests(unittest.TestCase):
    def test_parameter_diagnostic_survives_stream_cleanup(self):
        adapter, bodies, closed, stream_closed, _ = self.transport([first('{'), chunk(finish='tool_calls')])
        with self.assertRaises(GatewayError) as caught:
            adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(caught.exception.code, 'INVALID_TOOL_ARGUMENTS')
        self.assertEqual(caught.exception.argument_diagnostic.reason.value, 'MALFORMED_JSON')
        self.assertTrue(closed.is_set() and stream_closed.is_set())
        self.assertEqual(len(bodies), 1)

    def setUp(self):
        # Network guard permits only asyncio's internal Windows wakeup socketpair.
        execution_tests.ExecutionTests.setUp(self)
        self.runtime = replace(self.runtime, capabilities=replace(self.runtime.capabilities, tool_calling=Support.SUPPORTED))
        self.request = ModelRequest(Mode.CHAT, (ModelMessage("user", "Offline fixture"),), tools=(definition(),))
        guard = patch("fishery_ai.tools.executor.ToolExecutor.execute", side_effect=AssertionError("assembler never executes tools"))
        guard.start(); self.addCleanup(guard.stop)

    def transport(self, chunks=None, *, failure=None, close_error=None, client_close_error=None,
                  create_error=None, during_close=None, blocked=False):
        closed, stream_closed, started = (threading.Event() for _ in range(3))
        bodies = []
        class Stream:
            def __aiter__(self): return self.events()
            async def events(self):
                started.set()
                for item in chunks or []:
                    yield item
                if blocked: await asyncio.Event().wait()
                if failure: raise failure
            async def close(self):
                stream_closed.set()
                if during_close: during_close()
                if close_error: raise close_error
        class Client:
            def __init__(self): self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                bodies.append(kwargs)
                if create_error: raise create_error
                return Stream()
            async def close(self):
                closed.set()
                if client_close_error: raise client_close_error
        adapter = OpenAICompatibleAdapter(async_client_factory=lambda *_: Client())
        return adapter, bodies, closed, stream_closed, started

    def test_internal_stream_returns_only_after_stream_and_client_close(self):
        adapter, bodies, closed, stream_closed, _ = self.transport(good_chunks())
        response = adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(response.tool_calls[0].function_name, NAME)
        self.assertTrue(closed.is_set() and stream_closed.is_set())
        self.assertEqual(adapter.request_attempts, 1)
        self.assertTrue(bodies[0]["stream"])
        self.assertEqual(bodies[0]["tools"][0]["function"]["name"], NAME)

    def test_fake_sdk_sse_decoding_preserves_unicode_and_last_usage(self):
        clients = []
        events = []
        for index, item in enumerate(good_chunks()):
            choice = item.choices[0]
            calls = choice.delta.tool_calls
            encoded_calls = None if calls is None else [{"index": c.index, "id": c.id, "type": c.type,
                "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]
            events.append({"id":"fixture-response", "object":"chat.completion.chunk", "created":0,
                "model":"fixture-model", "choices":[{"index":0,"delta":{"tool_calls":encoded_calls},
                    "finish_reason":choice.finish_reason}], "usage":None})
        events[-1]["usage"] = {"prompt_tokens":7, "completion_tokens":4, "total_tokens":11}
        body = ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\n\n' for e in events) + 'data: [DONE]\n\n'
        async def respond(request):
            self.assertTrue(json.loads(request.content)["stream"])
            return httpx.Response(200, headers={"content-type":"text/event-stream"}, content=body.encode())
        def client(*_):
            sdk = AsyncOpenAI(api_key="fictional-sdk-key", base_url="http://mock.invalid/v1", max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
            clients.append(sdk); return sdk
        response = OpenAICompatibleAdapter(async_client_factory=client)._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(json.loads(response.tool_calls[0].arguments_json)["query"], "鳗鲡低氧表现")
        self.assertEqual(response.usage.total_tokens, 11)
        self.assertTrue(clients[0].is_closed())

    def test_disconnect_after_tool_delta_never_retries_or_returns_partial_call(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid/v1"))
        adapter, bodies, closed, stream_closed, _ = self.transport([first('{}')], failure=error)
        with self.assertRaises(GatewayError) as failure: adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(failure.exception.code, "CONNECTION_ERROR")
        self.assertEqual(len(bodies), 1)  # Runtime max_retries=1 cannot relax this path.
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_failure_after_terminal_is_still_failure(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid/v1"))
        adapter, _, closed, stream_closed, _ = self.transport(good_chunks(), failure=error)
        with self.assertRaises(GatewayError): adapter._complete_tool_stream(self.request, self.runtime)
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_malformed_and_incomplete_streams_close_both_resources(self):
        for chunks, code in (([first('{}')], "STREAM_INTERRUPTED"), ([first('[]'), chunk(finish="tool_calls")], "INVALID_TOOL_ARGUMENTS"),
                             ([first('{}'), chunk(finish="length")], "STREAM_TRUNCATED")):
            adapter, _, closed, stream_closed, _ = self.transport(chunks)
            with self.assertRaises(GatewayError) as error: adapter._complete_tool_stream(self.request, self.runtime)
            self.assertEqual(error.exception.code, code)
            self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_cleanup_error_discards_complete_tool_call_without_retry(self):
        adapter, bodies, closed, stream_closed, _ = self.transport(good_chunks(), close_error=RuntimeError("fictional-private-error"))
        with self.assertRaises(GatewayError) as error: adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "SDK_ERROR")
        self.assertNotIn("fictional-private-error", str(error.exception))
        self.assertEqual(len(bodies), 1)
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_client_cleanup_error_also_discards_complete_response(self):
        adapter, bodies, closed, stream_closed, _ = self.transport(good_chunks(),
            client_close_error=RuntimeError("fictional-private-client"))
        with self.assertRaises(GatewayError) as error: adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "SDK_ERROR")
        self.assertNotIn("fictional-private-client", str(error.exception))
        self.assertEqual(len(bodies), 1)
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_pre_output_provider_error_does_not_retry_internal_path(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid/v1"))
        adapter, bodies, closed, stream_closed, _ = self.transport(create_error=error)
        with self.assertRaises(GatewayError) as failure: adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(failure.exception.code, "CONNECTION_ERROR")
        self.assertEqual(len(bodies), 1)
        self.assertTrue(closed.is_set())
        self.assertFalse(stream_closed.is_set())  # A stream was never created.

    def test_buffer_rejection_closes_transport_without_executing(self):
        adapter, bodies, closed, stream_closed, _ = self.transport([first('x' * 4097)])
        with self.assertRaises(GatewayError) as error: adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "STREAM_BUFFER_LIMIT")
        self.assertTrue(closed.is_set() and stream_closed.is_set())
        self.assertEqual(len(bodies), 1)

    def test_cancel_during_blocked_read_closes_transport(self):
        adapter, _, closed, stream_closed, started = self.transport([first('{}')], blocked=True)
        handle = RequestHandle(); handle.start()
        errors = []
        def invoke():
            with request_scope(handle):
                try: adapter._complete_tool_stream(self.request, self.runtime)
                except GatewayError as error: errors.append(error.code)
        worker = threading.Thread(target=invoke); worker.start()
        self.assertTrue(started.wait(3)); handle.cancel(); worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["USER_CANCELLED"])
        self.assertTrue(closed.is_set() and stream_closed.is_set() and handle.io_closed)
        self.assertEqual(adapter.request_attempts, 1)

    def test_shared_turn_deadline_times_out_without_user_cancel(self):
        adapter, _, closed, stream_closed, _ = self.transport([first('{}')], blocked=True)
        handle = RequestHandle(); handle.start(); handle.limit_turn(0.5)
        with request_scope(handle), self.assertRaises(GatewayError) as error:
            adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "TOTAL_TIMEOUT")
        self.assertFalse(handle._cancel.is_set())
        self.assertTrue(closed.is_set() and stream_closed.is_set() and handle.io_closed)

    def test_request_deadline_is_checked_at_each_ready_chunk_without_waiting_for_io(self):
        adapter, bodies, closed, stream_closed, _ = self.transport(good_chunks())
        calls = [0]
        def remaining(_):
            calls[0] += 1
            if calls[0] == 3: raise GatewayError("TOTAL_TIMEOUT")
            return 30.0
        with patch.object(adapter, "_remaining", side_effect=remaining), self.assertRaises(GatewayError) as error:
            adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "TOTAL_TIMEOUT")
        self.assertTrue(closed.is_set() and stream_closed.is_set())
        self.assertEqual(len(bodies), 1)

    def test_cancel_during_cleanup_cannot_publish_a_complete_call(self):
        handle = RequestHandle(); handle.start()
        adapter, _, closed, stream_closed, _ = self.transport(good_chunks(), during_close=handle.cancel)
        with request_scope(handle), self.assertRaises(GatewayError) as error:
            adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "USER_CANCELLED")
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_deadline_expiry_during_final_normalization_cannot_publish(self):
        handle = RequestHandle(); handle.start()
        adapter, _, closed, stream_closed, _ = self.transport(good_chunks())
        original = _ToolCallStreamAssembler.finish
        def finish(assembler):
            result = original(assembler)
            handle._deadline = 0.0  # Deterministic expired clock, independent of Windows tick resolution.
            return result
        with patch.object(_ToolCallStreamAssembler, "finish", finish), request_scope(handle), self.assertRaises(GatewayError) as error:
            adapter._complete_tool_stream(self.request, self.runtime)
        self.assertEqual(error.exception.code, "TOTAL_TIMEOUT")
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_product_stream_gate_and_ordinary_text_stream_remain_unchanged(self):
        adapter, bodies, closed, stream_closed, _ = self.transport([chunk(content="ordinary", finish="stop")])
        with self.assertRaises(GatewayError) as error: list(adapter.stream(self.request, self.runtime))
        self.assertEqual(error.exception.code, "TOOL_STREAMING_NOT_IMPLEMENTED")
        self.assertEqual(bodies, [])
        handle = RequestHandle(); handle.start()
        with request_scope(handle): events = list(adapter.stream(ModelRequest(Mode.CHAT, ()), self.runtime))
        self.assertEqual(events[0].delta, "ordinary")
        self.assertTrue(closed.is_set() and stream_closed.is_set())

    def test_unknown_capability_still_blocks_internal_entry_before_io(self):
        adapter, bodies, *_ = self.transport(good_chunks())
        runtime = replace(self.runtime, capabilities=replace(self.runtime.capabilities, tool_calling=Support.UNKNOWN))
        with self.assertRaises(GatewayError) as error: adapter._complete_tool_stream(self.request, runtime)
        self.assertEqual(error.exception.code, "OPTION_UNKNOWN")
        self.assertEqual(bodies, [])


if __name__ == "__main__":
    unittest.main()
