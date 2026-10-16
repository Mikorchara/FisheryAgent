"""Finite parameter rejection metadata. No arguments, field names or exception text.

Shared by model/transport and execution contracts without a dependency on either.
Counts saturate at fixed limits; they are observations, never authorization inputs.
"""

from dataclasses import dataclass, replace
from enum import Enum


class ArgumentStage(str, Enum):
    MODEL_CONTRACT = "model_contract"
    STREAM_ASSEMBLER = "stream_assembler"
    EXECUTOR = "executor"
    DEFINITION = "definition"


class ArgumentRejection(str, Enum):
    MALFORMED_JSON = "MALFORMED_JSON"
    NOT_OBJECT = "NOT_OBJECT"
    UNEXPECTED_ARGUMENTS = "UNEXPECTED_ARGUMENTS"
    ARGUMENTS_TOO_LARGE = "ARGUMENTS_TOO_LARGE"
    INVALID_ENCODING = "INVALID_ENCODING"
    VALIDATOR_REJECTED = "VALIDATOR_REJECTED"
    ARGUMENTS_TOO_COMPLEX = "ARGUMENTS_TOO_COMPLEX"
    INVALID_JSON_VALUE = "INVALID_JSON_VALUE"


@dataclass(frozen=True)
class ToolArgumentDiagnostic:
    stage: ArgumentStage
    reason: ArgumentRejection
    argument_bytes: int | None = None
    object_member_count: int | None = None

    def __post_init__(self):
        if not isinstance(self.stage, ArgumentStage) or not isinstance(self.reason, ArgumentRejection):
            raise ValueError("invalid argument diagnostic")
        for value, limit in ((self.argument_bytes, 65536), (self.object_member_count, 1024)):
            if value is not None and (type(value) is not int or not 0 <= value <= limit):
                raise ValueError("invalid argument diagnostic count")

    def with_context(self, text=None, arguments=None):
        size = self.argument_bytes
        if isinstance(text, str):
            # Avoid allocating a second unbounded buffer just for diagnostics.
            if len(text) > 65536:
                size = 65536
            else:
                try:
                    size = min(len(text.encode("utf-8")), 65536)
                except UnicodeError:
                    size = None
        count = min(len(arguments), 1024) if isinstance(arguments, dict) else self.object_member_count
        return replace(self, argument_bytes=size, object_member_count=count)


class ToolArgumentError(ValueError):
    """Still a ValueError for existing callers; its message is a fixed enum only."""
    def __init__(self, diagnostic):
        self.argument_diagnostic = diagnostic
        super().__init__(diagnostic.reason.value)


def public_argument_diagnostic(value):
    """Allowlist projection; never serialize arbitrary exception attributes/dicts."""
    if type(value) is not ToolArgumentDiagnostic:
        return None
    try:
        ToolArgumentDiagnostic(value.stage, value.reason, value.argument_bytes, value.object_member_count)
    except (ValueError, TypeError, AttributeError):
        return None
    return {"schema_version": 1, "stage": value.stage.value, "reason": value.reason.value,
            "argument_bytes": value.argument_bytes, "object_member_count": value.object_member_count}


def rejection(stage, reason, text=None, arguments=None):
    return ToolArgumentDiagnostic(stage, reason).with_context(text, arguments)
