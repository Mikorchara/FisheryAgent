"""Shared bounded read-only ingress; live network ownership stays in Transport."""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Lock

from .contracts import BotConfig, BotError, decode, utc
from .service import plain


@dataclass(frozen=True)
class GroupReply:
    group_id: str
    msg_id: str
    content: str = field(repr=False)
    msg_seq: int = 1
    msg_type: int = 0


@dataclass(frozen=True)
class Outcome:
    code: str
    reply: GroupReply | None = None
    mode: str = 'OFFLINE_NOT_SENT'


class QQAdapter:
    """Transport supplies AppID; only the authenticated live Gateway may use live mode.

    Sessions retain counters, not chat history. Dedup is process-local and never
    evicts a live entry to admit another. The live Gateway owns authentication;
    this prototype does not promise durable or exactly-once delivery.
    """
    def __init__(self, config: BotConfig, queries, *, clock=None, mode="OFFLINE_NOT_SENT"):
        if not isinstance(config, BotConfig):
            raise BotError('INVALID_ACCESS_CONFIG')
        if mode not in ('OFFLINE_NOT_SENT', 'QQ_PASSIVE_READY'):
            raise BotError('INVALID_ADAPTER_MODE')
        self.mode = mode
        self.config, self._queries = config, queries
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._seen, self._sessions, self._groups = {}, {}, {}
        self._last_now = None

    def receive(self, raw: bytes, *, transport_app_id: str):
        return self._ingress(raw,transport_app_id)

    def admit_offline(self, raw: bytes, *, transport_app_id: str, operation):
        """Server-only preparation hook. Never enable AI through the live receiver."""
        if self.mode != 'OFFLINE_NOT_SENT':
            raise BotError('AI_LIVE_DISABLED')
        return self._ingress(raw,transport_app_id,operation)

    def _ingress(self, raw, transport_app_id, operation=None):
        # No worker/queue: reject concurrent ingress rather than wait unboundedly.
        if not self._lock.acquire(blocking=False):
            return self._outcome('BUSY')
        try:
            return self._receive(raw, transport_app_id, operation)
        except BotError as error:
            return self._outcome(error.code)
        except Exception:
            return self._outcome('READ_FAILED')  # Never serialize exception text.
        finally:
            self._lock.release()

    def _receive(self, raw, app_id, operation=None):
        if app_id != self.config.app_id:
            return self._outcome('APP_DENIED')
        now = utc(self._clock())
        # A time rollback must not resurrect expired requests/rate windows.
        if self._last_now is not None and now < self._last_now:
            return self._outcome('CLOCK_ROLLBACK')
        self._last_now = now
        message = decode(raw)
        access = next((g for g in self.config.groups if g.group_id == message.group_id), None)
        if access is None:
            return self._outcome('GROUP_DENIED')
        if message.member_id not in access.members:
            return self._outcome('MEMBER_DENIED')
        age = (now - message.timestamp).total_seconds()
        if age < -30 or age >= 300:
            return self._outcome('MESSAGE_EXPIRED')
        key = (app_id, message.group_id, message.message_id)
        fingerprint = hashlib.sha256(json.dumps([message.member_id, message.timestamp.isoformat(),
            message.content], ensure_ascii=True).encode()).hexdigest()
        self._seen = {k: v for k, v in self._seen.items() if v[1] > now}
        self._sessions = {k: v for k, v in self._sessions.items() if v['last'] + timedelta(seconds=900) > now}
        for bucket in self._groups.values():
            while bucket and bucket[0] + timedelta(seconds=60) <= now:
                bucket.popleft()
        if key in self._seen:
            return self._outcome('DUPLICATE' if self._seen[key][0] == fingerprint else 'MESSAGE_ID_CONFLICT')
        session_key = (app_id, message.group_id, message.member_id, access.device_id)
        if len(self._seen) >= self.config.dedup_limit:
            return self._outcome('DEDUP_CAPACITY')
        if session_key not in self._sessions and len(self._sessions) >= self.config.session_limit:
            return self._outcome('SESSION_CAPACITY')
        session = self._sessions.setdefault(session_key, dict(last=now, count=0, rate=deque()))
        while session['rate'] and session['rate'][0] + timedelta(seconds=60) <= now:
            session['rate'].popleft()
        group_rate = self._groups.setdefault(message.group_id, deque())
        if (len(session['rate']) >= self.config.member_per_minute
                or len(group_rate) >= self.config.group_per_minute):
            return self._outcome('RATE_LIMITED')
        # Claim before query; failures/replays cannot execute it again.
        self._seen[key] = (fingerprint, message.timestamp + timedelta(seconds=300))
        session['last'] = now
        session['rate'].append(now)
        group_rate.append(now)
        if operation is not None:
            return operation(message,access)
        code, text = self._queries.execute(message, access)
        # A delayed read cannot produce an already-expired passive reply.
        finished = utc(self._clock())
        if finished < now or (finished - message.timestamp).total_seconds() >= 300:
            return self._outcome('REPLY_EXPIRED')
        prefix = '【BOT-1A OFFLINE · 离线输出，未发送 QQ】' if self.mode == 'OFFLINE_NOT_SENT' else '【BOT-1B 只读实验】'
        text = prefix + '\n' + plain(text, 1600)
        if code == 'OK':
            session['count'] += 1
        return self._outcome(code, GroupReply(message.group_id, message.message_id, text))

    def _outcome(self, code, reply=None):
        return Outcome(code, reply, self.mode)

    def session_count(self, group_id, member_id):
        """Local diagnostics: counts only, never message bodies or cross-user history."""
        with self._lock:
            return sum(v['count'] for k, v in self._sessions.items() if k[1:3] == (group_id, member_id))


class OfflineQQAdapter(QQAdapter):
    """Compatibility entry for BOT-1A; output remains offline and cannot be sent."""
    def __init__(self, config, queries, *, clock=None):
        super().__init__(config, queries, clock=clock)
