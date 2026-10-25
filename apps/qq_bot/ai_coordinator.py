"""Channel admission/execution; Fake by default, real trials require an independent approval."""
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from threading import RLock
import time
import uuid

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel import ChannelAuthorization
from apps.ai_service.runtime.release_contracts import _hash
from .adapter import QQAdapter
from .ai_configuration import QQAIConfig
from .contracts import BotError


@dataclass(frozen=True)
class QQAIPlan:
    id: str
    prepared: object = field(repr=False)
    handle: object = field(repr=False)
    context: object = field(repr=False)


@dataclass(frozen=True,repr=False)
class QQAIMessageContext:
    app_id: str
    group_id: str
    member_id: str
    message_id: str
    timestamp: datetime
    deadline: float
    session_key: str

    @property
    def delivery_key(self):
        return _hash([self.app_id,self.group_id,self.message_id])


class QQAICoordinator:
    """Reuse the existing ingress and Service; never creates a second Agent loop.

    Constructor dependencies are explicit. It does not load instances, policies,
    secrets or providers. Service accepts the exact Fake Provider or a separately
    approved QwenTrialSession; ordinary QQ composition still has no AI Service.
    """
    def __init__(self,access,monitoring,service,*,config=QQAIConfig(),clock=None,monotonic=time.monotonic):
        if service.monitoring is not monitoring or type(config) is not QQAIConfig:
            raise BotError('INVALID_QQ_AI_COMPOSITION')
        self.access,self.monitoring,self.service,self.config=access,monitoring,service,config
        self._ingress=QQAdapter(access,None,clock=clock)
        self._clock=clock or (lambda:datetime.now(timezone.utc))
        self._now=monotonic
        self._generation=0
        self._tasks={}
        self._scheduler=None
        self._lock=RLock()
        self._requests=service.request_registry(limit=8)

    @property
    def revision(self):
        return _hash([self.config.revision,asdict(self.access),self._generation])

    def reconfigure(self,config,*,access=None):
        if type(config) is not QQAIConfig:
            raise BotError('INVALID_QQ_AI_CONFIG')
        with self._lock:
            self.config=config
            if access is not None:
                self.access=access;self._ingress.config=access
            self._generation+=1
            handles=[task['plan'].handle for task in self._tasks.values()]
        for handle in handles:
            handle.abort_io();handle.cancel()

    def _permission(self,message):
        if not self.config.enabled:
            raise BotError('AI_DISABLED')
        trial=self.service._channel_trial
        if trial is not None:
            try:trial.check_message(message)
            except GatewayError as error:raise BotError(error.code) from None
        group=next((g for g in self.access.groups if g.group_id==message.group_id),None)
        grant=next((g for g in self.config.grants if g.group_id==message.group_id),None)
        if (group is None or message.member_id not in group.members or grant is None
                or message.member_id not in grant.members or 'current' not in group.capabilities):
            raise BotError('AI_NOT_AUTHORIZED')
        if (grant.device_id!=group.device_id
                or grant.device_id not in {d['id'] for d in self.monitoring.devices()}):
            raise BotError('AI_DEVICE_NOT_AUTHORIZED')
        return grant

    def prepare(self,raw,*,transport_app_id):
        def operation(message,access):
            command,*rest=message.content.split(maxsplit=1)
            if command!='/问AI' or not rest or not rest[0].strip():
                raise BotError('AI_EXPLICIT_COMMAND_REQUIRED')
            with self._lock:
                grant=self._permission(message)
                trial=self.service._channel_trial
                if trial is not None:
                    try:trial.check_admission()
                    except GatewayError as error:raise BotError(error.code) from None
                revision,binding=self.revision,self.monitoring.binding_revision
                remaining=300-(self._clock()-message.timestamp).total_seconds()-15
                if remaining<=0:
                    raise BotError('AI_REPLY_WINDOW_TOO_SHORT')
                deadline=self._now()+min(self.config.budget.turn_timeout_s,remaining)
                for key,task in list(self._tasks.items()):
                    if task['deadline']<=self._now() and task['state'] in ('ADMITTED','COMPLETED','FAILED','CANCELLED'):
                        task['plan'].handle.cancel();del self._tasks[key]
                if len(self._tasks)>=8:
                    raise BotError('AI_CAPACITY_REACHED')
                def check():
                    with self._lock:
                        self._permission(message)
                        if (self.revision!=revision or self.monitoring.binding_revision!=binding
                                or self._now()>=deadline):
                            raise BotError('CHANNEL_AUTHORIZATION_CHANGED')
                authorization=ChannelAuthorization(self.monitoring.config.instance_id,grant.device_id,
                    binding,revision,self.config.preset_id,grant.tools,self.config.budget,check)
                try:
                    prepared=self.service.prepare_channel_turn(rest[0].strip(),authorization)
                    session_key=_hash([transport_app_id,message.group_id,message.member_id,
                        authorization.instance_id,binding,grant.device_id])
                    context=QQAIMessageContext(transport_app_id,message.group_id,message.member_id,
                        message.message_id,message.timestamp,deadline,session_key)
                    plan=QQAIPlan(uuid.uuid4().hex,prepared,self._requests.create(),context)
                    if trial is not None:trial.reserve_admission(plan.handle)
                except GatewayError as error:
                    raise BotError(error.code) from None
                self._tasks[plan.id]=dict(plan=plan,deadline=deadline,state='ADMITTED',result=None)
                return plan
        result=self._ingress.admit_offline(raw,transport_app_id=transport_app_id,operation=operation)
        if not isinstance(result,QQAIPlan):
            raise BotError(result.code)
        return result

    def execute(self,plan):
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is None or task['plan'] is not plan or task['state']!='ADMITTED':
                raise BotError('AI_PLAN_ALREADY_USED')
            task['state']='EXECUTING'
        try:
            plan.prepared.channel_authorization.check()
            plan.handle.limit_turn(max(.001,task['deadline']-self._now()))
            result=self.service.execute_channel_turn(plan.prepared,plan.handle)
            plan.prepared.channel_authorization.check()
            with self._lock:
                task.update(state='COMPLETED',result=result)
            return result
        except Exception as error:
            with self._lock:task['state']='FAILED'
            plan.handle.finish(getattr(error,'code','AI_SERVICE_UNAVAILABLE'))
            raise BotError(getattr(error,'code','AI_SERVICE_UNAVAILABLE')) from None

    def check_delivery(self,plan,result):
        """Fake candidates never authorize QQ; a separate phase-specific trial may."""
        self.validate_delivery_candidate(plan,result)
        trial=self.service._channel_trial
        return bool(trial is not None and trial.approval.phase=='qq' and not trial.offline_test)

    def validate_plan(self,plan):
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is None or task['plan'] is not plan or task['state'] in ('CANCELLED','FAILED'):
                raise BotError('INVALID_AI_PLAN')
        self.service.validate_channel_turn(plan.prepared)

    def validate_delivery_candidate(self,plan,result):
        """Validation only, never a network permission or a can_deliver override."""
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is None or task['plan'] is not plan or task['result'] is not result or task['state']!='COMPLETED':
                raise BotError('INVALID_AI_DELIVERY')
        plan.handle.assert_resources_closed()
        self.service.validate_channel_turn(plan.prepared)
        trial=self.service._channel_trial
        expected_status='local_experimental' if trial is not None else 'candidate'
        expected_offline=trial is None or trial.offline_test
        if (not result.completed or result.source is None or result.offline_only!=expected_offline
                or result.release_status!=expected_status or result.can_deliver is not False
                or result.scope_revision!=plan.prepared.execution.profile.revision):
            raise BotError('INVALID_AI_DELIVERY')
        if trial is not None and (trial.approval.phase!='qq' or trial.handle is not plan.handle
                or result.source.source_kind!='simulator'):
            raise BotError('TRIAL_QQ_DELIVERY_NOT_APPROVED')

    def claim_delivery(self,plan,result):
        """One submission even if a second fake DeliveryOwner is accidentally built."""
        self.validate_delivery_candidate(plan,result)
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is None or task['plan'] is not plan:raise BotError('INVALID_AI_PLAN')
            if task.get('delivery_claimed'):raise BotError('AI_DELIVERY_ALREADY_CLAIMED')
            task['delivery_claimed']=True

    def claim_scheduler(self,owner):
        with self._lock:
            if self._scheduler is not None:raise BotError('AI_SCHEDULER_ALREADY_BOUND')
            self._scheduler=owner

    def release_scheduler(self,owner):
        with self._lock:
            if self._scheduler is owner:self._scheduler=None

    def discard(self,plan):
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is not None:
                if task['plan'] is not plan:
                    raise BotError('INVALID_AI_PLAN')
                del self._tasks[plan.id]
                task['plan'].handle.cancel()
