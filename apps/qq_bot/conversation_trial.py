"""One process, two independent one-use approvals; no mutable shared trial Service."""
from dataclasses import asdict,replace
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import threading
from types import SimpleNamespace
import uuid

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_service.channel import ChannelBudget
from apps.ai_service.channel_conversation_trial import CONTRACT,ConversationQwenTurn,prepared_scope
from apps.ai_service.channel_trial import PRESET,QwenTrialApproval,cost_reservation,money
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from apps.ai_service.service import ManagementAssistantService
from .ai_configuration import QQAIConfig,QQAIGrant
from .configuration import project_credentials
from .contracts import BotError
from .conversations import ConversationOptions,ConversationStore
from .monitoring_source import InstanceMonitoring
from .trial_configuration import inputs_snapshot,local_path,read_json,write_new

ROOT=Path(__file__).resolve().parents[2]
CONSENTS=('provider_and_cost','qq_network','simulator_data_disclosure','projected_history_disclosure',
    'sdk_thread_hard_exit_risk','beijing_price_and_context_confirmed','local_operator_only','bounded_explanation_display')


def check_configuration(inputs,*,max_cost_cny='2.00'):
    """No instance connection, credential resolution, approval creation or network."""
    access,ai,config,grant,_=inputs_snapshot(inputs)
    if money(max_cost_cny)<cost_reservation():raise BotError('TRIAL_COST_RESERVATION_INSUFFICIENT')
    scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
    return dict(code='CONVERSATION_TRIAL_CHECKED_LIVE_BLOCKED',contract=CONTRACT,scope_sha256=_hash(scope),
        preset=PRESET,model=assistant_profile(PRESET).model,instance_id=config.instance_id,device_id=grant.device_id,
        group_ref=_hash(inputs.group_id)[:12],member_ref=_hash(inputs.member_id)[:12],
        model_turns=2,requests_per_turn=2,output_tokens_per_request=512,seconds_per_turn=90,retries=0,
        cost_cap_per_turn_cny=max_cost_cny,total_cost_cap_cny=str(money(max_cost_cny)*2),
        reserved_cost_per_turn_cny=str(cost_reservation()),business_instance_opened=False,
        credential_checked=False,network_requests=0,approval_created=False)


class TurnApprovalFile:
    """Create-only consumption, stable across copied/renamed approval files."""
    def __init__(self,host,path,plan):
        self.host,self.path,self.plan=host,local_path(path),deepcopy(plan)
        self.value=read_json(self.path);self.digest=_hash(self.value);self.claimed=False
        self.marker=host.inputs.ai_config.parent/('.qwen-conversation-'+self.value['approval_id']+'.used')
        self.check()

    def check(self):
        value=read_json(self.path)
        if _hash(value)!=self.digest or _hash(self.value)!=self.digest:raise BotError('TRIAL_APPROVAL_CHANGED')
        p=self.plan;h=self.host
        if (p.get('contract')!=CONTRACT or p.get('run_id')!=h.run_id
                or p.get('scope_sha256')!=h.scope_sha256 or p.get('bindings_sha256')!=h.bindings
                or p.get('qualification_id') is not None or p.get('status')!='pending_operator_approval'
                or type(p.get('turn')) is not int or p['turn'] not in (1,2)
                or p.get('max_cost_cny')!=h.max_cost):
            raise BotError('CONVERSATION_APPROVAL_RUN_MISMATCH')
        expected={**self.plan,'status':'local_experimental','approval_id':value.get('approval_id'),
            'approved_at':value.get('approved_at'),'consents':{k:True for k in CONSENTS}}
        try:
            identifier=value['approval_id'];approved=datetime.fromisoformat(value['approved_at'])
            if (value!=expected or type(identifier) is not str or len(identifier)!=32
                    or any(c not in '0123456789abcdef' for c in identifier)
                    or approved.tzinfo is None or not datetime.fromisoformat(value['created_at'])<=approved<=self.host.clock()):
                raise ValueError()
        except Exception:raise BotError('INVALID_CONVERSATION_TRIAL_APPROVAL') from None
        if self.host.clock()>=datetime.fromisoformat(value['expires_at']):raise BotError('TRIAL_APPROVAL_EXPIRED')
        if self.marker.exists():
            if not self.claimed:raise BotError('TRIAL_ALREADY_USED')
            if read_json(self.marker)!={'approval_sha256':self.digest}:raise BotError('TRIAL_CONSUMPTION_CHANGED')
        elif self.claimed:raise BotError('TRIAL_CONSUMPTION_CHANGED')

    def claim(self):
        self.check()
        if self.claimed:raise BotError('TRIAL_ALREADY_USED')
        try:write_new(self.marker,{'approval_sha256':self.digest})
        except BotError as error:
            if error.code=='TRIAL_OUTPUT_EXISTS':raise BotError('TRIAL_ALREADY_USED') from None
            raise
        self.claimed=True

    def confirm_claim(self):
        self.check()
        if not self.claimed:raise BotError('CONVERSATION_TRIAL_NOT_CONSUMED')

    def grant(self):
        h=self.host;v=self.value
        return QwenTrialApproval(v['approval_id'],'qq',v['scope_sha256'],v['bindings_sha256'],
            datetime.fromisoformat(v['expires_at']),v['max_cost_cny'],h.monitoring.config.instance_id,
            h.device_id,h.access.app_id,h.inputs.group_id,h.inputs.member_id)


