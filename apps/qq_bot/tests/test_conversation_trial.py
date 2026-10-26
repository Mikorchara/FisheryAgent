"""Typed Qwen/QQ assembly, real SDK classes + memory HTTP; no live keys/data/network."""
import asyncio
from dataclasses import asdict,replace
from datetime import timedelta
import hashlib
import json
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock,patch

import httpx
from openai import AsyncOpenAI
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.sdk_resources import CLEANUP_GRACE_S
from apps.ai_backend.tests import test_execution as sdk_fixture
from apps.ai_service.channel_conversation_trial import CONTRACT,ConversationQwenTurn
from apps.qq_bot.ai_coordinator import QQAICoordinator
from apps.qq_bot.ai_routing import TrialQQAIRouter
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.ai_trial_delivery import ConversationQQTransport
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.contracts import BotError
from apps.qq_bot.conversation_trial import ConversationTrial,TurnApprovalFile,check_configuration
from apps.qq_bot.conversation_trial_cli import run_session,main
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.transport import QQAPI
from apps.qq_bot.trial_configuration import TrialInputs,write_new,read_json
from apps.qq_bot.tests import test_ai_coordinator as fixture

APP=fixture.APP


class ConversationTrialTests(unittest.TestCase):
    setUpFixture=fixture.QQAIServiceTests.setUp
    make=fixture.QQAIServiceTests.make
    packet=fixture.QQAIServiceTests.packet
    ingest=fixture.QQAIServiceTests.ingest

    def setUp(self):
        self.setUpFixture();sdk_fixture.ExecutionTests.setUp(self)
        self.http=[];self.posts=[];self.mode='normal';self.started=threading.Event()
        for name,value in (('access.json',{'schema_version':1,'app_id':APP,'groups':[asdict(g) for g in self.access.groups]}),
            ('ai.json',{'schema_version':1,**asdict(self.config)}),
            ('source.json',{'schema_version':1,'instance_id':'test-instance','data_root':str(self.instance),
                'devices':['sim-pond-1','sim-pond-2']})):
            write_new(self.root/name,value)
        self.inputs=TrialInputs.parse(dict(access_file=str(self.root/'access.json'),ai_config=str(self.root/'ai.json'),
            monitoring_config=str(self.root/'source.json'),policy_directory=str(self.root/'policies'),
            group_id='group-a',member_id='member-a'))
        self.directory=self.root/'trial';self.directory.mkdir()
        self.host=ConversationTrial(self.inputs,self.directory,async_client_factory=self.factory,clock=lambda:self.now)
        self.api=QQAPI(APP,Mock(side_effect=AssertionError('no real secret')),
            client=httpx.Client(transport=httpx.MockTransport(self.qq_http),trust_env=False,follow_redirects=False))
        self.api._token='fictional-only';self.api._expires=time.monotonic()+3600
        self.addCleanup(self.api.close);self.addCleanup(self.host.close)

    def factory(self,runtime,remaining):
        async def handle(request):
            body=json.loads(request.content);self.http.append(body)
            if self.mode=='blocked':self.started.set();await asyncio.Event().wait()
            if self.mode=='model_error':return httpx.Response(503,json={'error':{'message':'private fake diagnostic'}})
            tool=next((m for m in body['messages'] if m['role']=='tool'),None)
            if tool is None:
                message={'role':'assistant','content':None,'tool_calls':[{'id':'fake-call','type':'function',
                    'function':{'name':'get_current_water_quality','arguments':'{}'}}]}
            else:
                payload=json.loads(tool['content']);q=payload['data_quality']
                hits=[f['code'] for f in payload['findings'] if f['kind']=='WATER_RISK' and f['state']=='HIT']
                message={'role':'assistant','content':json.dumps({'contract':'qq-water-explanation@1',
                    'source':'simulator','context':'window' if (q['quality'],q['freshness'],q['connectivity'])==('valid','fresh','online') else 'limited',
                    'metrics':['dissolved_oxygen_mg_l'],'rules':hits,'advice':['verify_observation']})}
            return httpx.Response(200,json={'id':'fake-response','object':'chat.completion','created':0,'model':runtime.model,
                'choices':[{'index':0,'message':message,'finish_reason':'stop' if tool else 'tool_calls'}],
                'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
        return AsyncOpenAI(api_key='fictional-only',base_url=runtime.base_url,max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle),trust_env=False,follow_redirects=False))

    def qq_http(self,request):
        if request.url.path=='/gateway':return httpx.Response(200,json={'url':'wss://api.bot.qq.com/websocket/'})
        self.posts.append(json.loads(request.content))
        if self.mode=='unknown':raise httpx.ReadTimeout('fake unknown',request=request)
        if self.mode=='send_failed':return httpx.Response(503,json={'code':1})
        return httpx.Response(200,json={'id':'fake-accepted'})

    def compose(self):
        self.coordinator=QQAICoordinator(self.host.access,self.host.monitoring,self.host.base_service,
            config=self.host.config,conversations=self.host.store,conversation_trial=self.host,clock=lambda:self.now)
        transport=ConversationQQTransport(self.api,self.host);transport.reconnect()
        self.scheduler=QQAIJobScheduler(self.coordinator,transport,clock=lambda:self.now,receipt_sink=self.host.checkpoint)
        adapter=QQAdapter(self.host.access,ReadOnlyQueries(self.host.monitoring,None),mode='QQ_PASSIVE_READY',clock=lambda:self.now)
        self.router=TrialQQAIRouter(adapter,self.scheduler)
        self.gateway=QQGateway(APP,self.api,adapter,trial_router=self.router,clock=lambda:self.now,connector=lambda _:None,emit=lambda *_a,**_k:None)
        def close():
            try:self.router.close()
            except BotError as e:
                if e.code!='AI_SDK_RESOURCE_UNSAFE':raise
            self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))
        self.addCleanup(close)

    def approve(self):
        plan=self.host.plan();self.host.approve(plan,self.directory/f"turn-{plan['turn']}.approval.json");return plan

    def receive(self,text='现在水质怎么样？',**kwargs):
        self.gateway._dispatch_authenticated(json.loads(self.packet(text=text,**kwargs)))
        raw,_,proof=self.gateway._queue.get_nowait();self.gateway._queue.task_done()
        return self.router.receive(raw,transport_app_id=APP,mention=proof)

    def ask(self,text='现在水质怎么样？'):
        code,task=self.receive(text);self.assertEqual(code,'AI_ADMITTED')
        return self.scheduler.wait(task,90+CLEANUP_GRACE_S+3)

    def test_two_separate_approvals_services_and_receipts_share_only_safe_history(self):
        self.compose();first=self.approve()
        with patch.object(self.host.monitoring,'capture_water',wraps=self.host.monitoring.capture_water) as read:
            self.assertEqual(self.ask()['history_code'],'HISTORY_COMMITTED')
            self.assertEqual(self.receive('那溶解氧呢？')[0],'CONVERSATION_TURN_NOT_APPROVED')
            self.ingest(oxygen=6.1);second=self.approve()
            self.assertEqual(second['state']['turns'],1);self.assertNotEqual(first['state'],second['state'])
            self.assertEqual(self.ask('那溶解氧呢？')['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(read.call_count,2);self.assertEqual(len(self.http),4);self.assertEqual(len(self.posts),2)
        self.assertIn('溶解氧：6.1',self.posts[-1]['content']);self.assertNotIn('溶解氧：2.2',self.posts[-1]['content'])
        self.assertIn('untrusted_historical_transcript_v1',json.dumps(self.http[2]['messages']))
        self.assertNotIn('2.2',json.dumps(self.http[2]['messages']))
        self.assertEqual([s.requests for s in self.host.sessions],[2,2])
        self.assertIsNot(self.host.sessions[0].handle,self.host.sessions[1].handle)
        self.assertIsNone(self.host.base_service._channel_trial)
        self.assertEqual(len(list(self.root.glob('.qwen-conversation-*.used'))),2)
        with self.assertRaisesRegex(BotError,'CONVERSATION_TURN_LIMIT'):self.host.plan()

    def test_greeting_help_clear_are_free_and_fake_mention_cannot_run(self):
        self.compose()
        for text in ('你好','你能做什么？','/帮助','/清空会话'):
            self.assertEqual(self.receive(text)[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.http,[])
        self.assertEqual(self.router.receive(self.packet(text='当前水质如何？'),transport_app_id=APP)[0],'AI_AUTHENTICATED_MENTION_REQUIRED')

    def test_unknown_member_and_group_have_no_model_or_reply(self):
        self.compose();self.approve()
        for options in ({'member':'intruder'},{'group':'group-b','member':'member-b'}):
            self.assertIn(self.receive(**options)[0],('GROUP_DENIED','MEMBER_DENIED'))
        self.assertEqual(self.http,[]);self.assertEqual(self.posts,[])

    def test_second_plan_cannot_be_created_before_first_delivery(self):
        self.compose();self.approve()
        with self.assertRaisesRegex(BotError,'CONVERSATION_TURN_PENDING'):self.host.plan()

    def test_unapproved_request_cannot_even_issue_a_history_snapshot(self):
        self.compose()
        with patch.object(self.host.store,'snapshot',wraps=self.host.store.snapshot) as snapshot:
            self.assertEqual(self.receive()[0],'CONVERSATION_TURN_NOT_APPROVED')
        snapshot.assert_not_called();self.assertEqual(self.http,[])

    def test_returned_plan_mutation_cannot_change_the_pending_permission(self):
        self.compose();plan=self.host.plan();plan['state']['turns']=99
        with self.assertRaisesRegex(BotError,'CONVERSATION_APPROVAL_STATE_CHANGED'):
            self.host.approve(plan,self.directory/'invalid.approval.json')
        self.assertFalse((self.directory/'invalid.approval.json').exists())

    def test_expired_approval_and_cleared_revision_are_refused_before_io(self):
        self.compose();self.approve();self.now+=timedelta(seconds=301)
        self.assertNotEqual(self.receive()[0],'AI_ADMITTED');self.assertEqual(self.http,[])

    def test_clear_after_approval_prevents_using_the_old_state(self):
        self.compose();self.approve();self.receive('/清空会话')
        self.assertEqual(self.receive()[0],'CONVERSATION_APPROVAL_STATE_CHANGED');self.assertEqual(self.http,[])

    def test_copied_consumed_approval_cannot_be_reused(self):
        self.compose();plan=self.approve();self.ask()
        with self.assertRaisesRegex(BotError,'TRIAL_ALREADY_USED'):
            TurnApprovalFile(self.host,self.directory/'turn-1.approval.json',plan)

    def test_unused_approval_cannot_be_loaded_by_a_different_process_identity(self):
        self.compose();plan=self.approve();directory=self.root/'other';directory.mkdir()
        other=ConversationTrial(self.inputs,directory,async_client_factory=self.factory,clock=lambda:self.now)
        try:
            with self.assertRaisesRegex(BotError,'CONVERSATION_APPROVAL_RUN_MISMATCH'):
                TurnApprovalFile(other,self.directory/'turn-1.approval.json',plan)
        finally:other.close()
        self.assertEqual(self.http,[])

    def test_delivery_unknown_has_no_history_or_second_permit(self):
        self.compose();self.approve();self.mode='unknown';done=self.ask()
        self.assertEqual(done['state'],'DELIVERY_UNKNOWN');self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertFalse(self.host.turns[0]['verified'])
        with self.assertRaisesRegex(BotError,'CONVERSATION_TURN_FAILED_STOP'):self.host.plan()
        self.assertEqual(len(self.http),2);self.assertEqual(len(self.posts),1)

    def test_check_does_not_open_instance_credentials_or_network(self):
        with (patch('apps.qq_bot.conversation_trial.InstanceMonitoring',side_effect=AssertionError('no DB')),
             patch('apps.qq_bot.conversation_trial.project_credentials',side_effect=AssertionError('no key'))):
            result=check_configuration(self.inputs)
        self.assertEqual(result['network_requests'],0);self.assertFalse(result['business_instance_opened'])

    def test_approval_expiry_is_separate_from_run_expiry(self):
        self.compose();self.host.minutes=1;self.approve();self.now+=timedelta(seconds=61)
        self.assertEqual(self.receive()[0],'TRIAL_APPROVAL_EXPIRED');self.assertEqual(self.http,[])

    def test_approval_bytes_or_scope_changes_reject_before_provider(self):
        self.compose();self.approve()
        path=self.directory/'turn-1.approval.json';value=read_json(path);value['max_cost_cny']='3.00'
        path.write_text(json.dumps(value),encoding='utf-8')  # Synthetic record only.
        self.assertEqual(self.receive()[0],'TRIAL_APPROVAL_CHANGED');self.assertEqual(self.http,[])

    def test_scope_change_rejects_greeting_and_model_without_old_memory(self):
        self.compose();self.approve()
        with patch('apps.qq_bot.conversation_trial.prepared_scope',return_value={'different':'scope'}):
            self.assertEqual(self.receive()[0],'TRIAL_SCOPE_CHANGED')
        self.assertEqual(self.http,[])

    def test_pending_second_plan_is_bound_to_the_actual_revision(self):
        self.compose();self.approve();self.ask();plan=self.host.plan()
        self.receive('/清空会话')
        with self.assertRaisesRegex(BotError,'CONVERSATION_APPROVAL_STATE_CHANGED'):
            self.host.approve(plan,self.directory/'turn-2.approval.json')
        self.assertFalse((self.directory/'turn-2.approval.json').exists());self.assertEqual(len(self.http),2)

    def test_authorization_revocation_cancels_owned_sdk_io(self):
        self.compose();self.approve();self.mode='blocked'
        _,task=self.receive();self.assertTrue(self.started.wait(5))
        self.coordinator.reconfigure(replace(self.host.config,enabled=False))
        result=self.scheduler.wait(task,10)
        self.assertIn(result['state'],('CANCELLED','FAILED'));self.assertEqual(len(self.http),1)
        self.assertFalse(self.host.turns[0]['verified']);self.assertEqual(self.posts,[])
        resources=self.host.sessions[0].handle.resource_info()
        self.assertTrue(resources['thread_exited']);self.assertTrue(resources['local_io_closed'])

    def test_running_timeout_and_disconnect_do_not_commit(self):
        self.compose();self.approve();self.mode='blocked'
        _,task=self.receive();self.assertTrue(self.started.wait(5))
        self.scheduler.cancel(task,reason='AI_TOTAL_TIMEOUT')
        self.assertEqual(self.scheduler.wait(task,10)['state'],'EXPIRED')
        self.assertEqual(self.host.store.counts()['turns'],0);self.assertEqual(len(self.http),1)

    def test_binding_or_configuration_change_invalidates_approved_turn(self):
        self.compose();self.approve()
        value=json.loads((self.root/'source.json').read_text(encoding='utf-8'));value['instance_id']='changed-instance'
        (self.root/'source.json').write_text(json.dumps(value),encoding='utf-8')
        self.assertEqual(self.receive()[0],'TRIAL_BINDINGS_CHANGED');self.assertEqual(self.http,[])

    def test_source_database_is_not_written_by_approved_query(self):
        self.compose();self.approve();before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.ask();self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)

    def test_delivery_checkpoint_failure_never_retries_or_authorizes_second_turn(self):
        self.compose();self.approve()
        with patch.object(self.host,'checkpoint',side_effect=OSError('private disk failure')):
            self.scheduler.delivery.receipt_sink=self.host.checkpoint;done=self.ask()
        self.assertTrue(done['api_accepted']);self.assertEqual(len(self.posts),1)
        self.assertFalse(self.host.turns[0]['verified']);self.assertEqual(len(self.http),2)
        with self.assertRaises(BotError):self.host.plan()

    def test_sdk_resource_failure_quarantines_scheduler_and_prevents_second_turn(self):
        self.compose();self.approve();original=self.coordinator.execute
        class Broken:
            failure='SDK_CLEANUP_FAILED'
            def snapshot(self):return dict(state='QUARANTINED',cleanup_error=self.failure,thread_exited=False,local_io_closed=False)
        def broken(plan):
            result=original(plan);plan.handle._sdk_resource=Broken();return result
        with patch.object(self.coordinator,'execute',side_effect=broken):done=self.ask()
        self.assertEqual(done['state'],'FAILED');self.assertEqual(done['code'],'SDK_CLEANUP_FAILED')
        self.assertFalse(self.host.turns[0]['verified']);self.assertEqual(self.posts,[])
        with self.assertRaises(BotError):self.host.plan()

    def test_revoke_after_api_acceptance_does_not_commit_history(self):
        self.compose();self.approve();original=self.coordinator.accept_delivery
        def revoke(*args):
            self.coordinator.reconfigure(replace(self.host.config,enabled=False));return original(*args)
        with patch.object(self.coordinator,'accept_delivery',side_effect=revoke):done=self.ask()
        self.assertTrue(done['api_accepted']);self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertFalse(self.host.turns[0]['verified']);self.assertEqual(len(self.posts),1)

    def run_fake(self,*,prompt=None,fatal=False):
        case=self;gateways=[];prompts=[];heartbeat=threading.Event()
        class Socket:
            step=0
            def __init__(self):self.closed=threading.Event();self.sent=[]
            @property
            def socket(self):return self
            def __enter__(self):return self
            def __exit__(self,*args):self.closed.set();return False
            def shutdown(self,*args):self.closed.set()
            def close(self):self.closed.set()
            def send(self,raw):
                value=json.loads(raw);self.sent.append(value)
                if value['op']==1:heartbeat.set()
            def wait(self,predicate):
                end=time.monotonic()+20
                while not predicate():
                    if self.closed.wait(.005):raise OSError('fake closed')
                    if time.monotonic()>end:raise AssertionError('fake phase timeout')
            def recv(self,timeout):
                self.step+=1
                if self.step==1:return json.dumps({'op':10,'d':{'heartbeat_interval':300000}})
                if self.step==2:return json.dumps({'op':0,'s':0,'t':'READY','d':{'session_id':'fake-session',
                    'user':{'id':'fake-bot'},'application':{'id':APP}}})
                if self.step==3:return case.packet(text='现在水质怎么样？ PRIVATE_QQ_CANARY').decode()
                if self.step==4:
                    self.wait(lambda:len(case.host.turns)==1)
                    if fatal:
                        class Fatal(Exception):rcvd=type('Close',(),{'code':4004})()
                        raise Fatal()
                    return json.dumps({'op':1})  # Heartbeat during second local approval.
                if self.step==5:
                    self.wait(lambda:case.host._ready is not None)
                    case.ingest(oxygen=6.1);return case.packet(text='那溶解氧呢？').decode()
                self.wait(lambda:len(case.host.turns)==2)
                gateways[0]._deadline=time.monotonic()-1
                return json.dumps({'op':11})
        socket=Socket()
        def gateway(*args,**kwargs):
            result=QQGateway(*args,**kwargs);gateways.append(result);return result
        def approve(plan,stopped):
            prompts.append(plan)
            if plan['turn']==2:self.assertTrue(heartbeat.wait(5))
            return prompt(plan,stopped) if prompt else True
        with patch('apps.qq_bot.conversation_trial_cli.QQGateway',side_effect=gateway):
            result=run_session(self.host,prompt=approve,api=self.api,connector=lambda _:socket,emit=lambda *_a,**_k:None)
        self.assertTrue(all(not t.is_alive() for t in self.host.coordinator._scheduler._threads)
            if self.host.coordinator._scheduler else True)
        if gateways and gateways[0]._worker:self.assertFalse(gateways[0]._worker.is_alive())
        self.assertFalse(any(t.name=='qq-conversation-gateway' and t.is_alive() for t in threading.enumerate()))
        return result,prompts

    def test_fake_gateway_two_turns_console_approval_and_final_reports(self):
        result,plans=self.run_fake()
        self.assertTrue(result['completed']);self.assertTrue(result['ram_cleared']);self.assertTrue(result['report_saved'])
        self.assertEqual(result['stop_reason'],'QQ_RUN_DURATION_REACHED')
        self.assertEqual([p['state']['turns'] for p in plans],[0,1]);self.assertEqual(len(self.http),4)
        self.assertEqual([t['model_requests'] for t in result['turns']],[2,2])
        self.assertTrue(all(t['verified'] for t in result['turns']))
        for name in ('result.json','turn-1.delivery.json','turn-2.delivery.json','turn-1.result.json','turn-2.result.json'):
            self.assertTrue((self.directory/name).is_file())
        text=''.join(p.read_text(encoding='utf-8') for p in self.directory.iterdir() if p.is_file())
        for private in ('PRIVATE_QQ_CANARY','member-a','group-a'):self.assertNotIn(private,text)

    def test_operator_declines_first_turn_without_gateway_or_provider(self):
        result,_=self.run_fake(prompt=lambda *_:False)
        self.assertEqual(result['code'],'CONVERSATION_OPERATOR_CANCELLED')
        self.assertEqual(self.http,[]);self.assertEqual(self.posts,[]);self.assertTrue(result['report_saved'])

    def test_operator_declines_second_turn_preserves_first_accepted_receipt(self):
        result,_=self.run_fake(prompt=lambda plan,_:plan['turn']==1)
        self.assertEqual(result['code'],'CONVERSATION_OPERATOR_CANCELLED')
        self.assertEqual(len(result['turns']),1);self.assertTrue(result['turns'][0]['verified'])
        self.assertEqual(len(self.http),2);self.assertEqual(len(self.posts),1)

    def test_ctrl_c_before_connect_saves_report_and_closes_workers(self):
        def interrupt(*_):raise KeyboardInterrupt()
        result,_=self.run_fake(prompt=interrupt)
        self.assertEqual(result['code'],'CONVERSATION_OPERATOR_CANCELLED');self.assertTrue(result['ram_cleared'])
        self.assertTrue(result['report_saved']);self.assertEqual(self.http,[])

    def test_gateway_failure_saves_existing_delivery_without_retrying_model(self):
        result,_=self.run_fake(fatal=True)
        self.assertEqual(result['code'],'QQ_GATEWAY_CLOSE_4004')
        self.assertEqual(len(self.http),2);self.assertEqual(len(self.posts),1)
        self.assertTrue(result['turns'][0]['verified']);self.assertTrue(result['report_saved'])

    def test_final_report_write_failure_preserves_used_permits_and_checkpoints(self):
        from apps.qq_bot.conversation_trial_cli import write_new as original
        def write(path,value):
            if Path(path).name=='result.json':raise OSError('private disk issue')
            return original(path,value)
        with patch('apps.qq_bot.conversation_trial_cli.write_new',side_effect=write):result,_=self.run_fake()
        self.assertEqual(result['code'],'CONVERSATION_RESULT_WRITE_FAILED');self.assertFalse(result['report_saved'])
        self.assertEqual(len(self.http),4);self.assertEqual(len(list(self.root.glob('.qwen-conversation-*.used'))),2)
        self.assertTrue((self.directory/'turn-2.delivery.json').is_file())

    def test_cli_requires_all_explicit_live_consents(self):
        path=self.root/'request.json';write_new(path,self.inputs.dictionary())
        with redirect_stdout(StringIO()) as out:
            result=main(['--run','--request-file',str(path)])
        self.assertEqual(result,1);self.assertIn('CONVERSATION_EXPLICIT_NETWORK_AND_MENTION_CONSENT_REQUIRED',out.getvalue())
        self.assertEqual(self.http,[])

    def test_powershell_check_uses_only_config_and_contract(self):
        shell=shutil.which('pwsh')
        if shell is None:self.skipTest('PowerShell 7 unavailable')
        path=self.root/'request.json';write_new(path,self.inputs.dictionary())
        script=Path(__file__).resolve().parents[3]/'scripts/dev/Test-QQConversation.ps1'
        result=subprocess.run([shell,'-NoProfile','-File',str(script),'-Check','-RequestFile',str(path)],
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout[-1000:]+result.stderr[-1000:])
        self.assertIn('未打开数据库',result.stdout)


if __name__=='__main__':unittest.main()
