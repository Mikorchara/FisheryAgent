"""Process-local storage of the last explicitly supplied canonical reading."""

from __future__ import annotations

from ..contracts import WaterQualityReading


class CurrentSnapshotStore:
    def __init__(self) -> None:
        self._current: WaterQualityReading | None = None

    def set_current(self, reading: WaterQualityReading) -> None:
        if not isinstance(reading, WaterQualityReading):
            raise ValueError("snapshot must be a WaterQualityReading")
        self._current = reading

    def get_current(self) -> WaterQualityReading | None:
        return self._current
