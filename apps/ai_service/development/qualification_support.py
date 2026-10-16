"""Management-only safe qualification helpers; no Prototype LLM execution imports."""
from dataclasses import asdict
from pathlib import Path
import json
import os
import re
import stat
from apps.ai_backend.contracts import Usage
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import check_cancelled
from apps.ai_backend.model_gateway import GatewayError, ModelResponse, StreamingModelError
from apps.ai_backend.observability import JsonlTraceSink
from ..runtime.locations import private_project_location
from ..runtime.assistant import MULTI_ROUND_SYSTEM_INSTRUCTION
from .qualification_adapter import response_summary

SAFE_CODES = frozenset({
    "CREDENTIAL_FILE_ERROR", "SECRET_MISSING", "USER_CANCELLED", "CONNECT_TIMEOUT", "READ_TIMEOUT",
    "TOTAL_TIMEOUT", "TIMEOUT", "DNS_ERROR", "TLS_ERROR", "PROXY_ERROR", "CONNECTION_ERROR", "SDK_ERROR",
    "INVALID_RESPONSE", "INVALID_TOOL_CALL", "MODEL_TOOL_CALL_MALFORMED", "TOOL_CALL_LIMIT", "TOOL_ROUND_LIMIT",
    "UNKNOWN_TOOL", "TOOL_NOT_ALLOWED", "INVALID_TOOL_ARGUMENTS", "TOOL_EXECUTION_ERROR", "TOOL_RESULT_TOO_LARGE",
    "OPTION_UNKNOWN", "OPTION_UNSUPPORTED", "OPTION_CONFLICT", "TOOL_UNSUPPORTED", "THINKING_UNSUPPORTED",
    "ASSISTANT_SOURCE_REQUIREMENT_UNMET", "ASSISTANT_RESPONSE_EMPTY", "ASSISTANT_RESPONSE_TRUNCATED",
    "ASSISTANT_RESPONSE_INCOMPLETE", "ASSISTANT_PRESET_NOT_ALLOWED", "ASSISTANT_PRESET_NOT_AVAILABLE",
    "MODEL_REQUEST_ERROR", "TOOL_CONVERSATION_ERROR", "TRACE_WRITE_ERROR", "NETWORK_CONFIRMATION_REQUIRED",
    "QUALIFICATION_REQUEST_LIMIT", "QUALIFICATION_IDENTITY_MISMATCH", "MODEL_IDENTITY_MISMATCH",
    "QUALIFICATION_NORMALIZATION_MISMATCH", "QUALIFICATION_INVALID_TRANSPORT",
    "QUALIFICATION_TOKEN_BUDGET_UNAVAILABLE", "QUALIFICATION_FAILED", "QUALIFICATION_REPORT_ERROR",
    "QUALIFICATION_UNSAFE_LOGGING",
    "QUALIFICATION_PROJECTION_MISMATCH",
    "INVALID_STREAM_EVENT", "INVALID_STREAM_STATE", "STREAM_INTERRUPTED", "STREAM_TRUNCATED",
    "STREAM_CHUNK_LIMIT", "STREAM_BUFFER_LIMIT", "STREAM_UNSUPPORTED", "TOOL_STREAM_TRANSPORT_NOT_IMPLEMENTED",
})


def safe_code(code):
    return code if isinstance(code, str) and (code in SAFE_CODES or re.fullmatch(r"HTTP_[1-5][0-9]{2}", code)) else "QUALIFICATION_FAILED"


class QualificationError(ValueError):
    def __init__(self, code="INVALID_QUALIFICATION_MANIFEST"):
        self.code = code
        super().__init__(code)  # Input content and paths never appear in the error.


def _credentials(root):
    location = private_project_location(root)
    return CredentialStore(location.env_path, private_location=location)


class _RunTrace(JsonlTraceSink):
    """Reuse existing record_* methods, retain only small run-local trace entries."""
    def __init__(self):
        super().__init__(Path("unused-qualification-trace"),
            tool_names=("get_current_water_quality", "search_fishery_knowledge"))
        self.entries = []

    def _append(self, entry):
        self.entries.append({"kind": entry["kind"], "status": entry["status"],
                             "error_code": safe_code(entry["error_code"]) if entry["error_code"] else None})

def _code(code):
    if code in {"TOOL_REQUEST_ALREADY_EXECUTED", "TOOL_CALL_ALREADY_EXECUTED", "MODEL_RESPONSE_TRUNCATED",
        "MODEL_RESPONSE_EMPTY", "MODEL_RESPONSE_INCOMPLETE", "MODEL_TOOL_CALL_INCOMPLETE",
        "QUALIFICATION_PATH_MISMATCH", "QUALIFICATION_RESULT_CONTEXT_MISMATCH",
        "QUALIFICATION_RELEASE_SCOPE_MISMATCH", "QUALIFICATION_PRODUCT_PROMPT_MISMATCH"}:
        return code
    if code in {"INVALID_STREAM_EVENT", "INVALID_STREAM_STATE", "STREAM_INTERRUPTED", "STREAM_TRUNCATED",
                "STREAM_CHUNK_LIMIT", "STREAM_BUFFER_LIMIT", "STREAM_UNSUPPORTED",
                "TOOL_STREAM_TRANSPORT_NOT_IMPLEMENTED", "QUALIFICATION_STREAMING_SCOPE_MISMATCH"}:
        return code
    return safe_code(code)


