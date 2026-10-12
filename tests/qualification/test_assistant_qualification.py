"""Long-lived qualification safety: bounded requests, fake SDK and safe reports."""

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import importlib.util
from io import StringIO
import json
from pathlib import Path
import threading
from types import SimpleNamespace as NS
from unittest.mock import patch

from tests.assistant.test_assistant import (AssistantFixture, FakeKnowledgeService, RecordingGateway,
                           QUERY, SCORE, KNOWLEDGE, LOCAL, FAKE_KEY, call, final)
from tests.assistant.test_assistant_sources import KnowledgeFixture
import tests.security.test_execution as test_execution
from fishery_ai.assistant import AssistantError, AssistantRequest, assistant_profile
from fishery_ai.development.qualification.assistant_qualification import (QualificationError, QualificationManifest,
    run_qualification, write_report)
from fishery_ai.assistant_sources import SourceRequirement as Requirement
from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.credentials import CredentialFileError, CredentialStore
from fishery_ai.execution import RequestHandle
from fishery_ai.model_gateway import GatewayError, ModelResponse, ModelToolCall, ProfileRegistry
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.development.qualification.qualification_adapter import QualificationAdapter
from fishery_ai.tools.registry import ToolRegistry
from fishery_ai.domain import DiagnosisService


from tests.support.paths import PROJECT_ROOT
PROJECT = PROJECT_ROOT


