"""Offline, reviewed official declarations; never discover from URL/model substrings."""


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
    # Compatibility entry point, now using the same conservative resolver as
    # local evidence and JSON profile loading. Lazy import avoids a data cycle.
    from .evidence_resolver import project_evidence, resolve_capabilities
    return resolve_capabilities(profile, project_evidence(profile))
