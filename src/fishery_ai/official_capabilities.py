"""Offline, reviewed official declarations; never discover from URL/model substrings."""

from dataclasses import replace

from .model_options import CapabilitySource, Support


REVIEWED_AT = "2026-10-01"
DASHSCOPE_CHAT_DOC = "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions"
DASHSCOPE_THINKING_DOC = "https://help.aliyun.com/zh/model-studio/deep-thinking"
DASHSCOPE_OMNI_DOC = "https://help.aliyun.com/zh/model-studio/qwen-omni"
DEEPSEEK_CHAT_DOC = "https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/"
DEEPSEEK_THINKING_DOC = "https://api-docs.deepseek.com/guides/thinking_mode/"

# Model IDs are exact. Endpoint entries are explicit, reviewed API roots.
DECLARATIONS = {
    ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"):
        (False, (), (DASHSCOPE_THINKING_DOC, DASHSCOPE_CHAT_DOC)),
    ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.8-flash"):
        (True, ("low", "medium", "xhigh"), (DASHSCOPE_THINKING_DOC, DASHSCOPE_CHAT_DOC)),
    ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.8-omni-flash"):
        (True, ("low", "medium", "xhigh"), (DASHSCOPE_CHAT_DOC, DASHSCOPE_OMNI_DOC)),
    ("deepseek_api", "https://api.deepseek.com", "deepseek-flash"):
        (True, ("low", "high", "max"), (DEEPSEEK_THINKING_DOC, DEEPSEEK_CHAT_DOC)),
    ("deepseek_api", "https://api.deepseek.com/v1", "deepseek-flash"):
        (True, ("low", "high", "max"), (DEEPSEEK_THINKING_DOC, DEEPSEEK_CHAT_DOC)),
}


def apply_official_capabilities(profile):
    declaration = DECLARATIONS.get((profile.service_id, profile.base_url, profile.model))
    if profile.adapter_id != "openai_chat" or declaration is None:
        return profile
    default, effort_values, _ = declaration
    capabilities = profile.capabilities
    updates = {"streaming": Support.SUPPORTED, "reasoning_on": Support.SUPPORTED,
               "reasoning_off": Support.SUPPORTED, "streaming_usage": Support.SUPPORTED,
               "thinking_streaming_combination": Support.SUPPORTED}
    if effort_values:
        updates["reasoning_effort"] = Support.SUPPORTED
    for name, status in updates.items():
        # Retain bundled historical user verification (Qwen Plus streaming).
        previous = capabilities.source_for(name)
        retain_user = (previous == CapabilitySource.USER_VERIFIED
                       and getattr(capabilities, name) != Support.UNKNOWN)
        capabilities = capabilities.with_evidence(name, CapabilitySource.OFFICIAL_DOCS)
        if retain_user:
            capabilities = capabilities.with_evidence(name, CapabilitySource.USER_VERIFIED)
        else:
            options = {name: status}
            if name == "reasoning_effort":
                options["effort_values"] = effort_values
            capabilities = replace(capabilities, **options)
    capabilities = capabilities.with_evidence("thinking_default", CapabilitySource.OFFICIAL_DOCS)
    capabilities = replace(capabilities, thinking_default=default,
                           effort_values=effort_values or capabilities.effort_values,
                           reasoning_temperature_conflict=(profile.service_id == "deepseek_api"),
                           service_id=profile.service_id,
                           adapter_id=profile.adapter_id, base_url=profile.base_url,
                           model_id=profile.model)
    return replace(profile, capabilities=capabilities)
