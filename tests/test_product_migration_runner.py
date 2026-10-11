"""Offline process-boundary tests: temporary reports, no credentials or Provider."""
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from fishery_ai.assistant_qualification import QualificationManifest

PROJECT = Path(__file__).resolve().parents[1]
INDEX = PROJECT / 'scripts/manifests/product-migration/qualification-plan.json'
ORDER = json.loads(INDEX.read_text(encoding='utf-8'))['order']
PLANS = {item['case_id']: QualificationManifest.from_json(PROJECT / item['manifest']).safe_plan()
         for item in ORDER}
SCHEMA = '2f1c15a25dcfceb5225f52ba544656c08242fed3c6e1b118775f8b37c233a050'
SYSTEM = '974cc942da1a909ee2f41c74aeb329fbfafe7aacd309aaeff90c9541e2843bc5'


class ProductMigrationRunnerTests(unittest.TestCase):
    def run_runner(self, *, confirm=False, scenario='ordinary', existing=None, index_change=None):
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if not shell:
            self.skipTest('PowerShell unavailable')
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'pyproject.toml').write_text('# fictional workspace', encoding='utf-8')
            python = root/'.venv/Scripts/python.exe'
            python.parent.mkdir(parents=True)
            python.write_text('process is mocked, never executed', encoding='utf-8')
            scripts = root/'scripts'
            folder = scripts/'manifests/product-migration'
            folder.mkdir(parents=True)
            (scripts/'qualify_assistant_turn.py').write_text('# mocked', encoding='utf-8')
            shutil.copyfile(INDEX, folder/INDEX.name)
            for item in ORDER:
                shutil.copyfile(PROJECT/item['manifest'], root/item['manifest'])
            if index_change:
                data = json.loads((folder/INDEX.name).read_text(encoding='utf-8'))
                if index_change == 'missing': data['order'].pop()
                if index_change == 'duplicate': data['order'][1] = data['order'][0]
                if index_change == 'reorder': data['order'][:2] = reversed(data['order'][:2])
                if index_change == 'extra': data['order'].append(data['order'][0])
                (folder/INDEX.name).write_text(json.dumps(data), encoding='utf-8')
            reports = root/'outputs/assistant-qualification/product-migration'
            if existing is not None:
                reports.mkdir(parents=True)
                (reports/'existing.json').write_text(json.dumps({'actual_network_requests': existing}), encoding='utf-8')
            # Replace only two external-process boundaries in the temporary script.
            # Actual frozen manifests/safe plans and all runner guards remain intact.
            runner = (PROJECT/'scripts/run_product_migration_qualification.ps1').read_text(encoding='utf-8')
            runner = runner.replace(". (Join-Path $PSScriptRoot 'projection_qualification_runner.ps1')", '')
            runner = runner.replace('$conditions = Invoke-P2EConditions $python', '$conditions = $global:fixtureConditions')
            (scripts/'under-test.ps1').write_text(runner, encoding='utf-8-sig')
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            driver = f"""
$ErrorActionPreference = 'Stop'
. {quote(PROJECT/'scripts/projection_qualification_runner.ps1')}
Set-Location -LiteralPath {quote(root)}
$global:fixtureConditions = @{{schema={quote(SCHEMA)};system={quote(SYSTEM)}}}
$global:fixturePlans = ConvertFrom-Json -InputObject {quote(json.dumps(PLANS))}
$global:previews=0; $global:networkCalls=0; $global:sequence=@()
$global:scenario={quote(scenario)}
if ($global:scenario -eq 'schema') {{ $global:fixtureConditions.schema='changed' }}
if ($global:scenario -eq 'system') {{ $global:fixtureConditions.system='changed' }}
function Invoke-QualificationProcess {{
    param([string]$Python,[string]$Manifest,[switch]$Network)
    $case=(Split-Path -Leaf $Manifest).Replace('assistant-','').Replace('.json','')
    $plan=$global:fixturePlans.PSObject.Properties[$case].Value | ConvertTo-Json -Depth 40 | ConvertFrom-Json
    if (-not $Network) {{
        $global:previews++
        if ($global:scenario -eq 'drift') {{ $plan.plan_sha256='changed' }}
        if ($global:scenario -eq 'case') {{ $plan.case_id='wrong' }}
        return @{{ExitCode=0;Data=@{{dry_run=$true;actual_network_requests=0;plan=$plan}}}}
    }}
    $global:networkCalls++; $global:sequence += $case
    $id=$global:networkCalls.ToString('x32')
    $parts=$case.Split('-')
    $relative='outputs/assistant-qualification/product-migration/'+$parts[1].ToLower()+'/'+$parts[2].ToLower()+'/'+$parts[3].ToLower()+'/'+$id+'.json'
    $path=Join-Path (Get-Location).Path $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
    $plan.network='AUTHORIZED_FOR_THIS_RUN'
    $errorCode='ASSISTANT_SOURCE_REQUIREMENT_UNMET'
    if ($global:scenario -in @('CREDENTIAL_FILE_ERROR','SECRET_MISSING','QUALIFICATION_REPORT_ERROR','USER_CANCELLED','CONNECTION_ERROR','READ_TIMEOUT','HTTP_401')) {{ $errorCode=$global:scenario }}
    if ($global:scenario -eq 'behavior') {{ $errorCode='TOOL_CALL_LIMIT' }}
    $success=$global:scenario -eq 'completed'
    if ($success) {{ $errorCode=$null }}
    $count=if ($errorCode -in @('CREDENTIAL_FILE_ERROR','SECRET_MISSING')) {{ 0 }} elseif ($success) {{ 2 }} else {{ 1 }}
    $rows=@()
    for ($i=1;$i -le $count;$i++) {{
        $rows+=@{{request_number=$i;tool_schema_sha256={quote(SCHEMA)};tool_definitions=@($plan.exposed_tools);knowledge_schema_required_query=$true;
            tool_choice=$(if ($i -eq 1) {{'auto'}} else {{'none'}});
            provider_observation=@{{provider_model_matches=$true;normalized_call_consistent=$true;normalized_metadata_consistent=$true}};
            normalized=@{{provider_model_matches=$true}}}}
    }}
    $safe=@{{run_id=$id;plan=$plan;status=$(if($success){{'completed'}}else{{'failed'}});success=$success;error_code=$errorCode;request_count=$count;actual_network_requests=$count;transport_attempts=$count;requests=$rows}}
    if ($global:scenario -eq 'identity') {{ $safe.plan.identity.model='wrong-model' }}
    if ($global:scenario -eq 'budget') {{ $safe.request_count=3 }}
    if ($global:scenario -eq 'inconsistency') {{ $safe.requests[0].provider_observation.normalized_call_consistent=$false }}
    if ($global:scenario -eq 'provider_model') {{ $safe.requests[0].provider_observation.provider_model_matches=$false }}
    $safe | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $path -Encoding UTF8
    if ($global:scenario -eq 'corrupt') {{ Set-Content -LiteralPath $path -Value '{{broken' }}
    if ($global:scenario -eq 'missing_file') {{ Remove-Item -LiteralPath $path }}
    if ($global:scenario -eq 'extra_report') {{ Copy-Item -LiteralPath $path -Destination (Join-Path (Split-Path -Parent $path) ('f'*32+'.json')) }}
    if ($global:scenario -eq 'old_prefix') {{ $relative=$relative.Replace('outputs/assistant-qualification/','') }}
    if ($global:scenario -eq 'wrong_model') {{ $relative=$relative.Replace('/qwen/','/deepseek/') }}
    if ($global:scenario -eq 'wrong_scenario') {{ $relative=$relative.Replace('/s1/','/s7/') }}
    if ($global:scenario -eq 'wrong_arm') {{ $relative=$relative.Replace('/a/','/b/') }}
    if ($global:scenario -eq 'traversal') {{ $relative='../../outside.json' }}
    if ($global:scenario -eq 'absolute') {{ $relative=$path }}
    if ($global:scenario -eq 'missing_report') {{ $relative=$null }}
    return @{{ExitCode=$(if($success){{0}}else{{1}});Data=@{{run_id=$id;report=$relative;status=$safe.status;success=$success;error_code=$errorCode;request_count=$count;actual_network_requests=$count}}}}
}}
$errorCode=$null
try {{ & {quote(scripts/'under-test.ps1')} {'-ConfirmNetwork' if confirm else ''} }}
catch {{ $errorCode=$_.Exception.Message.Split(':')[0] }}
@{{error=$errorCode;previews=$global:previews;network=$global:networkCalls;sequence=$global:sequence}} | ConvertTo-Json -Compress
"""
            entry = root/'driver.ps1'
            entry.write_text(driver, encoding='utf-8-sig')
            process = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                      '-File', str(entry)], capture_output=True, text=True, timeout=120)
            self.assertEqual(process.returncode, 0, 'offline fixture must complete')
            return json.loads(process.stdout.strip().splitlines()[-1])

    def test_default_all_thirty_dry_runs_no_provider(self):
        result = self.run_runner()
        self.assertIsNone(result['error'])
        self.assertEqual((result['previews'], result['network']), (30, 0))

    def test_source_failure_keeps_fixed_slots_no_retry_or_sample31(self):
        result = self.run_runner(confirm=True)
        self.assertIsNone(result['error'])
        self.assertEqual((result['previews'], result['network']), (60, 30))
        self.assertEqual(result['sequence'], [item['case_id'] for item in ORDER])

    def test_completed_two_request_report_contract(self):
        result = self.run_runner(confirm=True, scenario='completed')
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 30)

    def test_classified_model_behavior_failure_continues(self):
        result = self.run_runner(confirm=True, scenario='behavior')
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 30)

    def test_missing_duplicate_reordered_extra_positions_fail_closed(self):
        for change in ('missing', 'duplicate', 'reorder', 'extra'):
            with self.subTest(change=change):
                result = self.run_runner(confirm=True, index_change=change)
                self.assertEqual(result['error'], 'QUALIFICATION_INDEX_CHANGED')
                self.assertEqual(result['network'], 0)

    def test_plan_hash_and_case_drift_prevent_network(self):
        for scenario in ('drift', 'case'):
            result = self.run_runner(confirm=True, scenario=scenario)
            self.assertEqual(result['error'], 'QUALIFICATION_PLAN_CHANGED')
            self.assertEqual(result['network'], 0)

    def test_schema_and_system_drift_prevent_network(self):
        for scenario in ('schema', 'system'):
            result = self.run_runner(confirm=True, scenario=scenario)
            self.assertEqual(result['error'], 'QUALIFICATION_CONDITIONS_CHANGED')
            self.assertEqual(result['network'], 0)

    def test_existing_real_report_prevents_restart(self):
        result = self.run_runner(confirm=True, existing=1)
        self.assertEqual(result['error'], 'QUALIFICATION_ALREADY_RUN')
        self.assertEqual(result['network'], 0)

    def test_zero_request_preflight_is_not_real_sample(self):
        result = self.run_runner(existing=0)
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 0)

    def test_safety_credential_transport_and_cancel_stop_once(self):
        for scenario in ('CREDENTIAL_FILE_ERROR','SECRET_MISSING','QUALIFICATION_REPORT_ERROR',
                         'USER_CANCELLED','CONNECTION_ERROR','READ_TIMEOUT','HTTP_401'):
            with self.subTest(scenario=scenario):
                result = self.run_runner(confirm=True, scenario=scenario)
                self.assertEqual(result['error'], 'QUALIFICATION_BATCH_STOPPED')
                self.assertEqual(result['network'], 1)

    def test_report_partition_and_relative_path_contract(self):
        for scenario in ('old_prefix','wrong_model','wrong_scenario','wrong_arm','traversal','absolute','missing_report'):
            with self.subTest(scenario=scenario):
                result = self.run_runner(confirm=True, scenario=scenario)
                self.assertEqual(result['error'], 'QUALIFICATION_CLI_REPORT_INVALID')
                self.assertEqual(result['network'], 1)

    def test_corrupt_or_missing_report_stops_once(self):
        for scenario in ('corrupt','missing_file'):
            result = self.run_runner(confirm=True, scenario=scenario)
            self.assertEqual(result['error'], 'QUALIFICATION_REPORT_INVALID')
            self.assertEqual(result['network'], 1)

    def test_exact_identity_and_budget_enforced(self):
        for scenario, error in (('identity','QUALIFICATION_IDENTITY_MISMATCH'),
                                ('budget','QUALIFICATION_REPORT_IDENTITY_OR_BUDGET_INVALID')):
            result = self.run_runner(confirm=True, scenario=scenario)
            self.assertEqual(result['error'], error)
            self.assertEqual(result['network'], 1)

    def test_provider_model_and_normalization_consistency(self):
        for scenario in ('provider_model','inconsistency'):
            result = self.run_runner(confirm=True, scenario=scenario)
            self.assertEqual(result['error'], 'QUALIFICATION_PROVIDER_IDENTITY_OR_PROTOCOL_INVALID')
            self.assertEqual(result['network'], 1)

    def test_unexpected_extra_report_stops_once(self):
        result = self.run_runner(confirm=True, scenario='extra_report')
        self.assertEqual(result['error'], 'QUALIFICATION_UNEXPECTED_OUTPUT')
        self.assertEqual(result['network'], 1)

    def test_single_shared_runner_frozen_product_boundaries(self):
        text = (PROJECT/'scripts/run_product_migration_qualification.ps1').read_text(encoding='utf-8')
        self.assertEqual(text.count('Invoke-QualificationProcess -Python $python -Manifest $item.manifest -Network'), 1)
        for forbidden in ('load_dotenv','os.environ','Set-Acl','Start-Process','pull ',
                          'SYSTEM_INSTRUCTION =','SourceRequirement(', 'Set-Content'):
            self.assertNotIn(forbidden, text)
        self.assertNotIn('P2E-QWEN-S1-A', text)  # Order is not duplicated in PowerShell.
