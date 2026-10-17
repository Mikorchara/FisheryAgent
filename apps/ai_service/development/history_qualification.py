"""One consent-bound history candidate probe; no Web publication or new Tool loop."""
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import logging
import uuid

from apps.ai_backend.contracts import utcnow
from apps.ai_backend.credentials import CredentialFileError
from apps.ai_backend.credential_paths import CredentialLocationError
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION, TRANSCRIPT_KIND, TRANSCRIPT_NOTICE
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.model_options import GenerationOptions, Support
from apps.ai_backend.tool_conversation import ToolExecutionStep, ToolExecutionMode
from apps.ai_backend.tools import ToolRegistry, ToolDefinition
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from ..business_tools.water_quality_history import HISTORY_DEFINITION, WATER_QUALITY_HISTORY, validate_arguments
from ..contracts import PreparedAssistantTurn
from ..history_execution import (HISTORY_PROFILE, HISTORY_MAX_OUTPUT_TOKENS, HistoryCandidateConfig,
    validate_history_token_budget, history_scope, load_history_config)
from ..runtime.assistant import AssistantRequest, SYSTEM_INSTRUCTION, assistant_profile
from ..runtime.sources import SourceRequirement, requirement_satisfied_by_ledger
from ..runtime.release_contracts import _json, _hash
from ..service import ManagementAssistantService
from .qualification_adapter import QualificationAdapter
from .qualification_support import QualificationError, _credentials, _RunTrace, _ExperimentGateway, _code, write_report
from .streaming_qualification import _workspace

VERSION = 'management-history-qualification@2'
PRESET = 'dashscope-qwen38-flash-r1'
DEVICE = 'history-qualification-pond'
DO = 'dissolved_oxygen_mg_l'
MAX_OUTPUT_TOKENS = HISTORY_MAX_OUTPUT_TOKENS
QUERY_TIME = datetime(2026, 10, 17, 0, 30, tzinfo=timezone.utc)
QUESTION = ('请查询本次隔离测试设备过去30分钟的溶解氧历史，简短说明窗口均值变化、极值时间及数据覆盖限制；'
            '没有匹配数据时请明确说明，不用历史数据推断当前状态。')
LOCAL_ERRORS = frozenset({'QUALIFICATION_HISTORY_SCOPE_MISMATCH',
    'QUALIFICATION_HISTORY_RESULT_MISMATCH', 'QUALIFICATION_REGISTRY_MISMATCH',
    'QUALIFICATION_PROTOCOL_UNOBSERVED', 'QUALIFICATION_PLAN_CHANGED', 'QUALIFICATION_WORKSPACE_ERROR',
    'ASSISTANT_EXECUTION_PROFILE_CHANGED', 'ASSISTANT_SESSION_EXPIRED', 'REQUEST_ALREADY_EXECUTED'})


@dataclass(frozen=True)
class Case:
    case_id: str
    expected_status: str
    question: str = field(default=QUESTION, repr=False)
    exposed_tools: tuple[str, ...] = (WATER_QUALITY_HISTORY,)
    max_requests: int = 2


CASES = (Case('valid-history', 'OK'), Case('no-data', 'NO_DATA'), Case('partial-history', 'PARTIAL'))


def get_case(case_id):
    case = next((c for c in CASES if c.case_id == case_id), None)
    if case is None:
        raise QualificationError('INVALID_HISTORY_QUALIFICATION_CASE')
    return case


