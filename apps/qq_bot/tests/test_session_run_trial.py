"""Typed live path with real SDK classes + memory HTTP, never live keys/network."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock,patch
from contextlib import redirect_stdout
from io import StringIO

import httpx

from apps.ai_service.channel_session_trial import (SessionTrialQwenTurn,RunAuthorization,
    prepared_scope,preparation_record,CONTRACT)
from apps.ai_service.runtime.release_contracts import _hash
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.ai_coordinator import QQAICoordinator
from apps.qq_bot.ai_routing import TrialQQAIRouter
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.ai_trial_delivery import SessionQQTransport
from apps.qq_bot.contracts import BotError
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.run_consent import RunLimits
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.session_run import SessionRun
from apps.qq_bot.session_run_trial import SessionTrialRun,check_configuration
from apps.qq_bot.session_run_trial_cli import main,run_session
from apps.qq_bot.transport import QQAPI
from apps.qq_bot.trial_configuration import write_new,read_json
from apps.qq_bot.tests import test_session_run as base
from apps.qq_bot.tests import test_conversation_trial as old

APP=base.APP
ROOT=Path(__file__).resolve().parents[3]


class SessionRunTrialTests(unittest.TestCase):
    packet=base.SessionRunTests.packet
    ingest=base.SessionRunTests.ingest
    make=base.SessionRunTests.make
    factory=base.SessionRunTests.factory
    receive=old.ConversationTrialTests.receive
    ask=old.ConversationTrialTests.ask
    qq_http=old.ConversationTrialTests.qq_http
    test_actual_tool_definition_is_bound_to_real_scope=base.SessionRunTests.test_changed_actual_tool_definition_cannot_use_prepared_scope
    test_last_reserved_real_turn_completes=base.SessionRunTests.test_last_reserved_turn_completes_and_no_extra_model_request
    test_duplicate_whole_run_does_not_consume=base.SessionRunTests.test_duplicate_message_after_ingress_cache_expiry_does_not_consume

    def setUp(self):
        base.SessionRunTests.setUp(self);self.posts=[]
        self.api=QQAPI(APP,Mock(side_effect=AssertionError('no real secret')),
            client=httpx.Client(transport=httpx.MockTransport(self.qq_http),trust_env=False,follow_redirects=False))
        self.api._token='fictional-only';self.api._expires=time.monotonic()+3600
        self.addCleanup(self.api.close)

    def create(self,*,members=None,turns=5):
        self.directory=self.root/'run';self.directory.mkdir()
        self.host=SessionTrialRun(self.inputs,self.directory,members=members,limits=RunLimits(max_turns=turns),
            async_client_factory=self.factory,clock=lambda:self.now)
        self.addCleanup(self.host.close);return self.host

    def compose(self,*,members=None,turns=5):
        self.create(members=members,turns=turns);self.host.approve(self.host.plan(),confirmed=True)
        self.coordinator=QQAICoordinator(self.host.access,self.host.monitoring,self.host.base_service,
            config=self.host.config,conversations=self.host.store,session_run=self.host,clock=lambda:self.now)
        transport=SessionQQTransport(self.api,self.host);transport.reconnect()
        self.scheduler=QQAIJobScheduler(self.coordinator,transport,clock=lambda:self.now)
        adapter=QQAdapter(self.host.access,ReadOnlyQueries(self.host.monitoring,None),mode='QQ_PASSIVE_READY',clock=lambda:self.now)
        self.router=TrialQQAIRouter(adapter,self.scheduler)
        self.gateway=QQGateway(APP,self.api,adapter,trial_router=self.router,clock=lambda:self.now,
            connector=lambda _:None,emit=lambda *_a,**_k:None)
        def close():
            try:self.router.close()
            except BotError as error:
                if error.code!='AI_SDK_RESOURCE_UNSAFE':raise
            self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))
        self.addCleanup(close)

    def test_once_approved_five_typed_turns_resources_and_current_sources(self):
        self.compose();before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch.object(self.host.monitoring,'capture_water',wraps=self.host.monitoring.capture_water) as read:
            for i in range(5):self.assertEqual(self.ask()['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(read.call_count,5);self.assertEqual(len(self.http),10);self.assertEqual(len(self.posts),5)
        self.assertTrue(all(type(s) is SessionTrialQwenTurn and s.requests==2 for s in self.host.sessions))
        self.assertTrue(all(s.report()['sdk_resources']['state']=='CLOSED' for s in self.host.sessions))
        self.assertTrue(all(t['verified'] for t in self.host.turns))
        self.assertEqual(self.receive()[0],'RUN_TURN_LIMIT')
        self.assertEqual(self.host.ledger.report()['reserved_cost_cny'],'8.013825')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_unapproved_transport_and_declined_controller_have_zero_requests(self):
        self.create()
        with self.assertRaisesRegex(BotError,'RUN_NOT_APPROVED'):SessionQQTransport(self.api,self.host)
        result,_=self.run_fake(prompt=lambda *_:False)
        self.assertEqual(result['code'],'SESSION_OPERATOR_CANCELLED')
        self.assertEqual(self.http,[]);self.assertEqual(self.posts,[])
        self.assertFalse((self.directory/'approval.json').exists());self.assertTrue(result['report_saved'])

    def test_fake_only_host_and_json_flags_cannot_authorize_live_types(self):
        self.directory=self.root/'fake';self.directory.mkdir()
        host=SessionRun(self.inputs,self.directory,async_client_factory=self.factory,clock=lambda:self.now)
        self.addCleanup(host.close);host.approve(host.plan(),confirmed=True)
        with self.assertRaisesRegex(BotError,'SESSION_TRIAL_COMPOSITION_REQUIRED'):SessionQQTransport(self.api,host)
        with self.assertRaisesRegex(Exception,'SESSION_TRIAL_RUN_AUTHORIZATION_REQUIRED'):
            SessionTrialQwenTurn(None,run_authorization={'can_send':True},authority=None,
                conversation_epoch='fake',options=host.options,snapshot=None,validate=lambda:None,claim=lambda:None)
        self.assertEqual(self.http,[])

    def test_scope_preparation_flags_cannot_promote_candidate(self):
        from apps.qq_bot import session_run_trial as module
        original=module.read_json
        def altered(path):
            value=original(path)
            if Path(path).name=='qq_session_run_trial.json':value['status']='local_experimental'
            return value
        with patch.object(module,'read_json',side_effect=altered),patch('apps.qq_bot.session_run.InstanceMonitoring',side_effect=AssertionError('no database')):
            with self.assertRaisesRegex(Exception,'SESSION_TRIAL_SCOPE_REVIEW_REQUIRED'):check_configuration(self.inputs)

    def test_check_metadata_never_reads_credentials_or_database(self):
        with patch('apps.qq_bot.session_run.InstanceMonitoring',side_effect=AssertionError('no database')),\
                patch('apps.qq_bot.session_run_trial.project_credentials',side_effect=AssertionError('no keys')):
            value=check_configuration(self.inputs)
        self.assertEqual(value['network_requests'],0);self.assertFalse(value['approval_created'])

    def test_approval_is_current_process_exact_scope_and_cannot_be_reused(self):
        self.create();plan=self.host.plan();changed=json.loads(json.dumps(plan));changed['limits']['max_turns']=4
        with self.assertRaisesRegex(BotError,'INVALID_SESSION_TRIAL_APPROVAL'):self.host.approve(changed,confirmed=True)
        self.host.approve(plan,confirmed=True)
        with self.assertRaisesRegex(BotError,'INVALID_SESSION_TRIAL_APPROVAL'):self.host.approve(plan,confirmed=True)
        self.assertEqual(len(list(self.directory.glob('*.used'))),1)

    def test_cloned_authorization_and_other_lease_authority_are_rejected(self):
        from apps.ai_service.channel_session_run import LeaseAuthority
        self.compose();authorization=self.host._authorization
        with self.assertRaisesRegex(Exception,'SESSION_TRIAL_RUN_AUTHORIZATION_REQUIRED'):
            authorization.authority.validate(replace(authorization,ticket=object()))
        other=LeaseAuthority(lambda _:None)
        lease=other._issue(approval_id=authorization.consent_id+'-1',sequence=1,
            scope_sha256=authorization.scope_sha256,bindings_sha256=authorization.bindings_sha256,
            expires_at=self.now+timedelta(seconds=90),instance_id='test-instance',device_id='sim-pond-1',
            app_id=APP,group_id='group-a',member_id='member-a',message_key='fake')
        with self.assertRaisesRegex(Exception,'SESSION_TRIAL_LEASE_BINDING_CHANGED'):
            SessionTrialQwenTurn(lease,run_authorization=authorization,authority=self.host.store.authority,
                conversation_epoch=self.host.base_service.epoch,options=self.host.options,snapshot=None,
                validate=lambda:None,claim=lambda:None,async_client_factory=self.factory)
        self.assertEqual(self.http,[])

    def test_approval_expiry_and_changed_approval_halt(self):
        self.create();plan=self.host.plan();self.now+=timedelta(minutes=11)
        with self.assertRaisesRegex(BotError,'INVALID_SESSION_TRIAL_APPROVAL'):self.host.approve(plan,confirmed=True)

    def test_approval_file_tamper_after_first_reply_halts_before_new_sdk(self):
        self.compose();self.ask();value=read_json(self.directory/'approval.json');value['qualification_id']='forged'
        write_new(self.directory/'tampered.json',value);(self.directory/'tampered.json').replace(self.directory/'approval.json')
        self.assertEqual(self.receive()[0],'RUN_APPROVAL_CHANGED');self.assertEqual(len(self.http),2)

    def test_shared_quota_and_busy_do_not_charge_fourth_member(self):
        self.compose(members=self.members);self.mode='blocked'
        _,first=self.receive();self.assertTrue(self.started.wait(3))
        for member in self.members[1:3]:self.assertEqual(self.receive(member=member)[0],'AI_ADMITTED')
        self.assertEqual(self.receive(member=self.members[3])[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],3)

    def test_long_ledger_contention_is_safe_busy_reply_without_charge(self):
        self.compose()
        with patch.object(self.host.ledger,'reserve',side_effect=BotError('RUN_ADMISSION_BUSY')):
            self.assertEqual(self.receive()[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],0)
        self.assertEqual(self.http,[]);self.assertEqual(len(self.posts),1)

    def test_new_source_each_turn_and_clear_not_refunding(self):
        self.compose(turns=2);self.ask();self.ingest(oxygen=6.1);self.ask('那溶解氧呢？')
        self.assertIn('6.1',self.posts[-1]['content']);self.assertNotIn('2.2',self.posts[-1]['content'])
        self.assertIn('untrusted_historical_transcript_v1',json.dumps(self.http[2]))
        self.assertEqual(self.receive('/清空会话')[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.host.store.counts()['turns'],0);self.assertEqual(self.receive()[0],'RUN_TURN_LIMIT')

    def test_history_ttl_does_not_restore_allowance_or_supply_old_facts(self):
        self.compose();self.ask();self.host.store._now=lambda:time.monotonic()+901
        self.assertEqual(self.receive('那溶解氧呢？')[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(len(self.http),2);self.assertEqual(self.host.ledger.report()['consumed_turns'],1)
        self.assertEqual(self.ask()['state'],'DELIVERED');self.assertEqual(len(self.http),4)

    def test_changed_source_binding_and_scope_stop_before_model(self):
        self.compose()
        value=read_json(self.root/'source.json');value['instance_id']='different'
        write_new(self.root/'source.changed.json',value);(self.root/'source.changed.json').replace(self.root/'source.json')
        self.assertEqual(self.receive()[0],'TRIAL_BINDINGS_CHANGED');self.assertEqual(self.http,[])

    def test_runtime_scope_revocation_is_sticky(self):
        self.compose()
        with patch.object(self.host,'scope_for_options',return_value={'changed':True}):
            self.assertEqual(self.receive()[0],'RUN_SCOPE_CHANGED')
        self.assertEqual(self.receive()[0],'RUN_SCOPE_CHANGED');self.assertEqual(self.http,[])

    def test_gateway_disconnect_cancels_then_only_new_message_may_run(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        self.router.disconnected();self.assertEqual(self.scheduler.wait(task,8)['state'],'CANCELLED')
        self.mode='normal';self.router.connected();self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_provider_failure_and_unknown_delivery_allow_independent_request(self):
        self.compose();self.mode='model_error';self.assertEqual(self.ask()['state'],'FAILED')
        self.mode='unknown';self.assertEqual(self.ask()['state'],'DELIVERY_UNKNOWN')
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.mode='normal';self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],3)
        self.assertEqual(len(self.http),5);self.assertEqual(len(self.posts),2)

    def test_sdk_failure_blocks_entire_typed_run(self):
        self.compose();original=self.coordinator.execute
        class Broken:
            failure='SDK_CLEANUP_FAILED'
            def snapshot(self):return dict(state='QUARANTINED',cleanup_error=self.failure,thread_exited=False,local_io_closed=False)
        def broken(plan):
            result=original(plan);plan.handle._sdk_resource=Broken();return result
        with patch.object(self.coordinator,'execute',side_effect=broken):done=self.ask()
        self.assertEqual(done['code'],'SDK_CLEANUP_FAILED');self.assertEqual(self.posts,[])
        self.assertEqual(self.host.ledger.report()['state'],'HALTED')

    def test_revoke_scope_or_binding_changes_stop_typed_tasks(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        self.coordinator.reconfigure(replace(self.host.config,enabled=False))
        self.assertEqual(self.scheduler.wait(task,8)['state'],'CANCELLED')
        self.assertEqual(self.host.ledger.report()['stop_code'],'RUN_PERMISSION_CHANGED')

    def test_checkpoint_and_ledger_failures_prevent_further_requests(self):
        self.compose()
        with patch.object(self.host.ledger,'_append',side_effect=OSError('synthetic')):
            self.assertEqual(self.receive()[0],'RUN_LEDGER_FAILED')
        self.assertEqual(self.http,[])

    def test_delivery_checkpoint_failure_keeps_api_fact_without_retry(self):
        self.compose()
        with patch('apps.qq_bot.session_run.write_new',side_effect=OSError('synthetic')):done=self.ask()
        self.assertTrue(done['api_accepted']);self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(len(self.posts),1);self.assertEqual(len(self.http),2)
        self.assertEqual(self.host.ledger.report()['stop_code'],'RUN_CHECKPOINT_FAILED')

    def run_fake(self,*,prompt=None,turns=5,fatal=False,interrupt=False):
        if not hasattr(self,'host'):self.create(turns=turns)
        case=self;gateways=[];prompts=[]
        class Socket:
            step=0;sent_turn=0
            def __init__(self):self.closed=threading.Event()
            @property
            def socket(self):return self
            def __enter__(self):return self
            def __exit__(self,*_):self.closed.set();return False
            def close(self):self.closed.set()
            def shutdown(self,*_):self.closed.set()
            def send(self,raw):pass
            def wait(self,predicate):
                end=time.monotonic()+30
                while not predicate():
                    if self.closed.wait(.005):raise OSError('synthetic closed')
                    if time.monotonic()>end:raise AssertionError('synthetic deadline')
            def recv(self,timeout):
                self.step+=1
                if self.step==1:return json.dumps({'op':10,'d':{'heartbeat_interval':300000}})
                if self.step==2:return json.dumps({'op':0,'s':0,'t':'READY','d':{'session_id':'fake-session','user':{'id':'fake-bot'},'application':{'id':APP}}})
                if self.step==3:return case.packet(text='你好').decode()
                if self.sent_turn:
                    self.wait(lambda:len(case.host.turns)>=self.sent_turn or case.started.is_set() and interrupt)
                    if interrupt:self.wait(lambda:False)
                    if fatal:
                        class Fatal(Exception):rcvd=type('Close',(),{'code':4004})()
                        raise Fatal()
                if self.sent_turn<turns:
                    self.sent_turn+=1
                    if self.sent_turn>1:case.ingest(oxygen=6.1)
                    return case.packet(text='现在水质怎么样？ PRIVATE_QQ_CANARY' if self.sent_turn==1 else '那溶解氧呢？').decode()
                gateways[0]._deadline=time.monotonic()-1;return json.dumps({'op':11})
        socket=Socket()
        def gateway(*args,**kwargs):
            value=QQGateway(*args,**kwargs);gateways.append(value);return value
        def approval(plan,stopped):prompts.append(plan);return prompt(plan,stopped) if prompt else True
        original=self.host.check;main_ident=threading.get_ident()
        def check():
            if interrupt and threading.get_ident()==main_ident and self.started.is_set():raise KeyboardInterrupt()
            return original()
        with patch('apps.qq_bot.session_run_trial_cli.QQGateway',side_effect=gateway),patch.object(self.host,'check',side_effect=check):
            result=run_session(self.host,prompt=approval,api=self.api,connector=lambda _:socket,emit=lambda *_a,**_k:None)
        self.assertFalse(any(t.is_alive() and t.name=='qq-session-trial-gateway' for t in threading.enumerate()))
        return result,prompts

    def test_complete_fake_gateway_once_prompt_five_turns_and_final_report(self):
        result,prompts=self.run_fake()
        self.assertEqual(len(prompts),1);self.assertTrue(result['completed']);self.assertTrue(result['report_saved'])
        self.assertEqual(result['verified_turns'],5);self.assertEqual(result['api_accepted_turns'],5)
        self.assertTrue(result['ram_cleared']);self.assertEqual(result['stop_reason'],'QQ_RUN_DURATION_REACHED')
        self.assertEqual(len(self.http),10);self.assertEqual(len(self.posts),6)  # greeting is free
        text=''.join(p.read_text(encoding='utf-8') for p in self.directory.iterdir() if p.is_file())
        for secret in ('PRIVATE_QQ_CANARY','member-a','group-a'):self.assertNotIn(secret,text)

    def test_ctrl_c_before_and_during_model_closes_resources_and_reports(self):
        self.mode='blocked';result,_=self.run_fake(interrupt=True)
        self.assertTrue(result['report_saved']);self.assertTrue(result['ram_cleared'])
        self.assertEqual(result['stop_reason'],'OPERATOR_INTERRUPTED');self.assertEqual(len(self.http),1)
        self.assertEqual(self.host.sessions[0].report()['sdk_resources']['state'],'CLOSED')

    def test_ctrl_c_before_approval_has_no_claim_or_network(self):
        def interrupt(*_):raise KeyboardInterrupt()
        result,_=self.run_fake(prompt=interrupt)
        self.assertTrue(result['report_saved']);self.assertEqual(self.http,[]);self.assertEqual(self.posts,[])
        self.assertFalse(result['run_approved']);self.assertFalse(result['completed'])
        self.assertFalse((self.directory/'approval.json').exists())

    def test_fatal_gateway_preserves_first_delivery_and_no_model_retry(self):
        result,_=self.run_fake(fatal=True)
        self.assertEqual(result['code'],'QQ_GATEWAY_CLOSE_4004');self.assertEqual(result['verified_turns'],1)
        self.assertTrue(result['report_saved']);self.assertEqual(len(self.http),2)

    def test_final_report_failure_is_explicit_preserving_prior_checkpoints(self):
        from apps.qq_bot.session_run_trial_cli import write_new as original
        def write(path,value):
            if Path(path).name=='result.json':raise OSError('synthetic')
            return original(path,value)
        with patch('apps.qq_bot.session_run_trial_cli.write_new',side_effect=write):result,_=self.run_fake(turns=1)
        self.assertFalse(result['report_saved']);self.assertEqual(result['code'],'RUN_REPORT_FAILED')
        self.assertTrue((self.directory/'turn-1.delivery.json').is_file());self.assertEqual(len(self.http),2)

    def test_network_close_failure_still_saves_safe_report(self):
        original=self.api.close
        def close():original();raise BotError('SYNTHETIC_CLOSE_FAILED')
        with patch.object(self.api,'close',side_effect=close):result,_=self.run_fake(turns=1)
        self.assertTrue(result['report_saved']);self.assertFalse(result['completed'])
        self.assertTrue(result['ram_cleared']);self.assertEqual(len(self.http),2)

    def test_main_requires_explicit_live_flags_before_instance_or_key_access(self):
        request=self.root/'request.json';write_new(request,self.inputs.dictionary())
        with redirect_stdout(StringIO()) as output,patch('apps.qq_bot.session_run_trial_cli.SessionTrialRun',side_effect=AssertionError('no instance')):
            self.assertEqual(main(['--run','--request-file',str(request)]),1)
        self.assertIn('SESSION_EXPLICIT_NETWORK_AND_MENTION_CONSENT_REQUIRED',output.getvalue());self.assertEqual(self.http,[])

    def test_real_preparation_record_is_distinct_and_matches_actual_code(self):
        from apps.qq_bot.conversations import ConversationOptions
        scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
        record=json.loads((ROOT/'apps/ai_service/resources/qq_session_run_trial.json').read_text())
        self.assertEqual(record,preparation_record(scope));self.assertIsNone(record['qualification_id'])
        self.assertEqual(record['status'],'candidate');self.assertNotIn('can_send',record)

    def test_powershell_session_check_reuses_explicit_request_and_is_read_only(self):
        shell=shutil.which('pwsh')
        if not shell:self.skipTest('PowerShell 7 unavailable')
        request=self.root/'request.json';write_new(request,self.inputs.dictionary());before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        result=subprocess.run([shell,'-NoProfile','-File',str(ROOT/'scripts/dev/Test-QQConversation.ps1'),
            '-Mode','Session','-Check','-RequestFile',str(request)],capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('未打开数据库',result.stdout)
        self.assertNotIn('member-a',result.stdout);self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)


class SessionWorkflowTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        self.shell=shutil.which('pwsh')
        if not self.shell:self.skipTest('PowerShell 7 unavailable')
        parent=ROOT/'outputs/test-tmp';parent.mkdir(parents=True,exist_ok=True)
        temp=TemporaryDirectory(dir=parent);self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def ps(self,code):
        return subprocess.run([self.shell,'-NoProfile','-NonInteractive','-Command',code],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=25)

    def check_report(self,changes=None,*,native=0):
        from apps.qq_bot.tests.test_test_workflow import quoted
        checked=dict(scope_sha256='a'*64,max_turns=5,total_budget_cny='8.02')
        report=dict(contract=CONTRACT,scope_sha256='a'*64,report_saved=True,ram_cleared=True,
            code='SESSION_TRIAL_STOPPED',completed=True,api_accepted_turns=1,verified_turns=1,delivery_unknown_turns=0,
            quota=dict(max_turns=5,consumed_turns=1,reserved_model_requests=2,reserved_cost_cny='1.602765'))
        report.update(changes or {})
        (self.root/'checked.json').write_text(json.dumps(checked),encoding='utf-8')
        (self.root/'result.json').write_text(json.dumps(report),encoding='utf-8')
        return self.ps(f". {quoted(ROOT/'scripts/dev/qq_bot_test_common.ps1')};"
            f"$r=Read-BotJson {quoted(self.root/'result.json')};$c=Read-BotJson {quoted(self.root/'checked.json')};"
            f"try {{ Test-BotSessionReport -Report $r -Checked $c -NativeExit {native} }} catch {{ [Console]::WriteLine($_.Exception.Message);exit 1 }}")

    def test_disk_success_is_api_acceptance_not_client_confirmation(self):
        result=self.check_report();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('SESSION_ENDED_API_ACCEPTED_CHECK_CLIENT',result.stdout)

    def test_unknown_delivery_and_no_model_are_not_verified_success(self):
        self.assertIn('SESSION_ENDED_WITH_UNKNOWN_NO_RETRY',self.check_report({'delivery_unknown_turns':1}).stdout)
        self.assertIn('SESSION_ENDED_NO_VERIFIED_AI_REPLY',self.check_report({'api_accepted_turns':0,'verified_turns':0}).stdout)

    def test_missing_report_proof_scope_mismatch_and_native_error_stop(self):
        for changes in ({'report_saved':False},{'scope_sha256':'b'*64},{'completed':False}):
            with self.subTest(changes=changes):self.assertNotEqual(self.check_report(changes).returncode,0)
        self.assertNotEqual(self.check_report(native=1).returncode,0)

    def test_budget_or_request_counter_mismatch_rejected(self):
        result=self.check_report({'quota':dict(max_turns=5,consumed_turns=6,reserved_model_requests=12,reserved_cost_cny='9.6')})
        self.assertNotEqual(result.returncode,0)

    def test_old_mode_default_remains_two_turn_and_rejects_session_expansion(self):
        from apps.qq_bot.tests.test_test_workflow import quoted
        script=quoted(ROOT/'scripts/dev/Test-QQConversation.ps1')
        result=self.ps(f'& {script} -Check -RunSeconds 1800')
        self.assertNotEqual(result.returncode,0);self.assertIn('WORKFLOW_TWO_TURN_DURATION_LIMIT',result.stdout)
        result=self.ps(f'& {script} -Check -MaxTurns 5')
        self.assertNotEqual(result.returncode,0);self.assertIn('WORKFLOW_SESSION_OPTIONS_REQUIRE_SESSION_MODE',result.stdout)

