"""One consent-bound three-Tool candidate probe; reuses existing qualification helpers."""
from dataclasses import dataclass, field, replace
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
import logging
import uuid

from fishery_ai.knowledge import KnowledgeService
from apps.ai_backend.contracts import utcnow
from apps.ai_backend.credentials import CredentialFileError
from apps.ai_backend.credential_paths import CredentialLocationError
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_options import GenerationOptions
from apps.ai_backend.tool_conversation import ToolExecutionStep
from ..business_tools.registry import bind_tools, HISTORY_CANDIDATE_TOOL_NAMES, FORMAL_TOOL_NAMES
from ..business_tools.water_quality_history import WATER_QUALITY_HISTORY
from ..contracts import PreparedAssistantTurn
from ..normal_selection import NORMAL_SELECTION_CANDIDATE, normal_selection_scope, load_normal_selection_candidate
from ..runtime.assistant import AssistantRequest, assistant_profile
from ..runtime.release_contracts import _json, _hash
from ..runtime.sources import SourceRequirement as Requirement, requirement_satisfied_by_ledger
from ..service import ManagementAssistantService
from . import history_qualification as history
from .qualification_support import QualificationError, _credentials, _ExperimentGateway, _code, write_report
from .streaming_qualification import _NoDataAccess, _workspace

VERSION = 'management-normal-selection-qualification@1'
WATER, KNOWLEDGE = FORMAL_TOOL_NAMES
HISTORY = WATER_QUALITY_HISTORY


@dataclass(frozen=True)
class Case:
    case_id: str
    question: str = field(repr=False)
    expected_tools: tuple[str, ...]
    requirements: tuple[Requirement, ...]
    exposed_tools: tuple[str, ...] = HISTORY_CANDIDATE_TOOL_NAMES
    max_requests: int = 3


CASES = (
    Case('current-water', '请查询当前水质，简短说明本轮观测与数据状态。', (WATER,), (Requirement.CURRENT_OBSERVATION_QUERY,)),
    Case('water-history', '请查询过去30分钟溶解氧历史，简短说明窗口均值及覆盖限制。', (HISTORY,), (Requirement.HISTORICAL_WATER_QUERY,)),
    Case('project-knowledge', '请检索项目养殖知识，简短说明鳗鲡低氧表现，不需要当前或历史监测。', (KNOWLEDGE,), (Requirement.PROJECT_KNOWLEDGE_SEARCH,)),
    Case('current-history', '请先查询当前水质，再查询过去30分钟溶解氧历史，最后区分当前观测和历史窗口统计。',
         (WATER,HISTORY), (Requirement.CURRENT_OBSERVATION_QUERY,Requirement.HISTORICAL_WATER_QUERY)),
)


def get_case(case_id):
    case = next((c for c in CASES if c.case_id == case_id), None)
    if case is None:
        raise QualificationError('INVALID_QUALIFICATION_CASE')
    return case


def plan(case_id):
    case = get_case(case_id)
    profile = assistant_profile(history.PRESET)
    knowledge = KnowledgeService(files('fishery_ai').joinpath('resources/knowledge/eel_knowledge.json'))
    registry = bind_tools(_NoDataAccess(), history.DEVICE, knowledge, include_history=True)
    scope = normal_selection_scope(profile, registry, knowledge)
    if _json(scope) != load_normal_selection_candidate():
        raise QualificationError('QUALIFICATION_RELEASE_SCOPE_MISMATCH')
    encoded = profile.preset_protocol_spec.encode(GenerationOptions(max_output_tokens=1024),
        profile.default_reasoning, streaming=False, include_usage=False)
    output_field = profile.preset_protocol_spec.max_output_tokens_field
    if encoded.get(output_field) != 1024:
        raise QualificationError('QUALIFICATION_BUDGET_MISMATCH')
    # Reuse the deterministic thirty-minute dataset; no SQLite/credentials/SDK I/O.
    fixture_plan = history.plan('valid-history')
    value = dict(experiment_version=VERSION, backend_implementation='apps.ai_backend@1',
        case_id=case_id, scope=scope, scope_sha256=_hash(scope), release_status='candidate',
        web_flag_enabled=False, release_eligible=False, model_transport='NORMAL', thinking='off',
        history='EMPTY', history_framing_sha256=fixture_plan['history_framing_sha256'],
        exposed_tools=list(case.exposed_tools), expected_tools=list(case.expected_tools),
        requirements=[r.value for r in case.requirements], expected_requests=len(case.expected_tools)+1,
        max_model_requests=3, max_tool_calls=2, max_tool_rounds=2, max_output_tokens=1024,
        encoded_output_field=output_field, retry=0, turn_deadline_s=120,
        fixture=fixture_plan['fixture'], question_sha256=_hash(case.question),
        openai_sdk_version=fixture_plan['openai_sdk_version'], http_exercised=False,
        human_review_required=True)
    value['plan_sha256'] = _hash(value)
    return value


