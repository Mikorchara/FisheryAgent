"""Management AI composition using only the independent Backend execution types."""

from dataclasses import replace
from pathlib import Path
import secrets
import threading

from .runtime.assistant import AssistantRequest, AssistantService, assistant_profile
from apps.ai_backend.assistant_activity import safe_code
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle, request_scope, turn_deadline_scope
from apps.ai_backend.model_gateway import GatewayError, ProfileRegistry
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.providers import AuthSpec
from .runtime.policy import ToolPolicy, UserToolPolicyStore
from apps.ai_backend.tools.registry import ToolRegistry
from apps.ai_backend.tool_conversation import ToolCallingService, ToolModelTransport
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION

from .business_tools.registry import bind_tools, FORMAL_TOOL_NAMES, HISTORY_CANDIDATE_TOOL_NAMES
from .business_tools.water_quality_history import WATER_QUALITY_HISTORY
from .management_policy import ManagementToolPolicyStore
from .history_execution import HISTORY_PROFILE, HistoryCandidateConfig, load_history_config, resolve_history_candidate
from .runtime.release_contracts import _hash
from .runtime.sources import SourceRequirement
from .contracts import PreparedAssistantTurn
from .execution import ManagementExecutionConfig, load_execution_config, resolve_execution
from .streaming import ManagementStreamingConfig, load_streaming_config, resolve_streaming
from .normal_selection import (NORMAL_SELECTION_CANDIDATE, resolve_normal_selection_candidate,
    UNIFIED_PRESET, UnifiedToolTrials, load_unified_tool_trials, resolve_unified_tools)


PRESETS = ("dashscope-qwen38-flash-r1", "ollama-qwen35-4b-r1")


