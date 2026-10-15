"""T1 protocol only: fake SDK replies, fake tool results, no tool execution."""

import asyncio
import json
import queue
import socket
import threading
import unittest
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from openai import APIConnectionError, OpenAI

import tests.security.test_execution as test_execution
from fishery_ai.composition import build_offline_demo
from fishery_ai.contracts import AnalysisRequest, Mode, Status
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import (GatewayError, ModelMessage, ModelRequest, ModelResponse,
    ModelToolCall, ModelToolDefinition, MockGateway, ProfileRegistry)
from fishery_ai.model_options import Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter


def definition():
    return ModelToolDefinition("get_current_water_quality", "读取当前水质（仅协议 fixture）",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False})


def call(identifier="call_fixture_1", arguments='{}'):
    return ModelToolCall(identifier, "get_current_water_quality", arguments)


def sdk_call(identifier="call_fixture_1", arguments='{}', **changes):
    values = dict(id=identifier, type="function", function=NS(name="get_current_water_quality", arguments=arguments))
    return NS(**{**values, **changes})


def reply(content=None, calls=None):
    return NS(choices=[NS(message=NS(role="assistant", content=content, tool_calls=calls, reasoning_content=None))],
        model="fixture-model", usage=NS(prompt_tokens=3, completion_tokens=2, total_tokens=5))


