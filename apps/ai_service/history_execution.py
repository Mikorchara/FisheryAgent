"""Exact history-only local trial; user authorization never grants publication."""

from dataclasses import dataclass, asdict
import json
from pathlib import Path

from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION, TRANSCRIPT_NOTICE
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode, ToolModelTransport
from apps.ai_backend.tools.policy import ToolPolicy
from apps.monitoring.history import (HISTORY_VERSION, MAX_HISTORY_ROWS, MAX_HISTORY_ITEMS,
                                     MAX_HISTORY_RESULT_BYTES)
from .business_tools.water_quality_history import WATER_QUALITY_HISTORY
from .execution import ExecutionDecision
from .runtime.assistant import SYSTEM_INSTRUCTION, SINGLE_ROUND_PROMPT_ID
from .runtime.release_contracts import release_scope, _hash, _json, AssistantExecutionProfile
from .runtime.sources import SourceRequirement, HISTORY_SOURCE_CONTRACT_VERSION

HISTORY_PROFILE = 'water_history_candidate@2'
HISTORY_MAX_OUTPUT_TOKENS = 1024


def validate_history_token_budget(value, *, streaming=False):
    """Only the history Normal candidate; other qualification ceilings are unchanged."""
    if streaming is not False or type(value) is not int or not 1 <= value <= HISTORY_MAX_OUTPUT_TOKENS:
        raise GatewayError('INVALID_HISTORY_TOKEN_BUDGET')


def history_scope(profile, registry):
    policy = ToolPolicy('assistant', True, (WATER_QUALITY_HISTORY,))
    runtime = release_scope(profile, policy, registry, DEFAULT_HISTORY_PROJECTION)
    runtime.update(prompt_id=SINGLE_ROUND_PROMPT_ID, prompt_sha256=_hash(SYSTEM_INSTRUCTION))
    return {'runtime':runtime, 'transport':'NORMAL',
            'history_framing_sha256':_hash(TRANSCRIPT_NOTICE),
            'generation':asdict(profile.default_generation),
            'data_binding':{'version':HISTORY_VERSION, 'device':'FROZEN_PER_TURN',
                'max_rows':MAX_HISTORY_ROWS, 'max_items':MAX_HISTORY_ITEMS,
                'max_result_bytes':MAX_HISTORY_RESULT_BYTES},
            'source_version':HISTORY_SOURCE_CONTRACT_VERSION,
            'requirement':SourceRequirement.HISTORICAL_WATER_QUERY.value,
            'budget':{'calls':1, 'rounds':1, 'requests':2, 'retry':profile.max_retries,
                      'deadline_s':profile.total_timeout_s,
                      'max_output_tokens':HISTORY_MAX_OUTPUT_TOKENS}}


@dataclass(frozen=True)
class HistoryCandidateConfig:
    scope_json: str
    status: str = 'candidate'
    enabled: bool = False

    def __post_init__(self):
        try:
            if (self.status not in ('candidate', 'local_experimental') or type(self.enabled) is not bool
                    or self.status == 'candidate' and self.enabled):
                raise ValueError()
            object.__setattr__(self, 'scope_json', _json(json.loads(self.scope_json)))
        except (ValueError, TypeError, RecursionError):
            raise GatewayError('INVALID_HISTORY_CANDIDATE_CONFIG') from None


def load_history_config(*, enable_trial=False):
    if type(enable_trial) is not bool:
        raise GatewayError('INVALID_HISTORY_CANDIDATE_CONFIG')
    try:
        path = Path(__file__).with_name('resources')/'water_history_candidate.json'
        value = json.loads(path.read_bytes() if path.stat().st_size <= 16384 else b'')
        if set(value) != {'scope','status','enabled'} or value['enabled'] is not False:
            raise ValueError()
        config = HistoryCandidateConfig(_json(value['scope']), value['status'])
        return HistoryCandidateConfig(config.scope_json, config.status, True) if enable_trial else config
    except (OSError, ValueError, TypeError, RecursionError):
        raise GatewayError('INVALID_HISTORY_CANDIDATE_CONFIG') from None


def resolve_history_candidate(config, profile, selected, registry, *, device_id, epoch, policy_revision,
                              transport=ToolModelTransport.NORMAL):
    scope = history_scope(profile, registry)
    matched = (profile.preset_id == 'dashscope-qwen38-flash-r1'
        and scope['runtime']['thinking'] == 'off' and transport == ToolModelTransport.NORMAL
        and scope['budget'] == {'calls':1,'rounds':1,'requests':2,'retry':0,'deadline_s':120,
                               'max_output_tokens':HISTORY_MAX_OUTPUT_TOKENS}
        and _json(scope) == config.scope_json)
    authorized = WATER_QUALITY_HISTORY in selected.exposed_tools
    reason = ('HISTORY_CANDIDATE_SCOPE_MISMATCH' if not matched else
              'HISTORY_TOOL_NOT_AUTHORIZED' if not authorized else
              'HISTORY_CANDIDATE_NOT_RELEASED' if config.status == 'candidate' else
              'HISTORY_TRIAL_DISABLED' if not config.enabled else 'HISTORY_LOCAL_EXPERIMENTAL')
    revision = _hash({'profile':HISTORY_PROFILE, 'scope':scope, 'config':asdict(config),
        'device_id':device_id, 'epoch':epoch, 'policy_revision':policy_revision})
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.SINGLE_ROUND,
                             revision, config.status, reason),
                             matched and authorized and config.status == 'local_experimental' and config.enabled,
                             max_output_tokens=HISTORY_MAX_OUTPUT_TOKENS)
