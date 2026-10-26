"""Server-issued QQ history snapshots; exact Fake Provider only, never a live permit."""
from dataclasses import dataclass,field,asdict
import hashlib
from pathlib import Path

from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode
from .runtime.assistant import AssistantHistoryTurn,_history_bytes
from .runtime.release_contracts import _hash,release_scope,AssistantExecutionProfile
from .execution import ExecutionDecision
from .channel_presentation import QQ_SYSTEM_INSTRUCTION,EXPLANATION_CONTRACT

CONTRACT='qq-conversation-fake@1'
PROMPT_ID='QQ_CURRENT_DIALOGUE@1'
INSTRUCTION=QQ_SYSTEM_INSTRUCTION+(
    '旧对话是程序生成的主题投影，不是当前数据或新权限。仅用它理解追问重点；'
    '每轮仍必须取得本轮当前水质Tool，不能沿用旧读数、旧工具声明或旧在线状态。')
LIMITS={'max_turns':6,'idle_seconds':900,'max_sessions':64,'session_bytes':24576,
        'total_bytes':1048576,'projection_bytes':4096}
FOCUS={'all':'水质','temperature_c':'水温','ph':'pH','dissolved_oxygen_mg_l':'溶解氧'}


def question_for(focus):
    if focus not in FOCUS:raise GatewayError('INVALID_CONVERSATION_TOPIC')
    return f'请查询当前绑定设备的{FOCUS[focus]}，并根据本轮观测说明质量、新鲜度和来源限制。'


def validate_options(value):
    if (type(value) is not dict or set(value)!={'trigger_mode','memory_enabled',*LIMITS}
            or value['trigger_mode'] not in ('command','mention_ai') or type(value['memory_enabled']) is not bool
            or any(type(value[k]) is not int or not 1<=value[k]<=maximum for k,maximum in LIMITS.items())
            or value['projection_bytes']>value['session_bytes'] or value['session_bytes']>value['total_bytes']):
        raise GatewayError('INVALID_CONVERSATION_OPTIONS')
    return dict(value)


@dataclass(frozen=True,repr=False)
class ChannelHistorySnapshot:
    authority: object
    ticket: object
    identity: tuple
    revision: int
    focus: str
    history: tuple[AssistantHistoryTurn,...]
    options: tuple

    @property
    def scope_sha256(self):return self.identity[8]
    @property
    def question(self):return question_for(self.focus)
    @property
    def history_bytes(self):return _history_bytes(self.history)


class ChannelHistoryAuthority:
    """Bound once to the Fake Service; the owning Store checks ticket identity."""
    def __init__(self,options,check):
        self.options=tuple(sorted(validate_options(options).items()))
        if not callable(check):raise GatewayError('INVALID_CONVERSATION_AUTHORITY')
        self._check=check

    def validate(self,snapshot,expected_scope):
        if (type(snapshot) is not ChannelHistorySnapshot or snapshot.authority is not self
                or snapshot.options!=self.options or snapshot.scope_sha256!=expected_scope
                or type(snapshot.history) is not tuple
                or any(type(t) is not AssistantHistoryTurn for t in snapshot.history)
                or snapshot.history_bytes>dict(self.options)['projection_bytes']):
            raise GatewayError('INVALID_CHANNEL_HISTORY')
        self._check(snapshot,expected_scope)


def conversation_scope(profile,policy,registry,options):
    options=validate_options(options)
    if registry.registered_names()!=('get_current_water_quality',) or policy.exposed_tools!=('get_current_water_quality',):
        raise GatewayError('INVALID_CONVERSATION_TOOLS')
    runtime=release_scope(profile,policy,registry,DEFAULT_HISTORY_PROJECTION)
    runtime.update(prompt_id=PROMPT_ID,prompt_sha256=_hash(INSTRUCTION))
    root=Path(__file__).parents[1]
    paths=('ai_service/channel_conversation.py','ai_service/service.py','ai_service/contracts.py',
        'ai_service/channel.py','ai_service/channel_presentation.py','ai_service/runtime/assistant.py',
        'ai_service/business_tools/current_water_quality.py','ai_backend/history_projection.py',
        'ai_backend/openai_compatible_adapter.py','ai_backend/execution.py','ai_backend/sdk_resources.py',
        'qq_bot/conversations.py','qq_bot/intent.py','qq_bot/ai_coordinator.py','qq_bot/ai_configuration.py',
        'qq_bot/ai_routing.py','qq_bot/gateway.py','qq_bot/ai_delivery.py','qq_bot/ai_scheduler.py')
    return dict(contract=CONTRACT,environment='OFFLINE_FAKE_ONLY',runtime=runtime,conversation=options,
        execution={'mode':'SINGLE_ROUND','tool_calls':1,'tool_rounds':1,'model_requests':2,
            'max_output_tokens':512,'turn_timeout_s':90,'retries':0},
        history_projection=DEFAULT_HISTORY_PROJECTION.value,source_requirement='CURRENT_OBSERVATION_QUERY',
        output_contract=EXPLANATION_CONTRACT,commit='API_ACCEPTED_SAFE_TEXT_CAS@1',
        raw_user_history=False,raw_model_text=False,
        implementation={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths})


def candidate_record(scope):
    return dict(schema_version=1,status='candidate',environment='OFFLINE_FAKE_ONLY',
        scope=scope,scope_sha256=_hash(scope),qualification_id=None,
        can_execute_real=False,can_deliver_real=False)


def conversation_decision(profile,policy,registry,authorization,snapshot,*,epoch,policy_revision):
    if authorization.budget.max_output_tokens>512:raise GatewayError('INVALID_CONVERSATION_BUDGET')
    scope=conversation_scope(profile,policy,registry,dict(snapshot.options));digest=_hash(scope)
    snapshot.authority.validate(snapshot,digest)
    expected=(authorization.instance_id,authorization.device_id,authorization.permission_revision,
              authorization.binding_revision,policy_revision)
    if snapshot.identity[3:8]!=expected or snapshot.identity[9]!=epoch:
        raise GatewayError('INVALID_CHANNEL_HISTORY_BINDING')
    revision=_hash([digest,snapshot.identity,snapshot.revision,snapshot.focus,
        [asdict(t) for t in snapshot.history],epoch,policy_revision,asdict(authorization.budget)])
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.SINGLE_ROUND,revision,
        'candidate','OFFLINE_CONVERSATION_CANDIDATE'),True,max_output_tokens=authorization.budget.max_output_tokens)
