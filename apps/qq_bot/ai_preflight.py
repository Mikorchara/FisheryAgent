"""No secrets, instances or network: inspect the maintained real-trial candidate."""
import json
from pathlib import Path

from apps.ai_backend.tools import ToolDefinition, ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_service.business_tools.current_water_quality import WATER_DEFINITION, CURRENT_WATER_QUALITY
from apps.ai_service.channel_scope import monitoring_trial_scope, check_candidate
from apps.ai_service.runtime.assistant import assistant_profile
from .ai_configuration import PRESET


def prepared_scope():
    def no_data():raise RuntimeError('PREFLIGHT_HAS_NO_DATA_BINDING')
    registry=ToolRegistry((ToolDefinition(WATER_DEFINITION,no_data),))
    policy=ToolPolicy('assistant',True,(CURRENT_WATER_QUALITY,))
    return monitoring_trial_scope(assistant_profile(PRESET),policy,registry)


def readiness_report():
    path=Path(__file__).parents[1]/'ai_service/resources/qq_monitoring_trial.json'
    value=json.loads(path.read_text(encoding='utf-8'))
    scope=prepared_scope();checked=check_candidate(value,scope)
    return dict(code='QQ_AI_PREFLIGHT_VALID_LIVE_BLOCKED',**checked,ai_enabled=False,
        provider_plan={'preset_id':scope['runtime']['preset_id'],'identity':scope['runtime']['identity'],
            'budget':scope['execution']['budget'],'max_model_requests':2,'retries':0},
        blockers=['REAL_TRIAL_APPROVAL_REQUIRED','PROVIDER_AND_COST_CONSENT_REQUIRED',
            'INSTANCE_AND_QQ_DISCLOSURE_CONSENT_REQUIRED','LIVE_SERVICE_AND_DELIVERY_NOT_COMPOSED',
            'SDK_HARD_THREAD_EXIT_NOT_GUARANTEED'],
        credential_checked=False,management_policy_checked=False,business_instance_opened=False,network_requests=0)
