"""OpenAI-compatible Chat Completions transport; the SDK is isolated here."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import socket
import ssl
import time
import re
import asyncio
import json
import queue
import threading
from urllib.parse import urlsplit, urlunsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from .contracts import Usage, UsageSource
from .model_gateway import (GatewayError, ModelEvent, ModelRequest, ModelResponse,
                            RetryableGatewayError, RuntimeSnapshot, effective_options)
from .model_options import (OptionValidationError, ReasoningMode,
                            Support, validate_options)
from .providers import AuthSpec
from .execution import current_handle, RequestHandle
from .manual import ManualRequest, ManualResponse


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


class OpenAICompatibleAdapter:
    """The gateway owns retries; the SDK performs one attempt at a time."""

    def __init__(self, client_factory: Callable[[RuntimeSnapshot, float], object] | None = None,
                 *, async_client_factory=None):
        self._client_factory = client_factory or self._make_client
        self._async_client_factory = async_client_factory or self._make_async_client
        self.request_attempts = 0

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
        message = response.choices[0].message
        if not isinstance(message.content, str):
            raise GatewayError("INVALID_RESPONSE")
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is not None and not isinstance(reasoning, str):
            raise GatewayError("INVALID_RESPONSE")
        return ModelResponse(message.content, _usage(getattr(response, "usage", None)),
            getattr(response, "model", None), bool(reasoning), reasoning)

    @staticmethod
    def _event(chunk):
        delta = chunk.choices[0].delta.content if chunk.choices else None
        reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None) if chunk.choices else None
        if any(value is not None and not isinstance(value, str) for value in (delta, reasoning)):
            raise GatewayError("INVALID_STREAM_EVENT")
        usage = _usage(getattr(chunk, "usage", None))
        return ModelEvent(delta or "", usage if usage.source != UsageSource.UNAVAILABLE else None, reasoning)

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

    def _bridge(self, kwargs, runtime, *, stream, manual=False):
        """A request-owned loop/thread, bounded queue and actual cancellable SDK Task."""
        self._check_secret(runtime)
        handle = current_handle() or RequestHandle()
        handle.check()
        if not handle._claimed:
            handle.start()
        handle.io_closed = True
        inbox = queue.Queue(maxsize=32)
        stopped = threading.Event()

        async def put(item):
            while not stopped.is_set():
                try:
                    inbox.put_nowait(item)
                    return
                except queue.Full:
                    await asyncio.sleep(0.01)
            raise asyncio.CancelledError()

        async def operation():
            emitted = False
            deadline = time.monotonic() + runtime.total_timeout_s
            attempts = 0 if manual else runtime.max_retries
            async with asyncio.timeout(runtime.total_timeout_s):
                for attempt in range(attempts + 1):
                    handle.check()
                    client = self._async_client_factory(runtime, self._remaining(deadline))
                    handle.io_closed = False
                    sdk_stream = None
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
                                event = self._manual_response(chunk, runtime) if manual else self._event(chunk)
                                emitted = emitted or manual or bool(event.delta or event.reasoning_delta)
                                await put(("item", event))
                        else:
                            handle.check()
                            await put(("item", self._manual_response(response, runtime) if manual else self._response(response)))
                        return
                    except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                        handle.check()
                        error = self._map_error(exc)
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
                await put(("error", GatewayError("USER_CANCELLED")))
            except TimeoutError:
                await put(("error", GatewayError("TOTAL_TIMEOUT")))
            except GatewayError as exc:
                await put(("error", exc))
            except Exception:
                await put(("error", GatewayError("SDK_ERROR")))
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
        consumer_deadline = time.monotonic() + runtime.total_timeout_s + 5
        ended = False
        try:
            while True:
                try:
                    kind, item = inbox.get(timeout=0.2)
                except queue.Empty:
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
        finally:
            if not ended:
                handle.cancel()
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
        if OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(profile_or_runtime):
            return True
        if getattr(profile_or_runtime, "adapter_id", None) != "openai_chat":
            return False
        models = {"dashscope": {"qwen-plus", "qwen3.8-flash", "qwen3.8-omni-flash"},
                  "deepseek_api": {"deepseek-flash"}}
        return getattr(profile_or_runtime, "model", None) in models.get(
            getattr(profile_or_runtime, "service_id", None), set())

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
    def _kwargs(request: ModelRequest, runtime: RuntimeSnapshot, *, stream: bool) -> dict:
        generation, reasoning = effective_options(request, runtime)
        ollama_qwen35 = OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(runtime)
        try:
            validate_options(generation, reasoning, runtime.capabilities, streaming=stream)
        except OptionValidationError as exc:
            raise GatewayError(exc.code, option=exc.option) from exc
        kwargs = {"model": runtime.model,
                  "messages": [{"role": message.role, "content": message.content}
                               for message in request.messages]}
        if stream:
            kwargs["stream"] = True
            if runtime.capabilities.streaming_usage == Support.SUPPORTED:
                kwargs["stream_options"] = {"include_usage": True}
        if generation.max_output_tokens is not None:
            kwargs[runtime.capabilities.max_tokens_field] = generation.max_output_tokens
        if generation.temperature is not None:
            kwargs["temperature"] = generation.temperature
        if generation.top_p is not None:
            kwargs["top_p"] = generation.top_p
        if reasoning.mode != ReasoningMode.AUTO:
            if not OpenAICompatibleAdapter.supports_thinking_mapping(runtime):
                raise GatewayError("OPTION_UNSUPPORTED", option="reasoning")
            if ollama_qwen35:
                # Ollama maps recognized reasoning_effort aliases to its model's
                # thinking control; "none" explicitly requests no thinking.
                kwargs["reasoning_effort"] = "high" if reasoning.mode == ReasoningMode.ON else "none"
            elif runtime.service_id == "deepseek_api" and runtime.adapter_id == "openai_chat":
                kwargs["extra_body"] = {"thinking": {"type": "enabled" if reasoning.mode == ReasoningMode.ON
                                                     else "disabled"}}
            elif runtime.service_id == "dashscope" and runtime.adapter_id == "openai_chat":
                if runtime.model == "qwen3.8-omni-flash":
                    # This exact model uses effort as its protocol-level switch.
                    kwargs["reasoning_effort"] = "xhigh" if reasoning.mode == ReasoningMode.ON else "none"
                else:
                    kwargs["extra_body"] = {"enable_thinking": reasoning.mode == ReasoningMode.ON}
            else:
                raise GatewayError("OPTION_UNSUPPORTED", option="reasoning")
        if reasoning.effort is not None:
            if runtime.service_id in ("deepseek_api", "dashscope") and runtime.adapter_id == "openai_chat":
                kwargs["reasoning_effort"] = reasoning.effort
            else:
                raise GatewayError("OPTION_UNSUPPORTED", option="reasoning.effort")
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
        for attempt in range(runtime.max_retries + 1):
            client = None
            try:
                client = self._client_factory(runtime, self._remaining(deadline))
                self.request_attempts += 1
                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                if not isinstance(content, str):
                    raise GatewayError("INVALID_RESPONSE")
                reasoning_content = getattr(response.choices[0].message, "reasoning_content", None)
                if reasoning_content is not None and not isinstance(reasoning_content, str):
                    raise GatewayError("INVALID_RESPONSE")
                return ModelResponse(
                    content, _usage(getattr(response, "usage", None)),
                    returned_model=getattr(response, "model", None),
                    reasoning_present=bool(reasoning_content),
                    reasoning_content=reasoning_content,
                )
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                error = (RetryableGatewayError("TOTAL_TIMEOUT") if time.monotonic() >= deadline
                         else self._map_error(exc))
                if (isinstance(exc, APIStatusError) and
                        self._is_explicit_thinking_unsupported(exc)):
                    error = GatewayError("THINKING_UNSUPPORTED")
                if not isinstance(error, RetryableGatewayError) or attempt >= runtime.max_retries:
                    raise error from exc
            except RetryableGatewayError:
                if attempt >= runtime.max_retries:
                    raise
            except (IndexError, AttributeError, TypeError) as exc:
                raise GatewayError("INVALID_RESPONSE") from exc
            finally:
                if client is not None:
                    client.close()
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
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    reasoning_delta = (getattr(chunk.choices[0].delta, "reasoning_content", None)
                                       if chunk.choices else None)
                    if ((delta is not None and not isinstance(delta, str)) or
                            (reasoning_delta is not None and not isinstance(reasoning_delta, str))):
                        raise GatewayError("INVALID_STREAM_EVENT")
                    usage = _usage(getattr(chunk, "usage", None))
                    if delta or reasoning_delta:
                        emitted = True
                    if delta or reasoning_delta or usage.source != UsageSource.UNAVAILABLE:
                        yield ModelEvent(delta=delta or "", usage=usage if usage.source != UsageSource.UNAVAILABLE
                                         else None, reasoning_delta=reasoning_delta)
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
