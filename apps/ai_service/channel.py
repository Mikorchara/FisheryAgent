"""Server-only offline channel candidate contracts, not a second Agent or transport."""
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Callable
import threading

from apps.ai_backend.model_gateway import GatewayError, ModelResponse
from apps.ai_backend.tool_conversation import ToolExecutionStep, ToolExecutionMode
from apps.monitoring.contracts import METRICS
from .business_tools.current_water_quality import CURRENT_WATER_QUALITY, WATER_TOOL_PROJECTION
from .runtime.assistant import SINGLE_ROUND_PROMPT_ID, SYSTEM_INSTRUCTION
from .runtime.release_contracts import _hash, release_scope, AssistantExecutionProfile
from .runtime.sources import SourceRequirement
from .execution import ExecutionDecision
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION


@dataclass(frozen=True)
class ChannelBudget:
    max_output_tokens: int = 512
    turn_timeout_s: int = 90

    def __post_init__(self):
        if (type(self.max_output_tokens) is not int or not 1<=self.max_output_tokens<=1024
                or type(self.turn_timeout_s) is not int or not 1<=self.turn_timeout_s<=90):
            raise GatewayError('INVALID_CHANNEL_BUDGET')


@dataclass(frozen=True)
class ChannelAuthorization:
    """Created by a trusted channel owner; never accepted from message/HTTP JSON."""
    instance_id: str
    device_id: str
    binding_revision: str
    permission_revision: str
    preset_id: str
    tools: tuple[str, ...]
    budget: ChannelBudget
    check: Callable[[], None] = field(repr=False,compare=False)

    def __post_init__(self):
        if (self.tools != (CURRENT_WATER_QUALITY,) or not isinstance(self.budget,ChannelBudget)
                or not callable(self.check) or not all(isinstance(v,str) and v for v in (
                    self.instance_id,self.device_id,self.binding_revision,self.permission_revision,self.preset_id))):
            raise GatewayError('INVALID_CHANNEL_AUTHORIZATION')


class OfflineChannelProvider:
    """Canned ModelResponses only. This exact type has no SDK, URL or network hook."""
    def __init__(self, responses, *, wait_gate=None, wait_started=None):
        values=tuple(responses)
        if not values or any(not isinstance(v,(ModelResponse,GatewayError)) for v in values):
            raise ValueError('OFFLINE_MODEL_RESPONSES_REQUIRED')
        self._responses=deque(values)
        if any(value is not None and not isinstance(value,threading.Event)
               for value in (wait_gate,wait_started)):
            raise ValueError('INVALID_OFFLINE_WAIT_GATE')
        self.wait_gate,self.wait_started=wait_gate,wait_started
        self.requests=[]  # Memory-only test observation, never traced or represented.

    def __repr__(self):
        return 'OfflineChannelProvider(<in-memory>)'

    def complete(self,request,runtime):
        self.requests.append(request)
        if self.wait_gate is not None:
            from apps.ai_backend.execution import current_handle
            handle=current_handle()
            if handle is None:
                raise GatewayError('OFFLINE_REQUEST_HANDLE_REQUIRED')
            handle.io_closed=False
            handle.bind(self.wait_gate.set)  # Cooperative fake I/O abort; no SDK/network.
            try:
                if self.wait_started is not None:self.wait_started.set()
                while not self.wait_gate.wait(.02):handle.check()
                handle.check()
            finally:
                handle.unbind();handle.io_closed=True
        if not self._responses:
            raise GatewayError('OFFLINE_RESPONSES_EXHAUSTED')
        response=self._responses.popleft()
        if isinstance(response,GatewayError):
            raise response
        return response


