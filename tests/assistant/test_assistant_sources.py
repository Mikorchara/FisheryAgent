"""P1 deterministic/scripted source receipts; no real credentials or network."""

from dataclasses import FrozenInstanceError, replace
from contextlib import nullcontext
from datetime import timedelta
import json
from unittest.mock import patch

from tests.assistant.test_assistant import (AssistantFixture, RecordingGateway, FakeKnowledgeService,
                           QUERY, SCORE, KNOWLEDGE, NOW, call, final)
from fishery_ai.assistant import AssistantError, AssistantHistoryTurn, AssistantRequest, AssistantService
from fishery_ai.assistant_sources import (SourceRequirement as Requirement, TurnSource as Source,
    TurnSourceReceipt, receipt_from_execution, requirement_satisfied,
    TurnSourceLedger, ledger_from_execution, requirement_satisfied_by_ledger)
from fishery_ai.contracts import KnowledgeEvidence, Freshness, Quality, Status
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError
from fishery_ai.tool_conversation import ModelExecutionStep, ToolCallingService, ToolExecutionStep
from fishery_ai.tools.contracts import ToolExecutionResult
from fishery_ai.tools.policy import ToolPolicy
from fishery_ai.tools.registry import ToolRegistry
from fishery_ai.domain import DiagnosisService


class KnowledgeFixture(FakeKnowledgeService):
    def search(self, query, **kwargs):
        return (KnowledgeEvidence(evidence_id="fixture-evidence", category="water_quality",
            source_id="fixture-source", text="fictional evidence text", score=0.8,
            retrieved_at=NOW, source_version="fixture-v1"),)


def altered_execution(run, **changes):
    """Corruption fixtures change canonical steps, never derived legacy slots."""
    steps = []
    for step in run.steps:
        if isinstance(step, ModelExecutionStep) and step.request_index == 1 and "request_1" in changes:
            step = replace(step, result=changes["request_1"])
        if isinstance(step, ToolExecutionStep):
            step = replace(step, **{("result" if key == "tool_result" else key): value
                                    for key, value in changes.items() if key != "request_1"})
        steps.append(step)
    return replace(run, steps=tuple(steps))


