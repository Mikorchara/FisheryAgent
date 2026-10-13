"""Offline contract tests, never evidence of real model selection reliability."""

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from io import StringIO
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from fishery_ai.assistant import assistant_profile
from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.credentials import CredentialStore, CredentialFileError
from fishery_ai.development.qualification import multi_round_qualification as experiment
from fishery_ai.development.qualification.qualification_adapter import QualificationAdapter
from fishery_ai.execution import RequestHandle
from fishery_ai.model_gateway import GatewayError, ModelResponse, ModelToolCall, ProfileRegistry
from tests.support.paths import PROJECT_ROOT


FAKE_SECRET = "fictional-qualification-only-secret"
MODEL = "qwen3.8-flash"


def tool(name=experiment.WATER, identifier="first", arguments="{}"):
    return ModelResponse(None, Usage(total_tokens=7, source=UsageSource.PROVIDER),
        returned_model=MODEL, finish_reason="tool_calls",
        tool_calls=(ModelToolCall(identifier, name, arguments),))


def final(text="offline fixture final"):
    return ModelResponse(text, Usage(total_tokens=5, source=UsageSource.PROVIDER),
        returned_model=MODEL, finish_reason="stop")


class ScriptedGateway:
    def __init__(self, *responses, decide=None):
        self.responses, self.decide, self.requests = responses, decide, []
        self.request_attempts = 0  # A mock is not a real network request.

    def complete(self, request, runtime):
        self.requests.append(request)
        response = self.decide(len(self.requests), request, runtime) if self.decide else self.responses[len(self.requests)-1]
        if isinstance(response, Exception):
            raise response
        return response


class MultiRoundQualificationTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.create_connection", "socket.getaddrinfo", "socket.socket.connect",
                     "socket.socket.connect_ex", "socket.socket.sendto"):
            guard = patch(name, side_effect=AssertionError("offline tests forbid Provider I/O"))
            guard.start()
            self.addCleanup(guard.stop)
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.credentials = CredentialStore(process_env={"DASHSCOPE_API_KEY": FAKE_SECRET})

    def run_case(self, case, gateway, **options):
        return experiment.run(case, self.root, confirm_network=True,
            credential_store=self.credentials, gateway=gateway, **options)

    def test_dry_run_never_resolves_credentials_or_constructs_transport_registry(self):
        with patch.object(experiment, "_credentials", side_effect=AssertionError("no credentials")), \
             patch.object(experiment, "_isolated_registry", side_effect=AssertionError("no registry")), \
             patch.object(experiment, "QualificationAdapter", side_effect=AssertionError("no SDK")):
            report = experiment.run("low-oxygen", self.root)
            approved = experiment.plan("low-oxygen")
        self.assertEqual(report["request_count"], 0)
        self.assertEqual(report["actual_network_requests"], 0)
        self.assertEqual(approved["max_requests"], 3)
        self.assertFalse((self.root / "outputs").exists())

    def test_plan_fixed_cases_limits_hash_and_no_arbitrary_target(self):
        for case, count in (("low-oxygen",3),("normal",2),("current-do",2),("concept",1)):
            approved = experiment.plan(case)
            self.assertEqual(approved["max_requests"], count)
            self.assertEqual((approved["max_tool_calls"],approved["max_tool_rounds"],approved["runtime_max_requests"]), (2,2,3))
            self.assertEqual(approved["thinking"], "off")
            self.assertEqual(approved["response_mode"], "normal")
            self.assertEqual(approved["plan_sha256"], experiment.plan(case)["plan_sha256"])
        for value in (0,257,True,"256"):
            with self.assertRaises(experiment.QualificationError):
                experiment.plan("normal", max_output_tokens=value)
        with self.assertRaises(experiment.QualificationError):
            experiment.plan("../escape")
        with self.assertRaises(ValueError):
            experiment.plan("normal", "DS_1")

    def test_low_oxygen_second_decision_reads_actual_first_result(self):
        frozen = []
        def decide(index, request, runtime):
            frozen.append(runtime)
            if index == 1:
                self.assertEqual(len(request.messages), 2)
                self.assertNotIn("2.2", request.messages[0].content)
                self.assertNotIn("2.2", request.messages[1].content)
                self.assertEqual(request.tool_choice, "auto")
                return tool()
            if index == 2:
                payload = json.loads(request.messages[-1].content)
                self.assertEqual(payload["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                self.assertTrue(payload["findings"])
                self.assertEqual(request.messages[-1].tool_call_id, "first")
                return tool(experiment.KNOWLEDGE,"second",'{"query":"鳗鲡低氧表现"}')
            self.assertEqual(index,3)
            self.assertEqual(request.tool_choice,"none")
            self.assertEqual(len([item for item in request.messages if item.role=="tool"]),2)
            return final()
        report = self.run_case("low-oxygen", ScriptedGateway(decide=decide))
        self.assertTrue(report["success"])
        self.assertEqual(report["request_count"],3)
        self.assertTrue(all(runtime is frozen[0] for runtime in frozen))
        self.assertTrue(all(row["actual_result_in_next_request"] for row in report["executions"]))
        self.assertEqual(len(report["ledger"]["entries"]),2)
        self.assertTrue(all(row["satisfied"] for row in report["requirements"]))
        self.assertEqual(report["usage"]["usage"]["total_tokens"],19)
        self.assertEqual(report["actual_network_requests"],0)
        self.assertEqual(report["evidence_kind"],"offline_fixture")

    def test_normal_and_current_do_final_after_single_query(self):
        for case in ("normal","current-do"):
            with self.subTest(case=case):
                gateway = ScriptedGateway(tool(),final())
                report = self.run_case(case,gateway)
                self.assertTrue(report["success"])
                self.assertEqual(report["request_count"],2)
                self.assertTrue(report["early_final"])
                self.assertEqual(json.loads(gateway.requests[1].messages[-1].content)["water_quality"]["dissolved_oxygen_mg_l"],6.4)

    def test_concept_direct_no_tool_and_history_empty(self):
        gateway = ScriptedGateway(final())
        report = self.run_case("concept",gateway)
        self.assertTrue(report["success"])
        self.assertEqual(report["request_count"],1)
        self.assertEqual(report["executions"],[])
        self.assertEqual(report["ledger"],{"entries":[]})
        self.assertEqual(len(gateway.requests[0].messages),2)

    def test_concept_unnecessary_call_not_executed_or_retried(self):
        report = self.run_case("concept",ScriptedGateway(tool()))
        self.assertFalse(report["success"])
        self.assertEqual(report["error_code"],"QUALIFICATION_PATH_MISMATCH")
        self.assertEqual(report["request_count"],1)
        self.assertEqual(report["executions"],[])

    def test_missing_source_and_wrong_path_are_not_qualified(self):
        report = self.run_case("low-oxygen",ScriptedGateway(tool(),final()))
        self.assertFalse(report["success"])
        self.assertEqual(report["execution_status"],"completed")
        self.assertEqual(report["error_code"],"ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertEqual(report["request_count"],2) # Never auto-issue a recovery request.
        report = self.run_case("normal",ScriptedGateway(tool(experiment.KNOWLEDGE,arguments='{"query":"DO"}'),final()))
        self.assertFalse(report["success"])
        self.assertFalse(report["requirement_satisfied"])

    def test_no_match_is_completed_search_not_evidence(self):
        class EmptyKnowledge:
            backend = "portable"
            def search(self,*args,**kwargs): return ()
        with patch.object(experiment,"KnowledgeService",return_value=EmptyKnowledge()):
            report = self.run_case("low-oxygen",ScriptedGateway(tool(),
                tool(experiment.KNOWLEDGE,"second",'{"query":"DO"}'),final()))
        self.assertTrue(report["success"])
        receipt = report["ledger"]["entries"][1]["receipt"]
        self.assertTrue(receipt["project_search_completed"])
        self.assertFalse(receipt["has_project_evidence"])
        self.assertEqual(receipt["tool_status"],"NO_MATCH")

    def test_no_data_keeps_operation_proof_without_observation(self):
        original = experiment._isolated_registry
        def no_data(case,now):
            with patch.object(experiment.CurrentSnapshotStore,"set_current"):
                return original(case,now)
        with patch.object(experiment,"_isolated_registry",side_effect=no_data):
            report=self.run_case("current-do",ScriptedGateway(tool(),final()))
        self.assertTrue(report["success"])
        receipt=report["ledger"]["entries"][0]["receipt"]
        self.assertEqual(receipt["tool_status"],"NO_DATA")
        self.assertFalse(receipt["has_observation"])
        self.assertTrue(receipt["observation_query_completed"])

    def test_provider_failure_cancellation_malformed_duplicate_budget(self):
        scenarios = (
            ("normal",(tool(),GatewayError("READ_TIMEOUT")),"READ_TIMEOUT",2),
            ("normal",(GatewayError("USER_CANCELLED"),),"USER_CANCELLED",1),
            ("low-oxygen",(tool(arguments='{"extra":1}'),),"INVALID_TOOL_ARGUMENTS",1),
            ("low-oxygen",(GatewayError("MODEL_TOOL_CALL_MALFORMED"),),"MODEL_TOOL_CALL_MALFORMED",1),
            ("low-oxygen",(tool(),tool(identifier="second")),"TOOL_REQUEST_ALREADY_EXECUTED",2),
            ("low-oxygen",(tool(),tool(experiment.KNOWLEDGE,"second",'{"query":"DO"}'),tool(identifier="third")),"TOOL_ROUND_LIMIT",3),
        )
        for case,responses,code,count in scenarios:
            with self.subTest(code=code):
                report = self.run_case(case,ScriptedGateway(*responses))
                self.assertFalse(report["success"])
                self.assertEqual(report["error_code"],code)
                self.assertEqual(report["request_count"],count)
        report=self.run_case("normal",ScriptedGateway(tool(),GatewayError("READ_TIMEOUT")))
        self.assertEqual(len(report["ledger"]["entries"]),1)

    def test_capability_unknown_and_credentials_missing_fail_closed(self):
        with patch.object(self.credentials,"resolve",side_effect=CredentialFileError()):
            report=self.run_case("normal",ScriptedGateway())
        self.assertEqual(report["error_code"],"CREDENTIAL_FILE_ERROR")
        self.assertEqual(report["actual_network_requests"],0)
        report=experiment.run("normal",self.root,confirm_network=True,
            credential_store=CredentialStore(process_env={}),gateway=ScriptedGateway())
        self.assertEqual(report["error_code"],"SECRET_MISSING")
        self.assertEqual(report["request_count"],0)
        profile=assistant_profile(experiment.DEFAULT_PRESET)
        from fishery_ai.model_options import Support
        with patch.object(experiment,"assistant_profile",return_value=replace(profile,
                capabilities=replace(profile.capabilities,tool_calling=Support.UNKNOWN))):
            with self.assertRaises(experiment.QualificationError): experiment.plan("normal")

    def test_preset_model_mismatch_stops_once_without_followup(self):
        report=self.run_case("normal",ScriptedGateway(replace(tool(),returned_model="wrong-model")))
        self.assertEqual(report["error_code"],"MODEL_IDENTITY_MISMATCH")
        self.assertEqual(report["request_count"],1)
        self.assertEqual(report["executions"],[])
        self.assertEqual(report["usage"]["reported_count"],1)
        self.assertEqual(report["usage"]["usage"]["total_tokens"],7)

    def test_adapter_reuses_protocol_body_token_limit_off_retry_zero(self):
        profile=assistant_profile(experiment.DEFAULT_PRESET)
        runtime=ProfileRegistry([profile],self.credentials).snapshot(profile.profile_id)
        registry=experiment._isolated_registry(experiment.get_case("normal"),experiment.utcnow())
        from fishery_ai.model_gateway import ModelRequest, ModelMessage
        from fishery_ai.contracts import Mode
        adapter=QualificationAdapter(runtime.model,registry,(experiment.WATER,experiment.KNOWLEDGE),256)
        request=ModelRequest(Mode.CHAT,(ModelMessage("user","fixture"),))
        body=adapter._kwargs(request,runtime,stream=False)
        self.assertEqual(body["max_tokens"],256)
        self.assertFalse(body.get("stream",False))
        self.assertEqual(body["extra_body"]["enable_thinking"],False)
        self.assertEqual(runtime.max_retries,0)

    def test_debug_logging_fails_before_transport_and_credential_resolution(self):
        with patch.object(experiment.logging,"getLogger",return_value=NS(isEnabledFor=lambda level:True)), \
             patch.object(self.credentials,"resolve",side_effect=AssertionError("no credential read")):
            report=self.run_case("normal",ScriptedGateway())
        self.assertEqual(report["error_code"],"QUALIFICATION_UNSAFE_LOGGING")
        self.assertEqual(report["request_count"],0)

    def test_reports_hide_text_query_secret_and_cannot_change_global_store_policy(self):
        query="fictional-private-query-do-not-record"
        answer="fictional-private-final-do-not-record"
        report=self.run_case("low-oxygen",ScriptedGateway(tool(),
            tool(experiment.KNOWLEDGE,"second",json.dumps({"query":query})),final(answer)))
        saved=experiment.write_report(self.root,report)
        text=(self.root/"outputs/assistant-qualification"/saved).read_text(encoding="utf-8")
        for value in (query,answer,FAKE_SECRET,experiment.EXPERIMENT_INSTRUCTION,"raw_request","Authorization"):
            self.assertNotIn(value,text)
        self.assertFalse((self.root/"outputs/tool-policies").exists())
        self.assertFalse((self.root/".env").exists())
        self.assertEqual(report["remote_compute_stopped"],"UNKNOWN")

    def test_cli_single_case_default_dry_safe_invalid_input_and_no_report(self):
        spec=importlib.util.spec_from_file_location("multi_round_cli",PROJECT_ROOT/"scripts/qualification/qualify_multi_round.py")
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        output=StringIO()
        with patch.object(cli,"run",side_effect=AssertionError("no execute")),redirect_stdout(output):
            self.assertEqual(cli.main(["--case","normal"]),0)
        self.assertEqual(json.loads(output.getvalue())["actual_network_requests"],0)
        for args in (["--case","normal","--credential-path","fictional-private-path"],):
            with redirect_stderr(StringIO()) as error:
                with self.assertRaises(SystemExit): cli.main(args)
                self.assertNotIn("fictional-private-path",error.getvalue())

    def test_case_ceiling_reserves_final_before_unexpected_second_execution(self):
        report=self.run_case("normal",ScriptedGateway(tool(),
            tool(experiment.KNOWLEDGE,"second",'{"query":"DO"}')))
        self.assertEqual(report["request_count"],2)
        self.assertEqual(report["error_code"],"QUALIFICATION_REQUEST_LIMIT")
        self.assertEqual(len(report["executions"]),1)
        self.assertEqual(report["requests"][1]["normalized"]["tool_call_count"],1)

    def test_multiple_calls_text_imitation_and_truncation_not_qualified(self):
        multiple=replace(tool(),tool_calls=(ModelToolCall("one",experiment.WATER,"{}"),
            ModelToolCall("two",experiment.KNOWLEDGE,'{"query":"DO"}')))
        for response,code in ((multiple,"TOOL_CALL_LIMIT"),
                (final("[调用工具 get_current_water_quality]"),"ASSISTANT_SOURCE_REQUIREMENT_UNMET"),
                (replace(final(),finish_reason="length"),"MODEL_RESPONSE_TRUNCATED")):
            with self.subTest(code=code):
                report=self.run_case("current-do",ScriptedGateway(response))
                self.assertEqual(report["error_code"],code)
                self.assertFalse(report["success"])
                self.assertEqual(report["ledger"]["entries"],[])
                self.assertEqual(report["executions"],[])

    def test_existing_qualification_adapter_raw_normalized_summary_is_reused(self):
        registry=experiment._isolated_registry(experiment.get_case("normal"),experiment.utcnow())
        adapter=QualificationAdapter(MODEL,registry,(experiment.WATER,experiment.KNOWLEDGE),256)
        raw=NS(model=MODEL,choices=[NS(finish_reason="tool_calls",message=NS(content=None,
            tool_calls=[NS(id="sdk-call",type="function",function=NS(name=experiment.KNOWLEDGE,
            arguments='{"query":"fictional-sensitive-query"}'))]))],usage=None)
        normalized=adapter._response(raw)
        self.assertEqual(normalized.tool_calls[0].function_name,experiment.KNOWLEDGE)
        self.assertTrue(adapter.observations[0]["normalized_call_consistent"])
        self.assertTrue(adapter.observations[0]["normalized_metadata_consistent"])
        self.assertTrue(adapter.observations[0]["calls"][0]["query_valid"])
        self.assertNotIn("fictional-sensitive-query",json.dumps(adapter.observations))

    def test_formal_private_credential_composition_is_delegated_unchanged(self):
        with patch.object(experiment,"_credentials",return_value=self.credentials) as compose:
            report=experiment.run("concept",self.root,confirm_network=True,gateway=ScriptedGateway(final()))
        compose.assert_called_once_with(self.root)
        self.assertTrue(report["success"])
        self.assertIs(experiment._credentials,
            __import__("fishery_ai.development.qualification.assistant_qualification",fromlist=["_credentials"])._credentials)

    def test_report_write_failure_cli_retains_consumed_request_counts(self):
        spec=importlib.util.spec_from_file_location("multi_round_cli_write",PROJECT_ROOT/"scripts/qualification/qualify_multi_round.py")
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        report={"run_id":"f"*32,"request_count":2,"actual_network_requests":2}
        output=StringIO()
        with patch.object(cli,"run",return_value=report), \
             patch.object(cli,"write_report",side_effect=experiment.QualificationError("QUALIFICATION_REPORT_ERROR")), \
             redirect_stdout(output):
            self.assertEqual(cli.main(["--case","normal","--confirm-network"]),2)
        row=json.loads(output.getvalue())
        self.assertEqual(row["request_count"],2)
        self.assertEqual(row["actual_network_requests"],2)
        self.assertEqual(row["error_code"],"QUALIFICATION_REPORT_ERROR")

    def test_stop_before_second_request_preserves_only_completed_local_ledger(self):
        handle=RequestHandle()
        def decide(index,request,runtime):
            self.assertEqual(index,1)
            return tool()
        original=experiment.ToolCallingService.run_request
        def progress_wrap(service,request,runtime,**options):
            def progress(phase):
                if phase=="REQUEST_2": handle.cancel()
            return original(service,request,runtime,on_progress=progress,**options)
        gateway=ScriptedGateway(decide=decide)
        with patch.object(experiment.ToolCallingService,"run_request",progress_wrap):
            report=self.run_case("normal",gateway,handle=handle)
        self.assertEqual(report["status"],"cancelled")
        self.assertEqual(report["request_count"],1)
        self.assertEqual(len(report["ledger"]["entries"]),1)
        self.assertFalse(report["success"])

    def test_real_classification_requires_actual_adapter_protocol_observation(self):
        with patch.object(experiment,"QualificationAdapter",return_value=ScriptedGateway(final())), \
             patch.object(experiment,"_credentials",return_value=self.credentials):
            report=experiment.run("concept",self.root,confirm_network=True)
        self.assertFalse(report["provider_protocol_verified"])
        self.assertEqual(report["error_code"],"QUALIFICATION_NORMALIZATION_MISMATCH")
        self.assertFalse(report["success"])


class AssistantProductQualificationTests(unittest.TestCase):
    # Reuse setup only; do not inherit/collect the legacy experiment tests twice.
    setUp = MultiRoundQualificationTests.setUp

    def run_case(self, case, gateway, **options):
        return experiment.run(case, self.root, assistant_product=True, confirm_network=True,
                              credential_store=self.credentials, gateway=gateway, **options)

    def test_product_plan_pins_candidate_prompt_history_schema_and_qwen(self):
        from fishery_ai.assistant import MULTI_ROUND_PROMPT_ID
        config = experiment.load_assistant_execution_config()
        self.assertFalse(config.multi_round_enabled)
        self.assertEqual(config.releases[0].status, "candidate")
        self.assertEqual(len(experiment.PRODUCT_CASES), 6)
        for case in experiment.PRODUCT_CASES:
            plan = experiment.plan(case.case_id, assistant_product=True)
            self.assertEqual(plan["experiment_version"], "assistant-product-multi-round@1")
            self.assertEqual(plan["prompt_id"], MULTI_ROUND_PROMPT_ID)
            self.assertEqual(plan["release_scope"], json.loads(config.releases[0].scope_json))
            self.assertEqual(plan["max_requests"], 3)
            self.assertFalse(plan["release_eligible"])
            self.assertEqual(plan["plan_sha256"], experiment.plan(case.case_id, assistant_product=True)["plan_sha256"])
        with self.assertRaises(experiment.QualificationError):
            experiment.plan("normal", "deepseek-flash-r1", assistant_product=True)

    def test_dry_product_plan_never_resolves_credentials_or_constructs_adapter(self):
        with patch.object(experiment, "_credentials", side_effect=AssertionError("no credentials")), \
             patch.object(experiment, "QualificationAdapter", side_effect=AssertionError("no SDK")), \
             patch.object(experiment.AssistantService, "send", side_effect=AssertionError("no send")):
            report = experiment.run("history-current", self.root, assistant_product=True)
        self.assertEqual(report["actual_network_requests"], 0)
        self.assertEqual(report["request_count"], 0)
        self.assertFalse((self.root / "outputs").exists())

    def test_low_oxygen_uses_formal_service_prompt_gate_deadline_and_actual_result(self):
        from fishery_ai.execution import current_handle
        def decide(index, request, runtime):
            self.assertEqual(request.messages[0].content, experiment.MULTI_ROUND_SYSTEM_INSTRUCTION)
            self.assertLessEqual(current_handle().remaining_timeout(1000), runtime.total_timeout_s)
            self.assertEqual(runtime.max_retries, 0)
            if index == 1:
                self.assertEqual(len(request.messages), 2)
                return tool()
            if index == 2:
                data = json.loads(request.messages[-1].content)
                self.assertEqual(data["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                self.assertTrue(data["findings"])
                self.assertEqual(request.tool_choice, "auto")
                return tool(experiment.KNOWLEDGE, "second", '{"query":"鳗鲡低氧表现"}')
            self.assertEqual(index, 3)
            self.assertEqual(request.tool_choice, "none")
            self.assertEqual(len([m for m in request.messages if m.role == "tool"]), 2)
            return final()
        report = self.run_case("low-oxygen", ScriptedGateway(decide=decide))
        self.assertTrue(report["technical_success"])
        self.assertTrue(report["product_commit_gate_passed"])
        self.assertTrue(report["trace_recorded"])
        self.assertEqual(report["qualification_verdict"], "PENDING_MANUAL_REVIEW")
        self.assertEqual(report["request_count"], 3)
        self.assertEqual(len(report["activity"]["steps"]), 5)
        self.assertEqual(len(report["ledger"]["entries"]), 2)
        self.assertTrue(all(e["actual_result_in_next_request"] for e in report["executions"]))
        self.assertTrue(report["requirement_satisfied"])
        self.assertEqual(report["usage"]["usage"]["total_tokens"], 19)
        self.assertEqual(report["actual_network_requests"], 0)
        self.assertFalse(report["release_eligible"])

    def test_normal_and_do_stop_early_under_the_real_three_request_budget(self):
        for case in ("normal", "current-do"):
            gateway = ScriptedGateway(tool(), final())
            report = self.run_case(case, gateway)
            self.assertTrue(report["success"])
            self.assertEqual(report["request_count"], 2)
            self.assertEqual(gateway.requests[-1].tool_choice, "auto")
            self.assertEqual(report["activity"]["budget"]["model_requests"], 3)
            self.assertEqual(len(report["activity"]["steps"]), 3)
            self.assertTrue(report["early_final"])

    def test_concept_and_historical_explanation_can_finalize_without_receipts(self):
        for case in ("concept", "history-explanation"):
            report = self.run_case(case, ScriptedGateway(final()))
            self.assertTrue(report["success"])
            self.assertEqual(report["request_count"], 1)
            self.assertEqual(report["ledger"], {"entries": []})
            self.assertEqual(report["executions"], [])

    def test_history_current_uses_exact_product_projection_and_requeries_new_snapshot(self):
        from fishery_ai.assistant import AssistantRequest, AssistantContextBuilder
        from fishery_ai.history_projection import project_retained_history, TRANSCRIPT_KIND
        from fishery_ai.tool_conversation import ToolExecutionMode
        case = experiment.get_case("history-current", assistant_product=True)
        turn = AssistantRequest(experiment.DEFAULT_PRESET, case.question, history=case.history,
                                source_requirement=case.requirements[0])
        expected, _ = project_retained_history(turn, AssistantContextBuilder().build(turn,
            execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND), experiment.DEFAULT_HISTORY_PROJECTION)
        gateway = ScriptedGateway(tool(), final())
        report = self.run_case(case.case_id, gateway)
        self.assertTrue(report["success"])
        self.assertEqual(gateway.requests[0].messages, expected.model_request.messages)
        self.assertEqual(json.loads(gateway.requests[0].messages[1].content)["kind"], TRANSCRIPT_KIND)
        self.assertEqual(gateway.requests[0].messages[-1].content, case.question)
        self.assertEqual(report["history_projection"]["sent"], 2)
        self.assertEqual(json.loads(gateway.requests[1].messages[-1].content)["water_quality"]["dissolved_oxygen_mg_l"], 6.4)
        self.assertEqual(len(report["ledger"]["entries"]), 1)

    def test_historical_source_claim_and_text_imitation_cannot_pass_product_commit_gate(self):
        report = self.run_case("history-current", ScriptedGateway(final("[调用工具 get_current_water_quality] 已查询")))
        self.assertEqual(report["error_code"], "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertFalse(report["product_commit_gate_passed"])
        self.assertFalse(report["final_answer_present"])
        self.assertEqual(report["ledger"], {"entries": []})

    def test_missing_knowledge_is_qualification_failure_even_if_observation_gate_passes(self):
        report = self.run_case("low-oxygen", ScriptedGateway(tool(), final()))
        self.assertTrue(report["product_commit_gate_passed"])
        self.assertFalse(report["requirement_satisfied"])
        self.assertFalse(report["technical_success"])
        self.assertEqual(report["error_code"], "ASSISTANT_SOURCE_REQUIREMENT_UNMET")

    def test_unnecessary_tool_is_observed_not_preemptively_suppressed_by_experiment_ceiling(self):
        report = self.run_case("concept", ScriptedGateway(tool(), final()))
        self.assertEqual(report["error_code"], "QUALIFICATION_PATH_MISMATCH")
        self.assertEqual(report["request_count"], 2)
        self.assertEqual(len(report["executions"]), 1)
        self.assertTrue(report["product_commit_gate_passed"])

    def test_no_match_has_search_completion_without_evidence(self):
        class EmptyKnowledge:
            backend = "portable"
            def search(self, *args, **kwargs): return ()
        with patch.object(experiment, "KnowledgeService", return_value=EmptyKnowledge()):
            report = self.run_case("low-oxygen", ScriptedGateway(tool(),
                tool(experiment.KNOWLEDGE, "second", '{"query":"DO"}'), final()))
        self.assertTrue(report["technical_success"])
        receipt = report["ledger"]["entries"][1]["receipt"]
        self.assertEqual(receipt["tool_status"], "NO_MATCH")
        self.assertTrue(receipt["project_search_completed"])
        self.assertFalse(receipt["has_project_evidence"])

    def test_scope_mismatch_is_preflight_and_no_sdk_credentials_or_web_release_changes(self):
        config = experiment.load_assistant_execution_config()
        record = config.releases[0]
        scope = json.loads(record.scope_json); scope["prompt_sha256"] = "0" * 64
        config = replace(config, releases=(replace(record, scope_json=json.dumps(scope)),))
        with patch.object(experiment, "load_assistant_execution_config", return_value=config), \
             patch.object(experiment, "_credentials", side_effect=AssertionError("no credentials")):
            with self.assertRaises(experiment.QualificationError) as error:
                experiment.run("normal", self.root, assistant_product=True, confirm_network=True)
        self.assertEqual(error.exception.code, "QUALIFICATION_RELEASE_SCOPE_MISMATCH")
        actual = experiment.load_assistant_execution_config()
        self.assertFalse(actual.multi_round_enabled)
        self.assertEqual(actual.releases[0].status, "candidate")
        self.assertFalse((self.root / "outputs/tool-policies").exists())

    def test_permissions_malformed_calls_and_budget_keep_single_executor(self):
        multiple = replace(tool(), tool_calls=(tool().tool_calls[0],
            tool(experiment.KNOWLEDGE, "second", '{"query":"DO"}').tool_calls[0]))
        cases = (([tool("score_current_water_quality")], "TOOL_NOT_ALLOWED", 1),
                 ([tool(experiment.KNOWLEDGE, arguments='{"extra":1}')], "INVALID_TOOL_ARGUMENTS", 1),
                 ([multiple], "TOOL_CALL_LIMIT", 1),
                 ([tool(), tool(experiment.KNOWLEDGE, "second", '{"query":"DO"}'), tool(identifier="third")], "TOOL_ROUND_LIMIT", 3))
        for responses, code, count in cases:
            report = self.run_case("low-oxygen", ScriptedGateway(*responses))
            self.assertEqual(report["error_code"], code)
            self.assertEqual(report["request_count"], count)
            self.assertFalse(report["technical_success"])

    def test_timeout_cancel_and_trace_failure_never_qualify(self):
        for code in ("TOTAL_TIMEOUT", "USER_CANCELLED", "HTTP_429"):
            report = self.run_case("low-oxygen", ScriptedGateway(tool(), GatewayError(code)))
            self.assertEqual(report["error_code"], code)
            self.assertEqual(len(report["ledger"]["entries"]), 1)
            self.assertFalse(report["product_commit_gate_passed"])
        with patch.object(experiment._RunTrace, "record_assistant", side_effect=OSError("fictional-private-path")):
            report = self.run_case("concept", ScriptedGateway(final()))
        self.assertEqual(report["error_code"], "TRACE_WRITE_ERROR")
        self.assertFalse(report["technical_success"])
        self.assertFalse(report["final_answer_present"])

    def test_real_turn_deadline_is_not_reset_between_model_requests(self):
        ticks = [0.0]
        def decide(index, request, runtime):
            ticks[0] += 70
            return tool() if index == 1 else final()
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]):
            report = self.run_case("normal", ScriptedGateway(decide=decide))
        self.assertEqual(report["request_count"], 2)
        self.assertEqual(report["error_code"], "TOTAL_TIMEOUT")
        self.assertFalse(report["product_commit_gate_passed"])
        self.assertFalse(report["final_answer_present"])
        self.assertEqual(len(report["ledger"]["entries"]), 1)

    def test_reviewer_failure_never_auto_approves_and_cli_preview_is_not_in_stdout(self):
        report = self.run_case("concept", ScriptedGateway(final()),
            answer_reviewer=lambda text: (_ for _ in ()).throw(OSError("fictional-private")))
        self.assertTrue(report["technical_success"])
        self.assertEqual(report["human_review_status"], "PREVIEW_UNAVAILABLE")
        self.assertEqual(report["qualification_verdict"], "PENDING_MANUAL_REVIEW")
        spec = importlib.util.spec_from_file_location("product_preview_cli", PROJECT_ROOT / "scripts/qualification/qualify_multi_round.py")
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        def execute(*args, **options):
            options["answer_reviewer"]("fictional-answer\x1b[31m")
            return report
        with patch.object(cli, "run", side_effect=execute), patch.object(cli, "write_report", return_value="fake.json"), \
             redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
            self.assertEqual(cli.main(["--assistant-product", "--case", "concept", "--confirm-network", "--review-answer"]), 0)
        self.assertNotIn("fictional-answer", out.getvalue())
        self.assertIn("fictional-answer", err.getvalue())
        self.assertNotIn("\x1b", err.getvalue())

    def test_safe_report_and_optional_review_redact_secret_and_never_save_answer(self):
        answer = "fictional answer " + FAKE_SECRET
        query = "fictional-private-query"
        reviewed = []
        report = self.run_case("low-oxygen", ScriptedGateway(tool(),
            tool(experiment.KNOWLEDGE, "second", json.dumps({"query": query})), final(answer)), answer_reviewer=reviewed.append)
        self.assertNotIn(FAKE_SECRET, reviewed[0])
        self.assertIn("[REDACTED]", reviewed[0])
        self.assertEqual(report["human_review_status"], "PREVIEWED_NOT_APPROVED")
        self.assertEqual(report["qualification_verdict"], "PENDING_MANUAL_REVIEW")
        filename = experiment.write_report(self.root, report)
        saved = (self.root / "outputs/assistant-qualification" / filename).read_text(encoding="utf-8")
        for value in ("fictional answer", FAKE_SECRET, query, experiment.MULTI_ROUND_SYSTEM_INSTRUCTION,
                      experiment.EXPERIMENT_INSTRUCTION, "Authorization", "raw_result", "arguments_json"):
            self.assertNotIn(value, saved)
        self.assertFalse((self.root / ".env").exists())

    def test_product_cli_default_dry_run_and_single_explicit_confirmation(self):
        spec = importlib.util.spec_from_file_location("product_cli", PROJECT_ROOT / "scripts/qualification/qualify_multi_round.py")
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with patch.object(cli, "run", side_effect=AssertionError("no automatic run")), redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(["--assistant-product", "--case", "history-current"]), 0)
        self.assertEqual(json.loads(out.getvalue())["plan"]["prompt_id"], experiment.MULTI_ROUND_PROMPT_ID)
        with patch.object(cli, "run", return_value=self.run_case("concept", ScriptedGateway(final()))) as execute, \
             patch.object(cli, "write_report", return_value="fictional.json"), redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(["--assistant-product", "--case", "concept", "--confirm-network"]), 0)
        execute.assert_called_once()
        self.assertTrue(execute.call_args.kwargs["assistant_product"])
        self.assertTrue(execute.call_args.kwargs["confirm_network"])
        self.assertEqual(json.loads(out.getvalue())["qualification_verdict"], "PENDING_MANUAL_REVIEW")

    def test_product_reuses_formal_private_composition_without_manual_env_or_source_env(self):
        with patch.object(experiment, "_credentials", return_value=self.credentials) as compose:
            report = experiment.run("concept", self.root, assistant_product=True,
                                    confirm_network=True, gateway=ScriptedGateway(final()))
        compose.assert_called_once_with(self.root)
        self.assertTrue(report["success"])


if __name__ == "__main__":
    unittest.main()
