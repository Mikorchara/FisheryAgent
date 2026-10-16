"""One management candidate probe; no Web publication and no new Tool loop.

Uses isolated SQLite/Policy and the formal ManagementAssistantService. Product
Web gates remain closed; only this consent-bound candidate experiment constructs
a server-only PreparedAssistantTurn with execution permission for one claim.
"""
from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import logging
import uuid

from ..runtime.assistant import AssistantRequest, assistant_profile
from ..runtime.sources import SourceRequirement as Requirement, requirement_satisfied_by_ledger
from ..runtime.streaming_contracts import streaming_scope
from apps.ai_backend.contracts import utcnow
from apps.ai_backend.credential_paths import CredentialLocationError
from apps.ai_backend.credentials import CredentialFileError
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION, TRANSCRIPT_KIND, TRANSCRIPT_NOTICE
from fishery_ai.knowledge import KnowledgeService
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.model_options import Support
from apps.ai_backend.tool_conversation import ToolModelTransport, ToolExecutionStep
from apps.ai_backend.tools.policy import ToolPolicy
from .qualification_support import (
    QualificationError, _credentials, _RunTrace, write_report)
from .qualification_support import _ExperimentGateway, _code
from .qualification_adapter import QualificationAdapter
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from ..bindings import bind_tools
from ..contracts import PreparedAssistantTurn
from ..execution import _json, data_bindings
from ..service import ManagementAssistantService
from ..streaming import STREAMING_PRESET, STREAMING_TOOLS, load_streaming_config

WATER, KNOWLEDGE = STREAMING_TOOLS
DEVICE = 'qualification-pond'
VERSION = 'management-streaming-qualification@2'
LOCAL_ERRORS = frozenset({'QUALIFICATION_MANAGEMENT_SCOPE_MISMATCH', 'QUALIFICATION_BUDGET_MISMATCH',
    'QUALIFICATION_PLAN_CHANGED', 'QUALIFICATION_REQUEST_NOT_APPROVED', 'QUALIFICATION_PROTOCOL_UNOBSERVED',
    'QUALIFICATION_WORKSPACE_ERROR', 'QUALIFICATION_SOURCE_BINDING_MISMATCH'})


@dataclass(frozen=True)
class Case:
    case_id: str
    question: str = field(repr=False)
    oxygen: float
    expected_tools: tuple[str, ...]
    requirements: tuple[Requirement, ...]
    exposed_tools: tuple[str, ...] = STREAMING_TOOLS
    max_requests: int = 3


CASES = (
    Case('direct-final', '什么是溶氧？请简短解释概念，不需要当前现场数据，也不需要项目检索。',
         6.4, (), (Requirement.AUTO,)),
    Case('current-water', '请查询当前水质，简短说明观测数据与状态，不需要检索项目知识。',
         6.4, (WATER,), (Requirement.CURRENT_OBSERVATION_QUERY,)),
    Case('low-oxygen', '请先查询当前水质；如有低氧异常，再检索项目知识解释相关背景，最后简短说明并区分两类来源。',
         2.2, STREAMING_TOOLS, (Requirement.CURRENT_OBSERVATION_QUERY, Requirement.PROJECT_KNOWLEDGE_SEARCH)),
)


def get_case(case_id):
    case = next((c for c in CASES if c.case_id == case_id), None)
    if case is None:
        raise QualificationError('INVALID_MULTI_ROUND_CASE')
    return case


class _NoDataAccess:
    def query(self):
        raise AssertionError('dry-run definitions must not query data')


def _scope(profile, policy, registry, knowledge):
    return {'runtime': streaming_scope(profile, policy, registry, DEFAULT_HISTORY_PROJECTION),
            'data_bindings': data_bindings(knowledge)}


def _record(scope, config):
    records = [r for r in config.releases
               if json.loads(r.runtime.scope_json) == scope['runtime']
               and json.loads(r.data_bindings_json) == scope['data_bindings']]
    if len(records) != 1:
        raise QualificationError('QUALIFICATION_MANAGEMENT_SCOPE_MISMATCH')
    return records[0]


