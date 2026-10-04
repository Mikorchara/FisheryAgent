"""Validate sim-v1 and normalize into the existing canonical domain contract."""

from __future__ import annotations

from datetime import datetime
import math

from ..contracts import WaterQualityReading, aware
from .models import READING_FIELDS, SIMULATION_SCHEMA_VERSION, SimulationPacket


class SimulationAdapter:
    def __init__(self, *, stale_after_s: float = 300):
        if (type(stale_after_s) not in (int, float) or
                not math.isfinite(stale_after_s) or stale_after_s < 0):
            raise ValueError("stale_after_s must be finite and nonnegative")
        self.stale_after_s = stale_after_s

    def to_reading(self, packet: SimulationPacket, *, retrieved_at: datetime) -> WaterQualityReading:
        if not isinstance(packet, SimulationPacket):
            raise ValueError("expected a SimulationPacket")
        if packet.schema_version != SIMULATION_SCHEMA_VERSION:
            raise ValueError("unsupported simulation schema_version")
        if not isinstance(packet.device_id, str) or not packet.device_id.strip():
            raise ValueError("device_id is required")
        if type(packet.sequence) is not int or packet.sequence < 0:
            raise ValueError("sequence must be a nonnegative integer")
        if set(packet.readings) - set(READING_FIELDS):
            raise ValueError("unknown simulation reading field")
        if not isinstance(packet.observed_at, datetime) or not isinstance(retrieved_at, datetime):
            raise ValueError("timestamps must be datetime values")
        aware(packet.observed_at)
        aware(retrieved_at)
        raw = {
            target: self._numeric_value(packet.readings.get(field))
            for field, target in zip(READING_FIELDS, ("temp", "ph", "oxygen"))
        }
        # Physical range, validity and freshness use the canonical contract.
        # Fishery diagnosis thresholds belong exclusively to DiagnosisService.
        return WaterQualityReading.from_raw(
            raw, observed_at=packet.observed_at, retrieved_at=retrieved_at,
            source=f"simulation:{packet.device_id}", stale_after_s=self.stale_after_s,
        )

    @staticmethod
    def _numeric_value(value: object) -> float | str | None:
        if value is None:
            return None
        if type(value) not in (int, float):
            # Including bool and numeric strings: sim-v1 uses JSON numbers.
            return "invalid"
        try:
            return float(value)
        except OverflowError:
            return "invalid"
