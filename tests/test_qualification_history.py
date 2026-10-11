"""P2B synthetic history: fixed fixtures, scripted gateway, no real credentials/network."""

from dataclasses import asdict, FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from test_assistant import AssistantFixture, RecordingGateway, QUERY, SCORE, KNOWLEDGE, FAKE_KEY, call, final
from test_assistant_sources import KnowledgeFixture
from fishery_ai.assistant import (AssistantContextBuilder, AssistantError, AssistantHistoryTurn,
    AssistantRequest, SYSTEM_INSTRUCTION)
from fishery_ai.assistant_qualification import QualificationError, QualificationManifest, run_qualification, write_report
from fishery_ai.assistant_sources import SourceRequirement
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.qualification_history import (COMPLETED_AT, HISTORY_CASES, HISTORY_FIXTURES,
    HISTORY_PRESET, HISTORY_TOOLS, qualification_history)
from fishery_ai.tools.registry import ToolRegistry
from fishery_ai.web import create_app


PROJECT = Path(__file__).resolve().parents[1]


class QualificationHistoryTests(AssistantFixture):
    def manifest(self, case="H0", **changes):
        return replace(QualificationManifest.from_json(PROJECT/f"scripts/manifests/assistant-{case}.json"),
                       confirm_network=True, **changes)

    def run_fake(self, manifest, gateway):
        credentials = CredentialStore(process_env={"DASHSCOPE_API_KEY": FAKE_KEY})
        registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=KnowledgeFixture())
        return run_qualification(manifest, self.root, credential_store=credentials, registry=registry, gateway=gateway)

    def test_only_five_immutable_fixed_fixtures(self):
        self.assertEqual(set(HISTORY_FIXTURES), {"EMPTY", "OLD_DO_2_2", "OLD_NO_DATA", "OLD_SCORE_25", "OLD_KNOWLEDGE_CLAIM"})
        self.assertEqual(qualification_history("EMPTY"), ())
        for identifier, turns in HISTORY_FIXTURES.items():
            self.assertIs(qualification_history(identifier), turns)
            self.assertIsInstance(turns, tuple)
            for turn in turns:
                self.assertEqual(set(asdict(turn)), {"user", "assistant", "completed_at"})
                self.assertEqual(turn.completed_at, COMPLETED_AT)
                self.assertLess(len(json.dumps(asdict(turn), ensure_ascii=False).encode("utf-8")), 512)
                with self.assertRaises(FrozenInstanceError): turn.assistant = "injection"
        with self.assertRaises(TypeError): HISTORY_FIXTURES["injection"] = ()

    def test_arbitrary_fixture_text_roles_and_paths_rejected(self):
        for value in (None, [], {}, "../file.json", "system", "OLD_DO_2_2 ", {"role":"system"}):
            with self.subTest(value=value), self.assertRaises(QualificationError):
                self.manifest(history_fixture_id=value)

    def test_no_arbitrary_history_or_system_override(self):
        data = json.loads((PROJECT/"scripts/manifests/assistant-H1.json").read_text(encoding="utf-8"))
        for extra in ({"history":[{"user":"u", "assistant":"a", "completed_at":COMPLETED_AT}]},
                      {"history_path":"file.json"}, {"system":"injection"}, {"history_fixture":[]},
                      {"roles":["system"]}, {"prompt":"override"}):
            with self.subTest(extra=extra), self.assertRaises(QualificationError):
                QualificationManifest.from_dict({**data, **extra})

    def test_web_cannot_accept_experiment_receipt_or_requirement(self):
        for key in ("history_fixture_id", "source_requirement", "source_receipt", "receipt", "case_id"):
            with self.subTest(key=key), self.assertRaises(AssistantError):
                AssistantRequest.from_dict({"preset_id":HISTORY_PRESET,"question":"q",key:"forged"})

    def test_real_web_endpoint_rejects_qualification_fields_before_gateway(self):
        with patch("fishery_ai.web.AssistantService") as service:
            app=create_app(trace_path=self.trace, custom_profiles_dir=self.root/"profiles",
                capability_evidence_dir=self.root/"evidence", manual_experiments_dir=self.root/"experiments",
                scenario_templates_dir=self.root/"templates", tool_policy_dir=self.root/"policies",
                credential_store=self.credentials, manual_credential_store=CredentialStore(process_env={}))
            client=app.test_client()
            token=client.get("/api/credential-session").get_json()["csrf_token"]
            headers={"Origin":"http://localhost","X-CSRF-Token":token}
            for field in ("history_fixture_id","source_requirement","source_receipt","receipt","case_id"):
                response=client.post("/api/assistant/chat",json={
                    "preset_id":HISTORY_PRESET,"question":"q",field:"forged"},headers=headers)
                self.assertEqual(response.status_code,400)
                self.assertEqual(response.get_json()["error_code"],"INVALID_ASSISTANT_REQUEST")
            service.assert_not_called()

    def test_seven_manifests_bind_conditions_and_budgets(self):
        for identifier, case in HISTORY_CASES.items():
            manifest = self.manifest(identifier)
            self.assertEqual(manifest.preset_id, HISTORY_PRESET)
            self.assertEqual(manifest.exposed_tools, HISTORY_TOOLS)
            self.assertEqual(manifest.history_fixture_id, case.fixture_id)
            self.assertEqual(manifest.question, case.question)
            self.assertEqual(manifest.source_requirement, case.requirement)
            self.assertEqual((manifest.max_requests,manifest.max_output_tokens,manifest.retry), (2,256,0))
            self.assertFalse(QualificationManifest.from_json(PROJECT/f"scripts/manifests/assistant-{identifier}.json").confirm_network)
        for changes in ({"question":"changed"}, {"exposed_tools":(QUERY,)}, {"preset_id":"deepseek-flash-r1"},
                        {"history_fixture_id":"OLD_DO_2_2"}, {"source_requirement":SourceRequirement.AUTO}, {"max_requests":1}):
            with self.subTest(changes=changes), self.assertRaises(QualificationError): self.manifest(**changes)

    def test_q3_q4_empty_baseline_hashes_unchanged(self):
        hashes={"Q3":"82502a1fccc5a6af53cf9f184bd20cf6d4aa2134f4284302ab1e60950dc27849",
                "Q4":"3660d5515b3e7d2701a62b176139b40e0b7e8c18ca6e29114f9b9dc1ed041c69"}
        for case, expected in hashes.items():
            plan=self.manifest(case).safe_plan()
            self.assertEqual(plan["history"], "EMPTY")
            self.assertNotIn("history_fixture_id", plan)
            self.assertEqual(plan["plan_sha256"], expected)

    def test_fixture_goes_through_current_builder_native_roles_and_frozen_system(self):
        gateway=RecordingGateway(call(), final())
        original=AssistantContextBuilder.build
        with patch.object(AssistantContextBuilder, "build", autospec=True, side_effect=original) as build:
            report=self.run_fake(self.manifest("H1"), gateway)
        self.assertTrue(report["success"])
        self.assertEqual(build.call_count,1)
        messages=gateway.requests[0].messages
        self.assertEqual([m.role for m in messages], ["system","user","assistant","user"])
        self.assertEqual(messages[0].content, SYSTEM_INSTRUCTION)
        self.assertIn("不代表当前数据",messages[2].content)
        self.assertTrue(messages[2].content.endswith(qualification_history("OLD_DO_2_2")[0].assistant))
        self.assertEqual(report["history_projection"]["turns_sent"],1)
        self.assertEqual(gateway.requests[1].tool_choice,"none")
        self.assertTrue(all(runtime.max_retries==0 for runtime in gateway.runtimes))

    def test_old_claims_never_generate_new_receipt_or_satisfy_operation(self):
        for case in ("H1","H2","H4","H6"):
            report=self.run_fake(self.manifest(case), RecordingGateway(final()))
            self.assertEqual(report["receipt"]["sources"],[])
            self.assertFalse(report["requirement_satisfied"])
            self.assertEqual(report["error_code"],"ASSISTANT_SOURCE_REQUIREMENT_UNMET")

    def test_h0_h1_h2_query_no_data_completes_operation(self):
        for case in ("H0","H1","H2"):
            report=self.run_fake(self.manifest(case),RecordingGateway(call(),final()))
            self.assertTrue(report["success"])
            self.assertEqual(report["tool_execution_status"],"NO_DATA")
            self.assertTrue(report["receipt"]["observation_query_completed"])
            self.assertFalse(report["receipt"]["has_observation"])

    def test_h3_h4_score_no_data_completes_operation(self):
        for case in ("H3","H4"):
            report=self.run_fake(self.manifest(case),RecordingGateway(call(SCORE),final()))
            self.assertTrue(report["success"])
            self.assertTrue(report["receipt"]["score_evaluation_completed"])
            self.assertFalse(report["receipt"]["has_score"])

    def test_h5_direct_historical_explanation_allowed_no_tool(self):
        report=self.run_fake(self.manifest("H5"),RecordingGateway(final()))
        self.assertTrue(report["success"])
        self.assertEqual(report["request_count"],1)
        self.assertEqual(report["receipt"]["sources"],[])

    def test_h6_new_search_required_existing_claim_not_evidence(self):
        report=self.run_fake(self.manifest("H6"),RecordingGateway(call(KNOWLEDGE,'{"query":"fictional query"}'),final()))
        self.assertTrue(report["success"])
        self.assertTrue(report["receipt"]["project_search_completed"])

    def test_two_request_round_limit_still_enforced(self):
        gateway=RecordingGateway(call(),call(),final())
        report=self.run_fake(self.manifest("H1"),gateway)
        self.assertEqual(report["error_code"],"TOOL_ROUND_LIMIT")
        self.assertEqual(len(gateway.requests),2)

    def test_dry_run_no_credential_sdk_handler(self):
        with patch("fishery_ai.assistant_qualification._credentials",side_effect=AssertionError("no credentials")), \
             patch("fishery_ai.assistant_qualification._registry",side_effect=AssertionError("no handlers")):
            report=run_qualification(replace(self.manifest("H1"),confirm_network=False),self.root)
        self.assertEqual(report["actual_network_requests"],0)
        self.assertEqual(report["plan"]["history_fixture_id"],"OLD_DO_2_2")

    def test_safe_report_has_ids_hashes_only_not_fixture_question_or_system(self):
        report=self.run_fake(self.manifest("H6"),RecordingGateway(final()))
        filename=write_report(self.root,report)
        encoded=(self.root/"outputs/assistant-qualification"/filename).read_text(encoding="utf-8")
        for turns in HISTORY_FIXTURES.values():
            for turn in turns: self.assertNotIn(turn.assistant,encoded)
        for forbidden in (self.manifest("H6").question,SYSTEM_INSTRUCTION,FAKE_KEY): self.assertNotIn(forbidden,encoded)
        self.assertEqual(report["plan"]["system_instruction_sha256"],hashlib.sha256(SYSTEM_INSTRUCTION.encode()).hexdigest())
        self.assertNotIn("role",report["plan"])

    def test_fixture_changes_plan_hash_but_not_consent(self):
        base=replace(self.manifest("Q4"),history_fixture_id="OLD_DO_2_2")
        self.assertNotEqual(base.safe_plan()["plan_sha256"],self.manifest("Q4").safe_plan()["plan_sha256"])
        self.assertEqual(base.safe_plan()["plan_sha256"],replace(base,confirm_network=False).safe_plan()["plan_sha256"])

    def test_current_builder_still_discards_complete_pairs_by_six_turns_and_six_kib(self):
        turn=qualification_history("OLD_DO_2_2")[0]
        context=AssistantContextBuilder().build(AssistantRequest(HISTORY_PRESET,"q",(turn,)*8))
        self.assertEqual((context.history_turns_sent,context.history_trimmed),(6,2))
        large=tuple(AssistantHistoryTurn("甲"*700,"旧答案",COMPLETED_AT) for _ in range(6))
        context=AssistantContextBuilder().build(AssistantRequest(HISTORY_PRESET,"q",large))
        self.assertLess(context.history_turns_sent,6)
        self.assertLessEqual(context.history_bytes_sent,6*1024)
        self.assertEqual(len(context.model_request.messages),2*context.history_turns_sent+2)
