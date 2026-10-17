"""Frozen Normal candidate and separately approved, startup-frozen local trials."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from apps.ai_backend.history_projection import TRANSCRIPT_NOTICE
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode, ToolModelTransport
from apps.ai_backend.tools.policy import ToolPolicy
from apps.monitoring.history import HISTORY_VERSION, MAX_HISTORY_ROWS, MAX_HISTORY_ITEMS, MAX_HISTORY_RESULT_BYTES
from .business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES
from .execution import management_scope, ExecutionDecision
from .runtime.release_contracts import AssistantExecutionProfile, _hash, _json
from .runtime.sources import HISTORY_SOURCE_CONTRACT_VERSION
from .runtime.streaming_contracts import streaming_scope

NORMAL_SELECTION_CANDIDATE = 'management-normal-three-tools@1'
UNIFIED_PRESET = 'dashscope-qwen38-flash-r1'
# Explicit subsets of the approved three-Tool ceiling. The original exact
# Water+Knowledge pair retains its existing release and budget in Service.
WATER, KNOWLEDGE, HISTORY = HISTORY_CANDIDATE_TOOL_NAMES
UNIFIED_TOOL_SETS = ((), (WATER,), (KNOWLEDGE,), (HISTORY,), (WATER,KNOWLEDGE),
                    (WATER,HISTORY), (KNOWLEDGE,HISTORY), HISTORY_CANDIDATE_TOOL_NAMES)


def normal_selection_scope(profile, registry, knowledge):
    policy = ToolPolicy('assistant', True, HISTORY_CANDIDATE_TOOL_NAMES)
    return {**management_scope(profile, policy, registry, knowledge),
        'transport': 'NORMAL', 'history_framing_sha256': _hash(TRANSCRIPT_NOTICE),
        'generation': asdict(profile.default_generation),
        'history_binding': {'version': HISTORY_VERSION, 'device': 'FROZEN_PER_TURN',
            'max_rows': MAX_HISTORY_ROWS, 'max_items': MAX_HISTORY_ITEMS,
            'max_result_bytes': MAX_HISTORY_RESULT_BYTES, 'source_version': HISTORY_SOURCE_CONTRACT_VERSION},
        'budget': {'calls': 2, 'rounds': 2, 'requests': 3, 'retry': profile.max_retries,
                   'deadline_s': profile.total_timeout_s, 'max_output_tokens': 1024}}


def streaming_selection_scope(profile, registry, knowledge):
    scope = normal_selection_scope(profile,registry,knowledge)
    scope['runtime'] = streaming_scope(profile,ToolPolicy('assistant',True,HISTORY_CANDIDATE_TOOL_NAMES),
                                       registry,DEFAULT_HISTORY_PROJECTION)
    scope['transport'] = 'STREAMING'
    scope['budget'] = {**scope['budget'],'max_output_tokens':512}
    return scope


@dataclass(frozen=True)
class UnifiedToolTrials:
    normal_scope_json: str
    streaming_scope_json: str
    normal_enabled: bool = False
    streaming_enabled: bool = False

    def __post_init__(self):
        if type(self.normal_enabled) is not bool or type(self.streaming_enabled) is not bool:
            raise GatewayError('INVALID_UNIFIED_TOOL_TRIAL_CONFIG')
        for key in ('normal_scope_json','streaming_scope_json'):
            try:
                value=json.loads(getattr(self,key))
                if not isinstance(value,dict):raise ValueError()
                object.__setattr__(self,key,_json(value))
            except (ValueError,TypeError,RecursionError):
                raise GatewayError('INVALID_UNIFIED_TOOL_TRIAL_CONFIG') from None


def load_unified_tool_trials(*, normal=False, streaming=False):
    """Local approval only; no qualification id, file writes or browser switch."""
    try:
        path=Path(__file__).with_name('resources')/'assistant_unified_tools.json'
        value=json.loads(path.read_bytes() if path.stat().st_size<=32768 else b'')
        if (set(value)!={'schema_version','status','enabled','normal_scope','streaming_scope',
                        'authorized_tool_sets','qualification_id','validated_at'}
                or type(value['schema_version']) is not int or value['schema_version']!=1
                or value['status']!='local_experimental' or value['enabled'] is not False
                or value['qualification_id'] is not None or value['validated_at'] is not None
                or value['authorized_tool_sets']!=[list(names) for names in UNIFIED_TOOL_SETS]
                or _json(value['normal_scope'])!=load_normal_selection_candidate()):
            raise ValueError()
        return UnifiedToolTrials(_json(value['normal_scope']),_json(value['streaming_scope']),normal,streaming)
    except (OSError,ValueError,TypeError,RecursionError):
        raise GatewayError('INVALID_UNIFIED_TOOL_TRIAL_CONFIG') from None


def resolve_unified_tools(config,profile,policy,registry,knowledge,*,device_id,epoch,policy_revision,transport):
    streaming=transport==ToolModelTransport.STREAMING
    scope=(streaming_selection_scope if streaming else normal_selection_scope)(profile,registry,knowledge)
    pinned=config.streaming_scope_json if streaming else config.normal_scope_json
    matched=(profile.preset_id==UNIFIED_PRESET and _json(scope)==pinned
             and policy.exposed_tools in UNIFIED_TOOL_SETS)
    enabled=config.streaming_enabled if streaming else config.normal_enabled
    reason='active' if matched and enabled else 'flag_disabled' if not enabled else 'scope_not_published'
    # The pinned scope is a three-definition ceiling; the explicitly listed
    # subsets are a separate Policy intersection. Bind the actual subset too.
    revision=_hash({'release':'management-unified-tools@1','scope':scope,'config':asdict(config),
        'effective_tools':list(policy.exposed_tools),'device_id':device_id,'epoch':epoch,
        'policy_revision':policy_revision})
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND,
        revision,'local_experimental',reason),matched and enabled,transport,512 if streaming else 1024)


def load_normal_selection_candidate():
    """Fixed maintainer plan, not an enable switch or a Web-controlled file path."""
    try:
        path = Path(__file__).with_name('resources') / 'assistant_normal_candidate.json'
        value = json.loads(path.read_bytes() if path.stat().st_size <= 16384 else b'')
        if (set(value) != {'scope', 'status', 'enabled'} or value['status'] != 'candidate'
                or value['enabled'] is not False or not isinstance(value['scope'], dict)):
            raise ValueError()
        return _json(value['scope'])
    except (OSError, ValueError, TypeError, RecursionError):
        raise GatewayError('INVALID_NORMAL_TOOL_CANDIDATE') from None


def resolve_normal_selection_candidate(profile, selected, registry, knowledge, *, device_id, epoch,
                                        policy_revision, transport=ToolModelTransport.NORMAL):
    scope = normal_selection_scope(profile, registry, knowledge)
    matched = (transport == ToolModelTransport.NORMAL and scope['runtime']['thinking'] == 'off'
        and scope['budget']['retry'] == 0 and scope['budget']['deadline_s'] == 120
        and _json(scope) == load_normal_selection_candidate())
    authorized = set(selected.exposed_tools) == set(HISTORY_CANDIDATE_TOOL_NAMES)
    reason = ('NORMAL_TOOL_CANDIDATE_SCOPE_MISMATCH' if not matched else
              'NORMAL_TOOL_CANDIDATE_NOT_AUTHORIZED' if not authorized else
              'NORMAL_TOOL_CANDIDATE_NOT_RELEASED')
    revision = _hash({'candidate': NORMAL_SELECTION_CANDIDATE, 'scope': scope,
                     'device_id': device_id, 'epoch': epoch, 'policy_revision': policy_revision})
    # Offline qualification may explicitly stub admission. Product cannot enable it.
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND,
        revision, 'candidate', reason), False, max_output_tokens=1024)