def run(case_id, root, *, confirm_network=False, approved_plan_sha256=None,
        credential_store=None, adapter_factory=None, answer_reviewer=None, handle=None):
    approved, case = plan(case_id), get_case(case_id)
    report = dict(schema_version=1, run_id=uuid.uuid4().hex, plan=approved, status='not_executed',
        error_code='NETWORK_CONFIRMATION_REQUIRED', success=False, technical_success=False,
        qualification_verdict='NOT_RUN', human_review_status='NOT_RUN', release_eligible=False,
        request_count=0, actual_network_requests=0, transport_attempts=0, requests=[], executions=[],
        answer_quality_evaluated=False, http_exercised=False,
        evidence_kind='offline_fixture' if adapter_factory else 'real_provider')
    if confirm_network is not True:
        return report
    if approved_plan_sha256 != approved['plan_sha256']:
        raise QualificationError('QUALIFICATION_PLAN_CHANGED')
    trace = history._Trace(tool_names=case.exposed_tools)
    handle, adapter, gateway = handle or RequestHandle(), None, None
    report['started_at'] = utcnow().isoformat()
    try:
        if any(logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in
               ('openai','openai._base_client','httpx','httpcore')):
            raise QualificationError('QUALIFICATION_UNSAFE_LOGGING')
        with TemporaryDirectory(prefix='normal-selection-', dir=_workspace(root)) as temporary:
            folder = Path(temporary)
            monitoring = history._monitoring(folder, history.get_case('valid-history'))
            service = ManagementAssistantService(monitoring,
                credentials=credential_store if credential_store is not None else _credentials(Path(root)),
                traces=trace, policy_directory=folder/'policies', gateway_factory=lambda: gateway)
            selected = service.management_policy.snapshot()
            service.management_policy.save(case.exposed_tools, expected_revision=selected.revision)
            selected = service.management_policy.snapshot()
            profile, policy, decision, registry = service._configuration(history.PRESET, history.DEVICE,
                policy_snapshot=selected, execution_profile=NORMAL_SELECTION_CANDIDATE)
            if (plan(case_id) != approved or decision.can_send or
                    decision.profile.mode_reason != 'NORMAL_TOOL_CANDIDATE_NOT_RELEASED' or
                    normal_selection_scope(profile,registry,service.knowledge) != approved['scope'] or
                    policy.exposed_tools != case.exposed_tools or
                    registry.model_definitions() != service.history_registry.model_definitions()):
                raise QualificationError('QUALIFICATION_RELEASE_SCOPE_MISMATCH')
            adapter = (adapter_factory or history._Adapter)(profile.model, registry, case.exposed_tools, 1024)
            class Gateway:
                observed = None
                def complete(self, request, runtime):
                    if self.observed is None:
                        self.observed = _ExperimentGateway(adapter,runtime,registry,case,assistant_product=True)
                    return self.observed.complete(request,runtime)
            gateway = Gateway()
            # A single explicit experiment claim; never changes Web publication/config.
            prepared = PreparedAssistantTurn(AssistantRequest(history.PRESET,case.question),
                history.DEVICE,service.epoch,profile,policy,registry,replace(decision,can_send=True),
                selected.revision,selected.source)
            result = service.execute_turn(prepared,handle)
            formal = trace.result
            ledger = formal.source_ledger if formal else None
            executions = [s for s in formal.execution.steps if isinstance(s,ToolExecutionStep)] if formal else []
            observed = gateway.observed
            report['executions'] = [dict(tool_name=s.tool_name,handler_started=s.handler_started,
                status=s.result.status.value if s.result else None,
                actual_result_in_next_request=bool(s.result and observed and s.model_request_index < len(observed.contexts)
                    and (s.tool_call_id,s.result.to_json()) in observed.contexts[s.model_request_index])) for s in executions]
            path = tuple(s.tool_name for s in executions if s.handler_started) == case.expected_tools
            context = all(e['actual_result_in_next_request'] for e in report['executions'])
            satisfied = bool(ledger and all(requirement_satisfied_by_ledger(r,ledger) for r in case.requirements))
            rows = observed.rows if observed else []
            protocol = len(rows) == len(case.expected_tools)+1 and all(
                row.get('normalized',{}).get('provider_model_matches') is True and all(
                    row['provider_observation'].get(k) is True for k in
                    ('available','normalized_call_consistent','normalized_metadata_consistent')) for row in rows)
            encoded = len(adapter.encoded) == len(rows) and all(r['max_output_tokens'] == 1024 for r in adapter.encoded)
            cleanup = len(adapter.cleanup) == len(rows) and all(r['sdk_client_close_completed'] for r in adapter.cleanup)
            error = result['error_code'] or ('ASSISTANT_SOURCE_REQUIREMENT_UNMET' if not satisfied else
                'QUALIFICATION_PATH_MISMATCH' if not path else 'QUALIFICATION_RESULT_CONTEXT_MISMATCH' if not context else
                'QUALIFICATION_PROTOCOL_UNOBSERVED' if not protocol or not encoded or not cleanup else None)
            report.update(status='failed' if error else 'completed',error_code=error,
                success=result['successful_turn'] and not error, product_commit_gate_passed=result['successful_turn'],
                expected_path_matches=path,result_context_matches=context,requirement_satisfied=satisfied,
                provider_protocol_verified=protocol,encoded_budget_verified=encoded,clients_closed=cleanup,
                ledger=ledger.to_dict() if ledger else {'entries':[]},usage=result['usage'],
                total_latency_ms=result['total_latency_ms'],activity=result['activity'])
            report['human_review_status'] = 'PENDING' if result['successful_turn'] else 'NOT_AVAILABLE'
            if answer_reviewer and result['successful_turn']:
                answer_reviewer(result['final_text']); report['human_review_status']='PREVIEWED_NOT_APPROVED'
    except (CredentialFileError,CredentialLocationError):
        report.update(status='failed',error_code='CREDENTIAL_FILE_ERROR')
    except KeyboardInterrupt:
        handle.cancel(); report.update(status='cancelled',error_code='USER_CANCELLED',success=False)
    except Exception as error:
        report.update(status='failed',error_code=_code(getattr(error,'code',None)),success=False)
    finally:
        handle.finish(report['error_code'])
        if handle.error_code == 'USER_CANCELLED':
            report.update(status='cancelled',success=False,error_code='USER_CANCELLED')
        rows = gateway.observed.rows if gateway and gateway.observed else []
        attempts = getattr(adapter,'request_attempts',0) if adapter else 0
        report.update(technical_success=report['success'],qualification_verdict='PENDING_MANUAL_REVIEW' if report['success'] else 'FAILED',
            requests=rows,request_count=len(rows),transport_attempts=attempts,
            actual_network_requests=attempts if adapter_factory is None else 0,
            backend_io_closed=handle.io_closed,handle_state=handle.state,trace=trace.entries,finished_at=utcnow().isoformat())
    return report
