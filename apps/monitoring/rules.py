"""Small pure assessment functions; no database, Web, model or threshold copy.

DomainAnalysisService owns time/context evaluation and calls these rules.
Inputs are validated server facts. CLEAR is explicit evidence, never absence.
"""

from datetime import datetime

from fishery_ai.contracts import WaterQualityReading, Quality, Freshness
from fishery_ai.domain import DiagnosisService

from .contracts import (METRICS, ObservationRef, DataQuality, RuleIdentity,
                        MonitoringFinding, FindingState, ChannelAnalysis, water_metric_facts)


WATER_RULES = {
    "temperature_c": ("TEMP_CRITICAL_LOW", "TEMP_LOW", "TEMP_HIGH", "TEMP_CRITICAL_HIGH"),
    "ph": ("PH_CRITICAL_LOW", "PH_LOW", "PH_HIGH", "PH_CRITICAL_HIGH"),
    "dissolved_oxygen_mg_l": ("OXYGEN_CRITICAL_EXTREME", "OXYGEN_CRITICAL_LOW", "OXYGEN_LOW"),
}
VISUAL_RULES = {
    "SUSPECTED_LESION": ("suspected_lesion", "疑似病灶检测信号（模拟，非诊断）"),
    "SURFACE_ANOMALY": ("surface_anomaly", "体表异常检测信号（模拟）"),
    "SUSPECTED_DEAD": ("suspected_dead", "疑似死亡个体检测信号（模拟，需核查）"),
    "FEEDING_ANOMALY": ("feeding_anomaly", "摄食异常行为信号（模拟）"),
}
VISUAL_VERSION = "sim-visual-presence-v1"
QUALITY_VERSION = "monitoring-data-quality-v1"


def rule_identity(code, channel, diagnosis):
    version = (diagnosis.RULE_VERSION if code in {c for codes in WATER_RULES.values() for c in codes}
               else VISUAL_VERSION if code in VISUAL_RULES else QUALITY_VERSION)
    return RuleIdentity(code, version, ("simulator", channel,
        "window_mean" if channel == "water" else "window_summary", "husbandry_applicability_unconfirmed"))


def observation_ref(row, channel):
    if row is None:
        return None
    window, data = row["payload"]["window"], row["payload"]["data"]
    return ObservationRef(row["device_id"], channel, row["batch_id"], row["observed_at"], row["received_at"],
        window["start"], window["end"], window["duration_s"], data["aggregation"],
        statistics_version=data.get("model_version") if channel == "visual" else "window_mean-v1")


def assess_channel(device_id, channel, row, *, evaluated_at, freshness, connectivity, diagnosis,
                   water_metrics=None):
    """Per-channel assessment retaining its own time/window. No cross-channel inference."""
    if channel not in ("water", "visual"):
        raise ValueError("INVALID_ANALYSIS_CHANNEL")
    ref = observation_ref(row, channel)
    data = row["payload"]["data"] if row else None
    coverage = ()
    if data is None:
        quality = "missing"
    elif channel == "water":
        water_metrics = water_metric_facts(data) if water_metrics is None else water_metrics
        qualities = [m.quality for m in water_metrics]
        quality = ("invalid" if "invalid" in qualities else "missing" if all(q == "missing" for q in qualities)
                   else "valid" if all(q == "valid" for q in qualities) else "partial")
        coverage = tuple((m.id, m.valid_samples, m.sample_count) for m in water_metrics)
    else:
        valid, total = data.get("valid_frames", data["frames_processed"]), data["frames_processed"]
        quality = "invalid" if valid == 0 else "valid" if valid == total else "partial"
        coverage = (("frames", valid, total),)
    dq = DataQuality(quality, freshness, connectivity, coverage)
    findings = []

    def add(code, kind, state, message, fields=(), severity=None, reason=None):
        findings.append(MonitoringFinding(code, kind, state, severity, message, tuple(fields),
            rule_identity(code, channel, diagnosis), ref, reason))

    for code, hit, message in (
        ("SENSOR_INVALID", quality == "invalid", "观测数据无效，不能作为完整风险证据"),
        ("SENSOR_PARTIAL", quality == "partial", "观测覆盖不完整，仅可判断完整有效的部分"),
        ("SENSOR_MISSING", quality == "missing", "缺少可用观测，不代表正常"),
        ("SENSOR_STALE", freshness == "stale", "观测已过期，无法确认当前风险或恢复"),
        ("DEVICE_OFFLINE", connectivity == "offline", "设备上报中断，无法确认当前风险或恢复"),
    ):
        state = FindingState.HIT if hit else FindingState.CLEAR if data else FindingState.NOT_EVALUATED
        add(code, "DATA_QUALITY", state, message if hit else "数据状态条件未命中" if data else "尚无该通道观测",
            ("quality", "freshness", "connectivity"), "warning" if hit else None,
            "NO_DATA" if data is None else None)

    current = data is not None and freshness == "fresh" and connectivity == "online"
    if channel == "water":
        usable = {m.id: current and m.quality == "valid" for m in water_metrics} if data else dict.fromkeys(METRICS, False)
        values = [m.mean if usable[m.id] else None for m in water_metrics] if data else [None] * len(METRICS)
        present = sum(v is not None for v in values)
        hits = {}
        if present:
            reading = WaterQualityReading(*values, datetime.fromisoformat(row["observed_at"]),
                datetime.fromisoformat(row["received_at"]), "simulator:"+device_id+":window_mean",
                Quality.VALID if present == 3 else Quality.PARTIAL, Freshness.FRESH)
            hits = {f.code: f for f in diagnosis.diagnose(reading) if any(k in METRICS for k in f.facts_used)}
        for metric, codes in WATER_RULES.items():
            for code in codes:
                hit = hits.get(code)
                state = (FindingState.HIT if hit else FindingState.CLEAR if usable[metric]
                         else FindingState.NOT_EVALUATED if not current else FindingState.INSUFFICIENT_EVIDENCE)
                add(code, "WATER_RISK", state, hit.message if hit else "该条件未命中" if usable[metric] else "无法判断该指标当前风险或恢复",
                    (metric,), hit.severity if hit else None,
                    None if usable[metric] else "NO_DATA" if data is None else "STALE_OR_OFFLINE" if not current else "METRIC_NOT_RELIABLE")
    else:
        for code, (field, message) in VISUAL_RULES.items():
            positive = bool(data and (data["behavior_ratios"][field] > 0 if code == "FEEDING_ANOMALY" else data["anomaly_counts"][field] > 0))
            # A partial valid frame can prove a signal occurred, never prove its absence.
            hit = current and quality != "invalid" and positive
            clear = current and quality == "valid" and not positive
            state = (FindingState.HIT if hit else FindingState.CLEAR if clear else
                     FindingState.NOT_EVALUATED if not current else FindingState.INSUFFICIENT_EVIDENCE)
            add(code, "BEHAVIOR_SIGNAL" if code == "FEEDING_ANOMALY" else "VISUAL_SIGNAL", state,
                message if hit else "所列信号未出现（不证明无疾病）" if clear else "缺乏当前有效视觉证据",
                (field,), "warning" if hit else None,
                None if hit or clear else "NO_DATA" if data is None else "STALE_OR_OFFLINE" if not current else "FRAME_COVERAGE_INSUFFICIENT")
    return ChannelAnalysis(device_id, channel, evaluated_at.isoformat(), ref, dq, tuple(findings))
