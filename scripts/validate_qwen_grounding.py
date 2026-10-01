"""Explicit one-request Qwen grounding check; record Unicode results as UTF-8."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import uuid

from fishery_ai.credentials import CredentialFileError, CredentialStore

from fishery_ai.web import _builtin_profiles, create_app


PROFILE_ID = "qwen-plus-experimental"
QUESTION = "当前水质情况怎么样？"


def write_record(path: Path, record: dict) -> None:
    """Write a new local record without terminal encoding or replacement text."""
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="一次真实 Qwen low_oxygen Grounding 验证")
    parser.add_argument("--confirm-network", action="store_true")
    args = parser.parse_args()
    if not args.confirm_network:
        print("NETWORK_CONFIRMATION_REQUIRED")
        return 2

    workspace = Path.cwd()
    if not (workspace / "pyproject.toml").is_file():
        print("WORKSPACE_REQUIRED")
        return 2
    profile = next(item for item in _builtin_profiles() if item.profile_id == PROFILE_ID)
    if profile.max_retries != 0:
        print("RETRY_POLICY_MUST_BE_ZERO")
        return 2

    credentials = CredentialStore(workspace / ".env")
    try:
        present = credentials.status(profile.credential_ref, profile.auth_spec).availability == "PRESENT"
    except CredentialFileError:
        print("CREDENTIAL_FILE_ERROR")
        return 2
    print("QWEN_SECRET PRESENT" if present else "QWEN_SECRET MISSING")
    if not present:
        return 2

    output_dir = workspace / "outputs"
    output_dir.mkdir(exist_ok=True)
    record_path = output_dir / (
        "qwen-grounding-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-" + uuid.uuid4().hex[:8] + ".json")
    client = create_app(trace_path=output_dir / "web-traces.jsonl", credential_store=credentials).test_client()
    response = client.post("/api/analyze", json={
        "profile_id": PROFILE_ID, "scenario": "low_oxygen",
        "question": QUESTION, "confirm_network": True,
    })
    payload = response.get_json(silent=True) or {}
    result = payload.get("result") or {}
    allowed = ("status", "error_code", "observed_facts", "rule_results", "evidence",
               "inference", "recommendations", "uncertainty", "structured_parse_ok",
               "generated_text", "usage", "runtime", "trace_id")
    record = {
        "validation": "A3.0.3 Qwen low_oxygen",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "question": QUESTION, "http_status": response.status_code,
        "total_latency_ms": payload.get("total_latency_ms"),
        "result": {key: result.get(key) for key in allowed} if result else None,
        "error_code": payload.get("error_code") if not result else None,
    }
    write_record(record_path, record)
    # Console lines are ASCII-only; all model text and Usage live in the UTF-8 record.
    print(f"HTTP {response.status_code}")
    print(f"RECORD {record_path}")
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
