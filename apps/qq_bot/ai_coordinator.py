"""Channel admission/execution; Fake by default, real trials require an independent approval."""
from dataclasses import asdict,dataclass,field
from datetime import datetime,timezone
from threading import RLock
from contextlib import nullcontext
from functools import wraps
import time
import uuid

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel import ChannelAuthorization
from apps.ai_service.runtime.release_contracts import _hash
from .adapter import QQAdapter
from .ai_configuration import QQAIConfig
from .contracts import BotError
from .conversations import ConversationStore,ConversationKey,prepared_scope
from .intent import classify,GatewayMention
from apps.ai_service.channel import OfflineChannelProvider


def _validation_only(function):
    """No Tool/model/QQ I/O or history writes may be added inside these methods."""
    @wraps(function)
    def invoke(self,*args,**kwargs):
        scope=getattr(self.session_run,'validation_scope',None)
        with (scope() if scope is not None else nullcontext()):
            return function(self,*args,**kwargs)
    return invoke


@dataclass(frozen=True)
class QQAIPlan:
    id: str
    prepared: object = field(repr=False)
    handle: object = field(repr=False)
    context: object = field(repr=False)
    service: object = field(default=None,repr=False)


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
    def __init__(self,access,monitoring,service,*,config=QQAIConfig(),clock=None,monotonic=time.monotonic,conversations=None,conversation_trial=None,session_run=None):
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
        self.conversations=conversations;self._conversation_state=None;self._mention_owner=None
        self.conversation_trial=conversation_trial
        self.session_run=session_run
        self._conversation_host=conversation_trial or session_run
        if session_run is not None:
            from .session_run import SessionRun
            from .session_run_trial import SessionTrialRun
            if type(session_run) not in (SessionRun,SessionTrialRun) or conversation_trial is not None:
                raise BotError('SESSION_RUN_COMPOSITION_REQUIRED')
            session_run.bind(self)
        elif conversation_trial is not None:
            from .conversation_trial import ConversationTrial
            if type(conversation_trial) is not ConversationTrial:raise BotError('CONVERSATION_TRIAL_COMPOSITION_REQUIRED')
            conversation_trial.bind(self)
        elif conversations is not None:
            if (type(conversations) is not ConversationStore or service._channel_trial is not None
                    or type(service._offline_channel_provider) is not OfflineChannelProvider):
                raise BotError('QQ_CONVERSATION_FAKE_ONLY')
            service.bind_offline_conversations(conversations.authority)

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
            if self.session_run is not None:self.session_run.ledger.halt('RUN_PERMISSION_CHANGED')
            if self.conversations is not None:self.conversations.invalidate()
            handles=[task['plan'].handle for task in self._tasks.values()]
        for handle in handles:
            handle.abort_io();handle.cancel()

    def _permission(self,message):
        if not self.config.enabled:
            raise BotError('AI_DISABLED')
        if self._conversation_host is not None:self._conversation_host.check_message(message)
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

    def _sync_conversations(self):
        policy=self.service.management_policy.snapshot()
        if self.session_run is not None:
            digest=_hash(self.session_run.scope_for_options())
        elif self.conversation_trial is not None:
            from apps.ai_service.channel_conversation_trial import prepared_scope as trial_scope
            digest=_hash(trial_scope(self.conversations.options))
        else:digest=_hash(prepared_scope(self.conversations.options,self.config.preset_id))
        state=(self.revision,self.monitoring.binding_revision,policy.revision,digest)
        if self._conversation_state is not None and self._conversation_state!=state:self.conversations.invalidate()
        self._conversation_state=state
        if 'get_current_water_quality' not in policy.selected_tools or self.config.budget.max_output_tokens>512:
            raise BotError('AI_NOT_AUTHORIZED')
        return state

    @_validation_only
    def conversation_context(self,message,*,grant=None):
        if self.conversations is None:raise BotError('QQ_CONVERSATION_DISABLED')
        with self._lock:
            grant=grant or self._permission(message)
            permission,binding,policy,digest=self._sync_conversations()
            key=ConversationKey(self.access.app_id,message.group_id,message.member_id,
                self.monitoring.config.instance_id,grant.device_id,permission,binding,policy,digest,self.service.epoch)
            return key,self.conversations.topic(key)

    def validate_mention(self,raw,message,mention,app_id):
        import hashlib
        if (type(mention) is not GatewayMention or self._mention_owner is None
                or mention.owner is not self._mention_owner or mention.app_id!=app_id
                or mention.message_id!=message.message_id or mention.raw_sha256!=hashlib.sha256(raw).hexdigest()):
            raise BotError('AI_AUTHENTICATED_MENTION_REQUIRED')

    def clear_conversation(self,message):
        with self._lock:
            key,_=self.conversation_context(message);self.conversations.clear(key);return key

    def prepare(self,raw,*,transport_app_id,mention=None,capacity_check=None):
        def operation(message,access):
            command,*rest=message.content.split(maxsplit=1)
            if self.conversations is None and (command!='/问AI' or not rest or not rest[0].strip()):
                raise BotError('AI_EXPLICIT_COMMAND_REQUIRED')
            with self._lock:
                grant=self._permission(message)
                history=None;history_key=None;history_focus=None
                question=rest[0].strip() if command=='/问AI' and rest else ''
                if self.conversations is not None:
                    if command!='/问AI':
                        if self.conversations.options.trigger_mode!='mention_ai':raise BotError('AI_EXPLICIT_COMMAND_REQUIRED')
                        self.validate_mention(raw,message,mention,transport_app_id)
                        question=message.content
                    key,topic=self.conversation_context(message,grant=grant)
                    intent=classify(question,topic=topic,command_priority=False)
                    if intent.kind!='water':raise BotError('AI_WATER_QUESTION_REQUIRED')
                    history_key,history_focus=key,intent.focus;question=intent.question
                trial=self.service._channel_trial
                if trial is not None:
                    try:trial.check_admission()
                    except GatewayError as error:raise BotError(error.code) from None
                revision,binding=self.revision,self.monitoring.binding_revision
                remaining=300-(self._clock()-message.timestamp).total_seconds()-15
                if remaining<=0:
                    raise BotError('AI_REPLY_WINDOW_TOO_SHORT')
                deadline=self._now()+min(self.config.budget.turn_timeout_s,remaining)
                if self.session_run is not None:deadline=min(deadline,self._now()+self.session_run.remaining())
                session_key=_hash([transport_app_id,message.group_id,message.member_id,
                    self.monitoring.config.instance_id,binding,grant.device_id])
                if self.session_run is not None:
                    if capacity_check is None:raise BotError('RUN_SCHEDULER_ADMISSION_REQUIRED')
                    capacity_check(session_key)  # Under scheduler capacity lock, before quota or private Service.
                for key,task in list(self._tasks.items()):
                    if task['deadline']<=self._now() and task['state'] in ('ADMITTED','COMPLETED','FAILED','CANCELLED'):
                        task['plan'].handle.cancel()
                        if task['plan'].prepared.channel_history is not None:self.conversations.release(task['plan'].prepared.channel_history)
                        del self._tasks[key]
                if len(self._tasks)>=8:
                    raise BotError('AI_CAPACITY_REACHED')
                def check():
                    with self._lock:
                        self._permission(message)
                        if (self.revision!=revision or self.monitoring.binding_revision!=binding
                                or self._now()>=deadline):
                            raise BotError('CHANNEL_AUTHORIZATION_CHANGED')
                        if history is not None:history.authority.validate(history,history.scope_sha256)
                authorization=ChannelAuthorization(self.monitoring.config.instance_id,grant.device_id,
                    binding,revision,self.config.preset_id,grant.tools,self.config.budget,check)
                service=self.service
                try:
                    if self._conversation_host is not None:self._conversation_host.require_turn()
                    if history_key is not None:history=self.conversations.snapshot(history_key,focus=history_focus)
                    if self.conversation_trial is not None:
                        service=self.conversation_trial.begin(history);trial=service._channel_trial
                    elif self.session_run is not None:
                        service=self.session_run.begin(history,message=message);trial=service._channel_trial
                    prepared=service.prepare_channel_turn(question,authorization,history_snapshot=history) if history else \
                        service.prepare_channel_turn(question,authorization)
                    session_key=_hash([transport_app_id,message.group_id,message.member_id,
                        authorization.instance_id,binding,grant.device_id])
                    context=QQAIMessageContext(transport_app_id,message.group_id,message.member_id,
                        message.message_id,message.timestamp,deadline,session_key)
                    plan=QQAIPlan(uuid.uuid4().hex,prepared,self._requests.create(),context,service)
                    if trial is not None:trial.reserve_admission(plan.handle)
                except Exception as error:
                    if history is not None:self.conversations.release(history)
                    if self._conversation_host is not None and service is not self.service:
                        self._conversation_host.admission_failed(service._channel_trial,getattr(error,'code','AI_ADMISSION_FAILED'))
                    raise BotError(getattr(error,'code','AI_ADMISSION_FAILED')) from None
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
            result=(plan.service or self.service).execute_channel_turn(plan.prepared,plan.handle)
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
        trial=(plan.service or self.service)._channel_trial
        return bool(trial is not None and trial.approval.phase=='qq' and not trial.offline_test)

    @_validation_only
    def validate_plan(self,plan):
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is None or task['plan'] is not plan or task['state'] in ('CANCELLED','FAILED'):
                raise BotError('INVALID_AI_PLAN')
        try:(plan.service or self.service).validate_channel_turn(plan.prepared)
        except Exception:
            if self.conversations is not None:
                with self._lock:self._sync_conversations()
            raise

    def accept_delivery(self,plan,result,text,receipt,cancelled):
        snapshot=plan.prepared.channel_history
        if snapshot is None:return None
        if receipt.status!='DELIVERED' or not receipt.api_accepted:return 'HISTORY_NOT_COMMITTED_DELIVERY'
        with self._lock:
            try:
                if cancelled.is_set():raise BotError('AI_CANCELLED')
                plan.handle.check();self.validate_delivery_candidate(plan,result)
                source=result.source
                return self.conversations.commit(snapshot,turn_id=plan.context.delivery_key,text=text,
                    text_sha256=receipt.text_sha256,accepted_at=receipt.accepted_at,
                    source_times=tuple(t for t in (source.observed_at,source.received_at,source.evaluated_at) if t),
                    source_flags=(source.source_kind,source.quality,source.freshness,source.connectivity))
            except Exception:
                self.conversations.abort_snapshot(snapshot)
                return 'HISTORY_NOT_COMMITTED'

    @_validation_only
    def validate_delivery_candidate(self,plan,result):
        """Validation only, never a network permission or a can_deliver override."""
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is None or task['plan'] is not plan or task['result'] is not result or task['state']!='COMPLETED':
                raise BotError('INVALID_AI_DELIVERY')
        plan.handle.assert_resources_closed()
        service=plan.service or self.service
        service.validate_channel_turn(plan.prepared)
        trial=service._channel_trial
        expected_status=trial.release_status if trial is not None else 'candidate'
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

    def discard(self,plan,*,outcome=None):
        with self._lock:
            task=self._tasks.get(plan.id)
            if task is not None:
                if task['plan'] is not plan:
                    raise BotError('INVALID_AI_PLAN')
                del self._tasks[plan.id]
                if plan.prepared.channel_history is not None:self.conversations.release(plan.prepared.channel_history)
                if self._conversation_host is not None:
                    self._conversation_host.finish(plan,outcome or {'state':'CANCELLED','code':'AI_ADMISSION_ABORTED'})
                task['plan'].handle.cancel()
