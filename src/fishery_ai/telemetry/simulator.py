"""Compose baseline values and explicit overrides; no physical simulation."""

from __future__ import annotations

from datetime import datetime
import math

from ..contracts import aware
from .models import READING_FIELDS, SimulationPacket, SimulationRecipe


class TelemetrySimulator:
    def __init__(self, *, device_id: str = "sim-device-001",
                 baseline: SimulationRecipe | None = None):
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("device_id is required")
        self.device_id = device_id
        recipe = baseline if baseline is not None else SimulationRecipe()
        self._baseline = {field: getattr(recipe, field) for field in READING_FIELDS}
        for value in self._baseline.values():
            self._validate_number(value)
        self._overrides: dict[str, object] = {}
        self._sequence = 0

    @staticmethod
    def _validate_number(value: object) -> None:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("simulation values must be finite numbers; use invalid() for a fault")

    def _set(self, field: str, value: float) -> TelemetrySimulator:
        self._validate_number(value)
        self._overrides[field] = value
        return self

    def set_temperature(self, value: float) -> TelemetrySimulator:
        return self._set("temperature_c", value)

    def set_ph(self, value: float) -> TelemetrySimulator:
        return self._set("ph", value)

    def set_do(self, value: float) -> TelemetrySimulator:
        return self._set("dissolved_oxygen_mg_l", value)

    def missing(self, field: str) -> TelemetrySimulator:
        return self._fault(field, None)

    def invalid(self, field: str) -> TelemetrySimulator:
        return self._fault(field, "invalid")

    def _fault(self, field: str, value: object) -> TelemetrySimulator:
        if field not in READING_FIELDS:
            raise ValueError("unknown simulation reading field")
        self._overrides[field] = value
        return self

    def generate(self, *, observed_at: datetime) -> SimulationPacket:
        """Explicit timestamps make fresh/stale fixtures reproducible."""
        aware(observed_at)
        self._sequence += 1
        return SimulationPacket(self.device_id, observed_at,
                                self._baseline | self._overrides,
                                sequence=self._sequence)
