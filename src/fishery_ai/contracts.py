"""Immutable domain and application contracts for V0.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any

from .model_options import GenerationOptions, ReasoningOptions


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value


def parse_time(value: str) -> datetime:
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


class Quality(str, Enum):
    VALID = "valid"
    PARTIAL = "partial"
    INVALID = "invalid"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"


def evaluate_freshness(observed_at: datetime, evaluated_at: datetime,
                       stale_after_s: float) -> Freshness:
    """Shared domain age policy, for ingestion and current-state queries."""
    try:
        valid = type(stale_after_s) in (int, float) and math.isfinite(stale_after_s) and stale_after_s >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("stale_after_s must be finite and nonnegative")
    age_s = (aware(evaluated_at) - aware(observed_at)).total_seconds()
    return Freshness.STALE if age_s > stale_after_s else Freshness.FRESH


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


def _number(value: Any, lower: float, upper: float) -> tuple[float | None, bool]:
    if value is None or value == "" or value == "--":
        return None, False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, True
    if not math.isfinite(number) or not lower <= number <= upper:
        return None, True
    return number, False


@dataclass(frozen=True)
class WaterQualityReading:
    temperature_c: float | None
    ph: float | None
    dissolved_oxygen_mg_l: float | None
    observed_at: datetime
    retrieved_at: datetime
    source: str
    quality: Quality
    freshness: Freshness

    def __post_init__(self) -> None:
        aware(self.observed_at)
        aware(self.retrieved_at)
        if not self.source:
            raise ValueError("source is required")
        if self.observed_at > self.retrieved_at:
            raise ValueError("observed_at cannot be after retrieved_at")
        if not isinstance(self.quality, Quality):
            raise ValueError("quality must be a Quality value")
        if not isinstance(self.freshness, Freshness):
            raise ValueError("freshness must be a Freshness value")
        values = (self.temperature_c, self.ph, self.dissolved_oxygen_mg_l)
        limits = ((-50, 100), (0, 14), (0, 100))
        for value, (lower, upper) in zip(values, limits):
            if value is not None and (not math.isfinite(value) or not lower <= value <= upper):
                raise ValueError("water quality value is outside its physical range")
        if self.quality == Quality.VALID and any(value is None for value in values):
            raise ValueError("valid reading requires all three measurements")
        if self.quality == Quality.PARTIAL and not (0 < sum(value is not None for value in values) < 3):
            raise ValueError("partial reading requires some but not all measurements")

    @classmethod
    def from_raw(
        cls,
        raw: dict[str, Any],
        *,
        observed_at: datetime,
        retrieved_at: datetime,
        source: str,
        stale_after_s: float,
    ) -> WaterQualityReading:
        temp, bad_temp = _number(raw.get("temp"), -50, 100)
        ph, bad_ph = _number(raw.get("ph"), 0, 14)
        oxygen, bad_oxygen = _number(raw.get("oxygen"), 0, 100)
        values = (temp, ph, oxygen)
        if bad_temp or bad_ph or bad_oxygen or all(v is None for v in values):
            quality = Quality.INVALID
        elif any(v is None for v in values):
            quality = Quality.PARTIAL
        else:
            quality = Quality.VALID
        freshness = evaluate_freshness(observed_at, retrieved_at, stale_after_s)
        return cls(temp, ph, oxygen, observed_at, retrieved_at, source, quality, freshness)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox: tuple[float, float, float, float] | None = None
    track_id: str | None = None

    def __post_init__(self) -> None:
        if not self.label or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid detection")
        if self.bbox is not None:
            if len(self.bbox) != 4 or not all(math.isfinite(v) for v in self.bbox):
                raise ValueError("bbox must have four finite coordinates")
            x1, y1, x2, y2 = self.bbox
            if x1 > x2 or y1 > y2:
                raise ValueError("bbox coordinates are reversed")


@dataclass(frozen=True)
class DetectionEvent:
    event_id: str
    observed_at: datetime
    source: str
    model_id: str
    detections: tuple[Detection, ...]
    frame_id: str | None = None

    def __post_init__(self) -> None:
        aware(self.observed_at)
        if not all((self.event_id, self.source, self.model_id)):
            raise ValueError("event_id, source and model_id are required")
        if not isinstance(self.detections, tuple) or not all(isinstance(item, Detection) for item in self.detections):
            raise ValueError("detections must be an immutable tuple of Detection")


@dataclass(frozen=True)
class DetectionSummary:
    event_id: str
    observed_at: datetime
    count: int
    mean_confidence: float | None

    def __post_init__(self) -> None:
        aware(self.observed_at)
        if self.count < 0 or (self.mean_confidence is not None and
                              (not math.isfinite(self.mean_confidence) or not 0 <= self.mean_confidence <= 1)):
            raise ValueError("invalid detection summary")

    @classmethod
    def from_event(cls, event: DetectionEvent) -> DetectionSummary:
        count = len(event.detections)
        mean = sum(d.confidence for d in event.detections) / count if count else None
        return cls(event.event_id, event.observed_at, count, mean)


@dataclass(frozen=True)
class ObservedFacts:
    water_quality: WaterQualityReading
    detection_summary: DetectionSummary | None = None
    evaluated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.evaluated_at is not None:
            aware(self.evaluated_at)


@dataclass(frozen=True)
class RuleFinding:
    code: str
    severity: str
    message: str
    facts_used: tuple[str, ...]
    rule_version: str


@dataclass(frozen=True)
class KnowledgeEvidence:
    evidence_id: str
    text: str
    category: str
    score: float
    source_id: str
    retrieved_at: datetime
    source_title: str | None = None
    source_version: str | None = None

    def __post_init__(self) -> None:
        aware(self.retrieved_at)
        if not self.evidence_id or not self.source_id or not math.isfinite(self.score):
            raise ValueError("invalid evidence identity or score")


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


@dataclass(frozen=True)
class AnalysisRequest:
    mode: Mode
    profile_id: str
    question: str = ""
    generation: GenerationOptions = field(default_factory=GenerationOptions)
    reasoning: ReasoningOptions | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, Mode):
            raise ValueError("mode must be a Mode value")
        if self.mode == Mode.CHAT and not self.question.strip():
            raise ValueError("chat requires a question")
        if not self.profile_id:
            raise ValueError("profile_id is required")
        if not isinstance(self.generation, GenerationOptions):
            raise ValueError("generation must be GenerationOptions")
        if self.reasoning is not None and not isinstance(self.reasoning, ReasoningOptions):
            raise ValueError("reasoning must be ReasoningOptions")


@dataclass(frozen=True)
class AnalysisResult:
    request_id: str
    trace_id: str
    status: Status
    runtime: RuntimeInfo
    observed_facts: ObservedFacts
    rule_results: tuple[RuleFinding, ...]
    evidence: tuple[KnowledgeEvidence, ...]
    inference: str
    recommendations: tuple[str, ...]
    uncertainty: tuple[str, ...]
    generated_text: str
    structured_parse_ok: bool
    usage: Usage = field(default_factory=Usage)
    error_code: str | None = None
    error_option: str | None = None
    reasoning_content: str | None = None
