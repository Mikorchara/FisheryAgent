"""BOT-3B-2: new isolated SQLite, canned Provider, socket-denied fake QQ only."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

from apps.ai_service.channel import OfflineChannelProvider
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.ai_coordinator import QQAICoordinator
from apps.qq_bot.ai_delivery import DeliveryOwner, OfflineQQGateway
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.contracts import BotError
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.tests import test_ai_coordinator as fixtures

APP,scripted=fixtures.APP,fixtures.scripted


def until(predicate, timeout=3):
    deadline=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>=deadline:raise AssertionError('bounded test wait expired')
        time.sleep(.005)


class QQSchedulingTests(unittest.TestCase):
    # Reuse only the synthetic fixture, not the prior 31 test methods.
    setUp=fixtures.QQAIServiceTests.setUp
    make=fixtures.QQAIServiceTests.make
    ingest=fixtures.QQAIServiceTests.ingest
    packet=fixtures.QQAIServiceTests.packet

    def provider_script(self, *, blocked=False, turns=4, **kwargs):
        one=scripted()._responses
        self.provider=OfflineChannelProvider(tuple(one)*turns,**kwargs)
        self.backend._offline_channel_provider=self.provider
        if blocked:
            self.provider.wait_gate=threading.Event();self.provider.wait_started=threading.Event()

    def many_members(self):
        members=('member-a','member-b','member-c','member-d')
        groups=(replace(self.access.groups[0],members=members),self.access.groups[1])
        self.access=replace(self.access,groups=groups)
        self.config=replace(self.config,grants=(replace(self.config.grants[0],members=members),self.config.grants[1]))
        self.coordinator=self.make()

    def start(self, *, gateway=None, virtual_time=False):
        self.gateway=gateway or OfflineQQGateway(('ACCEPTED',)*8)
        kwargs={}
        if virtual_time:
            self.tick=100.0
            kwargs['monotonic']=lambda:self.tick
            self.coordinator=QQAICoordinator(self.access,self.source,self.backend,config=self.config,
                clock=lambda:self.now,monotonic=lambda:self.tick)
        self.scheduler=QQAIJobScheduler(self.coordinator,self.gateway,clock=lambda:self.now,**kwargs)
        self.addCleanup(self.scheduler.close)
        return self.scheduler

    def submit(self, **kwargs):
        return self.scheduler.submit(self.packet(**kwargs),transport_app_id=APP)

    def test_success_only_source_facts_and_single_passive_post_no_db_writes(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.start();task=self.submit();done=self.scheduler.wait(task)
        self.assertEqual(done['state'],'DELIVERED');self.assertTrue(done['api_accepted'])
        self.assertFalse(done['client_display_confirmed'])
        self.assertEqual(len(self.provider.requests),2);self.assertEqual(len(self.gateway.posts),1)
        body=self.gateway.posts[0]
        self.assertEqual((body['msg_seq'],body['msg_type']),(1,0))
        self.assertEqual(body['msg_id'],'ai-message-1')
        self.assertIn('溶解氧：2.2',body['content']);self.assertNotIn('实时为 8',body['content'])
        for text in ('SIMULATOR','模型自由文本尚未核验','评估时刻','未重新采样'):
            self.assertIn(text,body['content'])
        self.assertLessEqual(len(body['content']),1600)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.credentials.resolve.assert_not_called();self.backend.gateway_factory.assert_not_called()
        self.assertEqual(len(self.scheduler.take_acceptances()),1)
        self.assertEqual(self.scheduler.take_acceptances(),())

    def test_three_members_single_worker_two_waiters_fourth_busy(self):
        self.many_members();self.provider_script(blocked=True)
        self.start()
        tasks=[self.submit()];self.assertTrue(self.provider.wait_started.wait(1))
        tasks+=[self.submit(member=m) for m in ('member-b','member-c')]
        self.assertEqual([self.scheduler.snapshot(t)['state'] for t in tasks],['RUNNING','QUEUED','QUEUED'])
        started=time.monotonic()
        with self.assertRaisesRegex(BotError,'BUSY'):self.submit(member='member-d')
        self.assertLess(time.monotonic()-started,.5);self.assertEqual(len(self.provider.requests),1)
        self.provider.wait_gate.set()
        self.assertEqual([self.scheduler.wait(t)['state'] for t in tasks],['DELIVERED']*3)
        self.assertEqual(len(self.provider.requests),6);self.assertEqual(len(self.gateway.posts),3)

    def test_simultaneous_three_member_admission_uses_all_three_slots(self):
        self.many_members();self.provider_script(blocked=True);self.start()
        packets=[self.packet(member=m) for m in ('member-a','member-b','member-c')]
        barrier=threading.Barrier(3);tasks=[];errors=[]
        def admit(raw):
            try:
                barrier.wait(timeout=1)
                tasks.append(self.scheduler.submit(raw,transport_app_id=APP))
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=admit,args=(p,)) for p in packets]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertTrue(all(not t.is_alive() for t in threads));self.assertEqual(errors,[])
        self.assertEqual(len(tasks),3);self.assertTrue(self.provider.wait_started.wait(1))
        self.provider.wait_gate.set()
        self.assertTrue(all(self.scheduler.wait(t)['state']=='DELIVERED' for t in tasks))

    def test_thread_start_failure_releases_workers_and_scheduler_binding(self):
        original=threading.Thread.start;started=[]
        def fail_last(thread):
            if thread.name=='qq-ai-watchdog':raise RuntimeError('synthetic startup failure')
            original(thread);started.append(thread)
        with patch.object(threading.Thread,'start',fail_last):
            with self.assertRaisesRegex(RuntimeError,'synthetic startup failure'):
                QQAIJobScheduler(self.coordinator,OfflineQQGateway())
        self.assertTrue(all(not t.is_alive() for t in started))
        self.start();self.assertEqual(self.scheduler.wait(self.submit())['state'],'DELIVERED')

    def test_expired_unclaimed_b1_plan_is_reaped_without_deleting_running_plan(self):
        tick=[100.0]
        coordinator=QQAICoordinator(self.access,self.source,self.backend,config=self.config,
            clock=lambda:self.now,monotonic=lambda:tick[0])
        old=coordinator.prepare(self.packet(),transport_app_id=APP)
        tick[0]+=91
        fresh=coordinator.prepare(self.packet(),transport_app_id=APP)
        self.assertNotIn(old.id,coordinator._tasks)
        self.assertEqual(old.handle.state,'CANCELLED')
        # An executing owner retains its map entry until it has returned.
        coordinator._tasks[fresh.id]['state']='EXECUTING';tick[0]+=91
        coordinator.prepare(self.packet(),transport_app_id=APP)
        self.assertIn(fresh.id,coordinator._tasks)

    def test_same_session_busy_and_duplicate_original_message_never_rerun(self):
        self.provider_script(blocked=True);self.start()
        raw=self.packet();task=self.scheduler.submit(raw,transport_app_id=APP)
        self.assertTrue(self.provider.wait_started.wait(1))
        with self.assertRaisesRegex(BotError,'DUPLICATE'):self.scheduler.submit(raw,transport_app_id=APP)
        with self.assertRaisesRegex(BotError,'AI_SESSION_BUSY'):self.submit()
        self.provider.wait_gate.set();self.scheduler.wait(task)
        with self.assertRaisesRegex(BotError,'DUPLICATE'):self.scheduler.submit(raw,transport_app_id=APP)
        self.assertEqual(len(self.provider.requests),2);self.assertEqual(len(self.gateway.posts),1)

    def test_queued_ten_second_expiry_never_starts_provider(self):
        self.many_members();self.provider_script(blocked=True);self.start(virtual_time=True)
        first=self.submit();self.assertTrue(self.provider.wait_started.wait(1))
        queued=self.submit(member='member-b');self.tick+=10.01
        self.assertEqual(self.scheduler.wait(queued)['code'],'AI_QUEUE_TIMEOUT')
        self.assertEqual(len(self.provider.requests),1)
        self.scheduler.cancel(first);self.scheduler.wait(first)

    def test_total_ninety_second_timeout_aborts_provider_io(self):
        self.provider_script(blocked=True);self.start(virtual_time=True)
        task=self.submit();self.assertTrue(self.provider.wait_started.wait(1))
        handle=self.scheduler._jobs[task].plan.handle
        self.tick+=90.01;done=self.scheduler.wait(task)
        self.assertEqual((done['state'],done['code']),('EXPIRED','AI_TOTAL_TIMEOUT'))
        self.assertTrue(handle.io_closed);self.assertEqual(len(self.provider.requests),1)
        self.assertEqual(len(self.gateway.posts),0)

    def test_original_reply_deadline_preserves_fifteen_second_margin(self):
        self.provider_script(blocked=True);self.start(virtual_time=True)
        raw=self.packet();self.now+=timedelta(seconds=280)
        task=self.scheduler.submit(raw,transport_app_id=APP)
        self.assertTrue(self.provider.wait_started.wait(1))
        self.tick+=5.01
        self.assertEqual(self.scheduler.wait(task)['state'],'EXPIRED')
        self.assertEqual(len(self.gateway.posts),0)

    def test_too_old_original_message_rejected_before_model(self):
        self.start();raw=self.packet();self.now+=timedelta(seconds=286)
        with self.assertRaisesRegex(BotError,'AI_REPLY_WINDOW_TOO_SHORT'):
            self.scheduler.submit(raw,transport_app_id=APP)
        self.assertEqual(self.provider.requests,[])

    def test_user_cancel_propagates_and_all_three_workers_stop(self):
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1))
        handle=self.scheduler._jobs[task].plan.handle
        self.scheduler.cancel(task)
        self.assertEqual(self.scheduler.wait(task)['state'],'CANCELLED');self.assertTrue(handle.io_closed)
        self.scheduler.close()
        self.assertTrue(all(not t.daemon and not t.is_alive() for t in self.scheduler._threads))

    def test_shutdown_cancels_running_and_queued_jobs_without_orphans(self):
        self.many_members();self.provider_script(blocked=True);self.start()
        tasks=[self.submit()];self.assertTrue(self.provider.wait_started.wait(1))
        tasks.append(self.submit(member='member-b'))
        self.scheduler.close()
        self.assertTrue(all(self.scheduler.snapshot(t)['state']=='CANCELLED' for t in tasks))
        self.assertEqual(len(self.provider.requests),1)
        with self.assertRaisesRegex(BotError,'AI_SCHEDULER_STOPPED'):self.submit(member='member-c')

    def test_permission_revoked_during_provider_io_cancels_without_delivery(self):
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1))
        self.coordinator.reconfigure(replace(self.config,enabled=False))
        self.assertIn(self.scheduler.wait(task)['state'],('CANCELLED','FAILED'))
        self.assertEqual(len(self.provider.requests),1);self.assertEqual(len(self.gateway.posts),0)

    def test_device_and_instance_rebinding_invalidates_running_task(self):
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1))
        self.source.config=replace(self.source.config,instance_id='new-local-binding')
        done=self.scheduler.wait(task)
        self.assertEqual(done['state'],'CANCELLED');self.assertEqual(done['code'],'AI_AUTH_CHANGED')
        self.assertEqual(len(self.gateway.posts),0)

    def test_policy_revocation_during_provider_wait_is_detected(self):
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1))
        self.backend.management_policy.save([],expected_revision=self.backend.management_policy.snapshot().revision)
        done=self.scheduler.wait(task)
        self.assertEqual(done['state'],'CANCELLED');self.assertEqual(len(self.gateway.posts),0)

    def test_disconnect_cancels_and_reconnect_does_not_replay(self):
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1));self.gateway.disconnect()
        self.assertEqual(self.scheduler.wait(task)['code'],'AI_GATEWAY_DISCONNECTED')
        self.gateway.reconnect();time.sleep(.04)
        self.assertEqual(len(self.provider.requests),1);self.assertEqual(len(self.gateway.posts),0)
        second=self.submit();self.assertEqual(self.scheduler.wait(second)['state'],'DELIVERED')

    def test_failed_unknown_and_unconfirmed_replies_never_retry_or_regenerate(self):
        self.many_members();self.provider_script()
        self.start(gateway=OfflineQQGateway(('FAILED','UNKNOWN','UNCONFIRMED')))
        for member,state in zip(('member-a','member-b','member-c'),('FAILED','DELIVERY_UNKNOWN','DELIVERY_UNKNOWN')):
            done=self.scheduler.wait(self.submit(member=member))
            self.assertEqual(done['state'],state);self.assertFalse(done['api_accepted'])
        self.assertEqual(len(self.provider.requests),6);self.assertEqual(len(self.gateway.posts),3)
        self.assertEqual(self.scheduler.take_acceptances(),())

    def test_cancellation_after_http_submission_means_unknown_not_not_sent(self):
        gate,started=threading.Event(),threading.Event()
        self.start(gateway=OfflineQQGateway(wait_gate=gate,wait_started=started))
        task=self.submit();self.assertTrue(started.wait(1));self.scheduler.cancel(task)
        self.assertEqual(self.scheduler.wait(task)['state'],'DELIVERY_UNKNOWN')
        self.assertEqual(len(self.gateway.posts),1);self.assertEqual(len(self.provider.requests),2)

    def test_pending_delivery_keeps_session_slot_and_total_deadline(self):
        gate,started=threading.Event(),threading.Event()
        self.start(gateway=OfflineQQGateway(wait_gate=gate,wait_started=started),virtual_time=True)
        task=self.submit();self.assertTrue(started.wait(1))
        with self.assertRaisesRegex(BotError,'AI_SESSION_BUSY'):self.submit()
        self.tick+=90.01
        self.assertEqual(self.scheduler.wait(task)['state'],'DELIVERY_UNKNOWN')
        self.assertEqual(len(self.gateway.posts),1)

    def test_delivery_backlog_cannot_grow_past_total_three(self):
        self.many_members();self.provider_script()
        gate,started=threading.Event(),threading.Event()
        self.start(gateway=OfflineQQGateway(('ACCEPTED',)*3,wait_gate=gate,wait_started=started))
        tasks=[self.submit()];self.assertTrue(started.wait(1))
        tasks.append(self.submit(member='member-b'))
        until(lambda:self.scheduler.snapshot(tasks[-1])['state']=='DELIVERY_PENDING')
        tasks.append(self.submit(member='member-c'))
        until(lambda:self.scheduler.snapshot(tasks[-1])['state']=='DELIVERY_PENDING')
        with self.assertRaisesRegex(BotError,'BUSY'):self.submit(member='member-d')
        gate.set()
        self.assertTrue(all(self.scheduler.wait(t)['state']=='DELIVERED' for t in tasks))

    def test_permission_checked_again_immediately_before_submission(self):
        self.start();send=self.gateway.send
        def revoke(context,reply,**kwargs):
            self.coordinator.reconfigure(replace(self.config,enabled=False))
            return send(context,reply,**kwargs)
        with patch.object(self.gateway,'send',side_effect=revoke):
            done=self.scheduler.wait(self.submit())
        self.assertIn(done['state'],('CANCELLED','FAILED'));self.assertEqual(len(self.gateway.posts),0)

    def test_full_text_over_limit_rejected_not_truncated(self):
        from apps.ai_service.channel import SourceSummary
        self.start()
        with patch.object(SourceSummary,'presentation',lambda _: '证据'*1000):
            done=self.scheduler.wait(self.submit())
        self.assertEqual(done['code'],'AI_REPLY_TOO_LONG');self.assertEqual(len(self.gateway.posts),0)
        self.assertEqual(len(self.provider.requests),2)

    def test_backend_final_without_source_never_delivered(self):
        from apps.ai_backend.model_gateway import ModelResponse
        self.backend._offline_channel_provider=self.provider=OfflineChannelProvider((ModelResponse('all healthy',finish_reason='stop'),))
        self.start();done=self.scheduler.wait(self.submit())
        self.assertEqual(done['state'],'FAILED');self.assertEqual(len(self.gateway.posts),0)

    def test_fixed_queries_and_gateway_control_loop_remain_responsive(self):
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1))
        adapter=QQAdapter(self.access,ReadOnlyQueries(self.source,None),clock=lambda:self.now)
        begin=time.monotonic()
        for _ in range(3):
            self.assertTrue(self.gateway.connected)  # Gateway owner is never the AI worker.
            outcome=adapter.receive(self.packet(text='/当前水质'),transport_app_id=APP)
            self.assertEqual(outcome.code,'OK');self.assertIsNotNone(outcome.reply)
        self.assertLess(time.monotonic()-begin,.5)
        self.assertEqual(len(self.provider.requests),1)
        self.scheduler.cancel(task);self.scheduler.wait(task)

    def test_actual_gateway_pump_heartbeat_acks_during_blocked_ai(self):
        from apps.qq_bot.gateway import QQGateway
        from apps.qq_bot.tests import test_gateway as wire
        self.provider_script(blocked=True);self.start();task=self.submit()
        self.assertTrue(self.provider.wait_started.wait(1))
        api=Mock(app_id=APP);api.token.return_value='virtual-token'
        adapter=QQAdapter(self.access,ReadOnlyQueries(self.source,None),mode='QQ_PASSIVE_READY',clock=lambda:self.now)
        clock=wire.Clock();codes=[]
        gateway=QQGateway(APP,api,adapter,clock=lambda:self.now,monotonic=clock,
            emit=lambda code,**kw:codes.append(code))
        gateway._deadline=3.1
        socket=wire.FakeSocket(clock,[{'op':10,'d':{'heartbeat_interval':1000}},wire.ready()])
        gateway._pump(socket)
        self.assertIn('QQ_HEARTBEAT_SENT',codes);self.assertIn('QQ_HEARTBEAT_ACK',codes)
        self.assertTrue(any(p['op']==1 for p in socket.sent))
        self.assertEqual(self.scheduler.snapshot(task)['state'],'RUNNING')
        self.scheduler.cancel(task);self.scheduler.wait(task)

    def test_live_fixed_adapter_keeps_ai_disabled_with_scheduler_present(self):
        self.start()
        adapter=QQAdapter(self.access,ReadOnlyQueries(self.source,None,live=True),
            mode='QQ_PASSIVE_READY',clock=lambda:self.now)
        outcome=adapter.receive(self.packet(),transport_app_id=APP)
        self.assertEqual(outcome.code,'AI_DISABLED');self.assertEqual(self.provider.requests,[])

    def test_single_ai_worker_remains_exclusive_under_concurrent_admission(self):
        self.many_members();self.provider_script(blocked=True,turns=3)
        active=0;maximum=0;lock=threading.Lock();complete=self.provider.complete
        def observed(*args):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active)
            try:
                time.sleep(.01)
                return complete(*args)
            finally:
                with lock:active-=1
        self.start()
        with patch.object(self.provider,'complete',side_effect=observed):
            tasks=[self.submit()];self.assertTrue(self.provider.wait_started.wait(1))
            tasks.extend(self.submit(member=m) for m in ('member-b','member-c'))
            self.provider.wait_gate.set()
            self.assertTrue(all(self.scheduler.wait(t)['state']=='DELIVERED' for t in tasks))
        self.assertEqual(maximum,1)

    def test_shutdown_closes_inflight_fake_http_and_returns_unknown(self):
        gate,started=threading.Event(),threading.Event()
        self.start(gateway=OfflineQQGateway(wait_gate=gate,wait_started=started))
        task=self.submit();self.assertTrue(started.wait(1));self.scheduler.close()
        self.assertEqual(self.scheduler.snapshot(task)['state'],'DELIVERY_UNKNOWN')
        self.assertTrue(all(not t.is_alive() for t in self.scheduler._threads))

    def test_queued_cancel_has_no_provider_call_and_no_plan_leak(self):
        self.many_members();self.provider_script(blocked=True);self.start()
        first=self.submit();self.assertTrue(self.provider.wait_started.wait(1))
        second=self.submit(member='member-b');self.scheduler.cancel(second)
        self.assertEqual(self.scheduler.wait(second)['state'],'CANCELLED')
        self.assertNotIn(second,self.coordinator._tasks)
        self.assertEqual(len(self.provider.requests),1)
        self.scheduler.cancel(first);self.scheduler.wait(first)
        self.assertEqual(self.coordinator._tasks,{})

    def test_expired_utc_window_denied_by_delivery_owner(self):
        plan=self.coordinator.prepare(self.packet(),transport_app_id=APP)
        result=self.coordinator.execute(plan);gateway=OfflineQQGateway()
        owner=DeliveryOwner(self.coordinator,gateway,clock=lambda:self.now)
        self.now+=timedelta(seconds=285)
        with self.assertRaisesRegex(BotError,'AI_REPLY_EXPIRED'):
            owner.deliver(plan,result,threading.Event())
        self.assertEqual(len(gateway.posts),0)

    def test_trace_commit_failure_is_not_delivery_candidate(self):
        self.start()
        with patch.object(self.backend.traces,'record_assistant',side_effect=OSError('synthetic trace failure')):
            done=self.scheduler.wait(self.submit())
        self.assertEqual(done['code'],'TRACE_WRITE_ERROR');self.assertEqual(done['state'],'FAILED')
        self.assertEqual(len(self.gateway.posts),0)

    def test_no_data_is_disclosed_not_treated_as_online_or_healthy(self):
        self.start();done=self.scheduler.wait(self.submit(group='group-b',member='member-b'))
        self.assertEqual(done['state'],'DELIVERED')
        self.assertIn('当前状态无法完整确认',self.gateway.posts[0]['content'])
        self.assertIn('数据不足',self.gateway.posts[0]['content'])

    def test_configured_shorter_turn_budget_is_not_extended_by_scheduler(self):
        from apps.ai_service.channel import ChannelBudget
        self.config=replace(self.config,budget=ChannelBudget(256,1))
        self.provider_script(blocked=True);self.start(virtual_time=True)
        task=self.submit();self.assertTrue(self.provider.wait_started.wait(1))
        self.assertEqual(self.scheduler._jobs[task].plan.context.deadline,101.0)
        self.tick+=1.01
        self.assertEqual(self.scheduler.wait(task)['state'],'EXPIRED')

    def test_uncooperative_io_reports_shutdown_failure_then_can_be_reaped(self):
        self.start();started,release=threading.Event(),threading.Event()
        complete=self.provider.complete
        def uncooperative(*args):
            started.set();release.wait(2)
            return complete(*args)
        with patch.object(self.provider,'complete',side_effect=uncooperative):
            try:
                task=self.submit();self.assertTrue(started.wait(1))
                with self.assertRaisesRegex(BotError,'AI_SHUTDOWN_INCOMPLETE'):self.scheduler.close(timeout=.02)
                self.assertTrue(self.scheduler._threads[0].is_alive())
            finally:
                release.set();self.scheduler.close()
        self.assertEqual(self.scheduler.snapshot(task)['state'],'CANCELLED')

    def test_unauthorized_user_zero_model_zero_read(self):
        self.start()
        with patch.object(self.source,'capture_water',side_effect=AssertionError('no read')):
            with self.assertRaises(BotError):self.submit(member='not-approved')
        self.assertEqual(self.provider.requests,[]);self.assertEqual(len(self.gateway.posts),0)

    def test_real_transport_and_candidate_flag_changes_cannot_enable_delivery(self):
        with self.assertRaisesRegex(BotError,'OFFLINE_DELIVERY_REQUIRED'):
            QQAIJobScheduler(self.coordinator,object())
        plan=self.coordinator.prepare(self.packet(),transport_app_id=APP)
        result=self.coordinator.execute(plan)
        self.assertFalse(result.can_deliver);self.assertFalse(self.coordinator.check_delivery(plan,result))
        owner=DeliveryOwner(self.coordinator,OfflineQQGateway(),clock=lambda:self.now)
        for changed in (replace(result,can_deliver=True),replace(result,release_status='published')):
            with self.assertRaises(BotError):owner.deliver(plan,changed,threading.Event())

    def test_owner_prevents_second_submission_of_exact_result(self):
        plan=self.coordinator.prepare(self.packet(),transport_app_id=APP)
        result=self.coordinator.execute(plan);gateway=OfflineQQGateway()
        owner=DeliveryOwner(self.coordinator,gateway,clock=lambda:self.now)
        self.assertTrue(owner.deliver(plan,result,threading.Event()).api_accepted)
        with self.assertRaisesRegex(BotError,'AI_DELIVERY_ALREADY_CLAIMED'):
            owner.deliver(plan,result,threading.Event())
        other=DeliveryOwner(self.coordinator,gateway,clock=lambda:self.now)
        with self.assertRaisesRegex(BotError,'AI_DELIVERY_ALREADY_CLAIMED'):
            other.deliver(plan,result,threading.Event())
        self.assertEqual(len(gateway.posts),1)

    def test_second_scheduler_cannot_bypass_global_worker_and_delivery_limits(self):
        self.start()
        with self.assertRaisesRegex(BotError,'AI_SCHEDULER_ALREADY_BOUND'):
            QQAIJobScheduler(self.coordinator,OfflineQQGateway())
        self.assertEqual(sum(t.is_alive() for t in self.scheduler._threads),3)
        self.scheduler.close()
        with QQAIJobScheduler(self.coordinator,OfflineQQGateway(),clock=lambda:self.now) as replacement:
            task=replacement.submit(self.packet(),transport_app_id=APP)
            self.assertEqual(replacement.wait(task)['state'],'DELIVERED')

    def test_all_sources_retain_unknown_limits_through_delivery(self):
        self.provider_script(turns=4);self.start()
        for state in ('stale','offline','missing','invalid'):
            if state in ('missing','invalid'):
                from apps.simulator.generator import Simulator
                self.sim=Simulator(start=self.now,device_id='sim-pond-1',session_id='limits-'+state)
                self.ingest(state)
            else:self.now+=timedelta(seconds=31 if state=='stale' else 91)
            self.assertEqual(self.scheduler.wait(self.submit())['state'],'DELIVERED')
            self.assertIn('当前状态无法完整确认',self.gateway.posts[-1]['content'])

    def test_late_delivery_clock_expiry_denied_even_without_watchdog_tick(self):
        self.start();send=self.gateway.send
        def late(context,reply,**kwargs):
            self.now+=timedelta(seconds=286)
            return send(context,reply,**kwargs)
        with patch.object(self.gateway,'send',side_effect=late):
            done=self.scheduler.wait(self.submit())
        self.assertFalse(done['api_accepted']);self.assertEqual(len(self.gateway.posts),0)


if __name__=='__main__':unittest.main()