def plan(case_id):
    """No CredentialStore, SQLite, user Policy, SDK client or filesystem writes."""
    case = get_case(case_id)
    profile = assistant_profile(STREAMING_PRESET)
    knowledge = KnowledgeService(files('fishery_ai').joinpath('resources/knowledge/eel_knowledge.json'))
    registry = bind_tools(_NoDataAccess(), DEVICE, knowledge)
    policy = ToolPolicy('assistant', True, STREAMING_TOOLS)
    scope = _scope(profile, policy, registry, knowledge)
    config = load_streaming_config()
    record = _record(scope, config)
    if (profile.max_retries != 0 or profile.total_timeout_s != 120
            or profile.capabilities.tool_calling != Support.SUPPORTED
            or profile.capabilities.streaming != Support.SUPPORTED
            or scope['runtime']['thinking'] != 'off' or profile.default_response_mode != 'normal'):
        raise QualificationError('QUALIFICATION_IDENTITY_MISMATCH')
    encoded = profile.preset_protocol_spec.encode(profile.default_generation,
        profile.default_reasoning, streaming=True, include_usage=False)
    field = profile.preset_protocol_spec.max_output_tokens_field
    if (record.runtime.max_output_tokens != 512 or field is None
            or encoded.get(field) is not None and encoded[field] < 512):
        raise QualificationError('QUALIFICATION_BUDGET_MISMATCH')
    result = {'experiment_version': VERSION, 'backend_implementation': 'apps.ai_backend@1',
        'case_id': case.case_id, 'scope': scope,
        'scope_sha256': hashlib.sha256(_json(scope).encode()).hexdigest(),
        'release_status': record.runtime.status, 'web_flag_enabled': config.enabled,
        'config_sha256': hashlib.sha256(_json(asdict(config)).encode()).hexdigest(),
        'model_transport': 'STREAMING', 'thinking': 'off', 'history': 'EMPTY',
        'history_framing_sha256': hashlib.sha256(_json([TRANSCRIPT_KIND, TRANSCRIPT_NOTICE]).encode()).hexdigest(),
        'exposed_tools': list(STREAMING_TOOLS), 'expected_tools': list(case.expected_tools),
        'requirements': [r.value for r in case.requirements],
        'expected_requests': len(case.expected_tools)+1, 'max_model_requests': 3,
        'max_tool_calls': 2, 'max_tool_rounds': 2, 'max_output_tokens': 512,
        'encoded_output_field': field, 'retry': 0, 'turn_deadline_s': 120,
        'timeouts_s': [profile.connect_timeout_s, profile.read_timeout_s, profile.total_timeout_s],
        'question_sha256': hashlib.sha256(case.question.encode()).hexdigest(),
        'fixture': {'version': 'management-sqlite-window@1', 'device_id': DEVICE, 'seed': 42,
            'temperature_c': 28, 'ph': 7.5, 'dissolved_oxygen_mg_l': case.oxygen,
            'aggregation': 'window_mean', 'duration_s': 10, 'clock': 'FROZEN_FOR_FIXTURE',
            'source_kind': 'simulator', 'visual': 'NOT_PROVIDED'},
        'openai_sdk_version': version('openai'), 'done_marker': 'NOT_OBSERVABLE_BY_SDK',
        'http_sse_exercised': False, 'human_review_required': True, 'release_eligible': False}
    result['plan_sha256'] = hashlib.sha256(_json(result).encode()).hexdigest()
    return result


class _Trace(_RunTrace):
    def __init__(self):
        super().__init__()
        self.result = None  # Transient formal result, never written as a payload.

    def record_assistant(self, result, **timing):
        self.result = result
        super().record_assistant(result, **timing)


