"""One authoritative read boundary for pages and future read-only AI Tools."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from typing import Callable

from fishery_ai.telemetry.current import CurrentWaterQualityReader

from .contracts import (METRICS, validate_batch, MetricObservation, MonitoringSnapshot, identifier,
                        metric_quality, FindingState, ChannelAnalysis)
from .analysis import DomainAnalysisService, reading_from_row


def utcnow():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DeviceReadContext:
    """A selected device is bound once; no mutable global page selection."""
    device_id: str
    water_reader: CurrentWaterQualityReader
    _analysis_query: Callable[[str], ChannelAnalysis] | None = field(default=None, repr=False, compare=False)

    def analysis(self, channel="water"):
        if self._analysis_query is None:
            raise ValueError("ANALYSIS_SERVICE_UNAVAILABLE")
        return self._analysis_query(channel)


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
        self.domain_analysis = DomainAnalysisService(stale_after_s=stale_after_s, offline_after_s=offline_after_s)

    @property
    def stale_after_s(self):
        return self.domain_analysis.stale_after_s

    @property
    def offline_after_s(self):
        return self.domain_analysis.offline_after_s

    @property
    def diagnosis(self):
        return self.domain_analysis.diagnosis

    @diagnosis.setter
    def diagnosis(self, value):
        self.domain_analysis.diagnosis = value

    def _assess(self, device_id, channel, row, now):
        return self.domain_analysis.evaluate(device_id, channel, row, evaluated_at=now)

    def analysis(self, device_id, channel="water"):
        self._device(device_id)
        if channel not in ("water", "visual"):
            raise ValueError("INVALID_ANALYSIS_CHANNEL")
        return self._assess(device_id, channel, self.repository.read(device_id, channel), self.clock())

    def devices(self):
        return [{"id": key, "name": name, "source_kind": "simulator"} for key, name in self.device_names.items()]

    def _device(self, device_id):
        if device_id not in self.device_names:
            raise ValueError("UNKNOWN_MONITORING_DEVICE")

    def bind(self, device_id):
        self._device(device_id)
        return DeviceReadContext(device_id, CurrentWaterQualityReader(
            _DeviceSnapshotSource(self.repository, device_id), stale_after_s=self.stale_after_s, clock=self.clock),
            partial(self.analysis, device_id))

    def ingest(self, value):
        now = self.clock()
        batch = validate_batch(value, now=now, device_ids=self.device_names)
        assessments = {}
        for channel in ("water", "visual"):
            row = ({"device_id": batch["device_id"], "batch_id": batch["batch_id"],
                "observed_at": batch["timestamp"], "received_at": now.isoformat(),
                "payload": {"window": batch["window"], "data": batch[channel]}} if batch[channel] is not None else None)
            assessments[channel] = self._assess(batch["device_id"], channel, row, now)
        return self.repository.ingest(batch, now, assessments)

    def snapshot(self, device_id, view="available"):
        self._device(device_id)
        if view != "available":
            raise ValueError("LIVE_VIEW_CANNOT_OVERRIDE_DATA")
        row, history = self.repository.capture(device_id, "water")
        now = self.clock()
        analysis = self._assess(device_id, "water", row, now)
        freshness, connectivity = analysis.data_quality.freshness, analysis.data_quality.connectivity
        data = row["payload"]["data"] if row else None
        observed_at = row["observed_at"] if row else None
        metrics = []
        for key, (label, unit, _low, _high) in METRICS.items():
            stat = data["metrics"][key] if data else None
            value = stat["mean"] if stat else None
            quality = metric_quality(stat, data["sample_count"]) if stat else "missing"
            metrics.append(MetricObservation(key, label, value, unit, quality, "连续模拟器", observed_at, freshness,
                stat["valid_samples"] if stat else None, data["sample_count"] if data else None,
                stat["min"] if stat else None, stat["max"] if stat else None, stat["latest"] if stat else None,
                stat["invalid_samples"] if stat else None))
        trend = tuple({"observed_at": item["observed_at"], "received_at": item["received_at"], "batch_id": item["batch_id"], "window_duration_s": item["payload"]["window"]["duration_s"],
            "metric_quality": {key: metric_quality(item["payload"]["data"]["metrics"][key], item["payload"]["data"]["sample_count"]) for key in METRICS},
            **{key: (item["payload"]["data"]["metrics"][key]["mean"] if metric_quality(item["payload"]["data"]["metrics"][key], item["payload"]["data"]["sample_count"]) == "valid" else None) for key in METRICS}}
            for item in history)
        findings = tuple(f.to_dict() for f in analysis.findings if f.state == FindingState.HIT)
        return MonitoringSnapshot(device_id, "连续模拟器 · 非真实传感器", "simulator", observed_at,
            now.isoformat(), analysis.data_quality.quality, freshness, tuple(metrics), trend,
            row["received_at"] if row else None, connectivity, "window_mean" if row else None,
            row["payload"]["window"] if row else None, row["batch_id"] if row else None, findings, self.diagnosis.RULE_VERSION,
            row.get("last_reported_at") if row else None, analysis.to_dict())

    def cameras(self):
        result = []
        for device_id, name in self.device_names.items():
            row = self.repository.read(device_id, "visual")
            now = self.clock()
            analysis = self._assess(device_id, "visual", row, now)
            freshness, connectivity = analysis.data_quality.freshness, analysis.data_quality.connectivity
            result.append({"id": device_id, "name": name+" · 视觉", "device_id": device_id, "location": name,
                "status": connectivity, "source_kind": "simulator", "stream_url": None, "detections": [],
                "detection_status": "simulated" if row else "missing", "freshness": freshness,
                "signal_status": ("no_data" if not row else "no_valid_frames" if row["payload"]["data"].get("valid_frames") == 0 else
                    "suspected_anomaly" if any(f.state == FindingState.HIT and f.kind != "DATA_QUALITY" for f in analysis.findings) else
                    "no_obvious_anomaly" if all(f.state == FindingState.CLEAR for f in analysis.findings if f.kind != "DATA_QUALITY") else "indeterminate"),
                "observed_at": row["observed_at"] if row else None, "received_at": row["received_at"] if row else None,
                "last_reported_at": row.get("last_reported_at") if row else None,
                "evaluated_at": now.isoformat(), "batch_id": row["batch_id"] if row else None,
                "window": row["payload"]["window"] if row else None, "summary": row["payload"]["data"] if row else None,
                "analysis": analysis.to_dict()})
        return result

    def events(self):
        assessments = {}
        events = self.repository.events()
        result = []
        for event in events:
            if event.get("lifecycle_state") == "RESOLVED" or event.get("status") == "closed":
                result.append(event)
                continue
            key = (event["device_id"], event["channel"])
            if key not in assessments:
                row = self.repository.read(*key)
                assessments[key] = self._assess(*key, row, self.clock())
            result.append(self.repository.event_service.project(event, assessments[key]))
        return result

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
