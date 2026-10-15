"""Management-only composition: existing Assistant runtime, SQLite-backed water tool.

No provider protocol, intent routing, history projection or execution loop lives here.
"""

from dataclasses import replace
import hashlib
from importlib.resources import files
from pathlib import Path
import secrets

from fishery_ai.assistant import AssistantRequest, AssistantService, assistant_profile
from fishery_ai.assistant_activity import safe_code
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import RequestRegistry, request_scope, turn_deadline_scope
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.model_gateway import GatewayError, ProfileRegistry
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.providers import AuthSpec
from fishery_ai.tools.contracts import ToolError, ToolErrorCode
from fishery_ai.tools.policy import ToolPolicy, UserToolPolicyStore
from fishery_ai.tools.registry import ToolRegistry, CURRENT_WATER_QUALITY
from fishery_ai.tool_conversation import ToolCallingService


PRESETS = ("dashscope-qwen38-flash-r1", "ollama-qwen35-4b-r1")


class ManagementWaterRegistry:
    """Reuse the formal schema/validator; bind just one allowlisted app data source."""
    registered_names = staticmethod(ToolRegistry.registered_names)

    def __init__(self, definition, monitoring, device_id):
        self._definition = replace(definition, handler=lambda: water_payload(monitoring, device_id))

    def lookup(self, name):
        if name != CURRENT_WATER_QUALITY:
            raise ToolError(ToolErrorCode.UNKNOWN_TOOL)
        return self._definition

    def model_definitions(self):
        return (self._definition.model_definition,)


def water_payload(monitoring, device_id):
    # snapshot captures one SQLite row + its governed analysis in a read transaction.
    # It uses exactly the DomainAnalysisService used by MonitoringService.analysis().
    # No second reader/query or second Diagnosis pass can mix batches or rules.
    snapshot = monitoring.snapshot(device_id)
    analysis = snapshot.analysis
    if snapshot.observed_at is None:
        return {"status": "NO_DATA", "water_quality": None, "findings": [],
                "device_id": device_id, "evaluated_at": snapshot.evaluated_at,
                "analysis": analysis}
    values = {m.id: m.value if m.quality == "valid" else None for m in snapshot.metrics}
    present = sum(v is not None for v in values.values())
    # Canonical Reading quality matches Monitoring's existing reading projection.
    invalid = any((m.invalid_samples or 0) > 0 for m in snapshot.metrics)
    quality = "invalid" if invalid or not present else "valid" if present == 3 else "partial"
    return {"status": "OK", "water_quality": {**values, "quality": quality,
        "freshness": snapshot.freshness, "observed_at": snapshot.observed_at,
        "retrieved_at": snapshot.received_at, "source": "simulator:" + device_id + ":window_mean"},
        "evaluated_at": snapshot.evaluated_at, "findings": list(snapshot.findings),
        "rule_version": snapshot.rule_version, "device_id": device_id,
        "source_kind": snapshot.source_kind, "batch_id": snapshot.batch_id,
        "window": snapshot.window, "aggregation": snapshot.aggregation,
        "connectivity": snapshot.connectivity, "analysis": analysis}


