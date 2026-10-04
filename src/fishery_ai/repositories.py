"""Deterministic mock repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from datetime import datetime
import json

from .contracts import Detection, DetectionEvent, WaterQualityReading, parse_time, utcnow
from .telemetry import CurrentSnapshotStore, SimulationAdapter
from .telemetry.scenario_templates import ScenarioTemplateStore, apply_scenario_template, validate_id


class MockRepository:
    def __init__(self, resource_root: Path, *, stale_after_s: float = 300,
                 clock: Callable[[], datetime] = utcnow):
        self.templates = ScenarioTemplateStore(resource_root.joinpath("water_quality"))
        self.detection_root = resource_root.joinpath("detection")
        self.adapter = SimulationAdapter(stale_after_s=stale_after_s)
        # Only scenario generation uses this lazy, private demo state. Web current
        # facts are composed separately and never read through this repository.
        self._demo_snapshots: CurrentSnapshotStore | None = None
        self.clock = clock

    @property
    def demo_snapshots(self) -> CurrentSnapshotStore:
        if self._demo_snapshots is None:
            self._demo_snapshots = CurrentSnapshotStore()
        return self._demo_snapshots

    @property
    def snapshots(self) -> CurrentSnapshotStore:
        """Legacy demo alias; not the Web current-state store."""
        return self.demo_snapshots

    def water_quality(self, scenario: str) -> WaterQualityReading:
        """Generate a scenario for demo compatibility, never read current facts."""
        template = self.templates.get_template(scenario).template
        return apply_scenario_template(template, snapshot_store=self.demo_snapshots,
                                       adapter=self.adapter, now=self.clock())

    def detection(self, scenario: str) -> DetectionEvent:
        validate_id(scenario)
        fixture = json.loads(self.detection_root.joinpath(scenario + ".json").read_text(encoding="utf-8"))
        detections = tuple(
            Detection(
                label=d["label"], confidence=d["confidence"],
                bbox=tuple(d["bbox"]) if d.get("bbox") is not None else None,
                track_id=d.get("track_id"),
            ) for d in fixture["detections"]
        )
        return DetectionEvent(
            event_id=fixture["event_id"],
            observed_at=parse_time(fixture["observed_at"]),
            source=fixture["source"], model_id=fixture["model_id"],
            frame_id=fixture.get("frame_id"), detections=detections,
        )
