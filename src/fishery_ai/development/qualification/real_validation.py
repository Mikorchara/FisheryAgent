"""Explicit, one-request-at-a-time Cloud validation entry; never used by demo/tests."""

from __future__ import annotations

from dataclasses import replace
from importlib.resources import files
from pathlib import Path
import json
import socket
import ssl
import time

from ...credentials import CredentialFileError, CredentialStore
from ...credential_paths import CredentialLocationError, private_project_location

from ...application import Orchestrator
from ...contracts import AnalysisRequest, Mode, Usage, UsageAccumulator
from ...domain import DiagnosisService
from ...knowledge import KnowledgeService
from ...model_gateway import (GatewayError, ModelMessage, ModelRequest, ProfileRegistry)
from ...model_options import (GenerationOptions, ReasoningMode, ReasoningOptions, Support)
from ...observability import JsonlTraceSink
from ...openai_compatible_adapter import OpenAICompatibleAdapter
from ...repositories import MockRepository


PROFILE_ID = "deepseek-v4-flash-experimental"
RESOURCE_ROOT = files("fishery_ai").joinpath("resources")
CHECKS = ("network", "basic", "auto", "on", "off", "effort-low", "temperature", "top-p",
          "output-limit", "stream", "full-chain", "invalid-model")


def _network_diagnostics(runtime, gateway: OpenAICompatibleAdapter) -> dict:
    """One ordered, non-generating probe per layer; output contains no raw errors."""
    host, port = "api.deepseek.com", 443
    steps = []

    def probe(stage, operation):
        started = time.monotonic()
        try:
            value = operation()
            row = {"stage": stage, "status": "ok", "elapsed_ms":
                   round((time.monotonic() - started) * 1000, 3)}
            if value is not None:
                row["metadata"] = value
            steps.append(row)
            return True
        except Exception as exc:
            if isinstance(exc, GatewayError):
                code = exc.code
            elif isinstance(exc, socket.gaierror):
                code = "DNS_ERROR"
            elif isinstance(exc, ssl.SSLError):
                code = "TLS_ERROR"
            elif isinstance(exc, socket.timeout):
                code = "CONNECT_TIMEOUT"
            elif isinstance(exc, OSError):
                code = "CONNECTION_ERROR"
            else:
                code = "DIAGNOSTIC_ERROR"
            steps.append({"stage": stage, "status": "failed", "elapsed_ms":
                          round((time.monotonic() - started) * 1000, 3), "error_code": code})
            return False

    def tcp():
        with socket.create_connection((host, port), timeout=runtime.connect_timeout_s):
            pass

    def tls():
        with socket.create_connection((host, port), timeout=runtime.connect_timeout_s) as sock:
            sock.settimeout(runtime.read_timeout_s)
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host):
                pass

    if probe("dns", lambda: socket.getaddrinfo(host, port)):
        # DNS addresses are not needed in the report.
        steps[-1].pop("metadata", None)
        if probe("tcp", tcp) and probe("tls", tls):
            probe("http_models", lambda: gateway.list_models(runtime))
    return {"host": host, "port": port, "steps": steps,
            "model_request_count": gateway.request_attempts}


def _usage_data(usage: Usage) -> dict:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "source": usage.source.value,
    }


def _show_usage(usage: Usage, title: str) -> None:
    print(title)
    for label, value in _usage_data(usage).items():
        print(f"{label}: {'unavailable' if value is None else value}")


def _probe_runtime(runtime, check: str):
    """Only this explicit validation command can temporarily declare unknown capabilities."""
    caps = runtime.capabilities
    if check in ("on", "top-p", "effort-low"):
        caps = replace(caps, reasoning_on=Support.SUPPORTED)
    if check in ("off", "temperature", "output-limit"):
        caps = replace(caps, reasoning_off=Support.SUPPORTED)
    if check == "effort-low":
        caps = replace(caps, reasoning_effort=Support.SUPPORTED,
                       effort_values=("low", "high", "max"))
    elif check == "temperature":
        caps = replace(caps, temperature=Support.SUPPORTED)
        caps = replace(caps, reasoning_temperature_conflict=True)
    elif check == "top-p":
        caps = replace(caps, top_p=Support.SUPPORTED)
    elif check == "output-limit":
        caps = replace(caps, max_output_tokens=Support.SUPPORTED,
                       max_tokens_field="max_tokens")
    elif check == "stream":
        caps = replace(caps, streaming=Support.SUPPORTED)
    return replace(runtime, capabilities=caps, max_retries=0)


def _request(check: str) -> ModelRequest:
    message = ModelMessage("user", "请只回复：收到。")
    generation = GenerationOptions()
    reasoning = None
    if check == "auto":
        reasoning = ReasoningOptions(ReasoningMode.AUTO)
    elif check == "on":
        reasoning = ReasoningOptions(ReasoningMode.ON)
    elif check == "off":
        reasoning = ReasoningOptions(ReasoningMode.OFF)
    elif check == "effort-low":
        reasoning = ReasoningOptions(ReasoningMode.ON, "low")
    elif check == "temperature":
        generation = GenerationOptions(temperature=0.7)
        reasoning = ReasoningOptions(ReasoningMode.OFF)
    elif check == "top-p":
        generation = GenerationOptions(top_p=0.95)
        reasoning = ReasoningOptions(ReasoningMode.ON)
    elif check == "output-limit":
        generation = GenerationOptions(max_output_tokens=64)
        reasoning = ReasoningOptions(ReasoningMode.OFF)
    return ModelRequest(Mode.CHAT, (message,), generation, reasoning)


