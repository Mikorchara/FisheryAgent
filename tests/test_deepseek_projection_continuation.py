"""One-time DeepSeek continuation guards; temporary fictional reports, no network."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fishery_ai.assistant_qualification import QualificationManifest


PROJECT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
CASES = ('DEEPSEEK-H2F', 'DEEPSEEK-H2-A', 'DEEPSEEK-H2-B', 'DEEPSEEK-H5-A', 'DEEPSEEK-H5-B')
HASHES = {
    'DEEPSEEK-H2-A': '3bd3d342315a53afe82a42cdfb715846eb657b4ecf463420dc9b6cb0d3510a72',
    'DEEPSEEK-H2-B': 'a144baec7d8ed58ef9162342f6f61b2ac83267e3421e0b5db527d94d03db1c0d',
    'DEEPSEEK-H2F': '05a3a3dc1b12b479858c4ca7e569f70c2f6bb38e56a0c6f2e3e3bdcff8274df9',
    'DEEPSEEK-H5-A': '33d42c5cdc9148bd5db2dbe7dcf1971c01c6e0c96a6ea1d3f96c6b27d79598c9',
    'DEEPSEEK-H5-B': '04ab561c4f022dd86a627d6ddb732b8d160c3f1eac5eaf2836f725e852f02f42',
}


def fixed_order():
    order = ['H2F'] * 3
    for pair in range(1, 7):
        arms = ('A', 'B') if pair % 2 else ('B', 'A')
        for case in ('H2', 'H5'):
            order.extend(f'{case}-{arm}' for arm in arms)
    order.extend(['H2F'] * 3)
    return ['DEEPSEEK-' + case for case in order]


class DeepSeekContinuationTests(unittest.TestCase):
    def setUp(self):
        if not POWERSHELL:
            self.skipTest('PowerShell unavailable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'pyproject.toml').write_text('# temporary test workspace', encoding='utf-8')
        scripts = self.root/'scripts'
        scripts.mkdir()
        (scripts/'qualify_assistant_turn.py').write_text('# fake CLI marker', encoding='utf-8')
        env_python = self.root/'.venv/Scripts/python.exe'
        env_python.parent.mkdir(parents=True)
        env_python.write_text('not executed by offline process stub', encoding='utf-8')
        manifests = scripts/'manifests'
        manifests.mkdir()
        for case in CASES:
            (manifests/f'assistant-{case}.json').write_bytes(
                (PROJECT/f'scripts/manifests/assistant-{case}.json').read_bytes())
        self.reports = self.root/'outputs/assistant-qualification/cross-model/deepseek'
        self.reports.mkdir(parents=True)
        (self.reports/'run-order.txt').write_bytes(
            ('\r\n'.join(fixed_order())+'\r\n').encode('utf-8'))
        # The test invokes the actual one-time script and shared path guards, replacing only CLI processes.
        script = (PROJECT/'scripts/run_deepseek_projection_qualification_remaining.ps1').read_text(encoding='utf-8')
        script = script.replace(". (Join-Path $PSScriptRoot 'projection_qualification_runner.ps1')", '')
        script_path = scripts/'continuation-under-test.ps1'
        script_path.write_text(script, encoding='utf-8-sig')
        self.script_path = script_path
        self.write_first_report()

    def report(self, case='DEEPSEEK-H2F', run_id='a'*32, requests=2, identity=None, plan_hash=None):
        identity = identity or {'service_id':'deepseek_api','adapter_id':'openai_chat',
            'base_url':'https://api.deepseek.com','model':'deepseek-flash'}
        # Use the actual manifest contract; never fabricate identical A/B metadata.
        plan = QualificationManifest.from_json(
            PROJECT/f'scripts/manifests/assistant-{case}.json').safe_plan()
        plan['identity'] = identity
        plan['plan_sha256'] = plan_hash or HASHES[case]
        relative = self.relative_report_path(case, run_id)
        target = self.root/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {'run_id':run_id,'plan':plan,'status':'completed' if requests else 'failed',
            'success':bool(requests),'error_code':None if requests else 'CREDENTIAL_FILE_ERROR',
            'request_count':requests,'actual_network_requests':requests,'transport_attempts':requests,
            'requests':[{'provider_observation':{'available':True,'provider_model_matches':True,
                'finish_reason':'tool_calls','tool_call_count':1,'normalized_call_consistent':True,
                'tool_calls_present':True},'normalized':{'calls':[{'function_name':'get_current_water_quality',
                    'call_id_valid':True,'arguments_valid':True}]}} ,
                {'provider_observation':{'finish_reason':'stop','tool_calls_present':False}}][:requests],
            'receipt':{'tool_status':'NO_DATA',
                'observation_query_completed':True},'requirement_satisfied':True,
            'final_answer_present':True,'final_finish_reason':'stop'}
        target.write_text(json.dumps(data), encoding='utf-8')
        return target, data

    @staticmethod
    def relative_report_path(case, run_id):
        if case == 'DEEPSEEK-H2F':
            part = 'h2fresh'
        else:
            _, group, arm = case.split('-')
            part = f'{group.lower()}/{arm.lower()}'
        return f'outputs/assistant-qualification/cross-model/deepseek/{part}/{run_id}.json'

    def write_first_report(self):
        self.first_path, self.first = self.report()

    def add_process_stub(self, scenario='ordinary'):
        expected = '\n'.join(f"    '{case}' = '{HASHES[case]}'" for case in CASES)
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        plans = {case: QualificationManifest.from_json(
            PROJECT/f'scripts/manifests/assistant-{case}.json').safe_plan() for case in CASES}
        setup = f"""
