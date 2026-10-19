"""Pure shared Domain Analysis entry point; no repository, Web or model dependency."""

from datetime import datetime
import math

from .water_contracts import WaterQualityReading, Quality, Freshness, evaluate_freshness
from .diagnosis import DiagnosisService

from .contracts import WaterCapture, water_metric_facts
from .rules import assess_channel


def reading_from_row(row, *, metrics=None, freshness=Freshness.FRESH):
    """Canonical projection of validated facts, not a second risk rule implementation."""
    if row is None:
        return None
    metrics = water_metric_facts(row["payload"]["data"]) if metrics is None else metrics
    values = [m.mean if m.quality == "valid" else None for m in metrics]
    present = sum(v is not None for v in values)
    invalid = any(m.invalid_samples > 0 for m in metrics)
    quality = Quality.INVALID if invalid or not present else Quality.VALID if present == 3 else Quality.PARTIAL
    return WaterQualityReading(*values, datetime.fromisoformat(row["observed_at"]),
        datetime.fromisoformat(row["received_at"]), "simulator:"+row["device_id"]+":window_mean", quality, freshness)


class DomainAnalysisService:
    """Evaluate one device/channel at an explicit instant; never mutate or fetch facts."""

    def __init__(self, *, diagnosis=None, stale_after_s=30, offline_after_s=90):
        if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (stale_after_s, offline_after_s))
                or not 0 < stale_after_s < offline_after_s):
            raise ValueError("INVALID_MONITORING_LIFECYCLE")
        self.diagnosis = diagnosis if diagnosis is not None else DiagnosisService()
        self.stale_after_s, self.offline_after_s = stale_after_s, offline_after_s

    def evaluate(self, device_id, channel, row, *, evaluated_at):
        return self._evaluate(device_id, channel, row, evaluated_at=evaluated_at)

    def capture_water(self, device_id, row, *, evaluated_at):
        metrics = water_metric_facts(row["payload"]["data"] if row else None)
        analysis = self._evaluate(device_id, "water", row, evaluated_at=evaluated_at, water_metrics=metrics)
        reading = reading_from_row(row, metrics=metrics,
            freshness=Freshness(analysis.data_quality.freshness)) if row else None
        return WaterCapture(analysis, metrics, reading, self.diagnosis.RULE_VERSION,
                            row.get("last_reported_at") if row else None)

    def _evaluate(self, device_id, channel, row, *, evaluated_at, water_metrics=None):
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
                              connectivity=connectivity, diagnosis=self.diagnosis, water_metrics=water_metrics)