class AssistantSourceTests(AssistantFixture):
    def test_ledger_single_execution_parity_across_business_statuses(self):
        cases = ((QUERY, None, None), (QUERY, self.reading(), None),
                 (QUERY, self.reading(ph="invalid"), None), (QUERY, self.reading(ph=None), None),
                 (SCORE, None, None), (SCORE, self.reading(), None),
                 (SCORE, self.reading(ph="invalid"), None), (SCORE, self.reading(ph=None), None),
                 (KNOWLEDGE, None, KnowledgeFixture()), (KNOWLEDGE, None, FakeKnowledgeService()))
        for name, reading, knowledge in cases:
            with self.subTest(name=name, quality=reading.quality if reading else None):
                if reading:
                    self.store.set_current(reading)
                with patch.object(self.reader, "query", return_value=None) if reading is None else nullcontext():
                    result, _ = self.send_call(name, knowledge=knowledge)
                ledger = ledger_from_execution(result.execution)
                self.assertEqual(ledger, result.source_ledger)
                self.assertEqual(len(ledger.entries), 1)
                entry = ledger.entries[0]
                self.assertEqual((entry.execution_seq, entry.model_request_index, entry.tool_round), (2, 1, 1))
                self.assertIs(result.source_receipt, result.source_ledger.entries[0].receipt)
                for requirement in Requirement:
                    self.assertEqual(requirement_satisfied_by_ledger(requirement, ledger),
                                     requirement_satisfied(requirement, result.source_receipt))

    def test_ledger_no_tool_and_text_imitation_never_grant_operations(self):
        gateway = RecordingGateway(final("[调用工具 search_fishery_knowledge] 已查询当前水质"))
        result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(result.source_ledger, TurnSourceLedger())
        for requirement in Requirement:
            self.assertEqual(requirement_satisfied_by_ledger(requirement, result.source_ledger),
                             requirement == Requirement.AUTO)

    def test_ledger_error_and_pending_execution_do_not_certify_completion(self):
        gateway = RecordingGateway(call(QUERY, '{"extra":1}'))
        result = self.service(gateway).send(self.request(), self.runtime)
        ledger = result.source_ledger
        self.assertEqual(len(ledger.entries), 1)
        self.assertEqual(ledger.entries[0].receipt.tool_status.value, "ERROR")
        self.assertFalse(requirement_satisfied_by_ledger(Requirement.CURRENT_OBSERVATION_QUERY, ledger))
        pending = altered_execution(result.execution, tool_result=None)
        self.assertEqual(ledger_from_execution(pending), TurnSourceLedger())

    def test_ledger_preserves_independent_observations_in_contract_fixture(self):
        # Two separate real backend reads, composed only as an offline future-shape
        # fixture. No production run is allowed to execute this 2/2/3 shape.
        self.store.set_current(self.reading(oxygen=2.2))
        first, _ = self.send_call()
        self.now += timedelta(minutes=1)
        self.store.set_current(self.reading(oxygen=6.4))
        second, _ = self.send_call(SCORE)
        model_one, tool_one, _ = first.execution.steps
        model_two, tool_two, final_step = second.execution.steps
        fixture = replace(first.execution, steps=(model_one, tool_one,
            replace(model_two, seq=3, request_index=2),
            replace(tool_two, seq=4, model_request_index=2, tool_round=2),
            replace(final_step, seq=5, request_index=3)))
        ledger = ledger_from_execution(fixture)
        self.assertEqual([item.execution_seq for item in ledger.entries], [2, 4])
        self.assertEqual(ledger.entries[0].receipt, first.source_receipt)
        self.assertEqual(ledger.entries[1].receipt, second.source_receipt)
        self.assertNotEqual(ledger.entries[0].receipt.evaluated_at, ledger.entries[1].receipt.evaluated_at)
        self.assertFalse(ledger.entries[0].receipt.has_score)
        self.assertTrue(ledger.entries[1].receipt.has_score)
        for requirement in (Requirement.CURRENT_OBSERVATION_QUERY, Requirement.CURRENT_SCORE_EVALUATION):
            self.assertTrue(requirement_satisfied_by_ledger(requirement, ledger))
        self.assertFalse(requirement_satisfied_by_ledger(Requirement.PROJECT_KNOWLEDGE_SEARCH, ledger))
        with self.assertRaises(ValueError):
            receipt_from_execution(fixture)
        # Each correlation is checked independently, rather than borrowing another result.
        broken = replace(fixture, steps=(*fixture.steps[:3], replace(fixture.steps[3],
            tool_call_id="unmatched"), fixture.steps[4]))
        ledger = ledger_from_execution(broken)
        self.assertTrue(requirement_satisfied_by_ledger(Requirement.CURRENT_OBSERVATION_QUERY, ledger))
        self.assertFalse(requirement_satisfied_by_ledger(Requirement.CURRENT_SCORE_EVALUATION, ledger))

    def test_ledger_typed_immutable_summary_and_history_boundary(self):
        result, _ = self.send_call(KNOWLEDGE, knowledge=KnowledgeFixture())
        ledger = result.source_ledger
        draft = list(ledger.entries)
        copy = TurnSourceLedger(draft)
        draft.clear()
        self.assertEqual(copy, ledger)
        with self.assertRaises(FrozenInstanceError):
            ledger.entries[0].tool_round = 2
        for bad in ({"entries":[]}, result.to_dict(), "tool executed"):
            with self.assertRaises(TypeError):
                ledger_from_execution(bad)
            with self.assertRaises(TypeError):
                requirement_satisfied_by_ledger(Requirement.AUTO, bad)
        with self.assertRaises(TypeError):
            requirement_satisfied_by_ledger("AUTO", ledger)
        with self.assertRaises(ValueError):
            TurnSourceLedger((ledger.entries[0], ledger.entries[0]))
        self.assertNotIn("source_ledger", result.to_dict())
        for field in ("source_ledger", "tool_calls", "tool_result"):
            with self.assertRaises(AssistantError):
                AssistantHistoryTurn.from_dict({"user":"u", "assistant":"a",
                    "completed_at":self.now.isoformat(), field:ledger.to_dict()})
        text = json.dumps(ledger.to_dict()) + repr(ledger)
        for forbidden in ("fictional-query", "fictional evidence text", "fixture-source", "fixture-evidence"):
            self.assertNotIn(forbidden, text)

    def send_call(self, name=QUERY, requirement=Requirement.AUTO, *, knowledge=None):
        if knowledge is not None:
            self.registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=knowledge)
        arguments = '{"query":"fictional-query"}' if name == KNOWLEDGE else "{}"
        gateway = RecordingGateway(call(name, arguments), final("scripted final"))
        request = replace(self.request(), source_requirement=requirement)
        result = self.service(gateway, (name,)).send(request, self.runtime)
        for required in Requirement:
            self.assertEqual(requirement_satisfied_by_ledger(required, result.source_ledger),
                             requirement_satisfied(required, result.source_receipt))
        self.assertLessEqual(len(gateway.requests), 2)
        self.assertEqual(gateway.requests[0].tool_choice, "auto")
        if len(gateway.requests) == 2:
            self.assertEqual(gateway.requests[1].tool_choice, "none")
        return result, gateway

    def test_auto_concept_no_tool_none_receipt_still_commits(self):
        gateway = RecordingGateway(final("溶氧是水中的氧气。"))
        with patch.object(self.reader, "query", side_effect=AssertionError("no implicit read")):
            result = self.service(gateway).send(self.request("什么是溶氧？"), self.runtime)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual(result.source_receipt, TurnSourceReceipt())
        self.assertTrue(requirement_satisfied(Requirement.AUTO, result.source_receipt))
        self.assertEqual(len(gateway.requests), 1)

    def test_current_ok_receipt_and_requirement(self):
        self.store.set_current(self.reading())
        original = self.store.get_current()
        result, _ = self.send_call(requirement=Requirement.CURRENT_OBSERVATION_QUERY)
        receipt = result.source_receipt
        self.assertEqual(receipt.sources, frozenset({Source.CURRENT_TOOL_OBSERVATION}))
        self.assertEqual(receipt.quality, Quality.VALID)
        self.assertEqual(receipt.freshness, Freshness.FRESH)
        self.assertEqual(len(receipt.available_fields), 3)
        self.assertEqual(receipt.evaluated_at, self.now.isoformat())
        self.assertTrue(receipt.observation_query_completed)
        self.assertTrue(receipt.has_observation)
        self.assertFalse(receipt.score_evaluation_completed)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertIs(self.store.get_current(), original)

    def test_no_data_confirms_query_but_not_observation(self):
        result, _ = self.send_call(requirement=Requirement.CURRENT_OBSERVATION_QUERY)
        self.assertEqual(result.source_receipt.tool_status.value, "NO_DATA")
        self.assertFalse(result.source_receipt.sources)
        self.assertTrue(result.source_receipt.observation_query_completed)
        self.assertFalse(result.source_receipt.has_observation)
        self.assertIsNone(result.source_receipt.evaluated_at)
        self.assertIsNone(result.error_code)
        self.assertTrue(result.to_dict()["successful_turn"])
        auto, _ = self.send_call()
        self.assertTrue(auto.to_dict()["successful_turn"])

    def test_partial_invalid_stale_keep_limited_observation(self):
        for reading in (self.reading(ph=None), self.reading(ph="invalid"),
                        replace(self.reading(), observed_at=self.now-timedelta(hours=1)),
                        replace(self.reading(ph=None), observed_at=self.now-timedelta(hours=1)),
                        self.reading(temp=None, ph=None, oxygen=None)):
            with self.subTest(quality=reading.quality, observed=reading.observed_at):
                self.store.set_current(reading)
                result, _ = self.send_call(requirement=Requirement.CURRENT_OBSERVATION_QUERY)
                receipt = result.source_receipt
                self.assertEqual(receipt.sources, frozenset({Source.CURRENT_TOOL_OBSERVATION}))
                self.assertEqual(receipt.quality, reading.quality)
                self.assertEqual(receipt.freshness, Freshness.STALE if reading.observed_at < self.now else Freshness.FRESH)
                self.assertEqual(receipt.available_fields, tuple(key for key in
                    ("temperature_c", "ph", "dissolved_oxygen_mg_l") if getattr(reading, key) is not None))
                self.assertTrue(result.to_dict()["successful_turn"])

    def test_score_ok_grants_score_and_actual_observation(self):
        self.store.set_current(self.reading())
        result, _ = self.send_call(SCORE, Requirement.CURRENT_SCORE_EVALUATION)
        self.assertEqual(result.source_receipt.sources,
                         frozenset({Source.CURRENT_TOOL_SCORE, Source.CURRENT_TOOL_OBSERVATION}))
        self.assertTrue(requirement_satisfied(Requirement.CURRENT_OBSERVATION_QUERY, result.source_receipt))
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_partial_score_is_available_with_partial_metadata(self):
        self.store.set_current(self.reading(ph=None))
        result, _ = self.send_call(SCORE, Requirement.CURRENT_SCORE_EVALUATION)
        receipt = result.source_receipt
        self.assertIn(Source.CURRENT_TOOL_SCORE, receipt.sources)
        self.assertEqual(receipt.tool_status.value, "PARTIAL")
        self.assertEqual(receipt.quality, Quality.PARTIAL)
        self.assertNotIn("ph", receipt.available_fields)
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_not_scorable_grants_only_invalid_observation(self):
        self.store.set_current(self.reading(ph="invalid"))
        result, _ = self.send_call(SCORE, Requirement.CURRENT_SCORE_EVALUATION)
        receipt = result.source_receipt
        self.assertEqual(receipt.tool_status.value, "NOT_SCORABLE")
        self.assertEqual(receipt.sources, frozenset({Source.CURRENT_TOOL_OBSERVATION}))
        self.assertEqual(receipt.quality, Quality.INVALID)
        self.assertTrue(receipt.score_evaluation_completed)
        self.assertFalse(receipt.has_score)
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_score_no_data_grants_neither_source(self):
        result, _ = self.send_call(SCORE, Requirement.CURRENT_SCORE_EVALUATION)
        self.assertEqual(result.source_receipt.tool_status.value, "NO_DATA")
        self.assertFalse(result.source_receipt.sources)
        self.assertTrue(result.source_receipt.score_evaluation_completed)
        self.assertTrue(result.source_receipt.observation_query_completed)
        self.assertFalse(result.source_receipt.has_score)
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_stale_score_still_marked_stale_not_fresh(self):
        self.store.set_current(replace(self.reading(), observed_at=self.now-timedelta(hours=1)))
        result, _ = self.send_call(SCORE, Requirement.CURRENT_SCORE_EVALUATION)
        self.assertIn(Source.CURRENT_TOOL_SCORE, result.source_receipt.sources)
        self.assertEqual(result.source_receipt.freshness, Freshness.STALE)

    def test_knowledge_ok_certifies_search_and_evidence(self):
        result, _ = self.send_call(KNOWLEDGE, Requirement.PROJECT_KNOWLEDGE_SEARCH, knowledge=KnowledgeFixture())
        receipt = result.source_receipt
        self.assertEqual(receipt.sources, frozenset({Source.RETRIEVED_PROJECT_EVIDENCE}))
        self.assertTrue(receipt.project_search_completed)
        self.assertTrue(receipt.has_project_evidence)
        self.assertEqual(receipt.evidence_count, 1)
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_no_match_satisfies_search_not_evidence_presence(self):
        result, _ = self.send_call(KNOWLEDGE, Requirement.PROJECT_KNOWLEDGE_SEARCH, knowledge=FakeKnowledgeService())
        receipt = result.source_receipt
        self.assertTrue(receipt.project_search_completed)
        self.assertFalse(receipt.has_project_evidence)
        self.assertFalse(receipt.sources)
        self.assertEqual(receipt.evidence_count, 0)
        self.assertEqual(receipt.tool_status.value, "NO_MATCH")
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_tool_error_grants_no_sources_no_second_request(self):
        gateway = RecordingGateway(call())
        with patch.object(self.reader, "query", side_effect=RuntimeError("fictional-private-details")):
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertFalse(result.source_receipt.sources)
        self.assertEqual(result.source_receipt.tool_status.value, "ERROR")
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(len(gateway.requests), 1)
        for requirement in Requirement:
            self.assertEqual(requirement_satisfied(requirement, result.source_receipt),
                             requirement == Requirement.AUTO)

    def test_imitation_never_grants_receipt_and_auto_unchanged(self):
        for requirement in Requirement:
            with self.subTest(requirement=requirement):
                gateway = RecordingGateway(final("[调用工具 search_fishery_knowledge ...]"))
                request = replace(self.request(), source_requirement=requirement)
                with patch.object(self.reader, "query", side_effect=AssertionError("no implicit execution")):
                    result = self.service(gateway).send(request, self.runtime)
                self.assertEqual(result.source_receipt, TurnSourceReceipt())
                self.assertEqual(result.to_dict()["successful_turn"], requirement == Requirement.AUTO)
                self.assertEqual(len(gateway.requests), 1)

    def test_wrong_tool_cannot_satisfy_score_or_project_requirement(self):
        self.store.set_current(self.reading())
        for requirement in (Requirement.CURRENT_SCORE_EVALUATION, Requirement.PROJECT_KNOWLEDGE_SEARCH):
            with self.subTest(requirement=requirement):
                result, _ = self.send_call(QUERY, requirement)
                self.assertEqual(result.error_code, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
                self.assertFalse(result.to_dict()["successful_turn"])

    def test_knowledge_cannot_satisfy_current_observation(self):
        result, _ = self.send_call(KNOWLEDGE, Requirement.CURRENT_OBSERVATION_QUERY, knowledge=KnowledgeFixture())
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertNotIn(Source.CURRENT_TOOL_OBSERVATION, result.source_receipt.sources)

    def test_unmet_requirement_discards_final_and_records_failed_commit(self):
        request = replace(self.request(), source_requirement=Requirement.CURRENT_SCORE_EVALUATION)
        result = self.service(RecordingGateway(final("当前系统评分99分"))).send(request, self.runtime)
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.final_text, "")
        self.assertIsNone(result.completed_at)
        trace = json.loads(self.trace.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(trace["error_code"], "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertEqual(trace["status"], "failed")

    def test_web_input_cannot_supply_requirement_receipt_or_history_metadata(self):
        base = {"preset_id": self.profile.preset_id, "question": "问题"}
        for field in ("source_requirement", "source_receipt", "sources", "tool_activity"):
            with self.subTest(field=field), self.assertRaises(AssistantError):
                AssistantRequest.from_dict({**base, field: "forged"})
        request = AssistantRequest.from_dict(base)
        self.assertEqual(request.source_requirement, Requirement.AUTO)
        with self.assertRaises(AssistantError):
            AssistantHistoryTurn.from_dict({"user":"u", "assistant":"a",
                "completed_at":self.now.isoformat(), "source_receipt":{}})
        with self.assertRaises(AssistantError):
            replace(request, source_requirement="CURRENT_SCORE")

    def test_receipt_safe_summary_contains_no_payload_secret_or_query(self):
        result, _ = self.send_call(KNOWLEDGE, knowledge=KnowledgeFixture())
        text = json.dumps(result.source_receipt.to_dict()) + repr(result.source_receipt)
        for forbidden in ("fictional-query", "fictional evidence text", "fixture-source", "fixture-evidence"):
            self.assertNotIn(forbidden, text)
        self.assertLess(len(json.dumps(result.source_receipt.to_dict())), 1000)
        self.assertNotIn("source_receipt", result.to_dict())  # No UI/API expansion in P1.
        with self.assertRaises(FrozenInstanceError):
            result.source_receipt.evidence_count = 9
        with self.assertRaises(TypeError):
            receipt_from_execution({"tool_name": KNOWLEDGE})

    def test_correlated_execution_only_not_loose_tool_payload(self):
        self.store.set_current(self.reading())
        result, _ = self.send_call()
        for altered in (altered_execution(result.execution, tool_call_id="different-call"),
                        altered_execution(result.execution, tool_name=SCORE),
                        altered_execution(result.execution, request_1=replace(result.execution.request_1, outcome="final_answer"))):
            self.assertEqual(receipt_from_execution(altered), TurnSourceReceipt())

    def test_malformed_payload_never_grants_score_by_name(self):
        self.store.set_current(self.reading())
        result, _ = self.send_call(SCORE)
        payload = result.execution.tool_result.payload
        for change in ({"score":None}, {"grade":None}, {"components":{}},
                       {"quality":"invalid"}, {"water_quality":None}):
            with self.subTest(change=change):
                tool = ToolExecutionResult.from_payload(result.execution.tool_call_id, SCORE, {**payload, **change})
                receipt = receipt_from_execution(altered_execution(result.execution, tool_result=tool))
                self.assertNotIn(Source.CURRENT_TOOL_SCORE, receipt.sources)
                self.assertFalse(receipt.score_evaluation_completed)
        for change in ({"quality":"bogus"}, {"observed_at":"invalid-time"}, {"ph":-99}):
            tool = ToolExecutionResult.from_payload(result.execution.tool_call_id, SCORE,
                {**payload, "water_quality":{**payload["water_quality"], **change}})
            receipt = receipt_from_execution(altered_execution(result.execution, tool_result=tool))
            self.assertFalse(receipt.sources)
            self.assertFalse(receipt.observation_query_completed)
            self.assertFalse(receipt.score_evaluation_completed)

    def test_knowledge_inconsistent_count_no_match_or_empty_evidence_fail_closed(self):
        result, _ = self.send_call(KNOWLEDGE, knowledge=KnowledgeFixture())
        for payload in ({"status":"OK", "result_count":1, "evidence":[]},
                        {"status":"NO_MATCH", "result_count":1, "evidence":[{}]},
                        {"status":"OK", "result_count":1, "evidence":[{}]}):
            tool = ToolExecutionResult.from_payload(result.execution.tool_call_id, KNOWLEDGE, payload)
            receipt = receipt_from_execution(altered_execution(result.execution, tool_result=tool))
            self.assertFalse(receipt.sources)
            self.assertFalse(receipt.project_search_completed)

    def test_second_request_cancelled_keeps_local_receipt_but_not_success(self):
        self.store.set_current(self.reading())
        def cancel(index, request, runtime):
            if index == 2:
                raise GatewayError("USER_CANCELLED")
        gateway = RecordingGateway(call(), final(), callback=cancel)
        result = self.service(gateway).send(self.request(), self.runtime)
        self.assertIn(Source.CURRENT_TOOL_OBSERVATION, result.source_receipt.sources)
        self.assertEqual(result.status, Status.CANCELLED)
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(len(gateway.requests), 2)

    def test_typed_satisfaction_rejects_untrusted_shapes(self):
        with self.assertRaises(TypeError):
            requirement_satisfied("AUTO", TurnSourceReceipt())
        with self.assertRaises(TypeError):
            requirement_satisfied(Requirement.AUTO, {"sources":[]})

    def test_receipt_freezes_collections_and_omits_private_source(self):
        sources = {Source.CURRENT_TOOL_OBSERVATION}
        fields = ["ph"]
        receipt = TurnSourceReceipt(sources=sources, available_fields=fields)
        sources.clear(); fields.clear()
        self.assertEqual(receipt.sources, frozenset({Source.CURRENT_TOOL_OBSERVATION}))
        self.assertEqual(receipt.available_fields, ("ph",))
        self.store.set_current(replace(self.reading(), source="fictional-private-path-and-secret"))
        result, _ = self.send_call()
        self.assertNotIn("fictional-private-path-and-secret",
                         json.dumps(result.source_receipt.to_dict()) + repr(result.source_receipt))

    def test_requirement_failure_uses_existing_request_handle(self):
        handle = RequestHandle(); handle.start()
        gateway = RecordingGateway(final("没有真实调用"))
        with request_scope(handle):
            result = self.service(gateway).send(
                replace(self.request(), source_requirement=Requirement.CURRENT_SCORE_EVALUATION), self.runtime)
        self.assertEqual(handle.public_info()["error_code"], "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(len(gateway.requests), 1)

    def test_negative_business_results_satisfy_only_completed_operations(self):
        cases = ((QUERY, None, {Requirement.CURRENT_OBSERVATION_QUERY}),
                 (SCORE, None, {Requirement.CURRENT_OBSERVATION_QUERY, Requirement.CURRENT_SCORE_EVALUATION}),
                 (SCORE, self.reading(ph="invalid"),
                  {Requirement.CURRENT_OBSERVATION_QUERY, Requirement.CURRENT_SCORE_EVALUATION}),
                 (KNOWLEDGE, None, {Requirement.PROJECT_KNOWLEDGE_SEARCH}))
        for name, reading, satisfied in cases:
            with self.subTest(name=name, quality=reading.quality if reading else None):
                if reading:
                    self.store.set_current(reading)
                result, _ = self.send_call(name, knowledge=FakeKnowledgeService() if name == KNOWLEDGE else None)
                receipt = result.source_receipt
                for requirement in Requirement:
                    self.assertEqual(requirement_satisfied(requirement, receipt),
                                     requirement == Requirement.AUTO or requirement in satisfied)
                self.assertFalse(receipt.has_score)
                self.assertFalse(receipt.has_project_evidence)

    def test_score_proven_read_satisfies_query_without_extra_execution(self):
        for reading in (None, self.reading(), self.reading(ph=None), self.reading(ph="invalid")):
            with self.subTest(quality=reading.quality if reading else None):
                if reading:
                    self.store.set_current(reading)
                with patch.object(self.reader, "query", wraps=self.reader.query) as query:
                    result, gateway = self.send_call(SCORE, Requirement.CURRENT_OBSERVATION_QUERY)
                self.assertTrue(result.to_dict()["successful_turn"])
                self.assertTrue(result.source_receipt.observation_query_completed)
                self.assertEqual(query.call_count, 1)
                self.assertEqual(len(gateway.requests), 2)

    def test_malformed_no_data_is_not_completed_query_or_evaluation(self):
        for name in (QUERY, SCORE):
            result, _ = self.send_call(name)
            payload = result.execution.tool_result.payload
            changes = [{"water_quality":{}}, {"status":"OK"}]
            changes += ([{"findings":[{}]}] if name == QUERY else [
                {"score":1}, {"components":{"ph":{}}}, {"quality":"valid"},
                {"evaluated_at":self.now.isoformat()}])
            malformed = [{**payload, **change} for change in changes]
            malformed.append({key:value for key,value in payload.items() if key != "water_quality"})
            malformed.append({"status":"NO_DATA"})
            for data in malformed:
                with self.subTest(name=name, fields=tuple(data)):
                    tool = ToolExecutionResult.from_payload(result.execution.tool_call_id, name, data)
                    receipt = receipt_from_execution(altered_execution(result.execution, tool_result=tool))
                    self.assertFalse(receipt.sources)
                    self.assertFalse(receipt.observation_query_completed)
                    self.assertFalse(receipt.score_evaluation_completed)
                    self.assertFalse(receipt.project_search_completed)

    def test_malformed_not_scorable_does_not_certify_evaluation(self):
        self.store.set_current(self.reading(ph="invalid"))
        result, _ = self.send_call(SCORE)
        payload = result.execution.tool_result.payload
        for change in ({"score":15}, {"grade":"GOOD"}, {"components":{"ph":{}}},
                       {"quality":"valid"}, {"freshness":"stale"}):
            with self.subTest(change=change):
                tool = ToolExecutionResult.from_payload(result.execution.tool_call_id, SCORE, {**payload, **change})
                receipt = receipt_from_execution(altered_execution(result.execution, tool_result=tool))
                self.assertTrue(receipt.observation_query_completed)  # Independent canonical read remains valid.
                self.assertFalse(receipt.has_score)
                self.assertFalse(requirement_satisfied(Requirement.CURRENT_SCORE_EVALUATION, receipt))

    def test_payload_sources_do_not_substitute_for_completed_operation(self):
        receipt = TurnSourceReceipt(sources=frozenset(Source))
        for requirement in Requirement:
            self.assertEqual(requirement_satisfied(requirement, receipt), requirement == Requirement.AUTO)

    def test_malformed_json_result_never_certifies_operation(self):
        result, _ = self.send_call()
        tool = replace(result.execution.tool_result, _content_json="{")
        receipt = receipt_from_execution(altered_execution(result.execution, tool_result=tool))
        self.assertFalse(receipt.sources)
        self.assertFalse(receipt.observation_query_completed)

    def test_completed_query_does_not_override_followup_failure(self):
        def fail(index, request, runtime):
            if index == 2:
                raise GatewayError("READ_TIMEOUT")
        gateway = RecordingGateway(call(), final(), callback=fail)
        request = replace(self.request(), source_requirement=Requirement.CURRENT_OBSERVATION_QUERY)
        result = self.service(gateway).send(request, self.runtime)
        self.assertTrue(requirement_satisfied(request.source_requirement, result.source_receipt))
        self.assertFalse(result.source_receipt.has_observation)  # NO_DATA query legitimately completed.
        self.assertEqual(result.error_code, "READ_TIMEOUT")
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(result.final_text, "")
        self.assertIsNone(result.completed_at)
        self.assertEqual(len(gateway.requests), 2)

    def test_requirement_names_only_describe_operations(self):
        self.assertEqual({item.value for item in Requirement}, {
            "AUTO", "CURRENT_OBSERVATION_QUERY", "CURRENT_SCORE_EVALUATION", "PROJECT_KNOWLEDGE_SEARCH"})
        for old in ("CURRENT_OBSERVATION", "CURRENT_SCORE", "PROJECT_EVIDENCE"):
            with self.assertRaises(ValueError):
                Requirement(old)
        for field in ("observation_query_completed", "score_evaluation_completed", "project_search_completed"):
            with self.assertRaises(ValueError):
                TurnSourceReceipt(**{field:1})
