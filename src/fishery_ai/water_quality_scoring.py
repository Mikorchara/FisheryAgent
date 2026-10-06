"""EXPERIMENTAL / NOT PROFESSIONAL STANDARD. No I/O or model dependency."""

from dataclasses import dataclass, asdict
from types import MappingProxyType

from .contracts import Freshness, Quality, WaterQualityReading
from .domain import DiagnosisService


@dataclass(frozen=True)
class WaterQualityScore:
    status: str
    score: float | None
    grade: str | None
    components: dict
    quality: str | None
    freshness: str | None
    missing_components: tuple[str, ...] = ()
    partial: bool = False
    warnings: tuple[str, ...] = ()
    scoring_version: str = "experimental-water-quality-score-v1"
    standard: str = "EXPERIMENTAL / NOT PROFESSIONAL STANDARD"

    def to_dict(self):
        return asdict(self)


class WaterQualityScoringService:
    PENALTY_RATES = MappingProxyType({"temperature": 10.0, "ph": 40.0, "dissolved_oxygen": 20.0})

    def score(self, reading: WaterQualityReading | None) -> WaterQualityScore:
        if reading is None:
            return WaterQualityScore("NO_DATA", None, None, {}, None, None)
        values = {"temperature": reading.temperature_c, "ph": reading.ph,
                  "dissolved_oxygen": reading.dissolved_oxygen_mg_l}
        missing = tuple(key for key, value in values.items() if value is None)
        warnings = ("SENSOR_STALE",) if reading.freshness == Freshness.STALE else ()
        if reading.quality == Quality.INVALID:
            return WaterQualityScore("NOT_SCORABLE", None, None, {}, reading.quality.value,
                                     reading.freshness.value, missing, warnings=warnings)
        components = {}
        scores = []
        ranges = {"temperature": DiagnosisService.TEMP_NORMAL, "ph": DiagnosisService.PH_NORMAL}
        for key, value in values.items():
            if value is None:
                continue
            if key in ranges:
                lower, upper = ranges[key]
                distance = max(lower - value, value - upper, 0.0)
                reference = {"normal_range": list(ranges[key])}
            else:
                distance = max(DiagnosisService.OXYGEN_NORMAL_MIN - value, 0.0)
                reference = {"normal_min": DiagnosisService.OXYGEN_NORMAL_MIN}
            component = min(100.0, max(0.0, 100.0 - distance * self.PENALTY_RATES[key]))
            scores.append(component)
            components[key] = {"value": value, "score": round(component, 1), **reference}
        # Average unrounded component values; round only the displayed final score.
        final = round(sum(scores) / len(scores), 1)
        grade = "GOOD" if final >= 90 else "ACCEPTABLE" if final >= 70 else "WARNING" if final >= 50 else "CRITICAL"
        partial = reading.quality == Quality.PARTIAL
        return WaterQualityScore("PARTIAL" if partial else "OK", final, grade, components,
                                 reading.quality.value, reading.freshness.value, missing, partial, warnings)
