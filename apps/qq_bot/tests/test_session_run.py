"""Real SDK + memory HTTP, synthetic Monitoring and authenticated Fake Gateway."""
from dataclasses import asdict,replace
from datetime import timedelta
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import patch

from apps.ai_backend.tests import test_execution as sdk_fixture
from apps.ai_service.channel_session_run import SessionQwenTurn,prepared_scope,candidate_record
from apps.ai_service.runtime.release_contracts import _hash
from apps.qq_bot.ai_coordinator import QQAICoordinator
from apps.qq_bot.ai_delivery import OfflineQQGateway
from apps.qq_bot.ai_routing import OfflineQQAIRouter,OfflineGatewayAPI
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.contracts import BotError
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.run_consent import RunLimits
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.session_run import SessionRun
from apps.qq_bot.session_run_cli import main
from apps.qq_bot.trial_configuration import TrialInputs,write_new,read_json
from apps.qq_bot.tests import test_ai_coordinator as fixture
from apps.qq_bot.tests import test_conversation_trial as trial_fixture

APP=fixture.APP


class SessionRunTests(unittest.TestCase):
    packet=fixture.QQAIServiceTests.packet
    ingest=fixture.QQAIServiceTests.ingest
    make=fixture.QQAIServiceTests.make
    factory=trial_fixture.ConversationTrialTests.factory

    def setUp(self):
        fixture.QQAIServiceTests.setUp(self);sdk_fixture.ExecutionTests.setUp(self)
        self.http=[];self.mode='normal';self.started=threading.Event()
        self.members=('member-a','member-b','member-c','member-d')
        self.access=replace(self.access,groups=(replace(self.access.groups[0],members=self.members),self.access.groups[1]))
        self.config=replace(self.config,grants=(replace(self.config.grants[0],members=self.members),self.config.grants[1]))
        for name,value in (('access.json',{'schema_version':1,'app_id':APP,'groups':[asdict(g) for g in self.access.groups]}),
            ('ai.json',{'schema_version':1,**asdict(self.config)}),
            ('source.json',{'schema_version':1,'instance_id':'test-instance','data_root':str(self.instance),
                'devices':['sim-pond-1','sim-pond-2']})):
            write_new(self.root/name,value)
        self.inputs=TrialInputs.parse(dict(access_file=str(self.root/'access.json'),ai_config=str(self.root/'ai.json'),
            monitoring_config=str(self.root/'source.json'),policy_directory=str(self.root/'policies'),
            group_id='group-a',member_id='member-a'))

    def compose(self,*,turns=5,members=None,outcomes=None,approve=True):
        directory=self.root/'run';directory.mkdir()
        self.host=SessionRun(self.inputs,directory,async_client_factory=self.factory,
            limits=RunLimits(max_turns=turns),members=members,clock=lambda:self.now)
        self.addCleanup(self.host.close)
        self.coordinator=QQAICoordinator(self.host.access,self.host.monitoring,self.host.base_service,
            config=self.host.config,conversations=self.host.store,session_run=self.host,clock=lambda:self.now)
        if approve:self.host.approve(self.host.plan(),confirmed=True)
        self.delivery=OfflineQQGateway(outcomes or ('ACCEPTED',)*30)
        self.scheduler=QQAIJobScheduler(self.coordinator,self.delivery,clock=lambda:self.now)
        adapter=QQAdapter(self.host.access,ReadOnlyQueries(self.host.monitoring,None),mode='QQ_PASSIVE_READY',clock=lambda:self.now)
        self.router=OfflineQQAIRouter(adapter,self.scheduler)
        self.gateway=QQGateway(APP,OfflineGatewayAPI(APP),adapter,offline_router=self.router,
            connector=lambda _:None,clock=lambda:self.now,emit=lambda *_a,**_k:None)
        def close():
            try:self.router.close()
            except BotError as error:
                if error.code!='AI_SDK_RESOURCE_UNSAFE':raise
            self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))
        self.addCleanup(close)

    def receive(self,text='现在水质怎么样？',**kwargs):
        self.gateway._dispatch_authenticated(json.loads(self.packet(text=text,**kwargs)))
        raw,_,proof=self.gateway._queue.get_nowait();self.gateway._queue.task_done()
        return self.router.receive(raw,transport_app_id=APP,mention=proof)

    def ask(self,text='现在水质怎么样？',**kwargs):
        code,task=self.receive(text,**kwargs);self.assertEqual(code,'AI_ADMITTED')
        return self.scheduler.wait(task,95)

    def test_once_approved_five_turns_independent_services_and_fresh_tool(self):
        self.compose();before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch.object(self.host.monitoring,'capture_water',wraps=self.host.monitoring.capture_water) as read:
            for i in range(5):
                done=self.ask('现在水质怎么样？' if i==0 else '那溶解氧呢？')
                self.assertEqual(done['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(read.call_count,5);self.assertEqual(len(self.http),10)
        self.assertEqual(len({id(s.handle) for s in self.host.sessions}),5)
        self.assertTrue(all(type(s) is SessionQwenTurn for s in self.host.sessions))
        self.assertTrue(all(t['verified'] for t in self.host.turns))
        self.assertEqual(self.host.ledger.report()['reserved_cost_cny'],'8.013825')
        self.assertEqual(self.receive()[0],'RUN_TURN_LIMIT')
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),before)
        self.assertEqual(self.host.store.counts()['turns'],5)

    def test_each_turn_requeries_and_history_never_supplies_old_values(self):
        self.compose();self.ask();self.ingest(oxygen=6.1);self.ask('那溶解氧呢？')
        self.assertIn('6.1',self.delivery.posts[-1]['content'])
        self.assertNotIn('2.2',self.delivery.posts[-1]['content'])
        self.assertIn('untrusted_historical_transcript_v1',json.dumps(self.http[2]))
        self.assertNotIn('2.2',json.dumps(self.http[2]))

    def test_free_templates_fixed_commands_clear_and_fake_mention(self):
        self.compose()
        for text in ('你好','你能做什么？','/帮助','/当前水质','/清空会话'):
            self.assertEqual(self.receive(text)[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.http,[]);self.assertEqual(self.host.ledger.report()['consumed_turns'],0)
        self.assertEqual(self.router.receive(self.packet(text='当前水质如何？'),transport_app_id=APP)[0],
            'AI_AUTHENTICATED_MENTION_REQUIRED')

    def test_disabled_until_local_approval(self):
        self.compose(approve=False)
        self.assertEqual(self.receive()[0],'RUN_NOT_APPROVED');self.assertEqual(self.http,[])

    def test_nonselected_and_cross_group_are_denied_without_consumption(self):
        self.compose()
        for kwargs in ({'member':'member-b'},{'member':'intruder'},{'member':'member-b','group':'group-b'}):
            self.assertIn(self.receive(**kwargs)[0],('GROUP_DENIED','MEMBER_DENIED'))
        self.assertEqual(self.host.ledger.report()['consumed_turns'],0);self.assertEqual(self.http,[])

    def test_explicit_selection_not_beyond_existing_access_and_ai_grants(self):
        directory=self.root/'bad';directory.mkdir()
        for selected in (('intruder',),('member-a',)*2,tuple('abcde')):
            with self.assertRaisesRegex(BotError,'RUN_MEMBERS_NOT_APPROVED'):
                SessionRun(self.inputs,directory,async_client_factory=self.factory,members=selected,clock=lambda:self.now)

    def test_busy_and_singleflight_do_not_consume(self):
        self.compose(members=self.members);self.mode='blocked'
        first=self.receive();self.assertEqual(first[0],'AI_ADMITTED');self.assertTrue(self.started.wait(3))
        self.assertEqual(self.receive()[0],'QQ_REPLY_API_ACCEPTED')  # same session busy template
        self.assertEqual(self.host.ledger.report()['consumed_turns'],1)
        for member in self.members[1:3]:self.assertEqual(self.receive(member=member)[0],'AI_ADMITTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],3)
        self.assertEqual(self.receive(member=self.members[3])[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],3)

    def test_duplicate_message_after_ingress_cache_expiry_does_not_consume(self):
        self.compose();raw=self.packet();self.gateway._dispatch_authenticated(json.loads(raw))
        packet,_,proof=self.gateway._queue.get_nowait();self.gateway._queue.task_done()
        code,task=self.router.receive(packet,transport_app_id=APP,mention=proof)
        self.assertEqual(code,'AI_ADMITTED');self.scheduler.wait(task,95)
        # Clear short ingress dedup only; whole-Run ledger still owns the message.
        self.router._ingress._seen.clear();self.coordinator._ingress._seen.clear()
        code,_=self.router.receive(packet,transport_app_id=APP,mention=proof)
        self.assertEqual(code,'RUN_MESSAGE_ALREADY_USED');self.assertEqual(len(self.http),2)
        self.assertEqual(self.host.ledger.report()['consumed_turns'],1)

    def test_two_members_isolated_memory_shared_quota(self):
        self.compose(turns=2,members=self.members[:2]);self.ask();self.ask(member='member-b')
        self.assertEqual(self.host.store.counts()['turns'],2)
        transcript=[m for m in self.http[2]['messages'] if 'untrusted_historical_transcript_v1' in str(m)]
        self.assertTrue(all('已交付答复的主题投影' not in str(m) for m in transcript))
        self.assertEqual(self.receive(member='member-b')[0],'RUN_TURN_LIMIT')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_clear_history_does_not_refund_and_new_turn_uses_empty_history(self):
        self.compose(turns=2);self.ask();self.receive('/清空会话');self.ask()
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)
        self.assertEqual(self.host.store.counts()['turns'],1)
        self.assertEqual(self.receive()[0],'RUN_TURN_LIMIT')

    def test_ordinary_model_failure_closed_resources_allows_new_independent_message(self):
        self.compose();self.mode='model_error';done=self.ask()
        self.assertEqual(done['state'],'FAILED');self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(self.host.turns[0]['sdk_resources']['state'],'CLOSED')
        self.mode='normal';self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)
        self.assertEqual(len(self.http),3)

    def test_unknown_delivery_consumes_no_history_no_retry_next_message_allowed(self):
        self.compose(outcomes=('UNKNOWN','ACCEPTED'))
        self.assertEqual(self.ask()['state'],'DELIVERY_UNKNOWN')
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(len(self.http),4);self.assertEqual(len(self.delivery.posts),2)
        self.assertEqual(self.host.store.counts()['turns'],1)

    def test_last_reserved_turn_completes_and_no_extra_model_request(self):
        self.compose(turns=1);self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.receive()[0],'RUN_TURN_LIMIT');self.assertEqual(len(self.http),2)

    def test_permission_change_is_sticky_and_cancels_inflight(self):
        self.compose();self.mode='blocked';code,task=self.receive();self.assertTrue(self.started.wait(3))
        self.coordinator.reconfigure(replace(self.host.config,enabled=False))
        self.assertEqual(self.scheduler.wait(task,8)['state'],'CANCELLED')
        self.coordinator.reconfigure(self.host.config)
        self.assertEqual(self.receive()[0],'RUN_PERMISSION_CHANGED')

    def test_bindings_and_scope_changes_are_sticky(self):
        self.compose()
        value=read_json(self.root/'source.json');value['instance_id']='other'
        write_new(self.root/'source.changed.json',value)
        (self.root/'source.changed.json').replace(self.root/'source.json')  # Only this new synthetic fixture.
        self.assertEqual(self.receive()[0],'TRIAL_BINDINGS_CHANGED')
        self.assertEqual(self.http,[])

    def test_scope_change_revokes_even_after_reverting_file(self):
        self.compose()
        with patch('apps.qq_bot.session_run.prepared_scope',return_value={'changed':True}):
            self.assertEqual(self.receive()[0],'RUN_SCOPE_CHANGED')
        self.assertEqual(self.receive()[0],'RUN_SCOPE_CHANGED');self.assertEqual(self.http,[])

    def test_changed_actual_tool_definition_cannot_use_prepared_scope(self):
        from apps.ai_service import service as services
        from apps.ai_backend.tools import ToolDefinition,ToolRegistry
        original=services.bind_tools
        self.compose()
        def changed(*args,**kwargs):
            registry=original(*args,**kwargs)
            return ToolRegistry(tuple(ToolDefinition(replace(d,description='different tool contract'),
                registry.lookup(d.name).handler) for d in registry.model_definitions()))
        with patch.object(services,'bind_tools',side_effect=changed):
            code,_=self.receive()
        self.assertEqual(code,'SESSION_RUN_BINDING_CHANGED');self.assertEqual(self.http,[])

    def test_ledger_write_failure_blocks_model_and_future_admissions(self):
        self.compose()
        with patch.object(self.host.ledger,'_append',side_effect=OSError('synthetic')):
            self.assertEqual(self.receive()[0],'RUN_LEDGER_FAILED')
        self.assertEqual(self.receive()[0],'RUN_LEDGER_FAILED');self.assertEqual(self.http,[])

    def test_delivery_checkpoint_failure_preserves_acceptance_and_halts(self):
        self.compose()
        with patch('apps.qq_bot.session_run.write_new',side_effect=OSError('synthetic')):done=self.ask()
        self.assertTrue(done['api_accepted']);self.assertIn('report_error',done)
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(self.receive()[0],'RUN_CHECKPOINT_FAILED')
        self.assertEqual(len(self.delivery.posts),1)

    def test_sdk_resource_fault_stops_run_and_new_request(self):
        self.compose();original=self.coordinator.execute
        class Broken:
            failure='SDK_CLEANUP_FAILED'
            def snapshot(self):return dict(state='QUARANTINED',cleanup_error=self.failure,thread_exited=False,local_io_closed=False)
        def broken(plan):
            result=original(plan);plan.handle._sdk_resource=Broken();return result
        with patch.object(self.coordinator,'execute',side_effect=broken):done=self.ask()
        self.assertEqual(done['state'],'FAILED');self.assertEqual(done['code'],'SDK_CLEANUP_FAILED')
        self.assertEqual(self.host.ledger.report()['state'],'HALTED')
        self.assertEqual(self.delivery.posts.__len__(),0)

    def test_gateway_disconnect_cancel_and_reconnect_new_message_only(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        self.router.disconnected();done=self.scheduler.wait(task,8)
        self.assertEqual(done['state'],'CANCELLED');self.assertEqual(self.host.store.counts()['turns'],0)
        self.mode='normal';self.router.connected();self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_total_timeout_closed_resources_allows_next_independent_message(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        self.scheduler.cancel(task,reason='AI_TOTAL_TIMEOUT');done=self.scheduler.wait(task,8)
        self.assertEqual(done['state'],'EXPIRED')
        self.assertEqual(self.host.turns[0]['sdk_resources']['state'],'CLOSED')
        self.mode='normal';self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_queued_expiry_consumes_and_does_not_start_sdk(self):
        self.compose(members=self.members);self.mode='blocked'
        _,first=self.receive();self.assertTrue(self.started.wait(3))
        _,queued=self.receive(member='member-b')
        with self.scheduler._cv:self.scheduler._jobs[queued].queue_deadline=time.monotonic()-1
        done=self.scheduler.wait(queued,8);self.assertEqual(done['state'],'EXPIRED')
        self.assertEqual(len(self.http),1);self.assertEqual(self.host.sessions[1].requests,0)
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_owner_loss_halts_and_cancels_without_new_model(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        with patch.object(self.host.ledger._owner,'check',side_effect=BotError('RUN_OWNER_LOST')):
            done=self.scheduler.wait(task,8)
        self.assertIn(done['state'],('CANCELLED','FAILED'))
        self.assertEqual(self.host.ledger.report()['stop_code'],'RUN_OWNER_LOST')
        self.assertEqual(self.receive()[0],'RUN_OWNER_LOST');self.assertEqual(len(self.http),1)

    def test_clear_inflight_history_does_not_poison_other_member_or_refund(self):
        self.compose(members=self.members[:2]);self.mode='blocked'
        _,task=self.receive();self.assertTrue(self.started.wait(3))
        self.assertEqual(self.receive('/清空会话')[0],'QQ_REPLY_API_ACCEPTED')
        self.scheduler.wait(task,8);self.mode='normal'
        self.assertEqual(self.ask(member='member-b')['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_expiry_cancels_without_any_new_message(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        self.now+=timedelta(minutes=31)
        self.assertEqual(self.scheduler.wait(task,8)['state'],'CANCELLED')
        self.assertEqual(self.host.ledger.report()['stop_code'],'RUN_EXPIRED')

    def test_stop_closes_resources_writes_final_report_clears_ram(self):
        self.compose();self.ask();report=self.host.stop(self.scheduler)
        self.assertTrue(report['ram_cleared']);self.assertTrue((self.host.directory/'result.json').is_file())
        self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))
        self.assertTrue(all(s.report()['sdk_resources']['state']=='CLOSED' for s in self.host.sessions))

    def test_lifecycle_expiry_writes_report_and_joins_without_new_messages(self):
        self.compose();reports=[]
        controller=threading.Thread(target=lambda:reports.append(self.host.run_until_stopped(self.scheduler)))
        controller.start()
        try:
            self.now+=timedelta(minutes=31);controller.join(8)
            self.assertFalse(controller.is_alive());self.assertEqual(reports[0]['code'],'RUN_EXPIRED')
            self.assertTrue(reports[0]['ram_cleared'])
            self.assertTrue((self.host.directory/'result.json').is_file())
        finally:
            if controller.is_alive():self.host.ledger.halt('RUN_TEST_STOP');controller.join(8)

    def test_lifecycle_local_stop_cancels_pending_request_and_closes_sdk(self):
        self.compose();self.mode='blocked';_,task=self.receive();self.assertTrue(self.started.wait(3))
        stop=threading.Event();stop.set()
        report=self.host.run_until_stopped(self.scheduler,stop_event=stop)
        self.assertTrue(report['ram_cleared']);self.assertEqual(report['quota']['consumed_turns'],1)
        self.assertEqual(self.host.sessions[0].report()['sdk_resources']['state'],'CLOSED')

    def test_report_failure_is_safe_and_does_not_repeat_ai(self):
        self.compose();self.ask()
        with patch('apps.qq_bot.session_run.write_new',side_effect=OSError('synthetic')):
            with self.assertRaisesRegex(BotError,'RUN_REPORT_FAILED'):self.host.stop(self.scheduler)
        self.assertEqual(len(self.http),2);self.assertEqual(len(self.delivery.posts),1)

    def test_candidate_cli_is_offline_and_does_not_approve_or_open_instances(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()) as output:self.assertEqual(main(['--check-contract']),0)
        report=json.loads(output.getvalue());self.assertFalse(report['real_execution'])
        with redirect_stdout(StringIO()):self.assertEqual(main(['--check-contract','--total-budget-cny','2.00']),1)
        from apps.qq_bot.conversations import ConversationOptions
        scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
        self.assertEqual(candidate_record(scope)['scope_sha256'],_hash(scope))

    def test_candidate_file_matches_code_and_has_no_real_qualification(self):
        from pathlib import Path
        from apps.qq_bot.conversations import ConversationOptions
        resource=Path(__file__).resolve().parents[2]/'ai_service/resources/qq_session_run_candidate.json'
        record=json.loads(resource.read_text(encoding='utf-8'))
        self.assertEqual(record,candidate_record(prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))))
        self.assertIsNone(record['qualification_id']);self.assertFalse(record['can_execute_real'])

    def test_non_memory_sdk_client_rejected_and_closed_without_any_http(self):
        from openai import AsyncOpenAI
        import httpx
        clients=[];self.compose()
        def factory(runtime,remaining):
            client=AsyncOpenAI(api_key='fictional-only',base_url=runtime.base_url,max_retries=0,
                http_client=httpx.AsyncClient(trust_env=False,follow_redirects=False))
            clients.append(client);return client
        self.host.factory=factory
        done=self.ask();self.assertEqual(done['state'],'FAILED')
        self.assertEqual(done['code'],'SESSION_RUN_MEMORY_HTTP_REQUIRED')
        self.assertTrue(all(c.is_closed() for c in clients));self.assertEqual(self.http,[])

    def test_no_factory_cannot_create_live_host_or_read_instance(self):
        directory=self.root/'no-factory';directory.mkdir()
        with patch('apps.qq_bot.session_run.InstanceMonitoring',side_effect=AssertionError('no instance access')):
            with self.assertRaisesRegex(BotError,'SESSION_RUN_OFFLINE_ONLY'):
                SessionRun(self.inputs,directory,async_client_factory=None)

    def test_existing_live_trial_transports_reject_new_host_and_turn_types(self):
        import httpx
        from apps.qq_bot.transport import QQAPI
        from apps.qq_bot.ai_trial_delivery import TrialQQTransport,ConversationQQTransport
        self.compose();self.ask()
        api=QQAPI(APP,None,client=httpx.Client(transport=httpx.MockTransport(lambda _:None),trust_env=False))
        self.addCleanup(api.close)
        with self.assertRaisesRegex(BotError,'TRIAL_QQ_COMPOSITION_REQUIRED'):
            TrialQQTransport(api,self.host.sessions[0])
        with self.assertRaisesRegex(BotError,'CONVERSATION_TRIAL_COMPOSITION_REQUIRED'):
            ConversationQQTransport(api,self.host)

