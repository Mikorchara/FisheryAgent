"""QQ-only bounded RAM. No credentials, raw messages, persistence or business reads."""
from collections import OrderedDict
from dataclasses import dataclass,asdict,replace,field
from datetime import datetime
import hashlib
import json
from threading import RLock
import time

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_conversation import (ChannelHistoryAuthority,ChannelHistorySnapshot,
    LIMITS,FOCUS,validate_options,question_for)
from apps.ai_service.runtime.assistant import AssistantHistoryTurn,_history_bytes


@dataclass(frozen=True)
class ConversationOptions:
    trigger_mode: str = 'command'
    memory_enabled: bool = False
    max_turns: int = 6
    idle_seconds: int = 900
    max_sessions: int = 64
    session_bytes: int = 24576
    total_bytes: int = 1048576
    projection_bytes: int = 4096
    def __post_init__(self):validate_options(asdict(self))
    @classmethod
    def from_dict(cls,value):
        if type(value) is not dict or value.get('schema_version')!=1 or type(value.get('schema_version')) is not int:
            raise GatewayError('INVALID_CONVERSATION_OPTIONS')
        options={k:v for k,v in value.items() if k!='schema_version'}
        validate_options(options);return cls(**options)


@dataclass(frozen=True,repr=False)
class ConversationKey:
    app_id: str
    group_id: str
    member_id: str
    instance_id: str
    device_id: str
    permission_revision: str
    binding_revision: str
    policy_revision: str
    scope_sha256: str
    epoch: str
    def __post_init__(self):
        if any(type(v) is not str or not v or len(v.encode('utf-8'))>512 for v in asdict(self).values()):
            raise GatewayError('INVALID_CONVERSATION_KEY')
    def replace(self,**changes):return replace(self,**changes)
    @property
    def identity(self):return tuple(asdict(self).values())


@dataclass(frozen=True,repr=False)
class _Turn:
    id: str
    focus: str
    text: str
    text_sha256: str
    accepted_at: str
    source_times: tuple
    source_flags: tuple
    @property
    def size(self):return len(json.dumps(asdict(self),ensure_ascii=False,separators=(',',':')).encode())
    def projection(self):
        summary=(f'已交付答复的主题投影：{FOCUS[self.focus]}；观测时间{self.source_times}；'
                 f'来源与有效性{self.source_flags}。这是旧对话，不是当前读数或新工具执行。')
        return AssistantHistoryTurn(question_for(self.focus),summary,self.accepted_at)


@dataclass
class _Session:
    revision: int
    expires: float
    turns: list = field(default_factory=list)
    active: int = 0
    @property
    def size(self):return sum(t.size for t in self.turns)


