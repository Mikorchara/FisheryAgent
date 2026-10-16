"""Request-scoped, bounded execution of explicitly supplied calls; no model loop."""

import json
from threading import Lock

from ..execution import check_cancelled
from ..model_gateway import GatewayError, ModelToolCall
from .contracts import ToolError, ToolErrorCode, ToolExecutionResult
from .registry import ToolRegistry
from ..tool_argument_diagnostics import (ArgumentStage, ArgumentRejection, ToolArgumentError, rejection)


class ToolExecutor:
    """Create once per request. Attempts consume budget; call IDs cannot be replayed."""

    def __init__(self, registry: ToolRegistry, *, max_calls: int = 1,
                 max_result_bytes: int = 32768, policy=None, reject_duplicate_requests: bool = False,
                 on_handler_started=None):
        from .policy import ToolPolicy
        if not isinstance(policy, ToolPolicy):
            raise ValueError("explicit ToolPolicy required")
        self._policy = policy
        self._policy.validate_registry(registry)
        if type(max_calls) is not int or not 1 <= max_calls <= 8:
            raise ValueError("max_calls must be between 1 and 8")
        if type(max_result_bytes) is not int or not 256 <= max_result_bytes <= 262144:
            raise ValueError("max_result_bytes must be between 256 and 262144")
        self._registry = registry
        self._max_calls = max_calls
        self._max_result_bytes = max_result_bytes
        self._seen: set[str] = set()
        if type(reject_duplicate_requests) is not bool:
            raise ValueError("invalid duplicate request option")
        self._reject_duplicate_requests = reject_duplicate_requests
        self._seen_requests: set[tuple[str, str]] = set()
        self._lock = Lock()
        self._on_handler_started = on_handler_started

    def execute(self, call: ModelToolCall) -> ToolExecutionResult:
        if not isinstance(call, ModelToolCall):
            raise TypeError("call must be a ModelToolCall")
        check_cancelled()
        try:
            with self._lock:
                if call.id in self._seen:
                    raise ToolError(ToolErrorCode.TOOL_CALL_ALREADY_EXECUTED)
                if len(self._seen) >= self._max_calls:
                    raise ToolError(ToolErrorCode.TOOL_CALL_LIMIT)
                self._seen.add(call.id)
            definition = self._registry.lookup(call.function_name)
            if not self._policy.allows(call.function_name):
                raise ToolError(ToolErrorCode.TOOL_NOT_ALLOWED)
            try:
                if len(call.arguments_json.encode("utf-8")) > 4096:
                    raise ToolArgumentError(rejection(ArgumentStage.EXECUTOR,
                        ArgumentRejection.ARGUMENTS_TOO_LARGE, call.arguments_json))
                try:
                    arguments = json.loads(call.arguments_json)
                except (ValueError, TypeError):
                    raise ToolArgumentError(rejection(ArgumentStage.EXECUTOR,
                        ArgumentRejection.MALFORMED_JSON, call.arguments_json)) from None
                except RecursionError:
                    raise ToolArgumentError(rejection(ArgumentStage.EXECUTOR,
                        ArgumentRejection.ARGUMENTS_TOO_COMPLEX, call.arguments_json)) from None
                if not isinstance(arguments, dict):
                    raise ToolArgumentError(rejection(ArgumentStage.EXECUTOR,
                        ArgumentRejection.NOT_OBJECT, call.arguments_json))
                # The definition owns its parameter contract; the Executor only
                # enforces size, JSON shape and the safe error mapping.
                if self._reject_duplicate_requests:
                    normalized, invoke = definition.prepare(arguments)
                    signature = (call.function_name, json.dumps(normalized, sort_keys=True,
                        ensure_ascii=True, allow_nan=False, separators=(",", ":")))
                else:
                    invoke = definition.bind(arguments)
            except ToolArgumentError as error:
                raise ToolError(ToolErrorCode.INVALID_TOOL_ARGUMENTS,
                    argument_diagnostic=error.argument_diagnostic.with_context(call.arguments_json)) from None
            except UnicodeError:
                raise ToolError(ToolErrorCode.INVALID_TOOL_ARGUMENTS, argument_diagnostic=rejection(
                    ArgumentStage.EXECUTOR, ArgumentRejection.INVALID_ENCODING, call.arguments_json)) from None
            except (ValueError, TypeError, RecursionError, AttributeError):
                raise ToolError(ToolErrorCode.INVALID_TOOL_ARGUMENTS, argument_diagnostic=rejection(
                    ArgumentStage.EXECUTOR, ArgumentRejection.VALIDATOR_REJECTED, call.arguments_json)) from None
            if self._reject_duplicate_requests:
                with self._lock:
                    if signature in self._seen_requests:
                        raise ToolError(ToolErrorCode.TOOL_REQUEST_ALREADY_EXECUTED)
                    self._seen_requests.add(signature)
            check_cancelled()
            if self._on_handler_started:
                self._on_handler_started()  # Observation only; all authorization/validation already passed.
            payload = invoke()
            check_cancelled()
            result = ToolExecutionResult.from_payload(call.id, call.function_name, payload)
            if len(result.to_json().encode("utf-8")) > self._max_result_bytes:
                raise ToolError(ToolErrorCode.TOOL_RESULT_TOO_LARGE)
            check_cancelled()
            return result
        except ToolError as error:
            check_cancelled()
            return self._error(call, error.code, argument_diagnostic=error.argument_diagnostic)
        except GatewayError as error:
            if error.code == "USER_CANCELLED":
                raise
            check_cancelled()
            return self._error(call, ToolErrorCode.TOOL_EXECUTION_ERROR)
        except Exception:
            check_cancelled()
            return self._error(call, ToolErrorCode.TOOL_EXECUTION_ERROR)

    @staticmethod
    def _error(call: ModelToolCall, code: ToolErrorCode, *, argument_diagnostic=None) -> ToolExecutionResult:
        return ToolExecutionResult.from_payload(call.id, call.function_name,
            {"status": "ERROR", "error_code": code.value}, argument_diagnostic=argument_diagnostic)
