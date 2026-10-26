"""Single passive-reply ownership for exact offline or independently approved trial transports."""
from collections import deque
from dataclasses import dataclass,replace
from datetime import datetime, timezone
import hashlib
import json
import threading
import time

import httpx

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_presentation import render_channel_reply

from .contracts import BotError
from .adapter import GroupReply
from .service import plain
from .transport import QQAPI


@dataclass(frozen=True)
class DeliveryReceipt:
    status: str
    code: str
    api_accepted: bool = False
    client_display_confirmed: bool = False
    accepted_at: str | None = None
    text_sha256: str | None = None
    explanation_code: str | None = None
    explanation_in_payload: bool = False
    report_error: str | None = None


class OfflineQQGateway:
    """Exact fake type: QQAPI serializes into MockTransport, with no socket path.

    Events provide cooperative fake HTTP blocking/cancellation for tests. Outcomes
    are finite scripted values, not user messages, URLs or credential hooks.
    """
    def __init__(self, outcomes=('ACCEPTED',), *, wait_gate=None, wait_started=None):
        if (not outcomes or any(v not in ('ACCEPTED','FAILED','UNKNOWN','UNCONFIRMED') for v in outcomes)
                or any(v is not None and not isinstance(v,threading.Event) for v in (wait_gate,wait_started))):
            raise ValueError('INVALID_OFFLINE_DELIVERY_SCRIPT')
        self._outcomes=deque(outcomes)
        self._gate,self._started=wait_gate,wait_started
        self._connected=threading.Event();self._connected.set()
        self._closed=threading.Event()
        self.posts=deque(maxlen=128)  # Synthetic messages only; never logged or represented.

    def __repr__(self):return 'OfflineQQGateway(<in-memory>)'

    @property
    def connected(self):return self._connected.is_set() and not self._closed.is_set()

    def disconnect(self):self._connected.clear()
    def reconnect(self):
        if not self._closed.is_set():self._connected.set()
    def close(self):self._closed.set()

    def send(self, context, reply, *, clock, cancelled, before_post):
        if not self.connected:raise BotError('AI_GATEWAY_DISCONNECTED')
        def handle(request):
            before_post()  # Immediately before simulated submission, not only on admission.
            self.posts.append(json.loads(request.content))
            if self._started:self._started.set()
            while self._gate is not None and not self._gate.wait(.01):
                if cancelled.is_set() or not self.connected:
                    raise httpx.ReadTimeout('offline cancellation',request=request)
            if cancelled.is_set() or not self.connected:
                raise httpx.ReadTimeout('offline cancellation',request=request)
            outcome=self._outcomes.popleft() if self._outcomes else 'FAILED'
            if outcome=='UNKNOWN':raise httpx.ReadTimeout('offline unknown',request=request)
            if outcome=='FAILED':return httpx.Response(503,json={'code':1})
            return httpx.Response(200,json={'id':'offline-accepted'} if outcome=='ACCEPTED' else {})
        with httpx.Client(transport=httpx.MockTransport(handle),trust_env=False,
                          follow_redirects=False) as client:
            api=QQAPI(context.app_id,None,client=client)
            # Virtual token is local to MockTransport; no secret provider is consulted.
            api._token='offline-only';api._expires=time.monotonic()+3600
            try:return api.reply(reply,received_at=context.timestamp,now=clock())
            finally:api.close()


