"""QQ run validation snapshots: lexical, synchronous, thread-owned, never TTL.

Only validation-only entry points open these scopes. They must end before quota
reservation, business Tool I/O, SDK I/O, QQ HTTP or history commit. Dynamic guards
(ownership, expiry, SDK quarantine, object identity) run even on repeated checks.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
import threading

CONTRACT = 'qq-lexical-validation-snapshot@1'
_ACTIVE = ContextVar('qq_validation_snapshot', default=None)


class _Snapshot:
    def __init__(self, owner):
        self.owner = owner
        self.thread = threading.get_ident()
        self.values = {}
        self.open = True


class ValidationBoundary:
    @contextmanager
    def scope(self):
        current = _ACTIVE.get()
        if (type(current) is _Snapshot and current.open and current.owner is self
                and current.thread == threading.get_ident()):
            yield
            return
        snapshot = _Snapshot(self)
        token = _ACTIVE.set(snapshot)
        try:
            yield
        finally:
            snapshot.open = False
            snapshot.values.clear()
            _ACTIVE.reset(token)


def validation_once(key, operation):
    snapshot = _ACTIVE.get()
    if (type(snapshot) is not _Snapshot or not snapshot.open
            or snapshot.thread != threading.get_ident()):
        return operation()
    if key not in snapshot.values:
        # Failures are never cached; the owning Run retains its fail-closed state.
        snapshot.values[key] = operation()
    return snapshot.values[key]


def implementation_sha256(path):
    key = ('implementation-bytes', os.path.abspath(path))
    return validation_once(key, lambda: hashlib.sha256(path.read_bytes()).hexdigest())


def validation_active():
    """Offline tests assert snapshots never span external execution boundaries."""
    snapshot = _ACTIVE.get()
    return bool(type(snapshot) is _Snapshot and snapshot.open
                and snapshot.thread == threading.get_ident())
