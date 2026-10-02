"""Versioned request encoding only; a protocol never grants model support."""

from dataclasses import dataclass, replace

from .model_options import GenerationOptions, ReasoningMode, ReasoningOptions
from .providers import PROVIDERS


class ProtocolEncodingError(Exception):
    def __init__(self, option: str):
        super().__init__("OPTION_UNSUPPORTED")
        self.option = option


@dataclass(frozen=True)
class ProtocolSpec:
    spec_id: str
    version: str = "1"
    max_output_tokens_field: str = "max_tokens"
    thinking_encoding: str | None = None
    effort_field: str | None = None
    stream_field: str = "stream"
    usage_options_field: str = "stream_options"

    def encode(self, generation: GenerationOptions, reasoning: ReasoningOptions,
               *, streaming: bool, include_usage: bool) -> dict:
        body = {}
        if streaming:
            body[self.stream_field] = True
            if include_usage:
                body[self.usage_options_field] = {"include_usage": True}
        if generation.max_output_tokens is not None:
            body[self.max_output_tokens_field] = generation.max_output_tokens
        for name in ("temperature", "top_p"):
            value = getattr(generation, name)
            if value is not None:
                body[name] = value
        if reasoning.mode != ReasoningMode.AUTO:
            enabled = reasoning.mode == ReasoningMode.ON
            if self.thinking_encoding == "enable_thinking":
                body["extra_body"] = {"enable_thinking": enabled}
            elif self.thinking_encoding == "thinking_type":
                body["extra_body"] = {"thinking": {"type": "enabled" if enabled else "disabled"}}
            elif self.thinking_encoding in ("effort_high_none", "effort_xhigh_none"):
                on_value = "high" if self.thinking_encoding == "effort_high_none" else "xhigh"
                body["reasoning_effort"] = on_value if enabled else "none"
            else:
                raise ProtocolEncodingError("reasoning")
        if reasoning.effort is not None:
            if self.effort_field is None:
                raise ProtocolEncodingError("reasoning.effort")
            body[self.effort_field] = reasoning.effort
        return body


def protocol_for(connection: object) -> ProtocolSpec:
    """Select encoding by declared service/adapter, never by URL or model family.

    The deprecated capability token-field is accepted only as a legacy encoding
    override. It supplies no support evidence. Exact-model exceptions preserve
    the already implemented wire protocol.
    """
    service = getattr(connection, "service_id", "custom")
    adapter = getattr(connection, "adapter_id", "generic_openai_chat")
    model = getattr(connection, "model", "")
    spec_id = PROVIDERS.for_service(service).protocol_spec_id
    encoding = effort = None
    if adapter == "openai_chat":
        if service == "dashscope":
            effort = "reasoning_effort"
            encoding = "enable_thinking"
            if model == "qwen3.8-omni-flash":
                encoding = "effort_xhigh_none"
        elif service == "deepseek_api":
            effort = "reasoning_effort"
            encoding = "thinking_type"
    if (service == "ollama" and model == "qwen3.5:4b"
            and getattr(connection, "provider_kind", None) == "local"
            and adapter in ("openai_chat", "generic_openai_chat")):
        encoding = "effort_high_none"
    spec = ProtocolSpec(spec_id, thinking_encoding=encoding, effort_field=effort)
    legacy_field = getattr(getattr(connection, "capabilities", None), "max_tokens_field", None)
    return replace(spec, max_output_tokens_field=legacy_field) if legacy_field else spec
