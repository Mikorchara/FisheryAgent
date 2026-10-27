"""BOT-3F-B0. Isolated offline measurements, never an alternative AI entry point.

Core = matched current-water workloads through existing service contracts.
Entry = unchanged Web Normal HTTP and QQ Session routing. Prompts, authorization
and budgets remain channel-specific; their differences are recorded, not patched.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import timedelta
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

IMPORT_STARTED = time.perf_counter_ns()
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import httpx
from openai import AsyncOpenAI
from performance_observer import Observer, statistics
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.sdk_resources import SDK_RESOURCES, SDKResourceLease
from apps.ai_backend.tool_conversation import ToolCallingService
from apps.ai_backend.tools.executor import ToolExecutor
from apps.ai_service import channel_conversation, channel_session_run, channel_session_trial
from apps.ai_service import channel_trial, channel_presentation, execution
from apps.ai_service.runtime import release_contracts
from apps.ai_service.runtime.assistant import AssistantService, assistant_profile
from apps.ai_service.runtime.policy import UserToolPolicyStore
from apps.ai_service.management_policy import ManagementToolPolicyStore
from apps.ai_service.service import ManagementAssistantService, PRESETS
from apps.knowledge.tests.support import reference_knowledge
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
from apps.monitoring.service import MonitoringService
from apps.monitoring.repository import MonitoringRepository
from apps.qq_bot import ai_delivery, trial_configuration
from apps.qq_bot.contracts import BotError
from apps.qq_bot.tests import test_session_run_trial as qq_fixture
from apps.qq_bot.transport import QQAPI

IMPORT_MS = (time.perf_counter_ns() - IMPORT_STARTED) / 1e6
WATER = 'get_current_water_quality'
DEVICE = 'sim-pond-1'
SCHEMA = 'web-qq-offline-performance@1'


@dataclass(frozen=True)
class Condition:
    suite: str
    name: str
    scenario: str
    question: str
    model_expected: bool = True
    followup: bool = False


def conditions(suite='both'):
    # The six requested questions are unchanged in Entry. Core uses explicit,
    # canonical water inputs and empty history; it is not a routing workaround.
    core = [Condition('core', name, scenario, channel_conversation.question_for(focus))
        for name, scenario, focus in (
            ('fresh-all', 'fresh', 'all'), ('partial-ph', 'partial', 'ph'),
            ('stale-all', 'stale', 'all'), ('low-oxygen', 'low', 'dissolved_oxygen_mg_l'))]
    entry = [Condition('entry', *args) for args in (
        ('q1-water', 'fresh', '现在水质怎么样？', True, False),
        ('q2-oxygen', 'fresh', '溶解氧是多少？', True, False),
        ('q3-ph', 'partial', 'pH 数据是否正常？', True, False),
        ('q4-reliability', 'stale', '现在的数据可靠吗？', False, False),
        ('q5-followup', 'fresh', '那水温呢？', True, True),
        ('q6-risk', 'low', '有没有低氧风险？', False, False))]
    return core if suite == 'core' else entry if suite == 'entry' else core + entry


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def safe_code(error):
    code = getattr(error, 'code', None)
    if isinstance(code, str) and re.fullmatch(r'[A-Z0-9_]{1,96}', code):
        return code
    return 'EXPERIMENT_' + type(error).__name__.upper()


class MemoryModel:
    """Same two synthetic responses; only output references vary with the Tool."""
    def __init__(self, observer):
        self.observer = observer
        self.requests = []
        self.clients = []
        self.last_source_hash = None

    def reset(self):
        self.requests.clear()
        self.last_source_hash = None

    def factory(self, runtime, remaining):
        async def handle(request):
            index = len(self.requests) + 1
            with self.observer.span('model.http.' + str(index)):
                body = json.loads(request.content)
                tool = next((m for m in body['messages'] if m['role'] == 'tool'), None)
                # Hash only synthetic framing; never persist bodies/free text.
                self.requests.append({'system_sha256': digest(body['messages'][0]['content']),
                    'question_sha256': digest(body['messages'][-1]['content']) if tool is None else None,
                    'tool_definitions_sha256': digest(body.get('tools', [])),
                    'max_tokens': body.get('max_tokens'), 'has_tool_result': tool is not None})
                if tool is None:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                        'id': 'synthetic-call', 'type': 'function',
                        'function': {'name': WATER, 'arguments': '{}'}}]}
                else:
                    payload = json.loads(tool['content'])
                    quality = payload['data_quality']
                    hits = [f['code'] for f in payload['findings']
                            if f['kind'] == 'WATER_RISK' and f['state'] == 'HIT']
                    usable = (payload['status'] == 'OK' and
                              (quality['quality'], quality['freshness'], quality['connectivity']) ==
                              ('valid', 'fresh', 'online') and
                              all(m['quality'] == 'valid' for m in payload.get('metrics', {}).values()))
                    self.last_source_hash = digest(payload)
                    plan = {'contract': 'qq-water-explanation@1', 'source': 'simulator',
                        'context': 'window' if usable else 'limited',
                        'metrics': ['temperature_c', 'ph', 'dissolved_oxygen_mg_l'],
                        'rules': hits, 'advice': ['review_rules'] if hits else ['verify_observation']}
                    message = {'role': 'assistant', 'content': json.dumps(plan)}
                return httpx.Response(200, json={'id': 'synthetic-response',
                    'object': 'chat.completion', 'created': 0, 'model': runtime.model,
                    'choices': [{'index': 0, 'message': message,
                                 'finish_reason': 'stop' if tool else 'tool_calls'}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})
        client = AsyncOpenAI(api_key='offline-synthetic-not-a-key', base_url=runtime.base_url,
            max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle),
                trust_env=False, follow_redirects=False))
        self.clients.append(client)
        return client


class Fixture:
    def __init__(self, channel, condition, directory, observer):
        self.channel, self.condition, self.observer = channel, condition, observer
        self.case = qq_fixture.SessionRunTrialTests(
            'test_once_approved_five_typed_turns_resources_and_current_sources')
        self.closed = False
        self.history = []
        self.model = MemoryModel(observer)
        started = time.perf_counter_ns()
        try:
            self.case.setUp()
            if not self.case.root.resolve().is_relative_to(directory.resolve()):
                raise RuntimeError('Fixture escaped owned temporary root')
            self.case.factory = self.model.factory
            self.case.ingest('missing' if condition.scenario == 'partial' else 'valid',
                             oxygen=2.2 if condition.scenario == 'low' else 6.5)
            if condition.scenario == 'stale':
                self.case.now += timedelta(seconds=91)
            if channel == 'qq':
                # Replace only the fake transport: real reply API/owner checks stay.
                old_api = self.case.api
                def qq_http(request):
                    with observer.span('qq.mock_http'):
                        return self.case.qq_http(request)
                self.case.api = QQAPI(qq_fixture.APP, lambda: (_ for _ in ()).throw(
                    AssertionError('real QQ credentials forbidden')),
                    client=httpx.Client(transport=httpx.MockTransport(qq_http),
                        trust_env=False, follow_redirects=False))
                self.case.api._token = 'synthetic-qq-token'
                self.case.api._expires = time.monotonic() + 3600
                self.case.addCleanup(self.case.api.close)
                old_api.close()
                self.case.compose(turns=5)
            else:
                monitoring = self.case.source if condition.suite == 'core' else self.case.producer
                self.backend = ManagementAssistantService(monitoring,
                    knowledge=reference_knowledge(),
                    credentials=CredentialStore(process_env={assistant_profile(PRESETS[0]).credential_ref:
                        'offline-synthetic-not-a-key'}),
                    traces=JsonlTraceSink(self.case.root/'web.trace.jsonl', tool_names=(WATER,)),
                    policy_directory=self.case.root/'web-policy',
                    gateway_factory=lambda: OpenAICompatibleAdapter(async_client_factory=self.model.factory))
                if condition.suite == 'core':
                    policy = self.backend.tool_authorization()
                    self.backend.save_tool_authorization({'epoch': policy['epoch'],
                        'revision': policy['revision'], 'selected_tools': [WATER]})
                self.web = ManagementAssistant(self.backend)
                if condition.suite == 'entry':
                    self.client = create_app(data_service=monitoring, ai=self.web).test_client()
                    self.bootstrap = self.client.get('/api/ai/bootstrap?device='+DEVICE).get_json()
                else:
                    self.bootstrap = self.backend.bootstrap(DEVICE)
            self.setup_ms = (time.perf_counter_ns() - started) / 1e6
            self.database_before = hashlib.sha256(self.case.path.read_bytes()).hexdigest()
        except BaseException:
            self.close()
            raise

    def web_turn(self, question):
        body = {'preset_id': PRESETS[0], 'device_id': DEVICE, 'question': question,
            'history': list(self.history), 'epoch': self.bootstrap['epoch'],
            'revision': self.bootstrap['presets'][0]['revision'], 'confirm_network': True}
        if self.condition.suite == 'core':
            with self.observer.span('web.admission'):
                prepared = self.backend.prepare_turn(body)
                handle = RequestHandle()
            with self.observer.span('web.service'):
                value = self.backend.execute_turn(prepared, handle)
            with self.observer.span('web.response'):
                # Headless DTO serialization control, not an HTTP/browser claim.
                json.dumps(value, ensure_ascii=False)
        else:
            headers = {'X-Management-AI': self.bootstrap['browser_token']}
            with self.observer.span('web.control'):
                control = self.client.post('/api/ai/requests', json={'epoch': body['epoch']},
                    headers=headers).get_json()
            with self.observer.span('web.http_entry'):
                response = self.client.post('/api/ai/messages', json={**body, **control}, headers=headers)
                value = response.get_json().get('result', {})
                if response.status_code != 200:
                    raise BotError(value.get('error_code') or 'WEB_HTTP_FAILED')
        if not value.get('successful_turn'):
            raise BotError(value.get('error_code') or 'WEB_TURN_FAILED')
        with self.observer.span('web.history_client_commit'):
            # Same successful-DTO rule used by Web history; no browser rendering.
            self.history.append({'user': question, 'assistant': value['final_text'],
                                 'completed_at': value['completed_at']})
        return {'code': 'WEB_SUCCESS', 'history_committed': True}

    def qq_turn(self, question):
        with self.observer.span('qq.ingress'):
            code, task = self.case.receive(question)
        if code == 'AI_ADMITTED':
            value = self.case.scheduler.wait(task, 95)
            if value.get('state') != 'DELIVERED' or value.get('history_code') != 'HISTORY_COMMITTED':
                raise BotError(value.get('code') or 'QQ_TURN_FAILED')
            if self.case.host.turns[-1]['sdk_resources']['state'] != 'CLOSED':
                raise BotError('SDK_RESOURCE_UNCONFIRMED')
            return {'code': value['code'], 'history_committed': True}
        if code != 'QQ_REPLY_API_ACCEPTED':
            raise BotError(code)
        return {'code': code, 'history_committed': False}

    def turn(self, question):
        return self.qq_turn(question) if self.channel == 'qq' else self.web_turn(question)

    def seed_history(self):
        self.turn('现在水质怎么样？')
        if self.channel == 'qq' and self.case.host.store.counts()['turns'] != 1:
            raise BotError('SEED_HISTORY_NOT_COMMITTED')

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if not self.case.doCleanups():
                raise RuntimeError('Fixture cleanup assertion failed')
        finally:
            if any(not client.is_closed() for client in self.model.clients):
                raise RuntimeError('SDK clients leaked')


def instrument(observer, stack):
    methods = ((AssistantService, 'send', 'agent.assistant'),
        (ToolCallingService, 'run_request', 'agent.tool_loop'),
        (ManagementAssistantService, 'prepare_turn', 'service.prepare_web'),
        (ManagementAssistantService, 'prepare_channel_turn', 'service.prepare_qq'),
        (ManagementAssistantService, '_execute_claimed_turn', 'service.execute'),
        (ManagementAssistantService, 'validate_channel_turn', 'permission.channel'),
        (ToolExecutor, 'execute', 'tool.execute'),
        (MonitoringService, 'capture_water', 'monitoring.query'),
        (ManagementToolPolicyStore, 'snapshot', 'policy.management_snapshot'),
        (UserToolPolicyStore, 'load', 'policy.shared_load'),
        (OpenAICompatibleAdapter, 'complete', 'model.adapter'),
        (SDKResourceLease, 'settle', 'sdk.settle'),
        (AsyncOpenAI, 'close', 'sdk.client_close'),
        (QQAPI, 'reply', 'qq.api_reply'))
    from apps.qq_bot.ai_coordinator import QQAICoordinator
    from apps.qq_bot.ai_scheduler import QQAIJobScheduler
    from apps.qq_bot.conversations import ConversationStore
    from apps.qq_bot.session_run_trial import SessionTrialRun
    methods += ((QQAICoordinator, 'prepare', 'qq.prepare'),
        (QQAICoordinator, 'execute', 'qq.execute'),
        (QQAICoordinator, 'validate_plan', 'permission.watch_plan'),
        (QQAICoordinator, 'accept_delivery', 'qq.accept_history'),
        (QQAIJobScheduler, 'submit', 'qq.scheduler_submit'),
        (SessionTrialRun, 'check', 'permission.run'),
        (ConversationStore, 'commit', 'qq.history_commit'),
        (ai_delivery.DeliveryOwner, 'deliver', 'qq.delivery'),
        (MonitoringRepository, 'read', 'monitoring.repository_read'))
    for owner, name, label in methods:
        observer.method(stack, owner, name, label)
    for function, label in (
        (release_contracts.release_scope, 'scope.backend'),
        (execution.management_scope, 'scope.web'),
        (channel_session_trial.trial_scope, 'scope.qq_trial'),
        (channel_session_run.session_scope, 'scope.qq_session'),
        (channel_trial.fast_trial_scope, 'scope.qq_fast'),
        (trial_configuration.inputs_snapshot, 'config.bindings_snapshot'),
        (channel_presentation.render_channel_reply, 'presentation.render'),
        (channel_presentation.assess_explanation, 'presentation.assess')):
        observer.aliases(stack, function, label)
    original = threading.Thread.join
    def joined(thread, *args, **kwargs):
        if thread.name == 'fishery-sdk-request':
            with observer.span('sdk.thread_join'):
                return original(thread, *args, **kwargs)
        return original(thread, *args, **kwargs)
    stack.enter_context(patch.object(threading.Thread, 'join', joined))


def union_ms(events):
    intervals = sorted((e['start_ns'], e['end_ns']) for e in events)
    total = 0
    end = -1
    for start, finish in intervals:
        total += max(0, finish-max(start, end))
        end = max(end, finish)
    return total / 1e6


def measure(channel, condition, directory, observer, sample, phase, observed=True):
    row = {'sample': sample, 'channel': channel, 'suite': condition.suite,
        'condition': condition.name, 'scenario': condition.scenario, 'phase': phase,
        'observed': observed, 'success': False, 'error_code': None}
    fixture = None
    try:
        fixture = Fixture(channel, condition, directory, observer)
        row['fixture_setup_ms'] = fixture.setup_ms
        if condition.followup:
            fixture.seed_history()
        observer.active = sample
        observer.enabled = observed
        fixture.model.reset()
        start = time.perf_counter_ns()
        try:
            with observer.span('total'):
                result = fixture.turn(condition.question)
            row.update(result)
        finally:
            end = time.perf_counter_ns()
            observer.active = None
            observer.enabled = True
            row['total_ms'] = (end-start)/1e6
        row['model_requests'] = len(fixture.model.requests)
        expected = 0 if channel == 'qq' and not condition.model_expected else 2
        if row['model_requests'] != expected:
            raise BotError('UNEXPECTED_MODEL_COUNT')
        if hashlib.sha256(fixture.case.path.read_bytes()).hexdigest() != fixture.database_before:
            raise BotError('DATABASE_CHANGED')
        row.update(success=True, model_metadata=list(fixture.model.requests),
            source_sha256=fixture.model.last_source_hash,
            history_before=1 if condition.followup else 0,
            workload='ai' if expected else 'template',
            synthetic_database_unchanged=True)
        SDK_RESOURCES.assert_healthy()
    except KeyboardInterrupt:
        row['error_code'] = 'OPERATOR_INTERRUPTED'
    except Exception as error:
        row['error_code'] = safe_code(error)
    finally:
        observer.active = None
        if fixture is not None:
            row.setdefault('model_requests', len(fixture.model.requests))
            try:
                fixture.close()
            except Exception as error:
                row['success'] = False
                row['error_code'] = 'CLEANUP_' + safe_code(error)
        events = [e for e in observer.events if e['sample'] == sample]
        # Clip in-flight watchdog spans to the measured interval; report overlap.
        if 'total_ms' in row:
            for event in events:
                event['crossed_end'] = event['end_ns'] > end
                event['end_ns'] = min(end, event['end_ns'])
        row['stages'] = observer.summary(sample)
        core = next((e for e in events if e['label'] == 'agent.assistant'), None)
        if core is not None:
            row.update(before_core_ms=(core['start_ns']-start)/1e6,
                core_ms=(core['end_ns']-core['start_ns'])/1e6,
                after_core_ms=(end-core['end_ns'])/1e6)
        row['scope_union_ms'] = union_ms([e for e in events if e['label'].startswith('scope.')])
        row['config_policy_union_ms'] = union_ms([e for e in events
            if e['label'].startswith(('config.', 'policy.'))])
        submits = [e for e in events if e['label'] == 'qq.scheduler_submit']
        executions = [e for e in events if e['label'] == 'qq.execute']
        if submits and executions:
            row['admission_to_worker_ms'] = max(0, (executions[0]['start_ns']-submits[0]['end_ns'])/1e6)
        row['spans'] = events
    return row


def aggregate(rows):
    groups = {}
    for row in rows:
        if row['phase'] != 'sample' or not row['observed']:
            continue
        key = (row['suite'], row['condition'], row['channel'])
        groups.setdefault(key, []).append(row)
    output = []
    for (suite, condition, channel), items in sorted(groups.items()):
        good = [r for r in items if r['success']]
        metrics = {key: statistics([r[key] for r in good if key in r])
            for key in ('total_ms', 'before_core_ms', 'core_ms', 'after_core_ms',
                        'scope_union_ms', 'config_policy_union_ms', 'fixture_setup_ms')}
        labels = sorted({label for r in good for label in r['stages']})
        stages = {label: {metric: statistics([r['stages'].get(label, {}).get(metric, 0) for r in good])
            for metric in ('calls', 'inclusive_ms', 'exclusive_ms')} for label in labels}
        output.append({'suite': suite, 'condition': condition, 'channel': channel,
            'attempted': len(items), 'successful': len(good),
            'failures': [r['error_code'] for r in items if not r['success']],
            'metrics': metrics, 'stages': stages})
    return output


def write_report(directory, rows, metadata):
    aggregates = aggregate(rows)
    safe_rows = [{k: v for k, v in r.items() if k != 'spans'} for r in rows]
    result = {**metadata, 'schema': SCHEMA, 'records': safe_rows, 'aggregates': aggregates,
        'success': all(r['success'] for r in rows),
        'limitations': ['No real network or client display latency.',
            'Prompt, history, Scope, output budgets and guarded handlers differ by channel.',
            'Inclusive and cross-thread spans overlap; union time is not removable latency.',
            'Web history commit is test-client handling of successful DTO, not browser painting.']}
    # Only new files in this exclusive output directory; no source approvals/reports.
    path = directory/'results.json'
    temp = directory/'results.next.json'
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    with (directory/'samples.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        fields = ['sample','suite','condition','scenario','channel','phase','observed','success',
                  'error_code','workload','model_requests','total_ms','before_core_ms','core_ms',
                  'after_core_ms','scope_union_ms','config_policy_union_ms','fixture_setup_ms']
        writer = csv.DictWriter(stream, fields, extrasaction='ignore')
        writer.writeheader();writer.writerows(safe_rows)
    with (directory/'stages.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        fields = ['sample','stage','calls','inclusive_ms','exclusive_ms']
        writer = csv.DictWriter(stream, fields);writer.writeheader()
        for row in rows:
            for stage, value in row['stages'].items():
                writer.writerow({'sample':row['sample'], 'stage':stage, **value})
    lines = ['# Offline Web / QQ performance', '', 'P95 uses nearest rank and requires n >= 30.', '',
             '|Suite|Condition|Channel|Success|Median ms|P95 ms|Min / max ms|',
             '|---|---|---|---:|---:|---:|---:|']
    for group in aggregates:
        v=group['metrics']['total_ms']
        fmt=lambda x:'—' if x is None else f'{x:.3f}'
        lines.append(f"|{group['suite']}|{group['condition']}|{group['channel']}|{group['successful']}/{group['attempted']}|{fmt(v['median'])}|{fmt(v['p95'])}|{fmt(v['min'])} / {fmt(v['max'])}|")
    (directory/'SUMMARY.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def new_output(output_root=None):
    import stat
    allowed = ROOT/'outputs'/'performance'
    supplied = Path(output_root) if output_root else allowed
    for path in (supplied, *supplied.parents, allowed, *allowed.parents):
        if path.exists():
            info=path.lstat()
            if path.is_symlink() or getattr(info,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
                raise ValueError('Linked output directories are not allowed')
    allowed=allowed.resolve()
    root=supplied.resolve()
    if root != allowed and not root.is_relative_to(allowed):
        raise ValueError('Output must stay inside outputs/performance')
    root.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    target = root/('webqq-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    target.mkdir(exist_ok=False)
    return target


def run(args):
    directory = new_output(args.output_root)
    fixtures = directory/'fixtures';fixtures.mkdir()
    saved_temp = tempfile.tempdir
    tempfile.tempdir = str(fixtures)
    observer = Observer()
    rows = []
    metadata = {'mode': args.mode, 'suite': args.suite, 'network_requests': 0,
        'imports_ms': IMPORT_MS, 'python': platform.python_version(), 'platform': platform.platform(),
        'samples_requested': args.samples if args.mode == 'benchmark' else 2,
        'warmup_pairs': args.warmup, 'cold_definition': 'first fixture execution per condition; imports_ms separate',
        'timer': 'perf_counter_ns', 'p95': 'nearest-rank; withheld below 30 successful samples',
        'monitoring_schema': 2, 'fake_responses': 'one current-water call + one closed explanation',
        'source_access': 'new synthetic fixtures only'}
    print('REPORT_DIRECTORY='+str(directory), flush=True)
    interrupted = False
    try:
        with ExitStack() as stack:
            instrument(observer, stack)
            count = args.samples if args.mode == 'benchmark' else 2
            for condition in conditions(args.suite):
                phases = [('cold',0), *[('warmup',i) for i in range(args.warmup)],
                          *[('sample',i) for i in range(count)]]
                # Small alternating observed/unobserved probe, never pooled with samples.
                phases += [('observer_on',0),('observer_off',0),('observer_off',1),('observer_on',1)]
                for phase, index in phases:
                    for channel in (('web','qq') if index%2 == 0 else ('qq','web')):
                        sample=f'{condition.suite}-{condition.name}-{phase}-{index}-{channel}'
                        row=measure(channel,condition,fixtures,observer,sample,phase,
                                    observed=phase!='observer_off')
                        rows.append(row)
                        with (directory/'spans.jsonl').open('a',encoding='utf-8') as stream:
                            stream.write(json.dumps({'sample':sample,'spans':row['spans']})+'\n')
                        row.pop('spans')
                        observer.events.clear()  # All fixture workers joined; evidence is on disk.
                        if not row['success']:
                            print('SAMPLE_FAILED '+sample+' '+str(row['error_code']),flush=True)
                            # Record failures; unsafe SDK/resource cleanup ends the experiment.
                            SDK_RESOURCES.assert_healthy()
                            if row['error_code']=='OPERATOR_INTERRUPTED':
                                raise KeyboardInterrupt
                            if str(row['error_code']).startswith('CLEANUP_'):
                                raise RuntimeError('Unsafe fixture cleanup')
                write_report(directory,rows,metadata)
                good=sum(r['success'] for r in rows if r['condition']==condition.name and r['phase']=='sample')
                print(f'{condition.suite}/{condition.name}: {good}/{2*count} samples',flush=True)
    except KeyboardInterrupt:
        interrupted=True;metadata['stop_code']='OPERATOR_INTERRUPTED'
    except Exception as error:
        metadata['stop_code']=safe_code(error)
    finally:
        tempfile.tempdir=saved_temp
        metadata['threads_remaining']=[t.name for t in threading.enumerate()
            if t.name.startswith(('qq-ai-','fishery-sdk-request'))]
        metadata['completed']=not interrupted and 'stop_code' not in metadata
        write_report(directory,rows,metadata)
    print('RESULTS='+str(directory/'results.json'),flush=True)
    print('SUMMARY='+str(directory/'SUMMARY.md'),flush=True)
    return 0 if metadata['completed'] and not metadata['threads_remaining'] and all(r['success'] for r in rows) else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline synthetic Web/QQ measurement only')
    parser.add_argument('--mode',choices=('smoke','benchmark'),default='smoke')
    parser.add_argument('--suite',choices=('both','core','entry'),default='both')
    parser.add_argument('--samples',type=int,default=30)
    parser.add_argument('--warmup',type=int,default=2)
    parser.add_argument('--output-root')
    args=parser.parse_args(argv)
    if not 30<=args.samples<=300 or not 1<=args.warmup<=5:
        parser.error('samples must be 30..300 and warmup 1..5')
    try:
        return run(args)
    except Exception as error:
        print('EXPERIMENT_STOPPED '+safe_code(error),flush=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
