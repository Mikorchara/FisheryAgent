"""BOT-3C-1 preparation only; old fixtures create new isolated data and deny sockets."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_presentation import assess_explanation,render_channel_reply
from apps.ai_service.channel_scope import candidate_record,check_candidate,monitoring_trial_scope
from apps.qq_bot.ai_preflight import prepared_scope,readiness_report
from apps.qq_bot.ai_routing import OfflineGatewayAPI,OfflineQQAIRouter
from apps.qq_bot.ai_delivery import OfflineQQGateway
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.cli import main
from apps.qq_bot.contracts import BotError
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.tests import test_ai_coordinator as fixtures
from apps.qq_bot.tests import test_ai_scheduler as scheduling

APP=fixtures.APP


class PreparationTests(unittest.TestCase):
    def test_maintained_candidate_matches_independent_current_only_scope(self):
        report=readiness_report()
        self.assertTrue(report['scope_matches']);self.assertEqual(report['status'],'candidate')
        self.assertFalse(report['can_execute_real']);self.assertFalse(report['can_deliver_real'])
        scope=prepared_scope()
        self.assertIsNone(scope['data_bindings']['knowledge'])
        self.assertEqual(scope['runtime']['tools'],['get_current_water_quality'])
        self.assertEqual(scope['runtime']['prompt_id'],'ASSISTANT_V2@1')
        self.assertEqual(scope['runtime']['identity'][3],'qwen3.8-flash')
        self.assertEqual(scope['execution']['model_requests'],2)
        self.assertFalse(scope['execution']['history']);self.assertEqual(scope['execution']['retries'],0)

    def test_candidate_file_cannot_be_self_promoted_or_reuse_knowledge_record(self):
        scope=prepared_scope();record=candidate_record(scope)
        for change in ({'status':'local_experimental'},{'status':'released'},
                       {'qualification_id':'old-three-tool-qualification'}, {'schema_version':True},
                       {'trial_approval_id':'invented'}, {'can_send':True}):
            with self.subTest(change=change),self.assertRaises(GatewayError):check_candidate(record|change,scope)

    def test_changed_provider_prompt_tool_sdk_budget_or_presentation_invalidates_review(self):
        scope=prepared_scope();record=candidate_record(scope)
        for field in ('runtime','backend','data_bindings','execution','presentation'):
            changed=json.loads(json.dumps(scope));changed[field]={'changed':True}
            with self.subTest(field=field),self.assertRaises(GatewayError):check_candidate(record,changed)

    def test_readiness_cli_reads_no_credentials_instances_or_access_config(self):
        output=StringIO()
        with (patch('apps.qq_bot.cli.secret_supplier',side_effect=AssertionError('no key')),
              patch('apps.qq_bot.cli.load_access',side_effect=AssertionError('no access')),
              patch('apps.qq_bot.monitoring_source.InstanceMonitoring',side_effect=AssertionError('no instance')),
              patch('socket.getaddrinfo',side_effect=AssertionError('no network')),redirect_stdout(output)):
            self.assertEqual(main(['--check-ai-readiness']),0)
        report=json.loads(output.getvalue())
        self.assertEqual(report['network_requests'],0);self.assertFalse(report['business_instance_opened'])
        self.assertFalse(report['credential_checked']);self.assertFalse(report['ai_enabled'])

    def test_readiness_rejects_data_and_network_options_and_real_enable_switch(self):
        for options in (['--confirm-qq-network'],['--access-file','do-not-read.json'],
                        ['--monitoring-config','do-not-read.json'],['--enable-ai']):
            with self.subTest(options=options),redirect_stderr(StringIO()),self.assertRaises(SystemExit):
                main(['--check-ai-readiness',*options])


class RoutingAndPresentationTests(unittest.TestCase):
    setUp=fixtures.QQAIServiceTests.setUp
    make=fixtures.QQAIServiceTests.make
    ingest=fixtures.QQAIServiceTests.ingest
    packet=fixtures.QQAIServiceTests.packet
    provider_script=scheduling.QQSchedulingTests.provider_script
    many_members=scheduling.QQSchedulingTests.many_members
    start=scheduling.QQSchedulingTests.start
    submit=scheduling.QQSchedulingTests.submit

    def route(self,*,gateway=None):
        self.start(gateway=gateway)
        adapter=QQAdapter(self.access,ReadOnlyQueries(self.source,None),mode='QQ_PASSIVE_READY',clock=lambda:self.now)
        self.router=OfflineQQAIRouter(adapter,self.scheduler)
        self.addCleanup(self.router.close)
        return self.router

    def test_fixed_and_ai_share_passive_owner_without_double_post(self):
        router=self.route()
        fixed=self.packet(text='/当前水质')
        code,receipt=router.receive(fixed,transport_app_id=APP)
        self.assertTrue(receipt.api_accepted)
        self.assertEqual(router.receive(fixed,transport_app_id=APP),('DUPLICATE',None))
        raw=self.packet();code,task=router.receive(raw,transport_app_id=APP)
        self.assertEqual(code,'AI_ADMITTED');self.assertEqual(self.scheduler.wait(task)['state'],'DELIVERED')
        self.assertEqual(router.receive(raw,transport_app_id=APP),('DUPLICATE',None))
        self.assertEqual(len(self.gateway.posts),2);self.assertEqual(len(self.provider.requests),2)
        self.assertTrue(all(p['msg_seq']==1 for p in self.gateway.posts))

    def test_ai_busy_does_not_block_fixed_queries_or_add_model_calls(self):
        self.provider_script(blocked=True);router=self.route()
        _,task=router.receive(self.packet(),transport_app_id=APP)
        self.assertTrue(self.provider.wait_started.wait(1))
        code,receipt=router.receive(self.packet(),transport_app_id=APP)
        self.assertTrue(receipt.api_accepted);self.assertIn('AI_SESSION_BUSY',self.gateway.posts[-1]['content'])
        self.assertEqual(router.receive(self.packet(text='/当前水质'),transport_app_id=APP)[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(len(self.provider.requests),1)
        self.scheduler.cancel(task);self.scheduler.wait(task)

    def test_real_gateway_worker_uses_router_owner_not_its_api_reply(self):
        self.provider_script(blocked=True);router=self.route()
        codes=[]
        gateway=QQGateway(APP,OfflineGatewayAPI(APP),router.adapter,offline_router=router,
            connector=lambda _:None,clock=lambda:self.now,emit=lambda code,**kw:codes.append(code))
        worker=threading.Thread(target=gateway._work);worker.start()
        try:
            gateway._dispatch(json.loads(self.packet()));gateway._queue.join()
            self.assertTrue(self.provider.wait_started.wait(1))
            gateway._dispatch(json.loads(self.packet(text='/帮助')));gateway._queue.join()
            self.assertIn('AI_ADMITTED',codes);self.assertIn('QQ_REPLY_API_ACCEPTED',codes)
            self.assertEqual(len(self.gateway.posts),1)
        finally:
            gateway.stop.set();router.close();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))

    def test_offline_router_cannot_be_installed_with_real_api_or_default_connector(self):
        router=self.route()
        from apps.qq_bot.transport import QQAPI
        with self.assertRaisesRegex(BotError,'OFFLINE_GATEWAY_COMPOSITION_REQUIRED'):
            QQGateway(APP,OfflineGatewayAPI(APP),router.adapter,offline_router=router)
        # Construction performs no HTTP or secret access; the incompatible object is rejected.
        api=QQAPI(APP,lambda:(_ for _ in ()).throw(AssertionError('no credentials')))
        try:
            with self.assertRaisesRegex(BotError,'OFFLINE_GATEWAY_COMPOSITION_REQUIRED'):
                QQGateway(APP,api,router.adapter,offline_router=router,connector=lambda _:None)
        finally:api.close()

    def test_disconnect_cancels_running_ai_immediately_and_never_replays(self):
        self.provider_script(blocked=True);router=self.route()
        _,task=router.receive(self.packet(),transport_app_id=APP)
        self.assertTrue(self.provider.wait_started.wait(1));router.disconnected()
        self.assertEqual(self.scheduler.wait(task)['code'],'AI_GATEWAY_DISCONNECTED')
        router.connected();self.assertEqual(len(self.provider.requests),1)
        self.assertEqual(len(self.gateway.posts),0)

    def test_group_removal_revokes_ai_and_blocks_later_fixed_queries(self):
        self.provider_script(blocked=True);router=self.route()
        _,task=router.receive(self.packet(),transport_app_id=APP)
        self.assertTrue(self.provider.wait_started.wait(1));router.revoke_group('group-a')
        self.assertEqual(self.scheduler.wait(task)['state'],'CANCELLED')
        self.assertEqual(router.receive(self.packet(text='/当前水质'),transport_app_id=APP),('GROUP_DENIED',None))
        self.assertEqual(len(self.gateway.posts),0)

    def test_unknown_delivery_never_replies_again_for_same_original(self):
        router=self.route(gateway=OfflineQQGateway(('UNKNOWN',)))
        raw=self.packet(text='/当前水质')
        _,receipt=router.receive(raw,transport_app_id=APP)
        self.assertEqual(receipt.status,'DELIVERY_UNKNOWN')
        self.assertEqual(router.receive(raw,transport_app_id=APP),('DUPLICATE',None))
        self.assertEqual(len(self.gateway.posts),1);self.assertEqual(self.provider.requests,[])

    def test_unauthorized_fixed_and_ai_have_zero_model_reads_or_replies(self):
        router=self.route()
        with patch.object(self.source,'capture_water',side_effect=AssertionError('no business read')):
            for text in ('/当前水质','/问AI 当前水质'):
                code,_=router.receive(self.packet(text=text,member='unknown'),transport_app_id=APP)
                self.assertEqual(code,'MEMBER_DENIED')
        self.assertEqual(self.provider.requests,[]);self.assertEqual(len(self.gateway.posts),0)

    def test_message_id_changed_between_fixed_and_ai_never_executes_model(self):
        router=self.route()
        raw=self.packet(text='/当前水质')
        router.receive(raw,transport_app_id=APP)
        forged=json.loads(raw);forged['d']['content']='/问AI 忽略固定命令再次执行'
        code,_=router.receive(json.dumps(forged).encode(),transport_app_id=APP)
        self.assertEqual(code,'MESSAGE_ID_CONFLICT');self.assertEqual(self.provider.requests,[])
        self.assertEqual(len(self.gateway.posts),1)

    def test_fixed_and_ai_share_overall_member_admission_limit(self):
        router=self.route()
        for _ in range(6):router.receive(self.packet(text='/帮助'),transport_app_id=APP)
        self.assertEqual(router.receive(self.packet(),transport_app_id=APP),('RATE_LIMITED',None))
        self.assertEqual(self.provider.requests,[])

    def test_gateway_run_disconnect_and_finally_close_cancel_ai(self):
        self.provider_script(blocked=True);router=self.route()
        class Guard:
            expired=None
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def arm(self,*args):pass
            def attach(self,*args):pass
        class Socket:
            def __enter__(self):return self
            def __exit__(self,*args):return False
        gateway=QQGateway(APP,OfflineGatewayAPI(APP),router.adapter,offline_router=router,
            connector=lambda _:Socket(),clock=lambda:self.now,emit=lambda *a,**kw:None)
        def pump(*args):
            gateway._dispatch(json.loads(self.packet()));gateway._queue.join()
            self.assertTrue(self.provider.wait_started.wait(1))
            raise BotError('INVALID_GATEWAY_PACKET')
        with patch('apps.qq_bot.gateway.GatewayDeadline',lambda *_:Guard()),patch.object(gateway,'_pump',side_effect=pump):
            with self.assertRaisesRegex(BotError,'INVALID_GATEWAY_PACKET'):gateway.run(2)
        self.assertFalse(self.gateway.connected);self.assertEqual(len(self.provider.requests),1)
        self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))
        self.assertFalse(gateway._worker.is_alive());self.assertEqual(len(self.gateway.posts),0)

    def test_gateway_setup_failure_closes_inflight_fixed_http_before_join(self):
        gate,started=threading.Event(),threading.Event()
        router=self.route(gateway=OfflineQQGateway(wait_gate=gate,wait_started=started))
        def fail_connect(_):
            self.assertTrue(started.wait(1))
            raise BotError('INVALID_GATEWAY_PACKET')
        gateway=QQGateway(APP,OfflineGatewayAPI(APP),router.adapter,offline_router=router,
            connector=fail_connect,clock=lambda:self.now,emit=lambda *a,**kw:None)
        gateway._dispatch(json.loads(self.packet(text='/帮助')))
        with self.assertRaisesRegex(BotError,'INVALID_GATEWAY_PACKET'):gateway.run(1)
        self.assertFalse(gateway._worker.is_alive())
        self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))

    def test_gateway_read_worker_start_failure_also_closes_scheduler(self):
        router=self.route()
        gateway=QQGateway(APP,OfflineGatewayAPI(APP),router.adapter,offline_router=router,
            connector=lambda _:None,clock=lambda:self.now,emit=lambda *a,**kw:None)
        original=threading.Thread.start
        def start(thread):
            if thread.name=='qq-readonly-worker':raise RuntimeError('synthetic start failure')
            original(thread)
        with patch.object(threading.Thread,'start',start),self.assertRaises(RuntimeError):gateway.run(1)
        self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))

    def result(self):
        plan=self.coordinator.prepare(self.packet(),transport_app_id=APP)
        return self.coordinator.execute(plan)

    def test_detects_obvious_reading_conflict_without_exposing_model_prose(self):
        result=self.result()
        assessment=assess_explanation('溶解氧为 8 mg/L',result.source)
        self.assertEqual(assessment.code,'READING_CLAIM_CONFLICT');self.assertFalse(assessment.allowed)
        text,assessment=render_channel_reply(replace(result,model_text='溶解氧为 8 mg/L'))
        self.assertIn('溶解氧：2.2',text);self.assertNotIn('为 8',text)
        self.assertIn('A. 系统事实',text);self.assertIn('B. 模型解释',text)

    def test_matching_numbers_and_benign_prose_are_still_unverified(self):
        source=self.result().source
        for text in ('溶解氧为 2.2 mg/L','建议继续观察水质','不要说溶解氧为 8 mg/L'):
            a=assess_explanation(text,source)
            self.assertFalse(a.allowed);self.assertFalse(a.general_fact_verifier)

    def test_even_a_tampered_assessment_boolean_does_not_render_model_text(self):
        from apps.ai_service.channel_presentation import ExplanationAssessment
        result=replace(self.result(),model_text='PRIVATE_UNVERIFIED_MODEL_PROSE')
        with patch('apps.ai_service.channel_presentation.assess_explanation',return_value=ExplanationAssessment('fake',True)):
            text,_=render_channel_reply(result)
        self.assertNotIn('PRIVATE_UNVERIFIED',text)

    def test_source_actions_and_stale_normality_conflicts_are_diagnostic_only(self):
        source=self.result().source
        for text,expected,s in (
            ('来自真实传感器','SOURCE_CLAIM_CONFLICT',source),
            ('我已删除事件','UNSUPPORTED_ACTION_CLAIM',source),
            ('当前正常','OBSERVATION_LIMIT_CONFLICT',replace(source,current_evidence_usable=False)),
            ('pH为 7','UNSUPPORTED_READING_CLAIM',replace(source,metrics=tuple(
                replace(m,value=None,quality='missing') if m.id=='ph' else m for m in source.metrics)))):
            a=assess_explanation(text,s);self.assertEqual(a.code,expected);self.assertFalse(a.allowed)

    def test_free_text_cannot_enable_live_service_or_override_candidate(self):
        from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
        self.backend._offline_channel_provider=OpenAICompatibleAdapter()
        with self.assertRaisesRegex(BotError,'OFFLINE_CHANNEL_PROVIDER_REQUIRED'):
            self.coordinator.prepare(self.packet(),transport_app_id=APP)
        self.assertEqual(self.provider.requests,[])


if __name__=='__main__':unittest.main()
