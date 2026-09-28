"""Deterministic mock repositories."""

from __future__ import annotations

from pathlib import Path
import json

from .contracts import Detection, DetectionEvent, WaterQualityReading, parse_time


class MockRepository:
    def __init__(self, fixture_path: Path, *, stale_after_s: float = 300):
        self.data = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.stale_after_s = stale_after_s

    def water_quality(self, scenario: str) -> WaterQualityReading:
        fixture = self.data["water_quality"][scenario]
        return WaterQualityReading.from_raw(
            fixture["values"],
            observed_at=parse_time(fixture["observed_at"]),
            retrieved_at=parse_time(fixture["retrieved_at"]),
            source=fixture["source"],
            stale_after_s=self.stale_after_s,
        )

    def detection(self, scenario: str) -> DetectionEvent:
        fixture = self.data["detection"][scenario]
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
