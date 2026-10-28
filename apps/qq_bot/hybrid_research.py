"""Local Hybrid experiments: separate approvals, original Agent, no QQ transport.

Each <=5-turn Run owns its existing nonce/lease/quota journal. An operator can
approve the complete, enumerated batch once; no file can import that live grant.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import threading
import time

from apps.ai_backend import secure_files
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_service.channel import ChannelAuthorization
from apps.ai_service.channel_hybrid import HybridResult
from apps.ai_service.channel_hybrid_research import (CONTRACT, ResearchAuthority,
    ResearchHybridTurn, prepared_scope, preparation_record)
from apps.ai_service.channel_trial import PRESET, PRICE_INPUT, PRICE_OUTPUT, PRICE_URL, CONTEXT_RESERVATION
from apps.ai_service.channel_validation import validation_once
from apps.ai_service.runtime.assistant import assistant_profile, AssistantHistoryTurn
from apps.ai_service.runtime.release_contracts import _hash
from .configuration import project_credentials
from .contracts import BotError, GroupMessage
from .conversations import ConversationKey, ConversationOptions
from .hybrid_conversations import HybridConversationStore, HybridTurn
from .hybrid_research_suite import allocate
from .run_consent import RunLedger, RunLimits
from .session_run import SessionRun
from .trial_configuration import inputs_snapshot, local_path, read_json, write_new

ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT/'apps/ai_service/resources/local_hybrid_research_trial.json'
CONSENTS = ('provider_network', 'scope_prompt_price_and_total_budget', 'enumerated_independent_runs',
    'simulator_and_projected_history_disclosure', 'local_model_text_review_not_verified',
    'sdk_thread_hard_exit_risk', 'no_qq_no_retry_no_refund_no_resume')


def error_code(error):
    from apps.ai_backend.assistant_activity import safe_code
    if isinstance(error, KeyboardInterrupt):return 'RESEARCH_OPERATOR_INTERRUPTED'
    return safe_code(getattr(error, 'code', None)) or 'RESEARCH_OPERATION_FAILED'


def private_directory(path):
    path = local_path(path)
    secure_files.check_volume(path.parent)
    secure_files.private_directory(path)  # CREATE_NEW; never change an existing ACL.
    return path


def private_record(path, value):
    path = local_path(path)
    secure_files.inspect_policy(path.parent, directory=True)
    secure_files.write_private(path, (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n').encode('utf8'))


def check_configuration(inputs, *, instance_root, instance_id, device_id, memory_fixture=False):
    """Only explicit config/Policy metadata. Never stat/open Monitoring or resolve keys."""
    access, ai, source, grant, digest = inputs_snapshot(inputs)
    expected = Path(instance_root)
    if (not expected.is_absolute() or '..' in expected.parts or expected.anchor.startswith(('\\\\','//'))
            or source.data_root != expected or source.instance_id != instance_id or grant.device_id != device_id):
        raise BotError('RESEARCH_EXPLICIT_INSTANCE_MISMATCH')
    if not memory_fixture and not (expected == ROOT/'outputs/bot2c-instance'
            or expected.is_relative_to(ROOT/'outputs/hybrid-research-instances')):
        raise BotError('RESEARCH_ISOLATED_INSTANCE_REQUIRED')
    options = ConversationOptions(trigger_mode='mention_ai', memory_enabled=True)
    scope = prepared_scope(options)
    if read_json(RESOURCE) != preparation_record(scope):raise BotError('RESEARCH_SCOPE_REVIEW_REQUIRED')
    profile = assistant_profile(PRESET)
    return dict(contract=CONTRACT, code='LOCAL_HYBRID_CHECKED_APPROVAL_REQUIRED',
        scope_sha256=_hash(scope), bindings_metadata_sha256=digest,
        provider=profile.service_id, model=profile.model, preset=PRESET,
        data_root=str(expected), instance_id=instance_id, device_id=device_id,
        app_ref=_hash(access.app_id)[:12], group_ref=_hash(inputs.group_id)[:12],
        member_ref=_hash(inputs.member_id)[:12], prompt_id=scope['runtime']['prompt_id'],
        credential_ref=profile.credential_ref, credentials_read=False, database_opened=False,
        static_price_input_per_million_cny=str(PRICE_INPUT),static_price_output_per_million_cny=str(PRICE_OUTPUT),
        pricing_region='cn-beijing',price_reference=PRICE_URL,current_cloud_price_verified=False,
        reserved_input_tokens_per_request=CONTEXT_RESERVATION,
        network_requests=0, approval_created=False, qualification_id=None,
        qq_publication_authorized=False, status='candidate')


class LocalResearchTurn(HybridTurn):
    def projection(self):
        if self.source_flags == ('general','model_knowledge','NO_OBSERVATION'):
            text = '本地研究已接受的一般AI答复，未经事实核验、不是QQ交付或现场证据：\n'+self.text
        else:
            text = (f'本地研究水质话题记录；旧来源时间{self.source_times}、有效性{self.source_flags}。'
                    '不保存旧读数为当前事实，本轮必须重新查询Tool；不是QQ已送达记录。')
        return AssistantHistoryTurn(self.focus, text, self.accepted_at)


class LocalResearchStore(HybridConversationStore):
    turn_type = LocalResearchTurn


class ResearchLedger(RunLedger):
    def __init__(self, *args, allow_raw=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._plan.update(contract=CONTRACT, environment='LOCAL_PROVIDER_RESEARCH',raw_model_output_allowed=allow_raw)

    def report(self):return {**super().report(),'contract':CONTRACT}


class HybridResearchRun(SessionRun):
    def __init__(self, inputs, directory, *, instance_root, instance_id, device_id,
                 limits=RunLimits(), async_client_factory=None, clock=None, monotonic=time.monotonic,
                 batch_guard=None, allow_raw=False):
        if type(allow_raw) is not bool:raise BotError('INVALID_RESEARCH_RAW_CONSENT')
        self._allow_raw=allow_raw
        self._batch_guard=batch_guard
        self.expected = dict(instance_root=Path(instance_root), instance_id=instance_id, device_id=device_id)
        self._authorization, self._approval_digest = None, None
        self._authority = ResearchAuthority(self._validate_authorization)
        check_configuration(inputs, **self.expected, memory_fixture=async_client_factory is not None)
        self._initialize(inputs, directory, async_client_factory=async_client_factory, limits=limits,
                         members=(inputs.member_id,), clock=clock, monotonic=monotonic)
        self.review = private_directory(self.directory/'review')
        self._case_lock = threading.Lock()
        self._key = None

    def scope_for_options(self):return prepared_scope(self.options)
    def validation_scope(self):return self._authority.boundary.scope()
    def _new_store(self, monotonic):return LocalResearchStore(self.options, monotonic=monotonic)

    def _new_ledger(self, limits):
        return ResearchLedger(self.directory, scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest, limits=limits, clock=self.clock, monotonic=self.now,
            allow_raw=self._allow_raw)

    def _check_configuration(self):
        def validate():
            super(HybridResearchRun, self)._check_configuration()
            if read_json(RESOURCE)!=preparation_record(self.scope):raise BotError('RESEARCH_SCOPE_REVIEW_REQUIRED')
        return validation_once(('local-research-config', id(self)), validate)

    def approve(self, plan, *, confirmed=False):
        if confirmed is not True or plan!=self.plan() or self._authorization is not None:
            raise BotError('INVALID_RESEARCH_APPROVAL')
        self._check_configuration()
        SDK_RESOURCES.assert_healthy()
        observation=self.monitoring.capture_water(self.device_id).analysis.observation
        if observation is not None and observation.source_kind!='simulator':
            raise BotError('RESEARCH_SOURCE_NOT_SIMULATOR')
        record = dict(contract=CONTRACT, plan=plan, approved_at=self.clock().isoformat(),
            consents={c:True for c in CONSENTS}, operator_source='LOCAL_UNAUTHENTICATED',
            qualification_id=None, status='local_experimental', qq_publication_authorized=False)
        try:
            write_new(self.directory/'approval.json', record)
            self._approval_digest = _hash(record)
            consent = self.ledger.approve(self.ledger.plan(), confirmed=True)
            self._authorization = self._authority.issue(consent_id=consent.consent_id,
                scope_sha256=self.scope_sha256, bindings_sha256=self._binding_digest,
                lease_authority=self.ledger.authority)
        except Exception:
            self.ledger.halt('RESEARCH_APPROVAL_WRITE_FAILED')
            raise BotError('RESEARCH_APPROVAL_WRITE_FAILED') from None

    def _validate_authorization(self, value):
        if self._batch_guard is not None:self._batch_guard()
        super().check()
        if value is not self._authorization:raise BotError('RESEARCH_APPROVAL_CHANGED')
        if validation_once(('research-approval',id(self)), lambda:
                _hash(read_json(self.directory/'approval.json')))!=self._approval_digest:
            self.ledger.halt('RESEARCH_APPROVAL_CHANGED');raise BotError('RESEARCH_APPROVAL_CHANGED')

    def check(self):
        self.ledger.check()
        try:self._authority.validate(self._authorization)
        except Exception as error:
            self.ledger.halt(error_code(error));raise

    def _turn_credentials(self):
        self.check()
        return None if self.offline_test else project_credentials(ROOT)

    def _create_turn(self, lease, snapshot, validate):
        return ResearchHybridTurn(lease, run_authorization=self._authorization,
            authority=self.store.authority, conversation_epoch=self.base_service.epoch,
            options=self.options, snapshot=snapshot, validate=validate,
            claim=lambda:self.ledger.check_lease(lease), async_client_factory=self.factory,
            clock=self.clock, monotonic=self.now)

    def _conversation_key(self):
        policy = self.base_service.management_policy.snapshot()
        return ConversationKey(self.access.app_id, self.inputs.group_id, self.inputs.member_id,
            self.monitoring.config.instance_id, self.device_id, _hash([self.bindings, asdict(self.config)]),
            self.monitoring.binding_revision, policy.revision, self.scope_sha256, self.base_service.epoch)

    def execute_case(self, entry, *, save_raw=False, stop_event=None):
        """One existing Service Turn, not an Agent loop. A batch calls it serially."""
        case = entry['case']
        if save_raw and not self._allow_raw:raise BotError('RESEARCH_RAW_OUTPUT_NOT_APPROVED')
        from .hybrid_intent import classify
        if classify(case['question'],command_priority=False).kind!='agent':
            raise BotError('RESEARCH_CASE_NOT_AGENT')
        output = self.directory/f'case-{case["id"]}-repeat-{entry["repetition"]}.result.json'
        if output.exists():raise BotError('RESEARCH_CASE_ALREADY_RECORDED')
        if not self._case_lock.acquire(blocking=False):raise BotError('RESEARCH_BUSY')
        snapshot = session = handle = service = watchdog = None
        start = self.now(); watch_stop = threading.Event(); stop_event = stop_event or threading.Event()
        case = entry['case']; code = None; result = None; history_code = 'NOT_COMMITTED'
        before = 0; captured = False; review_hash = None; review_file = None; fatal = False
        try:
            self.require_turn()
            if stop_event.is_set():raise BotError('RESEARCH_CANCELLED')
            key = self._conversation_key()
            if case['dialogue'] is None or case['step']==1:
                self.store.clear(key)
            self._key = key
            snapshot = self.store.snapshot(key, focus=case['question']);before = len(snapshot.history)
            message = GroupMessage('local-'+case['id']+'-'+str(entry['repetition']),
                self.inputs.group_id, self.inputs.member_id, self.clock(), case['question'])
            service = self.begin(snapshot, message=message);session = service._channel_trial
            def check():
                self.check();snapshot.authority.validate(snapshot,self.scope_sha256)
                if stop_event.is_set():raise BotError('RESEARCH_CANCELLED')
            authorization = ChannelAuthorization(key.instance_id, key.device_id, key.binding_revision,
                key.permission_revision, self.config.preset_id, ('get_current_water_quality',),
                self.config.budget, check)
            prepared = service.prepare_channel_turn(case['question'], authorization, history_snapshot=snapshot)
            handle = RequestHandle();handle.limit_turn(min(90, self.remaining()))
            session.reserve_admission(handle)
            def supervise():
                while not watch_stop.wait(.1):
                    try:check();handle.check()
                    except Exception:
                        handle.abort_io();handle.cancel();return
            watchdog = threading.Thread(target=supervise, name='local-hybrid-watchdog', daemon=False)
            watchdog.start()
            result = service.execute_channel_turn(prepared, handle)
            check();handle.assert_resources_closed();service.validate_channel_turn(prepared)
            if (type(result) is not HybridResult or not result.completed
                    or result.can_deliver is not False or result.publication is None):
                raise BotError(result.error_code if result else 'RESEARCH_RESULT_INVALID')
            publication = result.publication
            if publication.branch!=result.branch:raise BotError('RESEARCH_RESULT_INVALID')
            review_hash = hashlib.sha256(publication.text.encode('utf8')).hexdigest()
            review_file = f'case-{case["id"]}-repeat-{entry["repetition"]}.json'
            review_value = dict(contract=CONTRACT, case_id=case['id'], question=case['question'],
                text=publication.text, code=publication.code, text_sha256=review_hash,
                source=asdict(result.source) if result.source is not None else None,
                local_capture_only=True, human_quality_verified=False,
                qq_api_accepted=False, client_display_confirmed=False)
            if save_raw:
                raw=result.model_text.encode('utf8')
                if len(raw)<=32768:review_value['model_output_json_or_text'] = result.model_text
                else:review_value.update(raw_output_omitted='OVER_32768_BYTES',raw_output_bytes=len(raw),
                                         raw_output_sha256=hashlib.sha256(raw).hexdigest())
            private_record(self.review/review_file, review_value)
            # Persist local acceptance before RAM history; no forged QQ Receipt/API acceptance.
            write_new(self.directory/f'case-{case["id"]}-repeat-{entry["repetition"]}.capture.json',
                dict(text_sha256=review_hash, review_file='review/'+review_file,
                     accepted_at=self.clock().isoformat(), acceptance='LOCAL_RESEARCH_CAPTURE_ONLY'))
            captured = True
            check()
            if publication.history_allowed:
                times, flags = result.history_metadata()
                history_code = self.store.commit(snapshot, turn_id=message.message_id,
                    text=publication.text, text_sha256=review_hash, accepted_at=self.clock().isoformat(),
                    source_times=times, source_flags=flags)
            else:history_code = 'NOT_COMMITTED_PRESENTATION'
            if not publication.allowed:code = publication.code
        except (Exception, KeyboardInterrupt) as error:
            code = error_code(error);fatal = True
            if handle is not None:handle.abort_io();handle.cancel()
        finally:
            watch_stop.set()
            if watchdog is not None:
                watchdog.join(3)
                if watchdog.is_alive():code='RESEARCH_WATCHDOG_STOP_FAILED'
            report = session.report() if session else {}
            resources = report.get('sdk_resources')
            safe = (report.get('model_requests',0)==0 and resources is None) or bool(resources
                and resources['state']=='CLOSED' and resources['thread_exited']
                and resources['local_io_closed'] and resources['cleanup_error'] is None)
            publication = result.publication if result and result.completed else None
            execution = report.get('execution',{})
            branch = execution.get('actual_branch')
            route = execution.get('model_route')
            expected = case['expected']
            row = dict(contract=CONTRACT, case_id=case['id'], category=case['category'],
                turn=session.lease.sequence if session else 0,
                repetition=entry['repetition'], expected=expected, actual_branch=branch,
                tool_choice_matches_expected=(route==expected and (expected!='water' or
                    execution.get('tool_handler_calls')==1 and all(t['name']=='get_current_water_quality'
                    for t in execution.get('tool_results',[])))) if expected!='ambiguous' and route else None,
                answering_quality_correct=None, requires_human_review=True,
                model_contract_valid=publication.allowed if publication is not None else None,
                contract_code=publication.code if publication else None,
                local_capture_saved=captured, local_text_sha256=review_hash,
                review_file='review/'+review_file if review_file else None,
                history_before=before, history_code=history_code,
                history_attached=before>0, context_understanding_correct=None,
                general_fact_verified=False, code=code, resources_safe=safe,
                total_ms=round((self.now()-start)*1000,3), **report)
            row.update(qq_api_accepted=False, client_display_confirmed=False, stop_required=fatal or not safe)
            if session is not None:
                with self._lock:self._active.pop(session.lease.sequence, None)
                # Avoid retaining model bodies in host.sessions across the batch.
                session.raw_text=None
                if hasattr(session,'hybrid_result'):session.hybrid_result=None
            if snapshot is not None:self.store.release(snapshot)
            if not safe:code=row['code']='RESEARCH_SDK_RESOURCE_UNSAFE'
            # Contract rejection is a recorded research outcome, not a network
            # exception. Runtime/permission/SDK/checkpoint errors stop the batch.
            if row['stop_required']:self.ledger.halt(code or 'RESEARCH_SDK_RESOURCE_UNSAFE')
            self.turns.append(row)
            try:write_new(self.directory/f'case-{case["id"]}-repeat-{entry["repetition"]}.result.json', row)
            except Exception:
                self.ledger.halt('RESEARCH_CHECKPOINT_FAILED');row.update(code='RESEARCH_CHECKPOINT_FAILED',stop_required=True)
            self._case_lock.release()
        return row


def experiment_plan(inputs, cases, *, instance_root, instance_id, device_id,
                    categories=None, case_ids=None, repetitions=1, total_budget_cny=None,
                    run_seconds=1800, experiment_seconds=7200, save_raw=False, memory_fixture=False):
    config = check_configuration(inputs, instance_root=instance_root, instance_id=instance_id,
        device_id=device_id, memory_fixture=memory_fixture)
    budget = allocate(cases, categories=categories, case_ids=case_ids, repetitions=repetitions,
        total_budget_cny=total_budget_cny, run_seconds=run_seconds, experiment_seconds=experiment_seconds)
    return dict(contract=CONTRACT, configuration=config, allocation=budget,
        created_at=datetime.now(timezone.utc).isoformat(), status='pending_local_operator_approval',
        raw_model_output_saved=save_raw, consent_requirements=list(CONSENTS),
        qq_network=False, general_real_qq_publication=False,
        notice='除程序免费分支外，普通自然语言也可能收费；每轮完整预留，不退款。'
               '多个独立五轮Run，不恢复旧余额；本地预算不是云平台账单硬上限。')


def summarize(rows, *, planned_turns):
    import statistics
    import math
    def rate(values):
        values=[v for v in values if v is not None]
        return dict(n=len(values), passed=sum(v is True for v in values),
                    rate=sum(v is True for v in values)/len(values) if values else None)
    times=sorted(r['total_ms'] for r in rows)
    branch={b:rate([r['model_contract_valid'] for r in rows if r['actual_branch']==b]) for b in ('general','water')}
    def distribution(values, decimal=False):
        values=sorted(values)
        convert=str if decimal else lambda v:v
        return dict(n=len(values),median=convert(statistics.median(values)) if values else None,
            p95=convert(values[min(len(values)-1,math.ceil(.95*len(values))-1)]) if len(values)>=30 else None,
            min=convert(values[0]) if values else None,max=convert(values[-1]) if values else None)
    syntax=rate([r.get('execution',{}).get('json_syntax_valid') for r in rows])
    syntax.update(errors=syntax['n']-syntax['passed'],error_rate=1-syntax['rate'] if syntax['rate'] is not None else None)
    return dict(planned_turns=planned_turns, recorded_turns=len(rows),
        unexecuted_turns=planned_turns-len(rows),
        tool_choice=rate([r['tool_choice_matches_expected'] for r in rows]), contracts=branch,
        json_syntax=syntax,
        category_tool_choice={c:rate([r['tool_choice_matches_expected'] for r in rows if r['category']==c]) for c in 'ABCDE'},
        unbacked_general_rejected=sum(r.get('actual_branch')=='general' and r.get('contract_code') in
            ('GENERAL_PUBLICATION_REJECTED','HYBRID_SOURCE_REQUIRED') for r in rows),
        failures=[dict(case_id=r['case_id'],repetition=r['repetition'],code=r['code']) for r in rows if r['code']],
        model_requests=sum(r.get('model_requests',0) for r in rows),
        model_http_requests=sum(r.get('model_http_requests',0) for r in rows),
        tool_handler_calls=sum(r.get('execution',{}).get('tool_handler_calls',0) for r in rows),
        input_tokens=sum(r.get('usage',{}).get('input_tokens',0) for r in rows),
        output_tokens=sum(r.get('usage',{}).get('output_tokens',0) for r in rows),
        usage_estimated_cost_cny=str(sum((Decimal(r.get('observed_usage_cost_cny','0')) for r in rows),Decimal('0'))),
        usage_complete=bool(rows) and all(r.get('usage_complete',False) for r in rows),
        latency_ms=distribution(times),
        adapter_mixed_ms=distribution([t['adapter_total_ms'] for r in rows for t in r.get('model_timings',[])]),
        input_token_distribution=distribution([r['usage']['input_tokens'] for r in rows if 'usage' in r]),
        output_token_distribution=distribution([r['usage']['output_tokens'] for r in rows if 'usage' in r]),
        usage_cost_distribution_cny=distribution([Decimal(r['observed_usage_cost_cny']) for r in rows
                                                if 'observed_usage_cost_cny' in r],decimal=True),
        answering_quality_correct=None, context_understanding_correct=None, billing_confirmed=False,
        qq_api_accepted=False, http_timing_note='adapter_total_ms包含权限、SDK I/O与清理；http_only_ms未分离，不能相加或冒称纯HTTP时延')


def write_csv(path, rows):
    """Only numeric/allowlisted research metadata; no question or model text."""
    import csv
    import os
    path=local_path(path)
    fields=('run','case_id','category','repetition','expected','actual_branch','model_requests',
        'model_http_requests','tool_handler_calls','model_contract_valid','json_syntax_valid',
        'history_before','history_code','total_ms','input_tokens','output_tokens',
        'observed_usage_cost_cny','resources_safe','code')
    with path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            value={k:row.get(k) for k in fields}
            for name in ('tool_handler_calls','json_syntax_valid'):value[name]=row.get('execution',{}).get(name)
            for name in ('input_tokens','output_tokens'):value[name]=row.get('usage',{}).get(name)
            writer.writerow(value)
        stream.flush();os.fsync(stream.fileno())
