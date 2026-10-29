"""Real typed Session + synthetic SQLite/SDK/QQ: revocation at every I/O edge."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
import threading
import unittest
from unittest.mock import patch

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_service.channel_validation import validation_active
from apps.qq_bot.contracts import BotError
from apps.qq_bot.session_run_trial import SessionTrialRun
from apps.qq_bot.tests import test_session_run_trial as fixture


class SessionValidationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SessionRunTrialTests(
            'test_once_approved_five_typed_turns_resources_and_current_sources')
        self.case.setUp();self.case.ingest(oxygen=6.5)
        self.addCleanup(lambda:self.assertTrue(self.case.doCleanups()))

    def compose(self,mode='chat'):
        case=self.case
        def create(*,members=None,turns=5):
            from apps.qq_bot.run_consent import RunLimits
            case.directory=case.root/'run';case.directory.mkdir()
            case.host=SessionTrialRun(case.inputs,case.directory,members=members,
                limits=RunLimits(max_turns=turns),async_client_factory=case.factory,
                clock=lambda:case.now,presentation_mode=mode)
            case.addCleanup(case.host.close);return case.host
        case.create=create;case.compose()

    def revoke_file(self):
        path=self.case.root/'ai.json'
        data=json.loads(path.read_text('utf8'));data['enabled']=False
        path.write_text(json.dumps(data),encoding='utf8')

    def test_heavy_static_check_once_inside_boundary_not_across_calls(self):
        self.compose();host=self.case.host
        from apps.qq_bot import session_run
        original=session_run.inputs_snapshot;calls=[];owner=threading.get_ident()
        def counted(*args,**kwargs):
            if threading.get_ident()==owner:calls.append(1)
            return original(*args,**kwargs)
        with patch.object(session_run,'inputs_snapshot',side_effect=counted):
            with host.validation_scope():host.check();host.check()
            self.assertEqual(len(calls),1)
            host.check();self.assertEqual(len(calls),2)

    def test_same_mtime_binding_change_is_detected_on_next_boundary(self):
        self.compose();self.case.host.check()
        path=self.case.root/'source.json';old=path.stat()
        data=path.read_bytes();changed=data.replace(b'test-instance',b'next-instance')
        self.assertEqual(len(changed),len(data));self.assertNotEqual(changed,data)
        # Publish one valid, same-size/same-mtime replacement. An in-place truncate
        # races the live watchdog and tests INVALID_MONITORING_CONFIG instead of
        # the intended valid binding-change boundary.
        staged=path.with_name('source-replacement.json')
        staged.write_bytes(changed);os.utime(staged,ns=(old.st_atime_ns,old.st_mtime_ns))
        os.replace(staged,path)
        self.assertEqual(path.stat().st_mtime_ns,old.st_mtime_ns)
        with self.assertRaisesRegex(BotError,'TRIAL_BINDINGS_CHANGED'):self.case.host.check()
        self.assertEqual(self.case.http,[])

    def test_clone_authorization_still_rejected_after_valid_cached_check(self):
        self.compose();host=self.case.host
        with host.validation_scope():
            host.check()
            with self.assertRaisesRegex(GatewayError,'SESSION_TRIAL_RUN_AUTHORIZATION_REQUIRED'):
                host._authority.validate(replace(host._authorization,ticket=object()))

    def test_sdk_quarantine_is_checked_even_with_static_snapshot(self):
        self.compose();host=self.case.host
        with host.validation_scope():
            host.check()
            with patch.object(SDK_RESOURCES,'assert_healthy',side_effect=GatewayError('SDK_RESOURCE_QUARANTINED')):
                with self.assertRaisesRegex(BotError,'SDK_RESOURCE_QUARANTINED'):host.check()

    def test_expiry_is_checked_even_with_static_snapshot(self):
        self.compose();host=self.case.host
        with host.validation_scope():
            host.check();self.case.now+=timedelta(minutes=31)
            with self.assertRaises(BotError):host.check()
        self.assertEqual(self.case.http,[])

    def test_validation_snapshots_never_span_business_or_network_io(self):
        case=self.case;seen=[];factory=case.factory
        def sdk(runtime,remaining):
            self.assertFalse(validation_active());seen.append('sdk')
            return factory(runtime,remaining)
        case.factory=sdk;self.compose()
        capture=case.host.monitoring.capture_water;commit=case.host.store.commit;reserve=case.host.ledger.reserve
        http=case.api._client._transport.handler
        def guarded(name,fn):
            def call(*args,**kwargs):
                self.assertFalse(validation_active(),name);seen.append(name)
                return fn(*args,**kwargs)
            return call
        with patch.object(case.host.monitoring,'capture_water',side_effect=guarded('tool',capture)),\
                patch.object(case.host.store,'commit',side_effect=guarded('history',commit)),\
                patch.object(case.host.ledger,'reserve',side_effect=guarded('reserve',reserve)),\
                patch.object(case.api._client._transport,'handler',side_effect=guarded('qq-http',http)):
            done=case.ask()
        self.assertEqual(done['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(seen.count('sdk'),2)
        for name in ('tool','history','reserve','qq-http'):self.assertEqual(seen.count(name),1)

    def test_revocation_after_first_model_blocks_tool_and_second_request(self):
        case=self.case;factory=case.factory
        def sdk(runtime,remaining):
            client=factory(runtime,remaining);handler=client._client._transport.handler
            async def http(request):
                self.assertFalse(validation_active())
                response=await handler(request);self.revoke_file();return response
            client._client._transport.handler=http;return client
        case.factory=sdk;self.compose()
        result=case.ask()
        self.assertNotEqual(result['state'],'DELIVERED')
        self.assertEqual(len(case.http),1);self.assertEqual(case.posts,[])
        self.assertEqual(case.host.store.counts()['turns'],0)

    def test_token_refresh_boundary_revocation_blocks_qq_post(self):
        self.compose();case=self.case;token=case.api.token
        def changed():self.revoke_file();return token()
        with patch.object(case.api,'token',side_effect=changed):done=case.ask()
        self.assertFalse(done.get('api_accepted'));self.assertEqual(case.posts,[])
        self.assertEqual(len(case.http),2);self.assertEqual(case.host.store.counts()['turns'],0)

    def test_api_accept_then_revocation_does_not_commit_or_resend(self):
        self.compose();case=self.case;handler=case.api._client._transport.handler
        def changed(request):
            response=handler(request);self.revoke_file();return response
        with patch.object(case.api._client._transport,'handler',side_effect=changed):done=case.ask()
        self.assertTrue(done.get('api_accepted'));self.assertNotEqual(done.get('history_code'),'HISTORY_COMMITTED')
        self.assertEqual(len(case.posts),1);self.assertEqual(len(case.http),2)
        self.assertEqual(case.host.store.counts()['turns'],0)

    def test_chat_commits_exact_accepted_text_hash(self):
        self.compose();case=self.case
        self.assertEqual(case.ask('现在溶解氧是多少？')['history_code'],'HISTORY_COMMITTED')
        sent=case.posts[-1]['content']
        turn=next(iter(case.host.store._sessions.values())).turns[-1]
        self.assertEqual(turn.text,sent);self.assertEqual(turn.text_sha256,hashlib.sha256(sent.encode()).hexdigest())
        self.assertIn('溶解氧：6.5 mg/L',sent);self.assertNotIn('水温：',sent)
        self.assertNotIn('A. 系统事实',sent)

    def test_detailed_session_scope_is_distinct_and_keeps_abc(self):
        self.compose('detailed');case=self.case
        self.assertEqual(case.ask()['history_code'],'HISTORY_COMMITTED')
        sent=case.posts[-1]['content']
        for label in ('A. 系统事实','B. 模型解释','C. 来源与限制'):self.assertIn(label,sent)
        from apps.ai_service.channel_session_trial import prepared_scope
        from apps.ai_service.runtime.release_contracts import _hash
        self.assertNotEqual(case.host.scope_sha256,_hash(prepared_scope(case.host.options,'chat')))

    def test_changing_display_mode_after_approval_invalidates_scope(self):
        self.compose();self.case.host.presentation_mode='detailed'
        with self.assertRaisesRegex(BotError,'RUN_SCOPE_CHANGED'):self.case.host.check()

    def test_both_display_checks_are_offline_and_scope_bound(self):
        from apps.qq_bot.session_run_trial import check_configuration
        with patch('apps.qq_bot.session_run.InstanceMonitoring',side_effect=AssertionError('no database')):
            chat=check_configuration(self.case.inputs)
            detailed=check_configuration(self.case.inputs,presentation_mode='detailed')
        self.assertEqual(chat['presentation_mode'],'chat')
        self.assertEqual(detailed['presentation_mode'],'detailed')
        self.assertNotEqual(chat['scope_sha256'],detailed['scope_sha256'])
        self.assertEqual(chat['network_requests'],0);self.assertFalse(chat['credential_checked'])