class PassiveReplyOwner:
    """One message claim shared by fixed replies, AI outcomes and safe errors.

    Ownership is not authorization. Only exact Fake/phase-approved Trial transports
    may be composed; each path still validates immediately before submission.
    """
    def __init__(self,gateway,*,clock=None):
        from .ai_trial_delivery import TrialQQTransport
        if type(gateway) not in (OfflineQQGateway,TrialQQTransport):raise BotError('OFFLINE_DELIVERY_REQUIRED')
        self.gateway=gateway
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self._claims={};self._lock=threading.Lock()

    def send(self,context,text,cancelled,validate):
        validate()
        text=plain(text,max(1,len(text)))
        if not 1<=len(text)<=1800:raise BotError('AI_REPLY_TOO_LONG')
        with self._lock:
            now=self.clock()
            self._claims={k:v for k,v in self._claims.items() if (now-v).total_seconds()<300}
            if context.delivery_key in self._claims:raise BotError('AI_DELIVERY_ALREADY_CLAIMED')
            if len(self._claims)>=128:raise BotError('AI_DELIVERY_CAPACITY')
            self._claims[context.delivery_key]=context.timestamp
        reply=GroupReply(context.group_id,context.message_id,text)
        try:
            self.gateway.send(context,reply,clock=self.clock,cancelled=cancelled,before_post=validate)
        except BotError as error:
            unknown=error.code in ('QQ_DELIVERY_UNKNOWN','QQ_SEND_NOT_CONFIRMED','QQ_HTTP_UNAVAILABLE',
                                   'QQ_RESPONSE_TOO_LARGE','INVALID_PACKET','PACKET_SIZE_LIMIT')
            return DeliveryReceipt('DELIVERY_UNKNOWN' if unknown else 'FAILED',error.code)
        return DeliveryReceipt('DELIVERED','QQ_REPLY_API_ACCEPTED',True,False,
            self.clock().isoformat(),hashlib.sha256(text.encode('utf-8')).hexdigest())


class DeliveryOwner:
    """Revalidation + full safe text + at-most-one submission per original message.

    Candidate can_deliver stays false. A separate phase-approved Trial transport
    does not promote candidates or remove authorization/source/resource checks.
    """
    def __init__(self, coordinator, gateway, *, clock=None, monotonic=time.monotonic,receipt_sink=None):
        from .ai_trial_delivery import TrialQQTransport
        if type(gateway) not in (OfflineQQGateway,TrialQQTransport):raise BotError('OFFLINE_DELIVERY_REQUIRED')
        if type(gateway) is TrialQQTransport and gateway.trial is not coordinator.service._channel_trial:
            raise BotError('TRIAL_QQ_COMPOSITION_REQUIRED')
        self.coordinator,self.gateway=coordinator,gateway
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.now=monotonic
        if receipt_sink is not None and not callable(receipt_sink):raise BotError('INVALID_DELIVERY_RECEIPT_SINK')
        self.receipt_sink=receipt_sink
        self.passive=PassiveReplyOwner(gateway,clock=self.clock)

    def deliver(self, plan, result, cancelled):
        def validate():
            if cancelled.is_set():raise BotError('AI_CANCELLED')
            if self.now()>=plan.context.deadline:raise BotError('AI_TOTAL_TIMEOUT')
            age=(self.clock()-plan.context.timestamp).total_seconds()
            if not 0<=age<285:raise BotError('AI_REPLY_EXPIRED')
            if not self.gateway.connected:raise BotError('AI_GATEWAY_DISCONNECTED')
            try:self.coordinator.validate_delivery_candidate(plan,result)
            except GatewayError as error:raise BotError(error.code) from None
        validate()
        from .ai_trial_delivery import TrialQQTransport
        live_trial=type(self.gateway) is TrialQQTransport and not self.gateway.trial.offline_test
        prefix='受控 Qwen 单轮实验 · SIMULATOR\n' if live_trial else '离线验收 · 非真实 QQ 交付\n'
        rendered,assessment=render_channel_reply(result,max_chars=1600-len(prefix))
        text=prefix+rendered
        # Sanitize mentions/control characters without silently truncating facts.
        text=plain(text,max(1,len(text)))
        if not 1<=len(text)<=1600:raise BotError('AI_REPLY_TOO_LONG')
        self.coordinator.claim_delivery(plan,result)
        receipt=self.passive.send(plan.context,text,cancelled,validate)
        receipt=replace(receipt,explanation_code=assessment.code,explanation_in_payload=assessment.allowed)
        if self.receipt_sink is not None:
            try:self.receipt_sink(receipt)
            except Exception:
                # Persistence cannot undo a submitted/accepted reply. Preserve
                # its actual delivery state; never resend to repair a report.
                receipt=replace(receipt,report_error='TRIAL_DELIVERY_CHECKPOINT_FAILED')
        return receipt
