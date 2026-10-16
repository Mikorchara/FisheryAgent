"""Small allowlisted projection of execution steps; never a second tool payload."""

from datetime import datetime
import math
import re

from .tool_argument_diagnostics import public_argument_diagnostic


STATES = {"RUNNING", "CANCEL_REQUESTED", "COMPLETED", "CANCELLED", "FAILED"}
OUTCOMES = {"not_started", "received", "tool_calls", "final_answer", "blocked", "failed",
            "cancelled", "multiple_tool_calls", "tool_round_limit"}
FINISH_REASONS = {"stop", "length", "tool_calls", "function_call", "content_filter"}


def safe_code(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) else None


def _number(value):
    return round(value, 3) if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def safe_usage(usage):
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "cached_input_tokens"):
        value = getattr(usage, key, None)
        result[key] = value if type(value) is int and value >= 0 else None
    source = getattr(usage, "source", "unavailable")
    result["source"] = source if source in ("provider", "unavailable") else "unavailable"
    return result


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def tool_summary(step, summarize=None):
    result = step.result
    summary = {"used_tool": step.handler_started, "tool_name": None,
               "tool_status": result.status.value if result else None,
               "duration_ms": _number(step.duration_ms)}
    if result is not None:
        diagnostic = public_argument_diagnostic(result.argument_diagnostic)
        if diagnostic is not None:
            summary["argument_diagnostic"] = diagnostic
    if summarize is not None:
        # Fixed application callback, never model/browser-supplied metadata. Only
        # these established fields may cross the backend Activity boundary.
        supplied = summarize(step)
        for key, limit in (("tool_name", 64), ("display_name", 80), ("display_summary", 256)):
            value = supplied.get(key)
            if isinstance(value, str) and 0 < len(value) <= limit:
                if key != "tool_name" or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
                    summary[key] = value
        if type(supplied.get("experimental")) is bool:
            summary["experimental"] = supplied["experimental"]
        for key, allowed in (("quality", ("valid", "partial", "invalid")), ("freshness", ("fresh", "stale"))):
            if supplied.get(key) in allowed:
                summary[key] = supplied[key]
        for key in ("observed_at", "evaluated_at"):
            stamp = _timestamp(supplied.get(key))
            if stamp is not None:
                summary[key] = stamp
        count = supplied.get("evidence_count")
        if type(count) is int and 0 <= count <= 100:
            summary["evidence_count"] = count
    return summary


def settle_activity(activity, state, error_code=None):
    """Resolve only unfinished steps, retaining all completed audit observations."""
    activity["state"] = state
    activity["safe_error_code"] = safe_code(error_code)
    if state in ("FAILED", "CANCELLED"):
        for step in activity["steps"]:
            if step["state"] in ("RUNNING", "ATTEMPTING"):
                step["state"] = state
                step["safe_error_code"] = safe_code(error_code)
    return activity


def project_activity(steps, *, request_id, budget, state="RUNNING", error_code=None,
                     revision=0, phase=None, total_latency_ms=None, summarize=None):
    from .tool_conversation import ModelExecutionStep, _aggregate_usage
    rows, usages = [], []
    for step in steps:
        if isinstance(step, ModelExecutionStep):
            outcome = step.result.outcome if step.result.outcome in OUTCOMES else "failed"
            step_state = ("CANCELLED" if step.result.error_code == "USER_CANCELLED" or outcome == "cancelled" else
                ("RUNNING" if step.request_started else "ATTEMPTING") if outcome in ("not_started", "received") else
                "REJECTED" if outcome == "blocked" else
                "FAILED" if outcome in ("failed", "multiple_tool_calls", "tool_round_limit") else "COMPLETED")
            rows.append({"seq": step.seq, "kind": "model", "request_index": step.request_index,
                "request_started": step.request_started,
                "state": step_state, "outcome": outcome, "safe_error_code": safe_code(step.result.error_code),
                "finish_reason": step.result.finish_reason if step.result.finish_reason in FINISH_REASONS else None,
                "usage": safe_usage(step.result.usage)})
            diagnostic = public_argument_diagnostic(step.result.argument_diagnostic)
            if diagnostic is not None:
                rows[-1]["argument_diagnostic"] = diagnostic
            if outcome not in ("not_started", "blocked"):
                usages.append(step.result.usage)
        else:
            summary = tool_summary(step, summarize)
            code = step.result.error_code.value if step.result and step.result.error_code else None
            step_state = ("FAILED" if step.handler_started else "REJECTED") if code else (
                "COMPLETED" if step.result else "RUNNING" if step.handler_started else "ATTEMPTING")
            rows.append({"seq": step.seq, "kind": "tool", "model_request_index": step.model_request_index,
                "tool_round": step.tool_round, "state": step_state, "handler_started": step.handler_started,
                "safe_error_code": safe_code(code), "result_status": summary.pop("tool_status"), **summary})
    usage = _aggregate_usage(usages)
    return settle_activity({"activity_schema_version": 2, "request_id": request_id,
        "revision": revision, "phase": phase, "current_step_seq": rows[-1]["seq"] if rows else None,
        "budget": {"tool_calls": budget.max_tool_calls, "tool_rounds": budget.max_tool_rounds,
                   "model_requests": budget.max_model_requests},
        "counts": {"model_requests_started": sum(row.get("request_started", False) for row in rows),
                   "tool_attempts": sum(row["kind"] == "tool" for row in rows),
                   "tools_executed": sum(row.get("handler_started", False) for row in rows)},
        "steps": rows, "aggregate_usage": safe_usage(usage.usage),
        "total_latency_ms": _number(total_latency_ms)}, state if state in STATES else "FAILED", error_code)
