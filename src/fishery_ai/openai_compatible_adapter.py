"""OpenAI-compatible Chat Completions transport; the SDK is isolated here."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import time

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .contracts import Usage
from .model_gateway import (GatewayError, ModelEvent, ModelRequest, ModelResponse,
                            RetryableGatewayError, RuntimeSnapshot)


RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _usage(value: object) -> Usage | None:
    if value is None:
        return None
    return Usage(getattr(value, "prompt_tokens", None),
                 getattr(value, "completion_tokens", None),
                 getattr(value, "total_tokens", None))


class OpenAICompatibleAdapter:
    """The gateway owns retries; the SDK performs one attempt at a time."""

    def __init__(self, client_factory: Callable[[RuntimeSnapshot, float], object] | None = None):
        self._client_factory = client_factory or self._make_client

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
    def _kwargs(request: ModelRequest, runtime: RuntimeSnapshot, *, stream: bool) -> dict:
        return {"model": runtime.model,
                "messages": [{"role": message.role, "content": message.content}
                             for message in request.messages],
                "max_tokens": request.max_tokens, "stream": stream}

    @staticmethod
    def _map_error(exc: Exception) -> GatewayError:
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return RetryableGatewayError("CONNECTION_OR_TIMEOUT")
        if isinstance(exc, APIStatusError):
            code = f"HTTP_{exc.status_code}"
            return (RetryableGatewayError(code) if exc.status_code in RETRYABLE_STATUS
                    else GatewayError(code))
        return GatewayError("SDK_ERROR")

    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        self._check_secret(runtime)
        deadline = time.monotonic() + runtime.total_timeout_s
        for attempt in range(runtime.max_retries + 1):
            client = None
            try:
                client = self._client_factory(runtime, self._remaining(deadline))
                response = client.chat.completions.create(**self._kwargs(request, runtime, stream=False))
                content = response.choices[0].message.content
                if not isinstance(content, str):
                    raise GatewayError("INVALID_RESPONSE")
                return ModelResponse(content, _usage(response.usage))
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                error = self._map_error(exc)
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
        if not runtime.capabilities.streaming:
            raise GatewayError("STREAMING_UNSUPPORTED")
        self._check_secret(runtime)
        deadline = time.monotonic() + runtime.total_timeout_s
        for attempt in range(runtime.max_retries + 1):
            client = None
            sdk_stream = None
            emitted = False
            try:
                client = self._client_factory(runtime, self._remaining(deadline))
                sdk_stream = client.chat.completions.create(**self._kwargs(request, runtime, stream=True))
                for chunk in sdk_stream:
                    self._remaining(deadline)
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    usage = _usage(chunk.usage)
                    if delta:
                        emitted = True
                    if delta or usage:
                        yield ModelEvent(delta=delta or "", usage=usage)
                return
            except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                error = self._map_error(exc)
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