$ErrorActionPreference='Stop'
. {quote(PROJECT/'scripts/projection_qualification_runner.ps1')}
Set-Location -LiteralPath {quote(self.root)}
$FixturePlans=ConvertFrom-Json -InputObject {quote(json.dumps(plans))}
$global:sequence=@(); $global:networkCalls=0; $global:scenario={quote(scenario)}
function Invoke-QualificationProcess {{
  param([string]$Python,[string]$Manifest,[switch]$Network)
  $case=(Split-Path -Leaf $Manifest).Replace('assistant-','').Replace('.json','')
  $hash=$ExpectedHashes[$case]
  $plan=$FixturePlans.PSObject.Properties[$case].Value
  if (-not $Network) {{ return @{{ExitCode=0;Data=@{{dry_run=$true;actual_network_requests=0;plan=$plan}}}} }}
  $global:networkCalls++; $global:sequence += $case
  $id=$global:networkCalls.ToString('x32')
  $code=if ($global:scenario -eq 'security') {{'CREDENTIAL_FILE_ERROR'}} elseif ($global:scenario -eq 'ordinary') {{'ASSISTANT_SOURCE_REQUIREMENT_UNMET'}} else {{$null}}
  $count=if ($code) {{1}} else {{2}}
  $safePath={quote(self.root)}+'/'+(Split-Path -Leaf $Manifest)
  $parts=if ($case -eq 'DEEPSEEK-H2F') {{'h2fresh'}} else {{ $case.Substring(9,2).ToLower()+'/'+$case.Substring($case.Length-1,1).ToLower() }}
  $report='outputs/assistant-qualification/cross-model/deepseek/'+$parts+'/'+$id+'.json'
  $target=Join-Path (Get-Location).Path $report
  New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
  # The preview and report use the same case-specific real safe plan.
  $data=@{{run_id=$id;plan=$plan;status=$(if($code){{'failed'}}else{{'completed'}});success=(!$code);error_code=$code;request_count=$count;actual_network_requests=$count;transport_attempts=$count;requests=@(1..$count|%{{@{{}}}})}}
  $data|ConvertTo-Json -Depth 15|Set-Content -LiteralPath $target -Encoding UTF8
  return @{{ExitCode=$(if($code){{1}}else{{0}});Data=@{{run_id=$id;report=$report;status=$data.status;error_code=$code;actual_network_requests=$count}}}}
}}
$ExpectedHashes=@{{
{expected}
}}
"""
        return setup

    def invoke(self, *, confirm=False, scenario='ordinary', mutate=None, add_zero=False):
        if mutate:
            mutate()
        if add_zero:
            self.report('DEEPSEEK-H2-A','b'*32,requests=0)
        flags = '-ConfirmNetwork' if confirm else ''
        code = self.add_process_stub(scenario) + f"""
