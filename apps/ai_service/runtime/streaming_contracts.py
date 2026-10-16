"""Maintainer-only Streaming scope and ephemeral safe SSE observations, no Tool loop."""

from collections import deque
from dataclasses import asdict, dataclass, field
from copy import deepcopy
from importlib.resources import files
import json
import re
import threading
import time

from .assistant import AssistantError
from .release_contracts import _hash, _json, release_scope
from apps.ai_backend.model_gateway import GatewayError


def streaming_scope(profile, policy, registry, projection):
    scope = release_scope(profile, policy, registry, projection)
    scope.update(response_mode="streaming", model_transport="STREAMING",
                 assembler_version="openai-tool-stream-assembler@1")
    return scope


@dataclass(frozen=True)
class AssistantStreamingRelease:
    scope_json: str = field(repr=False)
    status: str = "candidate"
    qualification_id: str | None = None
    validated_at: str | None = None
    max_output_tokens: int = 256

    def __post_init__(self):
        try:
            scope = json.loads(self.scope_json)
            expected = {"preset_id", "preset_variant", "contract_version", "identity", "protocol_spec",
                "thinking", "response_mode", "prompt_id", "prompt_sha256", "history_projection", "history_version",
                "tools", "tool_definitions_sha256", "model_transport", "assembler_version"}
            if (set(scope) != expected or scope["thinking"] != "off" or scope["response_mode"] != "streaming"
                    or scope["model_transport"] != "STREAMING" or self.status not in ("candidate", "released", "local_experimental")
                    or type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 512
                    or not isinstance(scope["identity"], list) or len(scope["identity"]) != 4
                    or not isinstance(scope["tools"], list) or not 1 <= len(scope["tools"]) <= 3
                    or any(not isinstance(v, str) or not v for v in scope["identity"] + scope["tools"])
                    or len(set(scope["tools"])) != len(scope["tools"])):
                raise ValueError()
            if self.status == "released":
                from apps.ai_backend.contracts import parse_time
                if not isinstance(self.qualification_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.qualification_id):
                    raise ValueError()
                parse_time(self.validated_at)
            elif self.qualification_id is not None or self.validated_at is not None:
                raise ValueError()
            object.__setattr__(self, "scope_json", _json(scope))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AssistantError("INVALID_ASSISTANT_STREAMING_CONFIG") from None


@dataclass(frozen=True)
class AssistantStreamingConfig:
    enabled: bool = False
    releases: tuple[AssistantStreamingRelease, ...] = ()

    def __post_init__(self):
        if (type(self.enabled) is not bool or not isinstance(self.releases, (tuple, list))
                or any(not isinstance(r, AssistantStreamingRelease) for r in self.releases)
                or len({r.scope_json for r in self.releases}) != len(self.releases)):
            raise AssistantError("INVALID_ASSISTANT_STREAMING_CONFIG")
        object.__setattr__(self, "releases", tuple(self.releases))


def resolve_streaming_profile(config, profile, policy, registry, *, epoch, projection):
    scope = streaming_scope(profile, policy, registry, projection)
    record = next((r for r in config.releases if r.scope_json == _json(scope)), None)
    available = config.enabled and record is not None and record.status in ("released", "local_experimental")
    return {"available": available, "mode": "BOUNDED_MULTI_ROUND", "max_model_requests": 3,
        "release_status": record.status if record else "unpublished",
        "max_output_tokens": record.max_output_tokens if record else None,
        "mode_reason": "active" if available else "flag_disabled" if not config.enabled else
            "candidate" if record is not None else "scope_not_published",
        "revision": _hash({"epoch": epoch, "config": asdict(config), "scope": scope, "policy": asdict(policy),
            "timeouts": [profile.connect_timeout_s, profile.read_timeout_s, profile.total_timeout_s],
            "generation": asdict(profile.default_generation), "credential_ref": profile.credential_ref,
            "auth": profile.auth_spec.value, "retry": profile.max_retries})}
