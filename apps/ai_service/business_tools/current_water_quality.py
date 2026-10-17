"""Current water Tool: unchanged definition, single capture and detached Monitoring DTO."""
from dataclasses import asdict
from apps.ai_backend.model_gateway import ModelToolDefinition

CURRENT_WATER_QUALITY = "get_current_water_quality"

WATER_TOOL_PROJECTION = "management-current-water@1"

WATER_DEFINITION = ModelToolDefinition(
    name=CURRENT_WATER_QUALITY,
    description=("只读查询当前水质数值、状态、告警；用于确认当前系统水质及其追问，不负责评分、等级或分项评分。"
                 "返回当前快照的水质观测、数据质量、新鲜度、观测与评估时间及确定性诊断。"
                 "NO_DATA表示查询完成但无快照；存在快照时OK不代表数据一定有效、完整或新鲜，须按quality/freshness说明INVALID、PARTIAL或STALE。"
                 "查询不等于重新采样。"),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
)


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
