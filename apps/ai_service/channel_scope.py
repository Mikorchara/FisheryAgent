"""Pure Monitoring-only real-trial scope preparation, without execution permission."""
from dataclasses import asdict
from importlib.metadata import version
import hashlib
from pathlib import Path

from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.sdk_resources import RESOURCE_CONTRACT
from .business_tools.current_water_quality import CURRENT_WATER_QUALITY, WATER_TOOL_PROJECTION
from .channel import ChannelBudget
from .channel_presentation import PRESENTATION_CONTRACT
from .runtime.assistant import SINGLE_ROUND_PROMPT_ID, SYSTEM_INSTRUCTION
from .runtime.release_contracts import _hash, release_scope


def monitoring_trial_scope(profile,policy,registry,*,budget=ChannelBudget()):
    if (registry.registered_names()!=(CURRENT_WATER_QUALITY,)
            or policy.exposed_tools!=(CURRENT_WATER_QUALITY,) or profile.max_retries!=0
            or profile.default_response_mode!='normal' or profile.default_reasoning.mode.value!='off'):
        raise GatewayError('INVALID_QQ_MONITORING_TRIAL_SCOPE')
    runtime=release_scope(profile,policy,registry,DEFAULT_HISTORY_PROJECTION)
    runtime.update(prompt_id=SINGLE_ROUND_PROMPT_ID,prompt_sha256=_hash(SYSTEM_INSTRUCTION))
    adapter=Path(__file__).parents[1]/'ai_backend/openai_compatible_adapter.py'
    resources=adapter.with_name('sdk_resources.py')
    execution=adapter.with_name('execution.py')
    return dict(contract='qq-monitoring-normal-trial@2',runtime=runtime,
        data_bindings={'water':WATER_TOOL_PROJECTION,'knowledge':None,'sources':['simulator']},
        execution={'mode':'SINGLE_ROUND','model_requests':2,'tool_calls':1,'tool_rounds':1,
            'history':False,'streaming':False,'retries':0,'budget':asdict(budget),
            'provider_timeouts_s':[profile.connect_timeout_s,profile.read_timeout_s,profile.total_timeout_s]},
        provider={'credential_ref':profile.credential_ref,'auth':profile.auth_spec.value},
        backend={'adapter':'apps.ai_backend.openai_compatible_adapter.OpenAICompatibleAdapter',
            'adapter_sha256':hashlib.sha256(adapter.read_bytes()).hexdigest(),
            'resource_contract':RESOURCE_CONTRACT,
            'resources_sha256':hashlib.sha256(resources.read_bytes()).hexdigest(),
            'execution_sha256':hashlib.sha256(execution.read_bytes()).hexdigest(),
            'openai_version':version('openai'),'httpx_version':version('httpx')},
        source_requirement='CURRENT_OBSERVATION_QUERY',presentation=PRESENTATION_CONTRACT)


def candidate_record(scope):
    return dict(schema_version=1,release_id='qq-monitoring-normal-trial-v2',status='candidate',
        scope=scope,scope_sha256=_hash(scope),qualification_id=None,validated_at=None,trial_approval_id=None)


def check_candidate(value,scope):
    # Candidate preparation is deliberately not a local_experimental approval
    # loader. Existing three-tool/Knowledge records cannot match this contract.
    expected=candidate_record(scope)
    if _hash(value)!=_hash(expected):raise GatewayError('QQ_TRIAL_SCOPE_REVIEW_REQUIRED')
    return {'scope_matches':True,'status':'candidate','can_execute_real':False,'can_deliver_real':False,
            'scope_sha256':expected['scope_sha256']}
