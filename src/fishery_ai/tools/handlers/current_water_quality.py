"""Canonical current-state read only; no scenario generation or I/O."""

from ...domain import DiagnosisService
from ...telemetry.current import CurrentWaterQualityReader


def water_quality_facts(reading) -> dict:
    return {
        "temperature_c": reading.temperature_c, "ph": reading.ph,
        "dissolved_oxygen_mg_l": reading.dissolved_oxygen_mg_l,
        "quality": reading.quality.value, "freshness": reading.freshness.value,
        "observed_at": reading.observed_at.isoformat(), "retrieved_at": reading.retrieved_at.isoformat(),
        "source": reading.source,
    }


def get_current_water_quality(*, reader: CurrentWaterQualityReader,
                              diagnosis: DiagnosisService) -> dict:
    view = reader.query()
    if view is None:
        return {"status": "NO_DATA", "water_quality": None, "findings": []}
    reading = view.reading
    findings = diagnosis.diagnose(reading)
    return {
        "status": "OK",
        "water_quality": water_quality_facts(reading),
        "evaluated_at": view.evaluated_at.isoformat(),
        "findings": [{"code": finding.code, "severity": finding.severity,
                      "message": finding.message, "facts_used": list(finding.facts_used),
                      "rule_version": finding.rule_version} for finding in findings],
        "rule_version": diagnosis.RULE_VERSION,
    }
