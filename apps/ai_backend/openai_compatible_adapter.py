"""OpenAI-compatible Chat Completions transport; the SDK is isolated here."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import socket
import ssl
import time
import re
import asyncio
import json
import math
import queue
import threading
from urllib.parse import urlsplit, urlunsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from .contracts import Usage, UsageSource
from .model_gateway import (GatewayError, ModelEvent, ModelRequest, ModelResponse, ModelToolCall,
                            RetryableGatewayError, StreamingModelError, RuntimeSnapshot, effective_options, validate_tool_request)
from .model_options import (GenerationOptions, OptionValidationError, ReasoningMode,
                            Support, validate_options)
from .providers import AuthSpec
from .execution import current_handle, RequestHandle
from .manual import ManualRequest, ManualResponse
from .tool_argument_diagnostics import (ArgumentStage, ArgumentRejection, ToolArgumentError,
    ToolArgumentDiagnostic, rejection)


RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _usage(value: object) -> Usage:
    if value is None:
        return Usage()
    details = getattr(value, "completion_tokens_details", None)
    prompt_details = getattr(value, "prompt_tokens_details", None)
    values = (getattr(value, "prompt_tokens", None),
              getattr(value, "completion_tokens", None),
              getattr(value, "total_tokens", None),
              getattr(details, "reasoning_tokens", None),
              getattr(prompt_details, "cached_tokens", None))
    return Usage(*values, source=UsageSource.PROVIDER) if any(
        item is not None for item in values) else Usage()


class _ToolCallStreamAssembler:
    """One bounded SDK response, not an executor or a product Streaming gate.

    Call finish only after clean iterator exhaustion and successful I/O cleanup.
    IDs are stable metadata; names/arguments may be deltas. No JSON repair.
    """

    MAX_CHUNKS = 4096
    MAX_BUFFER_BYTES = 262144
    MAX_ARGUMENT_BYTES = 4096  # Same upper boundary as the existing Executor.
    MAX_JSON_DEPTH = 16
    MAX_JSON_NODES = 1024

    def __init__(self, definitions):
        self._names = frozenset(d.name for d in definitions)
        self._chunks = self._bytes = self._argument_bytes = 0
        self._content, self._reasoning, self._arguments = [], [], []
        self._id = self._name = self._type = None
        self._model = self._response_id = self._finish_reason = None
        self._call_seen = self._arguments_seen = self._finished = self._failed = False
        self._usage = Usage()

    def __repr__(self):
        return f"_ToolCallStreamAssembler(chunks={self._chunks}, finished={self._finished})"

    def _reject(self, code="INVALID_STREAM_EVENT", *, argument_diagnostic=None):
        self._failed = True
        raise GatewayError(code, argument_diagnostic=argument_diagnostic) from None

    def _text(self, value, *, limit=None):
        if not isinstance(value, str):
            self._reject()
        # Reject oversized strings before allocating a second UTF-8 buffer.
        if len(value) > self.MAX_BUFFER_BYTES - self._bytes or (limit is not None and len(value) > limit):
            self._reject("STREAM_BUFFER_LIMIT")
        try:
            size = len(value.encode("utf-8"))
        except UnicodeError:
            self._reject()
        if limit is not None and size > limit:
            self._reject("STREAM_BUFFER_LIMIT")
        self._bytes += size
        if self._bytes > self.MAX_BUFFER_BYTES:
            self._reject("STREAM_BUFFER_LIMIT")
        return size

    def _stable(self, field, value, *, limit=256):
        if value is None or value == "":
            return
        self._text(value, limit=limit)
        prior = getattr(self, field)
        if prior is not None and prior != value:
            self._reject("INVALID_TOOL_CALL" if field == "_id" else "INVALID_STREAM_EVENT")
        setattr(self, field, value)

    def push(self, chunk):
        if self._finished or self._failed:
            self._reject("INVALID_STREAM_STATE")
        self._chunks += 1
        if self._chunks > self.MAX_CHUNKS:
            self._reject("STREAM_CHUNK_LIMIT")
        try:
            self._push(chunk)
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
            self._reject()

    def _push(self, chunk):
        self._stable("_model", getattr(chunk, "model", None))
        self._stable("_response_id", getattr(chunk, "id", None))
        usage = _usage(getattr(chunk, "usage", None))
        if usage.source != UsageSource.UNAVAILABLE:
            # Usage is cumulative per response, never summed across chunks.
            fields = ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "cached_input_tokens")
            values = []
            for key in fields:
                old, new = getattr(self._usage, key), getattr(usage, key)
                if old is not None and new is not None and new < old:
                    self._reject()
                values.append(new if new is not None else old)
            self._usage = Usage(*values, source=UsageSource.PROVIDER)
        choices = chunk.choices
        if not isinstance(choices, (list, tuple)) or len(choices) > 1:
            self._reject()
        if not choices:  # Optional usage-only frame, including after finish.
            return
        choice = choices[0]
        if type(choice.index) is not int or choice.index != 0:
            self._reject()
        delta = choice.delta
        if getattr(delta, "role", None) not in (None, "assistant"):
            self._reject()
        if getattr(delta, "function_call", None) is not None:
            self._reject("INVALID_TOOL_CALL")  # Legacy function_call deltas are not tool_calls.
        content, reasoning = getattr(delta, "content", None), getattr(delta, "reasoning_content", None)
        for text in (content, reasoning):
            if text is not None:
                self._text(text)
        calls = getattr(delta, "tool_calls", None)
        if calls is not None and not isinstance(calls, (list, tuple)):
            self._reject("INVALID_TOOL_CALL")
        if self._finish_reason is not None and (content or reasoning or calls):
            self._reject()  # No response data after a terminal marker.
        if content is not None:
            self._content.append(content)
        if reasoning is not None:
            self._reasoning.append(reasoning)
        if calls:
            if len(calls) != 1:
                self._reject("TOOL_CALL_LIMIT")
            call = calls[0]
            if type(call.index) is not int or call.index < 0:
                self._reject("INVALID_TOOL_CALL")
            if call.index != 0:
                self._reject("TOOL_CALL_LIMIT")
            self._call_seen = True
            self._stable("_id", getattr(call, "id", None))
            call_type = getattr(call, "type", None)
            if call_type not in (None, ""):
                if call_type != "function":
                    self._reject("INVALID_TOOL_CALL")
                self._type = call_type
            function = getattr(call, "function", None)
            if function is not None:
                name = getattr(function, "name", None)
                if name not in (None, ""):
                    self._text(name, limit=64)
                    # Repeated complete metadata is legal, conflicting names are not.
                    if not (self._name in self._names and name == self._name):
                        candidate = (self._name or "") + name
                        if not any(known.startswith(candidate) for known in self._names):
                            self._reject("INVALID_TOOL_CALL")
                        self._name = candidate
                arguments = getattr(function, "arguments", None)
                if arguments is not None:
                    self._arguments_seen = True
                    try:
                        size = self._text(arguments)
                    except GatewayError as error:
                        reason = (ArgumentRejection.ARGUMENTS_TOO_LARGE if error.code == "STREAM_BUFFER_LIMIT"
                                  else ArgumentRejection.INVALID_ENCODING if isinstance(arguments, str)
                                  else ArgumentRejection.MALFORMED_JSON)
                        raise GatewayError(error.code, argument_diagnostic=rejection(
                            ArgumentStage.STREAM_ASSEMBLER, reason, arguments)) from None
                    self._argument_bytes += size
                    if self._argument_bytes > self.MAX_ARGUMENT_BYTES:
                        self._reject("STREAM_BUFFER_LIMIT", argument_diagnostic=ToolArgumentDiagnostic(
                            ArgumentStage.STREAM_ASSEMBLER, ArgumentRejection.ARGUMENTS_TOO_LARGE,
                            argument_bytes=min(self._argument_bytes, 65536)))
                    self._arguments.append(arguments)
        reason = getattr(choice, "finish_reason", None)
        if reason is not None:
            if reason not in ("stop", "tool_calls", "function_call"):
                if reason in ("length", "content_filter"):
                    self._finish_reason = reason  # Failure audit only; never executable.
                self._reject("STREAM_TRUNCATED" if reason == "length" else "INVALID_STREAM_EVENT")
            if self._finish_reason is not None and reason != self._finish_reason:
                self._reject()
            self._finish_reason = reason

    def _validate_arguments(self, text):
        def reject(reason, arguments=None):
            self._reject("INVALID_TOOL_ARGUMENTS", argument_diagnostic=rejection(
                ArgumentStage.STREAM_ASSEMBLER, reason, text, arguments))
        # Bound nesting before json.loads, ignoring braces inside JSON strings.
        depth = 0; quoted = escaped = False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > self.MAX_JSON_DEPTH:
                    reject(ArgumentRejection.ARGUMENTS_TOO_COMPLEX)
            elif char in "]}":
                depth -= 1
        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        def invalid_constant(_):
            raise ValueError("invalid constant")
        try:
            try:
                value = json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)
            except json.JSONDecodeError:
                reject(ArgumentRejection.MALFORMED_JSON)
            except (ValueError, OverflowError):
                reject(ArgumentRejection.INVALID_JSON_VALUE)
            if not isinstance(value, dict):
                reject(ArgumentRejection.NOT_OBJECT)
            pending, nodes = [value], 0
            while pending:
                item = pending.pop(); nodes += 1
                if nodes > self.MAX_JSON_NODES:
                    reject(ArgumentRejection.ARGUMENTS_TOO_COMPLEX, value)
                if isinstance(item, dict):
                    pending.extend(item.keys()); pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
                elif isinstance(item, str):
                    item.encode("utf-8")
                elif isinstance(item, float) and not math.isfinite(item):
                    raise ValueError("non-finite number")
        except UnicodeError:
            reject(ArgumentRejection.INVALID_ENCODING)
        except RecursionError:
            reject(ArgumentRejection.ARGUMENTS_TOO_COMPLEX)
        except (ValueError, TypeError, OverflowError):
            reject(ArgumentRejection.INVALID_JSON_VALUE)

    def finish(self):
        if self._finished or self._failed:
            self._reject("INVALID_STREAM_STATE")
        if self._finish_reason is None:
            self._reject("STREAM_INTERRUPTED")
        calls = ()
        if self._call_seen:
            if (not self._id or not self._id.strip() or self._type != "function"
                    or self._name not in self._names or not self._arguments_seen):
                self._reject("INVALID_TOOL_CALL")
            arguments = "".join(self._arguments)
            self._validate_arguments(arguments)
            try:
                calls = (ModelToolCall(self._id, self._name, arguments, type=self._type),)
            except ToolArgumentError as error:
                self._reject("INVALID_TOOL_CALL", argument_diagnostic=error.argument_diagnostic)
            except (ValueError, TypeError, RecursionError):
                self._reject("INVALID_TOOL_CALL")
        elif self._finish_reason != "stop":
            self._reject("INVALID_TOOL_CALL")
        text, reasoning = "".join(self._content), "".join(self._reasoning)
        if not text.strip() and not calls:
            self._reject("INVALID_RESPONSE")
        self._finished = True
        return ModelResponse(text if self._content or not calls else None, self._usage,
            self._model, bool(reasoning), reasoning or None, tool_calls=calls, finish_reason=self._finish_reason)

    @property
    def observed_usage(self):
        return self._usage

    @property
    def observed_finish_reason(self):
        return self._finish_reason


class OpenAICompatibleAdapter:
    """The gateway owns retries; the SDK performs one attempt at a time."""

    def __init__(self, client_factory: Callable[[RuntimeSnapshot, float], object] | None = None,
                 *, async_client_factory=None):
        self._client_factory = client_factory or self._make_client
        self._async_client_factory = async_client_factory or self._make_async_client
        self.request_attempts = 0

    def _new_tool_stream_assembler(self, definitions):
        """Internal factory; qualification may observe without changing validation."""
        return _ToolCallStreamAssembler(definitions)

    @staticmethod
    def _make_async_client(runtime, remaining):
        timeout = httpx.Timeout(connect=min(runtime.connect_timeout_s, remaining),
            read=min(runtime.read_timeout_s, remaining), write=min(runtime.read_timeout_s, remaining),
            pool=min(runtime.connect_timeout_s, remaining))
        key = None if runtime.auth_spec == AuthSpec.NONE else runtime.credential._for_adapter()
        return AsyncOpenAI(base_url=runtime.base_url, api_key=key or "local-no-key",
                           timeout=timeout, max_retries=0)

    @staticmethod
    def _response(response):
        try:
            message = response.choices[0].message
            if getattr(message, "role", "assistant") != "assistant":
                raise GatewayError("INVALID_RESPONSE")
            raw_calls = getattr(message, "tool_calls", None)
            calls = ()
            if raw_calls is not None:
                if not isinstance(raw_calls, (list, tuple)):
                    raise GatewayError("INVALID_TOOL_CALL")
                try:
                    calls = tuple(ModelToolCall(id=call.id, type=call.type,
                        function_name=call.function.name, arguments_json=call.function.arguments)
                        for call in raw_calls)
                    if len({call.id for call in calls}) != len(calls):
                        raise ValueError("duplicate call ID")
                except ToolArgumentError as error:
                    raise GatewayError("INVALID_TOOL_CALL", argument_diagnostic=error.argument_diagnostic) from None
                except (AttributeError, TypeError, ValueError, RecursionError):
                    raise GatewayError("INVALID_TOOL_CALL") from None
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning is not None and not isinstance(reasoning, str):
                raise GatewayError("INVALID_RESPONSE")
            return ModelResponse(message.content, _usage(getattr(response, "usage", None)),
                getattr(response, "model", None), bool(reasoning), reasoning, tool_calls=calls,
                finish_reason=getattr(response.choices[0], "finish_reason", None))
        except (IndexError, AttributeError, TypeError, ValueError, RecursionError):
            raise GatewayError("INVALID_RESPONSE") from None

    @staticmethod
    def _event(chunk):
        if chunk.choices and getattr(chunk.choices[0].delta, "tool_calls", None):
            raise GatewayError("TOOL_STREAMING_NOT_IMPLEMENTED")
        delta = chunk.choices[0].delta.content if chunk.choices else None
        reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None) if chunk.choices else None
        if any(value is not None and not isinstance(value, str) for value in (delta, reasoning)):
            raise GatewayError("INVALID_STREAM_EVENT")
        usage = _usage(getattr(chunk, "usage", None))
        return ModelEvent(delta or "", usage if usage.source != UsageSource.UNAVAILABLE else None, reasoning,
                          getattr(chunk.choices[0], "finish_reason", None) if chunk.choices else None)

    @staticmethod
    def _manual_response(response, runtime):
        raw = response.model_dump(mode="json")
        encoded = json.dumps(raw, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
            raise GatewayError("RESPONSE_TOO_LARGE")
        key = runtime.credential._for_adapter()
        if key:
            def redact(value):
                if isinstance(value, str):
                    return value.replace(key, "[REDACTED]")
                if isinstance(value, dict):
                    return {redact(name): redact(item) for name, item in value.items()}
                if isinstance(value, list):
                    return [redact(item) for item in value]
                return value
            raw = redact(raw)
        return ManualResponse(raw, _usage(getattr(response, "usage", None)))

    def _bridge(self, kwargs, runtime, *, stream, manual=False, tool_definitions=None):
        """A request-owned loop/thread, bounded queue and actual cancellable SDK Task."""
        self._check_secret(runtime)
        handle = current_handle() or RequestHandle()
        handle.check()
        if not handle._claimed:
            handle.start()
        handle.io_closed = True
        inbox = queue.Queue(maxsize=32)
        stopped = threading.Event()
        deadline = handle.request_deadline(runtime.total_timeout_s)
        stream_assembler = None

        def safe_stream_error(error):
            if tool_definitions is None or isinstance(error, StreamingModelError):
                return error
            return StreamingModelError(error.code,
                usage=stream_assembler.observed_usage if stream_assembler is not None else Usage(),
                finish_reason=stream_assembler.observed_finish_reason if stream_assembler is not None else None,
                argument_diagnostic=error.argument_diagnostic)

        async def put(item):
            while not stopped.is_set():
                try:
                    inbox.put_nowait(item)
                    return
                except queue.Full:
                    await asyncio.sleep(0.01)
            raise asyncio.CancelledError()

        async def operation():
            nonlocal stream_assembler
            emitted = False
            assembling = tool_definitions is not None
            attempts = 0 if manual or assembling else runtime.max_retries
            async with asyncio.timeout(self._remaining(deadline)):
                for attempt in range(attempts + 1):
                    handle.check()
                    client = self._async_client_factory(runtime, self._remaining(deadline))
                    handle.io_closed = False
                    sdk_stream = None
                    assembler = self._new_tool_stream_assembler(tool_definitions) if assembling else None
                    stream_assembler = assembler
                    try:
                        self.request_attempts += 1
                        if manual:
                            response = await client.post("/chat/completions", body=kwargs,
                                cast_to=ChatCompletionChunk if stream else ChatCompletion,
                                stream=stream, **({"stream_cls": AsyncStream[ChatCompletionChunk]} if stream else {}))
                        else:
                            response = await client.chat.completions.create(**kwargs)
                        if stream:
                            sdk_stream = response
                            async for chunk in sdk_stream:
                                handle.check()
                                if assembler is not None:
                                    self._remaining(deadline)  # Also bound immediately ready / CPU-only chunks.
                                    emitted = True  # Tool metadata/arguments are observable too; never retry.
                                    assembler.push(chunk)
                                    if handle._event_channel is not None:
                                        # Only content; arguments/reasoning remain inside the assembler.
                                        handle.report_preview("".join(assembler._content), runtime.credential._for_adapter())
                                else:
                                    event = self._manual_response(chunk, runtime) if manual else self._event(chunk)
                                    emitted = emitted or manual or bool(event.delta or event.reasoning_delta)
                                    await put(("item", event))
                        else:
                            handle.check()
                            normalized = self._manual_response(response, runtime) if manual else self._response(response)
                            # A complete response (including tool calls with null
                            # content) is observable before queuing or cleanup.
                            emitted = True
                            await put(("item", normalized))
                        if assembler is None:
                            return
                    except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                        handle.check()
                        error = self._map_error(exc)
                        if (not manual and kwargs.get("tools") and isinstance(exc, APIStatusError)
                                and self._is_explicit_tool_unsupported(exc)):
                            raise GatewayError("TOOL_UNSUPPORTED") from None
                        if isinstance(exc, APIStatusError) and stream and self._is_explicit_streaming_unsupported(exc):
                            error = GatewayError("STREAM_UNSUPPORTED")
                        elif isinstance(exc, APIStatusError) and self._is_explicit_thinking_unsupported(exc):
                            error = GatewayError("THINKING_UNSUPPORTED")
                        if emitted or not isinstance(error, RetryableGatewayError) or attempt >= attempts:
                            raise error from None
                    finally:
                        try:
                            if sdk_stream is not None:
                                await sdk_stream.close()
                        finally:
                            await client.close()
                            handle.io_closed = True
                    if assembler is not None:
                        # Iterator exhausted AND cleanup succeeded; only now publish a complete call.
                        handle.check()
                        self._remaining(deadline)
                        normalized = assembler.finish()
                        handle.check()
                        self._remaining(deadline)
                        await put(("item", normalized))
                        return

        async def run():
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(operation())
            def cancel_task():
                if not task.done() and not loop.is_closed():
                    loop.call_soon_threadsafe(task.cancel)
            handle.bind(cancel_task)
            try:
                await task
                await put(("done", None))
            except asyncio.CancelledError:
                try:
                    handle.check()
                except GatewayError as exc:
                    await put(("error", safe_stream_error(exc)))
                else:
                    await put(("error", safe_stream_error(GatewayError("SDK_ERROR"))))
            except TimeoutError:
                await put(("error", safe_stream_error(GatewayError("TOTAL_TIMEOUT"))))
            except GatewayError as exc:
                await put(("error", safe_stream_error(exc)))
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                await put(("error", safe_stream_error(self._map_error(exc))))  # Cleanup never retries.
            except Exception:
                await put(("error", safe_stream_error(GatewayError("SDK_ERROR"))))
            finally:
                handle.unbind()

        def worker():
            try:
                with asyncio.Runner() as runner:
                    runner.run(run())
            except asyncio.CancelledError:
                pass  # Consumer closed; operation finally still closes owned SDK resources.
            except Exception:
                # Loop startup/cleanup failures must never strand the Flask consumer.
                try:
                    inbox.put_nowait(("error", GatewayError("SDK_ERROR")))
                except queue.Full:
                    pass

        thread = threading.Thread(target=worker, name="fishery-sdk-request", daemon=True)
        thread.start()
        consumer_deadline = deadline + 5  # Cleanup grace is not a renewed generation budget.
        ended = False
        try:
            while True:
                try:
                    kind, item = inbox.get(timeout=0.2)
                except queue.Empty:
                    handle.check()
                    if not thread.is_alive():
                        raise GatewayError("SDK_ERROR") from None
                    if time.monotonic() > consumer_deadline:
                        raise GatewayError("TOTAL_TIMEOUT")
                    continue
                if kind == "done":
                    ended = True
                    return
                if kind == "error":
                    ended = True
                    raise item
                handle.check()
                yield item
        except GatewayError as exc:
            raise safe_stream_error(exc) from None
        finally:
            if not ended:
                handle.abort_io()
            stopped.set()
            thread.join(timeout=5)
            if thread.is_alive():
                handle.io_closed = False

    def manual_complete(self, request: ManualRequest, runtime):
        if request.streaming:
            raise GatewayError("INVALID_REQUEST")
        events = self._bridge(json.loads(request.body_json), runtime, stream=False, manual=True)
        try:
            response = next(events)
            for _ in events:
                pass
            return response
        finally:
            events.close()

    def manual_stream(self, request: ManualRequest, runtime):
        if not request.streaming:
            raise GatewayError("INVALID_REQUEST")
        yield from self._bridge(json.loads(request.body_json), runtime, stream=True, manual=True)

    def _complete_tool_stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        """Buffered internal transport; only explicitly configured coordinators opt in.

        Keep the public stream() gate unchanged. All ordinary model capability,
        options and Preset gates still apply to this explicit fixture entry.
        """
        kwargs = self._kwargs(request, runtime, stream=True, _assemble_tools=True)
        events = self._bridge(kwargs, runtime, stream=True, tool_definitions=request.tools)
        response = None
        try:
            response = next(events)
            for _ in events:
                pass
            if current_handle() is not None:
                current_handle().check()
            return response
        except GatewayError as exc:
            if not isinstance(exc, StreamingModelError) and isinstance(response, ModelResponse):
                raise StreamingModelError(exc.code, usage=response.usage, finish_reason=response.finish_reason,
                    argument_diagnostic=exc.argument_diagnostic) from None
            raise
        finally:
            events.close()

    def complete_tool_stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        """Return a closed, verified model step; never expose raw stream deltas."""
        return self._complete_tool_stream(request, runtime)

    @staticmethod
    def _make_client(runtime: RuntimeSnapshot, remaining: float) -> OpenAI:
        timeout = httpx.Timeout(
            connect=min(runtime.connect_timeout_s, remaining),
            read=min(runtime.read_timeout_s, remaining),
            write=min(runtime.read_timeout_s, remaining),
            pool=min(runtime.connect_timeout_s, remaining),
        )
        key = None if runtime.auth_spec == AuthSpec.NONE else runtime.credential._for_adapter()
        return OpenAI(base_url=runtime.base_url, api_key=key or "local-no-key",
                      timeout=timeout, max_retries=0)

    @staticmethod
    def _check_secret(runtime: RuntimeSnapshot) -> None:
        if runtime.auth_spec == AuthSpec.REQUIRED_BEARER and not runtime.credential._for_adapter():
            raise GatewayError("SECRET_MISSING")

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RetryableGatewayError("TOTAL_TIMEOUT")
        return remaining

    @staticmethod
    def supports_ollama_qwen35_reasoning(profile_or_runtime: object) -> bool:
        """Identity is explicit; a Custom URL or model name never grants a capability."""
        return (getattr(profile_or_runtime, "provider_kind", None) == "local"
                and getattr(profile_or_runtime, "service_id", None) == "ollama"
                and getattr(profile_or_runtime, "model", None) == "qwen3.5:4b"
                and getattr(profile_or_runtime, "adapter_id", None)
                in ("openai_chat", "generic_openai_chat"))

    @staticmethod
    def supports_thinking_mapping(profile_or_runtime: object) -> bool:
        from .protocol_specs import protocol_for
        return protocol_for(profile_or_runtime).thinking_encoding is not None

    @staticmethod
    def fetch_ollama_thinking_metadata(runtime: RuntimeSnapshot) -> tuple[tuple[bool, ...], bool]:
        """Explicit local diagnostic; never called during ordinary analysis."""
        if not OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(runtime):
            raise GatewayError("METADATA_UNSUPPORTED")
        parsed = urlsplit(runtime.base_url)
        if parsed.path.rstrip("/") != "/v1":
            raise GatewayError("METADATA_UNSUPPORTED")
        show_url = urlunsplit((parsed.scheme, parsed.netloc, "/api/show", "", ""))
        try:
            timeout = httpx.Timeout(10.0, connect=min(runtime.connect_timeout_s, 5.0))
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.post(show_url, json={"model": runtime.model})
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectTimeout as exc:
            raise GatewayError("CONNECT_TIMEOUT") from exc
        except httpx.ReadTimeout as exc:
            raise GatewayError("READ_TIMEOUT") from exc
        except httpx.HTTPStatusError as exc:
            raise GatewayError(f"HTTP_{exc.response.status_code}") from exc
        except httpx.TransportError as exc:
            raise GatewayError("CONNECTION_ERROR") from exc
        except ValueError as exc:
            raise GatewayError("INVALID_RESPONSE") from exc
        thinking = payload.get("thinking") if isinstance(payload, dict) else None
        values = thinking.get("values") if isinstance(thinking, dict) else None
        default = thinking.get("default") if isinstance(thinking, dict) else None
        if (not isinstance(values, list) or not values
                or any(type(value) is not bool for value in values)
                or type(default) is not bool or default not in values):
            raise GatewayError("METADATA_UNAVAILABLE")
        return tuple(dict.fromkeys(values)), default

    @staticmethod
    def _kwargs(request: ModelRequest, runtime: RuntimeSnapshot, *, stream: bool, _assemble_tools=False) -> dict:
        from .model_gateway import validate_preset_response
        validate_tool_request(request, runtime, streaming=stream and not _assemble_tools)
        validate_preset_response(runtime, streaming=stream)
        generation, reasoning = effective_options(request, runtime)
        try:
            validate_options(generation, reasoning, runtime.capabilities, streaming=stream)
        except OptionValidationError as exc:
            raise GatewayError(exc.code, option=exc.option) from exc
        def encode_call(call):
            return {"id": call.id, "type": call.type,
                    "function": {"name": call.function_name, "arguments": call.arguments_json}}

        messages = []
        for message in request.messages:
            encoded = {"role": message.role, "content": message.content}
            if message.tool_calls:
                encoded["tool_calls"] = [encode_call(call) for call in message.tool_calls]
            if message.tool_call_id is not None:
                encoded["tool_call_id"] = message.tool_call_id
            messages.append(encoded)
        kwargs = {"model": runtime.model, "messages": messages}
        if request.tools:
            kwargs["tools"] = [{"type": tool.type, "function": {"name": tool.name,
                "description": tool.description, "parameters": tool.parameters_dict()}}
                for tool in request.tools]
        if request.tool_choice is not None:
            kwargs["tool_choice"] = request.tool_choice
        from .protocol_specs import ProtocolEncodingError
        try:
            kwargs.update(runtime.protocol_spec.encode(generation, reasoning, streaming=stream,
                include_usage=runtime.capabilities.streaming_usage == Support.SUPPORTED))
            limit = runtime.transport_output_token_limit
            ceiling = runtime.transport_output_token_ceiling
            if ceiling is not None and (type(ceiling) is not int or not 1<=ceiling<=4096 or limit is None):
                raise GatewayError('INVALID_TRANSPORT_OUTPUT_CEILING')
            if limit is not None:
                if stream:
                    if (not _assemble_tools or runtime.max_retries != 0
                            or type(limit) is not int or not 1 <= limit <= (ceiling or 512)):
                        raise GatewayError("INVALID_STREAMING_OUTPUT_BUDGET")
                elif (_assemble_tools or runtime.max_retries != 0
                        or type(limit) is not int or not 1 <= limit <= (ceiling or 1024)):
                    raise GatewayError("INVALID_NORMAL_OUTPUT_BUDGET")
                # Approved cost ceiling, encoded by ProtocolSpec, not Capability evidence.
                encoded = runtime.protocol_spec.encode(GenerationOptions(max_output_tokens=limit),
                    reasoning, streaming=stream, include_usage=False)
                token_field = runtime.protocol_spec.max_output_tokens_field
                if not token_field or encoded.get(token_field) != limit:
                    raise GatewayError("STREAMING_OUTPUT_BUDGET_UNAVAILABLE" if stream else "NORMAL_OUTPUT_BUDGET_UNAVAILABLE")
                kwargs[token_field] = min(kwargs.get(token_field, limit), limit)
        except ProtocolEncodingError as exc:
            raise GatewayError("OPTION_UNSUPPORTED", option=exc.option) from exc
        return kwargs

    @staticmethod
    def _map_error(exc: Exception) -> GatewayError:
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            # Inspect types only. Exception text can include a URL or request details.
            causes = []
            current = exc
            for _ in range(8):
                if current is None or current in causes:
                    break
                causes.append(current)
                current = current.__cause__ or current.__context__
            if any(isinstance(item, socket.gaierror) for item in causes):
                return RetryableGatewayError("DNS_ERROR")
            if any(isinstance(item, ssl.SSLError) for item in causes):
                return RetryableGatewayError("TLS_ERROR")
            if any(isinstance(item, httpx.ProxyError) for item in causes):
                return RetryableGatewayError("PROXY_ERROR")
            if any(isinstance(item, httpx.ConnectTimeout) for item in causes):
                return RetryableGatewayError("CONNECT_TIMEOUT")
            if any(isinstance(item, httpx.ReadTimeout) for item in causes):
                return RetryableGatewayError("READ_TIMEOUT")
            if isinstance(exc, APITimeoutError):
                return RetryableGatewayError("TIMEOUT")
            return RetryableGatewayError("CONNECTION_ERROR")
        if isinstance(exc, APIStatusError):
            code = f"HTTP_{exc.status_code}"
            return (RetryableGatewayError(code) if exc.status_code in RETRYABLE_STATUS
                    else GatewayError(code))
        return GatewayError("SDK_ERROR")

    @staticmethod
    def _is_explicit_streaming_unsupported(exc: APIStatusError) -> bool:
        """Recognize only clear provider refusals; generic HTTP errors stay inconclusive."""
        if exc.status_code not in {400, 405, 406, 422, 501}:
            return False
        body = getattr(exc, "body", None)
        if body is None:
            try:
                body = exc.response.json()
            except (AttributeError, ValueError, TypeError):
                return False

        messages = []
        if isinstance(body, str):
            messages.append(body)
        elif isinstance(body, dict):
            for container in (body, body.get("error")):
                if isinstance(container, dict):
                    for key in ("code", "type", "param", "message", "detail", "reason"):
                        value = container.get(key)
                        if isinstance(value, str):
                            messages.append(value[:2048])
                elif isinstance(container, str):
                    messages.append(container[:2048])
        text = re.sub(r"[_-]+", " ", " ".join(messages).casefold())
        return bool(re.search(
            r"\bstream(?:ing)?\b.{0,50}\b(?:is\s+)?(?:not supported|unsupported|not available|unavailable)\b"
            r"|\b(?:not supported|unsupported|not available|unavailable)\b.{0,50}\bstream(?:ing)?\b"
            r"|\b(?:does not|doesn't|cannot|can't)\s+support(?:s)?\b.{0,30}\bstream(?:ing)?\b",
            text))

    def list_models(self, runtime: RuntimeSnapshot, *, all_models: bool = False) -> list[dict]:
        """Explicit diagnostic only; return allowlisted public model metadata."""
        self._check_secret(runtime)
        client = None
        try:
            client = self._client_factory(runtime, runtime.total_timeout_s)
            response = client.models.list()
            result = []
            for item in response.data:
                model_id = getattr(item, "id", None)
                if not isinstance(model_id, str) or not model_id or len(model_id) > 128:
                    continue
                if not all_models and model_id != runtime.model:
                    continue
                extra = getattr(item, "model_extra", None) or {}
                result.append({
                    "id": model_id,
                    "context_length": extra.get("context_length"),
                    "max_output_tokens": extra.get("max_output_tokens"),
                    "reasoning_effort_levels": extra.get("reasoning_effort_levels"),
                })
                if len(result) >= 200:
                    break
            return result
        except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
            raise self._map_error(exc) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise GatewayError("INVALID_RESPONSE") from exc
        finally:
            if client is not None:
                client.close()

    @staticmethod
    def _is_explicit_tool_unsupported(exc: APIStatusError) -> bool:
        if exc.status_code not in {400, 422, 501}:
            return False
        body = getattr(exc, "body", None)
        error = body.get("error", body) if isinstance(body, dict) else None
        if not isinstance(error, dict):
            return False
        message = error.get("message")
        if not isinstance(message, str):
            return False
        # Never infer lack of support from auth, rate limits or malformed arguments.
        return bool(re.search(r"\b(?:tools|tool calling|function calling)\s+"
                              r"(?:(?:is|are)\s+)?(?:not supported|unsupported)"
                              r"(?:\s+(?:by|for|on)\b|[.!]|$)", message[:2048].casefold()))

    @staticmethod
    def _is_explicit_thinking_unsupported(exc: APIStatusError) -> bool:
        if exc.status_code not in {400, 405, 406, 422, 501}:
            return False
        body = getattr(exc, "body", None)
        if not isinstance(body, dict):
            return False
        error = body.get("error", body)
        if not isinstance(error, dict):
            return False
        message = " ".join(value[:2048] for key in ("message", "code", "param")
                           if isinstance((value := error.get(key)), str)).casefold()
        return bool(re.search(
            r"(?:thinking|reasoning|enable_thinking|reasoning_effort).{0,60}"
            r"(?:not supported|unsupported|unknown parameter|unrecognized)"
            r"|(?:not supported|unsupported|unknown parameter|unrecognized).{0,60}"
            r"(?:thinking|reasoning|enable_thinking|reasoning_effort)", message))

    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        kwargs = self._kwargs(request, runtime, stream=False)
        if current_handle() is not None:
            events = self._bridge(kwargs, runtime, stream=False)
            try:
                response = next(events)
                # Exhaust the bridge before parsing success: cleanup is part of completion.
                for _ in events:
                    pass
                return response
            finally:
                events.close()
        self._check_secret(runtime)
        deadline = time.monotonic() + runtime.total_timeout_s
        emitted = False
        for attempt in range(runtime.max_retries + 1):
            client = None
            try:
                client = self._client_factory(runtime, self._remaining(deadline))
                self.request_attempts += 1
                response = client.chat.completions.create(**kwargs)
                normalized = self._response(response)
                emitted = True
                return normalized
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                error = (RetryableGatewayError("TOTAL_TIMEOUT") if time.monotonic() >= deadline
                         else self._map_error(exc))
                if (kwargs.get("tools") and isinstance(exc, APIStatusError)
                        and self._is_explicit_tool_unsupported(exc)):
                    raise GatewayError("TOOL_UNSUPPORTED") from None
                if (isinstance(exc, APIStatusError) and
                        self._is_explicit_thinking_unsupported(exc)):
                    error = GatewayError("THINKING_UNSUPPORTED")
                if emitted or not isinstance(error, RetryableGatewayError) or attempt >= runtime.max_retries:
                    raise error from exc
            except RetryableGatewayError:
                if emitted or attempt >= runtime.max_retries:
                    raise
            except (IndexError, AttributeError, TypeError) as exc:
                raise GatewayError("INVALID_RESPONSE") from exc
            finally:
                if client is not None:
                    try:
                        client.close()
                    except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                        # Cleanup after an accepted call must not regenerate it.
                        raise self._map_error(exc) from None
        raise GatewayError("UNREACHABLE")

    def stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> Iterator[ModelEvent]:
        kwargs = self._kwargs(request, runtime, stream=True)
        if current_handle() is not None:
            yield from self._bridge(kwargs, runtime, stream=True)
            return
        self._check_secret(runtime)
        deadline = time.monotonic() + runtime.total_timeout_s
        for attempt in range(runtime.max_retries + 1):
            client = None
            sdk_stream = None
            emitted = False
            try:
                client = self._client_factory(runtime, self._remaining(deadline))
                self.request_attempts += 1
                sdk_stream = client.chat.completions.create(**kwargs)
                for chunk in sdk_stream:
                    self._remaining(deadline)
                    event = self._event(chunk)
                    if event.delta or event.reasoning_delta:
                        emitted = True
                    if event.delta or event.reasoning_delta or event.finish_reason or event.usage is not None:
                        yield event
                return
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                error = (RetryableGatewayError("TOTAL_TIMEOUT") if time.monotonic() >= deadline
                         else self._map_error(exc))
                if isinstance(exc, APIStatusError) and self._is_explicit_streaming_unsupported(exc):
                    error = GatewayError("STREAM_UNSUPPORTED")
                elif isinstance(exc, APIStatusError) and self._is_explicit_thinking_unsupported(exc):
                    error = GatewayError("THINKING_UNSUPPORTED")
                if emitted or not isinstance(error, RetryableGatewayError) or attempt >= runtime.max_retries:
                    raise error from exc
            except RetryableGatewayError:
                if emitted or attempt >= runtime.max_retries:
                    raise
            except (IndexError, AttributeError, TypeError) as exc:
                raise GatewayError("INVALID_STREAM_EVENT") from exc
            finally:
                if sdk_stream is not None and callable(getattr(sdk_stream, "close", None)):
                    sdk_stream.close()
                if client is not None:
                    client.close()
