"""Small, provider-neutral option and exact-model capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from urllib.parse import urlsplit, urlunsplit


def normalize_base_url(value: str) -> str:
    """Canonicalize URL scheme/host and trailing path slashes for identity matching."""
    parsed = urlsplit(value)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, parsed.fragment))


class Support(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CapabilitySource(str, Enum):
    MODEL_METADATA = "MODEL_METADATA"
    OFFICIAL_DOCS = "OFFICIAL_DOCS"
    USER_VERIFIED = "USER_VERIFIED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: str | CapabilitySource) -> CapabilitySource:
        if isinstance(value, cls):
            return value
        legacy = {"model_metadata": cls.MODEL_METADATA,
                  "official_docs": cls.OFFICIAL_DOCS, "user_verified": cls.USER_VERIFIED,
                  "unknown": cls.UNKNOWN, "experimental": cls.UNKNOWN}
        return legacy[value] if value in legacy else cls(value)


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
    reasoning_on: Support = Support.UNKNOWN
    reasoning_off: Support = Support.UNKNOWN
    reasoning_effort: Support = Support.UNKNOWN
    structured_output: Support = Support.UNKNOWN
    tool_calling: Support = Support.UNKNOWN
    streaming_usage: Support = Support.UNKNOWN
    max_tokens_field: str | None = None
    effort_values: tuple[str, ...] = ()
    reasoning_temperature_conflict: bool = False
    source: CapabilitySource = CapabilitySource.UNKNOWN
    model_id: str | None = None
    base_url: str | None = None
    adapter_id: str | None = None
    thinking_default: bool | None = None
    verified_at: str | None = None
    service_id: str | None = None
    evidence: tuple[tuple[str, CapabilitySource], ...] = ()

    def __post_init__(self) -> None:
        if self.base_url is not None:
            object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        for name in ("streaming", "temperature", "top_p", "max_output_tokens", "reasoning_on",
                     "reasoning_off", "reasoning_effort", "structured_output", "tool_calling",
                     "streaming_usage"):
            value = getattr(self, name)
            if isinstance(value, bool):  # Existing profile JSON remains readable.
                value = Support.SUPPORTED if value else Support.UNSUPPORTED
            object.__setattr__(self, name, Support(value))
        object.__setattr__(self, "effort_values", tuple(self.effort_values))
        object.__setattr__(self, "source", CapabilitySource.parse(self.source))
        if self.thinking_default is not None and type(self.thinking_default) is not bool:
            raise ValueError("thinking_default must be a boolean or None")
        evidence = self.evidence.items() if isinstance(self.evidence, dict) else self.evidence
        normalized = tuple(sorted((name, CapabilitySource.parse(source))
                                  for name, source in evidence))
        allowed = {"streaming", "temperature", "top_p", "max_output_tokens", "reasoning_on",
                   "reasoning_off", "reasoning_effort", "structured_output", "tool_calling",
                   "streaming_usage"}
        if any(name not in allowed for name, _ in normalized):
            raise ValueError("invalid capability evidence field")
        object.__setattr__(self, "evidence", normalized)
        if self.reasoning_effort == Support.SUPPORTED and not self.effort_values:
            raise ValueError("supported reasoning effort requires allowed values")
        if self.reasoning_effort != Support.SUPPORTED and self.effort_values:
            raise ValueError("effort values require supported reasoning effort")
        if self.max_tokens_field not in (None, "max_tokens", "max_completion_tokens"):
            raise ValueError("invalid max_tokens_field")
        if self.max_output_tokens == Support.SUPPORTED and self.max_tokens_field is None:
            raise ValueError("supported output limit requires a verified API field")

    def source_for(self, capability: str) -> CapabilitySource:
        return dict(self.evidence).get(capability, self.source)


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
    if reasoning.effort is not None and reasoning.mode != ReasoningMode.ON:
        raise OptionValidationError("OPTION_CONFLICT", "reasoning.effort")
    if reasoning.mode == ReasoningMode.ON:
        _require("reasoning_on", capabilities.reasoning_on)
    elif reasoning.mode == ReasoningMode.OFF:
        _require("reasoning_off", capabilities.reasoning_off)
    if reasoning.effort is not None:
        _require("reasoning_effort", capabilities.reasoning_effort)
        if reasoning.effort not in capabilities.effort_values:
            raise OptionValidationError("INVALID_OPTION_VALUE", "reasoning.effort")
    if (reasoning.mode == ReasoningMode.ON and generation.temperature is not None
            and capabilities.reasoning_temperature_conflict):
        raise OptionValidationError("OPTION_CONFLICT", "reasoning+temperature")
    if streaming:
        _require("streaming", capabilities.streaming)
