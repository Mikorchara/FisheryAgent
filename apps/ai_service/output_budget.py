"""Versioned local Qwen output envelope, applied only AFTER exact release matching."""
from dataclasses import replace
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.model_options import ReasoningMode
from apps.ai_backend.tool_conversation import ToolExecutionMode
from .runtime.release_contracts import _hash

CONTRACT = 'management-qwen-output-range@1'
PRESET = 'dashscope-qwen38-flash-r1'
MIN_TOKENS, MAX_TOKENS = 1, 4096
RECOMMENDED = (512,1024,2048,4096)


def key(preset,transport):
    return preset+':'+transport


def validate_tokens(value):
    if type(value) is not int or not MIN_TOKENS<=value<=MAX_TOKENS:
        raise GatewayError('INVALID_ASSISTANT_OUTPUT_BUDGET')


def validate_overrides(values):
    if not isinstance(values,dict) or set(values)-{key(PRESET,m) for m in ('normal','streaming')}:
        raise ValueError()
    for value in values.values():
        try: validate_tokens(value)
        except GatewayError: raise ValueError() from None


def eligible(profile,decision):
    return (profile.preset_id==PRESET and profile.default_reasoning.mode==ReasoningMode.OFF
        and profile.preset_protocol_spec is not None
        and profile.preset_protocol_spec.max_output_tokens_field in ('max_tokens','max_completion_tokens')
        and profile.total_timeout_s==120 and profile.max_retries==0
        and decision.can_send and decision.profile.release_status=='local_experimental'
        and decision.profile.mode==ToolExecutionMode.BOUNDED_MULTI_ROUND)


def apply(profile,decision,store):
    if store is None or not eligible(profile,decision):
        return decision
    decision=replace(decision,output_budget_default=decision.max_output_tokens)
    document=store.document()
    selected=document['output_budgets'].get(key(profile.preset_id,decision.model_transport.value.lower()))
    revision=document['budget_revision']
    if not revision:
        return replace(decision,output_budget_revision=0)
    if selected is not None:
        validate_tokens(selected)
    fingerprint=_hash({'base_execution_revision':decision.profile.revision,'contract':CONTRACT,
        'min_output_tokens':MIN_TOKENS,'max_output_tokens':MAX_TOKENS,'selected':selected,
        'budget_revision':revision,'qualification':'LOCAL_APPROVAL_NOT_PROVIDER_QUALIFICATION'})
    return replace(decision,profile=replace(decision.profile,revision=fingerprint),
        max_output_tokens=selected if selected is not None else decision.max_output_tokens,
        output_budget_contract=CONTRACT if selected is not None else None,output_budget_revision=revision)