class ConversationStore:
    def __init__(self,options=ConversationOptions(),*,monotonic=time.monotonic):
        if type(options) is not ConversationOptions:raise GatewayError('INVALID_CONVERSATION_OPTIONS')
        self._options=options;self._now=monotonic;self._last=None;self._serial=0
        self._sessions=OrderedDict();self._issued={};self._lock=RLock();self._closed=False
        self.authority=ChannelHistoryAuthority(asdict(options),self._validate)

    @property
    def options(self):return self._options

    def _prune(self):
        now=self._now()
        if self._closed:raise GatewayError('CONVERSATION_STORE_CLOSED')
        if self._last is not None and now<self._last:raise GatewayError('CONVERSATION_CLOCK_ROLLBACK')
        self._last=now
        for k in tuple(self._sessions):
            if self._sessions[k].expires<=now:del self._sessions[k]
        return now

    def _evict_idle(self,exclude=None):
        for k,s in self._sessions.items():
            if k!=exclude and not s.active:
                del self._sessions[k];return True
        return False

    def _session(self,key):
        now=self._prune()
        if key not in self._sessions:
            if len(self._sessions)>=self.options.max_sessions and not self._evict_idle():
                raise GatewayError('CONVERSATION_CAPACITY')
            self._serial+=1
            self._sessions[key]=_Session(self._serial,now+self.options.idle_seconds)
        return self._sessions[key]

    def topic(self,key):
        with self._lock:
            self._prune();s=self._sessions.get(key)
            return s.turns[-1].focus if self.options.memory_enabled and s and s.turns else None

    def snapshot(self,key,*,focus):
        if type(key) is not ConversationKey or focus not in FOCUS:raise GatewayError('INVALID_CONVERSATION_KEY')
        with self._lock:
            if len(self._issued)>=8:raise GatewayError('CONVERSATION_SNAPSHOT_CAPACITY')
            s=self._session(key)
            pairs=[t.projection() for t in s.turns] if self.options.memory_enabled else []
            while pairs and _history_bytes(pairs)>self.options.projection_bytes:pairs.pop(0)
            snap=ChannelHistorySnapshot(self.authority,object(),key.identity,s.revision,focus,tuple(pairs),self.authority.options)
            self._issued[snap.ticket]=(snap,key);s.active+=1
            return snap

    def _validate(self,snapshot,expected_scope):
        with self._lock:
            self._prune();record=self._issued.get(snapshot.ticket)
            if record is None or record[0] is not snapshot:raise GatewayError('INVALID_CHANNEL_HISTORY')
            s=self._sessions.get(record[1])
            if s is None or s.revision!=snapshot.revision:raise GatewayError('CONVERSATION_REVISION_CHANGED')

    def release(self,snapshot):
        with self._lock:
            record=self._issued.pop(snapshot.ticket,None)
            if record:
                s=self._sessions.get(record[1])
                if s and s.revision==snapshot.revision:
                    s.active=max(0,s.active-1)
                    if not s.active and not s.turns:self._sessions.pop(record[1],None)

    def clear(self,key):
        with self._lock:self._sessions.pop(key,None)

    def abort_snapshot(self,snapshot):
        with self._lock:
            record=self._issued.get(snapshot.ticket)
            s=self._sessions.get(record[1]) if record else None
            if s and s.revision==snapshot.revision:self._sessions.pop(record[1],None)

    def invalidate(self):
        with self._lock:self._sessions.clear()

    def close(self):
        with self._lock:
            self._closed=True;self._sessions.clear();self._issued.clear()

    def commit(self,snapshot,*,turn_id,text,text_sha256,accepted_at,source_times,source_flags):
        with self._lock:
            self.authority.validate(snapshot,snapshot.scope_sha256)
            if (type(text) is not str or not 1<=len(text)<=1600
                    or hashlib.sha256(text.encode()).hexdigest()!=text_sha256
                    or type(turn_id) is not str or not 1<=len(turn_id)<=128
                    or type(source_times) is not tuple or len(source_times)>3
                    or any(type(t) is not str or len(t)>64 for t in source_times)
                    or type(source_flags) is not tuple or len(source_flags)>4
                    or any(type(t) is not str or len(t)>32 for t in source_flags)):
                raise GatewayError('INVALID_DELIVERED_HISTORY')
            try:
                stamp=datetime.fromisoformat(accepted_at.replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError()
            except (ValueError,TypeError,AttributeError):raise GatewayError('INVALID_DELIVERED_HISTORY') from None
            if not self.options.memory_enabled:return 'HISTORY_DISABLED'
            s=self._sessions[self._issued[snapshot.ticket][1]]
            if any(t.id==turn_id for t in s.turns):return 'HISTORY_ALREADY_COMMITTED'
            turn=_Turn(turn_id,snapshot.focus,text,text_sha256,accepted_at,source_times,source_flags)
            if turn.size>self.options.session_bytes or turn.size>self.options.total_bytes:
                raise GatewayError('CONVERSATION_CONTENT_BUDGET')
            proposed=s.turns+[turn]
            while len(proposed)>self.options.max_turns or sum(t.size for t in proposed)>self.options.session_bytes:proposed.pop(0)
            own=self._issued[snapshot.ticket][1]
            others=sum(v.size for k,v in self._sessions.items() if k!=own);victims=[]
            for k,v in self._sessions.items():
                if others+sum(t.size for t in proposed)<=self.options.total_bytes:break
                if k!=own and not v.active:victims.append(k);others-=v.size
            while others+sum(t.size for t in proposed)>self.options.total_bytes and len(proposed)>1:proposed.pop(0)
            if others+sum(t.size for t in proposed)>self.options.total_bytes:raise GatewayError('CONVERSATION_CONTENT_BUDGET')
            for k in victims:del self._sessions[k]
            s.turns=proposed
            s.expires=self._now()+self.options.idle_seconds;self._sessions.move_to_end(own)
            return 'HISTORY_COMMITTED'

    def counts(self):
        with self._lock:
            self._prune()
            return dict(sessions=len(self._sessions),turns=sum(len(s.turns) for s in self._sessions.values()),
                content_bytes=sum(s.size for s in self._sessions.values()),pending=len(self._issued))


def prepared_scope(options,preset_id='dashscope-qwen38-flash-r1'):
    """No instance, key or network. Definition-only candidate fingerprint."""
    from apps.ai_backend.tools import ToolDefinition,ToolRegistry
    from apps.ai_backend.tools.policy import ToolPolicy
    from apps.ai_service.business_tools.current_water_quality import WATER_DEFINITION
    from apps.ai_service.runtime.assistant import assistant_profile
    from apps.ai_service.channel_conversation import conversation_scope
    def no_data():raise GatewayError('CONVERSATION_PREFLIGHT_NO_DATA')
    registry=ToolRegistry((ToolDefinition(WATER_DEFINITION,no_data),))
    return conversation_scope(assistant_profile(preset_id),ToolPolicy('assistant',True,('get_current_water_quality',)),
        registry,asdict(options))
