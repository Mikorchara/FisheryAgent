"""Explicit, one-turn Qwen trial; reuses the SDK Adapter and the original Agent loop."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
import hashlib
import json
import threading
import time

import httpx
from httpx import AsyncClient as _TrialHTTPClient
from openai import AsyncOpenAI

from apps.ai_backend.contracts import UsageSource
from apps.ai_backend.execution import current_handle
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_backend.tool_conversation import ToolExecutionMode
from .channel import ChannelBudget
from .channel_scope import monitoring_trial_scope
from .channel_presentation import EXPLANATION_CONTRACT
from .execution import ExecutionDecision
from .runtime.assistant import assistant_profile
from .runtime.release_contracts import AssistantExecutionProfile, _hash


TRIAL_CONTRACT='qq-qwen-current-explanation-trial@1'
PRESET='dashscope-qwen38-flash-r1'
PRICE_URL='https://help.aliyun.com/zh/model-studio/model-pricing'
MODEL_URL='https://help.aliyun.com/zh/model-studio/qwen3-8-flash'
# Conservative reservation, not a tokenizer approximation. Includes all server-side
# input up to the published context limit; never discounts cache/free quotas.
CONTEXT_RESERVATION=1_000_000
PRICE_INPUT=Decimal('0.8')
PRICE_OUTPUT=Decimal('2.7')
MAX_REQUEST_BYTES=32768


def money(value):
    try:
        if type(value) is not str or len(value)>32:raise ValueError()
        result=Decimal(value)
        if not result.is_finite() or not 0<result<=100:raise ValueError()
        return result
    except (InvalidOperation,ValueError):raise GatewayError('TRIAL_COST_INVALID') from None


def cost_reservation():
    return ((CONTEXT_RESERVATION*PRICE_INPUT+512*PRICE_OUTPUT)*2/Decimal(1_000_000)).quantize(
        Decimal('.000001'),rounding=ROUND_CEILING)


def fast_trial_scope(profile,policy,registry):
    if profile!=assistant_profile(PRESET):raise GatewayError('TRIAL_PRESET_NOT_ALLOWED')
    scope=monitoring_trial_scope(profile,policy,registry,budget=ChannelBudget())
    root=Path(__file__).parents[1]
    paths=('ai_service/channel_trial.py','ai_service/service.py','ai_service/channel.py',
        'ai_service/channel_presentation.py','ai_service/channel_conversation.py','ai_service/contracts.py',
        'qq_bot/conversations.py','qq_bot/intent.py','ai_service/channel_conversation_trial.py',
        'qq_bot/conversation_trial.py','qq_bot/conversation_trial_cli.py','qq_bot/trial.py','qq_bot/trial_configuration.py',
        'qq_bot/ai_trial_delivery.py','qq_bot/ai_coordinator.py','qq_bot/ai_scheduler.py',
        'qq_bot/ai_delivery.py','qq_bot/ai_routing.py','qq_bot/gateway.py','qq_bot/transport.py',
        'ai_service/channel_session_run.py','qq_bot/run_consent.py','qq_bot/session_run.py','qq_bot/session_run_cli.py',
        'ai_service/channel_session_trial.py','qq_bot/session_run_trial.py','qq_bot/session_run_trial_cli.py',
        'qq_bot/monitoring_source.py','qq_bot/ai_configuration.py','qq_bot/adapter.py',
        'ai_service/business_tools/current_water_quality.py','ai_service/business_tools/registry.py',
        'ai_service/runtime/assistant.py','ai_service/runtime/sources.py','ai_service/management_policy.py',
        'ai_service/runtime/resources/presets.json')
    return dict(contract=TRIAL_CONTRACT,project_root=str(root.parent.resolve()),base_scope=scope,
        implementation={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},
        transport={'adapter':'apps.ai_service.channel_trial.TrialQwenAdapter',
            'delegate':'apps.ai_backend.openai_compatible_adapter.OpenAICompatibleAdapter',
            'sdk':'AsyncOpenAI','follow_redirects':False,'trust_env':False,'retries':0},
        cost={'currency':'CNY','region':'cn-beijing','input_per_million':str(PRICE_INPUT),
            'output_per_million':str(PRICE_OUTPUT),'reserved_input_tokens_per_request':CONTEXT_RESERVATION,
            'output_tokens_per_request':512,'model_requests':2,'max_turns':1,
            'max_request_bytes':MAX_REQUEST_BYTES,'reservation_cny':str(cost_reservation()),
            'price_url':PRICE_URL,'model_url':MODEL_URL},
        presentation={'contract':EXPLANATION_CONTRACT,'raw_model_text':'NEVER',
            'mode':'SOURCE_BOUND_TEMPLATE_PLAN','general_fact_verifier':False},
        isolation='EXISTING_THREAD_RESOURCE_GATE_HARD_EXIT_NOT_GUARANTEED')


@dataclass(frozen=True,repr=False)
class QwenTrialApproval:
    approval_id: str
    phase: str
    scope_sha256: str
    bindings_sha256: str
    expires_at: datetime
    max_cost_cny: str
    instance_id: str
    device_id: str
    app_id: str = field(repr=False)
    group_id: str = field(repr=False)
    member_id: str = field(repr=False)

    def __post_init__(self):
        import re
        if (self.phase not in ('provider','qq') or self.expires_at.tzinfo is None
                or any(not re.fullmatch('[a-f0-9]{64}',v) for v in (self.scope_sha256,self.bindings_sha256))
                or any(not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_-]{1,128}',v) for v in (
                    self.approval_id,self.instance_id,self.device_id,self.app_id,self.group_id,self.member_id))
                or money(self.max_cost_cny)<cost_reservation()):
            raise GatewayError('INVALID_QWEN_TRIAL_APPROVAL')


class TrialQwenAdapter(OpenAICompatibleAdapter):
    """Only additional admission/budget guards; encoding, I/O and cleanup are inherited."""
    def __init__(self,trial,*,async_client_factory=None):
        self.trial=trial
        super().__init__(async_client_factory=async_client_factory or self._trial_client)

    def _trial_client(self,runtime,remaining):
        calls=0
        async def before_request(request):
            nonlocal calls
            self.trial.check();self.trial.handle.check()
            if (calls or request.method!='POST' or str(request.url)!=runtime.base_url.rstrip('/')+'/chat/completions'
                    or len(request.content)>MAX_REQUEST_BYTES):
                raise GatewayError('TRIAL_HTTP_REQUEST_REJECTED')
            calls+=1
            with self.trial._lock:
                if self.trial.http_requests>=2:raise GatewayError('TRIAL_MODEL_REQUEST_LIMIT')
                self.trial.http_requests+=1
        timeout=httpx.Timeout(connect=min(runtime.connect_timeout_s,remaining),read=min(runtime.read_timeout_s,remaining),
            write=min(runtime.read_timeout_s,remaining),pool=min(runtime.connect_timeout_s,remaining))
        http=_TrialHTTPClient(timeout=timeout,trust_env=False,follow_redirects=False,
            event_hooks={'request':[before_request]})
        class OwnedClient:
            """Keep the HTTP owner visible to cleanup even if SDK construction fails."""
            client=None
            @property
            def chat(owner):
                if owner.client is None:
                    owner.client=AsyncOpenAI(api_key=runtime.credential._for_adapter(),base_url=runtime.base_url,
                        max_retries=0,timeout=timeout,http_client=http)
                return owner.client.chat
            async def close(owner):
                if owner.client is not None:await owner.client.close()
                else:await http.aclose()
            def is_closed(owner):return http.is_closed and (owner.client is None or owner.client.is_closed())
        return OwnedClient()

    def manual_complete(self,*args,**kwargs):raise GatewayError('TRIAL_MANUAL_NOT_ALLOWED')
    def manual_stream(self,*args,**kwargs):raise GatewayError('TRIAL_MANUAL_NOT_ALLOWED')

    def _kwargs(self,request,runtime,*,stream,_assemble_tools=False):
        self.trial.check()
        if stream or _assemble_tools or runtime.max_retries!=0 or current_handle() is not self.trial.handle:
            raise GatewayError('TRIAL_NORMAL_HANDLE_REQUIRED')
        kwargs=super()._kwargs(request,runtime,stream=False)
        if (kwargs.get('max_tokens')!=512 or kwargs.get('extra_body',{}).get('enable_thinking') is not False
                or kwargs.get('model')!=assistant_profile(PRESET).model):
            raise GatewayError('TRIAL_TRANSPORT_BUDGET_MISMATCH')
        if len(json.dumps(kwargs,ensure_ascii=False,allow_nan=False).encode('utf-8'))>MAX_REQUEST_BYTES:
            raise GatewayError('TRIAL_INPUT_TOO_LARGE')
        with self.trial._lock:
            if self.trial.requests>=2:raise GatewayError('TRIAL_MODEL_REQUEST_LIMIT')
            self.trial.requests+=1  # Reserve before I/O. Unknown/failure is never refunded/retried.
        return kwargs

    def complete(self,request,runtime):
        result=super().complete(request,runtime)
        self.trial.check()
        usage=result.usage
        if (usage.source!=UsageSource.PROVIDER or type(usage.input_tokens) is not int
                or type(usage.output_tokens) is not int or not 0<=usage.input_tokens<=CONTEXT_RESERVATION
                or not 0<=usage.output_tokens<=512):
            raise GatewayError('TRIAL_USAGE_UNCONFIRMED')
        with self.trial._lock:
            self.trial.input_tokens+=usage.input_tokens;self.trial.output_tokens+=usage.output_tokens
            self.trial.responses_with_usage+=1
        return result


class QwenTrialSession:
    """Server-owned approval/one-turn lease. JSON booleans cannot instantiate execution."""
    release_status='local_experimental'

    def __init__(self,approval,*,validate,claim,async_client_factory=None,clock=None,monotonic=time.monotonic):
        if type(approval) is not QwenTrialApproval or not callable(validate) or not callable(claim):
            raise GatewayError('INVALID_QWEN_TRIAL_COMPOSITION')
        self._initialize(approval,validate=validate,claim=claim,async_client_factory=async_client_factory,
            clock=clock,monotonic=monotonic)

    def _initialize(self,approval,*,validate,claim,async_client_factory=None,clock=None,monotonic=time.monotonic):
        """Shared SDK guards only; each public constructor validates its exact grant type."""
        self.approval=approval;self._validate=validate;self._claim=claim
        self.clock=clock or (lambda:datetime.now(timezone.utc));self.now=monotonic
        self._deadline=self.now()+max(0,(approval.expires_at-self.clock()).total_seconds())
        self.offline_test=async_client_factory is not None
        self._lock=threading.RLock();self.handle=None;self.requests=0;self.http_requests=0;self.input_tokens=0;self.output_tokens=0
        self.responses_with_usage=0
        self._admitted_handle=None
        self.source=None
        self.adapter=TrialQwenAdapter(self,async_client_factory=async_client_factory)
        self.check()

    def check(self):
        if self.clock()>=self.approval.expires_at or self.now()>=self._deadline:
            raise GatewayError('TRIAL_APPROVAL_EXPIRED')
        SDK_RESOURCES.assert_healthy()
        self._validate()

    def check_message(self,message):
        self.check()
        a=self.approval
        if (message.group_id,message.member_id)!=(a.group_id,a.member_id):
            raise GatewayError('TRIAL_MEMBER_NOT_APPROVED')

    def check_admission(self):
        self.check()
        with self._lock:
            if self._admitted_handle is not None or self.handle is not None:
                raise GatewayError('TRIAL_ALREADY_USED')

    def reserve_admission(self,handle):
        with self._lock:
            self.check_admission()
            self._admitted_handle=handle

    def decision(self,profile,policy,registry,authorization,*,epoch,policy_revision):
        self.check()
        a=self.approval
        if (authorization.budget!=ChannelBudget() or authorization.preset_id!=PRESET
                or (authorization.instance_id,authorization.device_id)!=(a.instance_id,a.device_id)):
            raise GatewayError('TRIAL_BINDING_MISMATCH')
        scope=fast_trial_scope(profile,policy,registry)
        if _hash(scope)!=a.scope_sha256:raise GatewayError('TRIAL_SCOPE_CHANGED')
        revision=_hash([a.approval_id,a.scope_sha256,a.bindings_sha256,epoch,policy_revision,
            authorization.permission_revision,authorization.binding_revision])
        return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.SINGLE_ROUND,revision,
            'local_experimental','EXPLICIT_ONE_TURN_QWEN_TRIAL'),True,max_output_tokens=512)

    def arm(self,handle):
        self.check()
        with self._lock:
            if self.handle is not None or (self._admitted_handle is not None and self._admitted_handle is not handle):
                raise GatewayError('TRIAL_ALREADY_USED')
            self._claim()  # Exclusive persistent marker; crash/unknown execution consumes approval.
            self.handle=handle
            handle.limit_turn(min(90,max(.001,self._deadline-self.now())))

    def validate_tool_result(self,result):
        self.check()
        if not isinstance(result,dict) or result.get('source_kind')!='simulator':
            raise GatewayError('TRIAL_SOURCE_NOT_APPROVED')

    def guard_traces(self,sink):
        trial=self
        class GuardedTraces:
            def record_tool_conversation(self,*args,**kwargs):
                trial.check();return sink.record_tool_conversation(*args,**kwargs)
            def record_assistant(self,*args,**kwargs):
                trial.check();return sink.record_assistant(*args,**kwargs)
        return GuardedTraces()

    def report(self):
        with self._lock:
            actual=(self.input_tokens*PRICE_INPUT+self.output_tokens*PRICE_OUTPUT)/Decimal(1_000_000)
            return dict(model_requests=self.requests,usage={'input_tokens':self.input_tokens,
                'output_tokens':self.output_tokens},reserved_cost_cny=str(cost_reservation()),
                observed_usage_cost_cny=str(actual),billing_confirmed=False,
                usage_complete=self.requests>0 and self.responses_with_usage==self.requests,
                sdk_resources=self.handle.resource_info() if self.handle else None,
                source_summary=asdict(self.source) if self.source is not None else None,
                sdk_request_attempts=self.adapter.request_attempts,
                model_http_requests=self.http_requests,
                offline_test=self.offline_test,model_text_displayed=False,
                remote_compute_stopped='unknown')
