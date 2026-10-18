"""Provider-neutral model contracts, profile snapshots, and offline gateway."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Mapping, Protocol
from types import MappingProxyType
import json
import re
from urllib.parse import urlsplit

from .contracts import Mode, RuntimeInfo, Usage
from .credentials import CredentialSnapshot, CredentialStore
from .providers import AuthSpec
from .tool_argument_diagnostics import (ArgumentStage, ArgumentRejection, ToolArgumentError,
    public_argument_diagnostic, rejection)
from .model_options import (CapabilitySource, GenerationOptions, ModelCapabilities,
                            OptionValidationError, ProfileStatus, ReasoningMode, ReasoningOptions,
                            normalize_base_url, validate_options, Support)

if TYPE_CHECKING:
    from .manual import ManualRequest, ManualResponse
    from .protocol_specs import ProtocolSpec


Capabilities = ModelCapabilities

# Local inference can take longer before the first response than a cloud API.
# These finite defaults apply only when a local Profile does not specify values.
DEFAULT_LOCAL_READ_TIMEOUT_S = 120.0
DEFAULT_LOCAL_TOTAL_TIMEOUT_S = 180.0


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
    default_response_mode: str = "normal"
    service_id: str | None = None
    model_family: str | None = None
    auth_spec: AuthSpec | None = None
    credential_ref: str | None = None
    access_mode: str = "managed_custom"
    preset_id: str | None = None
    preset_variant: str | None = None
    preset_contract_version: str | None = None
    preset_response_modes: tuple[str, ...] = ()
    preset_protocol_spec: ProtocolSpec | None = field(default=None, repr=False)
    preset_is_default: bool = False

    # Original project declaration stays separate from the resolved view. This
    # prevents a previous resolution becoming new evidence on the next apply.
    capability_basis: ModelCapabilities | None = field(default=None, repr=False, compare=False)
    capability_evidence: tuple = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "preset_response_modes", tuple(self.preset_response_modes))
        if self.access_mode not in ("managed_custom", "preset"):
            raise ValueError("invalid access_mode")
        if self.access_mode == "preset" and not all((self.preset_id, self.preset_variant, self.preset_contract_version)):
            raise ValueError("preset requires a versioned template and variant")
        parsed = urlsplit(self.base_url)
        if not all((self.profile_id, self.display_name, self.provider_kind, self.model, self.provider_id)):
            raise ValueError("profile identity and model are required")
        if self.adapter_id not in ("openai_chat", "generic_openai_chat"):
            raise ValueError("unsupported adapter_id")
        if self.adapter_id == "generic_openai_chat" and self.provider_id not in ("custom", "ollama", "generic_openai"):
            raise ValueError("generic adapter requires custom, generic_openai or ollama provider identity")
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query
                or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("base_url must be an HTTP(S) URL without query or fragment")
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))
        if self.secret_env and self.credential_ref and self.secret_env != self.credential_ref:
            raise ValueError("secret_env and credential_ref must refer to the same variable")
        reference = self.credential_ref or self.secret_env
        object.__setattr__(self, "secret_env", reference)
        object.__setattr__(self, "credential_ref", reference)
        if reference is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", reference):
            raise ValueError("secret_env must be an environment variable name")
        auth = self.auth_spec or (AuthSpec.REQUIRED_BEARER if reference or self.provider_kind == "cloud"
                                  else AuthSpec.OPTIONAL_BEARER)
        object.__setattr__(self, "auth_spec", AuthSpec(auth))
        legacy_services = {"qwen": "dashscope", "deepseek": "deepseek_api"}
        service_id = self.service_id or legacy_services.get(self.provider_id, self.provider_id)
        family = self.model_family or self.provider_id
        if family not in ("qwen", "deepseek", "unknown"):
            family = "unknown"
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", service_id):
            raise ValueError("service_id must be a lowercase machine identifier")
        object.__setattr__(self, "service_id", service_id)
        object.__setattr__(self, "model_family", family)
        if self.adapter_id == "generic_openai_chat" and service_id not in ("custom", "ollama", "generic_openai"):
            raise ValueError("generic adapter requires service_id custom, generic_openai or ollama")
        if min(self.connect_timeout_s, self.read_timeout_s, self.total_timeout_s) <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_retries < 0 or self.max_retries > 3:
            raise ValueError("max_retries must be between 0 and 3")
        object.__setattr__(self, "profile_status", ProfileStatus(self.profile_status))
        if self.default_response_mode not in ("normal", "streaming"):
            raise ValueError("default_response_mode must be normal or streaming")
        capabilities = self.capabilities
        declared = capabilities.source != CapabilitySource.UNKNOWN or any(
            getattr(self.capabilities, name).value != "unknown" for name in (
                "streaming", "temperature", "top_p", "max_output_tokens", "reasoning_on",
                "reasoning_off", "reasoning_effort", "structured_output", "tool_calling",
                "streaming_usage", "thinking_streaming_combination", "thinking_off_streaming_combination"))
        if (declared and capabilities.model_id == self.model
                and capabilities.base_url == self.base_url
                and capabilities.service_id in (None, service_id)):
            # Bundled legacy declarations live inside this Profile, so its adapter
            # and derived service provide a safe one-time scope for old fields.
            capabilities = replace(capabilities,
                                   service_id=capabilities.service_id or service_id,
                                   adapter_id=capabilities.adapter_id or self.adapter_id)
            object.__setattr__(self, "capabilities", capabilities)
        if (capabilities.model_id not in (None, self.model)
                or capabilities.base_url not in (None, self.base_url)
                or capabilities.service_id not in (None, service_id)
                or capabilities.adapter_id not in (None, self.adapter_id)):
            raise ValueError("capabilities belong to a different service, adapter, base_url or model")
        if declared and (self.capabilities.model_id != self.model
                         or self.capabilities.base_url != self.base_url
                         or self.capabilities.service_id != service_id
                         or self.capabilities.adapter_id != self.adapter_id):
            raise ValueError("declared capabilities require exact service, adapter, model and URL")
        if self.profile_status == ProfileStatus.VERIFIED:
            declared_user_verified = any(
                getattr(self.capabilities, name).value != "unknown"
                and self.capabilities.source_for(name) == CapabilitySource.USER_VERIFIED
                for name in ("streaming", "temperature", "top_p", "max_output_tokens",
                             "reasoning_on", "reasoning_off", "reasoning_effort",
                             "structured_output", "tool_calling", "streaming_usage"))
            if (not declared_user_verified or not self.capabilities.verified_at
                    or self.capabilities.model_id != self.model
                    or self.capabilities.base_url != self.base_url
                    or self.capabilities.service_id != service_id):
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
            try:
                validate_options(self.default_generation, self.default_reasoning, self.capabilities)
            except OptionValidationError as exc:
                # A saved preference is not capability evidence. Keep preferences
                # when support is UNKNOWN; the request boundary will apply safe
                # defaults until the exact capability has been verified.
                if (exc.code not in ("OPTION_UNKNOWN", "OPTION_UNSUPPORTED") or
                        exc.option in ("temperature", "top_p", "max_output_tokens")):
                    raise ValueError("profile defaults conflict with scoped capabilities") from exc
        if self.capability_basis is None:
            object.__setattr__(self, "capability_basis", self.capabilities)

    @classmethod
    def from_dict(cls, data: dict) -> ModelProfile:
        values = dict(data)
        if values.get("provider_kind") == "local":
            values.setdefault("read_timeout_s", DEFAULT_LOCAL_READ_TIMEOUT_S)
            values.setdefault("total_timeout_s", DEFAULT_LOCAL_TOTAL_TIMEOUT_S)
        legacy_provider = values.get("provider_id", "custom")
        services = {"qwen": "dashscope", "deepseek": "deepseek_api"}
        values.setdefault("service_id", services.get(legacy_provider, legacy_provider))
        values.setdefault("provider_id", {"dashscope": "qwen", "deepseek_api": "deepseek"}.get(
            values["service_id"], values["service_id"]))
        values.setdefault("model_family", legacy_provider if legacy_provider in ("qwen", "deepseek")
                          else "unknown")
        capability_data = dict(values.get("capabilities", {}))
        if capability_data.get("source") == "experimental":
            capability_data["source"] = "UNKNOWN"
        if isinstance(capability_data.get("evidence"), dict):
            capability_data["evidence"] = tuple(capability_data["evidence"].items())
        if not capability_data or str(capability_data.get("source", "unknown")).lower() in (
                "unknown", "experimental"):
            # Only a fully unknown capability set may follow a changed model.
            if not any(value not in ("unknown", False) for key, value in capability_data.items()
                       if key in ("streaming", "temperature", "top_p", "max_output_tokens",
                                  "reasoning_on", "reasoning_off", "reasoning_effort",
                                  "structured_output", "tool_calling", "streaming_usage")):
                capability_data.setdefault("model_id", values["model"])
                capability_data.setdefault("base_url", values["base_url"])
                capability_data.setdefault("service_id", values["service_id"])
                capability_data.setdefault("adapter_id", values["adapter_id"])
        values["capabilities"] = ModelCapabilities(**capability_data)
        values["default_generation"] = GenerationOptions(**values.get("default_generation", {}))
        reasoning_data = dict(values.get("default_reasoning", {}))
        requested_thinking = values.pop("default_thinking_mode", None)
        if requested_thinking is not None:
            reasoning_data["mode"] = requested_thinking
        if "mode" in reasoning_data:
            reasoning_data["mode"] = ReasoningMode(reasoning_data["mode"])
        values["default_reasoning"] = ReasoningOptions(**reasoning_data)
        return cls(**values)


def effective_runtime_defaults(profile: ModelProfile
                                ) -> tuple[ReasoningOptions, str, list[str]]:
    """Resolve stored preferences without treating UNKNOWN as capability evidence."""
    if profile.access_mode == "preset":
        return profile.default_reasoning, profile.default_response_mode, []
    reasoning = profile.default_reasoning
    response_mode = profile.default_response_mode
    notices = []
    if (reasoning.mode == ReasoningMode.ON
            and profile.capabilities.reasoning_on != Support.SUPPORTED):
        reasoning = ReasoningOptions(ReasoningMode.AUTO)
        notices.append("THINKING_DEFAULT_FALLBACK")
    elif (reasoning.mode == ReasoningMode.OFF
          and profile.capabilities.reasoning_off != Support.SUPPORTED):
        reasoning = ReasoningOptions(ReasoningMode.AUTO)
        notices.append("THINKING_DEFAULT_FALLBACK")
    if response_mode == "streaming" and profile.capabilities.streaming != Support.SUPPORTED:
        response_mode = "normal"
        notices.append("RESPONSE_DEFAULT_FALLBACK")
    effective_on = reasoning.mode == ReasoningMode.ON or (
        reasoning.mode == ReasoningMode.AUTO and profile.capabilities.thinking_default is True)
    if (response_mode == "streaming" and effective_on
            and profile.capabilities.thinking_streaming_combination != Support.SUPPORTED):
        response_mode = "normal"
        notices.append("COMBINATION_DEFAULT_FALLBACK")
    if (response_mode == "streaming" and reasoning.mode == ReasoningMode.OFF
            and profile.capabilities.thinking_off_streaming_combination != Support.SUPPORTED):
        response_mode = "normal"
        notices.append("COMBINATION_DEFAULT_FALLBACK")
    return reasoning, response_mode, notices


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
    default_response_mode: str = "normal"
    credential: CredentialSnapshot = field(default_factory=CredentialSnapshot.none_required,
                                            repr=False, compare=False)
    service_id: str = "custom"
    model_family: str = "unknown"
    auth_spec: AuthSpec = AuthSpec.OPTIONAL_BEARER
    access_mode: str = "managed_custom"
    preset_id: str | None = None
    preset_variant: str | None = None
    preset_contract_version: str | None = None
    preset_response_modes: tuple[str, ...] = ()
    preset_protocol_spec: ProtocolSpec | None = field(default=None, repr=False)
    # Internal transport cost ceiling; not a Profile field or capability grant.
    transport_output_token_limit: int | None = field(default=None, repr=False)
    # Server-only range approval; absent preserves the legacy transport ceilings.
    transport_output_token_ceiling: int | None = field(default=None, repr=False)

    @property
    def protocol_spec(self):
        from .protocol_specs import protocol_for
        return self.preset_protocol_spec or protocol_for(self)

    @property
    def api_key(self) -> str | None:
        """Legacy internal bridge; never include this accessor in public serializers."""
        return self.credential._for_adapter()

    def public_info(self) -> RuntimeInfo:
        return RuntimeInfo(self.profile_id, self.provider_kind, self.model,
                           self.adapter_id, self.provider_id, self.profile_status.value,
                           self.service_id, self.model_family, self.access_mode,
                           self.preset_id, self.preset_variant, self.preset_contract_version)


class ProfileRegistry:
    def __init__(self, profiles: list[ModelProfile], credential_store: CredentialStore | None = None,
                 *, request_runtime: RuntimeSnapshot | None = None):
        if (any(not isinstance(profile, ModelProfile) for profile in profiles)
                or credential_store is not None and not isinstance(credential_store, CredentialStore)
                or request_runtime is not None and not isinstance(request_runtime, RuntimeSnapshot)):
            raise TypeError("new Backend profile, credential store and runtime required")
        ids = [profile.profile_id for profile in profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate profile_id")
        self._profiles = {profile.profile_id: profile for profile in profiles}
        self.credential_store = credential_store if credential_store is not None else CredentialStore()
        self._request_runtime = request_runtime


    def snapshot(self, profile_id: str, environ: Mapping[str, str] | None = None,
                 *, apply_runtime_defaults: bool = True) -> RuntimeSnapshot:
        profile = self._profiles[profile_id]
        if self._request_runtime is not None and environ is None:
            if self._request_runtime.profile_id != profile_id:
                raise ValueError("request runtime belongs to another Profile")
            return self._request_runtime
        store = self.credential_store if environ is None else CredentialStore(process_env=environ)
        credential = store.resolve(profile.credential_ref, profile.auth_spec)
        if apply_runtime_defaults:
            safe_reasoning, safe_response, _ = effective_runtime_defaults(profile)
        else:
            safe_reasoning, safe_response = ReasoningOptions(), "normal"
        return RuntimeSnapshot(
            profile_id=profile.profile_id, display_name=profile.display_name,
            provider_kind=profile.provider_kind, base_url=profile.base_url, model=profile.model,
            secret_env=profile.secret_env, connect_timeout_s=profile.connect_timeout_s,
            read_timeout_s=profile.read_timeout_s, total_timeout_s=profile.total_timeout_s,
            max_retries=profile.max_retries, capabilities=profile.capabilities,
            adapter_id=profile.adapter_id, provider_id=profile.provider_id,
            profile_status=profile.profile_status,
            default_generation=profile.default_generation if apply_runtime_defaults else GenerationOptions(),
            default_reasoning=safe_reasoning,
            default_response_mode=safe_response, credential=credential, auth_spec=profile.auth_spec,
            service_id=profile.service_id or profile.provider_id,
            model_family=profile.model_family or "unknown",
            access_mode=profile.access_mode, preset_id=profile.preset_id,
            preset_variant=profile.preset_variant, preset_contract_version=profile.preset_contract_version,
            preset_response_modes=profile.preset_response_modes,
            preset_protocol_spec=profile.preset_protocol_spec,
        )


@dataclass(frozen=True)
class ModelToolDefinition:
    name: str
    description: str
    parameters: Mapping = field(repr=False)
    type: str = "function"

    def __post_init__(self) -> None:
        if (self.type != "function" or not isinstance(self.name, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.name)
                or not isinstance(self.description, str)):
            raise ValueError("invalid function definition")
        if not isinstance(self.parameters, Mapping) or self.parameters.get("type", "object") != "object":
            raise ValueError("parameters must be an object JSON Schema")
        try:
            copied = json.loads(json.dumps(_plain_json(self.parameters), allow_nan=False))
        except (TypeError, ValueError, RecursionError):
            raise ValueError("parameters must be JSON serializable") from None
        object.__setattr__(self, "parameters", _freeze_json(copied))

    def parameters_dict(self) -> dict:
        """Return a detached JSON Schema, not a mutable reference to this contract."""
        return _plain_json(self.parameters)


def _freeze_json(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _plain_json(value):
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _json_content(text: str):
    def invalid_constant(_value):
        raise ValueError("non-finite JSON value")
    if not isinstance(text, str):
        raise ValueError("expected a JSON string")
    try:
        return json.loads(text, parse_constant=invalid_constant)
    except (ValueError, RecursionError):
        raise ValueError("invalid JSON string") from None


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    function_name: str
    arguments_json: str = field(repr=False)
    type: str = "function"

    def __post_init__(self) -> None:
        if (self.type != "function" or not isinstance(self.id, str) or not self.id.strip()
                or not isinstance(self.function_name, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.function_name)):
            raise ValueError("invalid function call")
        try:
            arguments = _json_content(self.arguments_json)
        except (ValueError, RecursionError):
            raise ToolArgumentError(rejection(ArgumentStage.MODEL_CONTRACT,
                ArgumentRejection.MALFORMED_JSON, self.arguments_json)) from None
        if not isinstance(arguments, dict):
            raise ToolArgumentError(rejection(ArgumentStage.MODEL_CONTRACT,
                ArgumentRejection.NOT_OBJECT, self.arguments_json))


def _tool_calls_tuple(calls) -> tuple[ModelToolCall, ...]:
    values = tuple(calls)
    if not all(isinstance(call, ModelToolCall) for call in values):
        raise ValueError("tool_calls must contain ModelToolCall")
    if len({call.id for call in values}) != len(values):
        raise ValueError("duplicate tool call ID")
    return values


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str | None = None
    tool_calls: tuple[ModelToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        calls = _tool_calls_tuple(self.tool_calls)
        object.__setattr__(self, "tool_calls", calls)
        if self.role not in ("system", "user", "assistant", "tool"):
            raise ValueError("invalid message role")
        if self.content is not None and not isinstance(self.content, str):
            raise ValueError("message content must be text or None")
        if calls and self.role != "assistant":
            raise ValueError("only assistant messages can carry tool_calls")
        if self.content is None and not (self.role == "assistant" and calls):
            raise ValueError("None content requires assistant tool_calls")
        if self.role == "tool":
            if not isinstance(self.tool_call_id, str) or not self.tool_call_id.strip():
                raise ValueError("tool result requires tool_call_id")
            _json_content(self.content)
        elif self.tool_call_id is not None:
            raise ValueError("only tool results can carry tool_call_id")


@dataclass(frozen=True)
class ModelRequest:
    mode: Mode
    messages: tuple[ModelMessage, ...]
    generation: GenerationOptions = field(default_factory=GenerationOptions)
    reasoning: ReasoningOptions | None = None
    tools: tuple[ModelToolDefinition, ...] = ()
    tool_choice: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if not all(isinstance(message, ModelMessage) for message in self.messages):
            raise ValueError("messages must contain ModelMessage")
        if not all(isinstance(tool, ModelToolDefinition) for tool in self.tools):
            raise ValueError("tools must contain ModelToolDefinition")
        if len({tool.name for tool in self.tools}) != len(self.tools):
            raise ValueError("duplicate tool definition name")
        if self.tool_choice not in (None, "auto", "none", "required"):
            raise ValueError("invalid tool_choice")
        if self.tool_choice is not None and not self.tools:
            raise ValueError("tool_choice requires tools")

    @property
    def uses_tools(self) -> bool:
        return bool(self.tools or any(message.tool_calls or message.role == "tool"
                                      for message in self.messages))


def validate_tool_request(request: ModelRequest, runtime: RuntimeSnapshot, *, streaming: bool) -> None:
    """Protocol availability grants no model support; Manual bypasses this contract."""
    if not request.uses_tools:
        return
    if streaming:
        raise GatewayError("TOOL_STREAMING_NOT_IMPLEMENTED")
    support = runtime.capabilities.tool_calling
    if support != Support.SUPPORTED:
        raise GatewayError("OPTION_UNKNOWN" if support == Support.UNKNOWN else "OPTION_UNSUPPORTED",
                           option="tool_calling")


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
    if runtime.access_mode == "preset" and reasoning != runtime.default_reasoning:
        raise GatewayError("PRESET_OPTION_LOCKED", option="reasoning")
    return generation, reasoning


def validate_preset_response(runtime, *, streaming: bool) -> None:
    """Published combinations are an allowlist, independent of runtime evidence."""
    if (runtime.access_mode == "preset" and runtime.preset_response_modes
            and ("streaming" if streaming else "normal") not in runtime.preset_response_modes):
        raise GatewayError("PRESET_MODE_NOT_PUBLISHED")


@dataclass(frozen=True)
class ModelResponse:
    text: str | None
    usage: Usage = field(default_factory=Usage)
    returned_model: str | None = None
    reasoning_present: bool = False
    reasoning_content: str | None = None
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        calls = _tool_calls_tuple(self.tool_calls)
        object.__setattr__(self, "tool_calls", calls)
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("response text must be a string or None")
        if self.text is None and not calls:
            raise ValueError("None response text requires tool_calls")
        if self.finish_reason is not None and not isinstance(self.finish_reason, str):
            raise ValueError("finish_reason must be text or None")


@dataclass(frozen=True)
class ModelEvent:
    delta: str = ""
    usage: Usage | None = None
    reasoning_delta: str | None = None
    finish_reason: str | None = None


class ModelGateway(Protocol):
    def complete(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse: ...
    # Internal transport foundation, not the product stream()/Web capability gate.
    def complete_tool_stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> ModelResponse: ...
    def stream(self, request: ModelRequest, runtime: RuntimeSnapshot) -> Iterator[ModelEvent]: ...
    def manual_complete(self, request: ManualRequest, runtime: RuntimeSnapshot) -> ManualResponse: ...
    def manual_stream(self, request: ManualRequest, runtime: RuntimeSnapshot) -> Iterator[ManualResponse]: ...


class GatewayError(Exception):
    def __init__(self, code: str, *, option: str | None = None, argument_diagnostic=None):
        super().__init__(code)
        self.code = code
        self.option = option
        self.argument_diagnostic = argument_diagnostic if public_argument_diagnostic(argument_diagnostic) else None


class RetryableGatewayError(GatewayError):
    pass


class StreamingModelError(GatewayError):
    """Safe statistics of an unsuccessful stream; never partial text or calls."""

    def __init__(self, code: str, *, usage: Usage, finish_reason: str | None = None, argument_diagnostic=None):
        super().__init__(code, argument_diagnostic=argument_diagnostic)
        self.usage = usage if isinstance(usage, Usage) else Usage()
        self.finish_reason = finish_reason if finish_reason in (
            "stop", "length", "tool_calls", "function_call", "content_filter") else None