class ManagementAssistant:
    """One app epoch, frozen device/policy per claimed turn, normal single-round only."""

    def __init__(self, monitoring, *, credentials, traces, policy_directory,
                 gateway_factory=OpenAICompatibleAdapter):
        self.monitoring, self.credentials, self.traces = monitoring, credentials, traces
        self.gateway_factory = gateway_factory
        self.epoch, self.browser_token = secrets.token_hex(16), secrets.token_urlsafe(32)
        devices = monitoring.devices()
        if not devices:
            raise ValueError("NO_MONITORING_DEVICE")
        reader = monitoring.bind(devices[0]["id"]).water_reader
        # Only formal metadata/Policy validation use the full Registry. No original
        # handler is executed by the management adapter, including score/knowledge.
        formal = ToolRegistry(reader, monitoring.diagnosis,
            knowledge=KnowledgeService(files("fishery_ai").joinpath("resources/knowledge/eel_knowledge.json")))
        self.definition = formal.lookup(CURRENT_WATER_QUALITY)
        self.policy_store = UserToolPolicyStore(policy_directory, formal)
        self.requests = RequestRegistry()

    @classmethod
    def local(cls, monitoring, project_root):
        from fishery_ai.credential_paths import private_project_location
        root = Path(project_root).resolve()
        location = private_project_location(root)
        return cls(monitoring, credentials=CredentialStore(location.env_path, private_location=location),
            traces=JsonlTraceSink(root / "outputs/management_web/assistant-traces.jsonl"),
            policy_directory=root / "outputs/tool-policies")

    def availability(self):
        return {"connected": True, "mode": "normal", "thinking": "off",
                "description": "Assistant Runtime · Normal · 只读水质查询"}

    def _configuration(self, preset_id, device_id):
        if preset_id not in PRESETS:
            raise GatewayError("ASSISTANT_PRESET_NOT_ALLOWED")
        if not isinstance(device_id, str):
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        self.monitoring.bind(device_id)  # Validate registered device, never page-global state.
        selected = self.policy_store.effective()["assistant"]
        policy = ToolPolicy("assistant", selected.llm_tool_calling,
            tuple(name for name in selected.exposed_tools if name == CURRENT_WATER_QUALITY))
        profile = assistant_profile(preset_id)
        # Fingerprint all maintainer profile fields + full effective selection + epoch/device.
        digest = hashlib.sha256((repr(profile) + repr(selected) + device_id + self.epoch).encode()).hexdigest()
        return profile, policy, digest

    def bootstrap(self, device_id):
        presets = []
        for identifier in PRESETS:
            p, policy, revision = self._configuration(identifier, device_id)
            presets.append({"preset_id": identifier, "display_name": p.display_name.rsplit(" · ", 1)[0],
                "runtime_type": p.provider_kind, "revision": revision})
        return {**self.availability(), "epoch": self.epoch, "browser_token": self.browser_token,
                "device_id": device_id, "presets": presets, "default_preset_id": PRESETS[0],
                "tools": list(policy.exposed_tools), "max_model_requests": 2,
                "max_tool_calls": 1, "max_tool_rounds": 1}

    def prepare(self):
        handle = self.requests.create()
        return {"request_id": handle.request_id, "control_token": handle.control_token}

    def handle(self, value):
        return self.requests.get(value.get("request_id"), value.get("control_token"))

    def send(self, value):
        allowed = {"preset_id", "question", "history", "conversation_id", "epoch", "device_id",
                   "revision", "confirm_network", "request_id", "control_token"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise GatewayError("INVALID_ASSISTANT_REQUEST")
        if value.get("epoch") != self.epoch:
            raise GatewayError("ASSISTANT_SESSION_EXPIRED")
        turn = AssistantRequest.from_dict({k: v for k, v in value.items()
            if k in {"preset_id", "question", "history", "conversation_id"}})
        device_id = value.get("device_id")
        profile, policy, revision = self._configuration(turn.preset_id, device_id)
        if value.get("confirm_network") is not True:
            raise GatewayError("NETWORK_CONFIRMATION_REQUIRED")
        if value.get("revision") != revision:
            raise GatewayError("ASSISTANT_EXECUTION_PROFILE_CHANGED")
        handle = self.handle(value)
        handle.start()  # Replay/cancellation gate before credentials or model I/O.
        try:
            handle.limit_turn(profile.total_timeout_s)
            runtime = ProfileRegistry([profile], self.credentials).snapshot(profile.profile_id)
            if (runtime.auth_spec == AuthSpec.REQUIRED_BEARER
                    and runtime.credential.status.availability != "PRESENT"):
                raise GatewayError("SECRET_MISSING")
            registry = ManagementWaterRegistry(self.definition, self.monitoring, device_id)
            coordinator = ToolCallingService(self.gateway_factory(), registry, self.traces, policy=policy)
            with request_scope(handle), turn_deadline_scope(runtime.total_timeout_s):
                result = AssistantService(coordinator).send(turn, runtime)
            return {**result.to_dict(), "device_id": device_id, "transport": "normal"}
        except Exception as error:
            # Internal errors never reach the HTTP response; mark the same cancellation owner.
            code = safe_code(getattr(error, "code", None)) or "AI_SERVICE_UNAVAILABLE"
            handle.finish(code)
            raise