def candidate_decision(profile,policy,registry,*,device_id,epoch,policy_revision,
                       authorization=None):
    """A new current-only composition, with no fabricated Knowledge or qualification."""
    scope=release_scope(profile,policy,registry,DEFAULT_HISTORY_PROJECTION)
    scope.update(prompt_id=SINGLE_ROUND_PROMPT_ID,prompt_sha256=_hash(SYSTEM_INSTRUCTION))
    contract=dict(version='channel-current-offline@1',runtime=scope,
        data_bindings={'water':WATER_TOOL_PROJECTION,'knowledge':None},
        device_id=device_id,epoch=epoch,policy_revision=policy_revision,
        environment='OFFLINE_FAKE_ONLY',requirement=SourceRequirement.CURRENT_OBSERVATION_QUERY.value,
        history=[],budget={'tool_calls':1,'tool_rounds':1,'model_requests':2})
    if authorization:
        contract.update(binding_revision=authorization.binding_revision,
            permission_revision=authorization.permission_revision,budget_limits=asdict(authorization.budget))
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.SINGLE_ROUND,
        _hash(contract),'candidate','OFFLINE_CHANNEL_CANDIDATE'),authorization is not None,
        max_output_tokens=authorization.budget.max_output_tokens if authorization else None)


@dataclass(frozen=True)
class SourceMetric:
    id: str
    value: float | None
    unit: str
    quality: str


@dataclass(frozen=True)
class SourceSummary:
    instance_id: str
    device_id: str
    source_kind: str
    status: str
    observed_at: str | None
    received_at: str | None
    evaluated_at: str
    quality: str
    freshness: str
    connectivity: str
    metrics: tuple[SourceMetric, ...]
    current_evidence_usable: bool

    @classmethod
    def from_result(cls,result,authorization):
        # The original loop created these steps from the actual handler execution.
        steps=[s for s in result.execution.steps if isinstance(s,ToolExecutionStep)
               and s.tool_name==CURRENT_WATER_QUALITY and s.handler_started and s.result is not None]
        if len(steps)!=1 or not result.source_ledger.single_receipt.observation_query_completed:
            raise GatewayError('CHANNEL_SOURCE_UNAVAILABLE')
        payload=steps[0].result.payload
        if (payload.get('projection_version')!=WATER_TOOL_PROJECTION
                or payload.get('device_id')!=authorization.device_id
                or payload.get('source_kind')!='simulator' or payload.get('status') not in ('OK','NO_DATA')):
            raise GatewayError('CHANNEL_SOURCE_INVALID')
        quality=payload['data_quality']
        water=payload.get('water_quality') or {}
        metrics=tuple(SourceMetric(key,water.get(key),unit,
            payload.get('metrics',{}).get(key,{}).get('quality','missing'))
            for key,(_label,unit,_low,_high) in METRICS.items())
        usable=(quality['quality']=='valid' and quality['freshness']=='fresh'
                and quality['connectivity']=='online' and payload['status']=='OK')
        return cls(authorization.instance_id,authorization.device_id,payload['source_kind'],payload['status'],
            water.get('observed_at'),water.get('retrieved_at'),payload['evaluated_at'],quality['quality'],
            quality['freshness'],quality['connectivity'],metrics,usable)

    def presentation(self):
        lines=[f'本轮只读事实 · {self.instance_id} · {self.device_id} · SIMULATOR',
            f'观测 {self.observed_at or "无"} / 接收 {self.received_at or "无"} / 评估 {self.evaluated_at}',
            f'质量 {self.quality} / 新鲜度 {self.freshness} / 连接 {self.connectivity}']
        if not self.current_evidence_usable:
            lines.append('当前状态无法完整确认；过期、缺测或无效数据不能解释为实时正常。')
        lines.append('以下为留存窗口值，不是重新采样或实时状态保证。')
        for metric in self.metrics:
            value=metric.value if metric.quality=='valid' and metric.value is not None else '数据不足'
            lines.append(f'{METRICS[metric.id][0]}：{value} {metric.unit}（{metric.quality}）')
        lines.append('合成观测仅用于测试；查询不等于重新采样。模型自由文本尚未核验，不作为本阶段可发送答复。')
        return '\n'.join(lines)


@dataclass(frozen=True)
class ChannelAssistantResult:
    completed: bool
    error_code: str | None
    source: SourceSummary | None
    model_text: str = field(repr=False)
    scope_revision: str
    release_status: str = 'candidate'
    offline_only: bool = True
    can_deliver: bool = False
    model_text_verified: bool = False

    @property
    def presentation(self):
        return self.source.presentation() if self.source else '本轮未取得可用的当前观测来源；没有可信答复。'
