"""Local developer validation UI; business analysis stays in Orchestrator."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Callable
import json
import os
import time

from flask import Flask, Response, jsonify, request

from .application import Orchestrator, result_to_dict
from .contracts import AnalysisRequest, Mode, Status
from .domain import DiagnosisService
from .knowledge import KnowledgeService
from .model_gateway import (MockGateway, ModelGateway, ModelProfile, ProfileRegistry)
from .observability import JsonlTraceSink
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .repositories import MockRepository


RESOURCE_ROOT = files("fishery_ai").joinpath("resources")
MOCK_PROFILE_ID = "mock-demo"


def _profiles() -> tuple[ModelProfile, ...]:
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
               real_gateway_factory: Callable[[], ModelGateway] = OpenAICompatibleAdapter) -> Flask:
    """Construct without loading .env or making a network request."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    profiles = {profile.profile_id: profile for profile in _profiles()}
    repository = MockRepository(RESOURCE_ROOT.joinpath("mock/scenarios.json"))
    scenarios = tuple(repository.data["water_quality"])
    diagnosis = DiagnosisService()
    knowledge = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
    traces = JsonlTraceSink(trace_path or Path.cwd() / "outputs/web-traces.jsonl")

    def error(code: str, status: int):
        return jsonify({"status": "failed", "error_code": code}), status

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
        return jsonify({
            "profiles": [{
                "profile_id": profile.profile_id,
                "display_name": profile.display_name,
                "provider": profile.provider_id if profile.profile_id != MOCK_PROFILE_ID else "mock",
                "model": profile.model,
                "profile_status": profile.profile_status.value,
                "runtime_type": "mock" if profile.profile_id == MOCK_PROFILE_ID else "cloud",
            } for profile in profiles.values()],
            "scenarios": scenarios,
        })

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

    return app


def run_web(*, port: int = 8765) -> None:
    """Load only the two expected Secret variables at the CLI boundary."""
    from dotenv import dotenv_values

    values = dotenv_values(Path.cwd() / ".env")
    for name in ("DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY"):
        if not os.environ.get(name) and values.get(name):
            os.environ[name] = values[name]
    app = create_app()
    print(f"Developer Validation Web UI: http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
