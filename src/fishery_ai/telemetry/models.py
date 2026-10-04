"""Simulation-only contracts; sim-v1 is not a hardware packet protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping


SIMULATION_SCHEMA_VERSION = "sim-v1"
READING_FIELDS = ("temperature_c", "ph", "dissolved_oxygen_mg_l")


@dataclass(frozen=True)
class SimulationRecipe:
    """Baseline values, without any business diagnosis thresholds."""

    temperature_c: float = 28.0
    ph: float = 7.5
    dissolved_oxygen_mg_l: float = 6.4


@dataclass(frozen=True)
class SimulationPacket:
    device_id: str
    observed_at: datetime
    readings: Mapping[str, object]
    sequence: int = 0
    schema_version: str = SIMULATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        # A later simulator override cannot change an already emitted packet.
        object.__setattr__(self, "readings", MappingProxyType(dict(self.readings)))