def fixture_batches(case):
    """Pure deterministic synthetic windows, never reads a user database/clock."""
    simulator = Simulator(start=QUERY_TIME-timedelta(minutes=40 if case.case_id == 'no-data' else 30),
        device_id=DEVICE, session_id='history-qualification-'+case.case_id, seed=42)
    batches = []
    for index in range(1 if case.case_id == 'no-data' else 30):
        batch = simulator.advance(60)
        batch['visual'] = None
        for key, value in (('temperature_c',28), ('ph',7.5), (DO,round(6.4-.4*(index//5),1))):
            batch['water']['metrics'][key].update(mean=value,min=value,max=value,latest=value)
        if case.case_id == 'partial-history':
            if 10 <= index < 15:
                continue  # Five minutes absent, never filled with zero/normal.
            if index == 20:
                metric = batch['water']['metrics'][DO]
                metric.update(mean=None,min=None,max=None,latest=None,valid_samples=0,
                              invalid_samples=batch['water']['sample_count'])
        batches.append(batch)
    return tuple(batches)


def _unavailable_handler(*args, **kwargs):
    raise AssertionError('plan definitions cannot execute a Tool')


def plan(case_id):
    """No SQLite, user Policy, credentials, SDK client, network, or writes."""
    validate_history_token_budget(MAX_OUTPUT_TOKENS)
    case = get_case(case_id)
    profile = assistant_profile(PRESET)
    registry = ToolRegistry([ToolDefinition(HISTORY_DEFINITION, _unavailable_handler,
                                           validate_arguments=validate_arguments)])
    # Qualification keeps the approved closed candidate manifest. Product trial
    # status is a separate user approval, not a new qualification verdict/hash.
    config = HistoryCandidateConfig(load_history_config().scope_json)
    scope = history_scope(profile, registry)
    if (_json(scope) != config.scope_json or config.enabled or config.status != 'candidate'
            or profile.capabilities.tool_calling != Support.SUPPORTED
            or scope['runtime']['thinking'] != 'off' or scope['transport'] != 'NORMAL'
            or scope['runtime']['tools'] != [WATER_QUALITY_HISTORY]
            or scope['budget'] != {'calls':1,'rounds':1,'requests':2,'retry':0,'deadline_s':120,
                                  'max_output_tokens':MAX_OUTPUT_TOKENS}):
        raise QualificationError('QUALIFICATION_HISTORY_SCOPE_MISMATCH')
    encoded = profile.preset_protocol_spec.encode(GenerationOptions(max_output_tokens=MAX_OUTPUT_TOKENS),
        profile.default_reasoning, streaming=False, include_usage=False)
    output_field = profile.preset_protocol_spec.max_output_tokens_field
    if output_field is None or encoded.get(output_field) != MAX_OUTPUT_TOKENS:
        raise QualificationError('QUALIFICATION_BUDGET_MISMATCH')
    result = {'experiment_version':VERSION,'backend_implementation':'apps.ai_backend@1',
        'case_id':case.case_id,'scope':scope,'scope_sha256':_hash(scope),
        'config_sha256':_hash(asdict(config)),'execution_profile':HISTORY_PROFILE,
        'release_status':'candidate','web_flag_enabled':False,'release_eligible':False,
        'model_transport':'NORMAL','thinking':'off','history':'EMPTY',
        'history_framing_sha256':_hash([TRANSCRIPT_KIND,TRANSCRIPT_NOTICE]),
        'tool_schema':HISTORY_DEFINITION.parameters_dict(),
        'exposed_tools':[WATER_QUALITY_HISTORY],'expected_tools':[WATER_QUALITY_HISTORY],
        'policy':{'mode':'assistant','llm_tool_calling':True,'exposed_tools':[WATER_QUALITY_HISTORY]},
        'source_requirement':SourceRequirement.HISTORICAL_WATER_QUERY.value,
        'expected_status':case.expected_status,'expected_requests':2,
        'max_model_requests':2,'max_tool_calls':1,'max_tool_rounds':1,
        'max_output_tokens':MAX_OUTPUT_TOKENS,'encoded_output_field':output_field,
        'profile_default_max_output_tokens':profile.default_generation.max_output_tokens,
        'normal_stream_encoding':'OMITTED_SDK_DEFAULT_FALSE',
        'retry':0,'turn_deadline_s':120,
        'timeouts_s':[profile.connect_timeout_s,profile.read_timeout_s,profile.total_timeout_s],
        'question_sha256':hashlib.sha256(case.question.encode()).hexdigest(),
        'fixture':{'version':'management-history-fixture@1','device_id':DEVICE,'seed':42,
            'query_time':QUERY_TIME.isoformat(),'clock':'FROZEN_FOR_FIXTURE','lookback_minutes':30,
            'required_metric':DO,'window_duration_s':60,'source_kind':'simulator','visual':'NOT_PROVIDED',
            'dataset_sha256':_hash(fixture_batches(case))},
        'openai_sdk_version':version('openai'),'http_exercised':False,'human_review_required':True}
    result['plan_sha256'] = _hash(result)
    return result


def _monitoring(folder, case):
    clock = [QUERY_TIME]
    monitoring = MonitoringService(MonitoringRepository(folder/'history.sqlite3'),
        device_names={DEVICE:'隔离历史资格设备'},clock=lambda:clock[0])
    for batch in fixture_batches(case):
        clock[0] = datetime.fromisoformat(batch['timestamp'])
        monitoring.ingest(batch)
    clock[0] = QUERY_TIME
    return monitoring


class _Trace(_RunTrace):
    def __init__(self, *, tool_names=(WATER_QUALITY_HISTORY,)):
        super().__init__(tool_names=tool_names)
        self.result = None  # Transient execution/ledger only, never serialize this object.

    def record_assistant(self, result, **timing):
        self.result = result
        super().record_assistant(result, **timing)


class _Adapter(QualificationAdapter):
    """Reuse Normal encoding/transport; observe only encoding and close completion."""
    _validate_token_budget = staticmethod(validate_history_token_budget)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encoded, self.cleanup = [], []
        factory = self._async_client_factory
        def observed_factory(runtime, remaining):
            client = factory(runtime, remaining)
            row = {'sdk_client_close_called':False,'sdk_client_close_completed':False}
            self.cleanup.append(row)
            class ObservedClient:
                chat = client.chat
                async def close(self):
                    row['sdk_client_close_called'] = True
                    await client.close()
                    row['sdk_client_close_completed'] = True
            return ObservedClient()
        self._async_client_factory = observed_factory

    def _kwargs(self, request, runtime, **options):
        body = super()._kwargs(request, runtime, **options)
        key = runtime.protocol_spec.max_output_tokens_field
        self.encoded.append({'output_field':key,'max_output_tokens':body.get(key),
                             'stream_field_present':'stream' in body,'stream_value':body.get('stream')})
        return body


class _Gateway:
    def __init__(self, adapter, registry, case):
        self.adapter,self.registry,self.case,self.observed = adapter,registry,case,None

    def complete(self, request, runtime):
        if (not request.messages or request.messages[0].role != 'system'
                or request.messages[0].content != SYSTEM_INSTRUCTION):
            raise GatewayError('QUALIFICATION_PRODUCT_PROMPT_MISMATCH')
        if self.observed is None:
            self.observed = _ExperimentGateway(self.adapter,runtime,self.registry,self.case)
        encoded_count,cleanup_count = len(self.adapter.encoded),len(self.adapter.cleanup)
        try:
            return self.observed.complete(request,runtime)
        finally:
            if self.observed.rows:
                row = self.observed.rows[-1]
                row['formal_system_prompt_verified'] = True
                row['encoded'] = dict(self.adapter.encoded[-1]) if len(self.adapter.encoded) > encoded_count else None
                row['cleanup'] = dict(self.adapter.cleanup[-1]) if len(self.adapter.cleanup) > cleanup_count else None


def _fixture_checks(payload, case):
    """Compare independent fixture expectations, not a second statistics engine."""
    if not isinstance(payload,dict):
        return {'payload_valid':False}
    empty, partial = case.case_id == 'no-data', case.case_id == 'partial-history'
    windows, reliable = (0,0) if empty else (25,24) if partial else (30,30)
    metric = payload.get('metrics',{}).get(DO,{})
    first,last = metric.get('first'),metric.get('last')
    checks = {
        'status_matches':payload.get('status') == case.expected_status,
        'range_matches':payload.get('requested_range') == {'start':(QUERY_TIME-timedelta(minutes=30)).isoformat(),
            'end':QUERY_TIME.isoformat(),'interval':'(start,end]'} and payload.get('evaluated_at') == QUERY_TIME.isoformat(),
        'binding_matches':payload.get('projection_version') == 'management-water-history@1'
            and payload.get('device_id') == DEVICE and payload.get('source_kind') == 'simulator'
            and payload.get('aggregation') == 'window_mean',
        'coverage_matches':payload.get('counts',{}).get('matching_windows') == windows
            and metric.get('reliable_windows') == reliable
            and payload.get('coverage',{}).get('received_window_s') == windows*60
            and metric.get('reliable_window_s') == reliable*60
            and metric.get('quality_counts') == {'valid':reliable,'partial':0,'invalid':1 if partial else 0,'missing':0}
            and metric.get('valid_samples') == reliable*60
            and metric.get('invalid_samples') == (60 if partial else 0),
        'statistics_match':((first,last,metric.get('last_minus_first'),metric.get('min_window_mean'),
            metric.get('max_window_mean')) == (None,None,None,None,None) if empty else
            bool(first and last and first.get('window_mean') == 6.4 and last.get('window_mean') == 4.4
                and abs(metric.get('last_minus_first',float('inf'))+2) < 1e-9
                and metric.get('min_window_mean',{}).get('value') == 4.4
                and metric.get('max_window_mean',{}).get('value') == 6.4)),
        'limitations_preserved':'NOT_CURRENT_OBSERVATION' in payload.get('limitations',[])
            and ('INCOMPLETE_RELIABLE_COVERAGE' in payload.get('limitations',[])) == (empty or partial),
        'gaps_match':payload.get('gaps',{}).get('total_s') == (1800 if empty else 300 if partial else 0)
            and metric.get('gaps',{}).get('total_s') == (1800 if empty else 360 if partial else 0),
    }
    # Batch/time references must point to actual fixture windows, never model text.
    references = {b['batch_id']:b for b in fixture_batches(case)}
    checks['references_match'] = all(ref is None or ref.get('batch_id') in references and all(
        ref.get(key) == value for key,value in (
            ('observed_at',references[ref['batch_id']]['timestamp']),
            ('window_start',references[ref['batch_id']]['window']['start']),
            ('window_end',references[ref['batch_id']]['window']['end']),
            ('session_id',references[ref['batch_id']]['session_id'])))
        for ref in (first,last,metric.get('min_window_mean'),metric.get('max_window_mean')))
    checks['reference_values_match'] = all(ref is None or ref.get('batch_id') in references and
        references[ref['batch_id']]['water']['metrics'][DO]['mean'] == ref.get(value_key)
        for ref,value_key in ((first,'window_mean'),(last,'window_mean'),
            (metric.get('min_window_mean'),'value'),(metric.get('max_window_mean'),'value')))
    return checks


def _safe_error(error):
    code = getattr(error,'code',None)
    return code if code in LOCAL_ERRORS else _code(code)


def run(case_id, root, *, confirm_network=False, approved_plan_sha256=None,
        credential_store=None, adapter_factory=None, answer_reviewer=None, handle=None):
    approved, case = plan(case_id), get_case(case_id)
    report = {'schema_version':1,'run_id':uuid.uuid4().hex,'plan':approved,'status':'not_executed',
        'error_code':'NETWORK_CONFIRMATION_REQUIRED','success':False,'technical_success':False,
        'qualification_verdict':'NOT_RUN','human_review_status':'NOT_RUN','release_eligible':False,
        'answer_quality_evaluated':False,'answer_truthfulness_evaluated':False,
        'request_count':0,'actual_network_requests':0,'transport_attempts':0,'requests':[],'executions':[],
        'ledger':{'entries':[]},'requirement_satisfied':False,'product_commit_gate_passed':False,
        'formal_result_available':False,
        'http_exercised':False,'evidence_kind':'offline_fixture' if adapter_factory else 'real_provider',
        'trace_sink':'run_local_memory_then_safe_report','remote_compute_stopped':'UNKNOWN'}
    if confirm_network is not True:
        return report
    if approved_plan_sha256 != approved['plan_sha256']:
        raise QualificationError('QUALIFICATION_PLAN_CHANGED')
    trace,handle,adapter,gateway = _Trace(),handle or RequestHandle(),None,None
    report['started_at'] = utcnow().isoformat()
    try:
        if any(logging.getLogger(name).isEnabledFor(logging.DEBUG) for name in
               ('openai','openai._base_client','httpx','httpcore')):
            raise GatewayError('QUALIFICATION_UNSAFE_LOGGING')
        with TemporaryDirectory(prefix='history-',dir=_workspace(root)) as temporary:
            folder = Path(temporary)
            monitoring = _monitoring(folder,case)
            credentials = credential_store if credential_store is not None else _credentials(Path(root))
            service = ManagementAssistantService(monitoring,credentials=credentials,traces=trace,
                policy_directory=folder/'policies',gateway_factory=lambda:gateway,
                history_config=HistoryCandidateConfig(load_history_config().scope_json))
            selected = service.management_policy.snapshot()
            service.management_policy.save([WATER_QUALITY_HISTORY],expected_revision=selected.revision)
            selected = service.management_policy.snapshot()
            profile,policy,decision,registry = service._configuration(PRESET,DEVICE,
                policy_snapshot=selected,execution_profile=HISTORY_PROFILE)
            if (plan(case_id) != approved or history_scope(profile,registry) != approved['scope']
                    or decision.profile.mode_reason != 'HISTORY_CANDIDATE_NOT_RELEASED'
                    or decision.can_send or policy.exposed_tools != case.exposed_tools
                    or _json(asdict(policy)) != _json(approved['policy'])):
                raise QualificationError('QUALIFICATION_HISTORY_SCOPE_MISMATCH')
            parity = registry.model_definitions() == service.history_registry.model_definitions()
            if not parity or decision.profile.mode != ToolExecutionMode.SINGLE_ROUND:
                raise QualificationError('QUALIFICATION_REGISTRY_MISMATCH')
            adapter = (adapter_factory or _Adapter)(profile.model,registry,case.exposed_tools,MAX_OUTPUT_TOKENS)
            gateway = _Gateway(adapter,registry,case)
            # One consent-bound development claim only. Web/config remain candidate/closed.
            prepared = PreparedAssistantTurn(AssistantRequest(PRESET,case.question,
                source_requirement=SourceRequirement.HISTORICAL_WATER_QUERY),DEVICE,service.epoch,
                profile,policy,registry,replace(decision,can_send=True),selected.revision,selected.source)
            result = service.execute_turn(prepared,handle)
            formal = trace.result
            ledger = formal.source_ledger if formal else None
            observed = gateway.observed
            rows = observed.rows if observed else []
            for step in formal.execution.steps if formal else ():
                if not isinstance(step,ToolExecutionStep):
                    continue
                included = bool(step.result and observed and step.model_request_index < len(observed.contexts)
                    and (step.tool_call_id,step.result.to_json()) in observed.contexts[step.model_request_index])
                payload = step.result.payload if step.result else {}
                report['executions'].append({'seq':step.seq,'tool_round':step.tool_round,
                    'tool_name':step.tool_name if step.tool_name == WATER_QUALITY_HISTORY else 'unknown_tool',
                    'handler_started':step.handler_started,'status':step.result.status.value if step.result else None,
                    'duration_ms':step.duration_ms,'actual_result_in_next_request':included,
                    'executed_after_client_cleanup':bool(step.handler_started and observed
                        and rows[step.model_request_index-1].get('cleanup',{}).get('sdk_client_close_completed')),
                    'fixture_checks':_fixture_checks(payload,case) if step.handler_started else {}})
            executed = [e for e in report['executions'] if e['handler_started']]
            path = len(executed) == 1 and executed[0]['tool_name'] == WATER_QUALITY_HISTORY
            context = path and all(e['actual_result_in_next_request'] and e['executed_after_client_cleanup'] for e in executed)
            fixture = path and all(all(e['fixture_checks'].values()) for e in executed)
            satisfied = bool(ledger and requirement_satisfied_by_ledger(SourceRequirement.HISTORICAL_WATER_QUERY,ledger))
            source_isolation = bool(ledger and not requirement_satisfied_by_ledger(
                SourceRequirement.CURRENT_OBSERVATION_QUERY,ledger) and all(
                not entry.receipt.has_observation and not entry.receipt.observation_query_completed
                and not entry.receipt.has_score and not entry.receipt.has_project_evidence for entry in ledger.entries))
            protocol = len(rows) == 2 and all(row.get('normalized',{}).get('provider_model_matches') is True
                and all(row['provider_observation'].get(k) is True for k in
                    ('available','normalized_call_consistent','normalized_metadata_consistent'))
                and row.get('encoded') == {'output_field':approved['encoded_output_field'],
                    'max_output_tokens':MAX_OUTPUT_TOKENS,'stream_field_present':False,'stream_value':None}
                and row.get('cleanup') == {'sdk_client_close_called':True,'sdk_client_close_completed':True}
                for row in rows)
            report.update(product_commit_gate_passed=result['successful_turn'],trace_recorded=result['trace_recorded'],
                formal_result_available=formal is not None,
                activity=result['activity'],usage=result['usage'],final_answer_present=bool(result['final_text']),
                final_finish_reason=result['final_finish_reason'],expected_path_matches=path,
                result_context_matches=context,fixture_matches=fixture,provider_protocol_verified=protocol,
                formal_turn_registry_matches=parity,ledger=ledger.to_dict() if ledger else {'entries':[]},
                requirement_satisfied=satisfied,historical_source_not_current=source_isolation,
                total_latency_ms=result['total_latency_ms'],
                history_projection={'projection_id':DEFAULT_HISTORY_PROJECTION.value,
                    'received':result['history_turns_received'],'sent':result['history_turns_sent']},
                web_can_send_after_probe=service.bootstrap(DEVICE)['history_candidate']['can_send'])
            error = (result['error_code'] or ('ASSISTANT_SOURCE_REQUIREMENT_UNMET' if not satisfied else
                'QUALIFICATION_PATH_MISMATCH' if not path else
                'QUALIFICATION_HISTORY_RESULT_MISMATCH' if not fixture or not source_isolation else
                'QUALIFICATION_RESULT_CONTEXT_MISMATCH' if not context else
                'QUALIFICATION_PROTOCOL_UNOBSERVED' if not protocol else None))
            report.update(success=result['successful_turn'] and not error,
                          status='completed' if not error else 'failed',error_code=error)
            if answer_reviewer and result['successful_turn']:
                try:
                    answer_reviewer(result['final_text'])
                    report['human_review_status'] = 'PREVIEWED_NOT_APPROVED'
                except KeyboardInterrupt:
                    # Provider turn has already completed; this only stops the preview.
                    report['human_review_status'] = 'PREVIEW_INTERRUPTED'
                except Exception:
                    report['human_review_status'] = 'PREVIEW_UNAVAILABLE'
            else:
                report['human_review_status'] = 'PENDING' if result['successful_turn'] else 'NOT_AVAILABLE'
    except (CredentialFileError,CredentialLocationError):
        report.update(status='failed',success=False,error_code='CREDENTIAL_FILE_ERROR')
    except KeyboardInterrupt:
        handle.cancel()
        report.update(status='cancelled',success=False,error_code='USER_CANCELLED')
    except Exception as error:
        report.update(status='failed',success=False,error_code=_safe_error(error))
    finally:
        handle.finish(report['error_code'])
        attempts = getattr(adapter,'request_attempts',0) if adapter else 0
        if handle.error_code == 'USER_CANCELLED':
            report.update(status='cancelled',success=False,error_code='USER_CANCELLED')
        rows = gateway.observed.rows if gateway and gateway.observed else []
        report.update(technical_success=report['success'],request_id=handle.request_id,
            qualification_verdict='PENDING_MANUAL_REVIEW' if report['success'] else 'FAILED',
            requests=rows,request_count=len(rows),transport_attempts=attempts,
            actual_network_requests=attempts if adapter_factory is None else 0,
            backend_io_closed=handle.io_closed,handle_state=handle.state,trace=trace.entries,
            finished_at=utcnow().isoformat())
    return report
