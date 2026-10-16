"""Generic execution/usage contracts; no domain observations or Analysis types."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from .model_options import GenerationOptions, ReasoningOptions

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value


def parse_time(value: str) -> datetime:
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


class Mode(str, Enum):
    CHAT = "chat"
    ADVICE = "advice"


class Status(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UsageSource(str, Enum):
    PROVIDER = "provider"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    source: UsageSource = UsageSource.UNAVAILABLE

    def __post_init__(self) -> None:
        values = (self.input_tokens, self.output_tokens, self.total_tokens,
                  self.reasoning_tokens, self.cached_input_tokens)
        if any(value is not None and (type(value) is not int or value < 0) for value in values):
            raise ValueError("token counts must be nonnegative integers")
        if not isinstance(self.source, UsageSource):
            raise ValueError("source must be a UsageSource")
        if self.source == UsageSource.UNAVAILABLE and any(value is not None for value in values):
            raise ValueError("unavailable usage cannot contain token counts")
        if self.source != UsageSource.UNAVAILABLE and all(value is None for value in values):
            raise ValueError("available usage requires at least one token count")


@dataclass(frozen=True)
class SessionUsage:
    request_count: int
    reported_count: int
    usage: Usage

    @property
    def complete(self) -> bool:
        return self.request_count > 0 and self.request_count == self.reported_count


class UsageAccumulator:
    """In-memory validation-session totals; missing fields remain unknown."""

    def __init__(self) -> None:
        self._items: list[Usage] = []

    def add(self, usage: Usage | None) -> None:
        self._items.append(usage or Usage())

    def snapshot(self) -> SessionUsage:
        reported = [item for item in self._items if item.source == UsageSource.PROVIDER]
        if not reported:
            return SessionUsage(len(self._items), 0, Usage())
        if len(reported) != len(self._items):
            return SessionUsage(len(self._items), len(reported), Usage())

        def total(field_name: str) -> int | None:
            values = [getattr(item, field_name) for item in reported]
            return sum(values) if len(reported) == len(self._items) and all(
                value is not None for value in values) else None

        return SessionUsage(len(self._items), len(reported), Usage(
            total("input_tokens"), total("output_tokens"), total("total_tokens"),
            total("reasoning_tokens"), total("cached_input_tokens"), UsageSource.PROVIDER))


@dataclass(frozen=True)
class RuntimeInfo:
    profile_id: str
    provider_kind: str
    model: str
    adapter_id: str = "generic_openai_chat"
    provider_id: str = "custom"
    profile_status: str = "custom"
    service_id: str = "custom"
    model_family: str = "unknown"
    access_mode: str = "managed_custom"
    preset_id: str | None = None
    preset_variant: str | None = None
    preset_contract_version: str | None = None
