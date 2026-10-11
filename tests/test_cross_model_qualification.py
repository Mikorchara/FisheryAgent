"""P2D preregistration and runner guards; fictional stores, no real transport."""

from dataclasses import replace
from contextlib import redirect_stdout
import importlib.util
import inspect
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from test_assistant import AssistantFixture, RecordingGateway, FAKE_KEY, QUERY, SCORE, KNOWLEDGE, call, final
from test_assistant_sources import KnowledgeFixture
from fishery_ai.assistant import AssistantContextBuilder, AssistantRequest, SYSTEM_INSTRUCTION, assistant_profile
from fishery_ai.assistant_qualification import (CROSS_MODEL_CASES, CROSS_MODEL_TARGETS, QualificationError,
    QualificationManifest, run_qualification, write_report)
from fishery_ai.assistant_sources import SourceRequirement
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle
from fishery_ai.model_gateway import ModelResponse, ModelToolCall, ProfileRegistry, validate_tool_request
from fishery_ai.model_options import Support, ReasoningMode
from fishery_ai.qualification_adapter import QualificationAdapter
from fishery_ai.qualification_history import HISTORY_TOOLS, qualification_history
from fishery_ai.qualification_projection import ProjectionId, build_projection, tool_schema_hash
from fishery_ai.tools.registry import ToolRegistry
from fishery_ai.web import create_app


PROJECT = Path(__file__).resolve().parents[1]
MODELS = ('DEEPSEEK', 'OLLAMA')
CONDITIONS = ('H2F', 'H2-A', 'H2-B', 'H5-A', 'H5-B')
PLANS = {
    'DEEPSEEK-H2F': '05a3a3dc1b12b479858c4ca7e569f70c2f6bb38e56a0c6f2e3e3bdcff8274df9',
    'DEEPSEEK-H2-A': '3bd3d342315a53afe82a42cdfb715846eb657b4ecf463420dc9b6cb0d3510a72',
    'DEEPSEEK-H2-B': 'a144baec7d8ed58ef9162342f6f61b2ac83267e3421e0b5db527d94d03db1c0d',
    'DEEPSEEK-H5-A': '33d42c5cdc9148bd5db2dbe7dcf1971c01c6e0c96a6ea1d3f96c6b27d79598c9',
    'DEEPSEEK-H5-B': '04ab561c4f022dd86a627d6ddb732b8d160c3f1eac5eaf2836f725e852f02f42',
    'OLLAMA-H2F': '1aaa4f5c3a4dd99a88454e624e1636b7cd84d14c9ae2cc630cc29c0e4c2dd962',
    'OLLAMA-H2-A': '62ce494f4545dcc1db4e22869b1732c3bfd1b92f5a66f2099a3d32e5931b77c3',
    'OLLAMA-H2-B': '689c61641a5e328c1fd71abb632d83c7b03ffec09f7394dfeb7060317babcc64',
    'OLLAMA-H5-A': 'c39308f665d5088504c62c9bb16faa01f1612629d1b888f542adbc7f95b296c5',
    'OLLAMA-H5-B': '9ad18a05f9dfa81fc977c4ea8f4ce5569843ebb45482ee95aaad4368a2e212ab',
}


