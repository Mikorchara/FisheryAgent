"""Allowlisted JSONL traces. No prompt, credential or raw profile is serialized."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json
import re
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
        self._append(entry)

    def record_tool_conversation(self, result, *, started_at: datetime,
                                 finished_at: datetime, total_ms: float) -> None:
        """Separate allowlist: no question, model text, tool arguments or facts."""
        tool = result.tool_result
        entry = {
            "kind": "read_only_tool_conversation",
            "request_id": result.request_id, "trace_id": result.trace_id,
            "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
            "status": result.status.value, "error_code": result.error_code,
            "model_request_1": asdict(result.request_1),
            "model_request_2": asdict(result.request_2),
            "tool_call_id": result.tool_call_id if result.tool_call_id and re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", result.tool_call_id) else None,
            "tool_name": "get_current_water_quality" if result.tool_name == "get_current_water_quality"
                         else "unknown_tool" if result.tool_name else None,
            "tool_result_status": tool.status.value if tool else None,
            "tool_duration_ms": round(result.tool_duration_ms, 3) if result.tool_duration_ms is not None else None,
            "final_finish_reason": result.final_finish_reason,
            "usage": asdict(result.usage), "timing": {"total_ms": round(total_ms, 3)},
        }
        self._append(entry)

    def _append(self, entry: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