class _Adapter(QualificationAdapter):
    def _kwargs(self, request, runtime, *, stream, _assemble_tools=False):
        result = super()._kwargs(request, runtime, stream=stream, _assemble_tools=_assemble_tools)
        field = runtime.protocol_spec.max_output_tokens_field
        if runtime.transport_output_token_limit != 512 or result.get(field) != 512:
            raise GatewayError('QUALIFICATION_BUDGET_MISMATCH')
        self._stream_row.update(encoded_max_output_tokens=result[field], encoded_stream=result['stream'])
        return result


class _Gateway:
    """Bind the existing observer to the Runtime frozen by ManagementAssistantService."""
    def __init__(self, adapter, registry, case):
        self.adapter, self.registry, self.case, self.observed = adapter, registry, case, None

    def complete_tool_stream(self, request, runtime):
        if self.observed is None:
            self.observed = _ExperimentGateway(self.adapter, runtime, self.registry, self.case,
                assistant_product=True, streaming=True)
        response = self.observed.complete_tool_stream(request, runtime)
        row = self.observed.rows[-1]
        # Captured before control returns to the only Runtime loop / Executor.
        row['handoff_after_cleanup'] = all(row['provider_observation'].get(k) is True for k in
            ('sdk_iterator_exhausted', 'assembly_complete', 'sdk_stream_closed', 'sdk_client_closed'))
        return response


def _workspace(root):
    root = Path(root).absolute()
    folder = root
    for part in ('', 'outputs', 'assistant-qualification', '.management-work'):
        if part:
            folder = folder/part
        if folder.exists() or folder.is_symlink():
            info = folder.lstat()
            if folder.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise QualificationError('QUALIFICATION_WORKSPACE_ERROR')
        else:
            folder.mkdir()
    return folder


def _monitoring(folder, case):
    now = utcnow()
    monitoring = MonitoringService(MonitoringRepository(folder/'monitor.sqlite3'),
        device_names={DEVICE: '隔离资格测试池'}, clock=lambda: now)
    batch = Simulator(start=now-timedelta(seconds=10), device_id=DEVICE,
        session_id='management-qualification', seed=42).advance()
    batch['visual'] = None
    for key, value in (('temperature_c', 28), ('ph', 7.5), ('dissolved_oxygen_mg_l', case.oxygen)):
        batch['water']['metrics'][key].update(mean=value, min=value, max=value, latest=value)
    monitoring.ingest(batch)
    return monitoring


def _safe_error(error):
    code = getattr(error, 'code', None)
    return code if code in LOCAL_ERRORS else _code(code)


