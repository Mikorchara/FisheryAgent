"""Local developer validation UI; business analysis stays in Orchestrator."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Callable
import json
import os
import re
import time
import uuid

from flask import Flask, Response, jsonify, request, stream_with_context

from .application import Orchestrator, result_to_dict
from .contracts import AnalysisRequest, Mode, Status
from .custom_profiles import CustomProfileStore, ProfileFieldError
from .domain import DiagnosisService
from .knowledge import KnowledgeService
from .model_gateway import (GatewayError, MockGateway, ModelGateway, ModelMessage,
                            ModelProfile, ModelRequest, ProfileRegistry)
from .observability import JsonlTraceSink
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .repositories import MockRepository


RESOURCE_ROOT = files("fishery_ai").joinpath("resources")
MOCK_PROFILE_ID = "mock-demo"
TEST_TTL_S = 600


def _profile_public(profile: ModelProfile, source: str) -> dict:
    return {"profile_id": profile.profile_id, "display_name": profile.display_name,
            "provider": "mock" if profile.profile_id == MOCK_PROFILE_ID else profile.provider_id,
            "model": profile.model, "profile_status": profile.profile_status.value,
            "runtime_type": "mock" if profile.profile_id == MOCK_PROFILE_ID else profile.provider_kind,
            "source": source}


def _fingerprint(values: dict[str, str]) -> tuple[str, ...]:
    return tuple(values[key] for key in ("provider_id", "adapter_id", "base_url",
                                         "model", "secret_env", "provider_kind"))


def _builtin_profiles() -> tuple[ModelProfile, ...]:
    mock = ModelProfile(
        profile_id=MOCK_PROFILE_ID, display_name="Mock 离线演示",
        provider_kind="mock", base_url="http://mock.invalid/v1", model="offline-mock",
        adapter_id="generic_openai_chat", provider_id="custom",
    )
    real = []
    for name in ("qwen_experimental.json", "deepseek_experimental.json"):
        path = RESOURCE_ROOT.joinpath("profiles", name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        real.extend(ModelProfile.from_dict(item) for item in payload["profiles"])
    return (mock, *real)


def create_app(*, trace_path: Path | None = None,
               custom_profiles_dir: Path | None = None,
               real_gateway_factory: Callable[[], ModelGateway] = OpenAICompatibleAdapter) -> Flask:
    """Construct without loading .env or making a network request."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    store = CustomProfileStore(custom_profiles_dir or Path.cwd() / "outputs/custom_profiles")
    builtins = _builtin_profiles()
    profiles = {profile.profile_id: profile for profile in (*builtins, *store.load())}
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

    def submitted_fields(payload: dict) -> dict:
        return {key: value for key, value in payload.items()
                if key not in ("test_id", "conflict_action", "conflict_profile_id",
                               "confirm_network", "method")}

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

    def conflict(values: dict, *, exclude_id: str | None = None) -> ModelProfile | None:
        remaining = [profile for profile in profiles.values()
                     if profile.profile_id != exclude_id]
        # Built-in identity wins even if a user Profile also matches another field.
        for source in ("built_in", "user_custom"):
            candidates = [profile for profile in remaining
                          if sources[profile.profile_id] == source]
            for profile in candidates:
                if (profile.provider_id == values["provider_id"]
                        and profile.base_url.rstrip("/") == values["base_url"].rstrip("/")
                        and profile.model == values["model"]):
                    return profile
            for profile in candidates:
                if profile.display_name.casefold() == values["display_name"].casefold():
                    return profile
        return None

    def conflict_response(profile: ModelProfile, values: dict):
        same_endpoint = (profile.provider_id == values["provider_id"]
                         and profile.base_url.rstrip("/") == values["base_url"].rstrip("/")
                         and profile.model == values["model"])
        return jsonify({"status": "conflict", "error_code": "PROFILE_CONFLICT",
                        "reason": "SAME_ENDPOINT_MODEL" if same_endpoint else "SAME_DISPLAY_NAME",
                        "allowed_actions": (["update", "copy", "cancel"]
                                            if sources[profile.profile_id] == "user_custom"
                                            else ["copy", "cancel"]),
                        "existing": _profile_public(profile, sources[profile.profile_id])}), 409

    def test_is_current(values: dict, test_id: object) -> bool:
        if values["provider_kind"] != "cloud":
            return True
        if not isinstance(test_id, str) or test_id not in successful_tests:
            return False
        fingerprint, at = successful_tests[test_id]
        return time.monotonic() - at <= TEST_TTL_S and fingerprint == _fingerprint(values)

    def save_profile(payload: dict, *, update_id: str | None = None):
        try:
            values = store.validate(submitted_fields(payload))
        except ProfileFieldError as exc:
            return profile_error(exc)
        if not test_is_current(values, payload.get("test_id")):
            return error("CONNECTION_TEST_REQUIRED", 400)
        if update_id is not None and sources.get(update_id) != "user_custom":
            return error("PROFILE_NOT_EDITABLE", 403)
        action = payload.get("conflict_action", "create")
        if action not in ("create", "copy", "update"):
            return error("INVALID_PROFILE", 400)
        if action == "copy" and update_id is None:
            base_name = values["display_name"][:65]
            number = 1
            while any(p.display_name.casefold() == f"{base_name}（副本 {number}）".casefold()
                      for p in profiles.values()):
                number += 1
            values["display_name"] = f"{base_name}（副本 {number}）"
        matched = conflict(values, exclude_id=update_id)
        if matched and action != "copy":
            if action == "update" and sources[matched.profile_id] != "user_custom":
                return error("PROFILE_NOT_EDITABLE", 403)
            if (action == "update" and update_id is None
                    and payload.get("conflict_profile_id") == matched.profile_id
                    and sources[matched.profile_id] == "user_custom"):
                update_id = matched.profile_id
                second = conflict(values, exclude_id=update_id)
                if second:
                    return conflict_response(second, values)
            else:
                return conflict_response(matched, values)
        if action == "update" and update_id is None:
            return error("PROFILE_NOT_EDITABLE", 403)
        if action == "copy" and update_id is not None:
            return error("INVALID_PROFILE", 400)
        try:
            profile = store.update(update_id, values) if update_id else store.create(values)
        except ProfileFieldError as exc:
            return profile_error(exc)
        except FileNotFoundError:
            return error("PROFILE_NOT_FOUND", 404)
        except (ValueError, TypeError):
            return error("INVALID_PROFILE", 400)
        except OSError:
            return error("PROFILE_SAVE_FAILED", 500)
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
        known = {profile.provider_id: profile for profile in builtins
                 if profile.profile_id != MOCK_PROFILE_ID}
        presets = [{"id": name, "label": label, "provider_id": profile.provider_id,
                    "adapter_id": profile.adapter_id, "base_url": profile.base_url,
                    "model": profile.model, "secret_env": profile.secret_env,
                    "provider_kind": profile.provider_kind}
                   for name, label in (("qwen", "Qwen"), ("deepseek", "DeepSeek"))
                   for profile in (known[name],)]
        presets.append({"id": "custom", "label": "Custom OpenAI-compatible",
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
        if sources.get(profile_id) != "user_custom":
            return error("PROFILE_NOT_FOUND", 404)
        profile = profiles[profile_id]
        return jsonify({"profile": _profile_public(profile, "user_custom"),
                        "fields": {"display_name": profile.display_name,
                                   "provider_id": profile.provider_id,
                                   "adapter_id": profile.adapter_id,
                                   "base_url": profile.base_url,
                                   "model": profile.model,
                                   "secret_env": profile.secret_env or "",
                                   "provider_kind": profile.provider_kind}})

    @app.put("/api/profiles/<profile_id>")
    def update_profile(profile_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("INVALID_PROFILE", 400)
        return save_profile(payload, update_id=profile_id)

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
                AnalysisRequest(Mode.CHAT, profile_id, question.strip()), scenario=scenario)
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
        if real and profile.secret_env and not os.environ.get(profile.secret_env):
            return error("SECRET_MISSING", 503)
        gateway = real_gateway_factory() if real else MockGateway()
        orchestrator = Orchestrator(
            repository, diagnosis, knowledge, ProfileRegistry([profile]), gateway, traces,
            resolve_secrets=real,
        )
        analysis_request = AnalysisRequest(Mode.CHAT, profile_id, question.strip())

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
