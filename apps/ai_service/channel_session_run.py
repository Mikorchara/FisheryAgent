"""BOT-3E-B: typed Fake-only run leases; no real-model qualification."""
from dataclasses import dataclass, field, asdict
from datetime import datetime
import hashlib
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode
from .channel import ChannelBudget
from .channel_conversation import INSTRUCTION, PROMPT_ID, validate_options
from .channel_conversation_trial import trial_scope as previous_scope
from .channel_trial import QwenTrialSession, PRESET, cost_reservation
from .execution import ExecutionDecision
from .runtime.assistant import assistant_profile
from .runtime.release_contracts import _hash, AssistantExecutionProfile

CONTRACT='qq-qwen-bounded-session-trial@1'


@dataclass(frozen=True,repr=False)
class TurnLease:
    authority: object
    ticket: object
    approval_id: str
    sequence: int
    scope_sha256: str
    bindings_sha256: str
    expires_at: datetime
    instance_id: str
    device_id: str
    app_id: str
    group_id: str
    member_id: str
    message_key: str
    phase: str = field(default='qq',init=False)


class LeaseAuthority:
    """Identity registry, not a serializable approval or a caller-supplied boolean."""
    def __init__(self,check):self._check=check;self._issued={}
    def _issue(self,**fields):
        lease=TurnLease(self,object(),**fields);self._issued[lease.ticket]=lease;return lease
    def validate(self,lease):
        if type(lease) is not TurnLease or lease.authority is not self or self._issued.get(lease.ticket) is not lease:
            raise GatewayError('INVALID_RUN_TURN_LEASE')
        self._check(lease)


def memory_sdk_factory(factory):
    """Strict memory HTTP with an owned close path, also for typed live-path tests."""
    def create(runtime,remaining):
        client=factory(runtime,remaining)
        class OwnedClient:
            @property
            def chat(owner):
                if (type(client) is not AsyncOpenAI or type(client._client._transport) is not httpx.MockTransport
                        or client.max_retries!=0 or client._client.trust_env or client._client.follow_redirects):
                    raise GatewayError('SESSION_RUN_MEMORY_HTTP_REQUIRED')
                return client.chat
            async def close(owner):await client.close()
            def is_closed(owner):return client.is_closed()
        return OwnedClient()
    return create


def session_scope(profile,policy,registry,options):
    from .channel_validation import implementation_sha256
    base=previous_scope(profile,policy,registry,asdict(options))
    root=Path(__file__).parents[1]
    paths=('ai_service/channel_session_run.py','qq_bot/run_consent.py','qq_bot/session_run.py',
        'qq_bot/session_run_cli.py','ai_service/channel_trial.py','ai_service/service.py',
        'qq_bot/ai_coordinator.py','qq_bot/ai_scheduler.py','qq_bot/ai_delivery.py','qq_bot/ai_routing.py')
    return dict(contract=CONTRACT,environment='OFFLINE_FAKE_ONLY',runtime=base['runtime'],
        sdk=base['sdk'],transport=base['transport'],presentation=base['presentation'],
        conversation=validate_options(asdict(options)),cost={**base['cost'],
            'reservation_per_turn_cny':str(cost_reservation()),'refund':False,'budget_type':'DECIMAL_CNY'},
        process={'max_seconds':1800,'max_turns':5,'max_members':4,'ai_workers':1,'waiting':2,
            'approval':'ONE_PROCESS_NONCE_OWNER@1','resume':False,'ledger':'FSYNC_RESERVE_BEFORE_IO@1'},
        execution=base['execution'],history=base['history'],commit=base['commit'],
        implementation={**base['implementation'],**{p:implementation_sha256(root/p) for p in paths}})


def prepared_scope(options):
    from apps.ai_backend.tools import ToolDefinition,ToolRegistry
    from apps.ai_backend.tools.policy import ToolPolicy
    from .business_tools.current_water_quality import WATER_DEFINITION
    return session_scope(assistant_profile(PRESET),ToolPolicy('assistant',True,('get_current_water_quality',)),
        ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),)),options)


def candidate_record(scope):
    return dict(schema_version=1,status='candidate',environment='OFFLINE_FAKE_ONLY',
        contract=CONTRACT,scope=scope,scope_sha256=_hash(scope),qualification_id=None,
        can_execute_real=False,can_deliver_real=False)


class SessionQwenTurn(QwenTrialSession):
    """Original SDK guards and Agent, with a distinct server-issued Run lease.

    Constructor requires memory HTTP. Neither the ordinary CLI nor existing real
    transports accept this type. BOT-3E-C must separately review real assembly.
    """
    release_status='candidate'

    def __init__(self,lease,*,authority,conversation_epoch,options,snapshot,validate,claim,
                 async_client_factory=None,clock=None,monotonic=None):
        if type(lease) is not TurnLease or async_client_factory is None:
            raise GatewayError('SESSION_RUN_OFFLINE_ONLY')
        lease.authority.validate(lease)
        self.authority,self.conversation_epoch=authority,conversation_epoch
        self.options,self.snapshot=options,snapshot
        kwargs={} if monotonic is None else {'monotonic':monotonic}
        self._initialize(lease,validate=validate,claim=claim,async_client_factory=memory_sdk_factory(async_client_factory),clock=clock,**kwargs)

    def decision(self,*args,**kwargs):raise GatewayError('SESSION_RUN_HISTORY_REQUIRED')

    def history_decision(self,profile,policy,registry,authorization,snapshot,*,epoch,policy_revision):
        self.check();self.approval.authority.validate(self.approval)
        digest=_hash(session_scope(profile,policy,registry,self.options))
        return self._bound_history_decision(profile,policy,registry,authorization,snapshot,
            epoch=epoch,policy_revision=policy_revision,digest=digest,reason='OFFLINE_BOUNDED_RUN_LEASE')

    def _bound_history_decision(self,profile,policy,registry,authorization,snapshot,*,epoch,policy_revision,digest,reason):
        if digest!=self.approval.scope_sha256:raise GatewayError('SESSION_RUN_BINDING_CHANGED')
        snapshot.authority.validate(snapshot,digest)
        expected=(authorization.instance_id,authorization.device_id,authorization.permission_revision,
            authorization.binding_revision,policy_revision)
        if (profile!=assistant_profile(PRESET) or authorization.budget!=ChannelBudget()
                or registry.registered_names()!=('get_current_water_quality',)
                or policy.exposed_tools!=('get_current_water_quality',)
                or snapshot is not self.snapshot or snapshot.authority is not self.authority
                or snapshot.identity[3:8]!=expected or snapshot.identity[9]!=self.conversation_epoch
                or digest!=self.approval.scope_sha256):
            raise GatewayError('SESSION_RUN_BINDING_CHANGED')
        revision=_hash([self.approval.approval_id,digest,self.approval.bindings_sha256,epoch,
            snapshot.identity,snapshot.revision,snapshot.focus,[asdict(t) for t in snapshot.history]])
        return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.SINGLE_ROUND,revision,
            self.release_status,reason),True,max_output_tokens=512)

