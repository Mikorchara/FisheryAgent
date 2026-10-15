"""In-process AI service boundary. Neither contract accepts Flask/browser objects."""

from dataclasses import dataclass, field
from typing import Protocol

from fishery_ai.assistant import AssistantRequest
from fishery_ai.execution import RequestHandle
from fishery_ai.model_gateway import ModelProfile
from fishery_ai.tools.policy import ToolPolicy
from apps.monitoring.service import MonitoringService

from .bindings import ManagementToolRegistry


@dataclass(frozen=True)
class PreparedAssistantTurn:
    """Server-only, ephemeral frozen configuration; never a browser request/response.

    Contains existing contracts, no new model/history/credential representation.
    It holds no resolved CredentialSnapshot; resolve once at execution as before.
    """
    request: AssistantRequest = field(repr=False)
    device_id: str = field(repr=False)
    epoch: str = field(repr=False)
    profile: ModelProfile = field(repr=False)
    policy: ToolPolicy = field(repr=False)
    registry: ManagementToolRegistry = field(repr=False)


class AssistantBackend(Protocol):
    """Explicitly injected application API; a Protocol is not authorization."""
    monitoring: MonitoringService
    epoch: str

    def availability(self) -> dict: ...
    def bootstrap(self, device_id: str) -> dict: ...
    def prepare_turn(self, value: dict) -> PreparedAssistantTurn: ...
    def execute_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle) -> dict: ...
