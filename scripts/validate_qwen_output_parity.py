"""Explicit four-request Qwen output parity check; UTF-8 records, no retries."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import time
import uuid

from dotenv import load_dotenv

from fishery_ai.application import Orchestrator, result_to_dict
from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.contracts import AnalysisRequest, Mode, Usage, UsageAccumulator, UsageSource
from fishery_ai.domain import DiagnosisService
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.model_gateway import GatewayError, ProfileRegistry
from fishery_ai.model_options import ReasoningMode, ReasoningOptions
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.repositories import MockRepository
from fishery_ai.web import _builtin_profiles


PROFILE_ID = "qwen-plus-experimental"
QUESTION = "当前水质情况怎么样？"
CASES = (("normal", "off"), ("streaming", "off"), ("normal", "on"), ("streaming", "on"))


class RecordingAdapter(OpenAICompatibleAdapter):
    """Record only a digest of public request options; never serialize RuntimeSnapshot."""
    def __init__(self):
        super().__init__()
        self.input_digest = None
        self.returned_model = None

    def check(self, request, runtime, *, stream):
        if (self.request_attempts or runtime.max_retries != 0 or runtime.model != "qwen-plus"
                or runtime.service_id != "dashscope"
                or runtime.base_url != "https://dashscope.aliyuncs.com/compatible-mode/v1"):
            raise GatewayError("VALIDATION_SCOPE_ERROR")
        body = self._kwargs(request, runtime, stream=stream)
        # The only allowed differences are stream=True and usage transport options.
        body.pop("stream", None)
        body.pop("stream_options", None)
        self.input_digest = hashlib.sha256(json.dumps(
            body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def complete(self, request, runtime):
        self.check(request, runtime, stream=False)
        response = super().complete(request, runtime)
        self.returned_model = response.returned_model
        return response

    def stream(self, request, runtime):
        self.check(request, runtime, stream=True)
        yield from super().stream(request, runtime)


def main():
    parser = argparse.ArgumentParser(description="4 次 Qwen low_oxygen Normal/Streaming 对照（可能计费）")
    parser.add_argument("--confirm-four-network-requests", action="store_true")
    args = parser.parse_args()
    if not args.confirm_four_network_requests:
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
    # Application startup boundary only. Never inspect, print, or persist Secret values.
    load_dotenv(workspace / ".env", override=False)
    if not os.environ.get(original.secret_env):
        print("QWEN_SECRET MISSING")
        return 2
    print("QWEN_SECRET PRESENT", flush=True)
    fixed_time = datetime.now(timezone.utc)
    output = workspace / "outputs"
    output.mkdir(exist_ok=True)
    suffix = fixed_time.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    path = output / ("qwen-output-parity-" + suffix + ".json")
    trace_path = output / ("qwen-output-parity-traces-" + suffix + ".jsonl")
    repository = MockRepository(RESOURCE_ROOT.joinpath("mock/scenarios.json"))
    knowledge = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
    accumulator = UsageAccumulator()
    records = []
    attempts = 0
    # Fixed four-case list; each case has one gateway call and SDK/Gateway retries=0.
    for mode, thinking in CASES:
        gateway = RecordingAdapter()
        profile = replace(original, max_retries=0)
        app = Orchestrator(repository, DiagnosisService(), knowledge, ProfileRegistry([profile]),
            gateway, JsonlTraceSink(trace_path), clock=lambda: fixed_time)
        request = AnalysisRequest(Mode.CHAT, PROFILE_ID, QUESTION,
                                  reasoning=ReasoningOptions(ReasoningMode(thinking)))
        started = time.monotonic()
        deltas = []
        terminal = {}
        result = None
        try:
            if mode == "normal":
                result = app.analyze(request, scenario="low_oxygen")
                public = result_to_dict(result)
                deltas = [result.generated_text]
            else:
                for event in app.analyze_stream(request, scenario="low_oxygen"):
                    if event.kind == "content_delta":
                        deltas.append(event.data["delta"])
                    if event.kind in ("completed", "failed"):
                        terminal = event.data
                public = terminal.get("result") or {}
        except Exception:
            # Do not print SDK exception text or a traceback with sensitive context.
            public = {"status": "failed", "error_code": "VALIDATION_INTERNAL_ERROR"}
        attempts += gateway.request_attempts
        if attempts > 4:
            raise RuntimeError("VALIDATION_REQUEST_BUDGET_EXCEEDED")
        usage = result.usage if result is not None else None
        if mode == "streaming":
            values = public.get("usage") or {}
            usage = Usage(**{**values, "source": UsageSource(values.get("source", "unavailable"))})
        accumulator.add(usage)
        item = {"mode": mode, "thinking": thinking, "request_attempts": gateway.request_attempts,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "ttft_ms": terminal.get("ttft_ms"), "delta_count": len(deltas) if mode == "streaming" else None,
                "input_digest": gateway.input_digest, "returned_model": gateway.returned_model,
                "result": public, "deltas": deltas}
        records.append(item)
        # Save after every call so a later interruption cannot lose earlier paid results.
        record = {"validation": "Qwen Normal/Streaming output parity", "recorded_at": fixed_time.isoformat(),
                  "profile_id": PROFILE_ID, "scenario": "low_oxygen", "question": QUESTION,
                  "sdk_retries": 0, "gateway_retries": 0, "request_attempts": attempts,
                  "trace_path": str(trace_path), "cases": records,
                  "session_usage": {"request_count": accumulator.snapshot().request_count,
                      "reported_count": accumulator.snapshot().reported_count,
                      "usage": result_to_dict(accumulator.snapshot().usage)}}
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(json.dumps({key: item[key] for key in ("mode", "thinking", "latency_ms", "ttft_ms",
            "request_attempts", "delta_count")} | {"status": public.get("status"),
            "error_code": public.get("error_code"), "parse_ok": public.get("structured_parse_ok"),
            "usage": public.get("usage")}, ensure_ascii=True), flush=True)
    print("RECORD", path, flush=True)
    print("TOTAL_USAGE", json.dumps(record["session_usage"], ensure_ascii=True), flush=True)
    return 0 if all(r["result"].get("structured_parse_ok") for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
