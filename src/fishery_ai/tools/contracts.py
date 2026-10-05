"""Read-only execution contracts; model protocol types remain in the Gateway."""

from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Callable

from ..model_gateway import ModelToolDefinition


class ToolStatus(str, Enum):
    OK = "OK"
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
    model_definition: ModelToolDefinition
    handler: Callable[[], dict] = field(repr=False, compare=False)


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
