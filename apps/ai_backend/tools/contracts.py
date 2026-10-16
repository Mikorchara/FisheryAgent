"""Read-only execution contracts; model protocol types remain in the Gateway."""

from dataclasses import dataclass, field
from enum import Enum
from functools import partial
import json
from typing import Callable

from ..model_gateway import ModelToolDefinition
from ..tool_argument_diagnostics import (ArgumentStage, ArgumentRejection, ToolArgumentError,
    ToolArgumentDiagnostic, public_argument_diagnostic, rejection)


class ToolStatus(str, Enum):
    """Business result of one tool execution; it is not an error-code channel.

    ``ERROR`` is the only member describing a failed execution, so it is the only
    one accompanied by a ``ToolErrorCode``. ``NO_DATA`` means the subject itself
    has no current data (for example no applied snapshot). ``NO_MATCH`` means the
    request was valid but nothing qualified (for example a read-only search whose
    hits did not meet the minimum). The two are deliberately distinct.

    How a caller reacts to a member - for example whether to continue a follow-up
    conversation - is orchestration policy owned by that caller, not by this
    contract.
    """

    OK = "OK"
    PARTIAL = "PARTIAL"
    NOT_SCORABLE = "NOT_SCORABLE"
    NO_DATA = "NO_DATA"
    NO_MATCH = "NO_MATCH"
    ERROR = "ERROR"


class ToolErrorCode(str, Enum):
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    TOOL_RESULT_TOO_LARGE = "TOOL_RESULT_TOO_LARGE"
    TOOL_CALL_LIMIT = "TOOL_CALL_LIMIT"
    TOOL_CALL_ALREADY_EXECUTED = "TOOL_CALL_ALREADY_EXECUTED"
    TOOL_REQUEST_ALREADY_EXECUTED = "TOOL_REQUEST_ALREADY_EXECUTED"


class ToolError(Exception):
    def __init__(self, code: ToolErrorCode, *, argument_diagnostic=None):
        self.code = ToolErrorCode(code)
        self.argument_diagnostic = argument_diagnostic if public_argument_diagnostic(argument_diagnostic) else None
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
        return self.prepare(arguments)[1]

    def prepare(self, arguments: dict) -> tuple[dict, Callable[[], dict]]:
        """Validate once; expose canonical arguments only to the local executor."""
        if self.validate_arguments is None:
            if arguments:
                raise ToolArgumentError(rejection(ArgumentStage.DEFINITION,
                    ArgumentRejection.UNEXPECTED_ARGUMENTS, arguments=arguments))
            return {}, self.handler
        try:
            validated = self.validate_arguments(arguments)
        except (ValueError, TypeError, RecursionError, UnicodeError, AttributeError):
            raise ToolArgumentError(rejection(ArgumentStage.DEFINITION,
                ArgumentRejection.VALIDATOR_REJECTED, arguments=arguments)) from None
        if not isinstance(validated, dict):
            raise ToolArgumentError(rejection(ArgumentStage.DEFINITION,
                ArgumentRejection.VALIDATOR_REJECTED, arguments=arguments))
        return validated, partial(self.handler, validated)


@dataclass(frozen=True)
class ToolExecutionResult:
    tool_call_id: str
    tool_name: str
    status: ToolStatus
    _content_json: str = field(repr=False)
    error_code: ToolErrorCode | None = None
    argument_diagnostic: ToolArgumentDiagnostic | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_payload(cls, call_id: str, name: str, payload: dict, *, argument_diagnostic=None):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"))
        status = ToolStatus(payload["status"])
        code = ToolErrorCode(payload["error_code"]) if status == ToolStatus.ERROR else None
        diagnostic = (argument_diagnostic if code == ToolErrorCode.INVALID_TOOL_ARGUMENTS
                      and public_argument_diagnostic(argument_diagnostic) else None)
        return cls(call_id, name, status, content, code, diagnostic)

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
