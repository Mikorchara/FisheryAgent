"""Finite SDK-level statistics only; no chunks, text or arguments are retained here.

The SDK hides SSE [DONE]. Exhaustion/finish/cleanup are separate observations,
not proof that a raw [DONE] marker was present or remote computation stopped.
"""

from dataclasses import asdict
from types import SimpleNamespace

from apps.ai_backend.openai_compatible_adapter import _ToolCallStreamAssembler
from .qualification_adapter import response_summary


def empty_observation():
    return {"available": False, "chunk_count": 0, "tool_delta_chunks": 0,
            "argument_delta_chunks": 0, "content_delta_chunks": 0,
            "reasoning_delta_chunks": 0, "usage_chunks": 0,
            "sdk_iterator_exhausted": False, "sdk_stream_closed": False,
            "sdk_client_closed": False, "assembly_complete": False,
            "normalized_call_consistent": None, "normalized_metadata_consistent": None,
            "done_marker": "NOT_OBSERVABLE_BY_SDK"}


def stream_response_summary(response, model, registry, exposed_tools):
    summary = response_summary(response, model, registry, exposed_tools)
    for call in summary["calls"]:
        call.pop("arguments", None)  # Even parameterless JSON is not copied into Streaming reports.
    return summary


class ObservedAssembler(_ToolCallStreamAssembler):
    """Same validator and bounds as production, with a finite safe projection."""
    def __init__(self, definitions, row, model, registry, exposed_tools):
        super().__init__(definitions)
        self.row, self.model, self.registry, self.exposed_tools = row, model, registry, exposed_tools

    def push(self, chunk):
        # Record presence/counts before validation, even if this chunk is rejected.
        # No per-chunk list, model text, id or fragment content is copied.
        self.row["available"] = True
        self.row["chunk_count"] = min(self.row["chunk_count"] + 1, self.MAX_CHUNKS + 1)
        choices = getattr(chunk, "choices", None)
        if isinstance(choices, (list, tuple)) and choices:
            delta = getattr(choices[0], "delta", None)
            calls = getattr(delta, "tool_calls", None)
            if isinstance(calls, (list, tuple)) and calls:
                self.row["tool_delta_chunks"] += 1
                self.row["tool_calls_present"] = True
                self.row["multiple_call_delta_seen"] = self.row.get("multiple_call_delta_seen", False) or len(calls) > 1 or any(
                    getattr(call, "index", None) != 0 for call in calls[:2])
                if any(getattr(getattr(call, "function", None), "arguments", None) is not None for call in calls[:2]):
                    self.row["argument_delta_chunks"] += 1
            for key, field in (("content_delta_chunks", "content"), ("reasoning_delta_chunks", "reasoning_content")):
                if getattr(delta, field, None):
                    self.row[key] += 1
        if getattr(chunk, "usage", None) is not None:
            self.row["usage_chunks"] += 1
        try:
            super().push(chunk)
        finally:
            self.row.update(buffer_bytes=self._bytes, argument_bytes=self._argument_bytes,
                            finish_reason=self.observed_finish_reason,
                            provider_model_matches=self._model == self.model if self._model else None,
                            usage=asdict(self.observed_usage))

    def finish(self):
        # Independently project the collected SDK fields before normalization;
        # exact IDs/JSON are compared transiently and never placed in the row.
        calls = (SimpleNamespace(id=self._id, type=self._type, function_name=self._name,
                                 arguments_json="".join(self._arguments)),) if self._call_seen else ()
        raw = SimpleNamespace(returned_model=self._model, finish_reason=self._finish_reason, tool_calls=calls)
        self.row.update(stream_response_summary(raw, self.model, self.registry, self.exposed_tools))
        response = super().finish()
        self.row.update(assembly_complete=True,
            normalized_call_consistent=tuple((c.id, c.type, c.function_name, c.arguments_json) for c in calls)
                == tuple((c.id, c.type, c.function_name, c.arguments_json) for c in response.tool_calls),
            normalized_metadata_consistent=self._finish_reason == response.finish_reason
                and self._model == response.returned_model)
        return response


class ObservedStream:
    def __init__(self, stream, row):
        self.stream, self.row = stream, row

    def __aiter__(self):
        return self._events()

    async def _events(self):
        async for chunk in self.stream:
            yield chunk
        self.row["sdk_iterator_exhausted"] = True

    async def close(self):
        await self.stream.close()
        self.row["sdk_stream_closed"] = True  # Only successful cleanup is certified.


class ObservedClient:
    def __init__(self, client, row):
        self.client, self.row = client, row
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        return ObservedStream(await self.client.chat.completions.create(**kwargs), self.row)

    async def close(self):
        await self.client.close()
        self.row["sdk_client_closed"] = True