def run_real_validation(*, check: str, scenario: str, confirm_network: bool,
                        credential_store: CredentialStore | None = None) -> int:
    if not confirm_network:
        print("Real validation requires --confirm-network; no network request was made.")
        return 2
    if check not in CHECKS:
        print("UNKNOWN_CHECK")
        return 2
    if credential_store is None:
        try:
            location = private_project_location(Path.cwd())
        except CredentialLocationError:
            print("CREDENTIAL_STORAGE_UNAVAILABLE")
            return 2
        credentials = CredentialStore(location.env_path, private_location=location)
    else:
        credentials = credential_store
    registry = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath(
        "profiles/deepseek_experimental.json"), credentials)
    profile = registry._profiles.get(PROFILE_ID)
    if profile is None:
        print("INACTIVE_VALIDATION_PROFILE")
        return 2
    try:
        runtime = _probe_runtime(registry.snapshot(PROFILE_ID), check)
    except CredentialFileError:
        print("CREDENTIAL_FILE_ERROR")
        return 2
    present = runtime.credential.status.availability == "PRESENT"
    print("REAL NETWORK VALIDATION")
    print(f"Service: {profile.service_id}")
    print(f"Model family: {profile.model_family}")
    print(f"Model: {profile.model}")
    print(f"Profile Status: {profile.profile_status.value.upper()}")
    print(f"Base URL: {profile.base_url}")
    print(f"Secret: {'PRESENT' if present else 'MISSING'}")
    print(f"Check: {check}")
    if not present:
        print("API CALL COUNT: 0")
        return 2

    gateway = OpenAICompatibleAdapter()
    if check == "network":
        diagnostic = _network_diagnostics(runtime, gateway)
        print(json.dumps(diagnostic, ensure_ascii=False))
        return 0 if diagnostic["steps"][-1]["status"] == "ok" else 1
    if check in ("on", "off", "effort-low", "temperature", "top-p", "output-limit", "stream"):
        print("EXPERIMENTAL PROBE: temporary capability only; Profile remains EXPERIMENTAL")
    started = time.monotonic()
    usage = Usage()
    result_data: dict = {"check": check}
    try:
        if check == "full-chain":
            repository = MockRepository(RESOURCE_ROOT.joinpath("scenarios"))
            knowledge = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
            trace_path = Path.cwd() / "outputs/real-validation-traces.jsonl"
            app = Orchestrator(repository, DiagnosisService(), knowledge,
                               ProfileRegistry([profile], credentials, request_runtime=runtime), gateway,
                               JsonlTraceSink(trace_path))
            result = app.analyze(AnalysisRequest(Mode.ADVICE, PROFILE_ID), scenario=scenario)
            usage = result.usage
            result_data.update({
                "status": result.status.value,
                "error_code": result.error_code,
                "scenario": scenario,
                "structured_parse_ok": result.structured_parse_ok,
                "output_kind": ("pure_json" if result.structured_parse_ok
                                and result.generated_text.lstrip().startswith("{")
                                else "fenced_json" if result.structured_parse_ok else "invalid"),
                "generated_text_present": bool(result.generated_text),
                "inference_present": bool(result.inference),
                "recommendation_count": len(result.recommendations),
                "uncertainty_count": len(result.uncertainty),
                "rule_codes": [item.code for item in result.rule_results],
                "evidence_ids": [item.evidence_id for item in result.evidence],
                "trace_id": result.trace_id,
            })
        elif check == "stream":
            first_content_at = None
            content_deltas = 0
            reasoning_seen = False
            for event in gateway.stream(_request(check), runtime):
                if event.delta:
                    content_deltas += 1
                    if first_content_at is None:
                        first_content_at = time.monotonic()
                reasoning_seen = reasoning_seen or bool(event.reasoning_delta)
                if event.usage is not None:
                    usage = event.usage
            result_data.update({
                "status": "completed",
                "content_delta_count": content_deltas,
                "reasoning_delta_present": reasoning_seen,
                "ttft_ms": (round((first_content_at - started) * 1000, 3)
                            if first_content_at is not None else None),
            })
        else:
            if check == "invalid-model":
                runtime = replace(runtime, model="__fishery_invalid_model_validation__")
            response = gateway.complete(_request(check), runtime)
            usage = response.usage
            result_data.update({
                "status": "completed",
                "returned_model": response.returned_model,
                "content_present": bool(response.text),
                "reasoning_output_present": response.reasoning_present,
            })
    except GatewayError as exc:
        result_data.update({"status": "failed", "error_code": exc.code,
                            "error_option": exc.option})
    except Exception:
        # Never print SDK exceptions: their raw text may contain request details.
        result_data.update({"status": "failed", "error_code": "UNEXPECTED_ERROR"})
    result_data["total_latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    result_data["api_call_count"] = gateway.request_attempts
    print(json.dumps(result_data, ensure_ascii=False))
    _show_usage(usage, "Request Usage")
    session = UsageAccumulator()
    session.add(usage)
    _show_usage(session.snapshot().usage, "Validation Session Usage")
    return 0 if result_data["status"] == "completed" else 1