class CrossModelQualificationTests(AssistantFixture):
    def manifest(self, model='DEEPSEEK', condition='H2-B', **changes):
        manifest = QualificationManifest.from_json(PROJECT / f'scripts/manifests/assistant-{model}-{condition}.json')
        return replace(manifest, **changes)

    def fake_run(self, manifest, gateway, **options):
        registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=KnowledgeFixture())
        credentials = CredentialStore(process_env={'DEEPSEEK_API_KEY': FAKE_KEY})
        return run_qualification(replace(manifest, confirm_network=True), self.root,
            credential_store=credentials, registry=registry, gateway=gateway, **options)

    def test_deepseek_h2fresh_manifest(self):
        manifest = self.manifest(condition='H2F')
        self.assertEqual(manifest.preset_id, 'deepseek-flash-r1')
        self.assertEqual(manifest.history_fixture_id, 'EMPTY')
        self.assertEqual(manifest.source_requirement, SourceRequirement.CURRENT_OBSERVATION_QUERY)

    def test_ollama_h2fresh_manifest(self):
        manifest = self.manifest('OLLAMA', 'H2F')
        self.assertEqual(manifest.preset_id, 'ollama-qwen35-4b-r1')
        self.assertEqual(manifest.history_fixture_id, 'EMPTY')
        self.assertEqual(manifest.projection_id, ProjectionId.CURRENT_NATIVE)

    def test_ten_manifests_and_fixed_plan_hashes(self):
        self.assertEqual(len(CROSS_MODEL_CASES), 10)
        for model in MODELS:
            for condition in CONDITIONS:
                manifest = self.manifest(model, condition)
                self.assertEqual(manifest.safe_plan()['plan_sha256'], PLANS[manifest.case_id])
                self.assertEqual(manifest.exposed_tools, HISTORY_TOOLS)
                self.assertEqual((manifest.max_requests, manifest.max_output_tokens, manifest.retry), (2, 256, 0))
                self.assertFalse(manifest.confirm_network)
                self.assertEqual(manifest.source_requirement,
                    SourceRequirement.AUTO if condition.startswith('H5') else SourceRequirement.CURRENT_OBSERVATION_QUERY)

    def test_all_eighteen_prior_manifest_plan_hashes_unchanged(self):
        expected = {
            'assistant-H0.json':'78b829f8d400448dad7bfc7cc588ff281597a3efb01d5b9a4987eac9260dd1aa',
            'assistant-H1.json':'9be8ccdbf3474b11192f3c16eea2f3d80887f869b2b5232a731f609293f1fbaa',
            'assistant-H2-A.json':'d793ea7e597bc52ce966d877358c59473144e3f5d6e5d4ad85551c9a1daf6a7f',
            'assistant-H2-B.json':'75074ffc507ebac65887cdcc10f0931e3211122463fa3702daee090eee78a3f6',
            'assistant-H2.json':'ba203b54e24187b83d626d5089c54e130cfe43fcb918e6b9412f59e8a382f19b',
            'assistant-H3.json':'59c945e1196d1135149c73ffc136a65564152f32e31a0f1e3c797a53437a0c62',
            'assistant-H4.json':'46be809772c5f6384208ece8bb6a999ea557d33cf1e49c428d1721b410d7b493',
            'assistant-H5-A.json':'d16ae69be0c1d84206e7e70eba9395146baa988f2b8754ba6e6c535235342ef4',
            'assistant-H5-B.json':'c9667e3e59f9d13a3e0fc010b106a8a8074e878ee22c455882fcb5f14c7d6d3a',
            'assistant-H5.json':'44fbd706cf29073c021847d87b206126fafe826ab26f0b079398426962a23305',
            'assistant-H6-A.json':'03ba942052fdeb6e0a1dd60627bdbf1090f9e1585ded3705811ce60ad8c55620',
            'assistant-H6-B.json':'811f4824187dbcddc7c612ebdc76c75a4accc88b0790bb24eff22fd65e1affd6',
            'assistant-H6.json':'c90a8ec82117d89dfde67ce3ae555245a9ce5242b0b13ba391282b94b79bb6a7',
            'assistant-H6F.json':'0195c180988b0090f255a0e68a9a41b54a2aca53419e332f1e2333aeaacce8bb',
            'assistant-Q1.json':'e8df778a1a078cbf2c219cd1e67fa8d680439c87ca6b6cf5242cb76b344020ec',
            'assistant-Q2.json':'14fcbd9fffd83a21276c5c1016e0831fc7748933ffdbca6277321cb680879a4b',
            'assistant-Q3.json':'82502a1fccc5a6af53cf9f184bd20cf6d4aa2134f4284302ab1e60950dc27849',
            'assistant-Q4.json':'3660d5515b3e7d2701a62b176139b40e0b7e8c18ca6e29114f9b9dc1ed041c69',
        }
        for filename, hash_value in expected.items():
            manifest = QualificationManifest.from_json(PROJECT/'scripts/manifests'/filename)
            self.assertEqual(manifest.safe_plan()['plan_sha256'], hash_value)

    def test_cross_case_identity_and_budget_cannot_be_changed(self):
        for model in MODELS:
            for changes in ({'preset_id':'dashscope-qwen38-flash-r1'}, {'question':'changed'},
                    {'exposed_tools':(QUERY,)}, {'history_fixture_id':'EMPTY'},
                    {'projection_id':ProjectionId.CURRENT_NATIVE}, {'source_requirement':SourceRequirement.AUTO},
                    {'max_requests':1}, {'max_output_tokens':255}, {'retry':1}):
                with self.subTest(model=model, changes=changes), self.assertRaises(QualificationError):
                    self.manifest(model, **changes)

    def test_published_profiles_off_normal_tools_and_auth(self):
        credentials = CredentialStore(process_env={'DEEPSEEK_API_KEY': FAKE_KEY})
        for key, target in CROSS_MODEL_TARGETS.items():
            profile = assistant_profile(target.preset_id)
            target.validate(profile)
            self.assertEqual(profile.capabilities.tool_calling, Support.SUPPORTED)
            self.assertEqual(profile.default_reasoning.mode, ReasoningMode.OFF)
            self.assertEqual(profile.default_response_mode, 'normal')
            runtime = ProfileRegistry([profile], credentials).snapshot(profile.profile_id)
            self.assertEqual(runtime.max_retries, 0)
            self.assertEqual(runtime.credential.status.availability, 'NONE_REQUIRED' if key=='ollama' else 'PRESENT')

    def test_profile_identity_contract_protocol_auth_and_capability_drift_fail_closed(self):
        for target in CROSS_MODEL_TARGETS.values():
            profile = assistant_profile(target.preset_id)
            for changes in ({'base_url':'https://fictional.invalid'}, {'model':'other-model'},
                    {'preset_contract_version':'1.0.3'},
                    {'preset_protocol_spec':replace(profile.preset_protocol_spec, version='2')},
                    {'capabilities':replace(profile.capabilities, tool_calling=Support.UNKNOWN)}):
                # A corrupt registry double; real ModelProfile already rejects mismatched capability identity.
                changed = SimpleNamespace(**{**vars(profile), **changes})
                with self.subTest(target=target.preset_id), self.assertRaises(QualificationError):
                    target.validate(changed)

    def test_safe_plan_rechecks_registry_drift_without_credential_resolution(self):
        manifest = self.manifest()
        profile = SimpleNamespace(**{**vars(assistant_profile(manifest.preset_id)), 'model':'other-model'})
        with patch('fishery_ai.assistant_qualification.assistant_profile', return_value=profile), \
                patch('fishery_ai.assistant_qualification._credentials', side_effect=AssertionError('no credential')):
            with self.assertRaises(QualificationError): manifest.safe_plan()

    def test_same_case_model_messages_system_framing_and_schema_are_equal(self):
        registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=KnowledgeFixture())
        for condition in CONDITIONS:
            messages = []
            metadata = []
            manifests = [self.manifest(model, condition) for model in MODELS]
            if condition != 'H2F':
                manifests.append(QualificationManifest.from_json(PROJECT / f'scripts/manifests/assistant-{condition}.json'))
            for manifest in manifests:
                projected = manifest.projection()
                messages.append(projected.context.model_request.messages)
                metadata.append(projected.safe_metadata())
                self.assertEqual(messages[-1][0].content, SYSTEM_INSTRUCTION)
                self.assertEqual(messages[-1][-1].content, manifest.question)
                self.assertEqual(tool_schema_hash(registry.model_definitions()),
                    '2f1c15a25dcfceb5225f52ba544656c08242fed3c6e1b118775f8b37c233a050')
            self.assertTrue(all(m == messages[0] for m in messages))
            self.assertTrue(all(m == metadata[0] for m in metadata))

    def test_native_is_current_builder_and_empty_a_b_parity(self):
        for model in MODELS:
            for condition in ('H2F', 'H2-A', 'H5-A'):
                manifest = self.manifest(model, condition)
                request = AssistantRequest(manifest.preset_id, manifest.question,
                    qualification_history(manifest.history_fixture_id), source_requirement=manifest.source_requirement)
                self.assertEqual(manifest.projection().context, AssistantContextBuilder().build(request))
            request = AssistantRequest(self.manifest(model).preset_id, 'q')
            self.assertEqual(build_projection(request, ProjectionId.CURRENT_NATIVE).context,
                build_projection(request, ProjectionId.UNTRUSTED_TRANSCRIPT_V1).context)

    def test_generic_projection_and_source_contract_contain_no_model_branches(self):
        from fishery_ai import qualification_projection, assistant_sources
        for module in (qualification_projection, assistant_sources):
            source = inspect.getsource(module).lower()
            for forbidden in ('deepseek', 'ollama', 'qwen', 'dashscope'):
                self.assertNotIn(forbidden, source)

    def test_provider_encoding_reuses_same_semantics_budget_and_no_retry(self):
        registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=KnowledgeFixture())
        credentials = CredentialStore(process_env={'DEEPSEEK_API_KEY': FAKE_KEY})
        for model in MODELS:
            manifest = self.manifest(model)
            profile = assistant_profile(manifest.preset_id)
            runtime = ProfileRegistry([profile], credentials).snapshot(profile.profile_id)
            request = replace(manifest.projection().context.model_request, tools=registry.model_definitions(), tool_choice='auto')
            validate_tool_request(request, runtime, streaming=False)
            body = QualificationAdapter(runtime.model, registry, manifest.exposed_tools, 256)._kwargs(request, runtime, stream=False)
            self.assertEqual(body[runtime.protocol_spec.max_output_tokens_field], 256)
            self.assertEqual(body['messages'][0]['content'], SYSTEM_INSTRUCTION)
            self.assertEqual(body['tools'][2]['function']['parameters']['required'], ['query'])
            self.assertEqual(runtime.max_retries, 0)
            self.assertNotIn(FAKE_KEY, json.dumps(body))

    def test_fresh_and_both_observation_arms_use_real_executor_and_no_data_receipt(self):
        for model in MODELS:
            for condition in ('H2F', 'H2-A', 'H2-B'):
                gateway = RecordingGateway(call(), final())
                report = self.fake_run(self.manifest(model, condition), gateway)
                self.assertTrue(report['success'])
                self.assertEqual(report['tool_execution_status'], 'NO_DATA')
                self.assertTrue(report['receipt']['observation_query_completed'])
                self.assertFalse(report['receipt']['has_observation'])
                self.assertTrue(report['requirement_satisfied'])
                self.assertEqual([r.tool_choice for r in gateway.requests], ['auto', 'none'])
                self.assertIs(gateway.runtimes[0], gateway.runtimes[1])
                self.assertEqual(report['request_count'], 2)

    def test_wrong_tool_and_direct_text_cannot_create_query_receipt(self):
        for model in MODELS:
            for replies in ((final('[调用工具 get_current_water_quality]'),),
                    (call(KNOWLEDGE, '{"query":"fictional-query"}'), final())):
                report = self.fake_run(self.manifest(model), RecordingGateway(*replies))
                self.assertFalse(report['receipt']['observation_query_completed'])
                self.assertFalse(report['success'])
                self.assertEqual(report['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')

    def test_h5_does_not_prefetch_in_either_model_or_arm(self):
        with patch.object(self.reader, 'query', side_effect=AssertionError('no prefetch')):
            for model in MODELS:
                for condition in ('H5-A', 'H5-B'):
                    report = self.fake_run(self.manifest(model, condition), RecordingGateway(final()))
                    self.assertTrue(report['success'])
                    self.assertEqual(report['receipt']['sources'], [])
                    self.assertEqual(report['request_count'], 1)

    def test_round_and_call_limits_and_cancellation_unchanged(self):
        multiple = ModelResponse(None, tool_calls=(ModelToolCall('one', QUERY, '{}'),
            ModelToolCall('two', SCORE, '{}')), finish_reason='tool_calls')
        for model in MODELS:
            for responses, expected, count in (((multiple,), 'TOOL_CALL_LIMIT', 1),
                    ((call(), call(), final()), 'TOOL_ROUND_LIMIT', 2)):
                report = self.fake_run(self.manifest(model), RecordingGateway(*responses))
                self.assertEqual(report['error_code'], expected)
                self.assertEqual(report['request_count'], count)
            handle = RequestHandle()
            gateway = RecordingGateway(call(), final(), callback=lambda *args: handle.cancel())
            report = self.fake_run(self.manifest(model), gateway, handle=handle)
            self.assertEqual(report['error_code'], 'USER_CANCELLED')
            self.assertEqual(report['request_count'], 1)

    def test_unconfirmed_never_reads_credentials_or_builds_transport(self):
        with patch('fishery_ai.assistant_qualification._credentials', side_effect=AssertionError('no credentials')), \
                patch('fishery_ai.assistant_qualification.QualificationAdapter', side_effect=AssertionError('no SDK')):
            for model in MODELS:
                report = run_qualification(self.manifest(model), self.root)
                self.assertEqual(report['actual_network_requests'], 0)
                self.assertEqual(report['error_code'], 'NETWORK_CONFIRMATION_REQUIRED')

    def test_output_partition_no_overwrite_and_no_secret_or_payload(self):
        for model in MODELS:
            for condition in CONDITIONS:
                manifest = self.manifest(model, condition)
                gateway = RecordingGateway(call(KNOWLEDGE, '{"query":"fictional-private-query"}'), final('fictional-private-answer'))
                report = self.fake_run(manifest, gateway)
                relative = write_report(self.root, report)
                expected = f'cross-model/{model.lower()}/'+('h2fresh' if condition=='H2F' else condition[:2].lower()+'/'+condition[-1].lower())
                self.assertTrue(relative.startswith(expected+'/'))
                stored = (self.root/'outputs/assistant-qualification'/relative).read_text(encoding='utf-8')
                for forbidden in (manifest.question, FAKE_KEY, 'fictional-private-query', 'fictional-private-answer',
                        'fictional evidence text', SYSTEM_INSTRUCTION, '"water_quality":'):
                    self.assertNotIn(forbidden, stored)
                for turn in qualification_history(manifest.history_fixture_id):
                    self.assertNotIn(turn.assistant, stored)
                with self.assertRaises(QualificationError): write_report(self.root, report)

    def test_output_cannot_relabel_other_model_identity(self):
        report = self.fake_run(self.manifest(), RecordingGateway(final()))
        report['plan']['case_id'] = 'OLLAMA-H2-B'
        with self.assertRaises(QualificationError): write_report(self.root, report)

    def test_output_reparse_boundary_refused(self):
        from types import SimpleNamespace
        folder = self.root/'outputs/assistant-qualification/cross-model'
        folder.mkdir(parents=True)
        original = Path.lstat
        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == folder else info
        report = self.fake_run(self.manifest(), RecordingGateway(final()))
        with patch.object(Path, 'lstat', autospec=True, side_effect=lstat):
            with self.assertRaises(QualificationError): write_report(self.root, report)

    def test_web_cannot_select_projection_or_qualification_case(self):
        with patch('fishery_ai.web.AssistantService') as service:
            app = create_app(trace_path=self.trace, custom_profiles_dir=self.root/'profiles',
                capability_evidence_dir=self.root/'evidence', manual_experiments_dir=self.root/'experiments',
                scenario_templates_dir=self.root/'templates', tool_policy_dir=self.root/'policies',
                credential_store=self.credentials, manual_credential_store=CredentialStore(process_env={}))
            client = app.test_client()
            epoch = client.get('/api/assistant/bootstrap').get_json()['epoch']
            token = client.get('/api/credential-session').get_json()['csrf_token']
            headers = {'Origin':'http://localhost', 'X-CSRF-Token':token}
            for fields in ({'case_id':'DEEPSEEK-H2-B'}, {'projection_id':ProjectionId.UNTRUSTED_TRANSCRIPT_V1.value},
                    {'qualification_model':'ollama'}, {'preset_id':'OLLAMA-H2-B'}):
                response = client.post('/api/assistant/chat', json={'preset_id':'deepseek-flash-r1',
                    'question':'q', 'epoch':epoch, **fields}, headers=headers)
                self.assertEqual(response.status_code, 400)
            service.assert_not_called()


class CrossModelRunnerTests(AssistantFixture):
    def cli_result(self, *, error_code=None, cli_error=False):
        """Real CLI serialization and writer, with execution replaced before any I/O."""
        spec = importlib.util.spec_from_file_location('cross_model_cli', PROJECT/'scripts/qualify_assistant_turn.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        root = self.root/'cli-fixture'
        root.mkdir()
        (root/'pyproject.toml').write_text('# fictional workspace', encoding='utf-8')
        path = root/'manifest.json'
        path.write_bytes((PROJECT/'scripts/manifests/assistant-DEEPSEEK-H2F.json').read_bytes())
        report = {'run_id':'a'*32, 'plan':QualificationManifest.from_json(path).safe_plan(),
            'status':'failed' if error_code else 'completed', 'success':not error_code,
            'error_code':error_code, 'request_count':2, 'actual_network_requests':2, 'transport_attempts':2}
        options = {'side_effect':QualificationError('QUALIFICATION_FAILED')} if cli_error else {'return_value':report}
        with patch.object(cli.Path, 'cwd', return_value=root), patch.object(cli, 'run_qualification', **options) as run, \
                redirect_stdout(StringIO()) as output:
            exit_code = cli.main(['--manifest', str(path), '--confirm-network'])
        self.assertEqual(run.call_count, 1)
        summary = json.loads(output.getvalue())
        if not cli_error:
            self.assertEqual(summary['report'],
                'outputs/assistant-qualification/cross-model/deepseek/h2fresh/'+'a'*32+'.json')
            self.assertEqual(json.loads((root/summary['report']).read_text(encoding='utf-8')), report)
        return {'ExitCode':exit_code, 'Data':summary, 'SafeReport':None if cli_error else report}

    def run_runner(self, model='deepseek', *, confirm=False, scenario='ordinary', existing=None, cli_result=None):
        powershell = shutil.which('powershell') or shutil.which('pwsh')
        if not powershell: self.skipTest('PowerShell unavailable')
        (self.root/'pyproject.toml').write_text('# fictional workspace', encoding='utf-8')
        python = self.root/'.venv/Scripts/python.exe'
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text('never executed: process helper is mocked', encoding='utf-8')
        manifests = self.root/'scripts/manifests'
        manifests.mkdir(parents=True, exist_ok=True)
        for condition in CONDITIONS:
            (manifests/f'assistant-{model.upper()}-{condition}.json').write_text('{}', encoding='utf-8')
        reports = self.root/f'outputs/assistant-qualification/cross-model/{model}'
        if existing is not None:
            reports.mkdir(parents=True, exist_ok=True)
            (reports/'existing.json').write_text(json.dumps({'actual_network_requests':existing}), encoding='utf-8')
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        hashes = '\n'.join(f"{quote(key)}={quote(value)}" for key,value in PLANS.items() if key.startswith(model.upper()))
        fixture_plans = {f'{model.upper()}-{condition}': QualificationManifest.from_json(
            PROJECT/f'scripts/manifests/assistant-{model.upper()}-{condition}.json').safe_plan()
            for condition in CONDITIONS}
        code = f"""
$ErrorActionPreference = 'Stop'
. {quote(PROJECT/'scripts/projection_qualification_runner.ps1')}
Set-Location -LiteralPath {quote(self.root)}
$FixturePlans = ConvertFrom-Json -InputObject {quote(json.dumps(fixture_plans))}
$script:previews = 0; $script:networkCalls = 0; $script:sequence = @()
$script:scenario = {quote(scenario)}
$script:model = {quote(model)}; $script:reportRoot = {quote(reports)}
$script:cliResult = ConvertFrom-Json -InputObject {quote(json.dumps(cli_result))}
function Invoke-QualificationProcess {{
    param([string]$Python, [string]$Manifest, [switch]$Network)
    $caseId = (Split-Path -Leaf $Manifest).Replace('assistant-', '').Replace('.json', '')
    $hash = $ExpectedHashes[$caseId]
    $plan = $FixturePlans.PSObject.Properties[$caseId].Value
    if (-not $Network) {{
        $script:previews++
        if ($script:scenario -eq 'drift') {{ $plan.plan_sha256 = 'changed' }}
        return @{{ExitCode=0;Data=@{{dry_run=$true;actual_network_requests=0;plan=$plan}}}}
    }}
    $script:networkCalls++; $script:sequence += $caseId
    if ($null -ne $script:cliResult -and $script:networkCalls -eq 1) {{
        if ($null -ne $script:cliResult.SafeReport) {{
            $cliPath = Join-Path (Get-Location).Path $script:cliResult.Data.report
            New-Item -ItemType Directory -Path (Split-Path -Parent $cliPath) -Force | Out-Null
            $script:cliResult.SafeReport | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $cliPath -Encoding UTF8
        }}
        return @{{ExitCode=$script:cliResult.ExitCode;Data=$script:cliResult.Data}}
    }}
    $id = $script:networkCalls.ToString('x32')
    $parts = if ($caseId.EndsWith('H2F')) {{ 'h2fresh' }} else {{ $caseId.Substring($caseId.Length-4,2).ToLower()+'/'+$caseId.Substring($caseId.Length-1).ToLower() }}
    $relative = 'cross-model/'+$script:model+'/'+$parts+'/'+$id+'.json'
    $path = Join-Path (Join-Path (Get-Location).Path 'outputs/assistant-qualification') $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
    $errorCode = if ($script:scenario -in @('CREDENTIAL_FILE_ERROR','SECRET_MISSING','QUALIFICATION_UNSAFE_LOGGING','QUALIFICATION_REPORT_ERROR','CONNECTION_ERROR','USER_CANCELLED')) {{ $script:scenario }} else {{ 'ASSISTANT_SOURCE_REQUIREMENT_UNMET' }}
    $count = if ($errorCode -in @('CREDENTIAL_FILE_ERROR','SECRET_MISSING','QUALIFICATION_UNSAFE_LOGGING')) {{ 0 }} else {{ 1 }}
    $safe = @{{run_id=$id;plan=$plan;status='failed';error_code=$errorCode;request_count=$count;actual_network_requests=$count;transport_attempts=$count}}
    if ($script:scenario -eq 'invalid_budget') {{ $safe.request_count = 3 }}
    if ($script:scenario -eq 'invalid_identity') {{ $safe.plan.case_id = 'DEEPSEEK-H5-A' }}
    $safe | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $path -Encoding UTF8
    $report = 'outputs/assistant-qualification/'+$relative
    if ($script:scenario -eq 'old_prefix') {{ $report = $relative }}
    if ($script:scenario -eq 'wrong_model') {{ $report = $report.Replace('/deepseek/', '/ollama/') }}
    if ($script:scenario -eq 'traversal') {{ $report = 'outputs/assistant-qualification/cross-model/'+$script:model+'/../../outside.json' }}
    if ($script:scenario -eq 'missing_report') {{ $report = $null }}
    if ($script:scenario -eq 'missing_file') {{ Remove-Item -LiteralPath $path }}
    if ($script:scenario -eq 'invalid_json') {{ Set-Content -LiteralPath $path -Value '{{broken' -Encoding UTF8 }}
    return @{{ExitCode=1;Data=@{{run_id=$id;report=$report;status='failed';error_code=$errorCode;actual_network_requests=$count}}}}
}}
$hashes = @{{
{hashes}
}}
$errorCode = $null
try {{ Invoke-ProjectionQualificationBatch -ModelKey {quote(model)} -ExpectedHashes $hashes -ProjectRoot {quote(self.root)} {'-ConfirmNetwork' if confirm else ''} }}
catch {{ $errorCode = $_.Exception.Message.Split(':')[0] }}
@{{error=$errorCode;previews=$script:previews;network=$script:networkCalls;sequence=$script:sequence}} | ConvertTo-Json -Compress
"""
        script = self.root/'runner-test.ps1'
        script.write_text(code, encoding='utf-8-sig')
        process = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, 'offline runner fixture failed')
        return json.loads(process.stdout.strip().splitlines()[-1]), reports

    def test_wrapper_syntax_hashes_targets_and_no_other_batch(self):
        for model in ('deepseek','ollama'):
            text = (PROJECT/f'scripts/run_{model}_projection_qualification.ps1').read_text(encoding='utf-8')
            self.assertIn('[switch]$ConfirmNetwork', text)
            self.assertIn(f"-ModelKey '{model}'", text)
            self.assertNotIn(f'run_{"ollama" if model=="deepseek" else "deepseek"}', text)
            for case,hash_value in PLANS.items():
                if case.startswith(model.upper()): self.assertIn(hash_value, text)

    def test_default_prepares_order_without_network(self):
        for model in ('deepseek', 'ollama'):
            result,reports = self.run_runner(model)
            self.assertIsNone(result['error'])
            self.assertEqual((result['previews'],result['network']), (5,0))
            saved = (reports/'run-order.txt').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(saved), 30)
            self.assertEqual(saved[:3]+saved[-3:], [model.upper()+'-H2F']*6)
            for condition in CONDITIONS: self.assertEqual(saved.count(model.upper()+'-'+condition), 6)

    def test_ordinary_failures_continue_once_per_fixed_schedule(self):
        result,reports = self.run_runner(confirm=True)
        self.assertIsNone(result['error'])
        self.assertEqual((result['previews'],result['network']), (35,30))
        self.assertEqual(result['sequence'], (reports/'run-order.txt').read_text(encoding='utf-8').splitlines())

    def test_fresh_batch_accepts_all_five_real_case_contracts(self):
        for model in ('deepseek', 'ollama'):
            with self.subTest(model=model):
                result, reports = self.run_runner(model, confirm=True)
                self.assertIsNone(result['error'])
                self.assertEqual(result['network'], 30)  # Offline process stubs only.
                counts = {}
                for path in reports.rglob('*.json'):
                    plan = json.loads(path.read_text(encoding='utf-8-sig'))['plan']
                    case = plan['case_id']
                    expected = QualificationManifest.from_json(
                        PROJECT/f'scripts/manifests/assistant-{case}.json').safe_plan()
                    self.assertEqual(plan, expected)
                    counts[case] = counts.get(case, 0) + 1
                self.assertEqual(counts, {f'{model.upper()}-{condition}': 6 for condition in CONDITIONS})

    def test_existing_real_sample_blocks_before_processes(self):
        result,_ = self.run_runner(confirm=True, existing=1)
        self.assertEqual(result['error'], 'QUALIFICATION_ALREADY_RUN')
        self.assertEqual((result['previews'],result['network']), (0,0))

    def test_zero_request_preflight_is_not_a_real_sample(self):
        result,_ = self.run_runner(existing=0)
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 0)

    def test_changed_plan_blocks_before_network(self):
        result,_ = self.run_runner(confirm=True, scenario='drift')
        self.assertEqual(result['error'], 'QUALIFICATION_PLAN_CHANGED')
        self.assertEqual(result['network'], 0)

    def test_local_safety_errors_and_cancellation_stop_no_retry(self):
        for error in ('CREDENTIAL_FILE_ERROR','SECRET_MISSING','QUALIFICATION_UNSAFE_LOGGING',
                'QUALIFICATION_REPORT_ERROR','USER_CANCELLED'):
            # Each fixture uses a new model output directory, never reads a real credential.
            if self.root.joinpath('outputs').exists():
                shutil.rmtree(self.root/'outputs')
            result,_ = self.run_runner(confirm=True, scenario=error)
            self.assertIsNotNone(result['error'])
            self.assertEqual(result['network'], 1)

    def test_ollama_transport_unavailable_stops_with_safe_report(self):
        result,reports = self.run_runner('ollama', confirm=True, scenario='CONNECTION_ERROR')
        self.assertEqual(result['error'], 'QUALIFICATION_BATCH_STOPPED')
        self.assertEqual(result['network'], 1)
        self.assertEqual(len(list(reports.rglob('*.json'))), 1)

    def test_mismatched_order_stops_before_network(self):
        reports = self.root/'outputs/assistant-qualification/cross-model/deepseek'
        reports.mkdir(parents=True)
        (reports/'run-order.txt').write_text('DEEPSEEK-H2-B\n', encoding='utf-8')
        result,_ = self.run_runner(confirm=True)
        self.assertEqual(result['error'], 'QUALIFICATION_ORDER_CHANGED')
        self.assertEqual(result['network'], 0)

    def test_completed_real_cli_contract_is_accepted_and_cannot_restart(self):
        fixture = self.cli_result()
        self.assertEqual(fixture['ExitCode'], 0)
        result,reports = self.run_runner(confirm=True, cli_result=fixture)
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 30)  # All process calls are fake.
        report = reports/'h2fresh'/('a'*32+'.json')
        before = report.read_bytes()
        repeated,_ = self.run_runner(confirm=True)
        self.assertEqual(repeated['error'], 'QUALIFICATION_ALREADY_RUN')
        self.assertEqual(repeated['network'], 0)
        self.assertEqual(report.read_bytes(), before)

    def test_failed_provider_real_cli_contract_exit_one_is_accepted(self):
        fixture = self.cli_result(error_code='HTTP_401')
        self.assertEqual(fixture['ExitCode'], 1)
        result,_ = self.run_runner(confirm=True, cli_result=fixture)
        self.assertIsNone(result['error'])
        self.assertEqual(result['network'], 30)

    def test_real_cli_error_exit_two_without_report_stops_once(self):
        fixture = self.cli_result(cli_error=True)
        self.assertEqual(fixture['ExitCode'], 2)
        self.assertNotIn('report', fixture['Data'])
        result,_ = self.run_runner(confirm=True, cli_result=fixture)
        self.assertEqual(result['error'], 'QUALIFICATION_CLI_REPORT_INVALID')
        self.assertEqual(result['network'], 1)

    def test_old_prefix_wrong_model_and_missing_report_stop_once(self):
        for scenario in ('old_prefix', 'wrong_model', 'missing_report'):
            with self.subTest(scenario=scenario):
                if (self.root/'outputs').exists(): shutil.rmtree(self.root/'outputs')
                result,_ = self.run_runner(confirm=True, scenario=scenario)
                self.assertEqual(result['error'], 'QUALIFICATION_CLI_REPORT_INVALID')
                self.assertEqual(result['network'], 1)

    def test_report_traversal_stops_without_reading_outside_boundary(self):
        result,_ = self.run_runner(confirm=True, scenario='traversal')
        self.assertEqual(result['error'], 'QUALIFICATION_REPORT_PATH_INVALID')
        self.assertEqual(result['network'], 1)

    def test_missing_file_and_invalid_report_json_stop_once(self):
        for scenario in ('missing_file', 'invalid_json'):
            with self.subTest(scenario=scenario):
                if (self.root/'outputs').exists(): shutil.rmtree(self.root/'outputs')
                result,_ = self.run_runner(confirm=True, scenario=scenario)
                self.assertEqual(result['error'], 'QUALIFICATION_REPORT_INVALID')
                self.assertEqual(result['network'], 1)

    def test_identity_and_budget_guards_still_stop_once(self):
        for scenario in ('invalid_identity', 'invalid_budget'):
            with self.subTest(scenario=scenario):
                if (self.root/'outputs').exists(): shutil.rmtree(self.root/'outputs')
                result,_ = self.run_runner(confirm=True, scenario=scenario)
                self.assertEqual(result['error'], 'QUALIFICATION_REPORT_IDENTITY_OR_BUDGET_INVALID')
                self.assertEqual(result['network'], 1)

    def test_non_json_process_stdout_is_a_separate_safe_error(self):
        powershell = shutil.which('powershell') or shutil.which('pwsh')
        if not powershell: self.skipTest('PowerShell unavailable')
        scripts = self.root/'scripts'
        scripts.mkdir()
        (scripts/'qualify_assistant_turn.py').write_text("print('not-json')\n", encoding='utf-8')
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        code = f"""
. {quote(PROJECT/'scripts/projection_qualification_runner.ps1')}
Set-Location -LiteralPath {quote(self.root)}
try {{ Invoke-QualificationProcess -Python {quote(sys.executable)} -Manifest 'unused' | Out-Null }}
catch {{ @{{error=$_.Exception.Message.Split(':')[0]}} | ConvertTo-Json -Compress }}
"""
        script = self.root/'invalid-stdout-test.ps1'
        script.write_text(code, encoding='utf-8-sig')
        process = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout.strip())['error'], 'QUALIFICATION_CLI_OUTPUT_INVALID')
