"""One explicit diagnostic request; no domain analysis, retries or raw model recording."""

from dataclasses import asdict, replace
import re
import time

from .contracts import Mode, Usage
from .model_gateway import GatewayError, ModelMessage, ModelRequest, ProfileRegistry
from .model_options import GenerationOptions, ReasoningMode, ReasoningOptions, Support


PROBE_FIELDS = {"streaming", "reasoning_on", "reasoning_off", "thinking_streaming_combination", "thinking_off_streaming_combination"}


def run_capability_probe(gateway, profile, capability: str, *, runtime=None) -> dict:
    if capability not in PROBE_FIELDS:
        raise ValueError("invalid probe capability")
    if profile.access_mode == "preset":
        raise ValueError("preset contract is read-only")
    streaming = capability in ("streaming", "thinking_streaming_combination", "thinking_off_streaming_combination")
    mode = (ReasoningMode.ON if capability in ("reasoning_on", "thinking_streaming_combination")
            else ReasoningMode.OFF if capability in ("reasoning_off", "thinking_off_streaming_combination") else ReasoningMode.AUTO)
    runtime = runtime if runtime is not None else ProfileRegistry([profile]).snapshot(profile.profile_id)
    # This is a diagnostic copy, never the Profile or ordinary business runtime.
    # An unknown protocol switch must not be guessed from a model name.
    if mode != ReasoningMode.AUTO and runtime.protocol_spec.thinking_encoding is None:
        return {"capability_name": capability, "status": "failure",
                "error_code": "CAPABILITY_PROBE_UNSUPPORTED", "latency_ms": 0.0}
    overrides = {capability: Support.SUPPORTED}
    if capability == "thinking_off_streaming_combination":
        # Diagnostic output budget only; never persist token support as evidence.
        overrides["max_output_tokens"] = Support.SUPPORTED
    if capability == "streaming" and runtime.capabilities.thinking_default is True:
        # AUTO uses the model default, but this diagnostic records streaming only.
        overrides["thinking_streaming_combination"] = Support.SUPPORTED
    capabilities = replace(runtime.capabilities, **overrides, service_id=runtime.service_id,
                           adapter_id=runtime.adapter_id, base_url=runtime.base_url,
                           model_id=runtime.model)
    runtime = replace(runtime, capabilities=capabilities, max_retries=0,
                      default_generation=GenerationOptions(), default_reasoning=ReasoningOptions(),
                      read_timeout_s=min(runtime.read_timeout_s, 30.0),
                      total_timeout_s=min(runtime.total_timeout_s, 60.0))
    # The new OFF combination has an explicit diagnostic-only 16-token budget.
    # Other probes retain the existing token-capability policy.
    generation = GenerationOptions(max_output_tokens=16 if capability == "thinking_off_streaming_combination" else 64) if (
        runtime.capabilities.max_output_tokens == Support.SUPPORTED) else GenerationOptions()
    request = ModelRequest(Mode.CHAT, (ModelMessage("user", "只回复 OK"),),
                           generation=generation, reasoning=ReasoningOptions(mode))
    started = time.monotonic()
    result = {"capability_name": capability, "status": "failure", "delta_count": 0,
              "reasoning_delta_count": 0, "ttft_ms": None, "content_ttft_ms": None,
              "usage": asdict(Usage()), "returned_model": None}
    if capability == "thinking_off_streaming_combination":
        result["finish_reason"] = None
    try:
        if streaming:
            events = gateway.stream(request, runtime)
            try:
                for event in events:
                    if event.delta or event.reasoning_delta:
                        elapsed = round((time.monotonic() - started) * 1000, 3)
                        if result["ttft_ms"] is None:
                            result["ttft_ms"] = elapsed
                    if capability == "thinking_off_streaming_combination" and event.finish_reason:
                        if event.finish_reason not in ("stop", "length", "tool_calls", "function_call", "content_filter"):
                            raise GatewayError("INVALID_STREAM_EVENT")
                        result["finish_reason"] = event.finish_reason
                    if event.delta and (capability != "thinking_off_streaming_combination" or event.delta.strip()):
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
            if capability == "thinking_off_streaming_combination" and result["finish_reason"] != "stop":
                raise GatewayError("PROBE_INCOMPLETE_STREAM")
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
