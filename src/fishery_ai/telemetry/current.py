"""Read current facts without simulation, mutation or missing-data fallback."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from ..contracts import WaterQualityReading, evaluate_freshness, utcnow
from .snapshot import CurrentSnapshotStore


@dataclass(frozen=True)
class CurrentWaterQualityView:
    reading: WaterQualityReading
    evaluated_at: datetime


class CurrentWaterQualityReader:
    def __init__(self, snapshot_store: CurrentSnapshotStore, *, stale_after_s: float,
                 clock: Callable[[], datetime] = utcnow):
        self._snapshot_store = snapshot_store
        self._stale_after_s = stale_after_s
        self._clock = clock

    def query(self) -> CurrentWaterQualityView | None:
        """Capture once; preserve ingestion metadata and leave the Store untouched."""
        reading = self._snapshot_store.get_current()
        if reading is None:
            return None
        evaluated_at = self._clock()
        freshness = evaluate_freshness(reading.observed_at, evaluated_at, self._stale_after_s)
        return CurrentWaterQualityView(replace(reading, freshness=freshness), evaluated_at)
