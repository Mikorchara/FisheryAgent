"""Pure shared Domain Analysis entry point; no repository, Web or model dependency."""

from datetime import datetime
import math

from fishery_ai.contracts import WaterQualityReading, Quality, Freshness, evaluate_freshness
from fishery_ai.domain import DiagnosisService

from .contracts import METRICS, metric_quality
from .rules import assess_channel


def reading_from_row(row):
    """Canonical projection of validated facts, not a second risk rule implementation."""
    if row is None:
        return None
    data = row["payload"]["data"]
    values = [data["metrics"][key]["mean"] if metric_quality(data["metrics"][key], data["sample_count"]) == "valid"
              else None for key in METRICS]
    present = sum(v is not None for v in values)
    invalid = any(s["invalid_samples"] > 0 for s in data["metrics"].values())
    quality = Quality.INVALID if invalid or not present else Quality.VALID if present == 3 else Quality.PARTIAL
    return WaterQualityReading(*values, datetime.fromisoformat(row["observed_at"]),
        datetime.fromisoformat(row["received_at"]), "simulator:"+row["device_id"]+":window_mean", quality, Freshness.FRESH)


class DomainAnalysisService:
    """Evaluate one device/channel at an explicit instant; never mutate or fetch facts."""

    def __init__(self, *, diagnosis=None, stale_after_s=30, offline_after_s=90):
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (stale_after_s, offline_after_s))
                or not 0 < stale_after_s < offline_after_s):
            raise ValueError("INVALID_MONITORING_LIFECYCLE")
        self.diagnosis = diagnosis if diagnosis is not None else DiagnosisService()
        self.stale_after_s, self.offline_after_s = stale_after_s, offline_after_s

    def evaluate(self, device_id, channel, row, *, evaluated_at):
        if not isinstance(evaluated_at, datetime) or evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("INVALID_ANALYSIS_TIME")
        if row is not None and row["device_id"] != device_id:
            raise ValueError("ANALYSIS_DEVICE_MISMATCH")
        freshness, connectivity = "unknown", "never_received"
        if row is not None:
            if evaluated_at < datetime.fromisoformat(row["received_at"]):
                raise ValueError("ANALYSIS_TIME_PRECEDES_RECEIPT")
            freshness = evaluate_freshness(datetime.fromisoformat(row["observed_at"]), evaluated_at, self.stale_after_s).value
            last_contact = datetime.fromisoformat(row.get("last_reported_at") or row["received_at"])
            connectivity = "offline" if (evaluated_at-last_contact).total_seconds() > self.offline_after_s else "online"
        return assess_channel(device_id, channel, row, evaluated_at=evaluated_at, freshness=freshness,
                              connectivity=connectivity, diagnosis=self.diagnosis)
