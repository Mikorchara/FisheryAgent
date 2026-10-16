"""Shared bounded coordinator; production stays single-round by default."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
import json
import math
import re
import time
from typing import Callable
import uuid

from .contracts import Mode, RuntimeInfo, SessionUsage, Status, Usage, UsageAccumulator, UsageSource, utcnow
from .execution import check_cancelled, current_handle, turn_deadline_scope
from .model_gateway import (GatewayError, ModelGateway, ModelMessage, ModelRequest,
                            ModelResponse, ModelToolCall, RuntimeSnapshot, validate_tool_request)
from .observability import JsonlTraceSink
from .tools import ToolExecutionResult, ToolExecutor, ToolRegistry, ToolStatus
from .tools.policy import ToolPolicy, ToolPolicyError
from .tool_argument_diagnostics import ToolArgumentDiagnostic, ToolArgumentError


@dataclass(frozen=True)
class ModelStepOutcome:
    outcome: str = "not_started"
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    error_code: str | None = None
    argument_diagnostic: ToolArgumentDiagnostic | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ToolTurnBudget:
    """Internal finite budget; publishing a different execution mode is separate."""
    max_tool_calls: int = 1
    max_tool_rounds: int = 1
    max_model_requests: int = 2

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in (
                self.max_tool_calls, self.max_tool_rounds, self.max_model_requests)):
            raise ValueError("invalid tool turn budget")
        if self.max_model_requests < self.max_tool_rounds + 1:
            raise ValueError("tool rounds require a final model request")

    @property
    def max_steps(self) -> int:
        return self.max_model_requests + self.max_tool_calls


SINGLE_ROUND_BUDGET = ToolTurnBudget()
BOUNDED_MULTI_ROUND_BUDGET = ToolTurnBudget(2, 2, 3)


class ToolExecutionMode(str, Enum):
    SINGLE_ROUND = "SINGLE_ROUND"
    BOUNDED_MULTI_ROUND = "BOUNDED_MULTI_ROUND"


class ToolModelTransport(str, Enum):
    """Internal typed transport selection; no Web request or release override."""
    NORMAL = "NORMAL"
    STREAMING = "STREAMING"


@dataclass(frozen=True)
class ModelExecutionStep:
    seq: int
    request_index: int
    result: ModelStepOutcome
    request_started: bool = False  # Gateway invocation, not proof of a Provider network attempt.

    def __post_init__(self):
        if (any(type(value) is not int or value < 1 for value in (self.seq, self.request_index))
                or type(self.request_started) is not bool or not isinstance(self.result, ModelStepOutcome)):
            raise ValueError("invalid model execution step")


@dataclass(frozen=True)
class ToolExecutionStep:
    seq: int
    model_request_index: int
    tool_round: int
    tool_call_id: str = field(repr=False)
    tool_name: str = field(repr=False)
    result: ToolExecutionResult | None = field(default=None, repr=False)
    duration_ms: float | None = None
    handler_started: bool = False

    def __post_init__(self):
        if (any(type(value) is not int or value < 1 for value in (
                self.seq, self.model_request_index, self.tool_round))
                or not isinstance(self.tool_call_id, str) or not self.tool_call_id
                or not isinstance(self.tool_name, str) or not self.tool_name
                or type(self.handler_started) is not bool
                or (self.result is not None and not isinstance(self.result, ToolExecutionResult))
                or (self.duration_ms is not None and (type(self.duration_ms) not in (int, float)
                    or not math.isfinite(self.duration_ms) or self.duration_ms < 0))):
            raise ValueError("invalid tool execution step")


def _finish_reason(value) -> str | None:
    return value if value in ("stop", "length", "tool_calls", "function_call", "content_filter") else None


@dataclass(frozen=True)
class ToolConversationResult:
    request_id: str
    trace_id: str
    status: Status
    runtime: RuntimeInfo
    generated_text: str = field(repr=False)
    steps: tuple[ModelExecutionStep | ToolExecutionStep, ...]
    usage: SessionUsage
    final_finish_reason: str | None = None
    error_code: str | None = None
    trace_recorded: bool = False
    reasoning_content: str | None = field(default=None, repr=False)
    application_mode: str = "assistant"
    budget: ToolTurnBudget = SINGLE_ROUND_BUDGET
    model_transport: ToolModelTransport = ToolModelTransport.NORMAL

    def __post_init__(self):
        if not isinstance(self.model_transport, ToolModelTransport):
            raise ValueError("typed model transport required")
        object.__setattr__(self, "steps", tuple(self.steps))
        model_indices = []
        for seq, step in enumerate(self.steps, 1):
            if not isinstance(step, (ModelExecutionStep, ToolExecutionStep)) or step.seq != seq:
                raise ValueError("invalid execution step order")
            if isinstance(step, ModelExecutionStep):
                if not isinstance(step.result, ModelStepOutcome):
                    raise TypeError("model step outcome required")
                model_indices.append(step.request_index)
            elif step.model_request_index not in model_indices or step.tool_round < 1:
                raise ValueError("tool step requires its preceding model request")
        if model_indices != list(range(1, len(model_indices) + 1)):
            raise ValueError("invalid model request order")

    def _legacy_model(self, index: int) -> ModelStepOutcome:
        if sum(isinstance(step, ModelExecutionStep) for step in self.steps) > 2:
            raise ValueError("legacy projection requires single-round execution")
        return next((step.result for step in self.steps if isinstance(step, ModelExecutionStep)
                     and step.request_index == index), ModelStepOutcome())

    @property
    def request_1(self) -> ModelStepOutcome:
        return self._legacy_model(1)

    @property
    def request_2(self) -> ModelStepOutcome:
        return self._legacy_model(2)

    @property
    def tool_step(self) -> ToolExecutionStep | None:
        tools = tuple(step for step in self.steps if isinstance(step, ToolExecutionStep))
        if len(tools) > 1:
            raise ValueError("legacy projection requires single tool execution")
        return tools[0] if tools else None

    @property
    def tool_result(self) -> ToolExecutionResult | None:
        return self.tool_step.result if self.tool_step else None

    @property
    def tool_duration_ms(self) -> float | None:
        return self.tool_step.duration_ms if self.tool_step else None

    @property
    def tool_call_id(self) -> str | None:
        return self.tool_step.tool_call_id if self.tool_step else None

    @property
    def tool_name(self) -> str | None:
        return self.tool_step.tool_name if self.tool_step else None


def _safe_code(code: str) -> str:
    if code == "INVALID_TOOL_CALL":
        return "MODEL_TOOL_CALL_MALFORMED"
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) else "MODEL_REQUEST_ERROR"


def _validate_response(response: ModelResponse) -> tuple[ModelToolCall, ...]:
    """Defensive boundary for alternate Gateways; T1 already validates the SDK."""
    if not isinstance(response, ModelResponse):
        raise GatewayError("INVALID_RESPONSE")
    try:
        calls = tuple(ModelToolCall(item.id, item.function_name, item.arguments_json, item.type)
                      for item in response.tool_calls)
        if len({item.id for item in calls}) != len(calls):
            raise ValueError
    except ToolArgumentError as error:
        raise GatewayError("MODEL_TOOL_CALL_MALFORMED", argument_diagnostic=error.argument_diagnostic) from None
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise GatewayError("MODEL_TOOL_CALL_MALFORMED") from None
    if (response.text is not None and not isinstance(response.text, str)) or (response.text is None and not calls):
        raise GatewayError("INVALID_RESPONSE")
    return calls


def _aggregate_usage(items: list[Usage]) -> SessionUsage:
    accumulator = UsageAccumulator()
    for item in items:
        accumulator.add(item)
    try:
        return accumulator.snapshot()
    except ValueError:
        # Different providers may report disjoint fields across calls. Per-step
        # counts remain intact; no complete total can then be claimed.
        return SessionUsage(len(items), sum(item.source == UsageSource.PROVIDER for item in items), Usage())


class ToolCallingService:
    """One shared bounded executor; callers own Analysis or Assistant context."""

    def __init__(self, gateway: ModelGateway, registry: ToolRegistry, traces: JsonlTraceSink,
                 *, clock: Callable[[], datetime] = utcnow,
                 id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
                 policy: ToolPolicy | None = None,
                 budget: ToolTurnBudget | None = None,
                 execution_mode: ToolExecutionMode = ToolExecutionMode.SINGLE_ROUND,
                 model_transport: ToolModelTransport = ToolModelTransport.NORMAL):
        if not isinstance(execution_mode, ToolExecutionMode):
            raise ValueError("typed internal execution mode required")
        if not isinstance(model_transport, ToolModelTransport):
            raise ValueError("typed internal model transport required")
        expected_budget = (SINGLE_ROUND_BUDGET if execution_mode == ToolExecutionMode.SINGLE_ROUND
                           else BOUNDED_MULTI_ROUND_BUDGET)
        budget = expected_budget if budget is None else budget
        if not isinstance(budget, ToolTurnBudget) or budget != expected_budget:
            raise ValueError("execution mode requires its fixed budget")
        self._budget = budget
        self._execution_mode = execution_mode
        self._model_transport = model_transport
        self.gateway, self.registry, self.traces = gateway, registry, traces
        self.clock, self.id_factory = clock, id_factory
        if not isinstance(policy, ToolPolicy):
            raise ValueError("explicit ToolPolicy required")
        self.policy = policy
        self.policy.validate_registry(registry)

    @property
    def budget(self) -> ToolTurnBudget:
        return self._budget

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return self._execution_mode

    @property
    def model_transport(self) -> ToolModelTransport:
        return self._model_transport


    def run_request(self, request: ModelRequest, runtime: RuntimeSnapshot, *,
                    request_id: str | None = None, trace_id: str | None = None,
                    final_response_instruction: str | None = None,
                    on_progress: Callable[[str], None] | None = None,
                    on_steps: Callable[[tuple], None] | None = None) -> ToolConversationResult:
        if not isinstance(request, ModelRequest) or not isinstance(runtime, RuntimeSnapshot):
            raise TypeError("new Backend request and runtime required")
        options = dict(request_id=request_id, trace_id=trace_id,
            final_response_instruction=final_response_instruction, on_progress=on_progress, on_steps=on_steps)
        if self.model_transport == ToolModelTransport.STREAMING:
            with turn_deadline_scope(runtime.total_timeout_s):
                return self._run_request(request, runtime, **options)
        return self._run_request(request, runtime, **options)

    def _run_request(self, request: ModelRequest, runtime: RuntimeSnapshot, *,
                     request_id=None, trace_id=None, final_response_instruction=None,
                     on_progress=None, on_steps=None) -> ToolConversationResult:
        """Shared bounded execution; caller owns context, Registry owns definitions."""
        started_at, start_tick = self.clock(), time.monotonic()
        handle = current_handle()
        request_id = request_id or (handle.request_id if handle else self.id_factory())
        trace_id = trace_id or self.id_factory()
        budget = self.budget
        policy = self.policy  # Freeze authorization for every request and execution in this turn.
        multi_round = self.execution_mode == ToolExecutionMode.BOUNDED_MULTI_ROUND
        transport = self.model_transport
        model_complete = (getattr(self.gateway, "complete_tool_stream", None)
                          if transport == ToolModelTransport.STREAMING else self.gateway.complete)
        steps: list[ModelExecutionStep | ToolExecutionStep] = []
        usage_items: list[Usage] = []
        executor = None
        tool_attempts = 0
        text, finish_reason, error_code = "", None, None
        reasoning_content = None
        status = Status.COMPLETED

        def publish_steps():
            if on_steps:
                on_steps(tuple(steps))  # Immutable runtime steps remain the only execution truth.

        def complete(request: ModelRequest, index: int):
            check_cancelled()
            if index + 1 > budget.max_model_requests:
                raise GatewayError("MODEL_REQUEST_LIMIT")
            if len(steps) >= budget.max_steps:
                raise GatewayError("TOOL_STEP_LIMIT")
            position = len(steps)
            steps.append(ModelExecutionStep(position + 1, index + 1, ModelStepOutcome()))

            def set_outcome(outcome):
                steps[position] = replace(steps[position], result=outcome)
                publish_steps()

            if on_progress:
                on_progress(f"REQUEST_{index + 1}")
            publish_steps()
            # The coordinator also gates alternate Gateways; no real capability is granted.
            try:
                check_cancelled()  # Progress callbacks may cancel before transport starts.
                validate_tool_request(request, runtime, streaming=False)
                if not callable(model_complete):
                    raise GatewayError("TOOL_STREAM_TRANSPORT_NOT_IMPLEMENTED")
            except GatewayError as exc:
                set_outcome(ModelStepOutcome("blocked", error_code=_safe_code(exc.code)))
                raise
            try:
                steps[position] = replace(steps[position], request_started=True)
                publish_steps()
                response = model_complete(request, runtime)
            except GatewayError as exc:
                reported = getattr(exc, "usage", None)
                reported = reported if isinstance(reported, Usage) else Usage()
                usage_items.append(reported)
                set_outcome(ModelStepOutcome("cancelled" if exc.code == "USER_CANCELLED" else "failed",
                                                usage=reported, finish_reason=_finish_reason(getattr(exc, "finish_reason", None)),
                                                error_code=_safe_code(exc.code),
                                                argument_diagnostic=exc.argument_diagnostic))
                raise
            except Exception:
                usage_items.append(Usage())
                set_outcome(ModelStepOutcome("failed", error_code="MODEL_REQUEST_ERROR"))
                raise GatewayError("MODEL_REQUEST_ERROR") from None
            reported_usage = (response.usage or Usage()) if isinstance(response, ModelResponse) else Usage()
            if not isinstance(reported_usage, Usage):
                usage_items.append(Usage())
                set_outcome(ModelStepOutcome("failed", error_code="INVALID_RESPONSE"))
                raise GatewayError("INVALID_RESPONSE")
            usage_items.append(reported_usage)
            set_outcome(ModelStepOutcome("received", reported_usage,
                                            _finish_reason(getattr(response, "finish_reason", None))))
            try:
                calls = _validate_response(response)
            except GatewayError as exc:
                set_outcome(replace(steps[position].result, outcome="failed", error_code=exc.code,
                    argument_diagnostic=exc.argument_diagnostic))
                raise
            set_outcome(replace(steps[position].result, outcome="tool_calls" if calls else "final_answer"))
            check_cancelled()
            return response, calls

        try:
            check_cancelled()
            if (multi_round or transport == ToolModelTransport.STREAMING) and runtime.max_retries != 0:
                raise GatewayError("TOOL_RETRY_NOT_ALLOWED")
            definitions = policy.model_definitions(self.registry)
            request = replace(request, tools=definitions, tool_choice="auto" if definitions else None)
            for index in range(budget.max_model_requests):
                response, calls = complete(request, index)
                if not calls:
                    text, finish_reason = response.text, _finish_reason(response.finish_reason)
                    if multi_round:
                        final_error = ("MODEL_RESPONSE_TRUNCATED" if finish_reason == "length" else
                            "MODEL_RESPONSE_EMPTY" if not isinstance(text, str) or not text.strip() else
                            "MODEL_RESPONSE_INCOMPLETE" if finish_reason != "stop" else None)
                        if final_error:
                            steps[-1] = replace(steps[-1], result=replace(steps[-1].result,
                                outcome="failed", error_code=final_error))
                            raise GatewayError(final_error)
                    reasoning_content = response.reasoning_content
                    break  # Early final: unused budget is never spent automatically.
                model_position = len(steps) - 1
                if request.tool_choice == "none":
                    steps[model_position] = replace(steps[model_position], result=replace(
                        steps[model_position].result, outcome="tool_round_limit", error_code="TOOL_ROUND_LIMIT"))
                    raise GatewayError("TOOL_ROUND_LIMIT")
                if len(calls) > 1:
                    steps[model_position] = replace(steps[model_position], result=replace(steps[model_position].result,
                        outcome="multiple_tool_calls", error_code="TOOL_CALL_LIMIT"))
                    raise GatewayError("TOOL_CALL_LIMIT")
                if (tool_attempts >= budget.max_tool_calls or tool_attempts >= budget.max_tool_rounds
                        or index + 1 >= budget.max_model_requests or len(steps) >= budget.max_steps):
                    raise GatewayError("TOOL_ROUND_LIMIT")
                if multi_round and response.finish_reason not in ("tool_calls", "function_call", "stop"):
                    steps[model_position] = replace(steps[model_position], result=replace(
                        steps[model_position].result, outcome="failed", error_code="MODEL_TOOL_CALL_INCOMPLETE"))
                    raise GatewayError("MODEL_TOOL_CALL_INCOMPLETE")
                tool_attempts += 1
                tool_position = len(steps)
                steps.append(ToolExecutionStep(tool_position + 1, index + 1, tool_attempts,
                                               calls[0].id, calls[0].function_name))
                check_cancelled()
                if on_progress:
                    on_progress("RUNNING_TOOL")
                publish_steps()  # Attempt only: the Executor has not authorized the Handler yet.
                tool_tick = time.monotonic()
                tool_result = None
                try:
                    if executor is None:
                        def handler_started():
                            steps[tool_position] = replace(steps[tool_position], handler_started=True)
                            publish_steps()

                        executor = ToolExecutor(self.registry, max_calls=budget.max_tool_calls,
                            policy=policy, reject_duplicate_requests=multi_round,
                            on_handler_started=handler_started)
                    tool_result = executor.execute(calls[0])
                finally:
                    tool_duration_ms = (time.monotonic() - tool_tick) * 1000
                    steps[tool_position] = replace(steps[tool_position], result=tool_result,
                                                   duration_ms=tool_duration_ms)
                    publish_steps()
                check_cancelled()
                if tool_result.status == ToolStatus.ERROR:
                    raise GatewayError(tool_result.error_code.value)
                final_only = (tool_attempts >= budget.max_tool_calls
                              or tool_attempts >= budget.max_tool_rounds
                              or index + 2 >= budget.max_model_requests)
                request = replace(request, tool_choice="none" if final_only else "auto", messages=(
                    *request.messages,
                    ModelMessage("assistant", response.text, tool_calls=calls),
                    ModelMessage("tool", tool_result.to_json(), tool_call_id=calls[0].id),
                    *((ModelMessage("user", final_response_instruction),)
                      if final_only and final_response_instruction else ()),
                ))
            else:
                raise GatewayError("MODEL_REQUEST_LIMIT")
            check_cancelled()
        except GatewayError as exc:
            error_code = _safe_code(exc.code)
            status = Status.CANCELLED if error_code == "USER_CANCELLED" else Status.FAILED
        except Exception:
            error_code, status = "TOOL_CONVERSATION_ERROR", Status.FAILED

        publish_steps()

        result = ToolConversationResult(request_id, trace_id, status, runtime.public_info(),
            text if status == Status.COMPLETED else "", tuple(steps), _aggregate_usage(usage_items),
            finish_reason if status == Status.COMPLETED else None, error_code,
            reasoning_content=reasoning_content if status == Status.COMPLETED else None,
            application_mode=policy.mode, budget=budget, model_transport=transport)
        try:
            self.traces.record_tool_conversation(result, started_at=started_at,
                finished_at=self.clock(), total_ms=(time.monotonic() - start_tick) * 1000)
        except Exception:
            return replace(result, status=result.status if result.error_code else Status.FAILED,
                           generated_text="", error_code=result.error_code or "TRACE_WRITE_ERROR")
        if transport == ToolModelTransport.STREAMING and result.status == Status.COMPLETED:
            try:
                check_cancelled()  # Synchronous trace I/O is part of this internal Turn too.
            except GatewayError as exc:
                result = replace(result, status=Status.CANCELLED if exc.code == "USER_CANCELLED" else Status.FAILED,
                    generated_text="", reasoning_content=None, final_finish_reason=None, error_code=_safe_code(exc.code))
                try:
                    self.traces.record_tool_conversation(result, started_at=started_at,
                        finished_at=self.clock(), total_ms=(time.monotonic() - start_tick) * 1000)
                except Exception:
                    return result  # Keep cancellation/timeout, never regenerate or report success.
        return replace(result, trace_recorded=True)
