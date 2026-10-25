"""Local operator plans and one-use approvals; never accepts configuration from QQ."""
from dataclasses import asdict,dataclass
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
import threading
from pathlib import Path
import uuid

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.secure_files import guard_path
from apps.ai_backend.tools import ToolDefinition,ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_service.business_tools.current_water_quality import WATER_DEFINITION,CURRENT_WATER_QUALITY
from apps.ai_service.channel import ChannelBudget
from apps.ai_service.channel_trial import (QwenTrialApproval,TRIAL_CONTRACT,PRESET,PRICE_URL,
    cost_reservation,fast_trial_scope,money)
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from apps.ai_service.runtime.policy import UserToolPolicyStore
from apps.ai_service.management_policy import ManagementToolPolicyStore
from .ai_configuration import load_ai_config
from .configuration import json_object,load_access
from .contracts import BotError,identifier
from .monitoring_source import InstanceMonitoring,load_monitoring_config


def local_path(value):
    path=Path(value)
    if not path.is_absolute() or path.anchor.startswith(('\\\\','//')) or '..' in path.parts:
        raise BotError('TRIAL_LOCAL_ABSOLUTE_PATH_REQUIRED')
    if os.name=='nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor))!=3:
            raise BotError('TRIAL_LOCAL_DISK_REQUIRED')
    guard_path(path)
    return path


def read_json(path):
    path=local_path(path);guard_path(path,regular=True)
    try:
        with path.open('rb') as stream:return json_object(stream.read(65537),65536)
    except BotError:raise
    except Exception:raise BotError('TRIAL_RECORD_UNAVAILABLE') from None


def write_new(path,value):
    path=local_path(path);guard_path(path,regular=True)
    # Parent must already exist. Never repair, replace, merge or truncate a file.
    try:
        with path.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
    except FileExistsError:raise BotError('TRIAL_OUTPUT_EXISTS') from None


def scope():
    registry=ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),))
    policy=ToolPolicy('assistant',True,(CURRENT_WATER_QUALITY,))
    return fast_trial_scope(assistant_profile(PRESET),policy,registry)


@dataclass(frozen=True,repr=False)
class TrialInputs:
    access_file: Path
    monitoring_config: Path
    ai_config: Path
    policy_directory: Path
    group_id: str
    member_id: str

    def dictionary(self):
        return {k:str(v) for k,v in asdict(self).items()}

    @classmethod
    def parse(cls,value):
        if not isinstance(value,dict) or set(value)!={'access_file','monitoring_config','ai_config',
                'policy_directory','group_id','member_id'}:raise BotError('INVALID_TRIAL_INPUTS')
        return cls(*(local_path(value[k]) for k in ('access_file','monitoring_config','ai_config','policy_directory')),
            identifier(value['group_id']),identifier(value['member_id']))


def inputs_snapshot(inputs,monitoring=None):
    access=load_access(inputs.access_file);ai=load_ai_config(inputs.ai_config)
    source_config=load_monitoring_config(inputs.monitoring_config);source_config.check_bindings(access)
    if not ai.enabled:raise BotError('AI_DISABLED')
    if ai.budget!=ChannelBudget():raise BotError('TRIAL_FIXED_BUDGET_REQUIRED')
    group=next((g for g in access.groups if g.group_id==inputs.group_id),None)
    grant=next((g for g in ai.grants if g.group_id==inputs.group_id),None)
    if (group is None or grant is None or inputs.member_id not in group.members
            or inputs.member_id not in grant.members or group.device_id!=grant.device_id
            or 'current' not in group.capabilities or grant.device_id not in source_config.devices):
        raise BotError('TRIAL_MEMBER_NOT_APPROVED')
    registry=ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),))
    shared=UserToolPolicyStore(inputs.policy_directory,registry)
    policy=ManagementToolPolicyStore(inputs.policy_directory,shared).snapshot()
    if CURRENT_WATER_QUALITY not in policy.selected_tools:raise BotError('CHANNEL_TOOL_NOT_AUTHORIZED')
    if monitoring is not None and monitoring.config!=source_config:raise BotError('TRIAL_BINDINGS_CHANGED')
    bindings=dict(inputs=inputs.dictionary(),access=asdict(access),ai=asdict(ai),
        source={'instance_id':source_config.instance_id,'root':str(source_config.data_root),
                'devices':source_config.devices},policy_revision=policy.revision,
        binding_revision=monitoring.binding_revision if monitoring is not None else None)
    paths=(inputs.access_file,inputs.ai_config,inputs.monitoring_config,
        inputs.policy_directory/'management_assistant_policy.json',inputs.policy_directory/'tool_policies.json')
    bindings['config_files']={str(p):[p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns]
        if p.exists() else None for p in paths}
    return access,ai,source_config,grant,_hash(bindings)


