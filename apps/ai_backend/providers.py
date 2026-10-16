"""Small static service registry; protocol references do not grant capabilities."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class AuthSpec(str, Enum):
    NONE = "NONE"
    REQUIRED_BEARER = "REQUIRED_BEARER"
    OPTIONAL_BEARER = "OPTIONAL_BEARER"


@dataclass(frozen=True)
class ProviderSpec:
    service_id: str
    display_name: str
    adapter_id: str
    protocol_spec_id: str
    default_base_url: str | None
    auth_spec: AuthSpec
    expected_credential_name: str | None
    metadata_method: str
    default_deployment: str


class ProviderRegistry:
    """Registration is independent of environment variables and network access."""

    _specs = MappingProxyType({
        "dashscope": ProviderSpec("dashscope", "Qwen · DashScope", "openai_chat",
            "dashscope_chat", "https://dashscope.aliyuncs.com/compatible-mode/v1",
            AuthSpec.REQUIRED_BEARER, "DASHSCOPE_API_KEY", "NONE", "cloud"),
        "deepseek_api": ProviderSpec("deepseek_api", "DeepSeek API", "openai_chat",
            "deepseek_chat", "https://api.deepseek.com", AuthSpec.REQUIRED_BEARER,
            "DEEPSEEK_API_KEY", "NONE", "cloud"),
        "ollama": ProviderSpec("ollama", "Ollama · 本地", "generic_openai_chat",
            "ollama_openai_chat", "http://127.0.0.1:11434/v1", AuthSpec.NONE,
            None, "OLLAMA_SHOW", "local"),
        "generic_openai": ProviderSpec("generic_openai", "Custom OpenAI-compatible",
            "generic_openai_chat", "generic_openai_chat", None, AuthSpec.OPTIONAL_BEARER,
            None, "NONE", "local"),
    })

    def all(self) -> tuple[ProviderSpec, ...]:
        return tuple(self._specs.values())

    def get(self, service_id: str) -> ProviderSpec:
        return self._specs["generic_openai" if service_id == "custom" else service_id]

    def for_service(self, service_id: str) -> ProviderSpec:
        # Lookup aliases/fallbacks never change a Profile's Capability Identity.
        return self._specs.get(service_id, self.get("generic_openai"))


PROVIDERS = ProviderRegistry()
