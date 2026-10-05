"""Explicit T5 diagnostic: reuse T3; never grant capability before success."""

from dataclasses import asdict, replace
import time

from .contracts import Status
from .model_gateway import GatewayError
from .model_options import GenerationOptions, ReasoningOptions, Support
from .evidence_resolver import CapabilityIdentity
from .tool_conversation import ToolCallingService
from .tools import ToolStatus


def run_tool_calling_probe(gateway, profile, registry, traces, *, runtime, policy=None):
    if profile.access_mode != "managed_custom" or profile.provider_kind == "mock":
        raise GatewayError("CAPABILITY_PROBE_UNSUPPORTED")
    if (runtime.profile_id != profile.profile_id
            or CapabilityIdentity.for_profile(runtime) != CapabilityIdentity.for_profile(profile)):
        raise GatewayError("PROFILE_IDENTITY_CHANGED")
    # Only this immutable diagnostic snapshot bypasses UNKNOWN. Stored defaults,
    # capability evidence and credentials are not changed by the diagnostic.
    diagnostic = replace(runtime, max_retries=0,
        default_generation=GenerationOptions(max_output_tokens=256),
        default_reasoning=ReasoningOptions(), default_response_mode="normal",
        capabilities=replace(runtime.capabilities, tool_calling=Support.SUPPORTED,
            max_output_tokens=Support.SUPPORTED, service_id=profile.service_id,
            adapter_id=profile.adapter_id, base_url=profile.base_url, model_id=profile.model))
    started = time.monotonic()
    result = ToolCallingService(gateway, registry, traces, policy=policy).converse("现在水质怎么样？请简短回答。", diagnostic)
    tool_status = result.tool_result.status.value if result.tool_result else None
    success = (result.status == Status.COMPLETED and result.error_code is None
        and result.request_1.outcome == "tool_calls"
        and result.tool_name == "get_current_water_quality" and bool(result.tool_call_id)
        and tool_status in (ToolStatus.OK.value, ToolStatus.NO_DATA.value)
        and result.request_2.outcome == "final_answer" and bool(result.generated_text.strip()))
    # Only the Adapter's narrow explicit protocol rejection is negative evidence.
    unsupported = (result.error_code == "TOOL_UNSUPPORTED"
                   and result.request_1.outcome == "failed"
                   and result.request_2.outcome == "not_started")
    return {"status": "success" if success else "unsupported" if unsupported else "failure",
        "verdict": "SUPPORTED" if success else "UNSUPPORTED" if unsupported else "UNKNOWN",
        "error_code": None if success else result.error_code or (
            "NO_TOOL_CALL" if result.request_1.outcome == "final_answer" else "CAPABILITY_PROBE_FAILED"),
        "model_requests": result.usage.request_count,
        "request_1": result.request_1.outcome, "request_2": result.request_2.outcome,
        "valid_tool_call": result.request_1.outcome == "tool_calls" and tool_status in ("OK", "NO_DATA"),
        "tool_result_status": tool_status, "final_answer_present": bool(result.generated_text.strip()),
        "latency_ms": round((time.monotonic() - started) * 1000, 3),
        "usage": asdict(result.usage), "trace_id": result.trace_id,
        "evidence_written": False}