def prerequisite_valid(value,expected_scope,bindings):
    if (not isinstance(value,dict) or value.get('contract')!=TRIAL_CONTRACT
            or value.get('code')!='QWEN_PROVIDER_TRIAL_VERIFIED' or value.get('offline_test') is not False
            or value.get('scope_sha256')!=expected_scope or value.get('bindings_sha256')!=bindings
            or value.get('completed') is not True or value.get('model_requests')!=2
            or value.get('model_text_displayed') is not False
            or value.get('sdk_resources',{}).get('state')!='CLOSED'
            or value.get('sdk_resources',{}).get('thread_exited') is not True
            or value.get('sdk_resources',{}).get('local_io_closed') is not True
            or value.get('sdk_resources',{}).get('cleanup_error') is not None):
        raise BotError('TRIAL_PROVIDER_PREREQUISITE_REQUIRED')
    return _hash(value)


def make_plan(inputs,*,phase,max_cost_cny,minutes=10,prerequisite=None,clock=None):
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    if phase not in ('provider','qq') or type(minutes) is not int or not 1<=minutes<=30:
        raise BotError('INVALID_TRIAL_PLAN')
    if money(max_cost_cny)<cost_reservation():raise BotError('TRIAL_COST_RESERVATION_INSUFFICIENT')
    access,ai,config,grant,_=inputs_snapshot(inputs)
    monitoring=InstanceMonitoring(config,clock=clock)
    access,ai,config,grant,bindings=inputs_snapshot(inputs,monitoring)
    capture=monitoring.capture_water(grant.device_id)
    ref=capture.analysis.observation
    if ref is not None and ref.source_kind!='simulator':raise BotError('TRIAL_SOURCE_NOT_APPROVED')
    current_scope=scope();scope_hash=_hash(current_scope)
    required=None
    if phase=='qq':
        if prerequisite is None:raise BotError('TRIAL_PROVIDER_PREREQUISITE_REQUIRED')
        path=local_path(prerequisite)
        required={'path':str(path),'sha256':prerequisite_valid(read_json(path),scope_hash,bindings)}
    elif prerequisite is not None:raise BotError('INVALID_TRIAL_PLAN')
    return dict(schema_version=1,contract=TRIAL_CONTRACT,status='pending_operator_approval',
        phase=phase,created_at=now.isoformat(),expires_at=(now+timedelta(minutes=minutes)).isoformat(),
        inputs=inputs.dictionary(),scope=current_scope,scope_sha256=scope_hash,bindings_sha256=bindings,
        instance_id=config.instance_id,device_id=grant.device_id,app_id=access.app_id,
        max_cost_cny=max_cost_cny,price_reviewed_at=now.isoformat(),pricing_region='cn-beijing',
        prerequisite=required,qualification_id=None)


_PLAN_KEYS={'schema_version','contract','status','phase','created_at','expires_at','inputs','scope',
    'scope_sha256','bindings_sha256','instance_id','device_id','app_id','max_cost_cny','price_reviewed_at',
    'pricing_region','prerequisite','qualification_id'}
_CONSENTS={'provider_and_cost','simulator_data_disclosure','sdk_thread_hard_exit_risk',
    'beijing_price_and_context_confirmed','local_operator_only'}


