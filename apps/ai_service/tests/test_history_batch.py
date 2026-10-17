"""Fixed batch orchestration only; child processes and all network are mocked."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from apps.ai_backend.tests import test_execution as offline_guard
from scripts.qualification import qualify_management_history_batch as batch


class HistoryBatchTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plans = batch.batch_plan()
        self.root_patch = patch.object(batch, 'ROOT', self.root)
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        self.cwd_patch = patch.object(Path, 'cwd', return_value=self.root)
        self.cwd_patch.start(); self.addCleanup(self.cwd_patch.stop)
        self.args = ['--confirm-network']
        for case in batch.CASE_IDS:
            self.args.extend(['--' + case + '-plan', self.plans['plans'][case]['plan_sha256']])

    def child(self, command, **options):
        case = command[command.index('--case') + 1]
        identifier = uuid.uuid4().hex
        self.commands.append(command)
        no_tool = self.fail_one and len(self.commands) == 2
        preflight = self.preflight
        requests = [] if preflight else [{'normalized': {'tool_call_count': 0 if no_tool else 1,
            'calls': [] if no_tool else [{'function_name': batch.q.WATER_QUALITY_HISTORY, 'arguments_valid': True}],
            'finish_reason': 'stop'}, 'outcome': 'final_answer' if no_tool else 'tool_calls'}]
        if not preflight and not no_tool:
            requests.append({'normalized': {'tool_call_count': 0, 'calls': [], 'finish_reason': 'stop'},
                             'outcome': 'final_answer'})
        success = not preflight and not no_tool
        report = {'run_id': identifier, 'plan': self.plans['plans'][case], 'evidence_kind': 'real_provider',
            'status': 'completed' if success else 'failed', 'technical_success': success,
            'error_code': 'CREDENTIAL_FILE_ERROR' if preflight else 'ASSISTANT_SOURCE_REQUIREMENT_UNMET' if no_tool else None,
            'request_count': len(requests), 'actual_network_requests': len(requests), 'transport_attempts': len(requests),
            'requests': requests, 'executions': [] if not success else [{'handler_started': True,
                'status': self.plans['plans'][case]['expected_status']}],
            'ledger': {'entries': [] if not success else [{'receipt': {'history_query_completed': True}}]},
            'requirement_satisfied': success, 'product_commit_gate_passed': success,
            'usage': {'usage': {'input_tokens': 3, 'output_tokens': None, 'total_tokens': None}},
            'final_text': 'never-persist-model-text', 'raw_arguments': 'never-persist-arguments'}
        name = batch.q.write_report(self.root, report)
        return SimpleNamespace(returncode=0 if success else 1, stdout=json.dumps({
            **{k: report[k] for k in ('run_id', 'status', 'request_count', 'actual_network_requests')},
            'report': 'outputs/assistant-qualification/' + name}))

    def execute(self, **settings):
        self.commands = []; self.fail_one = settings.get('fail_one', False); self.preflight = settings.get('preflight', False)
        with patch.object(batch.subprocess, 'run', side_effect=self.child), \
                redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
            code = batch.main(self.args)
        summary = json.loads(output.getvalue())
        report = json.loads((self.root / summary['report']).read_text(encoding='utf-8'))
        return code, summary, report

    def test_dry_run_is_inert_and_order_is_fixed_fifteen(self):
        with patch.object(batch.subprocess, 'run', side_effect=AssertionError('no child')), \
                patch.object(batch.q, '_credentials', side_effect=AssertionError('no credentials')), \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(batch.main([]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['actual_network_requests'], 0)
        self.assertEqual(result['batch']['order'], list(batch.CASE_IDS)*5)
        self.assertEqual(result['batch']['max_model_requests'], 30)
        self.assertEqual(result['batch']['max_output_tokens_per_request'], 1024)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_all_three_exact_approvals_required_before_any_child(self):
        for args in (['--confirm-network'], [*self.args[:-1], 'wrong'],
                [*self.args[:-1], 'd4ca9d91c2be245bd9f193f571aad33a18560eb7d572a52202f3ed5747c1a4e0']):
            with patch.object(batch.subprocess, 'run', side_effect=AssertionError('no child')), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(batch.main(args), 2)
            self.assertEqual(json.loads(output.getvalue())['actual_network_requests'], 0)

    def test_fifteen_independent_processes_no_retry_and_safe_aggregate(self):
        code, summary, report = self.execute(fail_one=True)
        self.assertEqual(code, 0); self.assertEqual(summary['completed_samples'], 15)
        self.assertEqual(summary['known_actual_network_requests'], 29)
        self.assertEqual([c[c.index('--case')+1] for c in self.commands], list(batch.ORDER))
        self.assertTrue(all('--confirm-network' in c and '--review-answer' not in c for c in self.commands))
        self.assertEqual(len({r['run_id'] for r in report['samples']}), 15)
        self.assertFalse(report['requests_may_be_unreported']); self.assertFalse(report['release_eligible'])
        no_data = report['by_case']['no-data']
        self.assertEqual((no_data['real_samples'], no_data['technical_success'], no_data['direct_no_tool']), (5,4,1))
        self.assertEqual(no_data['tool_statuses'], {'NO_DATA':4})
        self.assertEqual(report['by_case']['partial-history']['tool_statuses'], {'PARTIAL':5})
        self.assertEqual(no_data['usage']['output_tokens'], {'known_sum':0, 'observed_runs':0})
        self.assertNotIn('never-persist', json.dumps(report))

    def test_credential_preflight_stops_without_consuming_remaining_runs_or_denominator(self):
        code, summary, report = self.execute(preflight=True)
        self.assertEqual(code, 2); self.assertEqual(len(self.commands), 1)
        self.assertEqual(summary['known_actual_network_requests'], 0)
        self.assertEqual(report['by_case']['valid-history']['real_samples'], 0)
        self.assertFalse(summary['requests_may_be_unreported'])

    def test_invalid_or_missing_child_report_stops_counts_unknown(self):
        for child in (SimpleNamespace(returncode=0, stdout='not-json'),
                      SimpleNamespace(returncode=2, stdout='{"actual_network_requests":null}')):
            with patch.object(batch.subprocess, 'run', return_value=child) as process, \
                    redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()):
                self.assertEqual(batch.main(self.args), 2)
            summary = json.loads(output.getvalue())
            self.assertTrue(summary['requests_may_be_unreported'])
            self.assertEqual(summary['known_actual_network_requests'], 0)
            self.assertEqual(process.call_count, 1)

    def test_report_identity_budget_and_duplicate_rejection(self):
        self.commands=[]; self.fail_one=False; self.preflight=False
        command=['--case','valid-history']
        child=self.child(command)
        path=self.root/json.loads(child.stdout)['report']
        original=json.loads(path.read_text())
        for mutation in ({'actual_network_requests':3}, {'transport_attempts':True}, {'plan':{}},
                         {'run_id':'wrong'}, {'evidence_kind':'offline_fixture'}):
            path.write_text(json.dumps({**original,**mutation}))
            with self.assertRaises(batch.q.QualificationError):
                batch.read_sample(self.root,child,self.plans['plans']['valid-history'],set(),1)
        path.write_text(json.dumps(original))
        with self.assertRaises(batch.q.QualificationError):
            batch.read_sample(self.root,child,self.plans['plans']['valid-history'],{original['run_id']},1)

    def test_interrupt_stops_and_does_not_assume_zero_requests(self):
        with patch.object(batch.subprocess,'run',side_effect=KeyboardInterrupt()) as process, \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(batch.main(self.args),2)
        self.assertEqual(process.call_count,1)
        self.assertTrue(json.loads(output.getvalue())['requests_may_be_unreported'])


if __name__ == '__main__':
    unittest.main()
