"""Provider-neutral model contracts, profile snapshots, and offline gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping, Protocol
import json
import os
import re
from urllib.parse import urlsplit

from .contracts import Mode, RuntimeInfo, Usage
from .model_options import (GenerationOptions, ModelCapabilities, OptionValidationError,
                            ProfileStatus, ReasoningMode, ReasoningOptions,
                            validate_options)


Capabilities = ModelCapabilities


@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    display_name: str
    provider_kind: str
    base_url: str
    model: str
    secret_env: str | None = None
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 30.0
    total_timeout_s: float = 120.0
    max_retries: int = 1
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    adapter_id: str = "generic_openai_chat"
    provider_id: str = "custom"
    profile_status: ProfileStatus = ProfileStatus.CUSTOM
    default_generation: GenerationOptions = field(default_factory=GenerationOptions)
    default_reasoning: ReasoningOptions = field(default_factory=ReasoningOptions)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if not all((self.profile_id, self.display_name, self.provider_kind, self.model, self.provider_id)):
            raise ValueError("profile identity and model are required")
        if self.adapter_id not in ("openai_chat", "generic_openai_chat"):
            raise ValueError("unsupported adapter_id")
        if self.adapter_id == "generic_openai_chat" and self.provider_id != "custom":
            raise ValueError("generic adapter requires custom provider identity")
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query
                or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("base_url must be an HTTP(S) URL without query or fragment")
        if self.secret_env is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.secret_env):
            raise ValueError("secret_env must be an environment variable name")
        if min(self.connect_timeout_s, self.read_timeout_s, self.total_timeout_s) <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_retries < 0 or self.max_retries > 3:
            raise ValueError("max_retries must be between 0 and 3")
        object.__setattr__(self, "profile_status", ProfileStatus(self.profile_status))
        if (self.capabilities.model_id not in (None, self.model)
                or self.capabilities.base_url not in (None, self.base_url)):
            raise ValueError("capabilities belong to a different base_url or exact model")
        declared = self.capabilities.source != "unknown" or any(
            getattr(self.capabilities, name).value != "unknown" for name in (
                "streaming", "temperature", "top_p", "max_output_tokens", "reasoning_on",
                "reasoning_off", "reasoning_effort", "structured_output", "tool_calling",
                "streaming_usage"))
        if declared and (self.capabilities.model_id != self.model
                         or self.capabilities.base_url != self.base_url):
            raise ValueError("declared capabilities require exact model and base_url scope")
        if self.profile_status == ProfileStatus.VERIFIED:
            if (self.capabilities.source != "user_verified" or not self.capabilities.verified_at
                    or self.capabilities.model_id != self.model
                    or self.capabilities.base_url != self.base_url):
                raise ValueError("verified profile requires scoped, dated user verification")
            if all(getattr(self.capabilities, name).value == "unknown" for name in (
                    "streaming", "temperature", "top_p", "max_output_tokens", "reasoning_on",
                    "reasoning_off", "reasoning_effort", "structured_output", "tool_calling")):
                raise ValueError("verified profile requires an explicit capability result")
            try:
                validate_options(self.default_generation, self.default_reasoning, self.capabilities)
            except OptionValidationError as exc:
                raise ValueError("verified defaults conflict with capabilities") from exc
        elif self.default_generation != GenerationOptions() or self.default_reasoning != ReasoningOptions():
            raise ValueError("unverified profiles cannot carry verified advanced defaults")

    @classmethod
    def from_dict(cls, data: dict) -> ModelProfile:
        values = dict(data)
        capability_data = dict(values.get("capabilities", {}))
        if not capability_data or capability_data.get("source", "unknown") == "unknown":
            # Only a fully unknown capability set may follow a changed model.
            if not any(value not in ("unknown", False) for key, value in capability_data.items()
                       if key in ("streaming", "temperature", "top_p", "max_output_tokens",
                                  "reasoning_on", "reasoning_off", "reasoning_effort",
                                  "structured_output", "tool_calling", "streaming_usage")):
                capability_data.setdefault("model_id", values["model"])
                capability_data.setdefault("base_url", values["base_url"])
        values["capabilities"] = ModelCapabilities(**capability_data)
        values["default_generation"] = GenerationOptions(**values.get("default_generation", {}))
        reasoning_data = dict(values.get("default_reasoning", {}))
        if "mode" in reasoning_data:
            reasoning_data["mode"] = ReasoningMode(reasoning_data["mode"])
        values["default_reasoning"] = ReasoningOptions(**reasoning_data)
        return cls(**values)


@dataclass(frozen=True)
class RuntimeSnapshot:
    profile_id: str
    display_name: str
    provider_kind: str
    base_url: str
    model: str
    secret_env: str | None
    connect_timeout_s: float
    read_timeout_s: float
    total_timeout_s: float
    max_retries: int
    capabilities: ModelCapabilities
    adapter_id: str
    provider_id: str
    profile_status: ProfileStatus
    default_generation: GenerationOptions
    default_reasoning: ReasoningOptions
    api_key: str | None = field(default=None, repr=False, compare=False)

    def public_info(self) -> RuntimeInfo:
        return RuntimeInfo(self.profile_id, self.provider_kind, self.model,
                           self.adapter_id, self.provider_id, self.profile_status.value)


class ProfileRegistry:
    def __init__(self, profiles: list[ModelProfile]):
        ids = [profile.profile_id for profile in profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate profile_id")
        self._profiles = {profile.profile_id: profile for profile in profiles}

    @classmethod
    def from_json(cls, path: Path) -> ProfileRegistry:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls([ModelProfile.from_dict(item) for item in data["profiles"]])

    def snapshot(self, profile_id: str, environ: Mapping[str, str] | None = None) -> RuntimeSnapshot:
        profile = self._profiles[profile_id]
        variables = os.environ if environ is None else environ
        key = variables.get(profile.secret_env) if profile.secret_env else None
        return RuntimeSnapshot(
            profile_id=profile.profile_id, display_name=profile.display_name,
            provider_kind=profile.provider_kind, base_url=profile.base_url, model=profile.model,
            secret_env=profile.secret_env, connect_timeout_s=profile.connect_timeout_s,
            read_timeout_s=profile.read_timeout_s, total_timeout_s=profile.total_timeout_s,
            max_retries=profile.max_retries, capabilities=profile.capabilities,
            adapter_id=profile.adapter_id, provider_id=profile.provider_id,
            profile_status=profile.profile_status, default_generation=profile.default_generation,
            default_reasoning=profile.default_reasoning, api_key=key,
        )


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelRequest:
    mode: Mode
    messages: tuple[ModelMessage, ...]
    generation: GenerationOptions = field(default_factory=GenerationOptions)
    reasoning: ReasoningOptions | None = None


def effective_options(request: ModelRequest, runtime: RuntimeSnapshot
                      ) -> tuple[GenerationOptions, ReasoningOptions]:
    defaults = runtime.default_generation
    explicit = request.generation
    generation = GenerationOptions(
        max_output_tokens=(explicit.max_output_tokens if explicit.max_output_tokens is not None
                           else defaults.max_output_tokens),
        temperature=(explicit.temperature if explicit.temperature is not None else defaults.temperature),
        top_p=(explicit.top_p if explicit.top_p is not None else defaults.top_p),
    )
    reasoning = request.reasoning if request.reasoning is not None else runtime.default_reasoning
    return generation, reasoning


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: Usage = field(default_factory=Usage)
    returned_model: str | None = None
    reasoning_present: bool = False


@dataclass(frozen=True)
class ModelEvent:
    delta: str = ""
    usage: Usage | None = None
    reasoning_delta: str | None = None


class ModelGateway(Protocol):
    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse: ...
    def stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> Iterator[ModelEvent]: ...


class GatewayError(Exception):
    def __init__(self, code: str, *, option: str | None = None):
        super().__init__(code)
        self.code = code
        self.option = option


class RetryableGatewayError(GatewayError):
    pass


class MockGateway:
    """Offline model substitute. Profiles are selected, but no HTTP client is created."""

    def __init__(self):
        self.calls: list[tuple[str, RuntimeSnapshot]] = []

    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        generation, reasoning = effective_options(request, runtime)
        try:
            validate_options(generation, reasoning, runtime.capabilities)
        except OptionValidationError as exc:
            raise GatewayError(exc.code, option=exc.option) from exc
        self.calls.append((request.mode.value, runtime))
        text = json.dumps({
            "inference": "Mock 模型已根据规则结果和检索证据生成分析。",
            "recommendations": ["核对当前水质，并按确定性告警优先处理。"],
            "uncertainty": ["这是离线 Mock 输出，未经过真实模型验证。"],
        }, ensure_ascii=False)
        return ModelResponse(text)

    def stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> Iterator[ModelEvent]:
        generation, reasoning = effective_options(request, runtime)
        try:
            validate_options(generation, reasoning, runtime.capabilities)
        except OptionValidationError as exc:
            raise GatewayError(exc.code, option=exc.option) from exc
        response = self.complete(request, runtime)
        for part in (response.text[:len(response.text) // 2], response.text[len(response.text) // 2:]):
            yield ModelEvent(delta=part)
