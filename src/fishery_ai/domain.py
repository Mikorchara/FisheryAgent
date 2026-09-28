"""Deterministic water-quality diagnosis; no model or network dependency."""

from __future__ import annotations

from .contracts import Freshness, Quality, RuleFinding, WaterQualityReading


class DiagnosisService:
    RULE_VERSION = "fishery-production-c400b7a-v1"

    def diagnose(self, reading: WaterQualityReading) -> tuple[RuleFinding, ...]:
        findings: list[RuleFinding] = []

        def add(code: str, severity: str, message: str, fact: str) -> None:
            findings.append(RuleFinding(code, severity, message, (fact,), self.RULE_VERSION))

        if reading.quality == Quality.INVALID:
            add("SENSOR_INVALID", "warning", "水质数据无效，无法作完整诊断", "quality")
        elif reading.quality == Quality.PARTIAL:
            add("SENSOR_PARTIAL", "warning", "部分水质数据缺失", "quality")
        if reading.freshness == Freshness.STALE:
            add("SENSOR_STALE", "warning", "水质快照已过期，请先复测", "observed_at")

        t = reading.temperature_c
        if t is not None:
            if t < 15:
                add("TEMP_CRITICAL_LOW", "critical", f"水温极低 ({t:g}°C)", "temperature_c")
            elif t < 20:
                add("TEMP_LOW", "warning", f"水温偏低 ({t:g}°C)", "temperature_c")
            elif t > 33:
                add("TEMP_CRITICAL_HIGH", "critical", f"水温过高 ({t:g}°C)", "temperature_c")
            elif t > 30:
                add("TEMP_HIGH", "warning", f"水温偏高 ({t:g}°C)", "temperature_c")

        p = reading.ph
        if p is not None:
            if p < 6.5:
                add("PH_CRITICAL_LOW", "critical", f"pH 过低 ({p:g})", "ph")
            elif p < 7.0:
                add("PH_LOW", "warning", f"pH 偏低 ({p:g})", "ph")
            elif p > 9.0:
                add("PH_CRITICAL_HIGH", "critical", f"pH 过高 ({p:g})", "ph")
            elif p > 8.5:
                add("PH_HIGH", "warning", f"pH 偏高 ({p:g})", "ph")

        o = reading.dissolved_oxygen_mg_l
        if o is not None:
            if o < 1.0:
                add("OXYGEN_CRITICAL_EXTREME", "critical", f"溶氧极低 ({o:g} mg/L)", "dissolved_oxygen_mg_l")
            elif o < 3.0:
                add("OXYGEN_CRITICAL_LOW", "critical", f"溶氧低 ({o:g} mg/L)", "dissolved_oxygen_mg_l")
            elif o < 5.0:
                add("OXYGEN_LOW", "warning", f"溶氧偏低 ({o:g} mg/L)", "dissolved_oxygen_mg_l")
        return tuple(findings)
