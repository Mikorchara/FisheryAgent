"""Candidate probes use only the independent Fake SDK and isolated storage."""
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from apps.ai_backend.tests import test_execution as guard
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import RequestHandle
from apps.ai_service.development import normal_selection_qualification as q


class NormalSelectionQualificationTests(unittest.TestCase):
    def setUp(self):
        guard.ExecutionTests.setUp(self)
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.profile=q.assistant_profile(q.history.PRESET)
        self.credentials=CredentialStore(process_env={self.profile.credential_ref:'fictional-normal-selection-key'})

    def execute(self,case_id,plans=None,**options):
        case=q.get_case(case_id)
        args={q.WATER:'{}',q.HISTORY:'{"lookback_minutes":30,"metrics":["dissolved_oxygen_mg_l"]}',
              q.KNOWLEDGE:'{"query":"鳗鲡低氧表现"}'}
        self.sdk=FakeSDK(plans if plans is not None else [*[sdk_tool(n,arguments=args[n],identifier='c'+str(i),model=self.profile.model)
            for i,n in enumerate(case.expected_tools)],sdk_final('fictional-private-answer',model=self.profile.model)],model=self.profile.model)
        return q.run(case_id,self.root,confirm_network=True,approved_plan_sha256=q.plan(case_id)['plan_sha256'],
            credential_store=self.credentials,adapter_factory=lambda *a,**kw:q.history._Adapter(*a,**kw,
                async_client_factory=self.sdk.factory),**options)

    def test_four_inert_distinct_plans_and_unapproved_run(self):
        with patch.object(q,'_credentials',side_effect=AssertionError('no credential access')),patch.object(q.history,'_monitoring',side_effect=AssertionError('no database')):
            plans=[q.plan(c.case_id) for c in q.CASES]
            report=q.run('current-water',self.root)
            with self.assertRaisesRegex(q.QualificationError,'PLAN_CHANGED'):
                q.run('current-water',self.root,confirm_network=True,approved_plan_sha256=plans[1]['plan_sha256'])
        self.assertEqual(len(set(p['plan_sha256'] for p in plans)),4)
        self.assertTrue(all(p['release_status']=='candidate' and not p['web_flag_enabled'] for p in plans))
        self.assertEqual(report['actual_network_requests'],0);self.assertEqual(list(self.root.iterdir()),[])

    def test_all_four_fake_paths_sources_protocol_budget_cleanup_and_safe_report(self):
        for case in q.CASES:
            with self.subTest(case=case.case_id):
                report=self.execute(case.case_id)
                self.assertTrue(report['technical_success'],report.get('error_code'))
                self.assertTrue(report['product_commit_gate_passed']);self.assertTrue(report['result_context_matches'])
                self.assertTrue(report['requirement_satisfied']);self.assertTrue(report['clients_closed'])
                self.assertEqual(report['request_count'],len(case.expected_tools)+1)
                self.assertEqual(report['actual_network_requests'],0)
                self.assertEqual([e['tool_name'] for e in report['executions']],list(case.expected_tools))
                safe=json.dumps(report)
                for forbidden in ('fictional-private-answer','fictional-normal-selection-key','query_text','representative',
                                  q.get_case(case.case_id).question):
                    self.assertNotIn(forbidden,safe)
                self.assertTrue(all(b['max_tokens']==1024 and b['tool_choice'] in ('auto','none') for b in self.sdk.bodies))

    def test_wrong_tool_bad_args_truncation_stop_and_trace_fail_closed(self):
        for plans in ([sdk_final()], [sdk_tool(q.WATER,arguments='{"extra":1}')],
                      [sdk_final(finish='length')]):
            report=self.execute('current-water',plans)
            self.assertFalse(report['technical_success']);self.assertLessEqual(report['request_count'],1)
        handle=RequestHandle();handle.cancel()
        self.assertFalse(self.execute('current-water',handle=handle)['technical_success'])
        with patch.object(q.history._Trace,'record_assistant',side_effect=OSError('fictional trace failure')):
            self.assertFalse(self.execute('current-water')['technical_success'])

    def test_scope_drift_fails_before_credential_or_sdk(self):
        with patch.object(q,'load_normal_selection_candidate',return_value='{}'),self.assertRaisesRegex(q.QualificationError,'SCOPE_MISMATCH'):
            q.plan('current-water')

    def test_cli_defaults_dry_run_without_report_writes_or_credentials(self):
        from scripts.qualification.qualify_management_normal_selection import main
        output=StringIO()
        with redirect_stdout(output),patch.object(q,'run',side_effect=AssertionError('not approved')):
            self.assertEqual(main(['--case','current-water']),0)
        value=json.loads(output.getvalue())
        self.assertTrue(value['dry_run']);self.assertEqual(value['actual_network_requests'],0)
        self.assertEqual(value['plan']['plan_sha256'],q.plan('current-water')['plan_sha256'])
