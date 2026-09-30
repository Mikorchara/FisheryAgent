"""Local developer validation UI; business analysis stays in Orchestrator."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Callable
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
import re
import time
import uuid

from flask import Flask, Response, jsonify, request, stream_with_context

from .application import Orchestrator, result_to_dict
from .capability_store import CapabilityStore
from .contracts import AnalysisRequest, Mode, Status
from .custom_profiles import CustomProfileStore, ProfileFieldError
from .domain import DiagnosisService
from .knowledge import KnowledgeService
from .model_gateway import (GatewayError, MockGateway, ModelGateway, ModelMessage,
                            ModelProfile, ModelRequest, ProfileRegistry)
from .model_options import (CapabilitySource, GenerationOptions, OptionValidationError,
                            ReasoningMode, ReasoningOptions, Support, validate_options)
from .observability import JsonlTraceSink
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .repositories import MockRepository


RESOURCE_ROOT = files("fishery_ai").joinpath("resources")
MOCK_PROFILE_ID = "mock-demo"
TEST_TTL_S = 600


def _profile_public(profile: ModelProfile, source: str) -> dict:
    capability_scope_matches = (
        profile.capabilities.service_id == profile.service_id
        and profile.capabilities.model_id == profile.model
        and profile.capabilities.base_url == profile.base_url
        and profile.capabilities.adapter_id == profile.adapter_id
    )
    capabilities = profile.capabilities
    def capability(name: str) -> dict:
        status = getattr(capabilities, name).value if capability_scope_matches else Support.UNKNOWN.value
        return {"status": (getattr(capabilities, name).value if capability_scope_matches
                           else Support.UNKNOWN.value),
                "source": (capabilities.source_for(name).value
                           if capability_scope_matches and status != Support.UNKNOWN.value
                           else CapabilitySource.UNKNOWN.value)}
    reasoning_modes = ["auto"]
    if capability("reasoning_on")["status"] == "supported":
        reasoning_modes.append("on")
    if capability("reasoning_off")["status"] == "supported":
        reasoning_modes.append("off")
    return {"profile_id": profile.profile_id, "display_name": profile.display_name,
            "provider": "mock" if profile.profile_id == MOCK_PROFILE_ID else profile.service_id,
            "service_id": profile.service_id, "model_family": profile.model_family,
            "provider_id": profile.provider_id,
            "model": profile.model, "profile_status": profile.profile_status.value,
            "base_url": profile.base_url, "adapter_id": profile.adapter_id,
            "secret_env": profile.secret_env or "",
            "runtime_type": "mock" if profile.profile_id == MOCK_PROFILE_ID else profile.provider_kind,
            "source": source,
            "capabilities": {
                "streaming": capability("streaming")["status"],
                "streaming_scope_matches": capability_scope_matches,
                "source": capability("streaming")["source"],
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
            "reasoning_modes": reasoning_modes,
            "default_reasoning_mode": profile.default_reasoning.mode.value}


def _fingerprint(values: dict[str, str]) -> tuple[str, ...]:
    return tuple(values[key] for key in ("service_id", "model_family", "adapter_id", "base_url",
                                         "model", "secret_env", "provider_kind"))


def _builtin_profiles() -> tuple[ModelProfile, ...]:
    mock = ModelProfile(
        profile_id=MOCK_PROFILE_ID, display_name="Mock 离线演示",
        provider_kind="mock", base_url="http://mock.invalid/v1", model="offline-mock",
        adapter_id="generic_openai_chat", provider_id="custom",
    )
    real = []
    for name in ("qwen_experimental.json", "deepseek_experimental.json",
                 "ollama_qwen35_local.json"):
        path = RESOURCE_ROOT.joinpath("profiles", name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        real.extend(ModelProfile.from_dict(item) for item in payload["profiles"])
    return (mock, *real)


def create_app(*, trace_path: Path | None = None,
               custom_profiles_dir: Path | None = None,
               capability_evidence_dir: Path | None = None,
               real_gateway_factory: Callable[[], ModelGateway] = OpenAICompatibleAdapter) -> Flask:
    """Construct without loading .env or making a network request."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    store = CustomProfileStore(custom_profiles_dir or Path.cwd() / "outputs/custom_profiles")
    capability_store = CapabilityStore(capability_evidence_dir or
                                        Path.cwd() / "outputs/capability-evidence")
    builtins = _builtin_profiles()
    loaded_profiles = (*builtins, *store.load())
    profiles = {profile.profile_id: capability_store.apply(profile) for profile in loaded_profiles}
    names = [profile.display_name.casefold() for profile in profiles.values()]
    if len(names) != len(set(names)):
        raise ValueError("duplicate Profile display_name")
    sources = {profile.profile_id: "built_in" for profile in builtins}
    sources.update({profile_id: "user_custom" for profile_id in profiles if profile_id not in sources})
    successful_tests: dict[str, tuple[tuple[str, ...], float]] = {}
    repository = MockRepository(RESOURCE_ROOT.joinpath("mock/scenarios.json"))
    scenarios = tuple(repository.data["water_quality"])
    diagnosis = DiagnosisService()
    knowledge = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
    traces = JsonlTraceSink(trace_path or Path.cwd() / "outputs/web-traces.jsonl")

    def error(code: str, status: int):
        return jsonify({"status": "failed", "error_code": code}), status

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

    def secret_missing(profile: ModelProfile) -> bool:
        return bool(profile.secret_env and not os.environ.get(profile.secret_env))

    def name_exists(name: str, *, exclude_id: str | None = None) -> bool:
        return any(profile.profile_id != exclude_id
                   and profile.display_name.casefold() == name.casefold()
                   for profile in profiles.values())

    def test_is_current(values: dict, test_id: object) -> bool:
        if values["provider_kind"] != "cloud":
            return True
        if not isinstance(test_id, str) or test_id not in successful_tests:
            return False
        fingerprint, at = successful_tests[test_id]
        return time.monotonic() - at <= TEST_TTL_S and fingerprint == _fingerprint(values)

    def save_profile(payload: dict, *, update_id: str | None = None):
        if update_id is not None and sources.get(update_id) != "user_custom":
            return error("PROFILE_NOT_EDITABLE", 403)
        try:
            values = store.validate(submitted_fields(payload))
        except ProfileFieldError as exc:
            return profile_error(exc)
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
        known = {profile.service_id: profile for profile in builtins
                 if profile.profile_id != MOCK_PROFILE_ID}
        presets = [{"id": name, "label": label, "service_id": profile.service_id,
                    "model_family": profile.model_family,
                    "adapter_id": profile.adapter_id, "base_url": profile.base_url,
                    "model": profile.model, "secret_env": profile.secret_env,
                    "provider_kind": profile.provider_kind, "provider_id": profile.provider_id}
                   for name, label in (("dashscope", "Qwen · DashScope"),
                                       ("deepseek_api", "DeepSeek API"),
                                       ("ollama", "Ollama · 本地"))
                   for profile in (known[name],)]
        presets.append({"id": "custom", "label": "Custom OpenAI-compatible",
                        "service_id": "custom", "model_family": "unknown",
                        "provider_id": "custom", "adapter_id": "generic_openai_chat",
                        "base_url": "http://localhost:11434/v1", "model": "",
                        "secret_env": "", "provider_kind": "local"})
        return jsonify({
            "profiles": [_profile_public(profile, sources[profile.profile_id])
                         for profile in profiles.values()],
            "presets": presets,
            "scenarios": scenarios,
        })

    @app.post("/api/secret-status")
    def secret_status():
        payload = request.get_json(silent=True) or {}
        name = payload.get("secret_env") if isinstance(payload, dict) else None
        if not isinstance(name, str) or (name and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", name)):
            return error("INVALID_SECRET_ENV", 400)
        return jsonify({"secret_env": name,
                        "status": "PRESENT" if name and os.environ.get(name) else "MISSING"})

    @app.post("/api/profiles/models")
    def query_models():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        try:
            _, profile = draft(payload, model_optional=True)
        except ProfileFieldError as exc:
            return profile_error(exc)
        if secret_missing(profile):
            return error("SECRET_MISSING", 503)
        runtime = ProfileRegistry([profile]).snapshot(profile.profile_id)
        started = time.monotonic()
        try:
            models = real_gateway_factory().list_models(runtime, all_models=True)
            model_ids = sorted({item["id"] for item in models if isinstance(item.get("id"), str)})
        except GatewayError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
            return error(code, 502)
        except Exception:
            return error("INTERNAL_ERROR", 500)
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
        if secret_missing(profile):
            return error("SECRET_MISSING", 503)
        runtime = ProfileRegistry([profile]).snapshot(profile.profile_id)
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
        test_id = uuid.uuid4().hex
        successful_tests[test_id] = (_fingerprint(values), time.monotonic())
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
                                   "provider_kind": profile.provider_kind}})

    @app.post("/api/profiles/<profile_id>/probe")
    def probe_profile_capability(profile_id: str):
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or payload.get("confirm_network") is not True
                or payload.get("capability") != "streaming"):
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles.get(profile_id)
        if profile is None:
            return error("PROFILE_NOT_FOUND", 404)
        if profile.capabilities.streaming != Support.UNKNOWN:
            return error("CAPABILITY_ALREADY_KNOWN", 409)
        if secret_missing(profile):
            return error("SECRET_MISSING", 503)

        # Only this explicit probe gets a temporary capability allowance. Analysis uses
        # the stored Profile unchanged and remains subject to the normal capability gate.
        runtime = ProfileRegistry([profile]).snapshot(profile_id)
        probe_capabilities = replace(profile.capabilities, streaming=Support.SUPPORTED,
                                     service_id=profile.service_id, base_url=profile.base_url,
                                     model_id=profile.model, adapter_id=profile.adapter_id)
        runtime = replace(runtime, capabilities=probe_capabilities, max_retries=0)
        started = time.monotonic()
        try:
            gateway = real_gateway_factory()
            output_chars = 0
            for event in gateway.stream(ModelRequest(
                    Mode.CHAT, (ModelMessage("user", "只回复 OK"),)), runtime):
                output_chars += len(event.delta or "")
            if output_chars == 0:
                return jsonify({"status": "failure", "error_code": "PROBE_NO_CONTENT",
                                "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502
        except GatewayError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
            return jsonify({"status": "failure", "error_code": code,
                            "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502
        except Exception:
            return jsonify({"status": "failure", "error_code": "INTERNAL_ERROR",
                            "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502

        verified_at = datetime.now(timezone.utc).isoformat()
        profiles[profile_id] = capability_store.save_streaming(
            profile, Support.SUPPORTED, verified_at)
        capability = _profile_public(profiles[profile_id], sources[profile_id])["capabilities"]
        return jsonify({"status": "success", "capability": capability,
                        "latency_ms": round((time.monotonic() - started) * 1000, 3)})

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
        if not OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(profile):
            return error("METADATA_UNSUPPORTED", 400)
        runtime = ProfileRegistry([profile]).snapshot(profile_id)
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
        profile = profiles.get(profile_id)
        if profile is None:
            return error("PROFILE_NOT_FOUND", 404)
        mode_text = payload.get("mode")
        if mode_text not in (ReasoningMode.ON.value, ReasoningMode.OFF.value):
            return error("INVALID_REQUEST", 400)
        if not OpenAICompatibleAdapter.supports_ollama_qwen35_reasoning(profile):
            return error("CAPABILITY_PROBE_UNSUPPORTED", 400)
        if secret_missing(profile):
            return error("SECRET_MISSING", 503)
        mode = ReasoningMode(mode_text)
        field_name = "reasoning_on" if mode == ReasoningMode.ON else "reasoning_off"
        runtime = ProfileRegistry([profile]).snapshot(profile_id)
        temporary_capabilities = replace(
            runtime.capabilities, **{field_name: Support.SUPPORTED},
            service_id=profile.service_id, adapter_id=profile.adapter_id,
            base_url=profile.base_url, model_id=profile.model)
        runtime = replace(runtime, capabilities=temporary_capabilities, max_retries=0)
        started = time.monotonic()
        try:
            response = real_gateway_factory().complete(ModelRequest(
                Mode.CHAT, (ModelMessage("user", "只回复 OK"),),
                reasoning=ReasoningOptions(mode)), runtime)
            if not response.text.strip():
                return jsonify({"status": "failure", "error_code": "PROBE_NO_CONTENT",
                                "mode": mode.value,
                                "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502
        except GatewayError as exc:
            code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
            return jsonify({"status": "failure", "error_code": code, "mode": mode.value,
                            "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502
        except Exception:
            return jsonify({"status": "failure", "error_code": "INTERNAL_ERROR",
                            "mode": mode.value,
                            "latency_ms": round((time.monotonic() - started) * 1000, 3)}), 502
        verified_at = datetime.now(timezone.utc).isoformat()
        profiles[profile_id] = capability_store.save_thinking_probe(
            profile, mode, Support.SUPPORTED, verified_at)
        capability = _profile_public(profiles[profile_id], sources[profile_id])["capabilities"]
        return jsonify({"status": "success", "mode": mode.value,
                        "capability": capability,
                        "latency_ms": round((time.monotonic() - started) * 1000, 3)})

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

    @app.post("/api/analyze")
    def analyze():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("INVALID_REQUEST", 400)
        profile_id = payload.get("profile_id")
        scenario = payload.get("scenario")
        question = payload.get("question")
        if (not isinstance(profile_id, str) or profile_id not in profiles
                or not isinstance(scenario, str) or scenario not in scenarios
                or not isinstance(question, str) or not question.strip()
                or len(question) > 500):
            return error("INVALID_REQUEST", 400)
        real = profile_id != MOCK_PROFILE_ID
        if real and payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles[profile_id]
        reasoning, reasoning_error = analysis_reasoning(payload, profile)
        if reasoning_error:
            return error(reasoning_error, 400)
        if real and profile.secret_env and not os.environ.get(profile.secret_env):
            return error("SECRET_MISSING", 503)
        gateway = real_gateway_factory() if real else MockGateway()
        orchestrator = Orchestrator(
            repository, diagnosis, knowledge, ProfileRegistry([profile]), gateway, traces,
            resolve_secrets=real,
        )
        started = time.monotonic()
        try:
            result = orchestrator.analyze(
                AnalysisRequest(Mode.CHAT, profile_id, question.strip(), reasoning=reasoning),
                scenario=scenario)
        except Exception:
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
                or not isinstance(scenario, str) or scenario not in scenarios
                or not isinstance(question, str) or not question.strip()
                or len(question) > 500):
            return error("INVALID_REQUEST", 400)
        real = profile_id != MOCK_PROFILE_ID
        if real and payload.get("confirm_network") is not True:
            return error("NETWORK_CONFIRMATION_REQUIRED", 403)
        profile = profiles[profile_id]
        reasoning, reasoning_error = analysis_reasoning(payload, profile)
        if reasoning_error:
            return error(reasoning_error, 400)
        if real and profile.secret_env and not os.environ.get(profile.secret_env):
            return error("SECRET_MISSING", 503)
        gateway = real_gateway_factory() if real else MockGateway()
        orchestrator = Orchestrator(
            repository, diagnosis, knowledge, ProfileRegistry([profile]), gateway, traces,
            resolve_secrets=real,
        )
        analysis_request = AnalysisRequest(Mode.CHAT, profile_id, question.strip(),
                                          reasoning=reasoning)

        def events():
            for item in orchestrator.analyze_stream(analysis_request, scenario=scenario):
                yield (f"event: {item.kind}\n"
                       f"data: {json.dumps(item.data, ensure_ascii=False, separators=(',', ':'))}\n\n")

        response = Response(stream_with_context(events()), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        return response

    return app


def run_web(*, port: int = 8765) -> None:
    """Load local environment at the explicit Web startup boundary."""
    from dotenv import load_dotenv

    load_dotenv(Path.cwd() / ".env", override=False)
    app = create_app()
    print(f"Developer Validation Web UI: http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
