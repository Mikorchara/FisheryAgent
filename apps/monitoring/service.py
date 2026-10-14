"""One authoritative read boundary for pages and future read-only AI Tools."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math

from fishery_ai.contracts import WaterQualityReading, Quality, Freshness, evaluate_freshness
from fishery_ai.domain import DiagnosisService
from fishery_ai.telemetry.current import CurrentWaterQualityReader

from .contracts import METRICS, validate_batch, MetricObservation, MonitoringSnapshot, identifier


def utcnow():
    return datetime.now(timezone.utc)


def reading_from_row(row):
    if row is None:
        return None
    values = [row["payload"]["data"]["metrics"][key]["mean"] for key in METRICS]
    present = sum(v is not None for v in values)
    invalid = any(s["invalid_samples"] > 0 for s in row["payload"]["data"]["metrics"].values())
    quality = Quality.INVALID if invalid or not present else Quality.VALID if present == 3 else Quality.PARTIAL
    return WaterQualityReading(*values, datetime.fromisoformat(row["observed_at"]),
        datetime.fromisoformat(row["received_at"]), "simulator:"+row["device_id"]+":window_mean", quality, Freshness.FRESH)


@dataclass(frozen=True)
class DeviceReadContext:
    """A selected device is bound once; no mutable global page selection."""
    device_id: str
    water_reader: CurrentWaterQualityReader


class _DeviceSnapshotSource:
    def __init__(self, repository, device_id):
        self._repository, self._device_id = repository, device_id

    def get_current(self):
        return reading_from_row(self._repository.read(self._device_id, "water"))


class MonitoringService:
    data_mode = "simulator"

    def __init__(self, repository, *, device_names=None, clock=utcnow, stale_after_s=30, offline_after_s=90):
        self.repository = repository
        self.device_names = dict({"sim-pond-1": "模拟养殖池 1"} if device_names is None else device_names)
        for device_id, name in self.device_names.items():
            identifier(device_id)
            if not isinstance(name, str) or not 1 <= len(name) <= 128:
                raise ValueError("INVALID_DEVICE_REGISTRY")
        self.clock = clock
        self.stale_after_s, self.offline_after_s = stale_after_s, offline_after_s
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (stale_after_s, offline_after_s))
                or not 0 < stale_after_s < offline_after_s):
            raise ValueError("INVALID_MONITORING_LIFECYCLE")
        self.diagnosis = DiagnosisService()

    def devices(self):
        return [{"id": key, "name": name, "source_kind": "simulator"} for key, name in self.device_names.items()]

    def _device(self, device_id):
        if device_id not in self.device_names:
            raise ValueError("UNKNOWN_MONITORING_DEVICE")

    def bind(self, device_id):
        self._device(device_id)
        return DeviceReadContext(device_id, CurrentWaterQualityReader(
            _DeviceSnapshotSource(self.repository, device_id), stale_after_s=self.stale_after_s, clock=self.clock))

    def ingest(self, value):
        now = self.clock()
        batch = validate_batch(value, now=now, device_ids=self.device_names)
        findings = {}
        if batch["water"] is not None:
            row = {"device_id": batch["device_id"], "observed_at": batch["timestamp"],
                   "received_at": now.isoformat(), "payload": {"data": batch["water"]}}
            reading = reading_from_row(row)
            reading = WaterQualityReading(reading.temperature_c, reading.ph, reading.dissolved_oxygen_mg_l,
                reading.observed_at, reading.retrieved_at, reading.source, reading.quality,
                evaluate_freshness(reading.observed_at, now, self.stale_after_s))
            findings["water"] = [asdict(f) for f in self.diagnosis.diagnose(reading)]
        if batch["visual"] is not None:
            visual = batch["visual"]
            definitions = (("suspected_lesion", "疑似病灶检测信号（模拟，非诊断）"),
                           ("surface_anomaly", "体表异常检测信号（模拟）"),
                           ("suspected_dead", "疑似死亡个体检测信号（模拟，需核查）"))
            findings["visual"] = [{"code": key.upper(), "severity": "warning", "message": text,
                "rule_version": "sim-visual-presence-v1"} for key, text in definitions if visual["anomaly_counts"][key] > 0]
            if visual["behavior_ratios"]["feeding_anomaly"] > 0:
                findings["visual"].append({"code": "FEEDING_ANOMALY", "severity": "warning",
                    "message": "摄食异常行为信号（模拟）", "rule_version": "sim-visual-presence-v1"})
        return self.repository.ingest(batch, now, findings)

    def _state(self, row, now):
        if row is None:
            return "unknown", "never_received"
        freshness = evaluate_freshness(datetime.fromisoformat(row["observed_at"]), now, self.stale_after_s).value
        connectivity = "offline" if (now-datetime.fromisoformat(row.get("last_reported_at") or row["received_at"])).total_seconds() > self.offline_after_s else "online"
        return freshness, connectivity

    def snapshot(self, device_id, view="available"):
        self._device(device_id)
        if view != "available":
            raise ValueError("LIVE_VIEW_CANNOT_OVERRIDE_DATA")
        now = self.clock()
        row, history = self.repository.capture(device_id, "water")
        freshness, connectivity = self._state(row, now)
        reading = reading_from_row(row)
        data = row["payload"]["data"] if row else None
        observed_at = row["observed_at"] if row else None
        metrics = []
        for key, (label, unit, _low, _high) in METRICS.items():
            stat = data["metrics"][key] if data else None
            value = stat["mean"] if stat else None
            quality = "invalid" if stat and stat["invalid_samples"] else "valid" if value is not None else "missing"
            metrics.append(MetricObservation(key, label, value, unit, quality, "连续模拟器", observed_at, freshness,
                stat["valid_samples"] if stat else None, data["sample_count"] if data else None,
                stat["min"] if stat else None, stat["max"] if stat else None, stat["latest"] if stat else None,
                stat["invalid_samples"] if stat else None))
        trend = tuple({"observed_at": item["observed_at"], "received_at": item["received_at"], "batch_id": item["batch_id"], "window_duration_s": item["payload"]["window"]["duration_s"],
            **{key: item["payload"]["data"]["metrics"][key]["mean"] for key in METRICS}}
            for item in history)
        if reading:
            refreshed = WaterQualityReading(reading.temperature_c, reading.ph, reading.dissolved_oxygen_mg_l,
                reading.observed_at, reading.retrieved_at, reading.source, reading.quality, Freshness(freshness))
            findings = tuple(asdict(f) for f in self.diagnosis.diagnose(refreshed))
        else:
            findings = ()
        return MonitoringSnapshot(device_id, "连续模拟器 · 非真实传感器", "simulator", observed_at,
            now.isoformat(), reading.quality.value if reading else "missing", freshness, tuple(metrics), trend,
            row["received_at"] if row else None, connectivity, "window_mean" if row else None,
            row["payload"]["window"] if row else None, row["batch_id"] if row else None, findings, self.diagnosis.RULE_VERSION,
            row.get("last_reported_at") if row else None)

    def cameras(self):
        now = self.clock()
        result = []
        for device_id, name in self.device_names.items():
            row = self.repository.read(device_id, "visual")
            freshness, connectivity = self._state(row, now)
            result.append({"id": device_id, "name": name+" · 视觉", "device_id": device_id, "location": name,
                "status": connectivity, "source_kind": "simulator", "stream_url": None, "detections": [],
                "detection_status": "simulated" if row else "missing", "freshness": freshness,
                "signal_status": ("suspected_anomaly" if any(row["payload"]["data"]["anomaly_counts"].values()) else "no_obvious_anomaly") if row else "no_data",
                "observed_at": row["observed_at"] if row else None, "received_at": row["received_at"] if row else None,
                "last_reported_at": row.get("last_reported_at") if row else None,
                "evaluated_at": now.isoformat(), "batch_id": row["batch_id"] if row else None,
                "window": row["payload"]["window"] if row else None, "summary": row["payload"]["data"] if row else None})
        return result

    def events(self):
        return self.repository.events()

    def history(self, device_id, channel, limit=None):
        self._device(device_id)
        if limit is None:
            limit = min(60, self.repository.history_limit)
        if channel not in ("water", "visual") or type(limit) is not int or not 1 <= limit <= self.repository.history_limit:
            raise ValueError("INVALID_HISTORY_QUERY")
        return [{"batch_id": row["batch_id"], "device_id": device_id, "channel": channel,
            "source_kind": "simulator", "observed_at": row["observed_at"], "received_at": row["received_at"],
            "window": row["payload"]["window"], "summary": row["payload"]["data"]}
            for row in self.repository.history(device_id, channel)[-limit:]]
