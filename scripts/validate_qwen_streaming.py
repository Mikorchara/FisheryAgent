"""Explicit one-request Qwen Streaming probe; no persistent capability change."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import uuid

from fishery_ai.credentials import CredentialFileError, CredentialStore

from fishery_ai.application import Orchestrator
from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.contracts import AnalysisRequest, Mode
from fishery_ai.domain import DiagnosisService
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.model_gateway import ProfileRegistry
from fishery_ai.model_options import Support
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.repositories import MockRepository
from fishery_ai.web import _builtin_profiles


PROFILE_ID = "qwen-plus-experimental"


def main() -> int:
    parser = argparse.ArgumentParser(description="一次真实 Qwen 应用级 Streaming 验证")
    parser.add_argument("--confirm-network", action="store_true")
    args = parser.parse_args()
    if not args.confirm_network:
        print("NETWORK_CONFIRMATION_REQUIRED")
        return 2

    workspace = Path.cwd()
    if not (workspace / "pyproject.toml").is_file():
        print("WORKSPACE_REQUIRED")
        return 2
    original = next(p for p in _builtin_profiles() if p.profile_id == PROFILE_ID)
    if original.max_retries != 0:
        print("RETRY_POLICY_MUST_BE_ZERO")
        return 2

    credentials = CredentialStore(workspace / ".env")
    try:
        present = credentials.status(original.credential_ref, original.auth_spec).availability == "PRESENT"
    except CredentialFileError:
        print("CREDENTIAL_FILE_ERROR")
        return 2
    print("QWEN_SECRET PRESENT" if present else "QWEN_SECRET MISSING")
    if not present:
        return 2

    # Probe permission exists only in memory. A success may justify a later scoped
    # Capability update, but this script does not modify a built-in Profile.
    probe = replace(original, capabilities=replace(original.capabilities,
                                                  streaming=Support.SUPPORTED))
    output_dir = workspace / "outputs"
    output_dir.mkdir(exist_ok=True)
    gateway = OpenAICompatibleAdapter()
    orchestrator = Orchestrator(
        MockRepository(RESOURCE_ROOT.joinpath("mock/scenarios.json")),
        DiagnosisService(), KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json")),
        ProfileRegistry([probe], credentials), gateway, JsonlTraceSink(output_dir / "web-traces.jsonl"),
    )
    delta_count = 0
    terminal = None
    for event in orchestrator.analyze_stream(
            AnalysisRequest(Mode.CHAT, PROFILE_ID, "当前水质情况怎么样？"),
            scenario="low_oxygen"):
        if event.kind == "content_delta":
            delta_count += 1
        if event.kind in ("completed", "failed"):
            terminal = event

    details = terminal.data if terminal else {}
    result = details.get("result") or {}
    record = {
        "validation": "A3.1.1 Qwen Streaming one request",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": PROFILE_ID,
        "model": original.model,
        "status": terminal.kind if terminal else "failed",
        "error_code": details.get("error_code") if terminal else "STREAM_INTERRUPTED",
        "delta_count": delta_count,
        "ttft_ms": details.get("ttft_ms"),
        "total_latency_ms": details.get("total_latency_ms"),
        "usage": result.get("usage"),
        "structured_parse_ok": result.get("structured_parse_ok"),
        "request_attempts": gateway.request_attempts,
    }
    record_path = output_dir / ("qwen-streaming-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".json")
    with record_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("STATUS", record["status"])
    print("ERROR_CODE", record["error_code"] or "none")
    print("DELTA_COUNT", delta_count)
    print("TTFT_MS", record["ttft_ms"] if record["ttft_ms"] is not None else "unavailable")
    print("TOTAL_LATENCY_MS", record["total_latency_ms"] if record["total_latency_ms"] is not None else "unavailable")
    print("USAGE", json.dumps(record["usage"], ensure_ascii=True))
    print("STRUCTURED_PARSE_OK", record["structured_parse_ok"])
    print("REQUEST_ATTEMPTS", gateway.request_attempts)
    print("RECORD", record_path)
    return 0 if terminal and terminal.kind == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
