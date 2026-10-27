"""Typed real-run host over the shared quota/controller, with one local approval."""
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import time

from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_service.channel_trial import PRESET,cost_reservation
from apps.ai_service.channel_session_trial import (CONTRACT,prepared_scope,check_preparation,
    RunAuthorizationAuthority,SessionTrialQwenTurn)
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from .configuration import project_credentials
from .contracts import BotError,identifier
from .conversations import ConversationOptions
from .run_consent import RunLedger,RunLimits
from .session_run import SessionRun
from .trial_configuration import inputs_snapshot,read_json,write_new

ROOT=Path(__file__).resolve().parents[2]
CONSENTS=('provider_network','qq_network','scope_and_price_budget','simulator_disclosure',
    'projected_history_disclosure','sdk_thread_hard_exit_risk','local_operator_only')


def selected_members(inputs,access,grant,members):
    selected=(inputs.member_id,) if members is None else members
    group=next(g for g in access.groups if g.group_id==inputs.group_id)
    if (type(selected) is not tuple or not 1<=len(selected)<=4 or len(set(selected))!=len(selected)
            or any(identifier(m)!=m or m not in group.members or m not in grant.members for m in selected)):
        raise BotError('RUN_MEMBERS_NOT_APPROVED')
    return selected


def check_configuration(inputs,*,limits=RunLimits(),members=None):
    """Metadata/Policy/Scope only; no database, credential resolution or approval."""
    if type(limits) is not RunLimits:raise BotError('INVALID_RUN_LIMITS')
    access,ai,source,grant,_=inputs_snapshot(inputs)
    selected=selected_members(inputs,access,grant,members)
    options=ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)
    scope=prepared_scope(options)
    check_preparation(read_json(ROOT/'apps/ai_service/resources/qq_session_run_trial.json'),scope)
    return dict(code='SESSION_TRIAL_CHECKED_APPROVAL_REQUIRED',contract=CONTRACT,
        scope_sha256=_hash(scope),preset=PRESET,provider=assistant_profile(PRESET).service_id,
        model=assistant_profile(PRESET).model,instance_id=source.instance_id,device_id=grant.device_id,
        data_root=str(source.data_root),
        group_ref=_hash(inputs.group_id)[:12],member_refs=[_hash(m)[:12] for m in selected],
        max_turns=limits.max_turns,seconds=limits.seconds,total_budget_cny=limits.total_budget_cny,
        reservation_per_turn_cny=str(cost_reservation()),total_reservation_cny=str(cost_reservation()*limits.max_turns),
        max_model_requests=2*limits.max_turns,requests_per_turn=2,output_tokens_per_request=512,
        seconds_per_turn=90,retries=0,qualification_id=None,status='candidate',
        credential_checked=False,business_instance_opened=False,network_requests=0,approval_created=False)


class SessionTrialLedger(RunLedger):
    """Same quota primitive, distinct plan contract before any approval/claim."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._plan.update(contract=CONTRACT,environment='EXPLICIT_PROCESS_OPERATOR_TRIAL')
    def report(self):return {**super().report(),'contract':CONTRACT}


class SessionTrialRun(SessionRun):
    def __init__(self,inputs,directory,*,limits=RunLimits(),members=None,valid_minutes=10,
                 async_client_factory=None,clock=None,monotonic=time.monotonic):
        if type(valid_minutes) is not int or not 1<=valid_minutes<=10:raise BotError('INVALID_RUN_APPROVAL_DURATION')
        configuration=check_configuration(inputs,limits=limits,members=members)
        self._authorization=None;self._approval_digest=None
        self._authority=RunAuthorizationAuthority(self._validate_authorization)
        self._initialize(inputs,directory,async_client_factory=async_client_factory,limits=limits,
            members=members,clock=clock,monotonic=monotonic)
        self._pending_plan={**super().plan(),'created_at':self.clock().isoformat(),
            'configuration':configuration,
            'approval_deadline':(self.clock()+timedelta(minutes=valid_minutes)).isoformat(),
            'operator_source':'LOCAL_UNAUTHENTICATED','qualification_id':None,
            'consents_required':list(CONSENTS),'max_model_requests':limits.max_turns*2,
            'source':'SIMULATOR','history':'PROJECTED_UNTRUSTED_TRANSCRIPT_V1'}

    def scope_for_options(self):return prepared_scope(self.options)
    def _new_ledger(self,limits):
        return SessionTrialLedger(self.directory,scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest,limits=limits,clock=self.clock,monotonic=self.now)

    def plan(self):
        from copy import deepcopy
        return deepcopy(self._pending_plan)

    def approve(self,plan,*,confirmed=False):
        if (confirmed is not True or plan!=self._pending_plan or self._authorization is not None
                or self.clock()>=datetime.fromisoformat(plan['approval_deadline'])):
            raise BotError('INVALID_SESSION_TRIAL_APPROVAL')
        if (inputs_snapshot(self.inputs,self.monitoring)[-1]!=self.bindings
                or _hash(self.scope_for_options())!=self.scope_sha256):raise BotError('RUN_BINDINGS_CHANGED')
        check_configuration(self.inputs,limits=self.ledger.limits,members=self.members)
        SDK_RESOURCES.assert_healthy()
        value=dict(contract=CONTRACT,plan=plan,status='local_experimental',qualification_id=None,
            approved_at=self.clock().isoformat(),consents={k:True for k in CONSENTS},
            operator_source='LOCAL_UNAUTHENTICATED')
        try:
            write_new(self.directory/'approval.json',value);self._approval_digest=_hash(value)
            consent=self.ledger.approve(self.ledger.plan(),confirmed=True)
            self._authorization=self._authority._issue(consent_id=consent.consent_id,
                scope_sha256=self.scope_sha256,bindings_sha256=self._binding_digest,lease_authority=self.ledger.authority)
        except Exception:
            self.ledger.halt('RUN_APPROVAL_WRITE_FAILED');raise BotError('RUN_APPROVAL_WRITE_FAILED') from None
        return self._approval_digest

    def _validate_authorization(self,value):
        super().check()
        check_preparation(read_json(ROOT/'apps/ai_service/resources/qq_session_run_trial.json'),self.scope)
        if value is not self._authorization or _hash(read_json(self.directory/'approval.json'))!=self._approval_digest:
            self.ledger.halt('RUN_APPROVAL_CHANGED');raise BotError('RUN_APPROVAL_CHANGED')

    def check(self):
        self.ledger.check()
        try:
            self._authority.validate(self._authorization)
        except Exception as error:
            code=getattr(error,'code','RUN_APPROVAL_CHANGED');self.ledger.halt(code);raise BotError(code) from None

    def _turn_credentials(self):
        self.check()
        return None if self.offline_test else project_credentials(ROOT)

    def _create_turn(self,lease,snapshot,validate):
        self.check()
        return SessionTrialQwenTurn(lease,run_authorization=self._authorization,
            authority=self.store.authority,conversation_epoch=self.base_service.epoch,
            options=self.options,snapshot=snapshot,validate=validate,claim=lambda:self.ledger.check_lease(lease),
            async_client_factory=self.factory,clock=self.clock,monotonic=self.now)

    def report(self,code='RUN_SNAPSHOT'):
        report=super().report(code)
        return {**report,'run_approved':self._authorization is not None,
            'live_composition':not self.offline_test,
            'real_execution':not self.offline_test and any(s.requests>0 for s in self.sessions)}

