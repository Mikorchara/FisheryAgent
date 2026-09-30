"""OpenAI-compatible Chat Completions transport; the SDK is isolated here."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
import socket
import ssl
import time
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .contracts import Usage, UsageSource
from .model_gateway import (GatewayError, ModelEvent, ModelRequest, ModelResponse,
                            RetryableGatewayError, RuntimeSnapshot, effective_options)
from .model_options import (OptionValidationError, ReasoningMode,
                            Support, validate_options)


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

    def __init__(self, client_factory: Callable[[RuntimeSnapshot, float], object] | None = None):
        self._client_factory = client_factory or self._make_client
        self.request_attempts = 0

    @staticmethod
    def _make_client(runtime: RuntimeSnapshot, remaining: float) -> OpenAI:
        timeout = httpx.Timeout(
            connect=min(runtime.connect_timeout_s, remaining),
            read=min(runtime.read_timeout_s, remaining),
            write=min(runtime.read_timeout_s, remaining),
            pool=min(runtime.connect_timeout_s, remaining),
        )
        return OpenAI(base_url=runtime.base_url, api_key=runtime.api_key or "local-no-key",
                      timeout=timeout, max_retries=0)

    @staticmethod
    def _check_secret(runtime: RuntimeSnapshot) -> None:
        if runtime.secret_env and not runtime.api_key:
            raise GatewayError("SECRET_UNAVAILABLE")

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RetryableGatewayError("TOTAL_TIMEOUT")
        return remaining

    @staticmethod
    def supports_ollama_qwen35_reasoning(profile_or_runtime: object) -> bool:
        """Recognize only the local Ollama qwen3.5:4b endpoint this control targets."""
        if (getattr(profile_or_runtime, "provider_kind", None) != "local"
                or getattr(profile_or_runtime, "model", None) != "qwen3.5:4b"
                or getattr(profile_or_runtime, "adapter_id", None)
                not in ("openai_chat", "generic_openai_chat")):
            return False
        service_id = getattr(profile_or_runtime, "service_id", None)
        if service_id == "ollama":
            return True
        if service_id != "custom":
            return False
        try:
            parsed = urlsplit(getattr(profile_or_runtime, "base_url", ""))
            return (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
                    and parsed.port == 11434 and parsed.path.rstrip("/") == "/v1")
        except ValueError:
            return False

    @staticmethod
    def _kwargs(request: ModelRequest, runtime: RuntimeSnapshot, *, stream: bool) -> dict:
        generation, reasoning = effective_options(request, runtime)
        ollama_qwen35 = OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(runtime)
        capabilities = runtime.capabilities
        if ollama_qwen35:
            # Ollama's OpenAI-compatible adapter documents reasoning_effort="none"
            # as the request-level OFF control. This exact adapter/model scope does
            # not grant or infer any other capability (especially Streaming).
            capabilities = replace(capabilities, reasoning_on=Support.SUPPORTED,
                                   reasoning_off=Support.SUPPORTED)
        try:
            validate_options(generation, reasoning, capabilities, streaming=stream)
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
            if ollama_qwen35:
                # Ollama maps recognized reasoning_effort aliases to its model's
                # thinking control; "none" explicitly requests no thinking.
                kwargs["reasoning_effort"] = "high" if reasoning.mode == ReasoningMode.ON else "none"
            elif runtime.service_id == "deepseek_api" and runtime.adapter_id == "openai_chat":
                kwargs["extra_body"] = {"thinking": {"type": "enabled" if reasoning.mode == ReasoningMode.ON
                                                     else "disabled"}}
            elif runtime.service_id == "dashscope" and runtime.adapter_id == "openai_chat":
                kwargs["extra_body"] = {"enable_thinking": reasoning.mode == ReasoningMode.ON}
            else:
                raise GatewayError("OPTION_UNSUPPORTED", option="reasoning")
        if reasoning.effort is not None:
            if runtime.service_id == "deepseek_api" and runtime.adapter_id == "openai_chat":
                kwargs["extra_body"]["reasoning_effort"] = reasoning.effort
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

    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        kwargs = self._kwargs(request, runtime, stream=False)
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
                return ModelResponse(
                    content, _usage(getattr(response, "usage", None)),
                    returned_model=getattr(response, "model", None),
                    reasoning_present=bool(getattr(response.choices[0].message,
                                                   "reasoning_content", None)),
                )
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                error = (RetryableGatewayError("TOTAL_TIMEOUT") if time.monotonic() >= deadline
                         else self._map_error(exc))
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