class ManagementAssistantService:
    """One epoch and frozen device/policy/mode per turn; single-round by default."""

    def __init__(self, monitoring, *, credentials, traces, policy_directory,
                 gateway_factory=OpenAICompatibleAdapter, execution_config=None, streaming_config=None,
                 history_config=None, unified_config=None, knowledge=None):
        self.monitoring, self.credentials, self.traces = monitoring, credentials, traces
        self.gateway_factory = gateway_factory
        self._unified_config=load_unified_tool_trials() if unified_config is None else unified_config
        if not isinstance(self._unified_config,UnifiedToolTrials):
            raise GatewayError('INVALID_UNIFIED_TOOL_TRIAL_CONFIG')
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
        # Explicit business dependency only: no old Gateway/Registry/Executor.
        if knowledge is None:
            raise ValueError("KNOWLEDGE_SERVICE_REQUIRED")
        self.knowledge = knowledge
        from apps.knowledge.service import KnowledgeContentService
        if isinstance(self.knowledge,KnowledgeContentService):
            from .content_binding import content_scope_configs
            self._execution_config,self._streaming_config,self._unified_config=content_scope_configs(
                self._execution_config,self._streaming_config,self._unified_config)
        self.history_registry = bind_tools(monitoring, devices[0]["id"], self.knowledge, include_history=True)
        self.formal_registry = ToolRegistry([self.history_registry.lookup(name) for name in FORMAL_TOOL_NAMES])
        self.policy_store = UserToolPolicyStore(policy_directory, self.formal_registry)
        self.management_policy = ManagementToolPolicyStore(policy_directory, self.policy_store)
        self._history_config = load_history_config() if history_config is None else history_config
        if not isinstance(self._history_config, HistoryCandidateConfig):
            raise GatewayError('INVALID_HISTORY_CANDIDATE_CONFIG')

    @staticmethod
    def request_registry(**kwargs):
        from apps.ai_backend.execution import RequestRegistry
        from .runtime.activity import tool_summary
        return RequestRegistry(summarize_tool=tool_summary, **kwargs)

    @classmethod
    def local(cls, monitoring, project_root, *, multi_round_trial=False, streaming_trial=False, history_trial=False,
              unified_tools_trial=False, knowledge=None):
        from .runtime.locations import private_project_location
        root = Path(project_root).resolve()
        location = private_project_location(root)
        return cls(monitoring, knowledge=knowledge, credentials=CredentialStore(location.env_path, private_location=location),
            traces=JsonlTraceSink(root / "outputs/management_web/assistant-traces.jsonl",
                tool_names=HISTORY_CANDIDATE_TOOL_NAMES),
            policy_directory=root / "outputs/tool-policies",
            execution_config=load_execution_config(enable_trial=multi_round_trial),
            streaming_config=load_streaming_config(enable_trial=streaming_trial),
            history_config=load_history_config(enable_trial=history_trial),
            unified_config=load_unified_tool_trials(normal=unified_tools_trial and multi_round_trial,
                                                   streaming=unified_tools_trial and streaming_trial))

    def availability(self):
        return {"connected": True, "mode": "normal", "thinking": "off",
                "description": "Assistant Runtime · Normal · 水质查询 / 项目知识（按 Policy 授权）"}

    def tool_authorization(self):
        from .business_tools.registry import WATER_QUALITY_SCORE
        return {**self.management_policy.public(), 'epoch':self.epoch,
            'tools':[{'name':name, 'assembled':name in self.history_registry.registered_names(),
                      'history_query_only':name == WATER_QUALITY_HISTORY and not (
                          self._unified_config.normal_enabled or self._unified_config.streaming_enabled),
                      'candidate_only':name == WATER_QUALITY_HISTORY and self._history_config.status == 'candidate',
                      'compatibility_only':name == WATER_QUALITY_SCORE}
                     for name in (*FORMAL_TOOL_NAMES, WATER_QUALITY_HISTORY, WATER_QUALITY_SCORE)],
            'tool_trials':{'status':'local_experimental','normal_enabled':self._unified_config.normal_enabled,
                           'streaming_enabled':self._unified_config.streaming_enabled},
            'history_candidate':{'status':self._history_config.status,
                                 'enabled':self._history_config.enabled,
                                 'max_tool_calls':1,'max_tool_rounds':1,'max_model_requests':2}}

    def save_tool_authorization(self, value):
        if (not isinstance(value,dict) or set(value) != {'epoch','revision','selected_tools'}):
            raise GatewayError('INVALID_TOOL_POLICY')
        if value['epoch'] != self.epoch:
            raise GatewayError('ASSISTANT_SESSION_EXPIRED')
        self.management_policy.save(value['selected_tools'],expected_revision=value['revision'])
        return self.tool_authorization()

    def _configuration(self, preset_id, device_id, *, transport=ToolModelTransport.NORMAL,
                       policy_snapshot=None, execution_profile=None):
        if not isinstance(transport, ToolModelTransport):
            raise GatewayError('INVALID_ASSISTANT_REQUEST')
        if preset_id not in PRESETS:
            raise GatewayError("ASSISTANT_PRESET_NOT_ALLOWED")
        if not isinstance(device_id, str):
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        self.monitoring.bind(device_id)  # Validate registered device, never page-global state.
        if execution_profile not in (None, HISTORY_PROFILE, NORMAL_SELECTION_CANDIDATE):
            raise GatewayError('INVALID_ASSISTANT_REQUEST')
        historical = execution_profile == HISTORY_PROFILE
        candidate = execution_profile == NORMAL_SELECTION_CANDIDATE
        snapshot = policy_snapshot or self.management_policy.snapshot()
        unified=(not historical and not candidate and preset_id==UNIFIED_PRESET
            and set(snapshot.selected_tools).intersection(HISTORY_CANDIDATE_TOOL_NAMES)!=set(FORMAL_TOOL_NAMES) and (
                self._unified_config.streaming_enabled if transport==ToolModelTransport.STREAMING
                else self._unified_config.normal_enabled))
        registry = bind_tools(self.monitoring, device_id, self.knowledge,
            formal=self.history_registry if historical or candidate or unified else self.formal_registry,
            include_history=historical or candidate or unified)
        selected = ToolPolicy("assistant", True, snapshot.selected_tools)
        bound = {definition.name for definition in registry.model_definitions()}
        names = HISTORY_CANDIDATE_TOOL_NAMES if candidate or unified else selected.exposed_tools
        policy = ToolPolicy("assistant", selected.llm_tool_calling,
            tuple(name for name in names if name in bound and name in selected.exposed_tools
                  and (not historical or name == WATER_QUALITY_HISTORY)))
        profile = assistant_profile(preset_id)
        if candidate:
            execution = resolve_normal_selection_candidate(profile,selected,registry,self.knowledge,
                device_id=device_id,epoch=self.epoch,policy_revision=snapshot.revision,transport=transport)
        elif historical:
            execution = resolve_history_candidate(self._history_config,profile,selected,registry,
                device_id=device_id,epoch=self.epoch,policy_revision=snapshot.revision,transport=transport)
        elif unified:
            execution=resolve_unified_tools(self._unified_config,profile,policy,registry,self.knowledge,
                device_id=device_id,epoch=self.epoch,policy_revision=snapshot.revision,transport=transport)
        elif transport == ToolModelTransport.STREAMING:
            execution = resolve_streaming(self._streaming_config,profile,selected,policy,registry,self.knowledge,
                                          device_id=device_id,epoch=self.epoch)
        else:
            execution = resolve_execution(self._execution_config,profile,selected,policy,registry,self.knowledge,
                                          device_id=device_id,epoch=self.epoch)
        if not historical and not candidate and snapshot.source == 'MANAGEMENT_OVERRIDE':
            execution = replace(execution,profile=replace(execution.profile, revision=_hash({
                'execution_revision':execution.profile.revision,'management_policy_revision':snapshot.revision})))
        return profile, policy, execution, registry

    def bootstrap(self, device_id: str) -> dict:
        presets = []
        snapshot = self.management_policy.snapshot()
        for identifier in PRESETS:
            p, policy, execution, _registry = self._configuration(identifier, device_id,policy_snapshot=snapshot)
            _, streaming_policy, streaming, _ = self._configuration(identifier, device_id,
                transport=ToolModelTransport.STREAMING,policy_snapshot=snapshot)
            presets.append({"preset_id": identifier, "display_name": p.display_name.rsplit(" · ", 1)[0],
                "runtime_type": p.provider_kind, "revision": execution.profile.revision,
                "execution":{**execution.public(),'tools':list(policy.exposed_tools)},
                "streaming":{**streaming.public(),'tools':list(streaming_policy.exposed_tools)}})
        default_execution = presets[0]['execution']
        _, _, candidate, _ = self._configuration(PRESETS[0],device_id,
            policy_snapshot=snapshot,execution_profile=HISTORY_PROFILE)
        return {**self.availability(), "epoch": self.epoch,
                'history_candidate':{'execution_profile':HISTORY_PROFILE, 'preset_id':PRESETS[0],
                    'enabled':self._history_config.enabled, 'tools':[WATER_QUALITY_HISTORY],**candidate.public()},
                'policy_revision':snapshot.revision,
                "device_id": device_id, "presets": presets, "default_preset_id": PRESETS[0],
                "tools": presets[0]['execution']['tools'],
                **{key:default_execution[key] for key in ('max_model_requests','max_tool_calls','max_tool_rounds')}}

    def prepare_turn(self, value: dict, *, transport=ToolModelTransport.NORMAL) -> PreparedAssistantTurn:
        allowed = {"preset_id", "question", "history", "conversation_id", "epoch", "device_id",
                   "revision", "confirm_network", "execution_profile"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        if value.get("epoch") != self.epoch:
            raise GatewayError("ASSISTANT_SESSION_EXPIRED")
        turn = AssistantRequest.from_dict({k: v for k, v in value.items()
            if k in {"preset_id", "question", "history", "conversation_id"}})
        device_id = value.get("device_id")
        snapshot = self.management_policy.snapshot()
        execution_profile = value.get('execution_profile')
        profile, policy, execution, registry = self._configuration(turn.preset_id, device_id,transport=transport,
            policy_snapshot=snapshot,execution_profile=execution_profile)
        if execution_profile == HISTORY_PROFILE:
            turn = replace(turn,source_requirement=SourceRequirement.HISTORICAL_WATER_QUERY)
        if value.get("confirm_network") is not True:
            raise GatewayError("NETWORK_CONFIRMATION_REQUIRED")
        if value.get("revision") != execution.profile.revision:
            raise GatewayError("ASSISTANT_EXECUTION_PROFILE_CHANGED")
        if not execution.can_send:
            if execution_profile in (HISTORY_PROFILE, NORMAL_SELECTION_CANDIDATE):
                raise GatewayError(execution.profile.mode_reason)
            raise GatewayError('ASSISTANT_STREAMING_NOT_RELEASED' if transport == ToolModelTransport.STREAMING
                               else 'ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH')
        return PreparedAssistantTurn(turn, device_id, self.epoch, profile, policy, registry, execution,
                                     snapshot.revision, snapshot.source)

    def execute_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle) -> dict:
        return self.claim_turn(prepared, handle)()

    def claim_turn(self, prepared: PreparedAssistantTurn, handle: RequestHandle):
        """Claim before worker/headers; return one server-only, single-use execution."""
        if not isinstance(prepared, PreparedAssistantTurn) or not isinstance(handle, RequestHandle):
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        if prepared.epoch != self.epoch:
            raise GatewayError("ASSISTANT_SESSION_EXPIRED")
        current = self.management_policy.snapshot()
        if (current.source == 'MANAGEMENT_OVERRIDE' or prepared.policy_source == 'MANAGEMENT_OVERRIDE') \
                and current.revision != prepared.policy_revision:
            raise GatewayError('ASSISTANT_EXECUTION_PROFILE_CHANGED')
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
                if decision.max_output_tokens is not None:
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
