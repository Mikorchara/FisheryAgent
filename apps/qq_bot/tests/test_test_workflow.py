"""PowerShell operator wrappers: synthetic SQLite, fake orchestration; no network/keys."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


ROOT = Path(__file__).resolve().parents[3]
DEV = ROOT / 'scripts/dev'
PWSH = shutil.which('pwsh')
if not PWSH:
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
    PWSH = str(bundled) if bundled.is_file() else None


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows PowerShell 7 required')
class TestWorkflowTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'outputs/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(prefix='bot-workflow-', dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.instance = self.root / 'instance'
        self.instance.mkdir()
        self.db = self.instance / 'monitoring.sqlite3'
        now = datetime.now(timezone.utc)
        repository = MonitoringRepository(self.db)
        service = MonitoringService(repository, device_names={'sim-pond-1': 'Synthetic'}, clock=lambda: now)
        service.ingest(Simulator(start=now-timedelta(seconds=10), session_id='wrapper-test', device_id='sim-pond-1').advance())
        self.access = self.write('access.json', {
            'schema_version': 1, 'app_id': '123456789', 'groups': [{
                'group_id': 'PRIVATE_GROUP_SENTINEL', 'device_id': 'sim-pond-1',
                'members': ['PRIVATE_MEMBER_SENTINEL'], 'capabilities': ['current', 'history', 'events']}]})
        self.source = self.write('monitoring.json', {'schema_version': 1, 'instance_id': 'synthetic-workflow',
            'data_root': str(self.instance), 'devices': ['sim-pond-1']})
        self.ai = self.write('ai.json', {'schema_version': 1, 'enabled': True,
            'preset_id': 'dashscope-qwen38-flash-r1', 'budget': {'max_output_tokens': 512, 'turn_timeout_s': 90},
            'grants': [{'group_id': 'PRIVATE_GROUP_SENTINEL', 'members': ['PRIVATE_MEMBER_SENTINEL'],
                        'device_id': 'sim-pond-1', 'tools': ['get_current_water_quality']}]})
        self.reports = self.root / 'reports'

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def ps(self, *args):
        return subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-NonInteractive', *map(str, args)],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=35)

    def command_args(self):
        return ['-AccessFile', self.access, '-MonitoringConfig', self.source, '-ReportRoot', self.reports]

    def assert_safe(self, output):
        for text in ('PRIVATE_GROUP_SENTINEL', 'PRIVATE_MEMBER_SENTINEL', 'FAKE_KEY_SENTINEL', 'MODEL_TEXT_SENTINEL'):
            self.assertNotIn(text, output)

    def summary(self):
        return json.loads(next(self.reports.glob('test-*/summary.json')).read_text(encoding='utf-8'))

    def test_parse_all_public_scripts_and_helper(self):
        for path in (DEV / 'Test-QQBot.ps1', DEV / 'Test-QwenProvider.ps1', DEV / 'Test-QQAI.ps1',
                     DEV / 'qq_bot_test_common.ps1'):
            with self.subTest(path=path.name):
                result = self.ps('-Command', '$tokens=$null;$errors=$null;'
                    f'[void][System.Management.Automation.Language.Parser]::ParseFile({quoted(path)},[ref]$tokens,[ref]$errors);'
                    'if($errors.Count){exit 1}')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_fixed_check_is_read_only_and_default_offline(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = self.ps('-File', DEV / 'Test-QQBot.ps1', *self.command_args())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = self.summary()
        self.assertEqual(summary['status'], 'CHECK_PASSED_NO_NETWORK')
        self.assertFalse(summary['network_authorized'])
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assert_safe(result.stdout + result.stderr + json.dumps(summary))

    def test_public_provider_dry_run_generates_pending_plan_only(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = self.ps('-File', DEV / 'Test-QwenProvider.ps1', '-DryRun', *self.command_args(),
                         '-AIConfig', self.ai, '-PolicyDirectory', self.root / 'policies')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        summary = self.summary()
        self.assertEqual(summary['status'], 'PLAN_READY_NO_APPROVAL_NO_NETWORK')
        plan = json.loads(Path(summary['plan']).read_text(encoding='utf-8'))
        self.assertEqual(plan['status'], 'pending_operator_approval')
        self.assertFalse(list(self.reports.glob('test-*/approval.json')))
        self.assertFalse(list(self.root.glob('*.used')))
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assert_safe(result.stdout + result.stderr + json.dumps(summary))

    def test_missing_configuration_is_safe_failure(self):
        result = self.ps('-File', DEV / 'Test-QQBot.ps1', '-AccessFile', self.root / 'missing.json',
                         '-MonitoringConfig', self.source, '-ReportRoot', self.reports)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('WORKFLOW_CONFIG_MISSING', result.stdout)
        self.assertFalse(self.reports.exists())

    def test_qq_ai_requires_provider_receipt_and_rejects_fake_receipt(self):
        for report in (None, self.write('not-a-provider-report.json', {'completed': True})):
            with self.subTest(report=report):
                args = ['-File', DEV / 'Test-QQAI.ps1', '-Check', *self.command_args(),
                        '-AIConfig', self.ai, '-PolicyDirectory', self.root / 'policies']
                if report:
                    args.extend(['-ProviderReport', report])
                result = self.ps(*args)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('TRIAL_PROVIDER_PREREQUISITE_REQUIRED', result.stdout)
                self.assert_safe(result.stdout + result.stderr)

    def test_multiple_grants_require_explicit_selection(self):
        value = json.loads(self.ai.read_text())
        value['grants'][0]['members'].append('OTHER_MEMBER')
        self.ai.write_text(json.dumps(value))
        result = self.ps('-File', DEV / 'Test-QwenProvider.ps1', *self.command_args(),
                         '-AIConfig', self.ai, '-PolicyDirectory', self.root / 'policies')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('WORKFLOW_EXPLICIT_GROUP_MEMBER_REQUIRED', result.stdout)

    def test_conflicting_modes_and_external_report_root_rejected(self):
        result = self.ps('-File', DEV / 'Test-QQBot.ps1', '-Run', '-Check', *self.command_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('WORKFLOW_MODE_CONFLICT', result.stdout)
        external = self.root.parent.parent.parent / 'must-not-create-bot-report'
        result = self.ps('-File', DEV / 'Test-QQBot.ps1', '-AccessFile', self.access,
                         '-MonitoringConfig', self.source, '-ReportRoot', external)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('WORKFLOW_REPORT_MUST_BE_IN_PROJECT_OUTPUTS', result.stdout)
        self.assertFalse(external.exists())

    def fake_workflow(self, kind='provider', fail='', confirmation='yes', *, run=True):
        # Override private shell functions in this fresh PowerShell process only.
        # Public scripts expose no bypass/fake-approval parameter.
        script = self.root / 'synthetic-orchestration.ps1'
        calls = self.root / 'calls.json'
        prerequisite = self.write('synthetic-prerequisite.json', {})
        text = r'''
. __COMMON__
$script:commands = [Collections.Generic.List[string]]::new()
$script:confirmations = [Collections.Generic.List[string]]::new()
function Read-Host([string]$Prompt) {
    $script:confirmations.Add($Prompt)
    if (__CONFIRM__ -ceq 'no') { return 'NO' }
    if ($Prompt.Contains('QWEN')) { return 'QWEN' }
    return 'QQ'
}
function Invoke-BotNative([string]$Python,[string[]]$Arguments,[switch]$ApprovalPrompt) {
    $mode = @($Arguments | Where-Object { $_ -in @('--check-config','--check-monitoring','--prepare','--approve','--check','--run-provider','--run-qq','--connect') })[0]
    $script:commands.Add($mode)
    if ($mode -ceq __FAIL__) { return @{ExitCode=1;Record=@{code='TOTAL_TIMEOUT'};Codes=@('TOTAL_TIMEOUT')} }
    $code='OK'; $record=@{code=$code}
    if ($mode -eq '--prepare') {
        $out=$Arguments[[Array]::IndexOf($Arguments,'--output')+1]
        Write-BotJsonNew $out @{scope_sha256=('a'*64);instance_id='synthetic-workflow';device_id='sim-pond-1';expires_at='synthetic-expiry';max_cost_cny='2.00';scope=@{base_scope=@{runtime=@{preset_id='synthetic-qwen';identity=@('dashscope','adapter','https://example.invalid','synthetic-model')}};cost=@{reservation_cny='1.602765'}}}
    }
    if ($mode -eq '--approve') { $record['approval_sha256']='b'*64 }
    if ($mode -in @('--run-provider','--run-qq')) {
        $record=@{code='QWEN_PROVIDER_TRIAL_VERIFIED';completed=$true;model_requests=2;model_text_displayed=$false;
            raw_model_text='MODEL_TEXT_SENTINEL';secret='FAKE_KEY_SENTINEL';usage=@{input_tokens=80;output_tokens=10};
            sdk_resources=@{state='CLOSED';thread_exited=$true;local_io_closed=$true;cleanup_error=$null}}
        if ($mode -eq '--run-qq') {
            $record['delivery']=@(@{state='DELIVERED';api_accepted=$true})
            if (__FAIL__ -eq 'unknown') { $record['delivery']=@(@{state='DELIVERY_UNKNOWN';api_accepted=$false}); $record['completed']=$false }
        }
    }
    return @{ExitCode=0;Record=$record;Codes=@('OK')}
}
$rc=Invoke-BotTestWorkflow -Kind __KIND__ -ProjectRoot __ROOT__ __RUN__ -AccessFile __ACCESS__ -MonitoringConfig __SOURCE__ -AIConfig __AI__ -PolicyDirectory __POLICY__ -ProviderReport __PREREQ__ -ReportRoot __REPORTS__
Write-BotJsonNew __CALLS__ @{commands=$script:commands.ToArray();confirmations=$script:confirmations.ToArray()}
exit $rc
'''
        values = {'COMMON': DEV / 'qq_bot_test_common.ps1', 'CONFIRM': confirmation, 'FAIL': fail,
                  'KIND': kind, 'ROOT': ROOT, 'ACCESS': self.access, 'SOURCE': self.source, 'AI': self.ai,
                  'POLICY': self.root / 'policies', 'PREREQ': prerequisite if kind == 'qqai' else '',
                  'REPORTS': self.reports, 'CALLS': calls}
        for name, value in values.items():
            text = text.replace('__' + name + '__', quoted(value))
        script.write_text(text.replace('__RUN__', '-Run' if run else '-Check'), encoding='utf-8')
        result = self.ps('-File', script)
        trace = json.loads(calls.read_text(encoding='utf-8'))
        return result, trace

    def test_human_cancellation_never_approves_or_runs(self):
        result, trace = self.fake_workflow(confirmation='no')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace['commands'], ['--check-config', '--check-monitoring', '--prepare'])
        self.assertIn('WORKFLOW_OPERATOR_CANCELLED', result.stdout)

    def test_approval_and_recheck_failure_never_runs_provider(self):
        for fail in ('--approve', '--check'):
            with self.subTest(fail=fail):
                result, trace = self.fake_workflow(fail=fail)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('--run-provider', trace['commands'])
                self.assertIn('TOTAL_TIMEOUT', result.stdout)

    def test_provider_success_and_timeout_have_no_qq_or_retry(self):
        result, trace = self.fake_workflow()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(trace['commands'].count('--run-provider'), 1)
        self.assertNotIn('--run-qq', trace['commands'])
        self.assertEqual(len(trace['confirmations']), 1)
        summary = self.summary()
        self.assertEqual(summary['status'], 'PROVIDER_VERIFIED')
        self.assert_safe(result.stdout + result.stderr + json.dumps(summary))
        result, trace = self.fake_workflow(fail='--run-provider')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace['commands'].count('--run-provider'), 1)
        self.assertIn('TOTAL_TIMEOUT', result.stdout)

    def test_qq_ai_separate_confirmation_and_unknown_delivery(self):
        result, trace = self.fake_workflow(kind='qqai', fail='unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace['commands'].count('--run-qq'), 1)
        self.assertNotIn('--run-provider', trace['commands'])
        self.assertEqual(len(trace['confirmations']), 2)
        self.assertIn('WORKFLOW_NOT_COMPLETED_NO_RETRY', result.stdout)
        summary = self.summary()
        self.assertFalse(summary['api_accepted'])
        self.assertFalse(summary['client_display_confirmed'])
        self.assert_safe(result.stdout + result.stderr + json.dumps(summary))

    def test_qq_api_acceptance_is_not_client_display(self):
        result, trace = self.fake_workflow(kind='qqai')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(trace['commands'].count('--run-qq'), 1)
        summary = self.summary()
        self.assertTrue(summary['api_accepted'])
        self.assertFalse(summary['client_display_confirmed'])

    def test_native_capture_is_bounded_and_hides_non_json_diagnostics(self):
        child = self.root / 'synthetic-child.py'
        child.write_text("import json,sys\nprint('FAKE_KEY_SENTINEL',file=sys.stderr)\n"
                         "print(json.dumps({'code':'SYNTHETIC_OK'}))\n", encoding='utf-8')
        result = self.ps('-Command', f'. {quoted(DEV / "qq_bot_test_common.ps1")};'
            f'$r=Invoke-BotNative {quoted(ROOT / ".venv/Scripts/python.exe")} @({quoted(child)});'
            'Write-Host $r.Record.code;exit $r.ExitCode')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SYNTHETIC_OK', result.stdout)
        self.assert_safe(result.stdout + result.stderr)
        child.write_text("print('x'*65537)\n", encoding='utf-8')
        result = self.ps('-Command', f'. {quoted(DEV / "qq_bot_test_common.ps1")};'
            f'try{{Invoke-BotNative {quoted(ROOT / ".venv/Scripts/python.exe")} @({quoted(child)})}}'
            'catch{Write-Host $_.Exception.Message;exit 1}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('WORKFLOW_OUTPUT_LIMIT', result.stdout)


if __name__ == '__main__':
    unittest.main()