def run(case_id, root, *, confirm_network=False, approved_plan_sha256=None,
        credential_store=None, adapter_factory=None, answer_reviewer=None, handle=None):
    approved, case = plan(case_id), get_case(case_id)
    report = {'schema_version': 1, 'run_id': uuid.uuid4().hex, 'plan': approved,
        'status': 'not_executed', 'success': False, 'technical_success': False,
        'qualification_verdict': 'NOT_RUN', 'human_review_status': 'NOT_RUN', 'release_eligible': False,
        'error_code': 'NETWORK_CONFIRMATION_REQUIRED', 'request_count': 0,
        'actual_network_requests': 0, 'transport_attempts': 0, 'requests': [], 'executions': [],
        'ledger': {'entries': []}, 'requirements': [], 'product_commit_gate_passed': False,
        'trace_sink': 'run_local_memory_then_safe_report',
        'evidence_kind': 'offline_fixture' if adapter_factory else 'real_provider',
        'remote_compute_stopped': 'UNKNOWN', 'http_sse_exercised': False}
    if confirm_network is not True:
        return report
    if approved_plan_sha256 != approved['plan_sha256']:
        raise QualificationError('QUALIFICATION_PLAN_CHANGED')
    handle, trace, adapter, gateway = handle or RequestHandle(), _Trace(), None, None
    report['started_at'] = utcnow().isoformat()
    try:
        if any(logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in
                ('openai', 'openai._base_client', 'httpx', 'httpcore')):
            raise GatewayError('QUALIFICATION_UNSAFE_LOGGING')
        with TemporaryDirectory(prefix='turn-', dir=_workspace(root)) as temporary:
            folder = Path(temporary)
            monitoring = _monitoring(folder, case)
            baseline = monitoring.repository.read(DEVICE, 'water')
            credentials = credential_store if credential_store is not None else _credentials(Path(root))
            service = ManagementAssistantService(monitoring, credentials=credentials, traces=trace,
                policy_directory=folder/'policies', gateway_factory=lambda: gateway)
            selected = service.policy_store.default_selections()
            selected['modes']['assistant']['selected_tools'] = list(STREAMING_TOOLS)
            service.policy_store.save(selected)  # Isolated fixture, never outputs/tool-policies.
            profile, policy, decision, registry = service._configuration(STREAMING_PRESET, DEVICE,
                transport=ToolModelTransport.STREAMING)
            scope = _scope(profile, policy, registry, service.knowledge)
            if scope != approved['scope'] or plan(case_id) != approved or decision.max_output_tokens != 512:
                raise QualificationError('QUALIFICATION_PLAN_CHANGED')
            adapter = (adapter_factory or _Adapter)(profile.model, registry, STREAMING_TOOLS, 512, streaming=True)
            gateway = _Gateway(adapter, registry, case)
            # Explicit one-case candidate probe, not a release/flag change. No Web caller can construct this.
            prepared = PreparedAssistantTurn(AssistantRequest(STREAMING_PRESET, case.question,
                source_requirement=case.requirements[0]), DEVICE, service.epoch, profile, policy, registry,
                replace(decision, can_send=True))
            result = service.execute_turn(prepared, handle)
            observed = gateway.observed
            rows = observed.rows if observed else []
            formal = trace.result
            ledger = formal.source_ledger if formal else None
            requirements = [{'requirement': r.value, 'satisfied': bool(ledger and requirement_satisfied_by_ledger(r, ledger))}
                            for r in case.requirements]
            for step in formal.execution.steps if formal else ():
                if not isinstance(step, ToolExecutionStep):
                    continue
                after = step.model_request_index
                included = bool(step.result and observed and after < len(observed.contexts)
                    and (step.tool_call_id, step.result.to_json()) in observed.contexts[after])
                stream = rows[after-1]['provider_observation'] if after <= len(rows) else {}
                payload = step.result.payload if step.result else {}
                capture = payload.get('water_quality') or {}
                report['executions'].append({'seq': step.seq, 'tool_round': step.tool_round,
                    'tool_name': step.tool_name if step.tool_name in STREAMING_TOOLS else 'unknown_tool',
                    'handler_started': step.handler_started, 'status': step.result.status.value if step.result else None,
                    'duration_ms': step.duration_ms, 'actual_result_in_next_request': included,
                    'executed_after_stream_cleanup': step.handler_started and rows[after-1].get('handoff_after_cleanup') is True and all(stream.get(k) is True for k in
                        ('sdk_iterator_exhausted', 'assembly_complete', 'sdk_stream_closed', 'sdk_client_closed')),
                    'observation': {'device_matches': payload.get('device_id') == DEVICE,
                        'batch_matches': payload.get('batch_id') == baseline['batch_id'],
                        'time_matches': capture.get('observed_at') == baseline['observed_at'],
                        'source_binding_matches': payload.get('projection_version') == approved['scope']['data_bindings']['water'],
                        'values_match_fixture': all(capture.get(k) == v for k, v in (
                            ('temperature_c', 28), ('ph', 7.5), ('dissolved_oxygen_mg_l', case.oxygen))),
                        'batch_id': payload.get('batch_id'), 'source_kind': payload.get('source_kind'),
                        'observed_at': capture.get('observed_at'), 'evaluated_at': payload.get('evaluated_at'),
                        'quality': capture.get('quality'), 'freshness': capture.get('freshness'),
                        'rule_version': payload.get('rule_version')} if step.tool_name == WATER else None})
            path = tuple(e['tool_name'] for e in report['executions'] if e['handler_started']) == case.expected_tools
            context = all(e['actual_result_in_next_request'] and e['executed_after_stream_cleanup'] for e in report['executions'])
            source = all(all(e['observation'][key] is True for key in
                ('device_matches', 'batch_matches', 'time_matches', 'source_binding_matches', 'values_match_fixture'))
                for e in report['executions'] if e['tool_name'] == WATER and e['handler_started'])
            protocol = bool(rows) and all(row.get('normalized', {}).get('provider_model_matches') is True
                and all(row['provider_observation'].get(k) is True for k in ('available', 'assembly_complete',
                    'normalized_call_consistent', 'normalized_metadata_consistent', 'sdk_iterator_exhausted',
                    'sdk_stream_closed', 'sdk_client_closed'))
                and row['provider_observation'].get('encoded_max_output_tokens') == 512 for row in rows)
            report.update(product_commit_gate_passed=result['successful_turn'], trace_recorded=result['trace_recorded'],
                activity=result['activity'], usage=result['usage'], final_answer_present=bool(result['final_text']),
                final_finish_reason=result['final_finish_reason'], expected_path_matches=path,
                result_context_matches=context, source_binding_matches=source, provider_protocol_verified=protocol,
                ledger=ledger.to_dict() if ledger else {'entries': []},
                requirements=requirements, requirement_satisfied=all(r['satisfied'] for r in requirements),
                history_projection={'projection_id': DEFAULT_HISTORY_PROJECTION.value,
                    'received': result['history_turns_received'], 'sent': result['history_turns_sent']},
                total_latency_ms=result['total_latency_ms'],
                web_can_send_after_probe=service.bootstrap(DEVICE)['presets'][0]['streaming']['can_send'])
            error = result['error_code'] or ('ASSISTANT_SOURCE_REQUIREMENT_UNMET' if not report['requirement_satisfied'] else
                'QUALIFICATION_SOURCE_BINDING_MISMATCH' if not source else
                'QUALIFICATION_PATH_MISMATCH' if not path else 'QUALIFICATION_RESULT_CONTEXT_MISMATCH' if not context else
                'QUALIFICATION_PROTOCOL_UNOBSERVED' if not protocol else None)
            report.update(success=result['successful_turn'] and not error, status='completed' if not error else 'failed', error_code=error)
            if answer_reviewer and result['successful_turn']:
                try:
                    answer_reviewer(result['final_text'])  # Already redacted by formal Assistant; never in JSON.
                    report['human_review_status'] = 'PREVIEWED_NOT_APPROVED'
                except Exception:
                    report['human_review_status'] = 'PREVIEW_UNAVAILABLE'
            else:
                report['human_review_status'] = 'PENDING' if result['successful_turn'] else 'NOT_AVAILABLE'
    except (CredentialFileError, CredentialLocationError):
        report.update(status='failed', error_code='CREDENTIAL_FILE_ERROR')
    except KeyboardInterrupt:
        handle.cancel()
        report.update(status='cancelled', error_code='USER_CANCELLED')
    except Exception as error:
        report.update(status='failed', error_code=_safe_error(error))
    finally:
        handle.finish(report['error_code'])
        rows = gateway.observed.rows if gateway and gateway.observed else []
        attempts = getattr(adapter, 'request_attempts', 0) if adapter else 0
        if handle.error_code == 'USER_CANCELLED':
            report.update(status='cancelled', success=False, error_code='USER_CANCELLED')
        report.update(technical_success=report['success'], qualification_verdict='PENDING_MANUAL_REVIEW' if report['success'] else 'FAILED',
            request_id=handle.request_id, requests=rows, request_count=len(rows), transport_attempts=attempts,
            actual_network_requests=attempts if adapter_factory is None else 0, backend_io_closed=handle.io_closed,
            trace=trace.entries, handle_state=handle.state, finished_at=utcnow().isoformat())
    return report
