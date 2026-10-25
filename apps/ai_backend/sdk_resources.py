"""Explicit SDK leases and a sticky process-local quarantine; never a thread killer.

Cancellation is not cleanup. A failed lease remains visible even if its worker
eventually exits, and the shared budget refuses new SDK work until restart.
"""
import threading


RESOURCE_CONTRACT='sdk-resource-quarantine@1'
CLEANUP_GRACE_S=2.0


class SDKResourceLease:
    def __init__(self,budget):
        self.budget=budget
        self._lock=threading.RLock()
        self.thread=None
        self.started=False
        self.io_closed=True  # No SDK client created yet.
        self.task_done=False
        self.task_created=False
        self.abort_requested=False
        self.failure=None
        self.settled=False

    def attach(self,thread):
        with self._lock:self.thread=thread

    def launched(self):
        with self._lock:self.started=True

    def opening(self):
        with self._lock:self.io_closed=False

    def closed(self):
        with self._lock:self.io_closed=True

    def abort(self):
        with self._lock:self.abort_requested=True

    def task_finished(self):
        with self._lock:self.task_done=True

    def task_started(self):
        with self._lock:self.task_created=True

    def fail(self,code):
        with self._lock:
            if self.failure is None:self.failure=code
        self.budget.quarantine(self)

    def snapshot(self):
        with self._lock:
            alive=bool(self.thread and self.thread.is_alive())
            exited=not alive and (self.started or self.settled)
            return dict(contract=RESOURCE_CONTRACT,
                state='CLEANUP_FAILED' if self.failure else 'CLOSED' if self.settled else 'RUNNING',
                cancel_signal_sent=self.abort_requested,local_io_closed=self.io_closed,
                task_done=self.task_done if self.task_created else None,
                thread_started=self.started,thread_exited=exited,
                cleanup_error=self.failure,quarantined=self.failure is not None,
                remote_compute_stopped='unknown')

    def settle(self):
        with self._lock:
            if self.thread and self.thread.is_alive():code='SDK_CLEANUP_TIMEOUT'
            elif not self.io_closed or self.task_created and not self.task_done:code='SDK_CLEANUP_FAILED'
            else:code=None
            if code and self.failure is None:self.failure=code
            self.settled=True
            failure=self.failure
        if failure:self.budget.quarantine(self)
        self.budget.release(self)
        return failure


class SDKResourceBudget:
    """Bounded active SDK workers; any uncertain cleanup blows a sticky fuse.

    The optional explicit instance used by tests is never read from user JSON.
    There is deliberately no reset/ignore-error operation in the running process.
    """
    def __init__(self,limit=8):
        if type(limit) is not int or not 1<=limit<=8:raise ValueError('INVALID_SDK_RESOURCE_LIMIT')
        self.limit=limit
        self._lock=threading.Lock()
        self._active=set();self._failed=set()

    def reserve(self):
        from .model_gateway import GatewayError
        with self._lock:
            self._failed.update(lease for lease in self._active if lease.failure)
            if self._failed:raise GatewayError('SDK_RESOURCE_QUARANTINED')
            if len(self._active)>=self.limit:raise GatewayError('SDK_RESOURCE_LIMIT')
            lease=SDKResourceLease(self);self._active.add(lease);return lease

    def assert_healthy(self):
        from .model_gateway import GatewayError
        with self._lock:
            self._failed.update(lease for lease in self._active if lease.failure)
            if self._failed:raise GatewayError('SDK_RESOURCE_QUARANTINED')

    def quarantine(self,lease):
        with self._lock:self._failed.add(lease)

    def release(self,lease):
        with self._lock:self._active.discard(lease)

    def snapshot(self):
        with self._lock:
            return dict(active=len(self._active),quarantined=len(self._failed),limit=self.limit)


SDK_RESOURCES=SDKResourceBudget()
