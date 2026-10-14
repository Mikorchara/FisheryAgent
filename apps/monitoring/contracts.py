"""Versioned device window protocol. Validation never trusts producer provenance."""

from datetime import datetime, timezone
from dataclasses import dataclass
import json
import math
import re

SCHEMA_VERSION = 1
METRICS = {
    "temperature_c": ("水温", "°C", -50, 100),
    "ph": ("pH", "", 0, 14),
    "dissolved_oxygen_mg_l": ("溶解氧", "mg/L", 0, 100),
}
ANOMALIES = ("suspected_lesion", "surface_anomaly", "suspected_dead")
BEHAVIORS = ("normal_activity", "reduced_activity", "feeding", "feeding_anomaly", "unknown")


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
        object_keys(visual, ("aggregation", "frames_processed", "anomaly_counts", "behavior_ratios",
                            "length", "visible_fish_count", "model_version"))
        if visual["aggregation"] != "window_summary":
            fail()
        integer(visual["frames_processed"], 1, 6000)
        identifier(visual["model_version"])
        object_keys(visual["anomaly_counts"], ANOMALIES)
        for count in visual["anomaly_counts"].values():
            integer(count, 0, visual["frames_processed"])
        object_keys(visual["behavior_ratios"], BEHAVIORS)
        for ratio in visual["behavior_ratios"].values():
            number(ratio, 0, 1)
        if abs(sum(visual["behavior_ratios"].values())-1) > .00001:
            fail("INVALID_BEHAVIOR_RATIOS")
        length = visual["length"]
        object_keys(length, ("average_length_cm", "length_sample_count", "calibration", "calibration_id"))
        integer(length["length_sample_count"], 0, 6000)
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
