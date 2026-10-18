"""Web-only Assistant adapter: browser token and existing request control APIs."""

from pathlib import Path
import secrets

from apps.ai_backend.execution import RequestRegistry
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_service.contracts import AssistantBackend
from apps.ai_service.runtime.activity import tool_summary
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.history_execution import HISTORY_PROFILE


class ManagementAssistant:
    """Explicit Web opt-in; the backend owns business/runtime/Tool composition."""

    def __init__(self, backend: AssistantBackend):
        self.backend = backend
        self.browser_token = secrets.token_urlsafe(32)
        self.requests = RequestRegistry(summarize_tool=tool_summary)

    @classmethod
    def local(cls, monitoring, project_root, *, multi_round_trial=False, streaming_trial=False, history_trial=False,
              unified_tools_trial=False, knowledge=None):
        return cls(ManagementAssistantService.local(monitoring, Path(project_root),
            multi_round_trial=multi_round_trial, streaming_trial=streaming_trial, history_trial=history_trial,
            unified_tools_trial=unified_tools_trial, **({'knowledge':knowledge} if knowledge is not None else {})))

    @property
    def monitoring(self):
        return self.backend.monitoring

    @property
    def epoch(self):
        return self.backend.epoch

    def availability(self):
        return self.backend.availability()

    def bootstrap(self, device_id):
        value = dict(self.backend.bootstrap(device_id))
        # Business capability only. Internal execution identifiers are not Web inputs.
        history = value.pop('history_candidate', None)
        if history is not None:
            history = {key: item for key, item in history.items() if key != 'execution_profile'}
        return {**value, **({'history_query': history} if history is not None else {}),
                "browser_token": self.browser_token}

    def tool_authorization(self):
        return {**self.backend.tool_authorization(), 'browser_token':self.browser_token}

    def save_tool_authorization(self, value):
        return {**self.backend.save_tool_authorization(value), 'browser_token':self.browser_token}

    def prepare(self):
        handle = self.requests.create()
        return {"request_id": handle.request_id, "control_token": handle.control_token}

    def handle(self, value):
        return self.requests.get(value.get("request_id"), value.get("control_token"))

    def send(self, value):
        prepared, handle = self._prepare(value)
        return self.backend.execute_turn(prepared,handle)

    def claim_stream(self,value):
        prepared, handle = self._prepare(value,transport=ToolModelTransport.STREAMING)
        return prepared,handle,self.backend.claim_turn(prepared,handle)

    def _prepare(self,value,*,transport=ToolModelTransport.NORMAL):
        allowed = {"preset_id", "question", "history", "conversation_id", "epoch", "device_id",
                   "revision", "confirm_network", "request_id", "control_token", "action"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        # Preserve preflight-before-handle-claim order and freeze just one plan.
        body={k:v for k,v in value.items() if k not in {"request_id", "control_token"}}
        if 'action' in body:
            if body.pop('action') != 'history_query':
                raise GatewayError('INVALID_ASSISTANT_REQUEST')
            body['execution_profile'] = HISTORY_PROFILE
        # Keep the Normal service call contract unchanged.
        prepared = (self.backend.prepare_turn(body) if transport == ToolModelTransport.NORMAL else
                    self.backend.prepare_turn(body,transport=transport))
        return prepared,self.handle(value)
