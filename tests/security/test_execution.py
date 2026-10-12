"""R6/R7 offline transport cancellation, resource cleanup and raw body isolation."""

import asyncio
import json
import socket
import _socket
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from fishery_ai.contracts import Mode
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import RequestHandle, RequestRegistry, request_scope
from fishery_ai.manual import ManualRequest
from fishery_ai.model_gateway import GatewayError, ModelCapabilities, ModelProfile, ModelRequest, ProfileRegistry
from fishery_ai.model_options import ReasoningOptions, ReasoningMode, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.providers import AuthSpec


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        internal = threading.local()
        pair = socket.socketpair
        def wakeup_pair(*args, **kwargs):
            internal.wakeup = True
            try:
                return pair(*args, **kwargs)
            finally:
                internal.wakeup = False
        def guarded_connect(sock, address):
            if getattr(internal, "wakeup", False) and address[0] in ("127.0.0.1", "::1"):
                return _socket.socket.connect(sock, address)
            raise AssertionError("offline tests only")
        for name, value in (("socketpair", wakeup_pair),):
            guard = patch.object(socket, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(socket.socket, "connect", guarded_connect)
        guard.start()
        self.addCleanup(guard.stop)
        for obj, names in ((socket.socket, ("connect_ex", "sendto")),
                           (socket, ("create_connection", "getaddrinfo"))):
            for name in names:
                guard = patch.object(obj, name, side_effect=AssertionError("offline tests only"))
                guard.start()
                self.addCleanup(guard.stop)
        self.profile = ModelProfile("test", "Test", "local", "http://mock.invalid/v1", "test-model",
            auth_spec=AuthSpec.NONE, max_retries=1,
            capabilities=ModelCapabilities(streaming=Support.SUPPORTED, service_id="custom",
                adapter_id="generic_openai_chat", base_url="http://mock.invalid/v1", model_id="test-model"))
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={})).snapshot("test")

    def cancel_call(self, streaming):
        started, client_closed, stream_closed = (threading.Event() for _ in range(3))
        class Stream:
            def __aiter__(self):
                return self
            async def __anext__(self):
                started.set()
                await asyncio.Event().wait()
            async def close(self):
                stream_closed.set()
        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                if kwargs.get("stream"):
                    return Stream()
                started.set()
                await asyncio.Event().wait()
            async def close(self):
                client_closed.set()
        gateway = OpenAICompatibleAdapter(async_client_factory=lambda *_: Client())
        handle = RequestHandle()
        handle.start()
        errors = []
        def execute():
            with request_scope(handle):
                try:
                    if streaming:
                        list(gateway.stream(ModelRequest(Mode.CHAT, ()), self.runtime))
                    else:
                        gateway.complete(ModelRequest(Mode.CHAT, ()), self.runtime)
                except GatewayError as exc:
                    errors.append(exc.code)
                    handle.finish(exc.code)
        worker = threading.Thread(target=execute)
        worker.start()
        self.assertTrue(started.wait(2))
        handle.cancel()
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["USER_CANCELLED"])
        self.assertEqual(gateway.request_attempts, 1)
        self.assertTrue(client_closed.is_set())
        self.assertEqual(stream_closed.is_set(), streaming)
        self.assertTrue(handle.public_info()["backend_io_closed"])
        self.assertEqual(handle.state, "CANCELLED")
        self.assertEqual(handle.public_info()["remote_compute_stopped"], "unknown")

    def test_normal_blocked_io_is_cancelled_without_retry(self):
        self.cancel_call(False)

    def test_stream_blocked_read_is_cancelled_and_resources_close(self):
        self.cancel_call(True)

    def test_shared_turn_deadline_aborts_blocked_sdk_without_user_cancel(self):
        closed, timeout_values = threading.Event(), []
        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                await asyncio.Event().wait()
            async def close(self):
                closed.set()
        def factory(runtime, remaining):
            timeout_values.append(remaining)
            return Client()
        handle = RequestHandle(); handle.start(); handle.limit_turn(0.05)
        adapter = OpenAICompatibleAdapter(async_client_factory=factory)
        with request_scope(handle), self.assertRaises(GatewayError) as error:
            adapter.complete(ModelRequest(Mode.CHAT, ()), self.runtime)
        handle.finish(error.exception.code)
        self.assertEqual(error.exception.code, "TOTAL_TIMEOUT")
        self.assertEqual(handle.state, "FAILED")
        self.assertFalse(handle._cancel.is_set())
        self.assertTrue(closed.is_set())
        self.assertTrue(handle.io_closed)
        self.assertEqual(adapter.request_attempts, 1)  # No retry after timeout.
        self.assertTrue(0 < timeout_values[0] <= 0.051)

    def test_two_sdk_requests_use_remaining_turn_time_not_two_full_timeouts(self):
        calls, timeout_values, closed = [], [], []
        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    await asyncio.sleep(0.02)
                    return NS(choices=[NS(message=NS(content="OK", tool_calls=()), finish_reason="stop")], usage=None)
                await asyncio.Event().wait()
            async def close(self):
                closed.append(True)
        def factory(runtime, remaining):
            timeout_values.append(remaining)
            return Client()
        handle = RequestHandle(); handle.start(); handle.limit_turn(0.15)
        adapter = OpenAICompatibleAdapter(async_client_factory=factory)
        runtime = replace(self.runtime, max_retries=0)
        with request_scope(handle):
            self.assertEqual(adapter.complete(ModelRequest(Mode.CHAT, ()), runtime).text, "OK")
            with self.assertRaises(GatewayError) as error:
                adapter.complete(ModelRequest(Mode.CHAT, ()), runtime)
        self.assertEqual(error.exception.code, "TOTAL_TIMEOUT")
        self.assertLess(timeout_values[1], timeout_values[0])
        self.assertEqual(len(closed), 2)
        self.assertEqual(adapter.request_attempts, 2)

    def test_provider_error_before_turn_deadline_keeps_provider_code(self):
        from openai import BadRequestError
        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                raise BadRequestError("fictional", response=httpx.Response(400,
                    request=httpx.Request("POST", "http://mock.invalid/v1")), body={})
            async def close(self):
                pass
        handle = RequestHandle(); handle.start(); handle.limit_turn(2)
        with request_scope(handle), self.assertRaises(GatewayError) as error:
            OpenAICompatibleAdapter(async_client_factory=lambda *_: Client()).complete(
                ModelRequest(Mode.CHAT, ()), self.runtime)
        self.assertEqual(error.exception.code, "HTTP_400")
        self.assertFalse(handle._cancel.is_set())

    def test_turn_deadline_cannot_be_renewed_or_set_from_prepare_time(self):
        handle = RequestHandle()
        with patch("fishery_ai.execution.time.monotonic", return_value=100):
            handle.start(); handle.limit_turn(10)
        with patch("fishery_ai.execution.time.monotonic", return_value=105):
            handle.limit_turn(10)
            self.assertEqual(handle.remaining_timeout(30), 5)
        with patch("fishery_ai.execution.time.monotonic", return_value=111), self.assertRaises(GatewayError) as error:
            handle.check()
        self.assertEqual(error.exception.code, "TOTAL_TIMEOUT")

    def test_timeout_cleanup_abort_does_not_set_user_cancel_event(self):
        handle = RequestHandle(); handle.start()
        aborted = []
        handle.bind(lambda: aborted.append(True))
        handle.abort_io()
        self.assertEqual(aborted, [True])
        self.assertFalse(handle._cancel.is_set())
        handle.finish("TOTAL_TIMEOUT")
        self.assertEqual(handle.state, "FAILED")

    def test_cancel_before_sdk_sends_no_request(self):
        handle = RequestHandle()
        handle.cancel()
        with self.assertRaises(GatewayError) as error, request_scope(handle):
            pass
        self.assertEqual(error.exception.code, "USER_CANCELLED")
        self.assertTrue(handle.io_closed)

    def test_handle_ownership_and_single_execution(self):
        registry = RequestRegistry(limit=1)
        handle = registry.create()
        with self.assertRaises(GatewayError):
            registry.get(handle.request_id, "wrong-token")
        with self.assertRaises(GatewayError) as malformed:
            registry.get(handle.request_id, "不可用")
        self.assertEqual(malformed.exception.code, "REQUEST_NOT_FOUND")
        handle.start()
        with self.assertRaises(GatewayError):
            handle.start()
        handle.finish()
        handle.cancel()
        self.assertEqual(handle.state, "COMPLETED")
        self.assertIsNotNone(registry.create())
        self.assertNotIn(handle.control_token, repr(handle))

    def test_manual_raw_sdk_body_has_no_managed_injection(self):
        bodies, clients = [], []
        async def respond(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"id":"fake", "object":"chat.completion",
                "created":0, "model":"test-model", "choices":[{"index":0,
                    "message":{"role":"assistant", "content":None,
                        "tool_calls":[{"id":"fake-call", "type":"function", "function":{"name":"never_execute", "arguments":"{}"}}]},
                    "finish_reason":"tool_calls"}], "usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}})
        def client(*_):
            sdk = AsyncOpenAI(api_key="fictional-sdk-key", base_url="http://mock.invalid/v1",
                max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
            clients.append(sdk)
            return sdk
        adapter = OpenAICompatibleAdapter(async_client_factory=client)
        body = {"model":"test-model", "messages":[{"role":"user","content":"OK"}],
                "enable_thinking":False,"unknown_expert_field":{"test":True}, "max_tokens":8}
        request = ManualRequest.from_dict(body, model="test-model")
        runtime = replace(self.runtime, default_reasoning=ReasoningOptions(ReasoningMode.ON))
        with patch("fishery_ai.openai_compatible_adapter.validate_options", side_effect=AssertionError("no capability validation")), \
                patch("fishery_ai.openai_compatible_adapter.effective_options", side_effect=AssertionError("no runtime defaults")):
            response = adapter.manual_complete(request, runtime)
        self.assertEqual(bodies, [body])
        self.assertEqual(adapter.request_attempts, 1)
        self.assertTrue(clients[0].is_closed())
        self.assertEqual(response.usage.total_tokens, 5)
        self.assertEqual(response.raw["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "never_execute")
        self.assertNotIn("fictional-sdk-key", json.dumps(response.raw))

    def test_manual_reserved_fields_and_size_rejected(self):
        base={"model":"test-model","messages":[{"role":"user","content":"OK"}]}
        for field in ("headers", "extra_headers", "api_key", "base_url", "timeout", "extra_body"):
            with self.subTest(field=field), self.assertRaises(GatewayError):
                ManualRequest.from_dict({**base,field:"fictional"},model="test-model")
        with self.assertRaises(GatewayError):
            ManualRequest.from_dict({**base,"model":"different"},model="test-model")
        with self.assertRaises(GatewayError):
            ManualRequest.from_dict({**base,"messages":[{"content":"x"*13000}]},model="test-model")
        with self.assertRaises(GatewayError) as invalid:
            ManualRequest.from_dict({**base,"messages":[{"content":"\ud800"}]},model="test-model")
        self.assertEqual(invalid.exception.code, "INVALID_REQUEST")

    def test_async_loop_start_failure_is_safe_and_does_not_hang(self):
        handle = RequestHandle()
        handle.start()
        with patch("fishery_ai.openai_compatible_adapter.asyncio.Runner", side_effect=RuntimeError("fictional-private-error")):
            with request_scope(handle), self.assertRaises(GatewayError) as error:
                OpenAICompatibleAdapter().complete(ModelRequest(Mode.CHAT, ()), self.runtime)
        self.assertEqual(error.exception.code, "SDK_ERROR")
        self.assertNotIn("fictional-private-error", str(error.exception))

    def test_manual_response_redacts_even_json_escaped_fictional_credential(self):
        fictional = 'fake-quote-"-key'
        credential = CredentialStore(process_env={"TEST_FAKE_KEY":fictional}).resolve("TEST_FAKE_KEY")
        runtime = replace(self.runtime, credential=credential)
        response = NS(model_dump=lambda **_: {"echo":fictional},usage=None)
        safe = OpenAICompatibleAdapter._manual_response(response, runtime)
        self.assertEqual(safe.raw["echo"], "[REDACTED]")
        self.assertNotIn(fictional, json.dumps(safe.raw))
        self.assertNotIn(fictional, repr(safe))

    def test_async_retry_only_before_visible_content(self):
        from openai import APIConnectionError
        attempts = []
        class Stream:
            def __aiter__(self):
                return self.events()
            async def events(self):
                yield NS(choices=[NS(delta=NS(content="visible"))], usage=None)
                raise APIConnectionError(request=httpx.Request("POST", "http://mock.invalid/v1"))
            async def close(self):
                pass
        class Client:
            def __init__(self):
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **kwargs):
                attempts.append(kwargs)
                if len(attempts) == 1:
                    raise APIConnectionError(request=httpx.Request("POST", "http://mock.invalid/v1"))
                return Stream()
            async def close(self):
                pass
        handle = RequestHandle()
        handle.start()
        gateway = OpenAICompatibleAdapter(async_client_factory=lambda *_:Client())
        with request_scope(handle):
            stream = gateway.stream(ModelRequest(Mode.CHAT, ()), self.runtime)
            self.assertEqual(next(stream).delta, "visible")
            with self.assertRaises(GatewayError):
                next(stream)
        self.assertEqual(len(attempts), 2)  # First pre-output failure retried, post-output failure never regenerated.
        self.assertTrue(handle.io_closed)