class ConversationTrial:
    """Process permit is not a model permit. Model leases are immutable per Turn."""
    def __init__(self,inputs,directory,*,max_cost_cny='2.00',minutes=10,seconds=300,
                 async_client_factory=None,clock=None):
        if type(minutes) is not int or not 1<=minutes<=10 or type(seconds) is not int or not 1<=seconds<=600:
            raise BotError('INVALID_RUN_DURATION')
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.inputs,self.directory=inputs,local_path(directory)
        check_configuration(inputs,max_cost_cny=max_cost_cny)
        if not self.directory.is_dir() or any(self.directory.iterdir()):raise BotError('CONVERSATION_REPORT_DIRECTORY_NOT_EMPTY')
        self.monitoring=InstanceMonitoring(inputs_snapshot(inputs)[2],clock=self.clock)
        access,ai,_,grant,self.bindings=inputs_snapshot(inputs,self.monitoring)
        ref=self.monitoring.capture_water(grant.device_id).analysis.observation
        if ref is not None and ref.source_kind!='simulator':raise BotError('TRIAL_SOURCE_NOT_APPROVED')
        approved=next(g for g in access.groups if g.group_id==inputs.group_id)
        self.access=replace(access,groups=(replace(approved,members=(inputs.member_id,)),))
        self.config=QQAIConfig(True,PRESET,ChannelBudget(),(QQAIGrant(inputs.group_id,(inputs.member_id,),grant.device_id),))
        self.options=ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)
        self.store=ConversationStore(self.options);self.device_id=grant.device_id
        self.scope=prepared_scope(self.options);self.scope_sha256=_hash(self.scope)
        self.run_id=uuid.uuid4().hex;self.max_cost=max_cost_cny;self.minutes=minutes;self.seconds=seconds
        self.expires=self.clock()+timedelta(seconds=seconds)
        self.factory=async_client_factory;self.offline_test=async_client_factory is not None
        self._lock=threading.RLock();self._closed=False;self._halted=None
        self._pending=None;self._ready=None;self._active=None;self.turns=[];self.sessions=[]
        self.changed=threading.Event();self.coordinator=None
        self.base_service=ManagementAssistantService(self.monitoring,credentials=None,
            traces=JsonlTraceSink(self.directory/'unused-base.trace.jsonl'),policy_directory=inputs.policy_directory)

    def bind(self,coordinator):
        if (self.coordinator is not None or coordinator.service is not self.base_service
                or coordinator.monitoring is not self.monitoring or coordinator.conversations is not self.store
                or coordinator.access!=self.access or coordinator.config!=self.config):
            raise BotError('CONVERSATION_TRIAL_COMPOSITION_REQUIRED')
        self.coordinator=coordinator

    def check(self):
        if self._closed or self._halted:raise BotError(self._halted or 'CONVERSATION_TRIAL_CLOSED')
        if self.clock()>=self.expires:raise BotError('CONVERSATION_RUN_EXPIRED')
        SDK_RESOURCES.assert_healthy()
        if inputs_snapshot(self.inputs,self.monitoring)[-1]!=self.bindings:raise BotError('TRIAL_BINDINGS_CHANGED')
        if _hash(prepared_scope(self.options))!=self.scope_sha256:raise BotError('TRIAL_SCOPE_CHANGED')

    def check_message(self,message):
        self.check()
        if (message.group_id,message.member_id)!=(self.inputs.group_id,self.inputs.member_id):
            raise BotError('TRIAL_MEMBER_NOT_APPROVED')

    def key(self):
        if self.coordinator is None:raise BotError('CONVERSATION_TRIAL_NOT_BOUND')
        return self.coordinator.conversation_context(SimpleNamespace(group_id=self.inputs.group_id,member_id=self.inputs.member_id))[0]

    def plan(self):
        self.check();state=self.store.state(self.key())
        with self._lock:
            if self._active is not None or self._ready is not None:raise BotError('CONVERSATION_TURN_PENDING')
            if len(self.turns)>=2:raise BotError('CONVERSATION_TURN_LIMIT')
            if state['turns']!=len(self.turns) or (self.turns and not self.turns[-1]['verified']):
                raise BotError('CONVERSATION_PREVIOUS_TURN_NOT_COMMITTED')
            now=self.clock()
            self._pending=dict(schema_version=1,contract=CONTRACT,status='pending_operator_approval',
                run_id=self.run_id,turn=len(self.turns)+1,scope_sha256=self.scope_sha256,
                bindings_sha256=self.bindings,state=state,predecessor_sha256=_hash(self.turns[-1]) if self.turns else None,
                created_at=now.isoformat(),expires_at=min(self.expires,now+timedelta(minutes=self.minutes)).isoformat(),
                max_cost_cny=self.max_cost,qualification_id=None)
            return deepcopy(self._pending)

    def approve(self,plan,path):
        """Called only after the local operator's challenge; never called by QQ."""
        self.check();state=self.store.state(self.key())
        with self._lock:
            if self._ready or self._active or plan!=self._pending or plan['state']!=state:
                raise BotError('CONVERSATION_APPROVAL_STATE_CHANGED')
            now=self.clock()
            if now>=datetime.fromisoformat(plan['expires_at']):raise BotError('TRIAL_APPROVAL_EXPIRED')
            value={**plan,'status':'local_experimental','approved_at':now.isoformat(),
                'approval_id':uuid.uuid4().hex,'consents':{k:True for k in CONSENTS}}
            write_new(path,value);self._ready=TurnApprovalFile(self,path,plan)
            return self._ready.digest

    def require_turn(self):
        self.check()
        with self._lock:
            if len(self.sessions)>=2:raise BotError('CONVERSATION_TURN_LIMIT')
            if self._ready is None:raise BotError('CONVERSATION_TURN_NOT_APPROVED')
            self._ready.check()
            if self._active is not None:raise BotError('CONVERSATION_TURN_PENDING')

    def begin(self,snapshot):
        self.require_turn()
        with self._lock:
            record=self._ready
            if record.value['state']!=self.store.state(self.key()):raise BotError('CONVERSATION_APPROVAL_STATE_CHANGED')
            record.claim()  # Admission consumes even if later queue/SDK/delivery fails.
            self._ready=None;self._pending=None;self._active=record
            def validate():
                self.check();record.check()
                self.store.authority.validate(snapshot,self.scope_sha256)
            session=None
            try:
                session=ConversationQwenTurn(record.grant(),authority=self.store.authority,
                    conversation_epoch=self.base_service.epoch,options=self.options,state=record.value['state'],
                    validate=validate,claim=record.confirm_claim,async_client_factory=self.factory,clock=self.clock)
                self.sessions.append(session)
                credentials=project_credentials(ROOT) if not self.offline_test else None
                return ManagementAssistantService(self.monitoring,credentials=credentials,
                    traces=JsonlTraceSink(self.directory/f"turn-{record.value['turn']}.trace.jsonl"),
                    policy_directory=self.inputs.policy_directory,channel_trial=session)
            except Exception:
                self.admission_failed(session,'CONVERSATION_ADMISSION_FAILED');raise

    def admission_failed(self,session,code):
        with self._lock:
            if self._active is None:return
            report=session.report() if session is not None else {'model_requests':0,'sdk_resources':None}
            report.pop('source_summary',None)
            self.turns.append(dict(turn=self._active.value['turn'],approval_sha256=self._active.digest,
                verified=False,outcome={'state':'FAILED','code':code},backend_completed=False,
                **report))
            self._active=None;self._halted='CONVERSATION_TURN_FAILED_STOP';self.changed.set()

    def finish(self,plan,outcome):
        with self._lock:
            record=self._active
            if record is None:return
            session=plan.service._channel_trial
            if session not in self.sessions or session.approval.approval_id!=record.value['approval_id']:
                raise BotError('CONVERSATION_TRIAL_COMPOSITION_REQUIRED')
            report=session.report();report.pop('source_summary',None)
            verified=(outcome.get('state')=='DELIVERED' and outcome.get('api_accepted') is True
                and outcome.get('history_code')=='HISTORY_COMMITTED' and not outcome.get('report_error')
                and report['model_requests']==2 and report['sdk_resources'] is not None
                and report['sdk_resources'].get('state')=='CLOSED' and report['sdk_resources'].get('thread_exited') is True
                and report['sdk_resources'].get('local_io_closed') is True and report['sdk_resources'].get('cleanup_error') is None)
            self.turns.append(dict(turn=record.value['turn'],approval_sha256=record.digest,
                state_before=record.value['state'],outcome=dict(outcome),verified=verified,
                backend_completed=plan.handle.state=='COMPLETED',**report))
            self._active=None
            if not verified:self._halted='CONVERSATION_TURN_FAILED_STOP'
            self.changed.set()

    def checkpoint(self,receipt):
        with self._lock:
            if self._active is None:raise BotError('CONVERSATION_NO_ACTIVE_TURN')
            turn=self._active.value['turn']
        write_new(self.directory/f'turn-{turn}.delivery.json',dict(contract=CONTRACT,turn=turn,
            receipt=asdict(receipt),client_display_confirmed=False,automatic_retry=False))

    def close(self):
        self._closed=True;self.store.close();self.changed.set()

    def report(self,code):
        return dict(contract=CONTRACT,code=code,run_id=self.run_id,scope_sha256=self.scope_sha256,
            turns=list(self.turns),offline_test=self.offline_test,client_display_confirmed=False,
            automatic_retry=False,ram_cleared=self._closed,completed=len(self.turns)==2 and all(t['verified'] for t in self.turns))
