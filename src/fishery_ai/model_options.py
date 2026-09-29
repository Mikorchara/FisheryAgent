"""Small, provider-neutral option and exact-model capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class Support(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProfileStatus(str, Enum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    CUSTOM = "custom"


class ReasoningMode(str, Enum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class GenerationOptions:
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None


@dataclass(frozen=True)
class ReasoningOptions:
    mode: ReasoningMode = ReasoningMode.AUTO
    effort: str | None = None


@dataclass(frozen=True)
class ModelCapabilities:
    streaming: Support = Support.UNKNOWN
    temperature: Support = Support.UNKNOWN
    top_p: Support = Support.UNKNOWN
    max_output_tokens: Support = Support.UNKNOWN
    reasoning: Support = Support.UNKNOWN
    reasoning_toggle: Support = Support.UNKNOWN
    reasoning_effort: Support = Support.UNKNOWN
    structured_output: Support = Support.UNKNOWN
    tool_calling: Support = Support.UNKNOWN
    streaming_usage: Support = Support.UNKNOWN
    max_tokens_field: str | None = None
    effort_values: tuple[str, ...] = ()
    reasoning_temperature_conflict: bool = False
    source: str = "unknown"
    model_id: str | None = None
    base_url: str | None = None
    verified_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("streaming", "temperature", "top_p", "max_output_tokens", "reasoning",
                     "reasoning_toggle", "reasoning_effort", "structured_output", "tool_calling",
                     "streaming_usage"):
            value = getattr(self, name)
            if isinstance(value, bool):  # Existing profile JSON remains readable.
                value = Support.SUPPORTED if value else Support.UNSUPPORTED
            object.__setattr__(self, name, Support(value))
        object.__setattr__(self, "effort_values", tuple(self.effort_values))
        if self.source not in ("user_verified", "official_docs", "experimental", "unknown"):
            raise ValueError("invalid capability source")
        if self.reasoning_effort == Support.SUPPORTED and not self.effort_values:
            raise ValueError("supported reasoning effort requires allowed values")
        if self.reasoning_effort != Support.SUPPORTED and self.effort_values:
            raise ValueError("effort values require supported reasoning effort")
        if self.max_tokens_field not in (None, "max_tokens", "max_completion_tokens"):
            raise ValueError("invalid max_tokens_field")
        if self.max_output_tokens == Support.SUPPORTED and self.max_tokens_field is None:
            raise ValueError("supported output limit requires a verified API field")


class OptionValidationError(Exception):
    def __init__(self, code: str, option: str):
        super().__init__(code)
        self.code = code
        self.option = option


def _require(name: str, support: Support) -> None:
    if support == Support.UNKNOWN:
        raise OptionValidationError("OPTION_UNKNOWN", name)
    if support == Support.UNSUPPORTED:
        raise OptionValidationError("OPTION_UNSUPPORTED", name)


def validate_options(generation: GenerationOptions, reasoning: ReasoningOptions,
                     capabilities: ModelCapabilities, *, streaming: bool = False
                     ) -> None:
    """Validate only explicit options; AUTO and None send no advanced control."""
    if not isinstance(reasoning.mode, ReasoningMode):
        raise OptionValidationError("INVALID_OPTION_VALUE", "reasoning.mode")
    if generation.max_output_tokens is not None:
        value = generation.max_output_tokens
        if type(value) is not int or value <= 0:
            raise OptionValidationError("INVALID_OPTION_VALUE", "max_output_tokens")
        _require("max_output_tokens", capabilities.max_output_tokens)
    if generation.temperature is not None:
        value = generation.temperature
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 2):
            raise OptionValidationError("INVALID_OPTION_VALUE", "temperature")
        _require("temperature", capabilities.temperature)
    if generation.top_p is not None:
        value = generation.top_p
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 < value <= 1):
            raise OptionValidationError("INVALID_OPTION_VALUE", "top_p")
        _require("top_p", capabilities.top_p)
    if reasoning.mode != ReasoningMode.AUTO:
        _require("reasoning", capabilities.reasoning)
        _require("reasoning_toggle", capabilities.reasoning_toggle)
    if reasoning.effort is not None:
        if reasoning.mode != ReasoningMode.ON:
            raise OptionValidationError("OPTION_CONFLICT", "reasoning.effort")
        _require("reasoning_effort", capabilities.reasoning_effort)
        if reasoning.effort not in capabilities.effort_values:
            raise OptionValidationError("INVALID_OPTION_VALUE", "reasoning.effort")
    if (reasoning.mode == ReasoningMode.ON and generation.temperature is not None
            and capabilities.reasoning_temperature_conflict):
        raise OptionValidationError("OPTION_CONFLICT", "reasoning+temperature")
    if streaming:
        _require("streaming", capabilities.streaming)