$errorCode=$null; $errorMessage=$null
try {{ & {self.script_path} {flags} }} catch {{ $errorMessage=$_.Exception.Message; $errorCode=$errorMessage.Split(':')[0] }}
@{{error=$errorCode;message=$errorMessage;sequence=$global:sequence;network=$global:networkCalls}}|ConvertTo-Json -Compress
"""
        runner = self.root/'invoke-continuation.ps1'
        runner.write_text(code, encoding='utf-8-sig')
        proc = subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
            '-File',str(runner)], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, 'offline PowerShell continuation fixture failed')
        result=json.loads(proc.stdout.strip().splitlines()[-1])
        result['_output']='\n'.join(proc.stdout.strip().splitlines()[:-1])
        return result

    def test_current_audited_state_passes_and_starts_at_second_slot(self):
        result = self.invoke()
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 0)
        self.assertIn('NEXT POSITION: 2/30',result['_output'])
        self.assertIn('FIRST SAMPLE WILL NOT BE RE-RUN',result['_output'])

    def test_no_existing_real_sample_is_rejected(self):
        self.first_path.unlink()
        result = self.invoke()
        self.assertEqual(result['error'], 'QUALIFICATION_EXISTING_SAMPLE_COUNT_INVALID')
        self.assertEqual(result['network'], 0)

    def test_run_order_must_match_preserved_fixed_file(self):
        (self.reports/'run-order.txt').write_text('DEEPSEEK-H2F\n', encoding='utf-8')
        result=self.invoke(confirm=True)
        self.assertEqual(result['error'],'QUALIFICATION_ORDER_CHANGED')
        self.assertEqual(result['network'],0)

    def test_second_existing_real_sample_is_rejected(self):
        self.report('DEEPSEEK-H2-A','b'*32)
        result = self.invoke()
        self.assertEqual(result['error'], 'QUALIFICATION_EXISTING_SAMPLE_COUNT_INVALID')

    def test_existing_case_must_match_first_order_slot(self):
        def change():
            self.first['plan']['case_id']='DEEPSEEK-H2-A'
            self.first['plan']['plan_sha256']=HASHES['DEEPSEEK-H2-A']
            self.first_path.write_text(json.dumps(self.first), encoding='utf-8')
        result = self.invoke(mutate=change)
        self.assertEqual(result['error'], 'QUALIFICATION_REPORT_CASE_PATH_INVALID')
        self.assertEqual(result['network'], 0)

    def test_wrong_plan_and_identity_are_rejected(self):
        for field in ('plan','identity'):
            with self.subTest(field=field):
                if field == 'plan':
                    mutate = lambda: self._mutate_first(lambda d: d['plan'].__setitem__('plan_sha256','0'*64))
                    expected='QUALIFICATION_PLAN_INVALID'
                else:
                    mutate = lambda: self._mutate_identity()
                    expected='QUALIFICATION_IDENTITY_MISMATCH'
                result=self.invoke(mutate=mutate)
                self.assertEqual(result['error'],expected)

    def test_wrong_request_budget_and_report_directory_are_rejected(self):
        self.first['request_count']=1
        self.first_path.write_text(json.dumps(self.first),encoding='utf-8')
        result=self.invoke()
        self.assertEqual(result['error'],'QUALIFICATION_REQUEST_BUDGET_INVALID')
        self.first_path.unlink()
        wrong=self.reports/'h2'/'a'/self.first_path.name
        wrong.parent.mkdir(parents=True,exist_ok=True)
        wrong.write_bytes(json.dumps(self.first).encode('utf-8'))
        result=self.invoke()
        self.assertEqual(result['error'],'QUALIFICATION_REPORT_CASE_PATH_INVALID')

    def _mutate_first(self, callback):
        callback(self.first)
        self.first_path.write_text(json.dumps(self.first),encoding='utf-8')

    def _mutate_identity(self):
        self.first['plan']['plan_sha256']=HASHES['DEEPSEEK-H2F']
        self.first['plan']['identity']['model']='other'
        self.first_path.write_text(json.dumps(self.first),encoding='utf-8')

    def test_duplicate_run_id_and_corrupt_json_are_rejected(self):
        self.report('DEEPSEEK-H2-A','c'*32)
        source=self.reports/'h2'/'a'/('c'*32+'.json')
        duplicate=self.reports/'h2'/'a'/('a'*32+'.json')
        data=json.loads(source.read_text(encoding='utf-8')); data['run_id']='a'*32
        duplicate.write_text(json.dumps(data),encoding='utf-8')
        result=self.invoke()
        self.assertEqual(result['error'],'QUALIFICATION_DUPLICATE_RUN_ID')
        duplicate.unlink()
        corrupt=source; corrupt.write_text('{bad',encoding='utf-8')
        result=self.invoke()
        self.assertEqual(result['error'],'QUALIFICATION_REPORT_INVALID')

    def test_zero_request_report_is_ignored_as_a_schedule_slot(self):
        result=self.invoke(add_zero=True)
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'],0)

    def test_dry_run_makes_no_confirmed_calls(self):
        result=self.invoke()
        self.assertEqual(result['network'],0)
        self.assertIn('DRY RUN ONLY',result['_output'])

    def test_confirmed_execution_runs_exactly_schedule_two_through_thirty(self):
        result=self.invoke(confirm=True)
        self.assertIsNone(result['error'])
        self.assertEqual(result['sequence'],fixed_order()[1:])
        self.assertEqual(len(result['sequence']),29)
        self.assertEqual(result['network'],29)
        self.assertIn('2/30 DEEPSEEK-H2F',result['_output'])
        self.assertIn('30/30 DEEPSEEK-H2F',result['_output'])
        self.assertEqual(len(list(self.reports.rglob('*.json'))),30)

    def test_ordinary_failure_occupies_slot_and_continues(self):
        result=self.invoke(confirm=True,scenario='ordinary')
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['sequence']),29)

    def test_security_error_stops_after_one_slot(self):
        result=self.invoke(confirm=True,scenario='security')
        self.assertEqual(result['error'],'QUALIFICATION_BATCH_STOPPED')
        self.assertEqual(result['sequence'],[fixed_order()[1]])
        self.assertEqual(result['network'],1)

    def test_first_report_bytes_remain_unchanged(self):
        before=self.first_path.read_bytes()
        self.invoke(confirm=True,scenario='security')
        self.assertEqual(self.first_path.read_bytes(),before)

    def test_each_case_uses_its_actual_projection_and_requirement(self):
        for index, case in enumerate(CASES):
            with self.subTest(case=case):
                _, data = self.report(case, f'{index + 100:032x}', requests=0)
                manifest = QualificationManifest.from_json(
                    PROJECT/f'scripts/manifests/assistant-{case}.json')
                self.assertEqual(data['plan'], manifest.safe_plan())
        result = self.invoke()
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 0)

    def test_b_projection_and_h5_auto_reports_are_accepted(self):
        for case in ('DEEPSEEK-H2-B', 'DEEPSEEK-H5-A', 'DEEPSEEK-H5-B'):
            with self.subTest(case=case):
                path, _ = self.report(case, 'e'*32, requests=0)
                result = self.invoke()
                self.assertIsNone(result['error'])
                path.unlink()

    def test_wrong_case_projection_and_requirement_are_rejected(self):
        for case, field, value in (
                ('DEEPSEEK-H2-B', 'projection_id', 'CURRENT_NATIVE'),
                ('DEEPSEEK-H2-A', 'projection_id', 'UNTRUSTED_TRANSCRIPT_V1'),
                ('DEEPSEEK-H5-A', 'source_requirement', 'CURRENT_OBSERVATION_QUERY'),
                ('DEEPSEEK-H5-B', 'source_requirement', 'CURRENT_OBSERVATION_QUERY'),
                ('DEEPSEEK-H2-B', 'source_requirement', 'AUTO')):
            with self.subTest(case=case, field=field):
                path, data = self.report(case, 'f'*32, requests=0)
                data['plan'][field] = value
                path.write_text(json.dumps(data), encoding='utf-8')
                result = self.invoke(confirm=True)
                self.assertEqual(result['error'], 'QUALIFICATION_IDENTITY_MISMATCH')
                self.assertEqual(result['network'], 0)
                path.unlink()

    def test_first_sample_request_evidence_must_match_audited_result(self):
        self.first['requests'][0]['provider_observation']={'available':False}
        self.first_path.write_text(json.dumps(self.first),encoding='utf-8')
        result=self.invoke()
        self.assertEqual(result['error'],'QUALIFICATION_FIRST_SAMPLE_EVIDENCE_INVALID')
        self.assertEqual(result['network'],0)


if __name__ == '__main__':
    unittest.main()
