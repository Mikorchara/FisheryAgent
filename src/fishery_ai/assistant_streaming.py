"""Maintainer-only Streaming scope and ephemeral safe SSE observations, no Tool loop."""

from collections import deque
from dataclasses import asdict, dataclass, field
from copy import deepcopy
import json
import re
import threading
import time

from .assistant import AssistantError
from .assistant_execution import _hash, _json, release_scope
from .model_gateway import GatewayError


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

    def __post_init__(self):
        try:
            scope = json.loads(self.scope_json)
            expected = {"preset_id", "preset_variant", "contract_version", "identity", "protocol_spec",
                "thinking", "response_mode", "prompt_id", "prompt_sha256", "history_projection", "history_version",
                "tools", "tool_definitions_sha256", "model_transport", "assembler_version"}
            if (set(scope) != expected or scope["thinking"] != "off" or scope["response_mode"] != "streaming"
                    or scope["model_transport"] != "STREAMING" or self.status not in ("candidate", "released")
                    or not isinstance(scope["identity"], list) or len(scope["identity"]) != 4
                    or not isinstance(scope["tools"], list) or not 1 <= len(scope["tools"]) <= 3
                    or any(not isinstance(v, str) or not v for v in scope["identity"] + scope["tools"])
                    or len(set(scope["tools"])) != len(scope["tools"])):
                raise ValueError()
            if self.status == "released":
                from .contracts import parse_time
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
    available = config.enabled and record is not None and record.status == "released"
    return {"available": available, "mode": "BOUNDED_MULTI_ROUND", "max_model_requests": 3,
        "release_status": record.status if record else "unpublished",
        "revision": _hash({"epoch": epoch, "config": asdict(config), "scope": scope, "policy": asdict(policy),
            "timeouts": [profile.connect_timeout_s, profile.read_timeout_s, profile.total_timeout_s],
            "generation": asdict(profile.default_generation), "credential_ref": profile.credential_ref,
            "auth": profile.auth_spec.value, "retry": profile.max_retries})}


class AssistantEventChannel:
    """One POST, monotonic snapshots, bounded in-memory queue; no replay or regeneration."""
    MAX_EVENTS = 512
    MAX_PREVIEWS = 128
    MAX_PREVIEW_BYTES = 16384

    def __init__(self, handle, epoch):
        self.handle, self.epoch = handle, epoch
        self._condition = threading.Condition()
        self._queue = deque()
        self._sequence = self._previews = 0
        self._last_preview_at = 0.0
        self._last_request_index = None
        self._failed = self._terminal = False

    def emit(self, kind, payload, *, terminal=False):
        with self._condition:
            if self._terminal or self._failed and not terminal:
                return
            if self._sequence >= self.MAX_EVENTS and not terminal:
                self._failed = True
                raise GatewayError("ASSISTANT_EVENT_LIMIT")
            self._sequence += 1
            value = {"event_schema_version": 1, "request_id": self.handle.request_id,
                "epoch": self.epoch, "seq": self._sequence, "kind": kind, **payload}
            self._queue.append((self._sequence, json.dumps(value, ensure_ascii=False, allow_nan=False)))
            self._terminal = terminal
            self._condition.notify_all()

    def activity(self, info):
        # RequestHandle public_info is the existing allowlisted Activity projection.
        phase = info.get("phase")
        index = int(phase[-1]) if phase in ("REQUEST_1", "REQUEST_2", "REQUEST_3") else None
        if index and index != self._last_request_index:
            self._last_request_index = index
            self._last_preview_at = 0.0
            self.emit("preview_reset", {"request_index": index})
        activity = info.get("activity")
        if activity:
            model = next((s for s in reversed(activity["steps"]) if s["kind"] == "model"), None)
            if model and model.get("outcome") == "tool_calls":
                self.emit("preview_reset", {"request_index": model["request_index"]})
        self.emit("activity", {"state": info["state"], "phase": phase,
            "activity": deepcopy(activity), "error_code": info.get("error_code")})

    def preview(self, text, secret):
        if not isinstance(text, str) or not text or self._last_request_index is None:
            return
        now = time.monotonic()
        if self._previews >= self.MAX_PREVIEWS or self._previews and now - self._last_preview_at < 0.05:
            return
        # Withhold a trailing partial Secret before replacing complete occurrences.
        # Cumulative text means a Key split across arbitrary SDK chunks cannot leak.
        if secret:
            held = 0
            if not text.endswith(secret):
                held = next((n for n in range(min(len(secret)-1, len(text)), 0, -1)
                             if text.endswith(secret[:n])), 0)
            text = (text[:-held] if held else text).replace(secret, "[REDACTED]")
        encoded = text.encode("utf-8")
        text = encoded[:self.MAX_PREVIEW_BYTES].decode("utf-8", errors="ignore")
        self._previews += 1; self._last_preview_at = now
        self.emit("preview", {"request_index": self._last_request_index, "text": text,
            "preview_truncated": len(encoded) > self.MAX_PREVIEW_BYTES, "provisional": True})

    def events(self):
        delivered_terminal = False
        try:
            while True:
                with self._condition:
                    if not self._queue and not self._terminal:
                        self._condition.wait(timeout=1)
                    item = self._queue.popleft() if self._queue else None
                    finished = self._terminal and not self._queue
                if item is not None:
                    seq, data = item
                    if finished: delivered_terminal = True
                    yield f"id: {seq}\ndata: {data}\n\n"
                    if finished: return
                elif finished:
                    delivered_terminal = True
                    return
                else:
                    yield ": keep-alive\n\n"
        finally:
            if not delivered_terminal:
                self.handle.cancel()  # Disconnect closes the original I/O; never resumes generation.
