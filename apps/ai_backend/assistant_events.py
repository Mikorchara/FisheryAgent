"""Bounded ordered POST event channel; publication and HTTP live outside Backend."""
from collections import deque
from copy import deepcopy
import json
import threading
import time
from .model_gateway import GatewayError

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
