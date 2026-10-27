"""Independent process-approved Qwen run; never promotes the Fake-only Scope."""
from dataclasses import dataclass,asdict
import hashlib
from pathlib import Path

from apps.ai_backend.model_gateway import GatewayError
from .channel_session_run import SessionQwenTurn,TurnLease,memory_sdk_factory,session_scope as offline_scope
from .channel_trial import PRESET
from .runtime.assistant import assistant_profile
from .runtime.release_contracts import _hash

CONTRACT='qq-qwen-bounded-session-real-trial@1'


@dataclass(frozen=True,repr=False)
class RunAuthorization:
    authority: object
    ticket: object
    consent_id: str
    scope_sha256: str
    bindings_sha256: str
    lease_authority: object


class RunAuthorizationAuthority:
    """Only exact server-issued object identity grants execution, never JSON flags."""
    def __init__(self,check):self._check=check;self._authorization=None
    def _issue(self,*,consent_id,scope_sha256,bindings_sha256,lease_authority):
        if self._authorization is not None:raise GatewayError('SESSION_TRIAL_ALREADY_APPROVED')
        self._authorization=RunAuthorization(self,object(),consent_id,scope_sha256,bindings_sha256,lease_authority)
        return self._authorization
    def validate(self,value):
        if type(value) is not RunAuthorization or value is not self._authorization or value.authority is not self:
            raise GatewayError('SESSION_TRIAL_RUN_AUTHORIZATION_REQUIRED')
        self._check(value)


def trial_scope(profile,policy,registry,options):
    base=offline_scope(profile,policy,registry,options)
    root=Path(__file__).resolve().parents[2]
    paths=('apps/ai_service/channel_session_trial.py','apps/qq_bot/session_run_trial.py',
        'apps/qq_bot/session_run_trial_cli.py','scripts/dev/Test-QQConversation.ps1',
        'scripts/dev/qq_bot_test_common.ps1','apps/qq_bot/configuration.py',
        'apps/ai_service/runtime/locations.py','apps/ai_backend/credentials.py','apps/ai_backend/secure_files.py')
    return dict(contract=CONTRACT,environment='EXPLICIT_PROCESS_OPERATOR_TRIAL',
        runtime=base['runtime'],sdk=base['sdk'],transport=base['transport'],cost=base['cost'],
        execution=base['execution'],conversation=base['conversation'],history=base['history'],
        commit=base['commit'],presentation=base['presentation'],process=base['process'],
        approval={'type':'RunAuthorization','binding':'PROCESS_NONCE_AND_RUN_LEDGER',
            'operator':'LOCAL_UNAUTHENTICATED','old_approvals':'REJECT','resume':False,
            'consents':'PROVIDER_QQ_SCOPE_COST_SOURCE_HISTORY_SDK_RISK@1'},
        implementation=base['implementation'],entry_implementation={
            p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths})


def prepared_scope(options):
    from apps.ai_backend.tools import ToolDefinition,ToolRegistry
    from apps.ai_backend.tools.policy import ToolPolicy
    from .business_tools.current_water_quality import WATER_DEFINITION
    return trial_scope(assistant_profile(PRESET),ToolPolicy('assistant',True,('get_current_water_quality',)),
        ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),)),options)


def preparation_record(scope):
    return dict(schema_version=1,contract=CONTRACT,status='candidate',qualification_id=None,
        scope=scope,scope_sha256=_hash(scope),real_execution_requires='PROCESS_OPERATOR_RUNCONSENT',
        old_single_or_two_turn_approvals=False)


def check_preparation(value,scope):
    if value!=preparation_record(scope):raise GatewayError('SESSION_TRIAL_SCOPE_REVIEW_REQUIRED')


class SessionTrialQwenTurn(SessionQwenTurn):
    """Distinct typed live-path grant; original TrialQwenAdapter owns all SDK I/O."""
    release_status='local_experimental'

    def __init__(self,lease,*,run_authorization,authority,conversation_epoch,options,snapshot,
                 validate,claim,async_client_factory=None,clock=None,monotonic=None):
        if type(run_authorization) is not RunAuthorization or type(lease) is not TurnLease:
            raise GatewayError('SESSION_TRIAL_RUN_AUTHORIZATION_REQUIRED')
        run_authorization.authority.validate(run_authorization);lease.authority.validate(lease)
        if (lease.scope_sha256!=run_authorization.scope_sha256
                or lease.authority is not run_authorization.lease_authority
                or lease.bindings_sha256!=run_authorization.bindings_sha256
                or not lease.approval_id.startswith(run_authorization.consent_id+'-')):
            raise GatewayError('SESSION_TRIAL_LEASE_BINDING_CHANGED')
        if snapshot.identity[:5]!=(lease.app_id,lease.group_id,lease.member_id,lease.instance_id,lease.device_id):
            raise GatewayError('SESSION_TRIAL_HISTORY_IDENTITY_CHANGED')
        self.run_authorization=run_authorization
        self.authority,self.conversation_epoch=authority,conversation_epoch
        self.options,self.snapshot=options,snapshot
        def check():
            run_authorization.authority.validate(run_authorization);validate()
        kwargs={} if monotonic is None else {'monotonic':monotonic}
        factory=memory_sdk_factory(async_client_factory) if async_client_factory is not None else None
        self._initialize(lease,validate=check,claim=claim,async_client_factory=factory,clock=clock,**kwargs)

    def history_decision(self,profile,policy,registry,authorization,snapshot,*,epoch,policy_revision):
        self.check();self.approval.authority.validate(self.approval)
        digest=_hash(trial_scope(profile,policy,registry,self.options))
        return self._bound_history_decision(profile,policy,registry,authorization,snapshot,
            epoch=epoch,policy_revision=policy_revision,digest=digest,reason='EXPLICIT_PROCESS_RUNCONSENT')

