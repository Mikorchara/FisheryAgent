"""Management water facts and validation; no model, Web, storage or Prototype imports.

Forked narrowly from the established domain contract. Enum values, field order
and rejection semantics are preserved; class identity belongs to Monitoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any


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
class RuleFinding:
    code: str
    severity: str
    message: str
    facts_used: tuple[str, ...]
    rule_version: str
