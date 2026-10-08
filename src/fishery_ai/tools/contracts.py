"""Read-only execution contracts; model protocol types remain in the Gateway."""

from dataclasses import dataclass, field
from enum import Enum
from functools import partial
import json
from typing import Callable

from ..model_gateway import ModelToolDefinition


class ToolStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    NOT_SCORABLE = "NOT_SCORABLE"
    NO_DATA = "NO_DATA"
    ERROR = "ERROR"


class ToolErrorCode(str, Enum):
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    TOOL_RESULT_TOO_LARGE = "TOOL_RESULT_TOO_LARGE"
    TOOL_CALL_LIMIT = "TOOL_CALL_LIMIT"
    TOOL_CALL_ALREADY_EXECUTED = "TOOL_CALL_ALREADY_EXECUTED"


class ToolError(Exception):
    def __init__(self, code: ToolErrorCode):
        self.code = ToolErrorCode(code)
        super().__init__(self.code.value)


@dataclass(frozen=True)
class ToolDefinition:
    """Static binding of one model-visible definition to one server-side handler.

    Parameterless tools (the current default) leave ``validate_arguments`` unset:
    the Executor only accepts an empty ``{}`` object and calls ``handler()``.

    A tool that accepts parameters supplies ``validate_arguments``. The Executor
    parses the model's JSON, hands that object to the callable, and calls the
    handler with the **normalized** arguments as a single positional argument.
    Rejection is expressed by raising; the Executor maps it to a safe error.
    """

    model_definition: ModelToolDefinition
    handler: Callable[..., dict] = field(repr=False, compare=False)
    validate_arguments: Callable[[dict], dict] | None = field(default=None, repr=False, compare=False)

    def bind(self, arguments: dict) -> Callable[[], dict]:
        """Return the zero-argument invocation for already-parsed arguments.

        This is the whole server-side parameter contract: reject, normalize, and
        only then hand arguments to the bound handler. Bound once per call.
        """
        if self.validate_arguments is None:
            if arguments:
                raise ValueError("this tool accepts no parameters")
            return self.handler
        validated = self.validate_arguments(arguments)
        if not isinstance(validated, dict):
            raise ValueError("validated arguments must be a JSON object")
        return partial(self.handler, validated)


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_call_id: str
    tool_name: str
    status: ToolStatus
    _content_json: str = field(repr=False)
    error_code: ToolErrorCode | None = None

    @classmethod
    def from_payload(cls, call_id: str, name: str, payload: dict):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"))
        status = ToolStatus(payload["status"])
        code = ToolErrorCode(payload["error_code"]) if status == ToolStatus.ERROR else None
        return cls(call_id, name, status, content, code)

    @property
    def payload(self) -> dict:
        """Detached data: a caller cannot mutate the retained result."""
        return json.loads(self._content_json)

    def to_json(self) -> str:
        """Tool message content, without transport metadata or exception details."""
        return self._content_json

    def to_dict(self) -> dict:
        return {"tool_call_id": self.tool_call_id, "tool_name": self.tool_name,
                "status": self.status.value, "result": self.payload}
