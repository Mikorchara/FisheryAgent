"""One approved Assistant experiment; no publisher, discovery or history loading."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
import hashlib
import json
import logging
import os
import re
import stat
import time
import uuid

from .assistant import AssistantError, AssistantRequest, AssistantService, assistant_profile
from .assistant_sources import SourceRequirement, TurnSourceReceipt, requirement_satisfied
from .contracts import Usage
from .credential_paths import CredentialLocationError, private_project_location
from .credentials import CredentialFileError, CredentialStore
from .domain import DiagnosisService
from .execution import RequestHandle, check_cancelled, request_scope
from .knowledge import KnowledgeService
from .model_gateway import GatewayError, ModelResponse, ProfileRegistry
from .observability import JsonlTraceSink
from .qualification_adapter import FINISH_REASONS, QualificationAdapter, response_summary
from .telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from .tool_conversation import ToolCallingService, _aggregate_usage
from .tools.policy import ToolPolicy
from .tools.registry import ToolRegistry


MAX_OUTPUT_TOKENS = 256
MAX_MANIFEST_BYTES = 8192
KNOWN_CASE_IDS = frozenset({"Q1", "Q2", "Q3", "Q4"})
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
})


def safe_code(code):
    return code if isinstance(code, str) and (code in SAFE_CODES or re.fullmatch(r"HTTP_[1-5][0-9]{2}", code)) else "QUALIFICATION_FAILED"


class QualificationError(ValueError):
    def __init__(self, code="INVALID_QUALIFICATION_MANIFEST"):
        self.code = code
        super().__init__(code)  # Input content and paths never appear in the error.


@dataclass(frozen=True)
class QualificationManifest:
    preset_id: str
    question: str = field(repr=False)
    exposed_tools: tuple[str, ...]
    source_requirement: SourceRequirement = SourceRequirement.AUTO
    max_requests: int = 2
    max_output_tokens: int = 256
    retry: int = 0
    history: tuple = field(default=(), repr=False)
    confirm_network: bool = False
    case_id: str | None = None

    def __post_init__(self):
        try:
            AssistantRequest(self.preset_id, self.question, source_requirement=self.source_requirement)
            assistant_profile(self.preset_id)  # Fixed published OFF + Normal contract only.
        except (AssistantError, ValueError, TypeError):
            raise QualificationError("QUALIFICATION_PRESET_OR_QUESTION_INVALID") from None
        if (not isinstance(self.exposed_tools, (tuple, list)) or len(self.exposed_tools) > 3
                or any(not isinstance(name, str) or name not in ToolRegistry.registered_names() for name in self.exposed_tools)
                or len(set(self.exposed_tools)) != len(self.exposed_tools)):
            raise QualificationError("QUALIFICATION_TOOLS_NOT_ALLOWED")
        if (type(self.max_requests) is not int or self.max_requests not in (1, 2)
                or type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS
                or type(self.retry) is not int or self.retry != 0
                or type(self.confirm_network) is not bool or self.history not in ((), [])
                or self.case_id is not None and (not isinstance(self.case_id, str) or self.case_id not in KNOWN_CASE_IDS)):
            raise QualificationError()
        object.__setattr__(self, "exposed_tools", tuple(self.exposed_tools))
        object.__setattr__(self, "history", ())

    @classmethod
    def from_dict(cls, data):
        allowed = {"preset_id", "question", "exposed_tools", "source_requirement", "max_requests",
                   "max_output_tokens", "retry", "history", "confirm_network", "case_id"}
        if not isinstance(data, dict) or set(data) - allowed or not {"preset_id", "question", "exposed_tools"} <= set(data):
            raise QualificationError()
        # A saved file cannot grant permanent network permission. CLI consent is
        # applied to this immutable object in memory for this process invocation.
        if data.get("confirm_network", False) is not False:
            raise QualificationError("QUALIFICATION_CONFIRMATION_CLI_ONLY")
        try:
            values = dict(data)
            values["source_requirement"] = SourceRequirement(values.get("source_requirement", "AUTO"))
            return cls(**values)
        except (ValueError, TypeError, RecursionError):
            raise QualificationError() from None

    @classmethod
    def from_json(cls, path):
        def pairs(values):
            result = {}
            for key, value in values:
                if key in result:
                    raise QualificationError()
                result[key] = value
            return result
        try:
            with Path(path).open("rb") as stream:
                data = stream.read(MAX_MANIFEST_BYTES + 1)
            if len(data) > MAX_MANIFEST_BYTES:
                raise QualificationError()
            return cls.from_dict(json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs))
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            raise QualificationError() from None

    def safe_plan(self):
        profile = assistant_profile(self.preset_id)
        plan = {"preset_id": self.preset_id, "preset_display_name": profile.display_name,
                "identity": {"service_id": profile.service_id, "adapter_id": profile.adapter_id,
                             "base_url": profile.base_url, "model": profile.model},
                "contract_version": profile.preset_contract_version,
                "protocol_spec_id": profile.preset_protocol_spec.spec_id,
                "protocol_spec_version": profile.preset_protocol_spec.version,
                "thinking": "OFF", "response_mode": "Normal", "exposed_tools": list(self.exposed_tools),
                "source_requirement": self.source_requirement.value, "max_requests": self.max_requests,
                "max_output_tokens_per_request": self.max_output_tokens, "retry": 0, "history": "EMPTY",
                "case_id": self.case_id, "question_sha256": hashlib.sha256(self.question.encode("utf-8")).hexdigest(),
                "network": "AUTHORIZED_FOR_THIS_RUN" if self.confirm_network else "NOT_YET_AUTHORIZED"}
        approved = {key:value for key,value in plan.items() if key != "network"}
        plan["plan_sha256"] = hashlib.sha256(json.dumps(approved,sort_keys=True,separators=(",", ":")).encode("utf-8")).hexdigest()
        return plan


def _credentials(root):
    location = private_project_location(root)
    return CredentialStore(location.env_path, private_location=location)


def _registry():
    # CLI is a separate process: it cannot see the Web process's in-memory Store.
    # Empty Snapshot is intentional; never auto-Apply a scenario or import history.
    reader = CurrentWaterQualityReader(CurrentSnapshotStore(), stale_after_s=300)
    knowledge = KnowledgeService(files("fishery_ai").joinpath("resources/knowledge/eel_knowledge.json"))
    return ToolRegistry(reader, DiagnosisService(), knowledge=knowledge)


class _RunTrace(JsonlTraceSink):
    """Reuse existing record_* methods, retain only small run-local trace entries."""
    def __init__(self):
        super().__init__(Path("unused-qualification-trace"))
        self.entries = []

    def _append(self, entry):
        self.entries.append({"kind": entry["kind"], "status": entry["status"],
                             "error_code": safe_code(entry["error_code"]) if entry["error_code"] else None})


class _BoundedGateway:
    def __init__(self, gateway, manifest, model, registry):
        self.gateway, self.manifest, self.model, self.registry = gateway, manifest, model, registry
        self.rows = []

    def complete(self, request, runtime):
        check_cancelled()
        if len(self.rows) >= self.manifest.max_requests:
            raise GatewayError("QUALIFICATION_REQUEST_LIMIT")
        if (runtime.max_retries != 0 or runtime.model != self.model or runtime.default_response_mode != "normal"
                or tuple(tool.name for tool in request.tools) != tuple(
                    definition.name for definition in ToolPolicy("assistant", bool(self.manifest.exposed_tools),
                        self.manifest.exposed_tools).model_definitions(self.registry))):
            raise GatewayError("QUALIFICATION_IDENTITY_MISMATCH")
        row = {"request_number": len(self.rows) + 1, "tool_definitions": [tool.name for tool in request.tools],
               "knowledge_schema_required_query": any(tool.name == "search_fishery_knowledge"
                    and "query" in tool.parameters_dict().get("required", []) for tool in request.tools),
               "tool_choice": request.tool_choice, "outcome": "started", "error_code": None,
               "provider_observation": {"available": False, "normalized_call_consistent": None}}
        self.rows.append(row)  # Consume the attempt before forwarding; no retry.
        observation_index = len(getattr(self.gateway, "observations", ()))
        try:
            response = self.gateway.complete(request, runtime)
            if not isinstance(response, ModelResponse):
                raise GatewayError("INVALID_RESPONSE")
            if response.usage is not None and not isinstance(response.usage, Usage):
                raise GatewayError("INVALID_RESPONSE")
            row.update(normalized=response_summary(response, self.model, self.registry, self.manifest.exposed_tools),
                       usage=asdict(response.usage) if response.usage else None,
                       outcome="tool_calls" if response.tool_calls else "final_answer")
            observations = getattr(self.gateway, "observations", ())
            row["provider_observation"] = dict(observations[observation_index]) if len(observations) > observation_index else {
                "available": False, "normalized_call_consistent": None}
            if row["normalized"]["provider_model_matches"] is False:
                raise GatewayError("MODEL_IDENTITY_MISMATCH")
            check_cancelled()
            if self.manifest.max_requests == 1 and response.tool_calls:
                # First-request evidence only: no Handler or follow-up without budget.
                raise GatewayError("QUALIFICATION_REQUEST_LIMIT")
            return response
        except GatewayError as exc:
            row.update(outcome="cancelled" if exc.code == "USER_CANCELLED" else "failed", error_code=safe_code(exc.code))
            observations = getattr(self.gateway, "observations", ())
            if len(observations) > observation_index:
                row["provider_observation"] = dict(observations[observation_index])
            raise GatewayError(safe_code(exc.code)) from None
        except Exception:
            row.update(outcome="failed", error_code="QUALIFICATION_FAILED")
            raise GatewayError("QUALIFICATION_FAILED") from None


def run_qualification(manifest, root, *, credential_store=None, registry=None, gateway=None, handle=None):
    """Trusted composition injections are for offline tests, never manifest inputs."""
    if not isinstance(manifest, QualificationManifest):
        raise QualificationError()
    report = {"schema_version": 1, "run_id": uuid.uuid4().hex,
              "started_at": datetime.now(timezone.utc).isoformat(), "plan": manifest.safe_plan(),
              "request_count": 0, "actual_network_requests": 0, "transport_attempts": 0,
              "requests": [], "receipt": TurnSourceReceipt().to_dict(),
              "requirement_satisfied": requirement_satisfied(manifest.source_requirement, TurnSourceReceipt()),
              "tool_execution_status": None, "tool_duration_ms": None,
              "success": False, "error_code": "NETWORK_CONFIRMATION_REQUIRED", "status": "not_executed"}
    if not manifest.confirm_network:
        return report  # No credential resolution, Registry construction or SDK client.
    start = time.monotonic()
    traces = _RunTrace()
    handle = handle if handle is not None else RequestHandle()
    bounded = None
    adapter = None
    try:
        handle.start()
        with request_scope(handle):
            if any(logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in (
                    "openai", "openai._base_client", "httpx", "httpcore")):
                raise GatewayError("QUALIFICATION_UNSAFE_LOGGING")
            profile = assistant_profile(manifest.preset_id)
            credentials = credential_store if credential_store is not None else _credentials(Path(root))
            runtime = ProfileRegistry([profile], credentials).snapshot(profile.profile_id)
            if runtime.credential.status.availability not in ("PRESENT", "NONE_REQUIRED"):
                raise GatewayError("SECRET_MISSING")
            registry = registry if registry is not None else _registry()
            policy = ToolPolicy("assistant", bool(manifest.exposed_tools), manifest.exposed_tools)
            policy.validate_registry(registry)
            adapter = gateway if gateway is not None else QualificationAdapter(runtime.model, registry,
                manifest.exposed_tools, manifest.max_output_tokens)
            bounded = _BoundedGateway(adapter, manifest, runtime.model, registry)
            service = AssistantService(ToolCallingService(bounded, registry, traces, policy=policy))
            result = service.send(AssistantRequest(manifest.preset_id, manifest.question,
                source_requirement=manifest.source_requirement), runtime)
            report.update(success=result.status.value == "completed", status=result.status.value,
                error_code=safe_code(result.error_code) if result.error_code else None,
                receipt=result.source_receipt.to_dict(),
                requirement_satisfied=requirement_satisfied(manifest.source_requirement, result.source_receipt),
                tool_execution_status=result.execution.tool_result.status.value if result.execution.tool_result else None,
                tool_duration_ms=result.execution.tool_duration_ms, usage=asdict(result.execution.usage),
                final_finish_reason=(result.execution.final_finish_reason
                    if result.execution.final_finish_reason in FINISH_REASONS else None),
                final_answer_present=bool(result.final_text.strip()))
    except (CredentialFileError, CredentialLocationError):
        report.update(status="failed", error_code="CREDENTIAL_FILE_ERROR")
    except KeyboardInterrupt:
        handle.cancel()
        report.update(status="cancelled", error_code="USER_CANCELLED")
    except (GatewayError, AssistantError) as exc:
        report.update(status="cancelled" if exc.code == "USER_CANCELLED" else "failed", error_code=safe_code(exc.code))
    except Exception:
        report.update(status="failed", error_code="QUALIFICATION_FAILED")
    finally:
        handle.finish(report["error_code"])
        if handle.public_info()["error_code"] == "USER_CANCELLED":
            report.update(success=False, status="cancelled", error_code="USER_CANCELLED")
        rows = bounded.rows if bounded else []
        attempts = getattr(adapter, "request_attempts", 0) if adapter else 0
        # Preserve usage observed before a budget/identity rejection; the shared
        # Assistant cannot see a response that this wrapper had to block.
        observed_usage = _aggregate_usage([Usage(**row["usage"]) if row.get("usage") else Usage() for row in rows])
        report.update(request_id=handle.request_id, requests=rows, request_count=len(rows),
            transport_attempts=attempts, actual_network_requests=attempts,
            usage=asdict(observed_usage),
            backend_io_closed=handle.io_closed, remote_compute_stopped="UNKNOWN",
            trace=traces.entries, total_latency_ms=round((time.monotonic()-start)*1000, 3),
            finished_at=datetime.now(timezone.utc).isoformat())
    return report


def write_report(root, report):
    """Fixed generated boundary; no user-selected output or credential paths."""
    root = Path(root).absolute()
    folder = root / "outputs" / "assistant-qualification"
    try:
        for path in (root, root / "outputs", folder):
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise OSError
        folder.mkdir(parents=True, exist_ok=True)
        identifier = report["run_id"]
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError
        with (folder / (identifier + ".json")).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return identifier + ".json"
    except (OSError, ValueError, KeyError, TypeError):
        raise QualificationError("QUALIFICATION_REPORT_ERROR") from None
