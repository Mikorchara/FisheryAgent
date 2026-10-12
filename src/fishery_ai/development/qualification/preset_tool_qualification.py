"""Maintainer-only bounded qualification; no evidence or publication side effects."""

from dataclasses import asdict, replace
import time

from ...contracts import Mode, Status, Usage, UsageAccumulator
from ...execution import check_cancelled
from ...model_gateway import GatewayError, ModelMessage, ModelRequest, ModelResponse
from ...model_options import GenerationOptions, Support
from ...tool_conversation import ToolCallingService, SYSTEM_INSTRUCTION
from ...tools.policy import load_tool_policies, ToolPolicy
from ...tools.registry import CURRENT_WATER_QUALITY


class _QualificationGateway:
    """One round-trip (<=2 calls) plus one concept question; never retries."""
    def __init__(self, gateway, model):
        self.gateway, self.model = gateway, model
        self.calls = 0
        self.returned_models = []

    def complete(self, request, runtime):
        check_cancelled()
        if self.calls >= 3:
            raise GatewayError("QUALIFICATION_REQUEST_LIMIT")
        self.calls += 1
        response = self.gateway.complete(request, runtime)
        if not isinstance(response, ModelResponse):
            raise GatewayError("INVALID_RESPONSE")
        # Missing returned ID is reported as unavailable; aliases are not guessed.
        returned = response.returned_model
        self.returned_models.append(returned if returned == self.model else None)
        if returned is not None and returned != self.model:
            raise GatewayError("MODEL_IDENTITY_MISMATCH")
        check_cancelled()
        return response


def qualify_preset_tools(gateway, profile, runtime, registry, traces):
    """Does not touch Preset JSON, Managed Evidence, credentials or user overrides."""
    identity = tuple(getattr(profile, field) for field in ("service_id", "adapter_id", "base_url", "model"))
    actual = tuple(getattr(runtime, field) for field in ("service_id", "adapter_id", "base_url", "model"))
    if (profile.access_mode != "preset" or profile.preset_variant != "off"
            or runtime.access_mode != "preset" or runtime.profile_id != profile.profile_id
            or actual != identity or runtime.protocol_spec != profile.preset_protocol_spec
            or runtime.default_reasoning != profile.default_reasoning
            or "normal" not in profile.preset_response_modes):
        raise GatewayError("QUALIFICATION_IDENTITY_MISMATCH")
    if runtime.credential.status.availability not in ("PRESENT", "NONE_REQUIRED"):
        raise GatewayError("SECRET_MISSING")
    builtin = load_tool_policies()["assistant"]
    if not builtin.allows(CURRENT_WATER_QUALITY):
        raise GatewayError("TOOL_NOT_ALLOWED")
    policy = ToolPolicy("assistant", True, (CURRENT_WATER_QUALITY,))
    policy.validate_registry(registry)
    # Explicit diagnostic authorization only; published contract stays unchanged.
    diagnostic = replace(runtime, max_retries=0, default_response_mode="normal",
        default_generation=GenerationOptions(max_output_tokens=192),
        capabilities=replace(runtime.capabilities, tool_calling=Support.SUPPORTED,
                             max_output_tokens=Support.SUPPORTED))
    bounded = _QualificationGateway(gateway, runtime.model)
    start = time.monotonic()
    conversation = ToolCallingService(bounded, registry, traces, policy=policy).converse(
        "现在水质怎么样？请简短回答。", diagnostic)
    result = {"verdict":"UNKNOWN", "error_code":conversation.error_code,
        "request_1":conversation.request_1.outcome,
        "request_2":conversation.request_2.outcome,
        "tool_name":conversation.tool_name if conversation.tool_name == CURRENT_WATER_QUALITY else None,
        "tool_call_id_valid":bool(conversation.tool_call_id),
        "arguments_empty_object":conversation.tool_result is not None and conversation.tool_result.error_code is None,
        "tool_result_status":conversation.tool_result.status.value if conversation.tool_result else None,
        "final_answer_present":bool(conversation.generated_text.strip()),
        "final_finish_reason":conversation.final_finish_reason,
        "concept_question":{"outcome":"not_started", "no_tool":None, "content_present":False,
                            "usage":asdict(Usage()), "error_code":None},
        "round_trip_usage":asdict(conversation.usage),
        "request_1_usage":asdict(conversation.request_1.usage),
        "request_2_usage":asdict(conversation.request_2.usage),
        "usage":asdict(conversation.usage), "trace_id":conversation.trace_id,
        "qualified_variant":"off", "response_mode":"normal", "retry":0,
        "max_output_tokens":192, "concept_max_output_tokens":384, "max_tool_rounds":1}
    complete_round = (conversation.status == Status.COMPLETED and conversation.error_code is None
        and conversation.request_1.outcome == "tool_calls"
        and conversation.tool_name == CURRENT_WATER_QUALITY and bool(conversation.tool_call_id)
        and result["tool_result_status"] in ("OK", "NO_DATA")
        and conversation.request_2.outcome == "final_answer" and result["final_answer_present"]
        and conversation.final_finish_reason == "stop")
    concept_usage = Usage()
    try:
        if complete_round:
            check_cancelled()
            # Definitions remain available to prove model discretion; if it calls
            # a tool here, reject without Executor or a follow-up model request.
            request = ModelRequest(Mode.CHAT, (ModelMessage("system", SYSTEM_INSTRUCTION),
                ModelMessage("user", "什么是溶氧？请用一两句话简短回答，不要展开。")),
                tools=policy.model_definitions(registry), tool_choice="auto",
                generation=GenerationOptions(max_output_tokens=384))
            response = bounded.complete(request, diagnostic)
            concept_usage = response.usage or Usage()
            no_tool = not response.tool_calls
            concept_ok = no_tool and bool(response.text and response.text.strip()) and response.finish_reason == "stop"
            result["concept_question"] = {"outcome":"direct_answer" if concept_ok else "rejected",
                "no_tool":no_tool, "content_present":bool(response.text and response.text.strip()),
                "finish_reason":response.finish_reason if response.finish_reason in ("stop","length","tool_calls") else None,
                "usage":asdict(response.usage or Usage()),
                "error_code":None if concept_ok else "CONCEPT_QUESTION_NOT_DIRECT"}
            if concept_ok:
                result.update(verdict="SUPPORTED", error_code=None)
            else:
                result["error_code"] = "CONCEPT_QUESTION_NOT_DIRECT"
        else:
            result["error_code"] = result["error_code"] or "QUALIFICATION_ROUND_TRIP_INCOMPLETE"
    except GatewayError as exc:
        result["concept_question"]["outcome"] = "failed"
        result["concept_question"]["error_code"] = exc.code
        result["error_code"] = exc.code
    except Exception:
        result["error_code"] = "QUALIFICATION_FAILED"
    if bounded.calls > conversation.usage.request_count:
        accumulator = UsageAccumulator()
        for usage in (conversation.request_1.usage, conversation.request_2.usage, concept_usage):
            accumulator.add(usage)
        try:
            result["usage"] = asdict(accumulator.snapshot())
        except ValueError:
            result["usage"] = {"request_count":3, "reported_count":sum(
                usage.source.value == "provider" for usage in (
                    conversation.request_1.usage, conversation.request_2.usage, concept_usage)), "usage":asdict(Usage())}
    result.update(model_requests=bounded.calls, transport_attempts=getattr(gateway,"request_attempts",None),
                  returned_models=bounded.returned_models, latency_ms=round((time.monotonic()-start)*1000,3))
    return result
