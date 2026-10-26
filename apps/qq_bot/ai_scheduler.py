"""Bounded AI/passive delivery; default Fake, separate operator-approved trial composition."""
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import re
import threading
import time

from .ai_delivery import DeliveryOwner, OfflineQQGateway
from .contracts import BotError


TERMINAL=frozenset(('DELIVERED','DELIVERY_UNKNOWN','CANCELLED','FAILED','EXPIRED'))


@dataclass(repr=False)
class _Job:
    plan: object
    admitted_at: float
    queue_deadline: float
    state: str = 'ADMITTED'
    owner: str | None = None
    reason: str | None = None
    result: object = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    receipt: object = None


def _code(error):
    code=getattr(error,'code','AI_SERVICE_UNAVAILABLE')
    return code if isinstance(code,str) and re.fullmatch('[A-Z0-9_]{1,80}',code) else 'AI_SERVICE_UNAVAILABLE'


class QQAIJobScheduler:
    """One AI worker, one delivery worker, one watchdog, all joinable/non-daemon.

    At most three unfinished jobs total (including pending delivery), two queued
    AI jobs, one unfinished job per frozen authorized session. No per-job threads.
    Exact Fake or independently approved Trial transport only. Ordinary CLI stays disabled.
    """
    def __init__(self, coordinator, gateway, *, clock=None, monotonic=time.monotonic,receipt_sink=None):
        from .ai_trial_delivery import TrialQQTransport
        if type(gateway) not in (OfflineQQGateway,TrialQQTransport):raise BotError('OFFLINE_DELIVERY_REQUIRED')
        if type(gateway) is TrialQQTransport and gateway.trial is not coordinator.service._channel_trial:
            raise BotError('TRIAL_QQ_COMPOSITION_REQUIRED')
        self.coordinator,self.gateway=coordinator,gateway
        self.now=monotonic
        self.delivery=DeliveryOwner(coordinator,gateway,clock=clock,monotonic=monotonic,receipt_sink=receipt_sink)
        self._cv=threading.Condition(threading.RLock())
        self._jobs={};self._finished=OrderedDict();self._finished_resources={};self._acceptances=deque(maxlen=32)
        self._stopping=False
        self._resource_fault=None
        self._threads=tuple(threading.Thread(target=fn,name='qq-ai-'+name,daemon=False)
            for name,fn in (('worker',self._ai_loop),('delivery',self._delivery_loop),('watchdog',self._watch)))
        coordinator.claim_scheduler(self)
        try:
            for thread in self._threads:thread.start()
        except Exception:
            self.close();raise

    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def submit(self, raw, *, transport_app_id,mention=None):
        with self._cv:
            if self._stopping:raise BotError('AI_SCHEDULER_STOPPED')
            if self._resource_fault:raise BotError('AI_RESOURCE_QUARANTINED')
            if not self.gateway.connected:raise BotError('AI_GATEWAY_DISCONNECTED')
            plan=self.coordinator.prepare(raw,transport_app_id=transport_app_id,mention=mention)
            if (len(self._jobs)>=3 or sum(j.state=='QUEUED' for j in self._jobs.values())>=2):
                self.coordinator.discard(plan);raise BotError('BUSY')
            if any(j.plan.context.session_key==plan.context.session_key for j in self._jobs.values()):
                self.coordinator.discard(plan);raise BotError('AI_SESSION_BUSY')
            now=self.now()
            # Reserve the idle worker's first runnable slot immediately. Three
            # simultaneous arrivals must not lose a slot just because the worker
            # has not yet been scheduled by the OS; only the extra two are queued.
            ready=not any(j.owner=='ai' or j.state in ('ADMITTED','QUEUED') for j in self._jobs.values())
            job=_Job(plan,now,min(now+10,plan.context.deadline),state='ADMITTED' if ready else 'QUEUED')
            self._jobs[plan.id]=job;self._cv.notify_all()
            return plan.id

    def snapshot(self, task_id):
        with self._cv:
            if task_id in self._jobs:
                j=self._jobs[task_id]
                info=dict(task_id=task_id,state=j.state,code=j.reason,
                    api_accepted=False,client_display_confirmed=False)
                if j.plan.handle.resource_info() is not None:info['sdk_resources']=j.plan.handle.resource_info()
                return info
            if task_id not in self._finished:raise BotError('AI_TASK_NOT_FOUND')
            info=dict(self._finished[task_id])
            if task_id in self._finished_resources:
                info['sdk_resources']={**self._finished_resources[task_id].snapshot(),
                    'cancel_requested':info['sdk_resources']['cancel_requested']}
            return info

    def wait(self, task_id, timeout=3):
        deadline=time.monotonic()+timeout
        with self._cv:
            while task_id in self._jobs:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('AI_TASK_WAIT_TIMEOUT')
                self._cv.wait(remaining)
            return self.snapshot(task_id)

    def take_acceptances(self):
        """Bounded future history hook: API acceptance metadata, never chat memory."""
        with self._cv:
            values=tuple(self._acceptances);self._acceptances.clear();return values

    def cancel_conversation(self,key):
        with self._cv:
            ids=tuple(j.plan.id for j in self._jobs.values() if j.plan.prepared.channel_history is not None
                and j.plan.prepared.channel_history.identity==key.identity)
        for task_id in ids:self.cancel(task_id)

    def _finish(self, job, state, code):
        # Caller owns the condition. Execution/delivery must already have returned.
        task_id=job.plan.id
        receipt=job.receipt
        info=dict(task_id=task_id,state=state,code=code,
            api_accepted=bool(receipt and receipt.api_accepted),client_display_confirmed=False)
        if receipt and receipt.explanation_code is not None:
            info.update(explanation_code=receipt.explanation_code,
                        explanation_in_payload=receipt.explanation_in_payload)
        if receipt and receipt.report_error is not None:info['report_error']=receipt.report_error
        if receipt and receipt.history_code is not None:info['history_code']=receipt.history_code
        if job.plan.handle.resource_info() is not None:
            info['sdk_resources']=job.plan.handle.resource_info()
            self._finished_resources[task_id]=job.plan.handle._sdk_resource
        self._finished[task_id]=info
        while len(self._finished)>32:
            expired,_=self._finished.popitem(last=False)
            self._finished_resources.pop(expired,None)
        if receipt and receipt.api_accepted:
            self._acceptances.append(dict(task_id=task_id,accepted_at=receipt.accepted_at,
                text_sha256=receipt.text_sha256,client_display_confirmed=False))
        self._jobs.pop(task_id,None)
        self.coordinator.discard(job.plan)
        job.result=None;self._cv.notify_all()

    def _settle_cancel(self, job):
        self._finish(job,'EXPIRED' if job.reason in ('AI_QUEUE_TIMEOUT','AI_TOTAL_TIMEOUT','AI_REPLY_EXPIRED')
                     else 'CANCELLED',job.reason or 'AI_CANCELLED')

    def cancel(self, task_id, *, reason='AI_CANCELLED'):
        if reason not in ('AI_CANCELLED','AI_QUEUE_TIMEOUT','AI_TOTAL_TIMEOUT','AI_REPLY_EXPIRED',
                          'AI_AUTH_CHANGED','AI_GATEWAY_DISCONNECTED','AI_SHUTDOWN','AI_RESOURCE_UNSAFE'):
            raise BotError('INVALID_AI_CANCEL_REASON')
        with self._cv:
            job=self._jobs.get(task_id)
            if job is None:return False
            if job.cancelled.is_set():return True
            if job.reason is None:job.reason=reason
            job.cancelled.set()
            owned=job.owner is not None
            if not owned:self._settle_cancel(job)
            else:job.state='CANCEL_REQUESTED'
            self._cv.notify_all()
        # Abort owned Provider I/O, not merely Future.cancel(). Never hold the job
        # lock while invoking an I/O hook that may be executing on another thread.
        if owned:
            # The worker may already have finalized/discarded its plan by now.
            # Handle ownership remains valid independently of the task map.
            job.plan.handle.cancel();job.plan.handle.abort_io()
        return True

    def cancel_all(self, *, reason='AI_CANCELLED'):
        with self._cv:ids=tuple(self._jobs)
        for task_id in ids:self.cancel(task_id,reason=reason)

    def _pick(self, state, owner):
        with self._cv:
            while True:
                if self._stopping:return None
                for job in self._jobs.values():
                    if job.state==state or (owner=='ai' and job.state=='ADMITTED'):
                        job.state='RUNNING' if owner=='ai' else 'DELIVERING'
                        job.owner=owner;return job
                self._cv.wait(.05)

    def _ai_loop(self):
        while (job:=self._pick('QUEUED','ai')) is not None:
            result=None;error=None
            try:
                if self.now()>=job.queue_deadline:raise BotError('AI_QUEUE_TIMEOUT')
                result=self.coordinator.execute(job.plan)
            except Exception as failure:error=_code(failure)
            with self._cv:
                job.owner=None
                resource_error=job.plan.handle.resource_error()
                if error in ('SDK_CLEANUP_TIMEOUT','SDK_CLEANUP_FAILED','SDK_RESOURCE_QUARANTINED',
                             'SDK_RESOURCE_UNCONFIRMED'):
                    resource_error=resource_error or error
                if resource_error:
                    self._resource_fault=resource_error
                    self._finish(job,'FAILED',resource_error)
                elif job.cancelled.is_set():self._settle_cancel(job)
                elif error in ('CHANNEL_AUTHORIZATION_CHANGED','AI_NOT_AUTHORIZED','AI_DISABLED',
                               'AI_DEVICE_NOT_AUTHORIZED'):
                    self._finish(job,'CANCELLED','AI_AUTH_CHANGED')
                elif error:
                    self._finish(job,'EXPIRED' if error in ('AI_QUEUE_TIMEOUT','TOTAL_TIMEOUT') else 'FAILED',error)
                elif not result.completed:
                    self._finish(job,'EXPIRED' if result.error_code=='TOTAL_TIMEOUT' else 'FAILED',
                                 result.error_code or 'AI_BACKEND_FAILED')
                elif self.now()>=job.plan.context.deadline:self._finish(job,'EXPIRED','AI_TOTAL_TIMEOUT')
                else:
                    job.state='COMPLETED';job.result=result
                    job.state='DELIVERY_PENDING';self._cv.notify_all()
            if self._resource_fault:self.cancel_all(reason='AI_RESOURCE_UNSAFE')

    def _delivery_loop(self):
        while (job:=self._pick('DELIVERY_PENDING','delivery')) is not None:
            receipt=None;error=None
            try:receipt=self.delivery.deliver(job.plan,job.result,job.cancelled)
            except Exception as failure:error=_code(failure)
            with self._cv:
                job.owner=None;job.receipt=receipt
                if receipt and receipt.status in ('DELIVERED','DELIVERY_UNKNOWN'):
                    self._finish(job,receipt.status,receipt.code)
                elif job.cancelled.is_set():self._settle_cancel(job)
                else:
                    code=error or (receipt.code if receipt else 'AI_DELIVERY_FAILED')
                    state=('EXPIRED' if code in ('AI_TOTAL_TIMEOUT','AI_REPLY_EXPIRED') else
                        'CANCELLED' if code in ('CHANNEL_AUTHORIZATION_CHANGED','AI_GATEWAY_DISCONNECTED',
                            'AI_NOT_AUTHORIZED','AI_DISABLED','AI_DEVICE_NOT_AUTHORIZED') else 'FAILED')
                    self._finish(job,state,code)

    def _watch(self):
        while True:
            with self._cv:
                if self._stopping:return
                jobs=tuple(self._jobs.values())
            for job in jobs:
                reason=None
                if self.now()>=job.plan.context.deadline:reason='AI_TOTAL_TIMEOUT'
                elif job.state in ('ADMITTED','QUEUED') and self.now()>=job.queue_deadline:reason='AI_QUEUE_TIMEOUT'
                elif not self.gateway.connected:reason='AI_GATEWAY_DISCONNECTED'
                else:
                    try:self.coordinator.validate_plan(job.plan)
                    except Exception:reason='AI_AUTH_CHANGED'
                if reason:self.cancel(job.plan.id,reason=reason)
            with self._cv:
                if not self._stopping:self._cv.wait(.02)

    def close(self, timeout=3):
        with self._cv:
            self._stopping=True;ids=tuple(self._jobs);self._cv.notify_all()
        for task_id in ids:self.cancel(task_id,reason='AI_SHUTDOWN')
        self.gateway.close()
        deadline=time.monotonic()+timeout
        for thread in self._threads:
            if thread.ident is not None:thread.join(max(0,deadline-time.monotonic()))
        if any(t.is_alive() for t in self._threads):raise BotError('AI_SHUTDOWN_INCOMPLETE')
        if self._resource_fault:raise BotError('AI_SDK_RESOURCE_UNSAFE')
        self.coordinator.release_scheduler(self)