class _ExperimentGateway:
    """Observe without retaining response text/arguments; impose the case ceiling."""
    def __init__(self, gateway, runtime, registry, case, *, assistant_product=False, streaming=False):
        self.gateway, self.runtime, self.registry, self.case = gateway, runtime, registry, case
        self.assistant_product = assistant_product
        self.streaming = streaming
        self.rows = []
        self.contexts = []  # Transient tool protocol data, never serialized.

    def complete(self, request, runtime):
        if self.streaming:
            raise GatewayError("QUALIFICATION_INVALID_TRANSPORT")
        return self._complete(request, runtime)

    def complete_tool_stream(self, request, runtime):
        if not self.streaming:
            raise GatewayError("QUALIFICATION_INVALID_TRANSPORT")
        return self._complete(request, runtime)

    def _complete(self, request, runtime):
        check_cancelled()
        if len(self.rows) >= self.case.max_requests:
            raise GatewayError("QUALIFICATION_REQUEST_LIMIT")
        if (runtime is not self.runtime or runtime.max_retries != 0
                or tuple(tool.name for tool in request.tools) != self.case.exposed_tools):
            raise GatewayError("QUALIFICATION_IDENTITY_MISMATCH")
        if self.assistant_product and (request.messages[0].role != "system"
                or request.messages[0].content != MULTI_ROUND_SYSTEM_INSTRUCTION):
            raise GatewayError("QUALIFICATION_PRODUCT_PROMPT_MISMATCH")
        row = {"request_number": len(self.rows) + 1, "tool_definitions": list(self.case.exposed_tools),
            "tool_choice": request.tool_choice, "outcome": "started", "error_code": None}
        self.rows.append(row)
        self.contexts.append(tuple((message.tool_call_id, message.content)
            for message in request.messages if message.role == "tool"))
        observation_index = len(getattr(self.gateway, "observations", ()))
        try:
            response = (self.gateway.complete_tool_stream if self.streaming else self.gateway.complete)(request, runtime)
            if not isinstance(response, ModelResponse):
                raise GatewayError("INVALID_RESPONSE")
            summary = response_summary
            if self.streaming:
                from .streaming_observation import stream_response_summary
                summary = stream_response_summary
            row.update(normalized=summary(response, runtime.model, self.registry, self.case.exposed_tools),
                usage=asdict(response.usage or Usage()),
                returned_model=runtime.model if response.returned_model == runtime.model else None,
                outcome="tool_calls" if response.tool_calls else "final_answer")
            if response.returned_model != runtime.model:
                raise GatewayError("MODEL_IDENTITY_MISMATCH")
            # No handler/follow-up is authorized for the one-request concept case.
            if self.case.max_requests == 1 and response.tool_calls:
                raise GatewayError("QUALIFICATION_PATH_MISMATCH")
            if self.case.max_requests < 3 and len(self.rows) >= self.case.max_requests and response.tool_calls:
                raise GatewayError("QUALIFICATION_REQUEST_LIMIT")  # No execution without a final request slot.
            return response
        except GatewayError as error:
            row.update(outcome="failed", error_code=_code(error.code))
            if isinstance(error, StreamingModelError):
                row.update(usage=asdict(error.usage), finish_reason=error.finish_reason)
                raise StreamingModelError(_code(error.code), usage=error.usage, finish_reason=error.finish_reason) from None
            raise GatewayError(_code(error.code)) from None
        except Exception:
            row.update(outcome="failed", error_code="QUALIFICATION_FAILED")
            raise GatewayError("QUALIFICATION_FAILED") from None
        finally:
            observations = getattr(self.gateway, "observations", ())
            row["provider_observation"] = dict(observations[observation_index]) if len(observations) > observation_index else {
                "available": False, "normalized_call_consistent": None}

def write_report(root, report):
    """Fixed generated boundary; no user-selected output or credential paths."""
    root = Path(root).absolute()
    folder = root / "outputs" / "assistant-qualification"
    try:
        boundaries = [root, root / "outputs", folder]
        for path in boundaries:
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise OSError
            else:
                path.mkdir()
        identifier = report["run_id"]
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError
        with (folder / (identifier + ".json")).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return (folder / (identifier + ".json")).relative_to(root / "outputs" / "assistant-qualification").as_posix()
    except (OSError, ValueError, KeyError, TypeError):
        raise QualificationError("QUALIFICATION_REPORT_ERROR") from None
