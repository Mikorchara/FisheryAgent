"""Web service Protocols; shared monitoring DTOs have one canonical definition."""

from typing import Protocol

from apps.monitoring.contracts import MetricObservation, MonitoringSnapshot


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
