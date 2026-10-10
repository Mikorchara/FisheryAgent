"""Run-local observation and output budget; ordinary Adapter behavior is unchanged.

No SDK imports here: encoding, transport, retry and normalization are inherited.
Raw responses are inspected transiently and never retained or serialized.
"""

import json

from .model_gateway import GatewayError, ModelToolCall
from .model_options import GenerationOptions
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .tools.registry import SEARCH_FISHERY_KNOWLEDGE


FINISH_REASONS = {"stop", "length", "tool_calls", "function_call", "content_filter"}


def call_summary(call, registry, exposed_tools):
    """Validate with the Registry-owned contract without invoking the handler."""
    name = getattr(call, "function_name", None)
    arguments = getattr(call, "arguments_json", None)
    known = name in exposed_tools
    row = {"function_name": name if known else "unknown_tool",
           "call_id_valid": False, "arguments_present": isinstance(arguments, str),
           "arguments_valid": False}
    if name == SEARCH_FISHERY_KNOWLEDGE and known:
        row.update(query_present=False, query_valid=False)
    try:
        ModelToolCall(call.id, name, arguments, call.type)
        row["call_id_valid"] = True
        if not known or len(arguments.encode("utf-8")) > 4096:
            return row
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict):
            return row  # Match the Executor's JSON-object boundary, including [].
        if name == SEARCH_FISHERY_KNOWLEDGE:
            row["query_present"] = "query" in parsed
        registry.lookup(name).bind(parsed)  # Bind/validate only; never call invoke().
        row["arguments_valid"] = True
        if name == SEARCH_FISHERY_KNOWLEDGE:
            row["query_valid"] = True
        else:
            row["arguments"] = {}  # Parameterless tools; no arbitrary arguments copied.
    except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError):
        pass
    return row


def response_summary(response, model, registry, exposed_tools):
    returned = getattr(response, "returned_model", None)
    calls = getattr(response, "tool_calls", ())
    return {"finish_reason": response.finish_reason if response.finish_reason in FINISH_REASONS else None,
            "provider_model_matches": returned == model if returned is not None else None,
            "tool_calls_present": bool(calls), "tool_call_count": len(calls),
            "calls": [call_summary(call, registry, exposed_tools) for call in calls[:8]],
            "calls_summary_truncated": len(calls) > 8}


class QualificationAdapter(OpenAICompatibleAdapter):
    """Scoped to one qualification, not installed in Web or the ordinary Gateway."""

    def __init__(self, model, registry, exposed_tools, max_output_tokens, **factories):
        super().__init__(**factories)
        self.model, self.registry = model, registry
        self.exposed_tools = tuple(exposed_tools)
        self.max_output_tokens = max_output_tokens
        self.observations = []  # Only finite safe projections, never raw responses.

    def _kwargs(self, request, runtime, *, stream):
        if stream or runtime.max_retries != 0:
            raise GatewayError("QUALIFICATION_INVALID_TRANSPORT")
        kwargs = super()._kwargs(request, runtime, stream=False)
        # Mandatory cost budget is transport-scoped; do not manufacture model
        # capability evidence merely to send a maintainer-approved finite limit.
        encoded = runtime.protocol_spec.encode(GenerationOptions(max_output_tokens=self.max_output_tokens),
                                               runtime.default_reasoning, streaming=False, include_usage=False)
        field = runtime.protocol_spec.max_output_tokens_field
        if field is None or encoded.get(field) != self.max_output_tokens:
            raise GatewayError("QUALIFICATION_TOKEN_BUDGET_UNAVAILABLE")
        kwargs[field] = self.max_output_tokens
        return kwargs

    def _response(self, response):
        # This hook runs at the same boundary for inherited sync/AsyncOpenAI I/O.
        row = {"available": False, "normalized_call_consistent": None}
        raw_signatures = None
        try:
            choice = response.choices[0]
            raw_calls = getattr(choice.message, "tool_calls", None)
            if raw_calls is None or isinstance(raw_calls, (list, tuple)):
                raw_calls = raw_calls or ()
                from types import SimpleNamespace
                calls = tuple(SimpleNamespace(id=getattr(call, "id", None), type=getattr(call, "type", None),
                    function_name=getattr(getattr(call, "function", None), "name", None),
                    arguments_json=getattr(getattr(call, "function", None), "arguments", None)) for call in raw_calls)
                projection = SimpleNamespace(returned_model=getattr(response, "model", None),
                    finish_reason=getattr(choice, "finish_reason", None), tool_calls=calls)
                row.update(response_summary(projection, self.model, self.registry, self.exposed_tools), available=True)
                # Exact ID/arguments comparison stays transient, not in the report.
                raw_signatures = tuple((call.id, call.type, call.function_name, call.arguments_json) for call in calls)
        except (AttributeError, TypeError, ValueError, RecursionError):
            pass  # Normalization remains authoritative for malformed SDK responses.
        self.observations.append(row)
        normalized = super()._response(response)
        if raw_signatures is not None:
            row["normalized_call_consistent"] = raw_signatures == tuple(
                (call.id, call.type, call.function_name, call.arguments_json) for call in normalized.tool_calls)
            row["normalized_metadata_consistent"] = (
                row["finish_reason"] == (normalized.finish_reason if normalized.finish_reason in FINISH_REASONS else None)
                and row["provider_model_matches"] == (
                    normalized.returned_model == self.model if normalized.returned_model is not None else None))
            if not row["normalized_call_consistent"] or not row["normalized_metadata_consistent"]:
                raise GatewayError("QUALIFICATION_NORMALIZATION_MISMATCH")
        return normalized
