"""Monitoring and Knowledge bindings; handlers return detached JSON, never old Runtime types."""
from dataclasses import asdict
from functools import partial
from apps.ai_backend.tools import ToolRegistry, ToolDefinition
from .runtime.tools import WATER_DEFINITION, KNOWLEDGE_DEFINITION, validate_arguments, search_fishery_knowledge

WATER_TOOL_PROJECTION = "management-current-water@1"
KNOWLEDGE_BINDING_VERSION = "management-project-knowledge@1"


def water_payload(monitoring, device_id):
    return project_water_tool(monitoring.capture_water(device_id))


def project_water_tool(capture):
    """Detached Tool DTO from one capture; no Web history, fetch or diagnosis."""
    analysis, reading = capture.analysis, capture.reading
    ref, quality = analysis.observation, analysis.data_quality
    result = {"projection_version": WATER_TOOL_PROJECTION,
        "status": "OK" if ref else "NO_DATA", "water_quality": None,
        "device_id": analysis.device_id, "channel": analysis.channel, "batch_id": ref.batch_id if ref else None,
        "source_kind": ref.source_kind if ref else "simulator",
        "evaluated_at": analysis.evaluated_at, "last_reported_at": capture.last_reported_at,
        "connectivity": quality.connectivity, "data_quality": asdict(quality),
        "rule_version": capture.rule_version, "findings": []}
    if ref is None:
        return result
    result.update({"water_quality": {
        **{m.id: getattr(reading, m.id) for m in capture.metrics},
        "quality": reading.quality.value, "freshness": reading.freshness.value,
        "observed_at": reading.observed_at.isoformat(), "retrieved_at": reading.retrieved_at.isoformat(),
        "source": reading.source},
        "window": {"start": ref.window_start, "end": ref.window_end, "duration_s": ref.window_duration_s},
        "aggregation": ref.aggregation, "statistics_version": ref.statistics_version,
        "metrics": {m.id: {"unit": m.unit, "quality": m.quality,
            "invalid_samples": m.invalid_samples} for m in capture.metrics},
        # All outcomes matter, especially insufficient evidence / not evaluated.
        # Observation identity is shared above, not repeated for every finding.
        "findings": [{"code": f.code, "kind": f.kind, "state": f.state.value,
            "severity": f.severity, "message": f.message, "facts_used": list(f.facts_used),
            "reason": f.reason, "rule": asdict(f.rule)} for f in analysis.findings]})
    return result




def bind_tools(monitoring, device_id, knowledge, *, formal=None):
    # Definitions have one application owner. Rebind only the frozen device's
    # read handler; preserve the same shared Knowledge service and contract.
    water_definition = formal.lookup(WATER_DEFINITION.name).model_definition if formal else WATER_DEFINITION
    knowledge_entry = formal.lookup(KNOWLEDGE_DEFINITION.name) if formal else ToolDefinition(
        KNOWLEDGE_DEFINITION, partial(search_fishery_knowledge, service=knowledge),
        validate_arguments=validate_arguments)
    return ToolRegistry((
        ToolDefinition(water_definition, partial(water_payload, monitoring, device_id)), knowledge_entry))
