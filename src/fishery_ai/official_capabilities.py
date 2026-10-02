"""Offline, reviewed official declarations; never discover from URL/model substrings."""


REVIEWED_AT = "2026-10-01"
DASHSCOPE_CHAT_DOC = "https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions"
DASHSCOPE_THINKING_DOC = "https://help.aliyun.com/zh/model-studio/deep-thinking"
DASHSCOPE_OMNI_DOC = "https://help.aliyun.com/zh/model-studio/qwen-omni"
DEEPSEEK_CHAT_DOC = "https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/"
DEEPSEEK_THINKING_DOC = "https://api-docs.deepseek.com/guides/thinking_mode/"

# Clean-room reset: no active model-level declarations. Historical declarations
# are explicit offline fixtures only; ProtocolSpec remains independent.
DECLARATIONS = {}


def apply_official_capabilities(profile):
    # Compatibility entry point, now using the same conservative resolver as
    # local evidence and JSON profile loading. Lazy import avoids a data cycle.
    from .evidence_resolver import project_evidence, resolve_capabilities
    return resolve_capabilities(profile, project_evidence(profile))
