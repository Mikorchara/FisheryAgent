"""Small UI-facing contracts; independent of devices, storage and Provider SDKs."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MetricObservation:
    id: str
    label: str
    value: float | None
    unit: str
    quality: str
    source: str
    observed_at: str | None
    freshness: str


@dataclass(frozen=True)
class MonitoringSnapshot:
    device_id: str
    source: str
    source_kind: str
    observed_at: str | None
    evaluated_at: str
    quality: str
    freshness: str
    metrics: tuple[MetricObservation, ...]
    trend: tuple[dict, ...]


class MonitoringData(Protocol):
    def devices(self) -> list[dict]: ...

    def snapshot(self, device_id: str, view: str = "available") -> MonitoringSnapshot: ...


class AIService(Protocol):
    def availability(self) -> dict: ...

    def send(self, request: dict) -> dict: ...


class VideoDetection(Protocol):
    def cameras(self) -> list[dict]: ...


class KnowledgeFiles(Protocol):
    def files(self) -> list[dict]: ...


class EventRecords(Protocol):
    def events(self) -> list[dict]: ...
