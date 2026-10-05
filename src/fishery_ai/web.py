"""Local developer validation UI; business analysis stays in Orchestrator."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Callable
from dataclasses import replace
from datetime import datetime, timezone
import json
import re
import time
import uuid
from contextlib import nullcontext

from flask import Flask, Response, jsonify, request, stream_with_context

from .application import Orchestrator, result_to_dict, _public_data
from .capability_store import CapabilityStore
from .capability_probe import run_capability_probe
from .official_capabilities import apply_official_capabilities
from .contracts import AnalysisRequest, Mode, Status, utcnow
from .custom_profiles import CustomProfileStore, ProfileFieldError
from .credentials import CredentialFileError, CredentialStore
from .credential_paths import CredentialLocationError, private_project_location, private_manual_location
from .project_env import EnvWriteError, ProjectEnvWriter
from .web_security import install_local_security
from .providers import AuthSpec, PROVIDERS
from .domain import DiagnosisService
from .knowledge import KnowledgeService
from .model_gateway import (GatewayError, MockGateway, ModelGateway, ModelMessage,
                            ModelProfile, ModelRequest, ProfileRegistry, effective_runtime_defaults)
from .model_options import (CapabilitySource, GenerationOptions, OptionValidationError,
                            ReasoningMode, ReasoningOptions, Support, ModelCapabilities, validate_options)
from .observability import JsonlTraceSink
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .repositories import MockRepository
from .presets import preset_profiles, default_preset_id
from .model_gateway import validate_preset_response
from .execution import RequestRegistry, request_scope
from .tool_conversation import ToolCallingService, MockToolGateway
from .tool_capability_probe import run_tool_calling_probe
from .tool_policy import load_tool_policies, UserToolPolicyStore, ToolPolicyError
from .tools.catalog import tool_catalog
from .tools import ToolRegistry
from .manual import ManualRequest
from .manual_experiments import (ManualExperimentStore, validate_experiment, experiment_runtime,
                                 prepare_experiment_request)
from .telemetry import CurrentSnapshotStore, CurrentWaterQualityReader, SimulationAdapter
from .telemetry.scenario_templates import (
    ScenarioError, ScenarioTemplate, ScenarioTemplateStore, apply_scenario_template,
)


RESOURCE_ROOT = files("fishery_ai").joinpath("resources")
MOCK_PROFILE_ID = "mock-demo"
TEST_TTL_S = 600


# Public import retained for existing callers/tests.
_effective_runtime_defaults = effective_runtime_defaults

def _capability_scope_matches(profile: ModelProfile) -> bool:
    return (profile.capabilities.service_id == profile.service_id
            and profile.capabilities.model_id == profile.model
            and profile.capabilities.base_url == profile.base_url
            and profile.capabilities.adapter_id == profile.adapter_id)


def _profile_public(profile: ModelProfile, source: str) -> dict:
    if profile.access_mode == "preset" and profile.preset_response_modes:
        return {"profile_id": profile.profile_id, "display_name": profile.display_name,
                "access_mode": "preset", "source": source, "model": profile.model,
                "runtime_type": profile.provider_kind, "preset_id": profile.preset_id,
                "preset_variant": profile.preset_variant,
                "preset_contract_version": profile.preset_contract_version,
                "default_reasoning_mode": profile.default_reasoning.mode.value,
                "default_response_mode": profile.default_response_mode,
                "preset_response_modes": list(profile.preset_response_modes),
                "preset_is_default": profile.preset_is_default}
    capability_scope_matches = _capability_scope_matches(profile)
    capabilities = profile.capabilities
    def capability(name: str) -> dict:
        status = getattr(capabilities, name).value if capability_scope_matches else Support.UNKNOWN.value
        detail = dict(capabilities.resolution_details).get(name)
        known_or_conflict = status != Support.UNKNOWN.value or detail == "EVIDENCE_CONFLICT"
        public = {"status": status,
                "source": capabilities.source_for(name).value if capability_scope_matches and known_or_conflict else "UNKNOWN",
                "sources": [item.value for item in capabilities.sources_for(name)
                            if item != CapabilitySource.UNKNOWN] if capability_scope_matches and known_or_conflict else []}
        if detail is not None and capability_scope_matches:
            public["resolution"] = detail
            public["evidence"] = [{"source": item.source.value, "status": item.status.value,
                                  "observed_at": item.observed_at, "origin": item.origin}
                                 for item in profile.capability_evidence if item.capability == name]
        return public

    reasoning_modes = ["auto"]
    if capability("reasoning_on")["status"] == "supported":
        reasoning_modes.append("on")
    if capability("reasoning_off")["status"] == "supported":
        reasoning_modes.append("off")
    effective_reasoning, effective_response, runtime_default_warnings = _effective_runtime_defaults(profile)
    return {"profile_id": profile.profile_id, "display_name": profile.display_name,
            "access_mode": profile.access_mode, "preset_id": profile.preset_id,
            "preset_variant": profile.preset_variant,
            "preset_contract_version": profile.preset_contract_version,
            "provider": "mock" if profile.profile_id == MOCK_PROFILE_ID else profile.service_id,
            "service_id": profile.service_id, "model_family": profile.model_family,
            "provider_id": profile.provider_id,
            "model": profile.model, "profile_status": profile.profile_status.value,
            "base_url": profile.base_url, "adapter_id": profile.adapter_id,
            "secret_env": profile.secret_env or "",
            "credential_ref": profile.credential_ref or "", "auth_spec": profile.auth_spec.value,
            "runtime_type": "mock" if profile.profile_id == MOCK_PROFILE_ID else profile.provider_kind,
            "source": source,
            "capabilities": {
                "streaming": capability("streaming")["status"],
                "streaming_scope_matches": capability_scope_matches,
                "source": capability("streaming")["source"],
                "streaming_evidence": capability("streaming"),
                "thinking_streaming_combination": capability("thinking_streaming_combination"),
                "thinking_off_streaming_combination": capability("thinking_off_streaming_combination"),
                "thinking_default_sources": ([item.value for item in capabilities.sources_for("thinking_default")]
                                             if capability_scope_matches and capabilities.thinking_default is not None else []),
                "thinking_on": capability("reasoning_on"),
                "thinking_off": capability("reasoning_off"),
                "reasoning_effort": capability("reasoning_effort"),
                "structured_output": capability("structured_output"),
                "tool_calling": capability("tool_calling"),
                "thinking_default": (capabilities.thinking_default if capability_scope_matches
                                     else None),
                "effort_values": (list(capabilities.effort_values) if capability_scope_matches
                                  else []),
            },
            "thinking_probe_available": OpenAICompatibleAdapter.supports_thinking_mapping(profile),
            "reasoning_modes": reasoning_modes,
            "default_reasoning_mode": effective_reasoning.mode.value,
            "default_response_mode": effective_response,
            "stored_default_thinking_mode": profile.default_reasoning.mode.value,
            "stored_default_response_mode": profile.default_response_mode,
            "runtime_default_warnings": runtime_default_warnings}


def _fingerprint(values: dict[str, str]) -> tuple[str, ...]:
    return tuple(values[key] for key in ("service_id", "model_family", "adapter_id", "base_url",
                                         "model", "secret_env", "provider_kind", "auth_spec"))


def _builtin_profiles() -> tuple[ModelProfile, ...]:
    mock = ModelProfile(
        profile_id=MOCK_PROFILE_ID, display_name="Mock 离线演示",
        provider_kind="mock", base_url="http://mock.invalid/v1", model="offline-mock",
        adapter_id="generic_openai_chat", provider_id="custom",
        auth_spec=AuthSpec.NONE,
        capabilities=ModelCapabilities(streaming=Support.SUPPORTED, service_id="custom",
            adapter_id="generic_openai_chat", model_id="offline-mock", base_url="http://mock.invalid/v1"),
    )
    real = []
    for name in ("qwen_experimental.json", "deepseek_experimental.json",
                 "ollama_qwen35_local.json"):
        path = RESOURCE_ROOT.joinpath("profiles", name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        real.extend(ModelProfile.from_dict(item) for item in payload["profiles"])
    return (mock, *(apply_official_capabilities(profile) for profile in real))


def create_app(*, trace_path: Path | None = None,
               custom_profiles_dir: Path | None = None,
               capability_evidence_dir: Path | None = None,
               credential_store: CredentialStore | None = None,
               credential_writer: ProjectEnvWriter | None = None,
               manual_experiments_dir: Path | None = None,
               manual_credential_store: CredentialStore | None = None,
               manual_credential_writer: ProjectEnvWriter | None = None,
               scenario_templates_dir: Path | None = None,
               tool_policy_dir: Path | None = None,
               scenario_clock: Callable[[], datetime] = utcnow,
               stale_after_s: float = 300,
               allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1"),
               real_gateway_factory: Callable[[], ModelGateway] = OpenAICompatibleAdapter) -> Flask:
    """Construct without loading .env or making a network request."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    credentials = credential_store if credential_store is not None else CredentialStore()
    if credential_writer is not None and credential_writer.credentials is not credentials:
        raise ValueError("Credential writer must share the app CredentialStore")
    manual_credentials = manual_credential_store if manual_credential_store is not None else CredentialStore(process_env={})
    if manual_credentials is credentials or (manual_credentials.project_env_path is not None
            and manual_credentials.project_env_path == credentials.project_env_path):
        raise ValueError("Manual V2 credentials must be isolated")
    if manual_credential_writer is not None and manual_credential_writer.credentials is not manual_credentials:
        raise ValueError("Manual writer must share its isolated CredentialStore")
    experiments = ManualExperimentStore(manual_experiments_dir or Path.cwd() / "outputs/manual-experiments")
    manual_credential_revisions = {}
    credential_gate, credential_origin_gate = install_local_security(app, allowed_hosts)
    executions = RequestRegistry()
    store = CustomProfileStore(custom_profiles_dir or Path.cwd() / "outputs/custom_profiles")
    capability_store = CapabilityStore(capability_evidence_dir or
                                        Path.cwd() / "outputs/capability-evidence")
    builtins = _builtin_profiles()
    maintained = preset_profiles()
    loaded_profiles = (*builtins, *maintained, *store.load())
    profiles = {profile.profile_id: (profile if profile.access_mode == "preset"
                                     else capability_store.apply(profile)) for profile in loaded_profiles}
    names = [profile.display_name.casefold() for profile in profiles.values()]
    if len(names) != len(set(names)):
        raise ValueError("duplicate Profile display_name")
    sources = {profile.profile_id: "built_in" for profile in builtins}
    sources.update({profile.profile_id: "preset" for profile in maintained})
    sources.update({profile_id: "user_custom" for profile_id in profiles if profile_id not in sources})
    successful_tests: dict[str, tuple[tuple[str, ...], float, str | None]] = {}
    credential_revisions: dict[tuple[str, str], tuple[str, str]] = {}
    repository = MockRepository(RESOURCE_ROOT.joinpath("scenarios"))
    scenario_store = ScenarioTemplateStore(RESOURCE_ROOT.joinpath("scenarios/water_quality"),
        scenario_templates_dir if scenario_templates_dir is not None else
        Path.cwd() / "outputs/scenario_templates/water_quality")
    snapshots = CurrentSnapshotStore()
    simulation_adapter = SimulationAdapter(stale_after_s=stale_after_s)
    current_reader = CurrentWaterQualityReader(snapshots, stale_after_s=stale_after_s,
                                               clock=scenario_clock)
    app.extensions["fishery_snapshot_store"] = snapshots
    app.extensions["fishery_current_water_quality_reader"] = current_reader
    app.extensions["fishery_scenario_templates"] = scenario_store
    diagnosis = DiagnosisService()
    knowledge = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
    traces = JsonlTraceSink(trace_path or Path.cwd() / "outputs/web-traces.jsonl")
    tool_registry = ToolRegistry(current_reader, diagnosis)
    tool_policies = load_tool_policies()
    for policy in tool_policies.values():
        policy.validate_registry(tool_registry)  # Fail closed during app construction.
    policy_store = UserToolPolicyStore(tool_policy_dir if tool_policy_dir is not None else
        ((Path(custom_profiles_dir).parent if custom_profiles_dir is not None else Path.cwd() / "outputs")
         / "tool-policies"), tool_registry)
    app.extensions["fishery_tool_policy_store"] = policy_store
    tool_mock_profile = ModelProfile("tool-mock", "Tool Mock · 离线", "mock",
        "http://mock.invalid/v1", "offline-tool-model", auth_spec=AuthSpec.NONE, max_retries=0,
        capabilities=ModelCapabilities(tool_calling=Support.SUPPORTED, service_id="custom",
            adapter_id="generic_openai_chat", base_url="http://mock.invalid/v1", model_id="offline-tool-model"))

    def error(code: str, status: int):
        return jsonify({"status": "failed", "error_code": code}), status

    @app.route("/api/tool-policies", methods=["GET", "PUT", "DELETE"])
    def manage_tool_policies():
        failure = credential_origin_gate(required=False) if request.method == "GET" else credential_gate()
        if failure is not None:
            return failure
        try:
            if request.method == "PUT":
                policy_store.save(request.get_json(silent=True))
            elif request.method == "DELETE":
                payload = request.get_json(silent=True)
                if payload != {}:
                    return error("INVALID_REQUEST", 400)
                policy_store.reset()
            return jsonify({"catalog": tool_catalog(tool_registry), "policy": policy_store.public()})
        except ToolPolicyError as exc:
            return error(exc.code, 503 if exc.code == "TOOL_POLICY_STORAGE_ERROR" else 400)

    def scenario_failure(exc):
        status = 404 if exc.code == "SCENARIO_NOT_FOUND" else 403 if exc.code == "SCENARIO_READ_ONLY" else (
            409 if exc.code == "SCENARIO_ID_EXISTS" else 503 if exc.code == "SCENARIO_STORAGE_ERROR" else 400)
        return jsonify(status="failed", error_code=exc.code, field=exc.field), status

    def apply_template(template):
        return apply_scenario_template(template, snapshot_store=snapshots,
            adapter=simulation_adapter, now=scenario_clock())

    def snapshot_public(view):
        reading = view.reading if view is not None else None
        return {"snapshot": _public_data(reading),
                "rule_results": _public_data(diagnosis.diagnose(reading)) if reading else [],
                "status": "ready" if reading else "NO_DATA",
                **({"evaluated_at": view.evaluated_at.isoformat()} if view else {})}

    @app.get("/api/scenario-templates")
    def list_scenarios():
        try:
            return jsonify(templates=[item.public_info() for item in scenario_store.list_templates()])
        except ScenarioError as exc:
            return scenario_failure(exc)

    @app.post("/api/scenario-templates")
    def create_scenario():
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict) or set(payload) != {"template"} or not isinstance(payload["template"], dict):
                return error("INVALID_REQUEST", 400)
            template = ScenarioTemplate.from_dict({**payload["template"], "id": "user-" + uuid.uuid4().hex})
            item = scenario_store.create_user_template(template)
            return jsonify(template=item.public_info()), 201
        except ScenarioError as exc:
            return scenario_failure(exc)

    @app.put("/api/scenario-templates/<identifier>")
    def update_scenario(identifier):
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict) or set(payload) != {"template"}:
                return error("INVALID_REQUEST", 400)
            template = ScenarioTemplate.from_dict(payload["template"])
            item = scenario_store.update_user_template(identifier, template)
            return jsonify(template=item.public_info())
        except ScenarioError as exc:
            return scenario_failure(exc)

    @app.delete("/api/scenario-templates/<identifier>")
    def delete_scenario(identifier):
        failure = credential_gate()
        if failure is not None:
            return failure
        try:
            scenario_store.delete_user_template(identifier)
            return jsonify(status="deleted")
        except ScenarioError as exc:
            return scenario_failure(exc)

    @app.post("/api/scenario-templates/<identifier>/copy")
    def copy_scenario(identifier):
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"display_name"}:
            return error("INVALID_REQUEST", 400)
        try:
            item = scenario_store.save_as_user_template(identifier, display_name=payload["display_name"])
            return jsonify(template=item.public_info()), 201
        except ScenarioError as exc:
            return scenario_failure(exc)

    @app.get("/api/water-quality/current")
    def current_water_quality():
        return jsonify(snapshot_public(current_reader.query()))

    @app.post("/api/water-quality/apply")
    def apply_water_quality():
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict) or set(payload) not in ({"template_id"}, {"template"}):
                return error("INVALID_REQUEST", 400)
            template = (scenario_store.get_template(payload["template_id"]).template
                        if "template_id" in payload else ScenarioTemplate.from_dict(payload["template"]))
            apply_template(template)
            return jsonify(snapshot_public(current_reader.query()))
        except ScenarioError as exc:
            return scenario_failure(exc)

    def analysis_snapshot(payload):
        # Legacy scenario clients also use telemetry, never the removed JSON path.
        if payload.get("scenario") is not None:
            try:
                apply_template(scenario_store.get_template(payload["scenario"]).template)
            except ScenarioError as exc:
                return None, scenario_failure(exc)
        view = current_reader.query()
        return view, None if view is not None else error("NO_DATA", 409)

    def valid_scenario(payload):
        if payload.get("scenario") is None:
            return True
        try:
            scenario_store.get_template(payload["scenario"])
            return True
        except ScenarioError:
            return False

    @app.after_request
    def close_rejected_execution(response):
        # Prepared handles that fail preflight must not consume active slots until TTL.
        if (request.path in ("/api/analyze", "/api/analyze/stream", "/api/manual", "/api/manual-v2", "/api/tool-conversation")
                or request.path.endswith("/tool-probe")) and response.status_code >= 400:
            payload = request.get_json(silent=True)
            if isinstance(payload, dict) and "request_id" in payload:
                try:
                    handle = executions.get(payload.get("request_id"), payload.get("control_token"))
                    if not handle._claimed:
                        code = (response.get_json(silent=True) or {}).get("error_code", "INVALID_REQUEST")
                        handle.finish(code)
                        handle.io_closed = True
                except GatewayError:
                    pass
        return response

    @app.post("/api/requests")
    def prepare_execution():
        failure = credential_gate()
        if failure is not None:
            return failure
        try:
            handle = executions.create()
            return jsonify({**handle.public_info(), "control_token": handle.control_token})
        except GatewayError as exc:
            return error(exc.code, 429)

    @app.post("/api/requests/<request_id>/<action>")
    def control_execution(request_id, action):
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return error("INVALID_REQUEST", 400)
        try:
            handle = executions.get(request_id, payload.get("control_token"))
            if action == "cancel":
                handle.cancel()
            elif action != "status":
                return error("INVALID_REQUEST", 400)
            return jsonify(handle.public_info())
        except GatewayError as exc:
            return error(exc.code, 404)

    def claim_execution(payload, *, required=False):
        if "request_id" not in payload and not required:
            return None, None  # Compatibility for existing non-cancellable callers.
        failure = credential_gate()
        if failure is not None:
            return None, failure
        try:
            handle = executions.get(payload.get("request_id"), payload.get("control_token"))
            handle.start()
            handle.io_closed = True  # Until the adapter opens its request-owned client.
            return handle, None
        except GatewayError as exc:
            return None, error(exc.code, 409)

    def profile_error(exc: ProfileFieldError):
        return jsonify({"status": "failed", "error_code": "INVALID_PROFILE",
                        "field": exc.field, "reason": exc.reason,
                        "message": exc.message}), 400

    def analysis_reasoning(payload: dict, profile: ModelProfile):
        if "reasoning_mode" not in payload:
            return None, None
        mode = payload.get("reasoning_mode")
        if not isinstance(mode, str) or mode not in {item.value for item in ReasoningMode}:
            return None, "INVALID_REQUEST"
        effort = payload.get("reasoning_effort")
        if effort is not None and not isinstance(effort, str):
            return None, "INVALID_REQUEST"
        reasoning = ReasoningOptions(ReasoningMode(mode), effort)
        if profile.access_mode == "preset" and reasoning != profile.default_reasoning:
            return None, "PRESET_OPTION_LOCKED"
        try:
            validate_options(GenerationOptions(), reasoning, profile.capabilities)
        except OptionValidationError as exc:
            return None, exc.code
        return reasoning, None

    def submitted_fields(payload: dict) -> dict:
        return {key: value for key, value in payload.items()
                if key not in ("test_id", "confirm_network", "method")}

    def draft(payload: dict, *, model_optional: bool = False) -> tuple[dict, ModelProfile]:
        fields = submitted_fields(payload)
        if model_optional and not fields.get("model"):
            fields["model"] = "model-list-probe"
        if model_optional and not fields.get("display_name"):
            fields["display_name"] = "Model list probe"
        values = store.validate(fields)
        return values, store.build(values, "draft")[0]

    def request_runtime(profile: ModelProfile, *, manual=False):
        try:
            runtime = ProfileRegistry([profile], credentials).snapshot(profile.profile_id,
                apply_runtime_defaults=not manual)
        except CredentialFileError:
            return None, error("CREDENTIAL_FILE_ERROR", 503)
        if (runtime.auth_spec == AuthSpec.REQUIRED_BEARER
                and runtime.credential.status.availability != "PRESENT"):
            return None, error("SECRET_MISSING", 503)
        return runtime, None

    def name_exists(name: str, *, exclude_id: str | None = None) -> bool:
        return any(profile.profile_id != exclude_id
                   and profile.display_name.casefold() == name.casefold()
                   for profile in profiles.values())

    def test_is_current(values: dict, test_id: object) -> bool:
        if values["provider_kind"] != "cloud":
            return True
        if not isinstance(test_id, str) or test_id not in successful_tests:
            return False
        fingerprint, at, revision = successful_tests[test_id]
        try:
            profile = store.build(values, "draft")[0]
            current = credentials.resolve(profile.credential_ref, profile.auth_spec)
        except CredentialFileError:
            return False
        return (time.monotonic() - at <= TEST_TTL_S and fingerprint == _fingerprint(values)
                and revision == current.revision)

    def save_profile(payload: dict, *, update_id: str | None = None):
        # Bind validation and persistence to one credential generation during rotation.
        with credentials._lock:
            return persist_profile(payload, update_id=update_id)

    def persist_profile(payload: dict, *, update_id: str | None = None):
        if update_id is not None and sources.get(update_id) != "user_custom":
            return error("PROFILE_NOT_EDITABLE", 403)
        try:
            values = store.validate(submitted_fields(payload))
        except ProfileFieldError as exc:
            return profile_error(exc)
        try:
            candidate = capability_store.apply(store.build(values, "draft")[0])
        except (ValueError, TypeError):
            return error("INVALID_PROFILE", 400)
        if (values["default_thinking_mode"] == "on"
                and candidate.capabilities.reasoning_on == Support.UNSUPPORTED):
            return jsonify({"status": "failed", "error_code": "PROFILE_DEFAULT_CONFLICT",
                            "field": "default_thinking_mode",
                            "message": "该精确模型已记录不支持 Thinking ON，不能将其设为默认偏好。"}), 400
        if (values["default_thinking_mode"] == "off"
                and candidate.capabilities.reasoning_off == Support.UNSUPPORTED):
            return jsonify({"status": "failed", "error_code": "PROFILE_DEFAULT_CONFLICT",
                            "field": "default_thinking_mode",
                            "message": "该精确模型已记录不支持 Thinking OFF，不能将其设为默认偏好。"}), 400
        if (values["default_response_mode"] == "streaming"
                and candidate.capabilities.streaming == Support.UNSUPPORTED):
            return jsonify({"status": "failed", "error_code": "PROFILE_DEFAULT_CONFLICT",
                            "field": "default_response_mode",
                            "message": "该精确模型已记录不支持 Streaming，不能将其设为默认模式。"}), 400
        if update_id is not None and values["display_name"] != profiles[update_id].display_name:
            return error("PROFILE_NAME_IMMUTABLE", 400)
        if name_exists(values["display_name"], exclude_id=update_id):
            return error("PROFILE_NAME_EXISTS", 409)
        if not test_is_current(values, payload.get("test_id")):
            return error("CONNECTION_TEST_REQUIRED", 400)
        try:
            profile = store.update(update_id, values) if update_id else store.create(values)
        except ProfileFieldError as exc:
            if exc.reason == "NAME_EXISTS":
                return error("PROFILE_NAME_EXISTS", 409)
            return profile_error(exc)
        except FileNotFoundError:
            return error("PROFILE_NOT_FOUND", 404)
        except (ValueError, TypeError):
            return error("INVALID_PROFILE", 400)
        except OSError:
            return error("PROFILE_SAVE_FAILED", 500)
        profile = capability_store.apply(profile)
        profiles[profile.profile_id] = profile
        sources[profile.profile_id] = "user_custom"
        if isinstance(payload.get("test_id"), str):
            successful_tests.pop(payload["test_id"], None)
        return jsonify({"profile": _profile_public(profile, "user_custom")}), (200 if update_id else 201)

    @app.after_request
    def no_cache(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def index():
        html = RESOURCE_ROOT.joinpath("web/index.html").read_text(encoding="utf-8")
        return Response(html, mimetype="text/html")

    @app.get("/assets/<name>")
    def asset(name: str):
        if name not in ("app.css", "app.js"):
            return error("NOT_FOUND", 404)
        path = RESOURCE_ROOT.joinpath("web", name)
        return Response(path.read_text(encoding="utf-8"),
                        mimetype="text/css" if name.endswith(".css") else "text/javascript")

    @app.get("/api/config")
    def config():
        # Connection templates are provider infrastructure, independent of model catalogs.
        presets = [{"id": "custom" if spec.service_id == "generic_openai" else spec.service_id,
                    "label": spec.display_name,
                    "service_id": "custom" if spec.service_id == "generic_openai" else spec.service_id,
                    "model_family": "unknown", "adapter_id": spec.adapter_id,
                    "base_url": spec.default_base_url or "", "model": "",
                    "secret_env": spec.expected_credential_name or "", "auth_spec": spec.auth_spec.value,
                    "provider_kind": spec.default_deployment,
                    "provider_id": "custom" if spec.service_id == "generic_openai" else spec.service_id}
                   for spec in PROVIDERS.all()]
        return jsonify({
            "profiles": [_profile_public(profile, sources[profile.profile_id])
                         for profile in profiles.values()],
            "presets": presets,
            "default_preset_id": default_preset_id(),
            "providers": [{"service_id": spec.service_id, "display_name": spec.display_name,
                "adapter_id": spec.adapter_id, "protocol_spec_id": spec.protocol_spec_id,
                "default_base_url": spec.default_base_url, "auth_spec": spec.auth_spec.value,
                "expected_credential_name": spec.expected_credential_name,
                "metadata_method": spec.metadata_method, "default_deployment": spec.default_deployment}
                for spec in PROVIDERS.all()],
            "scenarios": [item.template.id for item in scenario_store.list_templates()],
            "scenario_templates": [item.public_info() for item in scenario_store.list_templates()],
        })

    @app.post("/api/secret-status")
    def secret_status():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return error("INVALID_REQUEST", 400)
        if isinstance(payload, dict) and "profile_id" in payload:
            profile = profiles.get(payload["profile_id"]) if isinstance(payload["profile_id"], str) else None
            if profile is None:
                return error("PROFILE_NOT_FOUND", 404)
            name, auth = profile.credential_ref, profile.auth_spec
        else:
            name = payload.get("credential_ref", payload.get("secret_env")) if isinstance(payload, dict) else None
            try:
                auth = AuthSpec(payload.get("auth_spec", "REQUIRED_BEARER")) if isinstance(payload, dict) else None
            except ValueError:
                return error("INVALID_AUTH_SPEC", 400)
        if name is None:
            name = ""
        if not isinstance(name, str) or (name and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", name)):
            return error("INVALID_SECRET_ENV", 400)
        try:
            status = credentials.status(name or None, auth).public_info()
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)
        return jsonify({"secret_env": "" if auth == AuthSpec.NONE else name,
                        "storage": "USER_PRIVATE" if credentials.private_location else "PROJECT_DIRECTORY",
                        "status": status["availability"], **status})

    def credential_target(payload):
        if not isinstance(payload, dict) or set(payload) - {"profile_id", "draft", "revision", "secret"}:
            return None, error("INVALID_REQUEST", 400)
        if "profile_id" in payload and "draft" not in payload:
            identifier = payload["profile_id"]
            profile = profiles.get(identifier) if isinstance(identifier, str) else None
            return (profile, None) if profile else (None, error("PROFILE_NOT_FOUND", 404))
        if "draft" in payload and "profile_id" not in payload and isinstance(payload["draft"], dict):
            try:
                _, profile = draft(payload["draft"], model_optional=True)
                return profile, None
            except ProfileFieldError as exc:
                return None, profile_error(exc)
        return None, error("INVALID_REQUEST", 400)

    def credential_view(profile):
        with credentials._lock:
            return credential_view_locked(profile)

    def credential_view_locked(profile):
        try:
            status = credentials.status(profile.credential_ref, profile.auth_spec).public_info()
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)
        info = {"provider": profile.service_id,
                "credential_name": profile.credential_ref if profile.auth_spec != AuthSpec.NONE else "",
                **status, "revision": None, "exists": False, "error_code": None}
        info["storage"] = "USER_PRIVATE" if credentials.private_location else "PROJECT_DIRECTORY"
        info["editable"] = False
        if status["source"] not in ("PROCESS_ENV", "NONE_REQUIRED"):
            if not profile.credential_ref:
                info["error_code"] = "CREDENTIAL_REF_MISSING"
            elif credential_writer is None:
                info["error_code"] = "CREDENTIAL_WRITER_DISABLED"
            else:
                try:
                    state = credential_writer.inspect(profile.credential_ref, profile.auth_spec)
                    scope = (profile.credential_ref, profile.auth_spec.value)
                    binding = credential_revisions.get(scope)
                    if binding is None or binding[0] != state["revision"]:
                        binding = (state["revision"], uuid.uuid4().hex)
                        credential_revisions[scope] = binding
                    info.update(state)
                    info["revision"] = binding[1]  # Bind file revision to the target credential.
                    info["editable"] = True
                except EnvWriteError as exc:
                    info["error_code"] = exc.code
        return jsonify(info)

    @app.post("/api/credentials/status")
    def credential_status():
        rejected = credential_origin_gate(required=False)
        if rejected is not None:
            return rejected
        profile, failure = credential_target(request.get_json(silent=True))
        if failure is not None:
            return failure
        return credential_view(profile)

    @app.route("/api/credentials", methods=["POST", "PUT", "DELETE"])
    def mutate_credential():
        rejected = credential_gate()
        if rejected is not None:
            return rejected
        payload = request.get_json(silent=True)
        profile, failure = credential_target(payload)
        if failure is not None:
            return failure
        if profile.auth_spec == AuthSpec.NONE:
            return error("AUTH_NONE", 403)
        if credential_writer is None:
            return error("CREDENTIAL_WRITER_DISABLED", 403)
        action = {"POST": "create", "PUT": "replace", "DELETE": "remove"}[request.method]
        if action == "remove" and "secret" in payload:
            return error("INVALID_REQUEST", 400)
        try:
            with credentials._lock:
                # Re-resolve a saved Profile after taking the shared rotation/edit lock.
                if "profile_id" in payload:
                    profile = profiles.get(payload["profile_id"])
                    if profile is None:
                        return error("PROFILE_NOT_FOUND", 404)
                credential_writer._editable(profile.credential_ref, profile.auth_spec)
                binding = credential_revisions.get((profile.credential_ref, profile.auth_spec.value))
                if binding is None or payload.get("revision") != binding[1]:
                    raise EnvWriteError("ENV_REVISION_CONFLICT")
                credential_writer.mutate(profile.credential_ref, profile.auth_spec, action=action,
                    expected_revision=binding[0], secret=payload.get("secret"))
                credential_revisions.clear()
                successful_tests.clear()  # Auth cache only; never remove evidence/defaults.
        except EnvWriteError as exc:
            status = (409 if exc.code in {"ENV_REVISION_CONFLICT", "CREDENTIAL_EXISTS", "CREDENTIAL_NOT_FOUND"}
                      else 403 if exc.code in {"PROCESS_ENV_READ_ONLY", "AUTH_NONE"}
                      else 400 if exc.code.startswith("INVALID_") else 503)
            return error(exc.code, status)
        except Exception:
            return error("ENV_WRITE_FAILED", 503)
        return credential_view(profile)

    @app.post("/api/profiles/models")
    def query_models():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        try:
            _, profile = draft(payload, model_optional=True)
        except ProfileFieldError as exc:
            return profile_error(exc)
        runtime, failure = request_runtime(profile)
        if failure is not None:
            return failure
        started = time.monotonic()
        try:
            models = real_gateway_factory().list_models(runtime, all_models=True)
            model_ids = sorted({item["id"] for item in models if isinstance(item.get("id"), str)})
        except GatewayError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
            return error(code, 502)
        except Exception:
            return error("INTERNAL_ERROR", 500)
        try:
            if credentials.resolve(profile.credential_ref, profile.auth_spec).revision != runtime.credential.revision:
                return error("CREDENTIAL_CHANGED", 409)
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)
        return jsonify({"status": "success", "models": model_ids,
                        "latency_ms": round((time.monotonic() - started) * 1000, 3),
                        "capabilities_verified": False})

    @app.post("/api/profiles/test")
    def test_connection():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        method = payload.get("method")
        if method not in ("models", "chat"):
            return error("INVALID_TEST_METHOD", 400)
        try:
            values, profile = draft(payload)
        except ProfileFieldError as exc:
            return profile_error(exc)
        runtime, failure = request_runtime(profile)
        if failure is not None:
            return failure
        gateway = real_gateway_factory()
        started = time.monotonic()

        def test_failure(code: str):
            return jsonify({"status": "failure", "error_code": code,
                            "model": profile.model,
                            "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502

        try:
            if method == "models":
                models = gateway.list_models(runtime, all_models=True)
                if not any(item.get("id") == profile.model for item in models):
                    return test_failure("MODEL_NOT_LISTED")
                returned_model = profile.model
            else:
                response = gateway.complete(ModelRequest(
                    Mode.CHAT, (ModelMessage("user", "只回复 OK"),)), runtime)
                returned_model = response.returned_model or profile.model
        except GatewayError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
            return test_failure(code)
        except Exception:
            return test_failure("INTERNAL_ERROR")
        with credentials._lock:
            try:
                if credentials.resolve(profile.credential_ref, profile.auth_spec).revision != runtime.credential.revision:
                    return error("CREDENTIAL_CHANGED", 409)
            except CredentialFileError:
                return error("CREDENTIAL_FILE_ERROR", 503)
            test_id = uuid.uuid4().hex
            successful_tests[test_id] = (_fingerprint(values), time.monotonic(), runtime.credential.revision)
        return jsonify({"status": "success", "method": method,
                        "model": returned_model,
                        "latency_ms": round((time.monotonic() - started) * 1000, 3),
                        "test_id": test_id, "capabilities_verified": False})

    @app.post("/api/profiles")
    def add_profile():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("INVALID_PROFILE", 400)
        return save_profile(payload)

    @app.get("/api/profiles/<profile_id>")
    def get_profile(profile_id: str):
        if profile_id not in profiles:
            return error("PROFILE_NOT_FOUND", 404)
        profile = profiles[profile_id]
        return jsonify({"profile": _profile_public(profile, sources[profile_id]),
                        "editable": sources[profile_id] == "user_custom",
                        "fields": {"display_name": profile.display_name,
                                   "service_id": profile.service_id,
                                   "model_family": profile.model_family,
                                   "adapter_id": profile.adapter_id,
                                   "base_url": profile.base_url,
                                   "model": profile.model,
                                   "secret_env": profile.secret_env or "",
                                   "auth_spec": profile.auth_spec.value,
                                   "provider_kind": profile.provider_kind,
                                   "default_thinking_mode": profile.default_reasoning.mode.value,
                                   "default_response_mode": profile.default_response_mode}})

    def execute_capability_probe(profile_id: str, payload: dict, capability: str):
        profile = profiles.get(profile_id)
        if profile is None:
            return error("PROFILE_NOT_FOUND", 404)
        if profile.access_mode == "preset":
            return error("PRESET_READ_ONLY", 403)
        if profile_id == MOCK_PROFILE_ID:
            return error("CAPABILITY_PROBE_UNSUPPORTED", 400)
        if capability != "streaming" and not OpenAICompatibleAdapter.supports_thinking_mapping(profile):
            return error("CAPABILITY_PROBE_UNSUPPORTED", 400)
        if capability in ("thinking_streaming_combination", "thinking_off_streaming_combination") and (
                profile.capabilities.streaming != Support.SUPPORTED or
                getattr(profile.capabilities, "reasoning_off" if capability == "thinking_off_streaming_combination"
                        else "reasoning_on") != Support.SUPPORTED):
            return error("OPTION_CONFLICT", 400)
        user_verified = profile.capabilities.source_for(capability) == CapabilitySource.USER_VERIFIED
        reverify = payload.get("reverify") is True
        if user_verified and not reverify:
            return error("CAPABILITY_ALREADY_KNOWN", 409)
        if reverify and not user_verified:
            return error("CAPABILITY_NOT_VERIFIED", 409)
        runtime, failure = request_runtime(profile)
        if failure is not None:
            return failure
        try:
            result = run_capability_probe(real_gateway_factory(), profile, capability, runtime=runtime)
        except Exception:
            return error("CAPABILITY_PROBE_FAILED", 502)
        if result["status"] in ("success", "unsupported"):
            try:
                # Merge against the latest profile: independent probes cannot overwrite each other.
                current = profiles[profile_id]
                if CapabilityStore._identity(current) != CapabilityStore._identity(profile):
                    return error("PROFILE_IDENTITY_CHANGED", 409)
                status = Support.SUPPORTED if result["status"] == "success" else Support.UNSUPPORTED
                profiles[profile_id] = capability_store.save_probe(current, capability, status,
                    datetime.now(timezone.utc).isoformat(), result)
            except (KeyError, OSError, ValueError):
                return error("CAPABILITY_RECORD_FAILED", 500)
            result["capability"] = _profile_public(profiles[profile_id], sources[profile_id])["capabilities"]
        return jsonify(result), 200 if result["status"] != "failure" else 502

    @app.post("/api/profiles/<profile_id>/probe")
    def probe_profile_capability(profile_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        capability = payload.get("capability")
        if capability not in ("streaming", "thinking_streaming_combination", "thinking_off_streaming_combination"):
            return error("INVALID_REQUEST", 400)
        return execute_capability_probe(profile_id, payload, capability)

    @app.put("/api/profiles/<profile_id>")
    def update_profile(profile_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("INVALID_PROFILE", 400)
        return save_profile(payload, update_id=profile_id)

    @app.post("/api/profiles/<profile_id>/metadata")
    def fetch_profile_metadata(profile_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles.get(profile_id)
        if profile is None:
            return error("PROFILE_NOT_FOUND", 404)
        if profile.access_mode == "preset":
            return error("PRESET_READ_ONLY", 403)
        if not OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(profile):
            return error("METADATA_UNSUPPORTED", 400)
        runtime, failure = request_runtime(profile)
        if failure is not None:
            return failure
        try:
            values, default = real_gateway_factory().fetch_ollama_thinking_metadata(runtime)
            profiles[profile_id] = capability_store.save_thinking_metadata(
                profile, list(values), default,
                datetime.now(timezone.utc).isoformat())
        except GatewayError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
            return error(code, 502)
        except (OSError, ValueError, TypeError, KeyError):
            return error("METADATA_INVALID", 502)
        except Exception:
            return error("INTERNAL_ERROR", 500)
        return jsonify({"status": "success",
                        "profile": _profile_public(profiles[profile_id], sources[profile_id])})

    @app.post("/api/profiles/<profile_id>/thinking-probe")
    def probe_thinking(profile_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        mode = payload.get("mode")
        if mode not in ("on", "off"):
            return error("INVALID_REQUEST", 400)
        return execute_capability_probe(profile_id, payload, "reasoning_" + mode)

    @app.delete("/api/profiles/<profile_id>")
    def delete_profile(profile_id: str):
        if sources.get(profile_id) != "user_custom":
            return error("PROFILE_NOT_EDITABLE", 403)
        try:
            store.delete(profile_id)
        except FileNotFoundError:
            return error("PROFILE_NOT_FOUND", 404)
        except OSError:
            return error("PROFILE_DELETE_FAILED", 500)
        profiles.pop(profile_id, None)
        sources.pop(profile_id, None)
        return jsonify({"status": "deleted", "profile_id": profile_id})

    @app.post("/api/profiles/<profile_id>/tool-probe")
    def probe_tool_calling(profile_id: str):
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"confirm_network", "request_id", "control_token"}:
            return error("INVALID_REQUEST", 400)
        if payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles.get(profile_id)
        if profile is None:
            return error("PROFILE_NOT_FOUND", 404)
        if sources.get(profile_id) != "user_custom" or profile.access_mode != "managed_custom":
            return error("CAPABILITY_PROBE_UNSUPPORTED", 403)
        try:
            assistant_policy = policy_store.effective()["assistant"]
        except ToolPolicyError as exc:
            return error(exc.code, 503)
        if not assistant_policy.allows("get_current_water_quality"):
            return error("TOOL_NOT_ALLOWED", 400)
        runtime, failure = request_runtime(profile)
        if failure is not None:
            return failure
        handle, failure = claim_execution(payload, required=True)
        if failure is not None:
            return failure
        try:
            with request_scope(handle):
                result = run_tool_calling_probe(real_gateway_factory(), profile, tool_registry,
                                               traces, runtime=runtime, policy=assistant_policy)
                if result["verdict"] in ("SUPPORTED", "UNSUPPORTED"):
                    handle.check()
                    current = profiles.get(profile_id)
                    if current is None or CapabilityStore._identity(current) != CapabilityStore._identity(profile):
                        raise GatewayError("PROFILE_IDENTITY_CHANGED")
                    profiles[profile_id] = capability_store.save_probe(current, "tool_calling",
                        Support(result["verdict"].lower()), datetime.now(timezone.utc).isoformat(), result)
                    result["evidence_written"] = True
            handle.finish(result["error_code"])
            # Only scalar diagnostic outcomes and Usage; no generated text or raw SDK data.
            result["profile"] = _profile_public(profiles[profile_id], sources[profile_id])
            return jsonify(result), 200 if result["status"] != "failure" else 502
        except GatewayError as exc:
            handle.finish(exc.code)
            return error(exc.code, 409)
        except Exception:
            handle.finish("CAPABILITY_PROBE_FAILED")
            return error("CAPABILITY_PROBE_FAILED", 502)

    @app.post("/api/tool-conversation")
    def tool_conversation():
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        allowed = {"target", "profile_id", "question", "response_mode", "confirm_network",
                   "request_id", "control_token"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            return error("INVALID_REQUEST", 400)
        if payload.get("response_mode", "normal") == "streaming":
            return error("TOOL_STREAMING_NOT_IMPLEMENTED", 400)
        question, target = payload.get("question"), payload.get("target", "mock")
        if (not isinstance(question, str) or not question.strip() or len(question) > 500
                or target not in ("mock", "selected") or payload.get("response_mode", "normal") != "normal"):
            return error("INVALID_REQUEST", 400)
        if target == "mock":
            profile = tool_mock_profile
        else:
            profile_id = payload.get("profile_id")
            if not isinstance(profile_id, str) or profile_id not in profiles:
                return error("INVALID_REQUEST", 400)
            profile = profiles[profile_id]
            # Block before resolving credentials or creating any real client.
            support = profile.capabilities.tool_calling if _capability_scope_matches(profile) else Support.UNKNOWN
            if support != Support.SUPPORTED:
                return error("OPTION_UNKNOWN" if support == Support.UNKNOWN else "OPTION_UNSUPPORTED", 400)
            if payload.get("confirm_network") is not True:
                return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        runtime, failure = request_runtime(profile)
        if failure is not None:
            return failure
        handle, failure = claim_execution(payload, required=True)
        if failure is not None:
            return failure
        started = time.monotonic()
        try:
            assistant_policy = policy_store.effective()["assistant"]
            gateway = MockToolGateway(delay_steps=10) if target == "mock" else real_gateway_factory()
            with request_scope(handle):
                result = ToolCallingService(gateway, tool_registry, traces, policy=assistant_policy).converse(question.strip(), runtime)
            handle.finish(result.error_code)
        except GatewayError as exc:
            handle.finish(exc.code)
            return error(exc.code, 409)
        except ToolPolicyError as exc:
            handle.finish(exc.code)
            return error(exc.code, 503)
        except Exception:
            handle.finish("INTERNAL_ERROR")
            return error("INTERNAL_ERROR", 500)
        tool = result.tool_result
        body = tool.payload if tool else None
        # Deliberate browser allowlist: no RuntimeSnapshot, credential or internal messages.
        if body and body.get("water_quality"):
            body["water_quality"].pop("source", None)
        public = {
            "status": result.status.value, "error_code": result.error_code,
            "request_id": result.request_id, "trace_id": result.trace_id,
            "generated_text": result.generated_text,
            "snapshot_status": "AVAILABLE" if snapshots.get_current() is not None else "NO_DATA",
            "request_1": _public_data(result.request_1), "request_2": _public_data(result.request_2),
            "tool_call": ({"id": result.tool_call_id if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", result.tool_call_id) else "unavailable",
                           "name": result.tool_name if result.tool_name in {item.name for item in tool_registry.model_definitions()} else "unknown_tool",
                           "arguments": {} if tool and tool.status.value in ("OK", "NO_DATA") else None}
                          if result.tool_call_id else None),
            "tool_result": body, "tool_duration_ms": result.tool_duration_ms,
            "final_finish_reason": result.final_finish_reason, "usage": _public_data(result.usage),
            "trace_recorded": result.trace_recorded,
        }
        # Alternate test/extension Gateways must not echo the request credential to the browser.
        secret = runtime.credential._for_adapter()
        def redact(value):
            if isinstance(value, str):
                return value.replace(secret, "[REDACTED]") if secret else value
            if isinstance(value, dict):
                return {redact(key): redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        return jsonify(result=redact(public), total_latency_ms=round((time.monotonic() - started) * 1000, 3)), (
            200 if result.status == Status.COMPLETED else 409 if result.status == Status.CANCELLED else 502)

    @app.post("/api/analyze")
    def analyze():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("INVALID_REQUEST", 400)
        profile_id = payload.get("profile_id")
        scenario = payload.get("scenario")
        question = payload.get("question")
        if (not isinstance(profile_id, str) or profile_id not in profiles
                or not valid_scenario(payload)
                or not isinstance(question, str) or not question.strip()
                or len(question) > 500):
            return error("INVALID_REQUEST", 400)
        real = profile_id != MOCK_PROFILE_ID
        if real and payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles[profile_id]
        try:
            validate_preset_response(profile, streaming=False)
        except GatewayError as exc:
            return error(exc.code, 400)
        reasoning, reasoning_error = analysis_reasoning(payload, profile)
        if reasoning_error:
            return error(reasoning_error, 400)
        safe_reasoning, safe_response_mode, _ = _effective_runtime_defaults(profile)
        runtime_profile = replace(profile, default_reasoning=safe_reasoning,
                                  default_response_mode=safe_response_mode)
        runtime, failure = request_runtime(runtime_profile)
        if failure is not None:
            return failure
        view, failure = analysis_snapshot(payload)
        if failure is not None:
            return failure
        gateway = real_gateway_factory() if real else MockGateway()
        orchestrator = Orchestrator(
            repository, diagnosis, knowledge, ProfileRegistry([runtime_profile], credentials,
                request_runtime=runtime), gateway, traces,
            resolve_secrets=real,
        )
        started = time.monotonic()
        handle, failure = claim_execution(payload)
        if failure is not None:
            return failure
        try:
            with request_scope(handle) if handle else nullcontext():
                result = orchestrator.analyze(
                    AnalysisRequest(Mode.CHAT, profile_id, question.strip(), reasoning=reasoning),
                    reading=view.reading, evaluated_at=view.evaluated_at)
            if handle:
                handle.finish(result.error_code)
        except GatewayError as exc:
            if handle:
                handle.finish(exc.code)
            return error(exc.code, 409)
        except Exception:
            if handle:
                handle.finish("INTERNAL_ERROR")
            # Raw provider or file errors can contain private data. Never send them to the browser.
            return error("INTERNAL_ERROR", 500)
        public = result_to_dict(result)
        if public.get("error_code") == "SECRET_UNAVAILABLE":
            public["error_code"] = "SECRET_MISSING"
        return jsonify({"result": public,
                        "total_latency_ms": round((time.monotonic() - started) * 1000, 3)}), (
                            200 if result.status == Status.COMPLETED else 502)

    @app.post("/api/analyze/stream")
    def analyze_stream():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("INVALID_REQUEST", 400)
        profile_id, scenario, question = (payload.get("profile_id"), payload.get("scenario"),
                                          payload.get("question"))
        if (not isinstance(profile_id, str) or profile_id not in profiles
                or not valid_scenario(payload)
                or not isinstance(question, str) or not question.strip()
                or len(question) > 500):
            return error("INVALID_REQUEST", 400)
        real = profile_id != MOCK_PROFILE_ID
        if real and payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles[profile_id]
        try:
            validate_preset_response(profile, streaming=True)
        except GatewayError as exc:
            return error(exc.code, 400)
        reasoning, reasoning_error = analysis_reasoning(payload, profile)
        if reasoning_error:
            return error(reasoning_error, 400)
        safe_reasoning, safe_response_mode, _ = _effective_runtime_defaults(profile)
        runtime_profile = replace(profile, default_reasoning=safe_reasoning,
                                  default_response_mode=safe_response_mode)
        runtime, failure = request_runtime(runtime_profile)
        if failure is not None:
            return failure
        view, failure = analysis_snapshot(payload)
        if failure is not None:
            return failure
        gateway = real_gateway_factory() if real else MockGateway()
        orchestrator = Orchestrator(
            repository, diagnosis, knowledge, ProfileRegistry([runtime_profile], credentials,
                request_runtime=runtime), gateway, traces,
            resolve_secrets=real,
        )
        analysis_request = AnalysisRequest(Mode.CHAT, profile_id, question.strip(),
                                          reasoning=reasoning)
        handle, failure = claim_execution(payload)
        if failure is not None:
            return failure

        def events():
            iterator = orchestrator.analyze_stream(analysis_request, reading=view.reading,
                                                  evaluated_at=view.evaluated_at)
            try:
                with request_scope(handle) if handle else nullcontext():
                    for item in iterator:
                        if handle and item.kind in ("completed", "failed"):
                            handle.finish(item.data.get("error_code"))
                        yield sse(item.kind, item.data)
            except GeneratorExit:
                if handle:
                    handle.cancel()
                raise
            except Exception as exc:
                code = exc.code if isinstance(exc, GatewayError) else "INTERNAL_ERROR"
                if handle:
                    handle.finish(code)
                yield sse("failed", {"error_code": code})
            finally:
                iterator.close()
                if handle and handle.state not in ("CANCELLED", "COMPLETED", "FAILED"):
                    handle.finish("USER_CANCELLED" if handle.state == "CANCEL_REQUESTED" else "STREAM_INTERRUPTED")

        response = Response(stream_with_context(events()), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        return response

    def sse(kind, data):
        return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

    @app.post("/api/manual")
    def manual_execution():
        # Independent expert path: fixed saved connection, no analysis/capability/defaults.
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or not isinstance(payload.get("profile_id"), str)
                or payload.get("profile_id") not in profiles):
            return error("INVALID_REQUEST", 400)
        if payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles[payload["profile_id"]]
        if profile.provider_kind == "mock":
            return error("MANUAL_CONNECTION_REQUIRED", 400)
        runtime, failure = request_runtime(profile, manual=True)
        if failure is not None:
            return failure
        runtime = replace(runtime, max_retries=0, access_mode="manual_expert",
                          preset_id=None, preset_variant=None, preset_contract_version=None)
        try:
            manual = ManualRequest.from_dict(payload.get("body"), model=runtime.model)
        except GatewayError as exc:
            return error(exc.code, 400)
        return execute_manual(manual, runtime, payload)

    def execute_manual(manual, runtime, payload):
        # Shared V1/V2 SDK, cancellation and raw response path; no Fishery analysis.
        handle, failure = claim_execution(payload, required=True)
        if failure is not None:
            return failure
        gateway = real_gateway_factory()
        started = time.monotonic()
        def public_response(item):
            from .application import _public_data
            data = {"raw_response": item.raw, "usage": _public_data(item.usage),
                    "runtime": _public_data(runtime.public_info()),
                    "request_id": handle.request_id,
                    "total_latency_ms": round((time.monotonic() - started) * 1000, 3)}
            # Defense in depth even for an alternate Gateway returning an echoed key.
            secret = runtime.credential._for_adapter()
            def redact(value):
                if isinstance(value, str):
                    return value.replace(secret, "[REDACTED]") if secret else value
                if isinstance(value, dict):
                    return {redact(key): redact(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [redact(item) for item in value]
                return value
            return redact(data)
        if not manual.streaming:
            try:
                with request_scope(handle):
                    result = gateway.manual_complete(manual, runtime)
                    handle.check()
                handle.finish()
                return jsonify(public_response(result))
            except Exception as exc:
                code = exc.code if isinstance(exc, GatewayError) else "INTERNAL_ERROR"
                handle.finish(code)
                return error(code, 502)
        def events():
            iterator = gateway.manual_stream(manual, runtime)
            try:
                with request_scope(handle):
                    for item in iterator:
                        handle.check()
                        yield sse("raw_delta", public_response(item))
                    handle.check()
                handle.finish()
                yield sse("completed", {"request_id": handle.request_id,
                    "total_latency_ms": round((time.monotonic() - started) * 1000, 3)})
            except GeneratorExit:
                handle.cancel()
                raise
            except Exception as exc:
                code = exc.code if isinstance(exc, GatewayError) else "INTERNAL_ERROR"
                handle.finish(code)
                yield sse("failed", {"error_code": code})
            finally:
                iterator.close()
                if handle.state not in ("COMPLETED", "FAILED", "CANCELLED"):
                    handle.finish("USER_CANCELLED")
        response = Response(stream_with_context(events()), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        return response

    def manual_ref(payload, allowed):
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise GatewayError("INVALID_REQUEST")
        ref = payload.get("credential_ref")
        if not isinstance(ref, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", ref):
            raise GatewayError("INVALID_CREDENTIAL_REF")
        return ref

    def manual_credential_view(ref):
        status = manual_credentials.status(ref).public_info()
        info = {**status, "credential_ref": ref, "storage": "MANUAL_PRIVATE",
                "editable": False, "revision": None, "exists": False}
        if status["source"] == "PROCESS_ENV":
            return info
        if manual_credential_writer is not None:
            state = manual_credential_writer.inspect(ref, AuthSpec.REQUIRED_BEARER)
            binding = manual_credential_revisions.get(ref)
            if binding is None or binding[0] != state["revision"]:
                binding = (state["revision"], uuid.uuid4().hex)
                manual_credential_revisions[ref] = binding
            info.update(state, editable=True, revision=binding[1])
        return info

    @app.post("/api/manual-v2/credentials/status")
    def manual_credential_status():
        failure = credential_origin_gate(required=False)
        if failure is not None:
            return failure
        try:
            ref = manual_ref(request.get_json(silent=True), {"credential_ref"})
            with manual_credentials._lock:
                return jsonify(manual_credential_view(ref))
        except (GatewayError, EnvWriteError) as exc:
            return error(exc.code, 400)
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)

    @app.route("/api/manual-v2/credentials", methods=["POST", "PUT", "DELETE"])
    def manual_credential_mutation():
        failure = credential_gate()
        if failure is not None:
            return failure
        try:
            payload = request.get_json(silent=True)
            ref = manual_ref(payload, {"credential_ref", "revision", "secret"})
            if manual_credential_writer is None:
                return error("CREDENTIAL_WRITER_DISABLED", 403)
            action = {"POST": "create", "PUT": "replace", "DELETE": "remove"}[request.method]
            if action == "remove" and "secret" in payload:
                return error("INVALID_REQUEST", 400)
            with manual_credentials._lock:
                binding = manual_credential_revisions.get(ref)
                if binding is None or payload.get("revision") != binding[1]:
                    return error("ENV_REVISION_CONFLICT", 409)
                manual_credential_writer.mutate(ref, AuthSpec.REQUIRED_BEARER, action=action,
                    expected_revision=binding[0], secret=payload.get("secret"))
                manual_credential_revisions.pop(ref, None)
                return jsonify(manual_credential_view(ref))
        except (GatewayError, EnvWriteError) as exc:
            return error(exc.code, 409 if exc.code == "ENV_REVISION_CONFLICT" else 400)
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)

    def safe_experiment(data):
        values = validate_experiment(data)
        # Never persist a currently resolved key even when pasted into free text.
        snapshot = manual_credentials.resolve(values["credential_ref"] or None,
            AuthSpec.REQUIRED_BEARER if values["credential_ref"] else AuthSpec.NONE)
        secret = snapshot._for_adapter()
        def contains_secret(value):
            if isinstance(value, str):
                return secret in value
            if isinstance(value, dict):
                return any(contains_secret(key) or contains_secret(item) for key, item in value.items())
            if isinstance(value, list):
                return any(contains_secret(item) for item in value)
            return False
        if secret and contains_secret(values):
            raise GatewayError("MANUAL_SECRET_IN_BODY")
        return values

    @app.route("/api/manual-v2/experiments", methods=["GET", "POST"])
    @app.route("/api/manual-v2/experiments/<identifier>", methods=["GET", "PUT", "DELETE"])
    def manual_experiment_crud(identifier=None):
        failure = credential_origin_gate(required=False) if request.method == "GET" else credential_gate()
        if failure is not None:
            return failure
        try:
            if request.method == "GET":
                entries = [experiments.get(identifier)] if identifier else experiments.list()
                for entry in entries:
                    safe_experiment({key: value for key, value in entry.items()
                                     if key not in ("id", "created_at", "updated_at")})
                return jsonify({"experiment": entries[0]} if identifier else {"experiments": entries})
            if request.method == "DELETE":
                experiments.delete(identifier)
                return jsonify(status="success")
            values = safe_experiment(request.get_json(silent=True))
            return jsonify(experiment=experiments.save(values, identifier)), 200
        except GatewayError as exc:
            return error(exc.code, 404 if exc.code == "EXPERIMENT_NOT_FOUND" else 400)
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)

    @app.post("/api/manual-v2")
    def manual_v2_execution():
        failure = credential_gate()
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"experiment", "confirm_network", "request_id", "control_token"}:
            return error("INVALID_REQUEST", 400)
        if payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        try:
            values = safe_experiment(payload.get("experiment"))
            runtime = experiment_runtime(values, manual_credentials)
            manual = prepare_experiment_request(values["raw_request_body"], model=runtime.model)
        except GatewayError as exc:
            return error(exc.code, 503 if exc.code == "SECRET_MISSING" else 400)
        except CredentialFileError:
            return error("CREDENTIAL_FILE_ERROR", 503)
        return execute_manual(manual, runtime, payload)

    return app


def run_web(*, port: int = 8765) -> None:
    """Fix the credential path at startup; each request resolves a fresh snapshot."""
    try:
        location = private_project_location(Path.cwd())
    except CredentialLocationError:
        print("CREDENTIAL_STORAGE_UNAVAILABLE", flush=True)
        return
    credentials = CredentialStore(location.env_path, private_location=location)
    manual_location = private_manual_location(Path.cwd())
    manual_credentials = CredentialStore(manual_location.env_path, process_env={}, private_location=manual_location)
    app = create_app(credential_store=credentials,
                     credential_writer=ProjectEnvWriter(location.env_path.parent, credentials,
                                                        require_git_ignored=False),
                     manual_credential_store=manual_credentials,
                     manual_credential_writer=ProjectEnvWriter(manual_location.env_path.parent, manual_credentials,
                         require_git_ignored=False, filename="manual.env"),
                     allowed_hosts=(f"127.0.0.1:{port}", f"localhost:{port}"))
    print(f"Developer Validation Web UI: http://127.0.0.1:{port}", flush=True)
    print(f"Project credentials (user-private): {location.env_path}", flush=True)
    print("Legacy project .env is not read or migrated.", flush=True)
    # CredentialStore owns project .env reads; Flask must not import it into os.environ.
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False,
            load_dotenv=False)