class GatewayToolTests(unittest.TestCase):
    def test_normal_parameter_diagnostic_preserves_public_error_and_cleanup(self):
        for arguments, reason in [('{', 'MALFORMED_JSON'), ('[]', 'NOT_OBJECT')]:
            with self.subTest(reason=reason):
                gateway, bodies, clients = self.sync_gateway([reply(calls=[sdk_call(arguments=arguments)])])
                with self.assertRaises(GatewayError) as caught:
                    gateway.complete(self.request, self.runtime)
                self.assertEqual(caught.exception.code, 'INVALID_TOOL_CALL')
                self.assertEqual(caught.exception.argument_diagnostic.reason.value, reason)
                self.assertEqual(caught.exception.argument_diagnostic.stage.value, 'model_contract')
                self.assertEqual(len(bodies), 1)
                self.assertTrue(all(client.closed for client in clients))

    def setUp(self):
        # Existing offline guard allows only asyncio's internal Windows wakeup
        # socketpair, never a provider / DNS / application network connection.
        test_execution.ExecutionTests.setUp(self)
        self.profile = replace(self.profile,
            capabilities=replace(self.profile.capabilities, tool_calling=Support.SUPPORTED))
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={})).snapshot(self.profile.profile_id)
        self.request = ModelRequest(Mode.CHAT, (ModelMessage("user", "现在水质怎么样？"),), tools=(definition(),))

    def sync_gateway(self, replies, *, close_error=None):
        bodies, clients = [], []
        sequence = iter(replies)

        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
                self.closed = False
            def create(self, **kwargs):
                bodies.append(kwargs)
                value = next(sequence)
                if isinstance(value, Exception):
                    raise value
                return value
            def close(self):
                self.closed = True
                if close_error:
                    raise close_error

        def factory(*_):
            client = Client()
            clients.append(client)
            return client

        return OpenAICompatibleAdapter(factory), bodies, clients

    def async_gateway(self, responses, *, close_error=None):
        bodies, clients = [], []
        sequence = iter(responses)

        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
                self.closed = False
            async def create(self, **kwargs):
                bodies.append(kwargs)
                value = next(sequence)
                if isinstance(value, Exception):
                    raise value
                return value
            async def close(self):
                self.closed = True
                if close_error:
                    raise close_error

        def factory(*_):
            client = Client()
            clients.append(client)
            return client

        return OpenAICompatibleAdapter(async_client_factory=factory), bodies, clients

    def test_definition_schema_is_detached_and_deeply_immutable(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
        tool = ModelToolDefinition("fixture", "说明", schema)
        schema["properties"]["x"]["type"] = "integer"
        self.assertEqual(tool.parameters["properties"]["x"]["type"], "string")
        with self.assertRaises(TypeError):
            tool.parameters["properties"]["x"]["type"] = "number"
        detached = tool.parameters_dict()
        detached["required"].append("changed")
        self.assertEqual(tool.parameters_dict()["required"], ["x"])
        with self.assertRaises(FrozenInstanceError):
            tool.name = "changed"

    def test_definition_rejects_invalid_name_type_or_non_json_schema(self):
        for changes in ({"name": "bad name"}, {"type": "custom"}, {"parameters": []},
                        {"parameters": {"type": "array"}}, {"parameters": {"limit": float("nan")}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ModelToolDefinition(**{**dict(name="fixture", description="test", parameters={}), **changes})

    def test_call_arguments_are_preserved_without_parsing_into_execution(self):
        value = call(arguments='{ "fixture": 1 }')
        self.assertEqual(value.arguments_json, '{ "fixture": 1 }')
        self.assertEqual(value.type, "function")
        self.assertNotIn("fixture\": 1", repr(value))

    def test_malformed_call_contract_rejected(self):
        for arguments in ('broken', '[]', 'null', '{"v":NaN}', ''):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                call(arguments=arguments)
        for changes in ({"id": ""}, {"type": "custom"}, {"function_name": "bad name"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ModelToolCall(**{**dict(id="fixture", function_name="fixture", arguments_json="{}"), **changes})

    def test_assistant_null_content_and_tool_result_contract(self):
        assistant = ModelMessage("assistant", tool_calls=[call()])
        result = ModelMessage("tool", '{"status":"NO_DATA"}', tool_call_id=call().id)
        self.assertIsNone(assistant.content)
        self.assertEqual(assistant.tool_calls, (call(),))
        self.assertEqual(result.tool_call_id, assistant.tool_calls[0].id)

    def test_message_rejects_wrong_role_missing_id_and_non_json_result(self):
        for kwargs in (dict(role="user", content=None), dict(role="assistant", content=None),
                       dict(role="user", content="x", tool_calls=(call(),)),
                       dict(role="tool", content="{}"), dict(role="tool", content="broken", tool_call_id="id"),
                       dict(role="user", content="x", tool_call_id="id"),
                       dict(role="assistant", tool_calls=(call(), call()))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ModelMessage(**kwargs)

    def test_request_tools_and_minimal_choice(self):
        for choice in (None, "auto", "none", "required"):
            request = replace(self.request, tool_choice=choice)
            self.assertTrue(request.uses_tools)
            body = OpenAICompatibleAdapter._kwargs(request, self.runtime, stream=False)
            if choice is None:
                self.assertNotIn("tool_choice", body)
            else:
                self.assertEqual(body["tool_choice"], choice)
        for kwargs in (dict(tools=(definition(), definition())), dict(tool_choice="unknown"),
                       dict(tools=(), tool_choice="auto")):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(self.request, **kwargs)

    def test_request_encoding_and_tool_call_id_round_trip(self):
        messages = (*self.request.messages, ModelMessage("assistant", None, (call(arguments='{ "x": 1 }'),)),
                    ModelMessage("tool", '{"status":"NO_DATA"}', tool_call_id="call_fixture_1"))
        body = OpenAICompatibleAdapter._kwargs(replace(self.request, messages=messages), self.runtime, stream=False)
        self.assertEqual(body["tools"], [{"type": "function", "function": {"name": definition().name,
            "description": definition().description, "parameters": definition().parameters_dict()}}])
        self.assertIsNone(body["messages"][1]["content"])
        self.assertEqual(body["messages"][1]["tool_calls"][0]["function"]["arguments"], '{ "x": 1 }')
        self.assertEqual(body["messages"][1]["tool_calls"][0]["id"], body["messages"][2]["tool_call_id"])
        self.assertEqual(body["messages"][2]["role"], "tool")

    def test_response_accepts_null_with_tool_calls_preserves_usage_and_model(self):
        gateway, bodies, clients = self.sync_gateway([reply(calls=[sdk_call()])])
        result = gateway.complete(self.request, self.runtime)
        self.assertIsNone(result.text)
        self.assertEqual(result.tool_calls, (call(),))
        self.assertEqual((result.usage.total_tokens, result.returned_model), (5, "fixture-model"))
        self.assertEqual(gateway.request_attempts, 1)
        self.assertTrue(clients[0].closed)

    def test_response_text_and_multiple_tool_calls(self):
        result = OpenAICompatibleAdapter._response(reply("说明", [sdk_call(), sdk_call("call_fixture_2")]))
        self.assertEqual(result.text, "说明")
        self.assertEqual(tuple(c.id for c in result.tool_calls), ("call_fixture_1", "call_fixture_2"))

    def test_null_response_without_valid_calls_still_rejected(self):
        for value in (reply(), reply(calls=[]), reply(content=42)):
            with self.assertRaises(GatewayError) as raised:
                OpenAICompatibleAdapter._response(value)
            self.assertEqual(raised.exception.code, "INVALID_RESPONSE")
        with self.assertRaises(ValueError):
            ModelResponse(None)

    def test_malformed_provider_tool_call_is_safe_and_not_retried(self):
        malformed = ([sdk_call(arguments="broken")], [sdk_call(type="custom")], [sdk_call(id="")],
                     [sdk_call(function=NS(name="fixture"))], [sdk_call(), sdk_call()], {"wrong": "shape"})
        for calls in malformed:
            with self.subTest(calls=calls):
                gateway, _, clients = self.sync_gateway([reply(calls=calls)])
                with self.assertRaises(GatewayError) as raised:
                    gateway.complete(self.request, self.runtime)
                self.assertEqual(raised.exception.code, "INVALID_TOOL_CALL")
                self.assertEqual(gateway.request_attempts, 1)
                self.assertTrue(clients[0].closed)

    def test_two_requests_through_sdk_fixture_no_tool_execution(self):
        gateway, bodies, _ = self.sync_gateway([reply(calls=[sdk_call()]), reply("当前没有可用水质快照。")])
        first = gateway.complete(self.request, self.runtime)
        # This JSON is a fixture, not a get_current_water_quality implementation.
        follow_up = replace(self.request, messages=(*self.request.messages,
            ModelMessage("assistant", first.text, first.tool_calls),
            ModelMessage("tool", '{"status":"NO_DATA"}', tool_call_id=first.tool_calls[0].id)))
        second = gateway.complete(follow_up, self.runtime)
        self.assertEqual(second.text, "当前没有可用水质快照。")
        self.assertEqual(second.tool_calls, ())
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[1]["messages"][-1]["tool_call_id"], "call_fixture_1")

    def test_official_sdk_mock_transport_two_requests(self):
        bodies = []

        def transport(request):
            self.assertEqual((request.method, request.url.path), ("POST", "/v1/chat/completions"))
            body = json.loads(request.content)
            bodies.append(body)
            message = ({"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_fixture_1", "type": "function", "function": {
                    "name": "get_current_water_quality", "arguments": "{}"}}]} if len(bodies) == 1
                else {"role": "assistant", "content": "fixture final"})
            return httpx.Response(200, json={"id": "completion-fixture", "object": "chat.completion",
                "created": 0, "model": "fixture-model", "choices": [{"index": 0,
                    "finish_reason": "tool_calls" if len(bodies) == 1 else "stop", "message": message}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})

        def client(*_):
            return OpenAI(api_key="offline-fixture", base_url="http://mock.invalid/v1", max_retries=0,
                          http_client=httpx.Client(transport=httpx.MockTransport(transport)))

        gateway = OpenAICompatibleAdapter(client)
        first = gateway.complete(self.request, self.runtime)
        follow_up = replace(self.request, messages=(*self.request.messages,
            ModelMessage("assistant", first.text, first.tool_calls),
            ModelMessage("tool", '{"status":"NO_DATA"}', tool_call_id=first.tool_calls[0].id)))
        second = gateway.complete(follow_up, self.runtime)
        self.assertEqual(second.text, "fixture final")
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[1]["messages"][-2]["tool_calls"][0]["id"],
                         bodies[1]["messages"][-1]["tool_call_id"])
        self.assertEqual(bodies[0]["tools"][0]["function"]["parameters"], definition().parameters_dict())

    def test_scripted_mock_follow_up_and_default_mock_remains_compatible(self):
        gateway = MockGateway(responses=(ModelResponse(None, tool_calls=(call(),)), ModelResponse("fixture final")))
        first = gateway.complete(self.request, self.runtime)
        second_request = replace(self.request, messages=(*self.request.messages,
            ModelMessage("assistant", tool_calls=first.tool_calls),
            ModelMessage("tool", "{}", tool_call_id=first.tool_calls[0].id)))
        self.assertEqual(gateway.complete(second_request, self.runtime).text, "fixture final")
        self.assertEqual(len(gateway.calls), 2)
        plain = ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),))
        self.assertIn("inference", json.loads(MockGateway().complete(plain, self.runtime).text))

    def test_tools_protocol_does_not_grant_model_capability(self):
        for support, code in ((Support.UNKNOWN, "OPTION_UNKNOWN"), (Support.UNSUPPORTED, "OPTION_UNSUPPORTED")):
            runtime = replace(self.runtime, capabilities=replace(self.runtime.capabilities, tool_calling=support))
            for request in (self.request, ModelRequest(Mode.CHAT, (ModelMessage("assistant", tool_calls=(call(),)),))):
                gateway, bodies, _ = self.sync_gateway([])
                with self.assertRaises(GatewayError) as raised:
                    gateway.complete(request, runtime)
                self.assertEqual((raised.exception.code, raised.exception.option), (code, "tool_calling"))
                self.assertEqual(bodies, [])

    def test_transient_error_before_tool_call_can_retry(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid"))
        gateway, _, clients = self.sync_gateway([error, reply(calls=[sdk_call()])])
        self.assertEqual(gateway.complete(self.request, self.runtime).tool_calls, (call(),))
        self.assertEqual(gateway.request_attempts, 2)
        self.assertTrue(all(c.closed for c in clients))

    def test_sync_cleanup_after_accepted_tool_call_never_retries(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid"))
        gateway, bodies, _ = self.sync_gateway([reply(calls=[sdk_call()])], close_error=error)
        with self.assertRaises(GatewayError) as raised:
            gateway.complete(self.request, self.runtime)
        self.assertEqual(raised.exception.code, "CONNECTION_ERROR")
        self.assertEqual((len(bodies), gateway.request_attempts), (1, 1))

    def test_async_bridge_parses_null_tool_response(self):
        gateway, _, clients = self.async_gateway([reply(calls=[sdk_call()])])
        handle = RequestHandle()
        with request_scope(handle):
            result = gateway.complete(self.request, self.runtime)
        self.assertEqual(result.tool_calls, (call(),))
        self.assertTrue(clients[0].closed)
        self.assertTrue(handle.io_closed)

    def test_async_follow_up_reuses_request_handle_without_reclaiming_or_cancelling(self):
        gateway, bodies, _ = self.async_gateway([reply(calls=[sdk_call()]), reply("fixture final")])
        handle = RequestHandle()
        with request_scope(handle):
            first = gateway.complete(self.request, self.runtime)
            follow_up = replace(self.request, messages=(*self.request.messages,
                ModelMessage("assistant", tool_calls=first.tool_calls),
                ModelMessage("tool", "{}", tool_call_id=first.tool_calls[0].id)))
            second = gateway.complete(follow_up, self.runtime)
        self.assertEqual(second.text, "fixture final")
        self.assertEqual(handle.state, "RUNNING")  # The application owns finalization.
        self.assertTrue(handle.io_closed)
        self.assertEqual(len(bodies), 2)

    def test_async_after_accepting_tool_output_queue_failure_never_retries(self):
        gateway, bodies, clients = self.async_gateway([reply(calls=[sdk_call()])])
        original_put = queue.Queue.put_nowait

        def interrupted_put(inbox, item):
            original_put(inbox, item)
            if item[0] == "item":
                raise APIConnectionError(request=httpx.Request("POST", "http://mock.invalid"))

        with patch.object(queue.Queue, "put_nowait", interrupted_put), request_scope(RequestHandle()):
            with self.assertRaises(GatewayError) as raised:
                gateway.complete(self.request, self.runtime)
        self.assertEqual(raised.exception.code, "CONNECTION_ERROR")
        self.assertEqual((len(bodies), gateway.request_attempts), (1, 1))
        self.assertTrue(clients[0].closed)

    def test_async_cleanup_after_tool_call_never_retries(self):
        error = APIConnectionError(request=httpx.Request("POST", "http://mock.invalid"))
        gateway, bodies, clients = self.async_gateway([reply(calls=[sdk_call()])], close_error=error)
        with request_scope(RequestHandle()), self.assertRaises(GatewayError) as raised:
            gateway.complete(self.request, self.runtime)
        self.assertEqual(raised.exception.code, "CONNECTION_ERROR")
        self.assertEqual((len(bodies), gateway.request_attempts), (1, 1))
        self.assertTrue(clients[0].closed)

    def test_tool_request_cancelled_before_io_sends_nothing(self):
        gateway, bodies, _ = self.async_gateway([])
        handle = RequestHandle()
        handle.cancel()
        with self.assertRaises(GatewayError) as raised, request_scope(handle):
            gateway.complete(self.request, self.runtime)
        self.assertEqual(raised.exception.code, "USER_CANCELLED")
        self.assertEqual(bodies, [])

    def test_tool_request_pending_io_cancellation_closes_client_without_retry(self):
        started, closed = threading.Event(), threading.Event()

        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                started.set()
                await asyncio.Event().wait()
            async def close(self):
                closed.set()

        gateway = OpenAICompatibleAdapter(async_client_factory=lambda *_: Client())
        handle, errors = RequestHandle(), []

        def execute():
            with request_scope(handle):
                try:
                    gateway.complete(self.request, self.runtime)
                except GatewayError as error:
                    errors.append(error.code)

        thread = threading.Thread(target=execute)
        thread.start()
        self.assertTrue(started.wait(2))
        handle.cancel()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["USER_CANCELLED"])
        self.assertTrue(closed.is_set())
        self.assertTrue(handle.io_closed)
        self.assertEqual(gateway.request_attempts, 1)

    def test_streaming_tool_requests_and_history_rejected_before_io(self):
        for request in (self.request, ModelRequest(Mode.CHAT, (ModelMessage("assistant", tool_calls=(call(),)),))):
            gateway, bodies, _ = self.sync_gateway([])
            with self.assertRaises(GatewayError) as raised:
                list(gateway.stream(request, self.runtime))
            self.assertEqual(raised.exception.code, "TOOL_STREAMING_NOT_IMPLEMENTED")
            self.assertEqual(bodies, [])
            with self.assertRaises(GatewayError):
                list(MockGateway().stream(request, self.runtime))

    def test_unsolicited_stream_tool_delta_rejected_in_both_sdk_paths(self):
        chunk = NS(choices=[NS(delta=NS(content=None, tool_calls=[NS(index=0)]))])
        for async_path in (False, True):
            closed = []

            class Stream:
                def __iter__(self):
                    return iter([chunk])
                def __aiter__(self):
                    async def chunks():
                        yield chunk
                    return chunks()
                def close(self):
                    if async_path:
                        async def finish():
                            closed.append("stream")
                        return finish()
                    closed.append("stream")

            replies = [Stream()]
            gateway, bodies, clients = self.async_gateway(replies) if async_path else self.sync_gateway(replies)
            plain = ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),))
            with request_scope(RequestHandle()) if async_path else patch("fishery_ai.openai_compatible_adapter.current_handle", return_value=None):
                with self.assertRaises(GatewayError) as raised:
                    list(gateway.stream(plain, self.runtime))
            self.assertEqual(raised.exception.code, "TOOL_STREAMING_NOT_IMPLEMENTED")
            self.assertEqual(len(bodies), 1)
            self.assertEqual(closed, ["stream"])
            self.assertTrue(clients[0].closed)

    def test_plain_request_body_and_text_response_unchanged(self):
        plain = ModelRequest(Mode.CHAT, (ModelMessage("system", "system"), ModelMessage("user", "test")))
        gateway, bodies, _ = self.sync_gateway([reply("ok")])
        self.assertEqual(gateway.complete(plain, self.runtime).text, "ok")
        self.assertEqual(bodies, [{"model": self.runtime.model, "messages": [
            {"role": "system", "content": "system"}, {"role": "user", "content": "test"}]}])

    def test_fixed_analysis_does_not_execute_unsolicited_tool_response(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as directory:
            app, _ = build_offline_demo(trace_path=Path(directory) / "trace.jsonl")
            app.gateway = MockGateway(responses=(ModelResponse(None, tool_calls=(call(),)),))
            result = app.analyze(AnalysisRequest(Mode.CHAT, "cloud-demo", "test"))
        self.assertEqual((result.status, result.error_code), (Status.FAILED, "UNEXPECTED_TOOL_CALL"))
        self.assertFalse(result.structured_parse_ok)

    def test_network_blocked(self):
        with self.assertRaisesRegex(AssertionError, "offline tests only"):
            socket.create_connection(("example.invalid", 443))


if __name__ == "__main__":
    unittest.main()
