"""Allowlisted JSONL traces. No prompt, credential or raw profile is serialized."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json
import threading

from .contracts import AnalysisResult, Mode


class JsonlTraceSink:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def record(self, result: AnalysisResult, *, mode: Mode, started_at: datetime,
               finished_at: datetime, total_ms: float) -> None:
        reading = result.observed_facts.water_quality
        entry = {
            "trace_id": result.trace_id,
            "request_id": result.request_id,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "mode": mode.value,
            "runtime": asdict(result.runtime),
            "input_snapshot_metadata": {
                "observed_at": reading.observed_at.isoformat(),
                "retrieved_at": reading.retrieved_at.isoformat(),
                "source": reading.source,
                "quality": reading.quality.value,
                "freshness": reading.freshness.value,
                "present_fields": [field for field, value in (
                    ("temperature_c", reading.temperature_c), ("ph", reading.ph),
                    ("dissolved_oxygen_mg_l", reading.dissolved_oxygen_mg_l)) if value is not None],
            },
            "rule_codes": [finding.code for finding in result.rule_results],
            "evidence_ids": [item.evidence_id for item in result.evidence],
            "status": result.status.value,
            "structured_parse_ok": result.structured_parse_ok,
            "timing": {"total_ms": round(total_ms, 3)},
            "usage": asdict(result.usage),
            "error_code": result.error_code,
            "error_option": result.error_option,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