class QualificationTests(AssistantFixture):
    def manifest(self, tools=(QUERY,), requirement=Requirement.AUTO, **changes):
        return QualificationManifest(LOCAL, "fictional question never in report", tools,
            source_requirement=requirement, confirm_network=True, **changes)

    def run_fake(self, manifest, gateway, **options):
        return run_qualification(manifest, self.root, credential_store=self.credentials,
            registry=self.registry, gateway=gateway, **options)

    def test_dry_plan_and_no_confirmation_never_compose_or_resolve(self):
        manifest = replace(self.manifest(), confirm_network=False)
        with patch("fishery_ai.development.qualification.assistant_qualification._credentials", side_effect=AssertionError("no credentials")), \
             patch("fishery_ai.development.qualification.assistant_qualification._registry", side_effect=AssertionError("no handler")), \
             patch("fishery_ai.development.qualification.assistant_qualification.QualificationAdapter", side_effect=AssertionError("no SDK")):
            self.assertEqual(manifest.safe_plan()["network"], "NOT_YET_AUTHORIZED")
            report = run_qualification(manifest, self.root)
        self.assertEqual(report["actual_network_requests"], 0)
        self.assertEqual(report["request_count"], 0)
        self.assertEqual(report["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        self.assertFalse((self.root / "outputs").exists())

    def test_qualification_composition_binds_one_knowledge_service(self):
        from fishery_ai.development.qualification.assistant_qualification import _registry
        service = FakeKnowledgeService()
        with patch("fishery_ai.development.qualification.assistant_qualification.KnowledgeService", return_value=service) as factory:
            registry = _registry()
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(registry.registered_names(), tuple(item.name for item in registry.model_definitions()))
        self.assertIs(registry.lookup(KNOWLEDGE).handler.keywords["service"], service)

    def test_manifest_rejects_unbounded_or_ambiguous_inputs(self):
        for changes in ({"max_requests":0}, {"max_requests":3}, {"max_requests":True},
                        {"max_output_tokens":0}, {"max_output_tokens":257}, {"max_output_tokens":True},
                        {"retry":1}, {"retry":False}, {"history":[{}]}, {"confirm_network":"yes"},
                        {"source_requirement":"AUTO"}, {"exposed_tools":[QUERY,QUERY]}, {"case_id":"../escape"}):
            with self.subTest(changes=changes), self.assertRaises(QualificationError):
                replace(self.manifest(), **changes)

    def test_non_whitelist_preset_and_tool_rejected(self):
        for preset in ("DS_1", "mock", "unpublished", LOCAL+"-on"):
            with self.assertRaises(QualificationError):
                replace(self.manifest(), preset_id=preset)
        for name in ("shell", "apply_scenario", "secret", "new_tool"):
            with self.assertRaises(QualificationError):
                self.manifest((name,))

    def test_manifest_cannot_set_connection_prompt_or_persistent_consent(self):
        base = {"preset_id":LOCAL, "question":"q", "exposed_tools":[QUERY]}
        for field in ("base_url", "credential_path", "model", "credential_ref", "system", "policy", "registry", "api_key"):
            with self.subTest(field=field), self.assertRaises(QualificationError):
                QualificationManifest.from_dict({**base, field:"fictional-private-value"})
        with self.assertRaises(QualificationError):
            QualificationManifest.from_dict({**base, "confirm_network":True})

    def test_duplicate_keys_oversized_and_malformed_manifest_fail_closed(self):
        path = self.root / "manifest.json"
        for text in ('{"preset_id":"a","preset_id":"b"}', "{", "a"*8193):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(QualificationError):
                QualificationManifest.from_json(path)

    def test_web_does_not_gain_internal_requirement_or_manifest_fields(self):
        for field in ("source_requirement", "max_requests", "exposed_tools", "confirm_network"):
            with self.assertRaises(AssistantError):
                AssistantRequest.from_dict({"preset_id":LOCAL,"question":"q",field:"forged"})

    def test_credential_error_no_gateway_no_fallback(self):
        credentials = CredentialStore(process_env={})
        with patch.object(credentials, "resolve", side_effect=CredentialFileError()) as resolve, \
             patch("fishery_ai.development.qualification.assistant_qualification.QualificationAdapter", side_effect=AssertionError("no gateway")), \
             patch("fishery_ai.development.qualification.assistant_qualification._registry", side_effect=AssertionError("no registry")):
            report = run_qualification(self.manifest(), self.root, credential_store=credentials)
        self.assertEqual(report["error_code"], "CREDENTIAL_FILE_ERROR")
        self.assertEqual(report["request_count"], 0)
        self.assertEqual(report["transport_attempts"], 0)
        self.assertEqual(resolve.call_count, 1)

    def test_private_composition_uses_existing_location_without_legacy_read(self):
        location = NS(env_path=self.root / "private" / "credentials.env")
        # A real legacy file is forbidden to read even in this temporary fixture.
        (self.root / ".env").write_text("DASHSCOPE_API_KEY=fictional-legacy\n", encoding="utf-8")
        with patch("fishery_ai.development.qualification.assistant_qualification.private_project_location", return_value=location) as paths, \
             patch("fishery_ai.development.qualification.assistant_qualification.CredentialStore", return_value=self.credentials) as store:
            report = run_qualification(self.manifest(), self.root, registry=self.registry,
                                       gateway=RecordingGateway(final()))
        self.assertTrue(report["success"])
        paths.assert_called_once_with(self.root)
        store.assert_called_once_with(location.env_path, private_location=location)
        self.assertEqual((self.root/".env").read_text(encoding="utf-8"), "DASHSCOPE_API_KEY=fictional-legacy\n")

    def test_injected_temporary_private_store_preserves_process_priority(self):
        path=self.root/"private.env"
        path.write_text("DASHSCOPE_API_KEY=fictional-private-key\n",encoding="utf-8")
        for process,expected in (({},"PROJECT_ENV"),({"DASHSCOPE_API_KEY":"fictional-process-key"},"PROCESS_ENV")):
            credentials=CredentialStore(path,process_env=process)
            gateway=RecordingGateway(final())
            manifest=replace(self.manifest(),preset_id="dashscope-qwen38-flash-r1")
            report=run_qualification(manifest,self.root,credential_store=credentials,registry=self.registry,gateway=gateway)
            self.assertTrue(report["success"])
            self.assertEqual(gateway.runtimes[0].credential.status.source,expected)
            self.assertNotIn("fictional-private-key",json.dumps(report))
            self.assertNotIn("fictional-process-key",json.dumps(report))

    def test_cloud_missing_credential_is_zero_request(self):
        manifest = replace(self.manifest(), preset_id="dashscope-qwen38-flash-r1")
        report = self.run_fake(manifest, RecordingGateway(final()))
        self.assertEqual(report["error_code"], "SECRET_MISSING")
        self.assertEqual(report["request_count"], 0)

    def test_sdk_debug_logging_fails_before_credentials_or_request(self):
        with patch("fishery_ai.development.qualification.assistant_qualification.logging.getLogger") as logger, \
             patch.object(self.credentials,"resolve",side_effect=AssertionError("no credential read")):
            logger.return_value.isEnabledFor.return_value=True
            report=self.run_fake(self.manifest(),RecordingGateway(final()))
        self.assertEqual(report["error_code"],"QUALIFICATION_UNSAFE_LOGGING")
        self.assertEqual(report["actual_network_requests"],0)

    def test_auto_direct_answer_uses_one_request_and_no_tool(self):
        gateway = RecordingGateway(final("fictional answer"))
        with patch.object(self.reader, "query", side_effect=AssertionError("no prefetch")):
            report = self.run_fake(self.manifest(max_requests=1), gateway)
        self.assertTrue(report["success"])
        self.assertEqual(report["request_count"], 1)
        self.assertEqual(report["receipt"]["sources"], [])
        self.assertIsNone(report["tool_execution_status"])
        self.assertFalse(report["requests"][0]["provider_observation"]["available"])

    def test_no_tool_non_auto_fails_commit_without_retry(self):
        report = self.run_fake(self.manifest(requirement=Requirement.CURRENT_OBSERVATION_QUERY),
                               RecordingGateway(final("invented claim")))
        self.assertFalse(report["success"])
        self.assertFalse(report["requirement_satisfied"])
        self.assertEqual(report["error_code"], "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertEqual(report["request_count"], 1)

    def test_one_request_call_stops_before_handler_or_second_request(self):
        gateway = RecordingGateway(replace(call(),usage=Usage(3,2,5,source=UsageSource.PROVIDER)), final())
        with patch.object(self.reader, "query", side_effect=AssertionError("no budget for Tool")):
            report = self.run_fake(self.manifest(max_requests=1), gateway)
        self.assertEqual(report["request_count"], 1)
        self.assertEqual(report["error_code"], "QUALIFICATION_REQUEST_LIMIT")
        self.assertEqual(report["receipt"]["sources"], [])
        self.assertEqual(report["requests"][0]["normalized"]["tool_call_count"], 1)
        self.assertEqual(report["usage"]["usage"]["total_tokens"],5)

    def test_current_receipt_two_requests_same_snapshot_retry_zero(self):
        self.store.set_current(self.reading())
        gateway = RecordingGateway(call(), final())
        report = self.run_fake(self.manifest(requirement=Requirement.CURRENT_OBSERVATION_QUERY), gateway)
        self.assertTrue(report["success"])
        self.assertEqual(report["request_count"], 2)
        self.assertEqual(report["tool_execution_status"], "OK")
        self.assertTrue(report["receipt"]["has_observation"])
        self.assertEqual([r.tool_choice for r in gateway.requests], ["auto","none"])
        self.assertIs(gateway.runtimes[0], gateway.runtimes[1])
        self.assertEqual(gateway.runtimes[0].max_retries, 0)
        self.assertEqual(len(gateway.requests[0].messages), 2)

    def test_no_data_query_and_score_complete_operation_without_payload(self):
        for name, requirement in ((QUERY, Requirement.CURRENT_OBSERVATION_QUERY),
                                  (SCORE, Requirement.CURRENT_SCORE_EVALUATION)):
            report = self.run_fake(self.manifest((name,), requirement), RecordingGateway(call(name),final()))
            self.assertTrue(report["success"])
            self.assertEqual(report["tool_execution_status"], "NO_DATA")
            self.assertFalse(report["receipt"]["has_observation"])
            self.assertFalse(report["receipt"]["has_score"])

    def test_score_receipt_and_safe_report_no_score_value(self):
        self.store.set_current(self.reading())
        report = self.run_fake(self.manifest((SCORE,), Requirement.CURRENT_SCORE_EVALUATION),
                               RecordingGateway(call(SCORE),final()))
        self.assertTrue(report["receipt"]["has_score"])
        self.assertNotIn('"score":', json.dumps(report))
        self.assertNotIn('"water_quality":', json.dumps(report))

    def test_knowledge_ok_and_no_match_never_save_query_or_evidence(self):
        for knowledge, expected in ((KnowledgeFixture(),True),(FakeKnowledgeService(),False)):
            self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=knowledge)
            report = self.run_fake(self.manifest((KNOWLEDGE,), Requirement.PROJECT_KNOWLEDGE_SEARCH),
                RecordingGateway(call(KNOWLEDGE,'{"query":"fictional-private-query"}'),final("fictional raw final")))
            self.assertTrue(report["success"])
            self.assertEqual(report["receipt"]["has_project_evidence"],expected)
            self.assertTrue(report["receipt"]["project_search_completed"])
            self.assertNotIn("fictional-private-query", json.dumps(report))
            self.assertNotIn("fictional evidence text", json.dumps(report))
            args = report["requests"][0]["normalized"]["calls"][0]
            self.assertTrue(args["query_present"])
            self.assertTrue(args["query_valid"])

    def test_imitation_is_no_protocol_call_and_no_receipt(self):
        report = self.run_fake(self.manifest((KNOWLEDGE,), Requirement.PROJECT_KNOWLEDGE_SEARCH),
                               RecordingGateway(final("[调用工具 search_fishery_knowledge ...]")))
        # Registry must bind Knowledge before the request; test it with a service.
        self.assertFalse(report["success"])
        self.assertEqual(report["request_count"], 0)  # Unbound Tool fails closed before Gateway.
        self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=FakeKnowledgeService())
        report = self.run_fake(self.manifest((KNOWLEDGE,), Requirement.PROJECT_KNOWLEDGE_SEARCH),
                               RecordingGateway(final("[调用工具 search_fishery_knowledge ...]")))
        self.assertEqual(report["request_count"], 1)
        self.assertFalse(report["requests"][0]["normalized"]["tool_calls_present"])
        self.assertFalse(report["receipt"]["project_search_completed"])

    def test_multiple_and_second_round_tool_calls_fail_closed(self):
        multiple = ModelResponse(None, tool_calls=(ModelToolCall("a",QUERY,"{}"),ModelToolCall("b",SCORE,"{}")),finish_reason="tool_calls")
        with patch.object(self.reader,"query",side_effect=AssertionError("do not run multiple")):
            report = self.run_fake(self.manifest((QUERY,SCORE)), RecordingGateway(multiple))
        self.assertEqual(report["error_code"], "TOOL_CALL_LIMIT")
        self.assertEqual(report["request_count"],1)
        report = self.run_fake(self.manifest(),RecordingGateway(call(),call()))
        self.assertEqual(report["error_code"], "TOOL_ROUND_LIMIT")
        self.assertEqual(report["request_count"],2)

    def test_wrong_tool_and_invalid_arguments_never_grant_requirement(self):
        for response, expected in ((call(SCORE),"TOOL_NOT_ALLOWED"), (call(QUERY,'{"extra":1}'),"INVALID_TOOL_ARGUMENTS")):
            with patch.object(self.reader,"query",side_effect=AssertionError("must not read")):
                report = self.run_fake(self.manifest(requirement=Requirement.CURRENT_OBSERVATION_QUERY),RecordingGateway(response))
            self.assertEqual(report["error_code"],expected)
            self.assertEqual(report["request_count"],1)
            self.assertFalse(report["requirement_satisfied"])

    def test_cancel_before_request_and_after_tool_never_send_followup(self):
        handle=RequestHandle(); handle.cancel()
        report=self.run_fake(self.manifest(),RecordingGateway(final()),handle=handle)
        self.assertEqual(report["error_code"],"USER_CANCELLED")
        self.assertEqual(report["request_count"],0)
        handle=RequestHandle()
        original=self.reader.query
        def cancel_read():
            value=original(); handle.cancel(); return value
        with patch.object(self.reader,"query",side_effect=cancel_read):
            report=self.run_fake(self.manifest(),RecordingGateway(call(),final()),handle=handle)
        self.assertEqual(report["error_code"],"USER_CANCELLED")
        self.assertEqual(report["request_count"],1)
        self.assertFalse(report["success"])

    def test_provider_error_is_single_attempt_and_safe_unknown_exception(self):
        for code in ("READ_TIMEOUT","HTTP_401","HTTP_429","PRIVATE_DETAILS_MUST_NOT_ESCAPE"):
            def fail(*_): raise GatewayError(code)
            report=self.run_fake(self.manifest(),RecordingGateway(final(),callback=fail))
            self.assertEqual(report["request_count"],1)
            self.assertEqual(report["error_code"],code if code != "PRIVATE_DETAILS_MUST_NOT_ESCAPE" else "QUALIFICATION_FAILED")
            self.assertNotIn("PRIVATE_DETAILS_MUST_NOT_ESCAPE",json.dumps(report))

    def test_unknown_finish_reason_is_not_copied_into_report(self):
        response = replace(final(), finish_reason="fictional-private-finish-reason")
        report = self.run_fake(self.manifest(), RecordingGateway(response))
        self.assertEqual(report["error_code"], "ASSISTANT_RESPONSE_INCOMPLETE")
        self.assertIsNone(report["final_finish_reason"])
        self.assertNotIn("fictional-private-finish-reason", json.dumps(report))

    def test_returned_model_mismatch_blocks_handler(self):
        response=replace(call(),returned_model="fictional-secret-as-model")
        report=self.run_fake(self.manifest(),RecordingGateway(response))
        self.assertEqual(report["error_code"],"MODEL_IDENTITY_MISMATCH")
        self.assertNotIn("fictional-secret-as-model",json.dumps(report))
        self.assertEqual(report["request_count"],1)

    def test_usage_preserved_per_request_and_aggregated(self):
        usage=Usage(3,2,5,source=UsageSource.PROVIDER)
        report=self.run_fake(self.manifest(),RecordingGateway(replace(call(),usage=usage),final(usage=usage)))
        self.assertEqual(report["usage"]["request_count"],2)
        self.assertEqual(report["usage"]["usage"]["total_tokens"],10)
        self.assertEqual(report["requests"][0]["usage"]["total_tokens"],5)

    def test_report_utf8_does_not_include_question_secret_id_payload_or_paths(self):
        self.store.set_current(replace(self.reading(),source="fictional-private-path"))
        response=call(call_id="fictional-private-id")
        report=self.run_fake(self.manifest(),RecordingGateway(response,final(FAKE_KEY)))
        filename=write_report(self.root,report)
        encoded=(self.root/"outputs/assistant-qualification"/filename).read_text(encoding="utf-8")
        for forbidden in (FAKE_KEY,"fictional-private-id","fictional-private-path","fictional question never in report",
                          '"messages":','"final_text":','"arguments_json":','"credential":'):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(json.loads(encoded),report)
        with self.assertRaises(QualificationError): write_report(self.root,report)  # No overwrite.

    def test_four_fixed_manifests_share_question_only_q3_q4(self):
        manifests=[QualificationManifest.from_json(PROJECT/f"scripts/qualification/manifests/assistant-Q{i}.json") for i in range(1,5)]
        self.assertEqual(manifests[2].question,manifests[3].question)
        self.assertEqual(len(manifests[3].exposed_tools),3)
        for manifest in manifests:
            self.assertFalse(manifest.confirm_network)
            self.assertEqual(manifest.max_requests,2)
            self.assertEqual(manifest.max_output_tokens,256)
            self.assertNotIn(manifest.question,repr(manifest))

    def test_plan_hash_binds_question_tools_budget_and_identity_not_consent(self):
        manifest=self.manifest()
        original=manifest.safe_plan()["plan_sha256"]
        self.assertEqual(original,replace(manifest,confirm_network=False).safe_plan()["plan_sha256"])
        for changes in ({"question":"different question"},{"exposed_tools":(SCORE,)},{"max_requests":1},
                        {"max_output_tokens":32},{"preset_id":"dashscope-qwen38-flash-r1"}):
            self.assertNotEqual(original,replace(manifest,**changes).safe_plan()["plan_sha256"])

    def test_success_never_publishes_capability_preset_or_policy(self):
        paths=[PROJECT/"src/fishery_ai/resources/profiles/presets.json",
               PROJECT/"src/fishery_ai/resources/tools/tool_policies.json"]
        before=[path.read_bytes() for path in paths]
        report=self.run_fake(self.manifest(),RecordingGateway(call(),final()))
        self.assertTrue(report["success"])
        self.assertEqual(before,[path.read_bytes() for path in paths])
        self.assertFalse((self.root/"outputs/capabilities").exists())

    def cli(self):
        spec=importlib.util.spec_from_file_location("qualification_cli",PROJECT/"scripts/qualification/qualify_assistant_turn.py")
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        (self.root/"pyproject.toml").write_text("",encoding="utf-8")
        return module

    def test_cli_defaults_dry_run_never_calls_runner(self):
        cli=self.cli()
        path=self.root/"manifest.json"
        path.write_bytes((PROJECT/"scripts/qualification/manifests/assistant-Q3.json").read_bytes())
        with patch.object(cli.Path,"cwd",return_value=self.root),patch.object(cli,"run_qualification",side_effect=AssertionError("no run")),redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(["--manifest",str(path)]),0)
        report=json.loads(output.getvalue())
        self.assertEqual(report["actual_network_requests"],0)
        self.assertTrue(report["dry_run"])
        self.assertNotIn("请查询",output.getvalue())

    def test_cli_confirmation_is_in_memory_for_one_manifest_and_file_unchanged(self):
        cli=self.cli()
        path=self.root/"manifest.json"
        path.write_bytes((PROJECT/"scripts/qualification/manifests/assistant-Q1.json").read_bytes())
        before=path.read_bytes()
        fake={"run_id":"a"*32,"status":"failed","success":False,"error_code":"CREDENTIAL_FILE_ERROR",
              "request_count":0,"actual_network_requests":0}
        with patch.object(cli.Path,"cwd",return_value=self.root),patch.object(cli,"run_qualification",return_value=fake) as run, \
             redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["--manifest",str(path),"--confirm-network"]),1)
        self.assertTrue(run.call_args.args[0].confirm_network)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(run.call_count,1)

    def test_cli_unknown_secret_argument_is_not_echoed(self):
        cli=self.cli()
        with redirect_stderr(StringIO()) as error,self.assertRaises(SystemExit):
            cli.main(["--manifest","fake","--api-key","fictional-secret-marker"])
        self.assertNotIn("fictional-secret-marker",error.getvalue())

    def test_cli_rejects_credential_or_outside_manifest_path_before_read(self):
        cli=self.cli()
        for path in (self.root/".env", PROJECT/"scripts/qualification/manifests/assistant-Q1.json"):
            with patch.object(cli.Path,"cwd",return_value=self.root), \
                 patch.object(cli.QualificationManifest,"from_json",side_effect=AssertionError("must not read")), \
                 redirect_stdout(StringIO()) as output:
                self.assertEqual(cli.main(["--manifest",str(path)]),2)
            self.assertIn("INVALID_QUALIFICATION_MANIFEST_PATH",output.getvalue())

    def test_keyboard_interrupt_cancels_shared_handle_and_writes_safe_result(self):
        handle=RequestHandle()
        def interrupt(*_):raise KeyboardInterrupt()
        report=self.run_fake(self.manifest(),RecordingGateway(final(),callback=interrupt),handle=handle)
        self.assertEqual(report["error_code"],"USER_CANCELLED")
        self.assertEqual(handle.state,"CANCELLED")
        self.assertEqual(report["request_count"],1)

    def test_report_write_failure_does_not_claim_zero_after_requests(self):
        cli=self.cli()
        path=self.root/"manifest.json"
        path.write_bytes((PROJECT/"scripts/qualification/manifests/assistant-Q1.json").read_bytes())
        fake={"actual_network_requests":2}
        with patch.object(cli.Path,"cwd",return_value=self.root),patch.object(cli,"run_qualification",return_value=fake), \
             patch.object(cli,"write_report",side_effect=QualificationError("QUALIFICATION_REPORT_ERROR")), \
             redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(["--manifest",str(path),"--confirm-network"]),2)
        self.assertEqual(json.loads(output.getvalue())["actual_network_requests"],2)

    def test_invalid_usage_cannot_leak_arbitrary_dataclass(self):
        from dataclasses import dataclass
        @dataclass
        class UnsafeUsage:
            secret:str="fictional-private-secret"
        report=self.run_fake(self.manifest(),RecordingGateway(replace(final(),usage=UnsafeUsage())))
        self.assertEqual(report["error_code"],"INVALID_RESPONSE")
        self.assertNotIn("fictional-private-secret",json.dumps(report))


    def test_report_directory_symlink_fails_closed(self):
        import os
        (self.root / "outputs").mkdir()
        target = self.root / "other"
        target.mkdir()
        try:
            os.symlink(target, self.root / "outputs/assistant-qualification", target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink unavailable")
        report = self.run_fake(self.manifest(), RecordingGateway(final()))
        with self.assertRaises(QualificationError):
            write_report(self.root, report)
        self.assertFalse(list(target.glob("*.json")))

    def test_report_reparse_directory_fails_without_symlink_privilege(self):
        folder = self.root / "outputs/assistant-qualification"
        folder.mkdir(parents=True)
        original = Path.lstat
        def lstat(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return NS(st_mode=info.st_mode, st_file_attributes=0x400) if path == folder else info
        report = self.run_fake(self.manifest(), RecordingGateway(final()))
        with patch.object(Path, "lstat", autospec=True, side_effect=lstat):
            with self.assertRaises(QualificationError):
                write_report(self.root, report)
        self.assertFalse(list(folder.glob("*.json")))

    def test_schema_hash_binds_description_and_required_query(self):
        from fishery_ai.development.qualification.qualification_projection import tool_schema_hash
        registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=KnowledgeFixture())
        tools = registry.model_definitions()
        original = tool_schema_hash(tools)
        changed = (*tools[:-1], replace(tools[-1], description="fictional changed description"))
        self.assertNotEqual(original, tool_schema_hash(changed))
        schema = tools[-1].parameters_dict()
        schema["required"] = []
        self.assertNotEqual(original, tool_schema_hash(
            (*tools[:-1], replace(tools[-1], parameters=schema))))

    def test_qualification_target_drift_fails_before_transport(self):
        from fishery_ai.development.qualification.assistant_qualification import MIGRATION_TARGETS
        from fishery_ai.model_options import Support
        from fishery_ai.providers import AuthSpec
        for target in MIGRATION_TARGETS.values():
            profile = assistant_profile(target.preset_id)
            for changes in ({"base_url": "https://fictional.invalid"}, {"model": "other-model"},
                {"preset_contract_version": "changed"},
                {"preset_protocol_spec": replace(profile.preset_protocol_spec, version="changed")},
                {"auth_spec": AuthSpec.NONE if profile.auth_spec != AuthSpec.NONE else AuthSpec.REQUIRED_BEARER},
                {"capabilities": replace(profile.capabilities, tool_calling=Support.UNKNOWN)}):
                with self.subTest(target=target.preset_id, fields=tuple(changes)), \
                        self.assertRaises(QualificationError):
                    target.validate(NS(**{**vars(profile), **changes}))


def sdk_reply(model, name=None, arguments="{}", content="fictional raw final", finish="stop"):
    calls=[NS(id="fictional-call-id",type="function",function=NS(name=name,arguments=arguments))] if name else None
    return NS(model=model,choices=[NS(finish_reason="tool_calls" if name else finish,
        message=NS(role="assistant",content=None if name else content,tool_calls=calls,reasoning_content=None))],
        usage=NS(prompt_tokens=3,completion_tokens=2,total_tokens=5))


class QualificationAdapterTests(AssistantFixture):
    def setUp(self):
        super().setUp()
        # Allow only asyncio's internal wakeup socketpair, matching existing SDK tests.
        test_execution.ExecutionTests.setUp(self)
        self.profile=assistant_profile(LOCAL)
        self.runtime=ProfileRegistry([self.profile],self.credentials).snapshot(self.profile.profile_id)
        self.registry=ToolRegistry(self.reader,DiagnosisService(),knowledge=KnowledgeFixture())

    def adapter(self,responses,tools=(QUERY,),factory=None):
        sequence=iter(responses); bodies=[]; clients=[]
        class Client:
            def __init__(self):
                self.chat=NS(completions=NS(create=self.create));self.closed=False
            async def create(self,**kwargs):
                bodies.append(kwargs);value=next(sequence)
                if isinstance(value,Exception):raise value
                return value
            async def close(self):self.closed=True
        def make(*_):
            client=Client();clients.append(client);return client
        return QualificationAdapter(self.profile.model,self.registry,tools,64,
            async_client_factory=factory or make),bodies,clients

    def run_adapter(self,adapter,tools=(QUERY,),requirement=Requirement.AUTO,handle=None):
        manifest=QualificationManifest(LOCAL,"fictional-question",tools,requirement,max_output_tokens=64,confirm_network=True)
        return run_qualification(manifest,self.root,credential_store=self.credentials,registry=self.registry,
                                 gateway=adapter,handle=handle)

    def test_fake_sdk_round_trip_raw_normalized_parity_budget_and_closure(self):
        adapter,bodies,clients=self.adapter([sdk_reply(self.profile.model,QUERY),sdk_reply(self.profile.model)])
        original=self.runtime.capabilities
        report=self.run_adapter(adapter,requirement=Requirement.CURRENT_OBSERVATION_QUERY)
        self.assertTrue(report["success"])
        self.assertEqual(report["transport_attempts"],2)
        self.assertEqual([body["max_tokens"] for body in bodies],[64,64])
        self.assertEqual([body["reasoning_effort"] for body in bodies],["none","none"])
        self.assertEqual([body["tool_choice"] for body in bodies],["auto","none"])
        self.assertTrue(all(client.closed for client in clients))
        self.assertEqual(self.runtime.capabilities,original)
        for row in report["requests"]:
            self.assertTrue(row["provider_observation"]["normalized_call_consistent"])
            self.assertTrue(row["provider_observation"]["normalized_metadata_consistent"])
        self.assertNotIn("fictional-call-id",json.dumps(report))
        self.assertNotIn("fictional raw final",json.dumps(report))

    def test_knowledge_hook_retains_only_query_shape(self):
        adapter,_,_=self.adapter([sdk_reply(self.profile.model,KNOWLEDGE,'{"query":"fictional-private-query"}'),sdk_reply(self.profile.model)],tools=(KNOWLEDGE,))
        report=self.run_adapter(adapter,(KNOWLEDGE,),Requirement.PROJECT_KNOWLEDGE_SEARCH)
        self.assertTrue(report["success"])
        row=report["requests"][0]["provider_observation"]["calls"][0]
        self.assertTrue(row["query_present"]);self.assertTrue(row["query_valid"])
        self.assertNotIn("fictional-private-query",json.dumps(report)+repr(adapter.observations))

    def test_raw_malformed_arguments_fail_without_followup(self):
        adapter,bodies,_=self.adapter([sdk_reply(self.profile.model,QUERY,"{")])
        report=self.run_adapter(adapter)
        self.assertFalse(report["success"])
        self.assertEqual(len(bodies),1)
        self.assertFalse(report["requests"][0]["provider_observation"]["calls"][0]["arguments_valid"])
        self.assertFalse(report["receipt"]["observation_query_completed"])

    def test_raw_non_object_arguments_are_never_reported_valid(self):
        for arguments in ("[]", "null", "false", "0", '"text"'):
            with self.subTest(arguments=arguments):
                adapter, bodies, _ = self.adapter([sdk_reply(self.profile.model, QUERY, arguments)])
                report = self.run_adapter(adapter)
                self.assertEqual(report["error_code"], "MODEL_TOOL_CALL_MALFORMED")
                self.assertEqual(len(bodies), 1)
                self.assertFalse(report["requests"][0]["provider_observation"]["calls"][0]["arguments_valid"])
                self.assertFalse(report["receipt"]["observation_query_completed"])

    def test_second_request_failure_does_not_reuse_first_raw_observation(self):
        adapter,_,_=self.adapter([sdk_reply(self.profile.model,QUERY),GatewayError("READ_TIMEOUT")])
        report=self.run_adapter(adapter)
        self.assertEqual(report["error_code"],"READ_TIMEOUT")
        self.assertFalse(report["requests"][1]["provider_observation"]["available"])
        self.assertEqual(report["transport_attempts"],2)

    def test_normalization_mismatch_is_visible_and_no_tool_execution(self):
        adapter,_,_=self.adapter([sdk_reply(self.profile.model,QUERY)])
        with patch.object(OpenAICompatibleAdapter,"_response",return_value=final()):
            report=self.run_adapter(adapter)
        self.assertEqual(report["error_code"],"QUALIFICATION_NORMALIZATION_MISMATCH")
        self.assertFalse(report["requests"][0]["provider_observation"]["normalized_call_consistent"])
        self.assertIsNone(report["tool_execution_status"])

    def test_true_sdk_cancel_closes_io_and_no_followup(self):
        started=threading.Event();closed=threading.Event()
        import asyncio
        class Client:
            def __init__(self):self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kwargs):started.set();await asyncio.Event().wait()
            async def close(self):closed.set()
        adapter,_,_=self.adapter([],factory=lambda *_:Client())
        handle=RequestHandle();reports=[]
        worker=threading.Thread(target=lambda:reports.append(self.run_adapter(adapter,handle=handle)))
        worker.start();self.assertTrue(started.wait(3));handle.cancel();worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(reports[0]["error_code"],"USER_CANCELLED")
        self.assertEqual(reports[0]["request_count"],1)
        self.assertTrue(closed.is_set())
        self.assertTrue(reports[0]["backend_io_closed"])
        self.assertEqual(reports[0]["remote_compute_stopped"],"UNKNOWN")

    def test_second_sdk_request_cancel_preserves_completed_query_not_success(self):
        import asyncio
        started=threading.Event();clients=[]
        model=self.profile.model
        class Client:
            def __init__(self):
                self.first=not clients;self.closed=False
                clients.append(self);self.chat=NS(completions=NS(create=self.create))
            async def create(self,**kwargs):
                if self.first:return sdk_reply(model,QUERY)
                started.set();await asyncio.Event().wait()
            async def close(self):self.closed=True
        adapter,_,_=self.adapter([],factory=lambda *_:Client())
        handle=RequestHandle();reports=[]
        worker=threading.Thread(target=lambda:reports.append(self.run_adapter(adapter,handle=handle)))
        worker.start();self.assertTrue(started.wait(3));handle.cancel();worker.join(5)
        self.assertFalse(worker.is_alive())
        report=reports[0]
        self.assertEqual(report["error_code"],"USER_CANCELLED")
        self.assertEqual(report["request_count"],2)
        self.assertTrue(report["receipt"]["observation_query_completed"])
        self.assertTrue(report["backend_io_closed"])
        self.assertTrue(all(client.closed for client in clients))
        self.assertFalse(report["success"])

    def test_each_preset_uses_fixed_protocol_budget_without_capability_mutation(self):
        from fishery_ai.contracts import Mode
        from fishery_ai.model_gateway import ModelMessage,ModelRequest
        for preset in ("dashscope-qwen38-flash-r1","deepseek-flash-r1",LOCAL):
            profile=assistant_profile(preset)
            credentials=CredentialStore(process_env={"DASHSCOPE_API_KEY":FAKE_KEY,"DEEPSEEK_API_KEY":FAKE_KEY})
            runtime=ProfileRegistry([profile],credentials).snapshot(profile.profile_id)
            adapter=QualificationAdapter(runtime.model,self.registry,(QUERY,),32)
            request=ModelRequest(Mode.CHAT,(ModelMessage("user","q"),),tools=(self.registry.lookup(QUERY).model_definition,))
            body=adapter._kwargs(request,runtime,stream=False)
            self.assertEqual(body[runtime.protocol_spec.max_output_tokens_field],32)
            self.assertEqual(runtime.capabilities,profile.capabilities)
            self.assertNotIn(FAKE_KEY,json.dumps(body))
            with self.assertRaises(GatewayError):adapter._kwargs(request,runtime,stream=True)

    def test_unknown_raw_function_and_model_are_only_safe_markers(self):
        adapter,_,_=self.adapter([sdk_reply("fictional-secret-model","fictional-secret-function")])
        report=self.run_adapter(adapter)
        self.assertEqual(report["error_code"],"MODEL_IDENTITY_MISMATCH")
        text=json.dumps(report)+repr(adapter.observations)
        self.assertNotIn("fictional-secret-model",text)
        self.assertNotIn("fictional-secret-function",text)
        self.assertEqual(report["requests"][0]["provider_observation"]["calls"][0]["function_name"],"unknown_tool")
