"""Consent-bound qualification over formal Normal runtime; all SDK I/O is fake."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import importlib.util
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.ai_backend.tests import test_execution as offline_guard
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final
from apps.ai_backend.credentials import CredentialStore, CredentialFileError
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import GatewayError, ModelResponse
from apps.ai_service.runtime.assistant import SYSTEM_INSTRUCTION, assistant_profile
from apps.ai_service.development import history_qualification as q
from apps.ai_service.development import streaming_qualification as previous

ROOT = Path(__file__).resolve().parents[3]
SECRET = 'fictional-history-qualification-secret'
ANSWER = 'fictional-answer-never-persist'
ARGS = json.dumps({'lookback_minutes':30,'metrics':[q.DO]})


class HistoryQualificationTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.profile=assistant_profile(q.PRESET)
        self.credentials=CredentialStore(process_env={self.profile.credential_ref:SECRET})
        self.sdk=None

    def call(self,arguments=ARGS,name=q.WATER_QUALITY_HISTORY):
        return sdk_tool(name,arguments=arguments,model=self.profile.model)

    def final(self,text=ANSWER,finish='stop'):
        return sdk_final(text,finish=finish,model=self.profile.model)

    def execute(self,case='valid-history',plans=None,**options):
        self.sdk=FakeSDK(plans or [self.call(),self.final()],model=self.profile.model,
            on_close=options.pop('on_close',None))
        return q.run(case,self.root,confirm_network=True,approved_plan_sha256=q.plan(case)['plan_sha256'],
            credential_store=self.credentials,
            adapter_factory=lambda *args,**kwargs:q._Adapter(*args,**kwargs,async_client_factory=self.sdk.factory),**options)

    def cli(self):
        spec=importlib.util.spec_from_file_location('history_qualification_cli',
            ROOT/'scripts/qualification/qualify_management_history.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        return cli

    def test_dry_run_is_inert_repeatable_and_three_cases_have_independent_hashes(self):
        with patch.object(q,'_credentials',side_effect=AssertionError('no credentials')), \
                patch.object(q,'MonitoringRepository',side_effect=AssertionError('no SQLite')), \
                patch.object(q,'_Adapter',side_effect=AssertionError('no SDK')):
            plans=[q.plan(c.case_id) for c in q.CASES]
            report=q.run('valid-history',self.root)
        self.assertEqual(list(self.root.iterdir()),[])
        self.assertEqual(report['actual_network_requests'],0);self.assertEqual(report['qualification_verdict'],'NOT_RUN')
        self.assertEqual(len({p['plan_sha256'] for p in plans}),3)
        self.assertEqual(len({p['scope_sha256'] for p in plans}),1)
        self.assertEqual(len({p['fixture']['dataset_sha256'] for p in plans}),3)
        for plan in plans:
            self.assertEqual(q.plan(plan['case_id']),plan)
            self.assertEqual(plan['release_status'],'candidate');self.assertFalse(plan['web_flag_enabled'])
            self.assertEqual(plan['scope']['runtime']['prompt_id'],'ASSISTANT_V2@1')
            self.assertEqual(plan['exposed_tools'],[q.WATER_QUALITY_HISTORY])
            self.assertEqual((plan['max_tool_calls'],plan['max_tool_rounds'],plan['max_model_requests']),(1,1,2))
            self.assertEqual(plan['max_output_tokens'],1024);self.assertEqual(plan['retry'],0)
            self.assertIsNone(plan['profile_default_max_output_tokens'])
            self.assertEqual(plan['scope']['budget']['max_output_tokens'],1024)

    def test_missing_wrong_cross_case_and_old_two_tool_approval_cannot_access_credentials(self):
        hashes=(None,'invalid',q.plan('no-data')['plan_sha256'],previous.plan('current-water')['plan_sha256'],
                '865051a3ec5175b38977f5db7a68630fe7a71625723a2f0a607ee77c462de7ed')
        for digest in hashes:
            with self.subTest(digest=digest),patch.object(q,'_credentials',side_effect=AssertionError('no credentials')):
                with self.assertRaisesRegex(q.QualificationError,'PLAN_CHANGED'):
                    q.run('valid-history',self.root,confirm_network=True,approved_plan_sha256=digest)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_scope_and_plan_mutations_fail_before_execution(self):
        config=q.load_history_config()
        for key in ('identity','protocol_spec','prompt_sha256','history_version','tool_definitions_sha256','tools'):
            changed=json.loads(config.scope_json);changed['runtime'][key]='changed'
            with patch.object(q,'load_history_config',return_value=replace(config,scope_json=q._json(changed))):
                with self.assertRaisesRegex(q.QualificationError,'SCOPE_MISMATCH'):q.plan('valid-history')
        for key in ('source_version','data_binding','budget'):
            changed=json.loads(config.scope_json);changed[key]='changed'
            with patch.object(q,'load_history_config',return_value=replace(config,scope_json=q._json(changed))):
                with self.assertRaisesRegex(q.QualificationError,'SCOPE_MISMATCH'):q.plan('valid-history')
        before=q.plan('valid-history')
        with patch.object(q,'VERSION','management-history-qualification@future'):
            self.assertNotEqual(q.plan('valid-history')['plan_sha256'],before['plan_sha256'])
        for value in (True,0,1025,1024.0,'1024'):
            with patch.object(q,'MAX_OUTPUT_TOKENS',value):
                with self.assertRaises(GatewayError):q.plan('valid-history')

    def test_all_three_formal_paths_statistics_sources_usage_cleanup_and_budget(self):
        for case,status,count,positive in (('valid-history','OK',30,True),('no-data','NO_DATA',0,False),
                ('partial-history','PARTIAL',24,True)):
            with self.subTest(case=case):
                def decide(index,body):
                    self.assertNotIn('stream',body);self.assertEqual(body['max_tokens'],1024)
                    self.assertEqual(body.get('extra_body',{}).get('enable_thinking'),False)
                    self.assertEqual(body['messages'][0]['content'],SYSTEM_INSTRUCTION)
                    self.assertEqual([tool['function']['name'] for tool in body['tools']],[q.WATER_QUALITY_HISTORY])
                    if index==1:
                        self.assertEqual(body['tool_choice'],'auto');self.assertEqual(len(body['messages']),2)
                        return self.call()
                    self.assertEqual(body['tool_choice'],'none');self.assertTrue(self.sdk.clients[0].closed)
                    payload=json.loads(next(m['content'] for m in body['messages'] if m['role']=='tool'))
                    self.assertEqual(payload['status'],status)
                    self.assertEqual(payload['metrics'][q.DO]['reliable_windows'],count)
                    self.assertTrue(all(q._fixture_checks(payload,q.get_case(case)).values()))
                    return self.final()
                report=self.execute(case,decide)
                self.assertTrue(report['technical_success'],report['error_code'])
                self.assertEqual((report['request_count'],report['transport_attempts'],report['actual_network_requests']),(2,2,0))
                self.assertTrue(report['expected_path_matches']);self.assertTrue(report['result_context_matches'])
                self.assertTrue(report['provider_protocol_verified']);self.assertTrue(report['fixture_matches'])
                self.assertTrue(report['formal_turn_registry_matches']);self.assertTrue(report['historical_source_not_current'])
                self.assertTrue(report['product_commit_gate_passed']);self.assertTrue(report['requirement_satisfied'])
                receipt=report['ledger']['entries'][0]['receipt']
                self.assertTrue(receipt['history_query_completed'])
                self.assertEqual(receipt['has_historical_observations'],positive)
                self.assertFalse(receipt['observation_query_completed']);self.assertFalse(receipt['has_observation'])
                self.assertEqual(report['usage']['usage']['total_tokens'],10)
                self.assertFalse(report['web_can_send_after_probe']);self.assertTrue(report['backend_io_closed'])
                self.assertEqual(report['qualification_verdict'],'PENDING_MANUAL_REVIEW')
                self.assertTrue(all(client.closed for client in self.sdk.clients))
                self.assertFalse(list((self.root/'outputs/assistant-qualification/.management-work').iterdir()))

    def test_history_budget_is_strict_at_construction_and_transport_without_expanding_old_limits(self):
        from apps.ai_service.development.qualification_adapter import validate_qualification_token_budget
        from apps.ai_service.history_execution import validate_history_token_budget
        for value in (1,256,512,1024):
            validate_history_token_budget(value)
        for value in (False,True,None,0,-1,1025,1024.0,'1024'):
            with self.subTest(value=value),self.assertRaises(GatewayError):
                q._Adapter(self.profile.model,None,(q.WATER_QUALITY_HISTORY,),value)
        with self.assertRaises(GatewayError):
            q._Adapter(self.profile.model,None,(q.WATER_QUALITY_HISTORY,),1024,streaming=True)
        for value,streaming in ((257,False),(1024,False),(513,True),(1024,True)):
            with self.assertRaises(GatewayError):
                validate_qualification_token_budget(value,streaming=streaming)
        original=q._Adapter._kwargs
        def mutated(adapter,*args,**kwargs):
            adapter.max_output_tokens=True
            return original(adapter,*args,**kwargs)
        with patch.object(q._Adapter,'_kwargs',mutated):
            report=self.execute()
        self.assertFalse(report['technical_success'])
        self.assertEqual(self.sdk.bodies,[])
        self.assertFalse(report['product_commit_gate_passed'])

    def test_optional_metrics_can_be_omitted_without_fabricating_empty_arguments_in_report(self):
        report=self.execute(plans=[self.call('{"lookback_minutes":30}'),self.final()])
        self.assertTrue(report['technical_success'],report['error_code'])
        call=report['requests'][0]['normalized']['calls'][0]
        self.assertTrue(call['arguments_valid']);self.assertNotIn('arguments',call)

    def test_wrong_valid_range_or_metric_fails_qualification_despite_completed_operation(self):
        for args in ('{"lookback_minutes":10}', '{"lookback_minutes":30,"metrics":["ph"]}'):
            with self.subTest(args=args):
                report=self.execute(plans=[self.call(args),self.final()])
                self.assertFalse(report['technical_success'])
                self.assertEqual(report['error_code'],'QUALIFICATION_HISTORY_RESULT_MISMATCH')
                self.assertTrue(report['requirement_satisfied']);self.assertTrue(report['product_commit_gate_passed'])

    def test_no_protocol_call_imitation_has_no_receipt_and_cannot_commit(self):
        report=self.execute(plans=[self.final('[调用工具 get_water_quality_history] 已经查询')])
        self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
        self.assertEqual(report['error_code'],'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
        self.assertEqual(report['ledger'],{'entries':[]});self.assertEqual(report['request_count'],1)

    def test_invalid_unauthorized_and_multiple_calls_never_execute_handler_or_followup(self):
        calls=[self.call('{}'),self.call('{"lookback_minutes":true}'),
            self.call('{"lookback_minutes":30,"device_id":"other"}'),self.call(name='get_current_water_quality')]
        many=self.call();many.choices[0].message.tool_calls*=2;calls.append(many)
        for response in calls:
            with self.subTest(response=response),patch.object(q.MonitoringService,'query_water_history') as query:
                report=self.execute(plans=[response])
            query.assert_not_called();self.assertFalse(report['success'])
            self.assertFalse(report['product_commit_gate_passed']);self.assertEqual(report['request_count'],1)
            self.assertTrue(all(not entry['receipt'].get('history_query_completed',False)
                and not entry['receipt'].get('has_historical_observations',False) for entry in report['ledger']['entries']))

    def test_second_tool_or_truncated_final_cannot_exceed_two_requests_or_commit(self):
        for response in (self.call(),self.final(finish='length')):
            report=self.execute(plans=[self.call(),response])
            self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
            self.assertEqual(report['request_count'],2);self.assertEqual(len(report['executions']),1)
            self.assertEqual(len(report['ledger']['entries']),1)

    def test_provider_identity_normalization_error_and_partial_usage_fail_safely(self):
        wrong=self.call();wrong.model='unexpected-model'
        for plans in ([wrong],[GatewayError('READ_TIMEOUT')],[self.call(),GatewayError('READ_TIMEOUT')]):
            report=self.execute(plans=plans)
            self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
            self.assertLessEqual(report['request_count'],2);self.assertTrue(all(client.closed for client in self.sdk.clients))
        self.assertEqual(report['usage']['reported_count'],1)
        self.assertIsNone(report['usage']['usage']['total_tokens'])
        self.assertEqual(report['requests'][0]['usage']['total_tokens'],5)
        self.assertEqual(len(report['ledger']['entries']),1)

    def test_stop_deadline_and_trace_failure_never_commit_or_preview(self):
        handle=RequestHandle();previews=[]
        report=self.execute(handle=handle,on_close=lambda _:handle.cancel(),answer_reviewer=previews.append)
        self.assertEqual(report['error_code'],'USER_CANCELLED');self.assertFalse(report['product_commit_gate_passed'])
        self.assertEqual(previews,[]);self.assertEqual(report['request_count'],1)
        handle=RequestHandle()
        report=self.execute(handle=handle,on_close=lambda index:handle.cancel() if index==1 else None)
        self.assertEqual(report['error_code'],'USER_CANCELLED');self.assertFalse(report['product_commit_gate_passed'])
        self.assertEqual(report['request_count'],2);self.assertEqual(len(report['ledger']['entries']),1)
        with patch.object(q._Trace,'_append',side_effect=OSError('private-trace-detail')):
            report=self.execute()
        self.assertEqual(report['error_code'],'TRACE_WRITE_ERROR');self.assertFalse(report['product_commit_gate_passed'])
        clock=[1000.0]
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            report=self.execute(on_close=lambda _:clock.__setitem__(0,1121.0))
        self.assertEqual(report['error_code'],'TOTAL_TIMEOUT');self.assertFalse(report['product_commit_gate_passed'])

    def test_corrupt_fixture_tampering_or_statistics_mismatch_is_not_technical_pass(self):
        original=q._monitoring
        def altered(folder,case):
            monitoring=original(folder,case)
            query=monitoring.query_water_history
            def tamper(*args,**kwargs):
                payload=query(*args,**kwargs)
                payload['metrics'][q.DO]['first']['window_mean']=9
                return payload
            monitoring.query_water_history=tamper
            return monitoring
        with patch.object(q,'_monitoring',side_effect=altered):
            report=self.execute()
        self.assertFalse(report['technical_success']);self.assertFalse(report['fixture_matches'])

    def test_closed_web_permission_and_device_policy_are_verified_before_single_claim(self):
        execute=q.ManagementAssistantService.execute_turn
        def guard(service,prepared,handle):
            public=service.bootstrap(q.DEVICE)['history_candidate']
            self.assertFalse(public['can_send']);self.assertEqual(public['release_status'],'candidate')
            self.assertEqual(prepared.policy.exposed_tools,(q.WATER_QUALITY_HISTORY,))
            self.assertEqual(prepared.device_id,q.DEVICE)
            self.assertEqual(prepared.policy_revision,service.management_policy.snapshot().revision)
            with self.assertRaisesRegex(GatewayError,'HISTORY_CANDIDATE_NOT_RELEASED'):
                service.prepare_turn({'preset_id':q.PRESET,'device_id':q.DEVICE,'question':'test',
                    'history':[],'epoch':service.epoch,'execution_profile':q.HISTORY_PROFILE,
                    'revision':public['revision'],'confirm_network':True})
            return execute(service,prepared,handle)
        with patch.object(q.ManagementAssistantService,'execute_turn',guard):report=self.execute()
        self.assertTrue(report['success']);self.assertFalse((self.root/'outputs/tool-policies').exists())

    def test_policy_revoked_after_plan_rejected_before_sdk(self):
        execute=q.ManagementAssistantService.execute_turn
        def revoke(service,prepared,handle):
            current=service.management_policy.snapshot()
            service.management_policy.save([],expected_revision=current.revision)
            return execute(service,prepared,handle)
        with patch.object(q.ManagementAssistantService,'execute_turn',revoke):report=self.execute()
        self.assertFalse(report['success']);self.assertEqual(report['transport_attempts'],0)
        self.assertEqual(report['error_code'],'ASSISTANT_EXECUTION_PROFILE_CHANGED')

    def test_safe_report_preview_redaction_and_no_overwrite(self):
        previews=[]
        report=self.execute(plans=[self.call(),self.final(ANSWER+' '+SECRET)],answer_reviewer=previews.append)
        self.assertTrue(report['success']);self.assertIn('[REDACTED]',previews[0]);self.assertNotIn(SECRET,previews[0])
        self.assertEqual(report['human_review_status'],'PREVIEWED_NOT_APPROVED')
        self.assertFalse(report['release_eligible']);self.assertFalse(report['http_exercised'])
        serialized=json.dumps(report)
        for forbidden in (ANSWER,SECRET,q.QUESTION,SYSTEM_INSTRUCTION,ARGS,
                          'Authorization','CredentialSnapshot','window_mean','details_omitted','control_token'):
            self.assertNotIn(forbidden,serialized)
        filename=q.write_report(self.root,report)
        self.assertEqual(json.loads((self.root/'outputs/assistant-qualification'/filename).read_text(encoding='utf-8')),report)
        with self.assertRaises(q.QualificationError):q.write_report(self.root,report)

    def test_technical_pass_does_not_certify_answer_truthfulness_or_manual_approval(self):
        report=self.execute('no-data',plans=[self.call(),self.final('虚构历史值，仅用于证明技术审查不评价正文')])
        self.assertTrue(report['technical_success'])
        self.assertEqual(report['qualification_verdict'],'PENDING_MANUAL_REVIEW')
        self.assertFalse(report['answer_truthfulness_evaluated']);self.assertFalse(report['answer_quality_evaluated'])
        self.assertFalse(report['release_eligible'])

    def test_sdk_client_cleanup_failure_cannot_execute_handler_or_pass(self):
        def factory(*args,**kwargs):
            def sdk(runtime,remaining):
                client=self.sdk.factory(runtime,remaining)
                async def fail_close():raise OSError('private-cleanup-message')
                client.close=fail_close
                return client
            return q._Adapter(*args,**kwargs,async_client_factory=sdk)
        self.sdk=FakeSDK([self.call(),self.final()],model=self.profile.model)
        with patch.object(q.MonitoringService,'query_water_history') as query:
            report=q.run('valid-history',self.root,confirm_network=True,
                approved_plan_sha256=q.plan('valid-history')['plan_sha256'],credential_store=self.credentials,
                adapter_factory=factory)
        query.assert_not_called();self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
        self.assertEqual(report['transport_attempts'],1)
        self.assertFalse(report['requests'][0]['cleanup']['sdk_client_close_completed'])
        self.assertNotIn('private-cleanup-message',json.dumps(report))

    def test_credential_preflight_and_keyboard_interrupt_preserve_request_accounting(self):
        with patch.object(q,'_credentials',side_effect=CredentialFileError()):
            report=q.run('valid-history',self.root,confirm_network=True,
                approved_plan_sha256=q.plan('valid-history')['plan_sha256'])
        self.assertEqual(report['error_code'],'CREDENTIAL_FILE_ERROR');self.assertEqual(report['actual_network_requests'],0)
        # Test control interruption before execution, without entering a real SDK.
        with patch.object(q.ManagementAssistantService,'execute_turn',side_effect=KeyboardInterrupt()):
            report=self.execute()
        self.assertEqual(report['error_code'],'USER_CANCELLED');self.assertEqual(report['transport_attempts'],0)

    def test_cli_defaults_dry_run_and_rejects_batch_unknown_or_unapproved_arguments(self):
        cli=self.cli()
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(['--case','valid-history']),0)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        with patch.object(cli,'run',side_effect=AssertionError('no execution')),redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(['--case','valid-history','--confirm-network','--plan-sha256','wrong']),2)
        self.assertEqual(json.loads(output.getvalue())['actual_network_requests'],0)
        for args in (['--case','all'],['--case','valid-history','--retry','1'],
                     ['--case','valid-history','--dry-run','--confirm-network']):
            with redirect_stderr(StringIO()),self.assertRaises(SystemExit):cli.main(args)

    def test_cli_preview_terminal_only_and_preserves_counts_if_report_write_fails(self):
        cli=self.cli()
        class Terminal(StringIO):
            def isatty(self):return True
        report={'run_id':'a'*32,'status':'completed','error_code':None,'technical_success':True,'success':True,
            'request_count':2,'actual_network_requests':2,'qualification_verdict':'PENDING_MANUAL_REVIEW',
            'human_review_status':'PREVIEWED_NOT_APPROVED'}
        def run(*args,**kwargs):
            kwargs['answer_reviewer']('visible-preview\x1b[31m\u202eprivate-direction')
            return report
        args=['--case','valid-history','--confirm-network','--plan-sha256',q.plan('valid-history')['plan_sha256']]
        with patch.object(cli,'run',run),patch.object(cli,'write_report',return_value='a.json'), \
                redirect_stdout(StringIO()) as output,redirect_stderr(Terminal()) as terminal:
            self.assertEqual(cli.main([*args,'--review-answer']),0)
        self.assertNotIn('visible-preview',output.getvalue());self.assertIn('visible-preview',terminal.getvalue())
        self.assertNotIn('\x1b',terminal.getvalue());self.assertNotIn('\u202e',terminal.getvalue())
        with patch.object(cli,'run',side_effect=AssertionError('no execution')), \
                redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            self.assertEqual(cli.main([*args,'--review-answer']),2)
        with patch.object(cli,'run',return_value=report), \
                patch.object(cli,'write_report',side_effect=q.QualificationError('QUALIFICATION_REPORT_ERROR')), \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(args),2)
        self.assertEqual(json.loads(output.getvalue())['actual_network_requests'],2)
        with patch.object(cli,'run',side_effect=RuntimeError('private-unexpected-after-start')), \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(args),2)
        self.assertIsNone(json.loads(output.getvalue())['actual_network_requests'])
        self.assertNotIn('private-unexpected-after-start',output.getvalue())

    def test_normalization_disagreement_is_fatal_without_followup(self):
        with patch('apps.ai_backend.openai_compatible_adapter.OpenAICompatibleAdapter._response',
                return_value=ModelResponse(ANSWER,returned_model=self.profile.model,finish_reason='stop')):
            report=self.execute()
        self.assertFalse(report['success']);self.assertEqual(report['error_code'],'QUALIFICATION_NORMALIZATION_MISMATCH')
        self.assertEqual(report['request_count'],1);self.assertEqual(report['ledger'],{'entries':[]})
