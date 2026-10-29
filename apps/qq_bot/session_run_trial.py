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
from apps.ai_service.channel_validation import validation_once
from apps.ai_service.channel_chat_presentation import validate_mode
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


def check_configuration(inputs,*,limits=RunLimits(),members=None,presentation_mode='chat'):
    """Metadata/Policy/Scope only; no database, credential resolution or approval."""
    if type(limits) is not RunLimits:raise BotError('INVALID_RUN_LIMITS')
    access,ai,source,grant,_=inputs_snapshot(inputs)
    selected=selected_members(inputs,access,grant,members)
    options=ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)
    validate_mode(presentation_mode)
    scope=prepared_scope(options,presentation_mode)
    check_preparation(read_json(_preparation_path(presentation_mode)),scope)
    return dict(code='SESSION_TRIAL_CHECKED_APPROVAL_REQUIRED',contract=CONTRACT,
        scope_sha256=_hash(scope),preset=PRESET,provider=assistant_profile(PRESET).service_id,
        model=assistant_profile(PRESET).model,instance_id=source.instance_id,device_id=grant.device_id,
        data_root=str(source.data_root),
        group_ref=_hash(inputs.group_id)[:12],member_refs=[_hash(m)[:12] for m in selected],
        max_turns=limits.max_turns,seconds=limits.seconds,total_budget_cny=limits.total_budget_cny,
        reservation_per_turn_cny=str(cost_reservation()),total_reservation_cny=str(cost_reservation()*limits.max_turns),
        max_model_requests=2*limits.max_turns,requests_per_turn=2,output_tokens_per_request=512,
        seconds_per_turn=90,retries=0,qualification_id=None,status='candidate',
        presentation_mode=presentation_mode,
        credential_checked=False,business_instance_opened=False,network_requests=0,approval_created=False)


def _preparation_path(mode):
    validate_mode(mode)
    name='qq_session_run_trial.json' if mode=='chat' else 'qq_session_run_trial_detailed.json'
    return ROOT/'apps/ai_service/resources'/name


class SessionTrialLedger(RunLedger):
    """Same quota primitive, distinct plan contract before any approval/claim."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._plan.update(contract=CONTRACT,environment='EXPLICIT_PROCESS_OPERATOR_TRIAL')
    def report(self):return {**super().report(),'contract':CONTRACT}


class SessionTrialRun(SessionRun):
    # Subclasses must supply their own reviewed preparation/consent/typed Turn.
    consents = CONSENTS
    contract = CONTRACT
    configuration_check = staticmethod(check_configuration)
    preparation_path = staticmethod(_preparation_path)
    preparation_check = staticmethod(check_preparation)
    authorization_authority = RunAuthorizationAuthority
    def __init__(self,inputs,directory,*,limits=RunLimits(),members=None,valid_minutes=10,
                 async_client_factory=None,clock=None,monotonic=time.monotonic,presentation_mode='chat'):
        if type(valid_minutes) is not int or not 1<=valid_minutes<=10:raise BotError('INVALID_RUN_APPROVAL_DURATION')
        self.presentation_mode=validate_mode(presentation_mode)
        configuration=self.configuration_check(inputs,limits=limits,members=members,presentation_mode=presentation_mode)
        self._authorization=None;self._approval_digest=None
        self._authority=self.authorization_authority(self._validate_authorization)
        self._initialize(inputs,directory,async_client_factory=async_client_factory,limits=limits,
            members=members,clock=clock,monotonic=monotonic)
        self._pending_plan={**super().plan(),'created_at':self.clock().isoformat(),
            'configuration':configuration,
            'approval_deadline':(self.clock()+timedelta(minutes=valid_minutes)).isoformat(),
            'operator_source':'LOCAL_UNAUTHENTICATED','qualification_id':None,
            'consents_required':list(self.consents),'max_model_requests':limits.max_turns*2,
            'source':'SIMULATOR','history':'PROJECTED_UNTRUSTED_TRANSCRIPT_V1'}

    def scope_for_options(self):return prepared_scope(self.options,self.presentation_mode)
    def validation_scope(self):return self._authority.boundary.scope()
    def _check_configuration(self):
        if self.presentation_mode!=self.scope['presentation']['mode']:
            raise BotError('RUN_SCOPE_CHANGED')
        return validation_once(('run-configuration',id(self)),super()._check_configuration)
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
        self.configuration_check(self.inputs,limits=self.ledger.limits,members=self.members,presentation_mode=self.presentation_mode)
        SDK_RESOURCES.assert_healthy()
        value=dict(contract=self.contract,plan=plan,status='local_experimental',qualification_id=None,
            approved_at=self.clock().isoformat(),consents={k:True for k in self.consents},
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
        if value is not self._authorization:
            self.ledger.halt('RUN_APPROVAL_CHANGED');raise BotError('RUN_APPROVAL_CHANGED')
        def check_files():
            self.preparation_check(read_json(self.preparation_path(self.presentation_mode)),self.scope)
            if _hash(read_json(self.directory/'approval.json'))!=self._approval_digest:
                self.ledger.halt('RUN_APPROVAL_CHANGED');raise BotError('RUN_APPROVAL_CHANGED')
        validation_once(('run-approval',id(self)),check_files)

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
            async_client_factory=self.factory,clock=self.clock,monotonic=self.now,
            presentation_mode=self.presentation_mode)

    def report(self,code='RUN_SNAPSHOT'):
        report=super().report(code)
        return {**report,'run_approved':self._authorization is not None,
            'live_composition':not self.offline_test,
            'real_execution':not self.offline_test and any(s.requests>0 for s in self.sessions)}

