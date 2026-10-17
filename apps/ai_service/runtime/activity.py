"""Bounded business metadata; generic step projection is owned by Backend."""
from apps.ai_backend.assistant_activity import _number, _timestamp, project_activity as _project_activity
from apps.ai_backend.tool_argument_diagnostics import public_argument_diagnostic
from .catalog import CATALOG, catalog_display
from ..business_tools.registry import KNOWN_TOOL_NAMES, HISTORY_CANDIDATE_TOOL_NAMES
from ..business_tools.water_quality_history import WATER_QUALITY_HISTORY, result_metadata as history_metadata

def tool_summary(step):
    """Only labels and limited business metadata, never query, facts or evidence text."""
    name = step.tool_name if step.tool_name in (*KNOWN_TOOL_NAMES, *HISTORY_CANDIDATE_TOOL_NAMES) else None
    result = step.result
    summary = {"used_tool": step.handler_started, "tool_name": name,
               "tool_status": result.status.value if result else None,
               "duration_ms": _number(step.duration_ms)}
    summary.update(catalog_display(name))
    summary["experimental"] = any(entry.name == name and entry.experimental for entry in CATALOG)
    if result is not None:
        diagnostic = public_argument_diagnostic(result.argument_diagnostic)
        if diagnostic is not None:
            summary["argument_diagnostic"] = diagnostic
        payload = result.payload
        if name == WATER_QUALITY_HISTORY:
            metadata = history_metadata(payload) if step.handler_started else None
            if metadata is not None:
                summary.update(source_type="historical_water", source_kind="simulator",
                    history_range={"start": metadata["history_range_start"], "end": metadata["history_range_end"]},
                    window_count=metadata["history_window_count"],
                    reliable_windows=dict(metadata["history_reliable_windows"]),
                    evaluated_at=metadata["evaluated_at"])
                # Reuse the Backend's existing bounded display field. Generic
                # Steps/polling need no new schema or raw history projection.
                counts = ", ".join(f"{key}={count}" for key, count in metadata["history_reliable_windows"])
                summary["display_summary"] = (f"历史水质 · simulator · {metadata['history_range_start']} → "
                    f"{metadata['history_range_end']} · 可靠窗口 {counts}")
            return summary
        water = payload.get("water_quality")
        water = water if isinstance(water, dict) else {}
        for key in ("quality", "freshness"):
            allowed = ("valid", "partial", "invalid") if key == "quality" else ("fresh", "stale")
            if water.get(key) in allowed:
                summary[key] = water[key]
        for key, value in (("observed_at", water.get("observed_at")),
                           ("evaluated_at", payload.get("evaluated_at"))):
            parsed = _timestamp(value)
            if parsed is not None:
                summary[key] = parsed
        count = payload.get("result_count")
        if (name == "search_fishery_knowledge" and type(count) is int and 0 <= count <= 100
                and isinstance(payload.get("evidence"), list) and count == len(payload["evidence"])):
            summary["evidence_count"] = count
    return summary


def project_activity(*args, **kwargs):
    return _project_activity(*args, **kwargs, summarize=tool_summary)
