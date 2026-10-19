"""Versioned device window protocol. Validation never trusts producer provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from enum import Enum
import json
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .water_contracts import WaterQualityReading

SCHEMA_VERSION = 1
METRICS = {
    "temperature_c": ("水温", "°C", -50, 100),
    "ph": ("pH", "", 0, 14),
    "dissolved_oxygen_mg_l": ("溶解氧", "mg/L", 0, 100),
}
ANOMALIES = ("suspected_lesion", "surface_anomaly", "suspected_dead")
BEHAVIORS = ("normal_activity", "reduced_activity", "feeding", "feeding_anomaly", "unknown")


class FindingState(str, Enum):
    HIT = "HIT"
    CLEAR = "CLEAR"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_EVALUATED = "NOT_EVALUATED"


class EventState(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class RuleIdentity:
    rule_id: str
    version: str
    scope: tuple[str, ...]
    publication_status: str = "PROTOTYPE"
    assessment_policy_version: str = "monitoring-assessment-v1"

    def __post_init__(self):
        if (not isinstance(self.rule_id, str) or not self.rule_id or not isinstance(self.version, str)
                or not self.version or self.publication_status != "PROTOTYPE"
                or not isinstance(self.assessment_policy_version, str) or not self.assessment_policy_version):
            raise ValueError("INVALID_PROTOTYPE_RULE_IDENTITY")
        if not isinstance(self.scope, tuple) or not self.scope or any(not isinstance(x, str) or not x for x in self.scope):
            raise ValueError("INVALID_RULE_SCOPE")


@dataclass(frozen=True)
class ObservationRef:
    device_id: str
    channel: str
    batch_id: str
    observed_at: str
    received_at: str
    window_start: str
    window_end: str
    window_duration_s: float
    aggregation: str
    source_kind: str = "simulator"
    statistics_version: str | None = None

    def __post_init__(self):
        if self.channel not in ("water", "visual") or self.source_kind != "simulator":
            raise ValueError("INVALID_OBSERVATION_SCOPE")
        for value in (self.device_id, self.batch_id):
            identifier(value)
        number(self.window_duration_s, 1, 60)
        start, end = timestamp(self.window_start), timestamp(self.window_end)
        if (timestamp(self.observed_at) != end or timestamp(self.received_at) < end
                or abs((end-start).total_seconds()-self.window_duration_s) > .001
                or self.aggregation != ("window_mean" if self.channel == "water" else "window_summary")):
            raise ValueError("INVALID_OBSERVATION_TIME_OR_AGGREGATION")


@dataclass(frozen=True)
class DataQuality:
    quality: str
    freshness: str
    connectivity: str
    coverage: tuple[tuple[str, int, int], ...] = ()  # metric/channel, valid count, attempted count

    def __post_init__(self):
        if (self.quality not in ("valid", "partial", "invalid", "missing")
                or self.freshness not in ("fresh", "stale", "unknown")
                or self.connectivity not in ("online", "offline", "never_received")
                or not isinstance(self.coverage, tuple)
                or any(not isinstance(c, tuple) or len(c) != 3 or not isinstance(c[0], str)
                       or type(c[1]) is not int or type(c[2]) is not int or not 0 <= c[1] <= c[2]
                       for c in self.coverage)):
            raise ValueError("INVALID_DATA_QUALITY")


@dataclass(frozen=True)
class MonitoringFinding:
    code: str
    kind: str
    state: FindingState
    severity: str | None
    message: str
    facts_used: tuple[str, ...]
    rule: RuleIdentity
    observation: ObservationRef | None
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.state, FindingState) or not isinstance(self.rule, RuleIdentity):
            raise ValueError("INVALID_FINDING_CONTRACT")
        if self.code != self.rule.rule_id or self.severity not in (None, "info", "warning", "critical"):
            raise ValueError("INVALID_FINDING_CONTRACT")
        if (self.state == FindingState.HIT) != (self.severity is not None):
            raise ValueError("INVALID_FINDING_SEVERITY")

    def to_dict(self):
        result = asdict(self)
        result["rule_version"] = self.rule.version  # Existing consumers keep this alias.
        return result


@dataclass(frozen=True)
class ChannelAnalysis:
    device_id: str
    channel: str
    evaluated_at: str
    observation: ObservationRef | None
    data_quality: DataQuality
    findings: tuple[MonitoringFinding, ...]
    schema_version: int = 1

    def __post_init__(self):
        timestamp(self.evaluated_at)
        if (self.channel not in ("water", "visual") or not isinstance(self.data_quality, DataQuality)
                or not isinstance(self.findings, tuple)
                or any(not isinstance(f, MonitoringFinding) or f.observation != self.observation for f in self.findings)
                or self.observation is not None and (self.observation.device_id != self.device_id or self.observation.channel != self.channel)):
            raise ValueError("INVALID_ANALYSIS_SCOPE")

    def to_dict(self):
        result = asdict(self)
        result["findings"] = [f.to_dict() for f in self.findings]
        result["status"] = "NO_DATA" if self.observation is None else "AVAILABLE"
        return result


@dataclass(frozen=True)
class EventAssessment:
    event_id: str
    lifecycle_state: EventState
    rule: RuleIdentity | None
    observation: ObservationRef | None
    evaluated_at: str
    reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.lifecycle_state, EventState):
            raise ValueError("INVALID_EVENT_STATE")


def metric_quality(stat, sample_count):
    if stat["invalid_samples"]:
        return "invalid"
    if stat["mean"] is None or stat["valid_samples"] == 0:
        return "missing"
    return "valid" if stat["valid_samples"] == sample_count else "partial"


@dataclass(frozen=True)
class WaterMetricFact:
    """Received window statistics, without page labels or risk interpretation."""
    id: str
    unit: str
    mean: float | None
    quality: str
    valid_samples: int
    sample_count: int
    invalid_samples: int
    minimum: float | None
    maximum: float | None
    latest: float | None


def water_metric_facts(data):
    """Classify each received metric once for rules and read projections."""
    if data is None:
        return ()
    return tuple(WaterMetricFact(key, unit, stat["mean"], metric_quality(stat, data["sample_count"]),
        stat["valid_samples"], data["sample_count"], stat["invalid_samples"],
        stat["min"], stat["max"], stat["latest"])
        for key, (_label, unit, _low, _high) in METRICS.items() for stat in (data["metrics"][key],))


@dataclass(frozen=True)
class WaterCapture:
    """One detached current row assessed once; no history or presentation payload."""
    analysis: ChannelAnalysis
    metrics: tuple[WaterMetricFact, ...]
    reading: WaterQualityReading | None
    rule_version: str
    last_reported_at: str | None


@dataclass(frozen=True)
class MetricObservation:
    id: str
    label: str
    value: float | None
    unit: str
    quality: str
    source: str
    observed_at: str | None
    freshness: str
    valid_samples: int | None = None
    sample_count: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    latest: float | None = None
    invalid_samples: int | None = None


@dataclass(frozen=True)
class MonitoringSnapshot:
    device_id: str
    source: str
    source_kind: str
    observed_at: str | None
    evaluated_at: str
    quality: str
    freshness: str
    metrics: tuple[MetricObservation, ...]
    trend: tuple[dict, ...]
    received_at: str | None = None
    connectivity: str = "not_connected"
    aggregation: str | None = None
    window: dict | None = None
    batch_id: str | None = None
    findings: tuple[dict, ...] = ()
    rule_version: str | None = None
    last_reported_at: str | None = None
    analysis: dict | None = None


def valid_token(token):
    return isinstance(token, str) and 32 <= len(token) <= 128 and token.isascii() and token.isalnum()


class IngestionError(ValueError):
    def __init__(self, code, http_status=400):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def fail(code="INVALID_MONITORING_BATCH", status=400):
    raise IngestionError(code, status)


def object_keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        fail()


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        fail()


def number(value, low, high):
    if type(value) not in (int, float):
        fail()
    try:
        valid = math.isfinite(value) and low <= value <= high
    except OverflowError:
        valid = False
    if not valid:
        fail()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        fail()


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        fail()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            fail()
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        fail()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("DUPLICATE_JSON_FIELD")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _value: fail())
    except (ValueError, TypeError, RecursionError, UnicodeError):
        fail()


def validate_batch(value, *, now, device_ids):
    object_keys(value, ("schema_version", "batch_id", "session_id", "sequence", "device_id",
                        "timestamp", "window", "water", "visual"))
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        fail("UNSUPPORTED_MONITORING_SCHEMA")
    for key in ("batch_id", "session_id", "device_id"):
        identifier(value[key])
    if value["device_id"] not in device_ids:
        fail("DEVICE_NOT_ALLOWED", 403)
    integer(value["sequence"], 0, 2**31-1)
    window = value["window"]
    object_keys(window, ("start", "end", "duration_s"))
    start, end = timestamp(window["start"]), timestamp(window["end"])
    number(window["duration_s"], 1, 60)
    if abs((end-start).total_seconds()-window["duration_s"]) > .001 or timestamp(value["timestamp"]) != end:
        fail("INVALID_WINDOW")
    age = (now-end).total_seconds()
    if age < 0 or age > 300:
        fail("OBSERVATION_TIME_REJECTED")
    water, visual = value["water"], value["visual"]
    if water is None and visual is None:
        fail("EMPTY_MONITORING_BATCH")
    if water is not None:
        object_keys(water, ("aggregation", "sample_count", "metrics"))
        if water["aggregation"] != "window_mean":
            fail()
        integer(water["sample_count"], 1, 600)
        object_keys(water["metrics"], METRICS)
        for key, (_label, unit, low, high) in METRICS.items():
            stat = water["metrics"][key]
            object_keys(stat, ("unit", "mean", "min", "max", "latest", "valid_samples", "invalid_samples"))
            if stat["unit"] != unit:
                fail("INVALID_METRIC_UNIT")
            integer(stat["valid_samples"], 0, water["sample_count"])
            integer(stat["invalid_samples"], 0, water["sample_count"])
            if stat["valid_samples"]+stat["invalid_samples"] > water["sample_count"]:
                fail()
            fields = [stat[k] for k in ("mean", "min", "max", "latest")]
            if stat["valid_samples"] == 0:
                if any(v is not None for v in fields):
                    fail()
            else:
                for v in fields:
                    number(v, low, high)
                if not stat["min"] <= stat["mean"] <= stat["max"] or not stat["min"] <= stat["latest"] <= stat["max"]:
                    fail()
    if visual is not None:
        # Additive statistics: legacy v1 windows remain readable/acceptable.
        object_keys(visual, ("aggregation", "frames_processed", "anomaly_counts", "behavior_ratios",
                            "length", "visible_fish_count", "model_version") +
                    (("valid_frames",) if "valid_frames" in visual else ()))
        if visual["aggregation"] != "window_summary":
            fail()
        integer(visual["frames_processed"], 1, 6000)
        valid_frames = visual.get("valid_frames", visual["frames_processed"])
        integer(valid_frames, 0, visual["frames_processed"])
        identifier(visual["model_version"])
        object_keys(visual["anomaly_counts"], ANOMALIES)
        for count in visual["anomaly_counts"].values():
            integer(count, 0, valid_frames)
        object_keys(visual["behavior_ratios"], BEHAVIORS)
        for ratio in visual["behavior_ratios"].values():
            number(ratio, 0, 1)
        if abs(sum(visual["behavior_ratios"].values())-(1 if valid_frames else 0)) > .00001:
            fail("INVALID_BEHAVIOR_RATIOS")
        length = visual["length"]
        object_keys(length, ("average_length_cm", "length_sample_count", "calibration", "calibration_id") +
                    (("valid_frame_count",) if "valid_frame_count" in length else ()))
        integer(length["length_sample_count"], 0, 6000)
        if "valid_frame_count" in length:
            integer(length["valid_frame_count"], 0, min(valid_frames, length["length_sample_count"]))
            if bool(length["valid_frame_count"]) != bool(length["length_sample_count"]):
                fail()
        if not valid_frames and (length["length_sample_count"] or visual["visible_fish_count"] is not None):
            fail()
        if length["calibration"] not in ("uncalibrated", "simulated"):
            fail()
        if length["length_sample_count"] == 0:
            if length["average_length_cm"] is not None:
                fail()
        else:
            if length["calibration"] != "simulated":
                fail("LENGTH_CALIBRATION_REQUIRED")
            number(length["average_length_cm"], .1, 300)
        if length["calibration"] == "uncalibrated":
            if length["length_sample_count"] != 0 or length["calibration_id"] is not None:
                fail()
        else:
            identifier(length["calibration_id"])
        if visual["visible_fish_count"] is not None:
            number(visual["visible_fish_count"], 0, 10000)
    # JSON roundtrip detaches caller-owned dictionaries and normalizes UTC for ordering.
    result = json.loads(json.dumps(value, allow_nan=False))
    result["timestamp"] = end.isoformat()
    result["window"]["start"] = start.isoformat()
    result["window"]["end"] = end.isoformat()
    return result
