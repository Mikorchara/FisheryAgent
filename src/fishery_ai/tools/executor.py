"""Request-scoped, bounded execution of explicitly supplied calls; no model loop."""

import json
from threading import Lock

from ..execution import check_cancelled
from ..model_gateway import GatewayError, ModelToolCall
from .contracts import ToolError, ToolErrorCode, ToolExecutionResult
from .registry import ToolRegistry


class ToolExecutor:
    """Create once per request. Attempts consume budget; call IDs cannot be replayed."""

    def __init__(self, registry: ToolRegistry, *, max_calls: int = 1,
                 max_result_bytes: int = 32768):
        if type(max_calls) is not int or not 1 <= max_calls <= 8:
            raise ValueError("max_calls must be between 1 and 8")
        if type(max_result_bytes) is not int or not 256 <= max_result_bytes <= 262144:
            raise ValueError("max_result_bytes must be between 256 and 262144")
        self._registry = registry
        self._max_calls = max_calls
        self._max_result_bytes = max_result_bytes
        self._seen: set[str] = set()
        self._lock = Lock()

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
            try:
                if len(call.arguments_json.encode("utf-8")) > 4096:
                    raise ValueError
                arguments = json.loads(call.arguments_json)
                if not isinstance(arguments, dict) or arguments:
                    raise ValueError
            except (ValueError, TypeError, RecursionError, UnicodeError, AttributeError):
                raise ToolError(ToolErrorCode.INVALID_TOOL_ARGUMENTS) from None
            check_cancelled()
            payload = definition.handler()
            check_cancelled()
            result = ToolExecutionResult.from_payload(call.id, call.function_name, payload)
            if len(result.to_json().encode("utf-8")) > self._max_result_bytes:
                raise ToolError(ToolErrorCode.TOOL_RESULT_TOO_LARGE)
            check_cancelled()
            return result
        except ToolError as error:
            check_cancelled()
            return self._error(call, error.code)
        except GatewayError as error:
            if error.code == "USER_CANCELLED":
                raise
            check_cancelled()
            return self._error(call, ToolErrorCode.TOOL_EXECUTION_ERROR)
        except Exception:
            check_cancelled()
            return self._error(call, ToolErrorCode.TOOL_EXECUTION_ERROR)

    @staticmethod
    def _error(call: ModelToolCall, code: ToolErrorCode) -> ToolExecutionResult:
        return ToolExecutionResult.from_payload(call.id, call.function_name,
                                                {"status": "ERROR", "error_code": code.value})
