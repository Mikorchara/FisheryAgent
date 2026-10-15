"""Management Tool bindings and DTO projection; no HTTP or orchestration."""

from dataclasses import asdict, replace
from types import MappingProxyType

from fishery_ai.tools.contracts import ToolError, ToolErrorCode
from fishery_ai.tools.registry import ToolRegistry, CURRENT_WATER_QUALITY, SEARCH_FISHERY_KNOWLEDGE


WATER_TOOL_PROJECTION = "management-current-water@1"


class ManagementToolRegistry:
    """Keep formal contracts/Knowledge handler; replace only the water data binding."""
    registered_names = staticmethod(ToolRegistry.registered_names)

    def __init__(self, formal, monitoring, device_id):
        self._entries = MappingProxyType({
            CURRENT_WATER_QUALITY: replace(formal.lookup(CURRENT_WATER_QUALITY),
                handler=lambda: water_payload(monitoring, device_id)),
            SEARCH_FISHERY_KNOWLEDGE: formal.lookup(SEARCH_FISHERY_KNOWLEDGE)})

    def lookup(self, name):
        if name not in self._entries:
            raise ToolError(ToolErrorCode.UNKNOWN_TOOL)
        return self._entries[name]

    def model_definitions(self):
        return tuple(entry.model_definition for entry in self._entries.values())


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

