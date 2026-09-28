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


@dataclass(frozen=True)
class Capabilities:
    streaming: bool = True
    tool_calling: bool = False


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
    capabilities: Capabilities = field(default_factory=Capabilities)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if not all((self.profile_id, self.display_name, self.provider_kind, self.model)):
            raise ValueError("profile identity and model are required")
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an HTTP(S) URL without query or fragment")
        if self.secret_env is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.secret_env):
            raise ValueError("secret_env must be an environment variable name")
        if min(self.connect_timeout_s, self.read_timeout_s, self.total_timeout_s) <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_retries < 0 or self.max_retries > 3:
            raise ValueError("max_retries must be between 0 and 3")

    @classmethod
    def from_dict(cls, data: dict) -> ModelProfile:
        values = dict(data)
        values["capabilities"] = Capabilities(**values.get("capabilities", {}))
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
    capabilities: Capabilities
    api_key: str | None = field(default=None, repr=False, compare=False)

    def public_info(self) -> RuntimeInfo:
        return RuntimeInfo(self.profile_id, self.provider_kind, self.model)


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
            profile.profile_id, profile.display_name, profile.provider_kind,
            profile.base_url, profile.model, profile.secret_env,
            profile.connect_timeout_s, profile.read_timeout_s,
            profile.total_timeout_s, profile.max_retries,
            profile.capabilities, key,
        )


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelRequest:
    mode: Mode
    messages: tuple[ModelMessage, ...]
    max_tokens: int = 1024


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: Usage | None = None


@dataclass(frozen=True)
class ModelEvent:
    delta: str = ""
    usage: Usage | None = None


class ModelGateway(Protocol):
    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse: ...
    def stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> Iterator[ModelEvent]: ...


class GatewayError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RetryableGatewayError(GatewayError):
    pass


class MockGateway:
    """Offline model substitute. Profiles are selected, but no HTTP client is created."""

    def __init__(self):
        self.calls: list[tuple[str, RuntimeSnapshot]] = []

    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse:
        self.calls.append((request.mode.value, runtime))
        text = json.dumps({
            "inference": "Mock 模型已根据规则结果和检索证据生成分析。",
            "recommendations": ["核对当前水质，并按确定性告警优先处理。"],
            "uncertainty": ["这是离线 Mock 输出，未经过真实模型验证。"],
        }, ensure_ascii=False)
        return ModelResponse(text)

    def stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> Iterator[ModelEvent]:
        if not runtime.capabilities.streaming:
            raise GatewayError("STREAMING_UNSUPPORTED")
        response = self.complete(request, runtime)
        for part in (response.text[:len(response.text) // 2], response.text[len(response.text) // 2:]):
            yield ModelEvent(delta=part)
