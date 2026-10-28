"""Local-only real-type assembly over MockTransport and new synthetic SQLite."""
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import hashlib
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import subprocess
import shutil
import threading
import unittest
from unittest.mock import patch

import httpx

from apps.ai_backend.credentials import CredentialStore
from apps.ai_service.channel_hybrid_research import prepared_scope, preparation_record
from apps.ai_service.channel_trial import PRESET
from apps.ai_service.runtime.assistant import assistant_profile
from apps.qq_bot.contracts import BotError
from apps.qq_bot.hybrid_research import (HybridResearchRun, check_configuration, experiment_plan,
    summarize, private_directory)
from apps.qq_bot.hybrid_research_cli import run_experiment, main
from apps.qq_bot.hybrid_research_suite import load_suite, allocate
from apps.qq_bot.run_consent import RunLimits
from apps.qq_bot.tests import test_session_run as base
from apps.qq_bot.tests import test_hybrid_run as hybrid_fixture


class HybridResearchTests(unittest.TestCase):
    make=base.SessionRunTests.make
    ingest=base.SessionRunTests.ingest
    packet=base.SessionRunTests.packet
    factory=hybrid_fixture.HybridRunTests.factory

    def setUp(self):
        base.SessionRunTests.setUp(self)
        self.http=[];self.mode='general';self.started=threading.Event()
        self.general_text='溶解氧是溶解在水中的氧气；这是一般概念说明。'
        self.cases=load_suite()

    def entry(self, ident='A01', repeat=1):
        return dict(case=asdict(next(c for c in self.cases if c.id==ident)),repetition=repeat)

    def host(self, *, approve=True, turns=5, real=False, allow_raw=False):
        directory=self.root/('research-'+str(len(list(self.root.glob('research-*')))))
        private_directory(directory)
        host=HybridResearchRun(self.inputs,directory,instance_root=self.instance,
            instance_id='test-instance',device_id='sim-pond-1',limits=RunLimits(turns),
            async_client_factory=None if real else self.factory,clock=lambda:self.now,allow_raw=allow_raw)
        self.addCleanup(host.close)
        if approve:host.approve(host.plan(),confirmed=True)
        return host

    def plan(self, ids=None, *, total='100', repeat=1):
        plan=experiment_plan(self.inputs,self.cases,instance_root=self.instance,
            instance_id='test-instance',device_id='sim-pond-1',case_ids=ids or ['A01','A02'],
            repetitions=repeat,total_budget_cny=total,memory_fixture=True)
        plan['approval_deadline']=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
        return plan

    def batch(self, plan, *, prompt=lambda *_:True, emit=lambda _:None):
        directory=self.root/('batch-'+str(len(list(self.root.glob('batch-*')))))
        private_directory(directory)
        result=run_experiment(self.inputs,plan,directory,prompt=prompt,
            async_client_factory=self.factory,clock=lambda:self.now,emit=emit)
        return directory,result

    def test_suite_48_cases_categories_and_repeat_allocations(self):
        self.assertEqual(len(self.cases),48)
        self.assertEqual(set(c.category for c in self.cases),set('ABCDE'))
        plan=allocate(self.cases,total_budget_cny='80')
        self.assertEqual((plan['max_turns'],plan['run_count'],plan['max_model_requests']),(48,10,96))
        self.assertEqual(plan['total_run_budgets_cny'],'76.99')
        large=allocate(self.cases,repetitions=5,total_budget_cny='400')
        self.assertEqual(large['max_turns'],240)
        self.assertTrue(all(r['max_turns']<=5 for r in large['runs']))
        for r in large['runs']:
            for e in r['entries']:
                if e['case']['dialogue']:
                    self.assertEqual(sum(d['case']['dialogue']==e['case']['dialogue'] for d in r['entries']),5)

    def test_budget_insufficient_does_not_silently_reduce_selection(self):
        with self.assertRaisesRegex(BotError,'EXPERIMENT_BUDGET_INSUFFICIENT'):
            allocate(self.cases,total_budget_cny='8.02')
        with self.assertRaisesRegex(BotError,'RESEARCH_DIALOGUE_MUST_BE_COMPLETE'):
            allocate(self.cases,case_ids=['D01'])
        with self.assertRaisesRegex(BotError,'INVALID_RESEARCH_LIMITS'):
            allocate(self.cases,repetitions=6)
        with self.assertRaisesRegex(BotError,'INVALID_RUN_LIMITS'):RunLimits(6)

    def test_no_approval_no_model_no_quota(self):
        host=self.host(approve=False)
        row=host.execute_case(self.entry())
        self.assertEqual(row['code'],'RUN_NOT_APPROVED');self.assertEqual(self.http,[])
        self.assertEqual(host.ledger.report()['consumed_turns'],0)

    def test_general_one_model_zero_tool_and_local_not_qq_history(self):
        host=self.host();before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch.object(host.monitoring,'capture_water',side_effect=AssertionError('no general SQL')):
            row=host.execute_case(self.entry())
        self.assertIsNone(row['code']);self.assertEqual(row['model_requests'],1)
        self.assertEqual(row['execution']['tool_handler_calls'],0)
        self.assertTrue(row['model_contract_valid']);self.assertEqual(row['history_code'],'HISTORY_COMMITTED')
        self.assertFalse(row['qq_api_accepted']);self.assertEqual(row['sdk_resources']['state'],'CLOSED')
        self.assertEqual(host.ledger.report()['reserved_cost_cny'],'1.602765')
        review=json.loads((host.directory/row['review_file']).read_text('utf8'))
        self.assertNotIn('model_output_json_or_text',review);self.assertFalse(review['human_quality_verified'])
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_raw_output_requires_separate_bound_run_consent(self):
        host=self.host()
        self.assertFalse(host.plan()['raw_model_output_allowed'])
        with self.assertRaisesRegex(BotError,'RESEARCH_RAW_OUTPUT_NOT_APPROVED'):
            host.execute_case(self.entry(),save_raw=True)
        self.assertEqual(self.http,[]);self.assertEqual(host.ledger.report()['consumed_turns'],0)
        other=self.host(allow_raw=True);row=other.execute_case(self.entry(),save_raw=True)
        self.assertTrue(other.plan()['raw_model_output_allowed'])
        review=json.loads((other.directory/row['review_file']).read_text('utf8'))
        self.assertIn('model_output_json_or_text',review)

    def test_water_two_models_one_tool_and_source_preserved(self):
        self.mode='water';host=self.host()
        with patch.object(host.monitoring,'capture_water',wraps=host.monitoring.capture_water) as read:
            row=host.execute_case(self.entry('B02'))
        self.assertEqual((row['model_requests'],read.call_count),(2,1))
        self.assertTrue(row['tool_choice_matches_expected']);self.assertTrue(row['model_contract_valid'])
        self.assertEqual(row['execution']['tool_handler_calls'],1)
        review=json.loads((host.directory/row['review_file']).read_text('utf8'))
        self.assertEqual(review['source']['source_kind'],'simulator');self.assertTrue(review['source']['rule_hits'])

    def test_mixed_dialogue_uses_locally_captured_history_not_old_water_values(self):
        host=self.host()
        a=host.execute_case(self.entry('D01'));b=host.execute_case(self.entry('D02'))
        self.mode='water';c=host.execute_case(self.entry('D03'))
        self.ingest(oxygen=6.1);d=host.execute_case(self.entry('D04'))
        self.assertEqual([r['history_before'] for r in (a,b,c,d)],[0,1,2,3])
        transcript=json.dumps(self.http[-2]['messages'],ensure_ascii=False)
        self.assertIn('本地研究',transcript);self.assertNotIn('2.2',transcript)
        self.assertIn('6.1',json.dumps(self.http[-1],ensure_ascii=False))

    def test_independent_cases_and_new_runs_do_not_inherit_history(self):
        host=self.host();host.execute_case(self.entry('A01'))
        row=host.execute_case(self.entry('A02'));self.assertEqual(row['history_before'],0)
        other=self.host();self.assertEqual(other.store.counts()['turns'],0)
        self.assertNotEqual(host.ledger.plan()['consent_id'],other.ledger.plan()['consent_id'])

    def test_bad_json_and_unbacked_current_claim_are_recorded_not_success(self):
        host=self.host();self.mode='bad_json'
        row=host.execute_case(self.entry('A01'))
        self.assertFalse(row['model_contract_valid']);self.assertFalse(row['execution']['json_syntax_valid'])
        self.assertFalse(row['stop_required']);self.assertEqual(host.store.counts()['turns'],0)
        self.mode='general';self.general_text='我已查询现场，当前水质正常。'
        row=host.execute_case(self.entry('B01'))
        self.assertFalse(row['tool_choice_matches_expected']);self.assertFalse(row['model_contract_valid'])
        self.assertEqual(row['code'],'GENERAL_PUBLICATION_REJECTED')
        self.assertEqual(host.ledger.report()['consumed_turns'],2)

    def test_tool_then_general_facts_only_not_valid_explanation(self):
        host=self.host();self.mode='water_general'
        row=host.execute_case(self.entry('B01'))
        self.assertFalse(row['model_contract_valid']);self.assertTrue(row['local_capture_saved'])
        review=json.loads((host.directory/row['review_file']).read_text('utf8'))
        self.assertIn('2.2 mg/L',review['text']);self.assertNotIn(self.general_text,review['text'])

    def test_stale_partial_missing_never_invents_current_hit(self):
        self.ingest('missing');self.now+=timedelta(seconds=122);self.mode='water';host=self.host()
        row=host.execute_case(self.entry('B05'))
        review=json.loads((host.directory/row['review_file']).read_text('utf8'))
        source=review['source'];self.assertEqual(source['rule_hits'],[])
        for word in ('SIMULATOR','过期','离线','缺测'):self.assertIn(word,review['text'])

    def test_last_reserved_turn_finishes_then_limit_without_refund(self):
        host=self.host(turns=1);first=host.execute_case(self.entry())
        self.assertTrue(first['model_contract_valid'])
        row=host.execute_case(self.entry('A02'));self.assertEqual(row['code'],'RUN_TURN_LIMIT')
        self.assertEqual(len(self.http),1);self.assertEqual(host.ledger.report()['consumed_turns'],1)

    def test_repeated_message_no_second_consumption(self):
        host=self.host();host.execute_case(self.entry())
        with self.assertRaisesRegex(BotError,'RESEARCH_CASE_ALREADY_RECORDED'):host.execute_case(self.entry())
        self.assertEqual(len(self.http),1);self.assertEqual(host.ledger.report()['consumed_turns'],1)

    def test_scope_change_and_permission_revocation_zero_new_request(self):
        host=self.host();self.assertEqual(len(self.http),0)
        value=json.loads((self.root/'ai.json').read_text('utf8'));value['enabled']=False
        (self.root/'ai.json').write_text(json.dumps(value),encoding='utf8')
        row=host.execute_case(self.entry());self.assertTrue(row['stop_required']);self.assertEqual(self.http,[])

    def test_expiry_no_request(self):
        host=self.host();self.now+=timedelta(hours=1)
        row=host.execute_case(self.entry());self.assertEqual(row['code'],'RUN_EXPIRED');self.assertEqual(self.http,[])

    def test_busy_does_not_consume(self):
        host=self.host();host._case_lock.acquire()
        try:
            with self.assertRaisesRegex(BotError,'RESEARCH_BUSY'):host.execute_case(self.entry())
        finally:host._case_lock.release()
        self.assertEqual(host.ledger.report()['consumed_turns'],0)

    def test_cancel_live_mock_sdk_closes_and_no_more_model(self):
        host=self.host();self.mode='blocked';stopped=threading.Event();rows=[]
        thread=threading.Thread(target=lambda:rows.append(host.execute_case(self.entry(),stop_event=stopped)))
        thread.start();self.assertTrue(self.started.wait(15));stopped.set();thread.join(20)
        self.assertFalse(thread.is_alive());self.assertTrue(rows[0]['stop_required'])
        self.assertEqual(rows[0]['sdk_resources']['state'],'CLOSED');self.assertEqual(len(self.http),1)

    def test_batch_two_independent_runs_single_enumerated_operator_approval(self):
        calls=[];plan=self.plan(['A01','A02','A03','A04','A05','A06'])
        directory,report=self.batch(plan,prompt=lambda p,s:calls.append(p) or True)
        self.assertTrue(report['completed']);self.assertEqual(len(calls),1)
        self.assertEqual(len(report['runs']),2);self.assertEqual(report['summary']['model_requests'],6)
        self.assertEqual([r['quota']['consumed_turns'] for r in report['runs']],[5,1])
        self.assertTrue(report['ram_cleared']);self.assertTrue((directory/'result.json').is_file())
        self.assertTrue((directory/'results.csv').is_file())
        self.assertEqual(len(list(directory.glob('*.used'))),1)

    def test_decline_stops_before_database_or_credentials(self):
        plan=self.plan()
        with patch('apps.qq_bot.hybrid_research_cli.HybridResearchRun',side_effect=AssertionError('no DB')):
            directory,report=self.batch(plan,prompt=lambda *_:False)
        self.assertEqual(report['code'],'RESEARCH_OPERATOR_CANCELLED');self.assertEqual(self.http,[])
        self.assertFalse((directory/'approval.json').exists())

    def test_provider_failure_stops_batch_no_retry_and_keeps_reserved_turn(self):
        self.mode='provider_error';directory,report=self.batch(self.plan())
        self.assertFalse(report['completed']);self.assertEqual(len(self.http),1)
        self.assertEqual(report['runs'][0]['quota']['consumed_turns'],1)
        self.assertEqual(report['summary']['unexecuted_turns'],1)
        self.assertIsNone(report['rows'][0]['tool_choice_matches_expected'])
        self.assertEqual(report['summary']['tool_choice']['n'],0)
        self.assertTrue((directory/'result.json').is_file())

    def test_bad_contracts_counted_and_next_distinct_sample_not_retried(self):
        self.mode='bad_json';directory,report=self.batch(self.plan())
        self.assertTrue(report['completed']);self.assertEqual(len(self.http),2)
        self.assertEqual(report['summary']['contracts']['general']['passed'],0)
        self.assertEqual(len(report['summary']['failures']),2)

    def test_report_failure_is_false_not_silent_success(self):
        from apps.qq_bot.hybrid_research_cli import write_new
        def save(path,value):
            if path.name=='result.json' and path.parent.name.startswith('batch-'):raise OSError('synthetic disk fault')
            return write_new(path,value)
        with patch('apps.qq_bot.hybrid_research_cli.write_new',side_effect=save):
            _,report=self.batch(self.plan(['A01']))
        self.assertFalse(report['report_saved']);self.assertEqual(report['code'],'RESEARCH_FINAL_REPORT_FAILED')
        self.assertEqual(len(self.http),1)

    def test_auxiliary_report_failure_persists_failed_final_status(self):
        with patch('apps.qq_bot.hybrid_research_cli.write_csv',side_effect=OSError('synthetic disk fault')):
            directory,report=self.batch(self.plan(['A01']))
        saved=json.loads((directory/'result.json').read_text('utf8'))
        self.assertTrue(report['report_saved']);self.assertFalse(saved['completed'])
        self.assertEqual(saved['code'],'RESEARCH_AUX_REPORT_FAILED');self.assertEqual(len(self.http),1)

    def test_capture_failure_blocks_history_and_next_request(self):
        host=self.host()
        with patch('apps.qq_bot.hybrid_research.private_record',side_effect=OSError('synthetic fault')):
            row=host.execute_case(self.entry())
        self.assertTrue(row['stop_required']);self.assertEqual(host.store.counts()['turns'],0)
        host.execute_case(self.entry('A02'));self.assertEqual(len(self.http),1)

    def test_no_p95_or_quality_claim_from_tiny_sample(self):
        host=self.host();row=host.execute_case(self.entry())
        summary=summarize([row],planned_turns=48)
        self.assertIsNone(summary['latency_ms']['p95']);self.assertIsNone(summary['answering_quality_correct'])
        self.assertEqual(summary['unexecuted_turns'],47)

    def test_invalid_multiple_tool_selection_not_mistaken_for_general(self):
        from types import SimpleNamespace
        from apps.ai_backend.tool_conversation import ModelExecutionStep, ModelStepOutcome
        from apps.ai_service.channel_hybrid_research import ResearchHybridTurn
        target=SimpleNamespace()
        result=SimpleNamespace(final_text='',status=SimpleNamespace(value='failed'),error_code='TOOL_CALL_LIMIT',
            execution=SimpleNamespace(steps=(ModelExecutionStep(1,1,
                ModelStepOutcome('multiple_tool_calls',finish_reason='tool_calls',error_code='TOOL_CALL_LIMIT')),)))
        ResearchHybridTurn.inspect_execution(target,result)
        self.assertEqual(target.execution_metadata['actual_branch'],'general')
        self.assertEqual(target.execution_metadata['model_route'],'water')
        self.assertEqual(target.execution_metadata['tool_handler_calls'],0)
        self.assertIsNone(target.execution_metadata['json_syntax_valid'])

    def test_batch_plan_mutation_during_approval_rejected_without_model(self):
        def tamper(plan,stopped):
            plan['allocation']['max_turns']=999
            return True
        _,report=self.batch(self.plan(),prompt=tamper)
        self.assertEqual(report['code'],'RESEARCH_PLAN_CHANGED');self.assertEqual(self.http,[])

    def test_scope_change_is_sticky_before_model(self):
        from apps.qq_bot import hybrid_research as module
        host=self.host();scope={**host.scope,'modified_scope':True}
        with patch.object(module,'prepared_scope',return_value=scope):row=host.execute_case(self.entry())
        self.assertEqual(row['code'],'RUN_SCOPE_CHANGED');self.assertEqual(self.http,[])
        self.assertIsNotNone(host.ledger.report()['stop_code'])

    def test_ledger_write_failure_zero_sdk_request(self):
        host=self.host()
        with patch.object(host.ledger,'_append',side_effect=OSError('synthetic fsync failure')):
            row=host.execute_case(self.entry())
        self.assertEqual(row['code'],'RUN_LEDGER_FAILED');self.assertEqual(self.http,[])
        self.assertEqual(host.ledger.report()['consumed_turns'],1)

    def test_history_commit_failure_no_retry_and_stops(self):
        host=self.host()
        with patch.object(host.store,'commit',side_effect=MemoryError('synthetic fault')):
            row=host.execute_case(self.entry())
        self.assertTrue(row['local_capture_saved']);self.assertTrue(row['stop_required'])
        self.assertEqual(host.store.counts()['turns'],0);self.assertEqual(len(self.http),1)

    def test_checkpoint_fsync_failure_stops_batch(self):
        from apps.qq_bot import hybrid_research as module
        save=module.write_new
        def failure(path,value):
            if path.name.endswith('.capture.json'):raise OSError('synthetic fsync')
            return save(path,value)
        with patch.object(module,'write_new',side_effect=failure):
            _,report=self.batch(self.plan())
        self.assertFalse(report['completed']);self.assertEqual(len(self.http),1)
        self.assertNotEqual(report['rows'][0]['history_code'],'HISTORY_COMMITTED')

    def test_operator_interrupt_saves_partial_and_clears_ram(self):
        with patch.object(HybridResearchRun,'execute_case',side_effect=KeyboardInterrupt):
            directory,report=self.batch(self.plan())
        self.assertEqual(report['code'],'RESEARCH_OPERATOR_INTERRUPTED')
        self.assertTrue(report['report_saved']);self.assertTrue(report['ram_cleared'])
        self.assertEqual(self.http,[]);self.assertTrue((directory/'result.json').exists())

    def test_permission_revoke_during_model_cancels_io(self):
        host=self.host();self.mode='blocked';rows=[]
        thread=threading.Thread(target=lambda:rows.append(host.execute_case(self.entry())))
        thread.start();self.assertTrue(self.started.wait(15))
        value=json.loads((self.root/'ai.json').read_text('utf8'));value['enabled']=False
        (self.root/'ai.json').write_text(json.dumps(value),encoding='utf8')
        thread.join(20)
        self.assertFalse(thread.is_alive());self.assertTrue(rows[0]['stop_required'])
        self.assertEqual(rows[0]['sdk_resources']['state'],'CLOSED')

    def test_unapproved_member_is_not_selected_and_configuration_fails(self):
        from dataclasses import replace
        bad=replace(self.inputs,member_id='intruder')
        with self.assertRaisesRegex(BotError,'TRIAL_MEMBER_NOT_APPROVED'):
            check_configuration(bad,instance_root=self.instance,instance_id='test-instance',
                                device_id='sim-pond-1',memory_fixture=True)
        self.assertEqual(self.http,[])

    def test_old_approval_json_cannot_initialize_turn(self):
        from apps.ai_service.channel_hybrid_research import ResearchAuthority
        from apps.ai_backend.model_gateway import GatewayError
        authority=ResearchAuthority(lambda _:None)
        with self.assertRaisesRegex(GatewayError,'RESEARCH_APPROVAL_REQUIRED'):
            authority.validate({'contract':'qq-qwen-bounded-session-real-trial@1','status':'local_experimental'})

    def test_free_template_case_rejected_without_model_or_quota(self):
        host=self.host();entry=self.entry();entry['case']['question']='你好'
        with self.assertRaisesRegex(BotError,'RESEARCH_CASE_NOT_AGENT'):host.execute_case(entry)
        self.assertEqual(self.http,[]);self.assertEqual(host.ledger.report()['consumed_turns'],0)

    def test_shared_sdk_quarantine_refuses_new_local_request(self):
        from apps.ai_backend.model_gateway import GatewayError
        from apps.qq_bot import hybrid_research as module
        host=self.host()
        with patch.object(module.SDK_RESOURCES,'assert_healthy',side_effect=GatewayError('SDK_RESOURCE_QUARANTINED')):
            row=host.execute_case(self.entry())
        self.assertTrue(row['stop_required']);self.assertEqual(self.http,[])
        self.assertIsNotNone(host.ledger.report()['stop_code'])

    def test_batch_approval_changed_after_first_capture_stops_before_second_model(self):
        from apps.qq_bot import hybrid_research as module
        save=module.private_record
        def change(path,value):
            save(path,value)
            approval=path.parent.parent.parent/'approval.json'
            current=json.loads(approval.read_text('utf8'));current['claim_id']='tampered'
            approval.write_text(json.dumps(current),encoding='utf8')
        with patch.object(module,'private_record',side_effect=change):_,report=self.batch(self.plan())
        self.assertFalse(report['completed']);self.assertEqual(len(self.http),1)
        self.assertEqual(report['rows'][0]['code'],'RESEARCH_BATCH_APPROVAL_CHANGED')

    def test_output_json_duplicate_and_fake_receipt_refused(self):
        host=self.host()
        for i,mode in enumerate(('duplicate_json','fake_receipt','no_tool_water'),1):
            self.mode=mode;row=host.execute_case(self.entry('A0'+str(i)))
            self.assertFalse(row['model_contract_valid'])
            self.assertEqual(row['history_code'],'NOT_COMMITTED_PRESENTATION')
        self.assertEqual(len(self.http),3)

    def test_check_and_powershell_check_read_only_metadata_no_database(self):
        from apps.qq_bot import hybrid_research as module
        # Only metadata points at the explicit known isolated root. Check cannot
        # open even that path; the actual synthetic DB stays in this temporary fixture.
        value=json.loads((self.root/'source.json').read_text('utf8'))
        value.update(data_root=str(module.ROOT/'outputs/bot2c-instance'),instance_id='bot2c-isolated')
        (self.root/'source.json').write_text(json.dumps(value),encoding='utf8')
        request=self.root/'request.json';request.write_text(json.dumps(self.inputs.dictionary()),encoding='utf8')
        args=['--check','--request-file',str(request),'--instance-root',value['data_root'],
              '--instance-id','bot2c-isolated','--device-id','sim-pond-1','--total-budget-cny','80']
        with patch('apps.qq_bot.session_run.InstanceMonitoring',side_effect=AssertionError('no DB')), \
                patch.object(module,'project_credentials',side_effect=AssertionError('no credentials')), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(main(args),0)
        pwsh=shutil.which('pwsh')
        if not pwsh:self.skipTest('PowerShell7 not available')
        script=module.ROOT/'scripts/dev/Test-HybridProvider.ps1'
        process=subprocess.run([pwsh,'-NoProfile','-File',str(script),'-Check','-RequestFile',str(request),
            '-InstanceRoot',value['data_root'],'-TotalBudgetCny','80'],capture_output=True,text=True,
            encoding='utf8',timeout=40)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertIn('LOCAL_HYBRID_CHECKED_APPROVAL_REQUIRED',process.stdout)
        self.assertEqual(self.http,[])

    def test_real_typed_service_and_real_sdk_over_memory_http_only(self):
        from apps.qq_bot import hybrid_research as module
        from apps.ai_service import channel_trial
        from apps.ai_service.channel_hybrid_research import ResearchHybridTurn
        target=self.root/'outputs'/'bot2c-instance';target.mkdir(parents=True)
        src=sqlite3.connect(self.path);dst=sqlite3.connect(target/'monitoring.sqlite3')
        try:src.backup(dst)
        finally:src.close();dst.close()
        value=json.loads((self.root/'source.json').read_text('utf8'));value['data_root']=str(target)
        (self.root/'source.json').write_text(json.dumps(value),encoding='utf8')
        self.instance=target;calls=[]
        def http(**kwargs):
            async def respond(request):
                calls.append(request.method)
                return httpx.Response(200,json={'id':'synthetic','object':'chat.completion','created':0,
                    'model':assistant_profile(PRESET).model,'choices':[{'index':0,'message':{'role':'assistant',
                        'content':json.dumps({'contract':'qq-hybrid-reply@1','kind':'general','text':self.general_text})},
                        'finish_reason':'stop'}], 'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
            return httpx.AsyncClient(transport=httpx.MockTransport(respond),**kwargs)
        credentials=CredentialStore(process_env={assistant_profile(PRESET).credential_ref:'fictional-test-only'})
        with patch.object(module,'ROOT',self.root),patch.object(module,'project_credentials',return_value=credentials) as supplier, \
                patch.object(channel_trial,'_TrialHTTPClient',side_effect=http):
            host=self.host(real=True);row=host.execute_case(self.entry())
        self.assertIsNone(row['code']);self.assertIs(type(host.sessions[-1]),ResearchHybridTurn)
        self.assertFalse(row['offline_test']);self.assertEqual(row['model_http_requests'],1)
        self.assertEqual(host.sessions[-1].approval.phase,'provider')
        self.assertFalse(row['qq_api_accepted']);self.assertEqual(calls,['POST']);supplier.assert_called_once()


if __name__=='__main__':unittest.main()
