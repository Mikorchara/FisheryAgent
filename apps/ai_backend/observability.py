"""Allowlisted JSONL traces. No prompt, credential or raw profile is serialized."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json
import re
import threading

from .tool_argument_diagnostics import public_argument_diagnostic


def _model_outcome(outcome):
    # Explicit projection: the diagnostic is not arbitrary exception metadata.
    result = {"outcome": outcome.outcome, "usage": asdict(outcome.usage),
              "finish_reason": outcome.finish_reason, "error_code": outcome.error_code}
    diagnostic = public_argument_diagnostic(outcome.argument_diagnostic)
    if diagnostic is not None:
        result["argument_diagnostic"] = diagnostic
    return result


class JsonlTraceSink:
    def __init__(self, path: Path, *, tool_names=()):
        self.tool_names = tuple(tool_names)
        self.path = path
        self._lock = threading.Lock()


    def record_tool_conversation(self, result, *, started_at: datetime,
                                 finished_at: datetime, total_ms: float) -> None:
        """Separate allowlist: no question, model text, tool arguments or facts."""
        from .tool_conversation import ModelExecutionStep, ToolExecutionStep
        legacy = (sum(isinstance(step, ModelExecutionStep) for step in result.steps) <= 2
                  and sum(isinstance(step, ToolExecutionStep) for step in result.steps) <= 1)
        tool = result.tool_result if legacy else None
        call_id = result.tool_call_id if legacy else None
        name = result.tool_name if legacy else None
        duration = result.tool_duration_ms if legacy else None
        steps = []
        for step in result.steps:
            if isinstance(step, ModelExecutionStep):
                steps.append({"seq": step.seq, "kind": "model", "request_index": step.request_index,
                              "request_started": step.request_started,
                              **_model_outcome(step.result)})
            else:
                steps.append({"seq": step.seq, "kind": "tool", "model_request_index": step.model_request_index,
                    "tool_round": step.tool_round,
                    "tool_call_id": step.tool_call_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", step.tool_call_id) else None,
                    "tool_name": step.tool_name if step.tool_name in self.tool_names else "unknown_tool",
                    "result_status": step.result.status.value if step.result else None,
                    "handler_started": step.handler_started,
                    "duration_ms": round(step.duration_ms, 3) if step.duration_ms is not None else None})
                diagnostic = public_argument_diagnostic(step.result.argument_diagnostic) if step.result else None
                if diagnostic is not None:
                    steps[-1]["argument_diagnostic"] = diagnostic
        entry = {
            "kind": "read_only_tool_conversation",
            "application_mode": result.application_mode,
            "request_id": result.request_id, "trace_id": result.trace_id,
            "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
            "status": result.status.value, "error_code": result.error_code,
            "steps": steps,
            "legacy_projection_available": legacy,
            "model_request_1": _model_outcome(result.request_1) if legacy else None,
            "model_request_2": _model_outcome(result.request_2) if legacy else None,
            "tool_call_id": call_id if call_id and re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", call_id) else None,
            "tool_name": name if name in self.tool_names
                         else "unknown_tool" if name else None,
            "tool_result_status": tool.status.value if tool else None,
            "tool_duration_ms": round(duration, 3) if duration is not None else None,
            "final_finish_reason": result.final_finish_reason,
            "usage": asdict(result.usage), "timing": {"total_ms": round(total_ms, 3)},
        }
        if result.model_transport.value == "STREAMING":
            entry["model_transport"] = result.model_transport.value
        self._append(entry)

    def record_assistant(self, result, *, started_at: datetime, finished_at: datetime) -> None:
        """Final commit outcome and numeric history budgets; no conversation material."""
        entry = {"kind": "assistant_turn", "application_mode": "assistant",
            "preset_id": result.preset_id, "request_id": result.execution.request_id,
            "prompt_id": result.prompt_id,
            "trace_id": result.execution.trace_id, "status": result.status.value,
            "error_code": result.error_code, "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "timing": {"total_ms": result.total_latency_ms},
            "history_turns_received": result.context.history_turns_received,
            "history_turns_sent": result.context.history_turns_sent,
            "history_trimmed": result.context.history_trimmed,
            "history_bytes_sent": result.context.history_bytes_sent,
            "activity": result.to_dict()["activity"],
            "usage": asdict(result.execution.usage)}
        if result.execution.model_transport.value == "STREAMING":
            entry["model_transport"] = result.execution.model_transport.value
        self._append(entry)

    def _append(self, entry: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
