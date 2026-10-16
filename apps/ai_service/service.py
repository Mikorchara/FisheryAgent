"""Headless AI application composition; reuse the formal Assistant execution path."""

from importlib.resources import files
from dataclasses import replace
from pathlib import Path
import secrets
import threading

from fishery_ai.assistant import AssistantRequest, AssistantService, assistant_profile
from fishery_ai.assistant_activity import safe_code
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import RequestHandle, request_scope, turn_deadline_scope
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.model_gateway import GatewayError, ProfileRegistry
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.providers import AuthSpec
from fishery_ai.tools.policy import ToolPolicy, UserToolPolicyStore
from fishery_ai.tools.registry import ToolRegistry
from fishery_ai.tool_conversation import ToolCallingService, ToolModelTransport
from fishery_ai.history_projection import DEFAULT_HISTORY_PROJECTION

from . import bindings
from .contracts import PreparedAssistantTurn
from .execution import ManagementExecutionConfig, load_execution_config, resolve_execution
from .streaming import ManagementStreamingConfig, load_streaming_config, resolve_streaming


PRESETS = ("dashscope-qwen38-flash-r1", "ollama-qwen35-4b-r1")


class ManagementAssistantService:
    """One epoch and frozen device/policy/mode per turn; single-round by default."""

    def __init__(self, monitoring, *, credentials, traces, policy_directory,
                 gateway_factory=OpenAICompatibleAdapter, execution_config=None, streaming_config=None):
        self.monitoring, self.credentials, self.traces = monitoring, credentials, traces
        self.gateway_factory = gateway_factory
        self.epoch = secrets.token_hex(16)
        self._execution_config = load_execution_config() if execution_config is None else execution_config
        if not isinstance(self._execution_config, ManagementExecutionConfig):
            raise GatewayError('INVALID_MANAGEMENT_EXECUTION_CONFIG')
        self._streaming_config = load_streaming_config() if streaming_config is None else streaming_config
        if not isinstance(self._streaming_config, ManagementStreamingConfig):
            raise GatewayError('INVALID_MANAGEMENT_STREAMING_CONFIG')
        devices = monitoring.devices()
        if not devices:
            raise ValueError("NO_MONITORING_DEVICE")
        reader = monitoring.bind(devices[0]["id"]).water_reader
        # One KnowledgeService per application; use the original Registry binding.
        # The full Registry still validates existing Analysis/Assistant selections;
        # only the two management bindings below are eligible for execution.
        self.knowledge = KnowledgeService(files("fishery_ai").joinpath("resources/knowledge/eel_knowledge.json"))
        self.formal_registry = ToolRegistry(reader, monitoring.diagnosis, knowledge=self.knowledge)
        self.policy_store = UserToolPolicyStore(policy_directory, self.formal_registry)

    @classmethod
    def local(cls, monitoring, project_root, *, multi_round_trial=False, streaming_trial=False):
        from fishery_ai.credential_paths import private_project_location
        root = Path(project_root).resolve()
        location = private_project_location(root)
        return cls(monitoring, credentials=CredentialStore(location.env_path, private_location=location),
            traces=JsonlTraceSink(root / "outputs/management_web/assistant-traces.jsonl"),
            policy_directory=root / "outputs/tool-policies",
            execution_config=load_execution_config(enable_trial=multi_round_trial),
            streaming_config=load_streaming_config(enable_trial=streaming_trial))

    def availability(self):
        return {"connected": True, "mode": "normal", "thinking": "off",
                "description": "Assistant Runtime · Normal · 水质查询 / 项目知识（按 Policy 授权）"}

    def _configuration(self, preset_id, device_id, *, transport=ToolModelTransport.NORMAL):
        if not isinstance(transport, ToolModelTransport):
            raise GatewayError('INVALID_ASSISTANT_REQUEST')
        if preset_id not in PRESETS:
            raise GatewayError("ASSISTANT_PRESET_NOT_ALLOWED")
        if not isinstance(device_id, str):
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        self.monitoring.bind(device_id)  # Validate registered device, never page-global state.
        registry = bindings.ManagementToolRegistry(self.formal_registry, self.monitoring, device_id)
        selected = self.policy_store.effective()["assistant"]
        bound = {definition.name for definition in registry.model_definitions()}
        policy = ToolPolicy("assistant", selected.llm_tool_calling,
            tuple(name for name in selected.exposed_tools if name in bound))
        profile = assistant_profile(preset_id)
        if transport == ToolModelTransport.STREAMING:
            execution = resolve_streaming(self._streaming_config,profile,selected,policy,registry,self.knowledge,
                                          device_id=device_id,epoch=self.epoch)
        else:
            execution = resolve_execution(self._execution_config,profile,selected,policy,registry,self.knowledge,
                                          device_id=device_id,epoch=self.epoch)
        return profile, policy, execution, registry

    def bootstrap(self, device_id: str) -> dict:
        presets = []
        for identifier in PRESETS:
            p, policy, execution, _registry = self._configuration(identifier, device_id)
            _, _, streaming, _ = self._configuration(identifier, device_id,transport=ToolModelTransport.STREAMING)
            presets.append({"preset_id": identifier, "display_name": p.display_name.rsplit(" · ", 1)[0],
                "runtime_type": p.provider_kind, "revision": execution.profile.revision,
                "execution":execution.public(),"streaming":streaming.public()})
        default_execution = presets[0]['execution']
        return {**self.availability(), "epoch": self.epoch,
                "device_id": device_id, "presets": presets, "default_preset_id": PRESETS[0],
                "tools": list(policy.exposed_tools),
                **{key:default_execution[key] for key in ('max_model_requests','max_tool_calls','max_tool_rounds')}}

    def prepare_turn(self, value: dict, *, transport=ToolModelTransport.NORMAL) -> PreparedAssistantTurn:
        allowed = {"preset_id", "question", "history", "conversation_id", "epoch", "device_id",
                   "revision", "confirm_network"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        if value.get("epoch") != self.epoch:
            raise GatewayError("ASSISTANT_SESSION_EXPIRED")
        turn = AssistantRequest.from_dict({k: v for k, v in value.items()
            if k in {"preset_id", "question", "history", "conversation_id"}})
        device_id = value.get("device_id")
        profile, policy, execution, registry = self._configuration(turn.preset_id, device_id,transport=transport)
        if value.get("confirm_network") is not True:
            raise GatewayError("NETWORK_CONFIRMATION_REQUIRED")
        if value.get("revision") != execution.profile.revision:
            raise GatewayError("ASSISTANT_EXECUTION_PROFILE_CHANGED")
        if not execution.can_send:
            raise GatewayError('ASSISTANT_STREAMING_NOT_RELEASED' if transport == ToolModelTransport.STREAMING
                               else 'ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH')
        return PreparedAssistantTurn(turn, device_id, self.epoch, profile, policy, registry, execution)

    def execute_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle) -> dict:
        return self.claim_turn(prepared, handle)()

    def claim_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle):
        """Claim before worker/headers; return one server-only, single-use execution."""
        if not isinstance(prepared, PreparedAssistantTurn):
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        if prepared.epoch != self.epoch:
            raise GatewayError("ASSISTANT_SESSION_EXPIRED")
        if not prepared.execution.can_send:
            raise GatewayError('ASSISTANT_STREAMING_NOT_RELEASED' if
                prepared.execution.model_transport == ToolModelTransport.STREAMING else 'ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH')
        handle.start()  # Replay/cancellation gate before credentials or model I/O.
        handle.limit_turn(prepared.profile.total_timeout_s)
        lock, used = threading.Lock(), False

        def execute():
            nonlocal used
            with lock:
                if used:
                    raise GatewayError('REQUEST_ALREADY_EXECUTED')
                used = True
            return self._execute_claimed_turn(prepared,handle)
        return execute

    def _execute_claimed_turn(self, prepared, handle):
        turn, device_id = prepared.request, prepared.device_id
        profile, policy, registry = prepared.profile, prepared.policy, prepared.registry
        try:
            # ContextVar ownership must be established in the actual worker thread.
            with request_scope(handle), turn_deadline_scope(profile.total_timeout_s):
                runtime = ProfileRegistry([profile], self.credentials).snapshot(profile.profile_id)
                handle.check()
                if (runtime.auth_spec == AuthSpec.REQUIRED_BEARER
                        and runtime.credential.status.availability != "PRESENT"):
                    raise GatewayError("SECRET_MISSING")
                decision = prepared.execution
                if decision.model_transport == ToolModelTransport.STREAMING:
                    runtime = replace(runtime,transport_output_token_limit=decision.max_output_tokens)
                mode = decision.profile.mode
                coordinator = ToolCallingService(self.gateway_factory(), registry, self.traces, policy=policy,
                    execution_mode=mode,model_transport=decision.model_transport)
                result = AssistantService(coordinator,execution_mode=mode,
                    history_projection=DEFAULT_HISTORY_PROJECTION).send(turn, runtime)
            return {**result.to_dict(), "device_id": device_id, "transport":decision.model_transport.value.lower(),
                    "execution":prepared.execution.public()}
        except Exception as error:
            # Internal errors never reach the HTTP response; mark the same cancellation owner.
            code = safe_code(getattr(error, "code", None)) or "AI_SERVICE_UNAVAILABLE"
            handle.finish(code)
            raise
