"""In-process AI service boundary. Neither contract accepts Flask/browser objects."""

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .runtime.assistant import AssistantRequest
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import ModelProfile
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_backend.tools.policy import ToolPolicy
from apps.monitoring.service import MonitoringService

from apps.ai_backend.tools.registry import ToolRegistry
from .execution import ExecutionDecision


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
    registry: ToolRegistry = field(repr=False)
    execution: ExecutionDecision = field(repr=False)
    policy_revision: str | None = field(default=None, repr=False)
    policy_source: str | None = field(default=None, repr=False)


class AssistantBackend(Protocol):
    """Explicitly injected application API; a Protocol is not authorization."""
    monitoring: MonitoringService
    epoch: str

    def availability(self) -> dict: ...
    def tool_authorization(self) -> dict: ...
    def save_tool_authorization(self, value: dict) -> dict: ...
    def bootstrap(self, device_id: str) -> dict: ...
    def prepare_turn(self, value: dict, *, transport=ToolModelTransport.NORMAL) -> PreparedAssistantTurn: ...
    def execute_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle) -> dict: ...
    def claim_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle) -> Callable[[],dict]: ...
