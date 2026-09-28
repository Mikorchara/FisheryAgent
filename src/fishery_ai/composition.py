"""Minimal composition root for the offline V0.1 demo."""

from pathlib import Path
from importlib.resources import files

from .application import Orchestrator
from .domain import DiagnosisService
from .knowledge import KnowledgeService
from .model_gateway import MockGateway, ProfileRegistry
from .observability import JsonlTraceSink
from .repositories import MockRepository


RESOURCE_ROOT = files("fishery_ai").joinpath("resources")


def build_offline_demo(*, trace_path: Path | None = None, stale_after_s: float = 300
                       ) -> tuple[Orchestrator, MockGateway]:
    repository = MockRepository(RESOURCE_ROOT.joinpath("mock/scenarios.json"), stale_after_s=stale_after_s)
    knowledge = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
    profiles = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath("mock/profiles.json"))
    gateway = MockGateway()
    traces = JsonlTraceSink(trace_path or Path.cwd() / "outputs/mock-traces.jsonl")
    return Orchestrator(repository, DiagnosisService(), knowledge, profiles, gateway, traces,
                        resolve_secrets=False), gateway