def validate_record(value,*,approved=False,clock=None):
    try:
        expected=_PLAN_KEYS|({'approval_id','approved_at','consents'} if approved else set())
        if (set(value)!=expected or type(value['schema_version']) is not int or value['schema_version']!=1
                or value['contract']!=TRIAL_CONTRACT or value['qualification_id'] is not None
                or value['status']!=('local_experimental' if approved else 'pending_operator_approval')
                or value['pricing_region']!='cn-beijing'):raise ValueError()
        # One fresh snapshot for this validation. Comparing value and digest does
        # not require rereading every source/SDK file twice. Never cache across
        # checks: same-size/mtime edits must still invalidate the next boundary.
        current_scope=scope()
        if value['scope']!=current_scope or value['scope_sha256']!=_hash(current_scope):raise ValueError()
        now=(clock or (lambda:datetime.now(timezone.utc)))()
        created=datetime.fromisoformat(value['created_at']);expires=datetime.fromisoformat(value['expires_at'])
        price=datetime.fromisoformat(value['price_reviewed_at'])
        if (any(t.tzinfo is None for t in (created,expires,price)) or not created<=now<expires
                or not timedelta(0)<expires-created<=timedelta(minutes=30)
                or not timedelta(0)<=now-price<=timedelta(hours=24)):
            raise BotError('TRIAL_APPROVAL_EXPIRED')
        if approved:
            if (set(value['consents'])!=_CONSENTS or any(v is not True for v in value['consents'].values())
                    or not created<=datetime.fromisoformat(value['approved_at'])<=now):raise ValueError()
        if value['phase'] not in ('provider','qq') or money(value['max_cost_cny'])<cost_reservation():raise ValueError()
        return TrialInputs.parse(value['inputs'])
    except (BotError,GatewayError):raise
    except Exception:raise BotError('INVALID_TRIAL_APPROVAL' if approved else 'INVALID_TRIAL_PLAN') from None


def approve_plan(plan,*,clock=None):
    validate_record(plan,clock=clock)
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    return {**plan,'status':'local_experimental','approval_id':uuid.uuid4().hex,
        'approved_at':now.isoformat(),'consents':{k:True for k in sorted(_CONSENTS)}}


class ApprovalFile:
    def __init__(self,path,expected_sha256,*,clock=None):
        self.path=local_path(path);self.clock=clock
        self.value=read_json(self.path);self.digest=_hash(self.value)
        if self.digest!=expected_sha256:raise BotError('TRIAL_APPROVAL_DIGEST_MISMATCH')
        self.inputs=validate_record(self.value,approved=True,clock=clock)
        # Stable across renamed/copied approval files: the approved AI config
        # directory + approval identity owns consumption, not this file's name.
        self.marker=self.inputs.ai_config.parent/('.qwen-trial-'+self.value['approval_id']+'.used')
        self.claimed=False
        self._lock=threading.RLock()

    def check(self):
        with self._lock:self._check()

    def _check(self):
        if _hash(read_json(self.path))!=self.digest:raise BotError('TRIAL_APPROVAL_CHANGED')
        validate_record(self.value,approved=True,clock=self.clock)
        guard_path(self.marker,regular=True)
        if self.marker.exists() and not self.claimed:raise BotError('TRIAL_ALREADY_USED')
        if self.claimed:
            value=read_json(self.marker)
            if value!={'approval_sha256':self.digest}:raise BotError('TRIAL_CONSUMPTION_CHANGED')

    def claim(self):
        with self._lock:
            self._check()
            if self.claimed:raise BotError('TRIAL_ALREADY_USED')
            try:write_new(self.marker,{'approval_sha256':self.digest})
            except BotError as error:
                if error.code=='TRIAL_OUTPUT_EXISTS':raise BotError('TRIAL_ALREADY_USED') from None
                raise
            self.claimed=True

    def grant(self):
        v=self.value
        return QwenTrialApproval(v['approval_id'],v['phase'],v['scope_sha256'],v['bindings_sha256'],
            datetime.fromisoformat(v['expires_at']),v['max_cost_cny'],v['instance_id'],v['device_id'],
            v['app_id'],v['inputs']['group_id'],v['inputs']['member_id'])
