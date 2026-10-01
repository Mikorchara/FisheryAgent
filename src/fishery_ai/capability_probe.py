"""One explicit diagnostic request; no domain analysis, retries or raw model recording."""

from dataclasses import asdict, replace
import re
import time

from .contracts import Mode, Usage
from .model_gateway import GatewayError, ModelMessage, ModelRequest, ProfileRegistry
from .model_options import GenerationOptions, ReasoningMode, ReasoningOptions, Support


PROBE_FIELDS = {"streaming", "reasoning_on", "reasoning_off", "thinking_streaming_combination"}


def run_capability_probe(gateway, profile, capability: str, *, runtime=None) -> dict:
    if capability not in PROBE_FIELDS:
        raise ValueError("invalid probe capability")
    streaming = capability in ("streaming", "thinking_streaming_combination")
    mode = (ReasoningMode.ON if capability in ("reasoning_on", "thinking_streaming_combination")
            else ReasoningMode.OFF if capability == "reasoning_off" else ReasoningMode.AUTO)
    runtime = runtime if runtime is not None else ProfileRegistry([profile]).snapshot(profile.profile_id)
    overrides = {capability: Support.SUPPORTED}
    if capability == "streaming" and runtime.capabilities.thinking_default is True:
        # AUTO uses the model default, but this diagnostic records streaming only.
        overrides["thinking_streaming_combination"] = Support.SUPPORTED
    capabilities = replace(runtime.capabilities, **overrides, service_id=runtime.service_id,
                           adapter_id=runtime.adapter_id, base_url=runtime.base_url,
                           model_id=runtime.model)
    runtime = replace(runtime, capabilities=capabilities, max_retries=0,
                      default_generation=GenerationOptions(), default_reasoning=ReasoningOptions())
    request = ModelRequest(Mode.CHAT, (ModelMessage("user", "只回复 OK"),),
                           generation=GenerationOptions(), reasoning=ReasoningOptions(mode))
    started = time.monotonic()
    result = {"capability_name": capability, "status": "failure", "delta_count": 0,
              "reasoning_delta_count": 0, "ttft_ms": None, "content_ttft_ms": None,
              "usage": asdict(Usage()), "returned_model": None}
    try:
        if streaming:
            events = gateway.stream(request, runtime)
            try:
                for event in events:
                    if event.delta or event.reasoning_delta:
                        elapsed = round((time.monotonic() - started) * 1000, 3)
                        if result["ttft_ms"] is None:
                            result["ttft_ms"] = elapsed
                    if event.delta:
                        result["delta_count"] += 1
                        if result["content_ttft_ms"] is None:
                            result["content_ttft_ms"] = elapsed
                    if event.reasoning_delta:
                        result["reasoning_delta_count"] += 1
                    if event.usage is not None:
                        result["usage"] = asdict(event.usage)
            finally:
                close = getattr(events, "close", None)
                if callable(close):
                    close()
            if not result["delta_count"]:
                raise GatewayError("PROBE_NO_CONTENT")
        else:
            response = gateway.complete(request, runtime)
            if not response.text.strip():
                raise GatewayError("PROBE_NO_CONTENT")
            result["usage"] = asdict(response.usage or Usage())
            result["returned_model"] = response.returned_model
        result["status"] = "success"
    except GatewayError as exc:
        code = exc.code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", exc.code) else "GATEWAY_ERROR"
        explicit_refusal = (code == "STREAM_UNSUPPORTED" and streaming or
                            code == "THINKING_UNSUPPORTED" and mode != ReasoningMode.AUTO)
        result.update(status="unsupported" if explicit_refusal else "failure", error_code=code)
    except Exception:
        result["error_code"] = "CAPABILITY_PROBE_FAILED"
    result["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result
