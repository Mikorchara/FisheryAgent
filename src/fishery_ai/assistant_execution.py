"""Startup-frozen maintainer release scope and Web confirmation binding; no I/O loop."""

from dataclasses import asdict, dataclass, field
import hashlib
from importlib.resources import files
import json
import re

from .assistant import AssistantError, MULTI_ROUND_PROMPT_ID, MULTI_ROUND_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION
from .history_projection import PROJECTION_VERSION, ProjectionId
from .protocol_specs import protocol_for
from .tool_conversation import ToolExecutionMode


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def release_scope(profile, policy, registry, projection):
    """Safe maintainer facts, including fingerprints of actual executable definitions."""
    definitions = policy.model_definitions(registry)
    return {"preset_id": profile.preset_id, "preset_variant": profile.preset_variant,
        "contract_version": profile.preset_contract_version,
        "identity": [profile.service_id, profile.adapter_id, profile.base_url, profile.model],
        "protocol_spec": asdict(profile.preset_protocol_spec or protocol_for(profile)),
        "thinking": profile.default_reasoning.mode.value, "response_mode": profile.default_response_mode,
        "prompt_id": MULTI_ROUND_PROMPT_ID, "prompt_sha256": _hash(MULTI_ROUND_SYSTEM_INSTRUCTION),
        "history_projection": projection.value, "history_version": PROJECTION_VERSION,
        "tools": [d.name for d in definitions],
        "tool_definitions_sha256": _hash([{"name": d.name, "description": d.description,
            "parameters": d.parameters_dict()} for d in definitions])}


@dataclass(frozen=True)
class AssistantMultiRoundRelease:
    release_id: str
    status: str
    scope_json: str = field(repr=False)
    qualification_id: str | None = None
    validated_at: str | None = None

    def __post_init__(self):
        try:
            scope = json.loads(self.scope_json)
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.release_id)
                    or self.status not in ("candidate", "released", "local_experimental")
                    or set(scope) != {"preset_id", "preset_variant", "contract_version", "identity", "protocol_spec",
                        "thinking", "response_mode", "prompt_id", "prompt_sha256", "history_projection",
                        "history_version", "tools", "tool_definitions_sha256"}
                    or not isinstance(scope["identity"], list) or len(scope["identity"]) != 4
                    or not isinstance(scope["tools"], list) or not 1 <= len(scope["tools"]) <= 3
                    or any(not isinstance(v, str) or not v for v in scope["identity"] + scope["tools"])
                    or len(set(scope["tools"])) != len(scope["tools"])
                    or scope["thinking"] != "off" or scope["response_mode"] != "normal"):
                raise ValueError()
            if self.status == "released":
                from .contracts import parse_time
                if not isinstance(self.qualification_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.qualification_id):
                    raise ValueError()
                parse_time(self.validated_at)
            if self.status == "local_experimental" and (self.qualification_id is not None or self.validated_at is not None):
                raise ValueError()  # Trial approval is not real model qualification.
            object.__setattr__(self, "scope_json", _json(scope))
        except (ValueError, TypeError, AttributeError):
            raise AssistantError("INVALID_ASSISTANT_EXECUTION_CONFIG") from None


@dataclass(frozen=True)
class AssistantExecutionConfig:
    multi_round_enabled: bool = False
    releases: tuple[AssistantMultiRoundRelease, ...] = ()

    def __post_init__(self):
        if (type(self.multi_round_enabled) is not bool or not isinstance(self.releases, (tuple, list))
                or any(not isinstance(r, AssistantMultiRoundRelease) for r in self.releases)
                or len({r.release_id for r in self.releases}) != len(self.releases)
                or len({r.scope_json for r in self.releases}) != len(self.releases)):
            raise AssistantError("INVALID_ASSISTANT_EXECUTION_CONFIG")
        object.__setattr__(self, "releases", tuple(self.releases))

    @classmethod
    def from_dict(cls, data):
        try:
            if (set(data) != {"schema_version", "multi_round_enabled", "releases"}
                    or type(data["schema_version"]) is not int or data["schema_version"] != 1
                    or not isinstance(data["releases"], list)):
                raise ValueError()
            records = []
            for r in data["releases"]:
                if set(r) != {"release_id", "status", "scope", "qualification_id", "validated_at"}:
                    raise ValueError()
                records.append(AssistantMultiRoundRelease(r["release_id"], r["status"], _json(r["scope"]),
                                                        r["qualification_id"], r["validated_at"]))
            return cls(data["multi_round_enabled"], tuple(records))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AssistantError("INVALID_ASSISTANT_EXECUTION_CONFIG") from None


def load_assistant_execution_config():
    """One fixed package path. Load once per app epoch, never accept a Web path."""
    try:
        return AssistantExecutionConfig.from_dict(json.loads(files("fishery_ai").joinpath(
            "resources/profiles/assistant_execution.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        raise AssistantError("INVALID_ASSISTANT_EXECUTION_CONFIG") from None


@dataclass(frozen=True)
class AssistantExecutionProfile:
    mode: ToolExecutionMode
    revision: str
    release_status: str
    mode_reason: str

    def public(self):
        return {"mode": self.mode.value, "max_model_requests":
            3 if self.mode == ToolExecutionMode.BOUNDED_MULTI_ROUND else 2, "revision": self.revision,
            "release_status": self.release_status, "mode_reason": self.mode_reason}


def resolve_execution_profile(config, profile, policy, registry, *, epoch, projection):
    scope = release_scope(profile, policy, registry, projection)
    matched = next((r for r in config.releases if r.scope_json == _json(scope)), None)
    multi = config.multi_round_enabled and matched is not None and matched.status in ("released", "local_experimental")
    reason = ("active" if multi else "flag_disabled" if not config.multi_round_enabled else
              "candidate" if matched is not None and matched.status == "candidate" else "scope_not_published")
    mode = ToolExecutionMode.BOUNDED_MULTI_ROUND if multi else ToolExecutionMode.SINGLE_ROUND
    revision = _hash({"epoch": epoch, "config": asdict(config), "scope": scope, "policy": asdict(policy),
        "mode": mode.value, "system_sha256": _hash(MULTI_ROUND_SYSTEM_INSTRUCTION if multi else SYSTEM_INSTRUCTION),
        "runtime": {"credential_ref": profile.credential_ref, "auth": profile.auth_spec.value,
            "timeouts": [profile.connect_timeout_s, profile.read_timeout_s, profile.total_timeout_s],
            "generation": asdict(profile.default_generation), "reasoning": asdict(profile.default_reasoning),
            "max_retries": profile.max_retries}})
    return AssistantExecutionProfile(mode, revision, matched.status if matched else "unmatched", reason)
