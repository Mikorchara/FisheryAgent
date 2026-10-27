"""Offline bounded run host. Existing Gateway/Scheduler/Agent remain owners."""
from dataclasses import asdict,replace
from datetime import datetime,timezone
import threading
import time

from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_service.channel import ChannelBudget
from apps.ai_service.channel_session_run import SessionQwenTurn,prepared_scope,CONTRACT
from apps.ai_service.channel_trial import PRESET
from apps.ai_service.runtime.release_contracts import _hash
from apps.ai_service.service import ManagementAssistantService
from .ai_configuration import QQAIConfig,QQAIGrant
from .contracts import BotError,identifier
from .conversations import ConversationOptions,ConversationStore
from .monitoring_source import InstanceMonitoring
from .run_consent import RunLedger,RunLimits
from .trial_configuration import inputs_snapshot,local_path,write_new


class SessionRun:
    """One selected group/instance/device, up to four explicitly selected members.

    No real transport or credential supplier. All turns use memory HTTP and the
    existing SDK resource contract, with a private Service and Handle per lease.
    """
    def __init__(self,inputs,directory,*,async_client_factory,limits=RunLimits(),members=None,
                 clock=None,monotonic=time.monotonic):
        if async_client_factory is None:raise BotError('SESSION_RUN_OFFLINE_ONLY')
        self._initialize(inputs,directory,async_client_factory=async_client_factory,limits=limits,
            members=members,clock=clock,monotonic=monotonic)

    def _initialize(self,inputs,directory,*,async_client_factory,limits,members,clock,monotonic):
        """Shared run mechanics; public constructors own their distinct authorization gates."""
        self.clock=clock or (lambda:datetime.now(timezone.utc));self.now=monotonic
        self.inputs,self.directory=inputs,local_path(directory)
        if not self.directory.is_dir() or any(self.directory.iterdir()):raise BotError('RUN_DIRECTORY_NOT_EMPTY')
        access,ai,source,grant,_=inputs_snapshot(inputs)
        selected=(inputs.member_id,) if members is None else members
        group=next(g for g in access.groups if g.group_id==inputs.group_id)
        if (type(selected) is not tuple or not 1<=len(selected)<=4 or len(set(selected))!=len(selected)
                or any(identifier(m)!=m or m not in group.members or m not in grant.members for m in selected)):
            raise BotError('RUN_MEMBERS_NOT_APPROVED')
        self.members=selected;self.device_id=grant.device_id
        self.monitoring=InstanceMonitoring(source,clock=self.clock)
        self.bindings=inputs_snapshot(inputs,self.monitoring)[-1]
        self.access=replace(access,groups=(replace(group,members=selected),))
        self.config=QQAIConfig(True,PRESET,ChannelBudget(),(QQAIGrant(inputs.group_id,selected,grant.device_id),))
        self.options=ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)
        self.store=ConversationStore(self.options,monotonic=monotonic)
        self.scope=self.scope_for_options();self.scope_sha256=_hash(self.scope)
        self._binding_digest=_hash([self.bindings,selected,asdict(limits)])
        self.ledger=self._new_ledger(limits)
        self.base_service=ManagementAssistantService(self.monitoring,credentials=None,
            traces=JsonlTraceSink(self.directory/'unused-base.trace.jsonl'),policy_directory=inputs.policy_directory)
        self.factory=async_client_factory;self.offline_test=async_client_factory is not None;self._lock=threading.RLock()
        self.coordinator=None;self.sessions=[];self.turns=[];self._active={};self._closed=False

    def scope_for_options(self):return prepared_scope(self.options)

    def _new_ledger(self,limits):
        return RunLedger(self.directory,scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest,limits=limits,clock=self.clock,monotonic=self.now)

    def _turn_credentials(self):return None

    def _create_turn(self,lease,snapshot,validate):
        return SessionQwenTurn(lease,authority=self.store.authority,conversation_epoch=self.base_service.epoch,
            options=self.options,snapshot=snapshot,validate=validate,claim=lambda:self.ledger.check_lease(lease),
            async_client_factory=self.factory,clock=self.clock,monotonic=self.now)

    def plan(self):
        plan=self.ledger.plan()
        plan.update(preset=PRESET,instance_ref=_hash(self.monitoring.config.instance_id)[:12],
            device_ref=_hash(self.device_id)[:12],group_ref=_hash(self.inputs.group_id)[:12],
            member_refs=[_hash(m)[:12] for m in self.members])
        return plan

    def approve(self,plan,*,confirmed=False):
        # Approval is a trusted local operation over this Host, not file import.
        if plan!=self.plan():raise BotError('INVALID_RUN_APPROVAL')
        return self.ledger.approve(self.ledger.plan(),confirmed=confirmed)

    def bind(self,coordinator):
        if (self.coordinator is not None or coordinator.service is not self.base_service
                or coordinator.monitoring is not self.monitoring or coordinator.conversations is not self.store
                or coordinator.access!=self.access or coordinator.config!=self.config):
            raise BotError('SESSION_RUN_COMPOSITION_REQUIRED')
        self.coordinator=coordinator

    def check(self):
        self.ledger.check()
        try:
            SDK_RESOURCES.assert_healthy()
            if inputs_snapshot(self.inputs,self.monitoring)[-1]!=self.bindings:raise BotError('RUN_BINDINGS_CHANGED')
            if _hash(self.scope_for_options())!=self.scope_sha256:raise BotError('RUN_SCOPE_CHANGED')
            if self.coordinator is not None and (self.coordinator.config!=self.config or self.coordinator.access!=self.access):
                raise BotError('RUN_PERMISSION_CHANGED')
        except Exception as error:
            code=getattr(error,'code','RUN_CONFIGURATION_UNAVAILABLE')
            self.ledger.halt(code);raise BotError(code) from None

    def check_message(self,message):
        self.check()
        if message.group_id!=self.inputs.group_id or message.member_id not in self.members:
            raise BotError('RUN_MEMBER_NOT_APPROVED')

    def remaining(self):return self.ledger.remaining()
    def require_turn(self):self.check();self.ledger.can_admit()

    def begin(self,snapshot,*,message):
        self.check_message(message)
        if (snapshot.identity[:3]!=(self.access.app_id,message.group_id,message.member_id)
                or snapshot.identity[3:5]!=(self.monitoring.config.instance_id,self.device_id)):
            raise BotError('RUN_HISTORY_BINDING_CHANGED')
        self.store.authority.validate(snapshot,self.scope_sha256)
        lease=self.ledger.reserve(message_key=_hash([self.access.app_id,message.group_id,message.message_id]),
            fingerprint=_hash([message.member_id,message.timestamp.isoformat(),message.content]),
            member_id=message.member_id,instance_id=self.monitoring.config.instance_id,
            device_id=self.device_id,app_id=self.access.app_id,group_id=message.group_id)
        with self._lock:self._active[lease.sequence]=dict(lease=lease,snapshot=snapshot,session=None)
        def validate():
            self.check();self.ledger.check_lease(lease)
            self.store.authority.validate(snapshot,self.scope_sha256)
        try:
            session=self._create_turn(lease,snapshot,validate)
            with self._lock:
                self._active[lease.sequence]['session']=session;self.sessions.append(session)
            return ManagementAssistantService(self.monitoring,credentials=self._turn_credentials(),
                traces=JsonlTraceSink(self.directory/f'turn-{lease.sequence}.trace.jsonl'),
                policy_directory=self.inputs.policy_directory,channel_trial=session)
        except Exception as error:
            self.admission_failed(None,getattr(error,'code','RUN_ADMISSION_FAILED'),sequence=lease.sequence);raise

    def admission_failed(self,session,code,*,sequence=None):
        with self._lock:
            sequence=sequence or (session.approval.sequence if session is not None else None)
            record=self._active.pop(sequence,None)
            if record is None:return
            self.turns.append(dict(turn=sequence,verified=False,state='FAILED',code=code,model_requests=0))
        self.ledger.halt('RUN_ADMISSION_FAILED')

    def finish(self,plan,outcome):
        session=plan.service._channel_trial;sequence=session.approval.sequence
        with self._lock:
            record=self._active.pop(sequence,None)
            if record is None:return
            report=session.report();report.pop('source_summary',None)
            resources=report['sdk_resources']
            safe=resources is None and report['model_requests']==0 or (resources is not None
                and resources.get('state')=='CLOSED' and resources.get('thread_exited') is True
                and resources.get('local_io_closed') is True and resources.get('cleanup_error') is None)
            verified=bool(outcome.get('state')=='DELIVERED' and outcome.get('api_accepted') is True
                and outcome.get('history_code')=='HISTORY_COMMITTED' and not outcome.get('report_error')
                and safe and report['model_requests']==2)
            entry=dict(turn=sequence,verified=verified,outcome=dict(outcome),
                backend_completed=plan.handle.state=='COMPLETED',**report)
            self.turns.append(entry)
        if not safe:self.ledger.halt('RUN_SDK_RESOURCE_UNSAFE')
        if outcome.get('report_error'):self.ledger.halt('RUN_CHECKPOINT_FAILED')
        code=outcome.get('code') or ''
        if code in ('AI_AUTH_CHANGED','CHANNEL_AUTHORIZATION_CHANGED'):
            # A user clearing only their snapshot is not a run-wide revocation.
            try:self.check()
            except BotError:pass
        try:write_new(self.directory/f'turn-{sequence}.result.json',entry)
        except Exception:self.ledger.halt('RUN_CHECKPOINT_FAILED')

    def checkpoint_for(self,plan,receipt):
        try:
            sequence=plan.service._channel_trial.approval.sequence
            write_new(self.directory/f'turn-{sequence}.delivery.json',dict(contract=self.scope['contract'],
                turn=sequence,receipt=asdict(receipt),client_display_confirmed=False,automatic_retry=False))
        except Exception:
            self.ledger.halt('RUN_CHECKPOINT_FAILED');raise BotError('RUN_CHECKPOINT_FAILED') from None

    def stop(self,scheduler,*,code='RUN_STOPPED',report_path=None):
        """No background recovery; caller owns scheduler lifecycle."""
        error=None
        try:scheduler.close()
        except BotError as failure:self.ledger.halt(failure.code);error=failure
        finally:self.close()
        report=self.report(code)
        try:write_new(report_path or self.directory/'result.json',report)
        except Exception:
            self.ledger.halt('RUN_REPORT_FAILED');raise BotError('RUN_REPORT_FAILED') from None
        if error:raise error
        return report

    def run_until_stopped(self,scheduler,*,stop_event=None):
        """Controller-thread loop; never wait for input on a Gateway/worker thread."""
        if scheduler.coordinator is not self.coordinator:raise BotError('SESSION_RUN_COMPOSITION_REQUIRED')
        stop_event=stop_event or threading.Event();code='RUN_STOPPED'
        try:
            while not stop_event.wait(.05):self.check()
        except KeyboardInterrupt:code='RUN_OPERATOR_INTERRUPTED'
        except Exception as error:code=getattr(error,'code','RUN_CONTROLLER_FAILED');self.ledger.halt(code)
        return self.stop(scheduler,code=code)

    def close(self):
        self._closed=True;self.store.close();self.ledger.close()

    def report(self,code='RUN_SNAPSHOT'):
        return dict(contract=self.scope['contract'],code=code,scope_sha256=self.scope_sha256,
            quota=self.ledger.report(),turns=sorted(self.turns,key=lambda t:t['turn']),
            offline_test=self.offline_test,real_execution=not self.offline_test,ram_cleared=self._closed,
            client_display_confirmed=False,automatic_retry=False)

