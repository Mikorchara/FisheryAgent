"""Handwritten timelines. Add phases here without changing generation or HTTP code."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Phase:
    at_s: float
    temperature_c: float = 26.4
    ph: float = 7.5
    dissolved_oxygen_mg_l: float = 6.4
    lesion_rate: float = 0
    surface_rate: float = 0
    death_rate: float = 0
    reduced_activity: float = .05
    feeding: float = .1
    feeding_anomaly: float = 0
    unknown_behavior: float = .02
    online: bool = True
    water_online: bool = True
    visual_online: bool = True
    missing_metric: str | None = None
    invalid_metric: str | None = None
    calibrated: bool = False


SCENARIOS = {
    "normal": (Phase(0), Phase(180)),
    "low_oxygen": (Phase(0), Phase(60, dissolved_oxygen_mg_l=4.2), Phase(120, dissolved_oxygen_mg_l=2.2, reduced_activity=.5)),
    # One drop/recovery episode, then hold normal. Values are fictional observations.
    "oxygen_drop_recovery": (Phase(0), Phase(20),
        Phase(50, dissolved_oxygen_mg_l=2.2, reduced_activity=.5),
        Phase(90, dissolved_oxygen_mg_l=2.2, reduced_activity=.5),
        Phase(180, dissolved_oxygen_mg_l=4.2, reduced_activity=.2),
        Phase(300), Phase(360)),
    "suspected_disease": (Phase(0), Phase(30, lesion_rate=.3, surface_rate=.25), Phase(120, lesion_rate=.6, surface_rate=.4, death_rate=.08)),
    "reduced_feeding": (Phase(0, feeding=.5), Phase(60, feeding=.05, feeding_anomaly=.6, reduced_activity=.25)),
    "combined_anomaly": (Phase(0), Phase(60, temperature_c=32, dissolved_oxygen_mg_l=3.8, lesion_rate=.3, feeding_anomaly=.3),
                         Phase(120, temperature_c=34, dissolved_oxygen_mg_l=2.2, lesion_rate=.6, surface_rate=.4, feeding_anomaly=.5)),
    "device_offline": (Phase(0), Phase(30, online=False)),
    "partial": (Phase(0, missing_metric="dissolved_oxygen_mg_l"),),
    "invalid": (Phase(0, invalid_metric="ph"),),
    "visual_only": (Phase(0, water_online=False, surface_rate=.3),),
    "water_only": (Phase(0, visual_online=False),),
}


def at_time(phases, elapsed_s):
    """Continuous numeric interpolation, discrete channel changes at phase boundaries."""
    left = phases[0]
    right = left
    for phase in phases[1:]:
        if elapsed_s >= phase.at_s:
            left = phase
        else:
            right = phase
            break
    else:
        right = left
    fraction = 0 if right.at_s <= left.at_s else (elapsed_s-left.at_s)/(right.at_s-left.at_s)
    numeric = ("temperature_c", "ph", "dissolved_oxygen_mg_l", "lesion_rate", "surface_rate", "death_rate",
               "reduced_activity", "feeding", "feeding_anomaly", "unknown_behavior")
    result = {key: getattr(left, key)+(getattr(right, key)-getattr(left, key))*fraction for key in numeric}
    result.update({key: getattr(left, key) for key in ("online", "water_online", "visual_online", "missing_metric", "invalid_metric", "calibrated")})
    return result
