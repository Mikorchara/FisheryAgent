"""Small process-local request lifecycle; no credentials or model payload stored."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import secrets
import threading
import time
import uuid


_current = ContextVar("fishery_request_handle", default=None)
TERMINAL = {"CANCELLED", "COMPLETED", "FAILED"}


class RequestHandle:
    def __init__(self):
        self.request_id = uuid.uuid4().hex
        self.control_token = secrets.token_urlsafe(32)
        self.created_at = time.monotonic()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._hook = None
        self._claimed = False
        self.state = "RUNNING"
        self.error_code = None
        self.io_closed = False
        self.phase = None  # Optional safe UI observation; not model content or lifecycle state.
        self._activity = None  # Allowlisted derived metadata only, no arguments/results/receipts.
        self._activity_revision = 0
        self._committing = False

    def __repr__(self):
        return f"RequestHandle(state={self.state})"

    def start(self):
        with self._lock:
            if self._claimed:
                from .model_gateway import GatewayError
                raise GatewayError("REQUEST_ALREADY_EXECUTED")
            self._claimed = True
            self.check()

    def check(self):
        if self._cancel.is_set():
            from .model_gateway import GatewayError
            raise GatewayError("USER_CANCELLED")

    def bind(self, hook):
        with self._lock:
            self._hook = hook
            cancelled = self._cancel.is_set()
        if cancelled:
            hook()

    def unbind(self):
        with self._lock:
            self._hook = None

    def report_phase(self, phase):
        if phase not in ("REQUEST_1", "RUNNING_TOOL", "REQUEST_2", "REQUEST_3", "FINALIZING"):
            raise ValueError("invalid execution phase")
        with self._lock:
            if self.state == "RUNNING":
                self.phase = phase

    def report_steps(self, steps, *, budget, total_latency_ms=None):
        from .assistant_activity import project_activity
        with self._lock:
            if self.state in TERMINAL:
                return
            self._activity_revision += 1
            self._activity = project_activity(steps, request_id=self.request_id, budget=budget,
                state=self.state, revision=self._activity_revision, phase=self.phase,
                total_latency_ms=total_latency_ms)

    def finalize_result(self, record_result):
        """Serialize Stop against final trace+commit; never publish success before recording."""
        with self._lock:
            self._committing = True
            try:
                result = record_result(self._cancel.is_set())
                self.finish(result.error_code)
                return result
            finally:
                self._committing = False

    def cancel(self):
        with self._lock:
            if self._committing or self.state in TERMINAL or self.state == "CANCEL_REQUESTED":
                return
            self._cancel.set()
            self.state = "CANCEL_REQUESTED"
            if self._activity is not None:
                self._activity_revision += 1
                self._activity.update(state=self.state, revision=self._activity_revision)
            hook = self._hook
            if not self._claimed:
                self.state = "CANCELLED"
                self.error_code = "USER_CANCELLED"
                self.io_closed = True  # No I/O was started.
        if hook:
            try:
                hook()
            except RuntimeError:
                pass  # Event loop already closed; the execution owner finalizes state.

    def finish(self, error_code=None):
        with self._lock:
            self.error_code = "USER_CANCELLED" if self._cancel.is_set() else error_code
            self.state = "CANCELLED" if self._cancel.is_set() else "FAILED" if error_code else "COMPLETED"
            self._hook = None
            if self._activity is not None:
                from .assistant_activity import settle_activity
                self._activity_revision += 1
                self._activity.update(revision=self._activity_revision, phase=self.phase)
                settle_activity(self._activity, self.state, self.error_code)

    def public_info(self):
        with self._lock:
            info = {"request_id": self.request_id, "state": self.state,
                    "error_code": self.error_code, "backend_io_closed": self.io_closed,
                    "remote_compute_stopped": "unknown"}
            if self.phase is not None:
                info["phase"] = self.phase
            if self._activity is not None:
                info["activity"] = deepcopy(self._activity)
            return info


class RequestRegistry:
    def __init__(self, *, limit=8, ttl_s=300):
        self._lock = threading.RLock()
        self._items = {}
        self.limit, self.ttl_s = limit, ttl_s

    def create(self):
        from .model_gateway import GatewayError
        with self._lock:
            now = time.monotonic()
            for key, item in list(self._items.items()):
                if now - item.created_at > self.ttl_s and (not item._claimed or item.state in TERMINAL):
                    self._items.pop(key)
            if sum(item.state not in TERMINAL for item in self._items.values()) >= self.limit:
                raise GatewayError("REQUEST_LIMIT_REACHED")
            finished = [key for key, item in self._items.items() if item.state in TERMINAL]
            for key in finished[:-32]:
                self._items.pop(key)
            handle = RequestHandle()
            self._items[handle.request_id] = handle
            return handle

    def get(self, request_id, token):
        from .model_gateway import GatewayError
        with self._lock:
            handle = self._items.get(request_id) if isinstance(request_id, str) else None
            if (not handle or not isinstance(token, str) or not token.isascii()
                    or len(token) > 128 or not secrets.compare_digest(handle.control_token, token)):
                raise GatewayError("REQUEST_NOT_FOUND")
            if time.monotonic() - handle.created_at > self.ttl_s and not handle._claimed:
                self._items.pop(request_id)
                raise GatewayError("REQUEST_EXPIRED")
            return handle


def current_handle():
    return _current.get()


def check_cancelled():
    handle = current_handle()
    if handle:
        handle.check()


@contextmanager
def request_scope(handle):
    token = _current.set(handle)
    try:
        check_cancelled()
        yield
    finally:
        _current.reset(token)
