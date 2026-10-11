"""Analysis v1: fixed grounding plus the existing bounded coordinator, offline."""

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fishery_ai.application import result_to_dict
from fishery_ai.composition import build_offline_demo
from fishery_ai.contracts import AnalysisRequest, Mode, Status, Usage, UsageSource, WaterQualityReading, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import ModelProfile, ModelCapabilities, ProfileRegistry, ModelResponse, ModelToolCall, GatewayError
from fishery_ai.model_options import Support
from fishery_ai.providers import AuthSpec
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools.policy import ToolPolicy
from fishery_ai.tools import ToolRegistry
from tests.tools.test_tool_conversation import RecordingGateway

NAME = "get_current_water_quality"
NOW = parse_time("2026-10-06T05:00:00Z")
FINAL = '{"inference":"依据程序事实分析", "recommendations":["加强监测"], "uncertainty":[]}'
KNOWLEDGE = "search_fishery_knowledge"


class FakeKnowledge:
    """Binds the Knowledge Tool without an index; no evidence means a NO_MATCH payload."""

    backend = "portable"

    def search(self, query, *, top_k=5, retrieved_at=None, intent_text=None):
        return ()


class AnalysisToolTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline Analysis tests"))
            guard.start(); self.addCleanup(guard.stop)
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.app, _ = build_offline_demo(trace_path=self.root / "trace.jsonl")
        self.app.clock = lambda: NOW
        self.profile = ModelProfile("analysis-fixture", "Fictional", "local", "http://fixture.invalid/v1",
            "fictional-model", auth_spec=AuthSpec.NONE, max_retries=1,
            capabilities=ModelCapabilities(tool_calling=Support.SUPPORTED, streaming=Support.SUPPORTED,
                service_id="custom", adapter_id="generic_openai_chat", base_url="http://fixture.invalid/v1", model_id="fictional-model"))
        self.app.profiles = ProfileRegistry([self.profile], CredentialStore(process_env={}))
        self.app.tool_policy = ToolPolicy("analysis", True, (NAME,))
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: NOW)
        self.app.tool_registry = ToolRegistry(self.reader, self.app.diagnosis)
        self.initial = self.reading()
        self.store.set_current(self.initial)
        self.usage = Usage(10, 2, 12, source=UsageSource.PROVIDER)

    def reading(self, **values):
        return WaterQualityReading.from_raw({"temp":28,"ph":7.5,"oxygen":6, **values},
            observed_at=NOW, retrieved_at=NOW, source="fake:sensor", stale_after_s=300)

    def run_analysis(self, *responses, gateway=None):
        self.app.gateway = gateway or RecordingGateway(*responses)
        return self.app.analyze(AnalysisRequest(Mode.CHAT, self.profile.profile_id, "现在水质怎么样？"),
            reading=self.initial, evaluated_at=NOW)

    def call(self, name=NAME, args="{}", call_id="analysis-call"):
        return ModelResponse(None, self.usage, tool_calls=(ModelToolCall(call_id,name,args),), finish_reason="tool_calls")

    def final(self):
        return ModelResponse(FINAL, self.usage, reasoning_content="fictional reasoning", finish_reason="stop")

    def test_policy_off_keeps_original_request_and_no_executor(self):
        self.app.tool_policy = ToolPolicy("analysis", False, ())
        with patch("fishery_ai.tool_conversation.ToolExecutor", side_effect=AssertionError("disabled")):
            result = self.run_analysis(self.final())
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(self.app.gateway.requests[0].tools, ())
        self.assertIsNone(self.app.gateway.requests[0].tool_choice)
        self.assertFalse(result.tool_activity.enabled)
        self.assertFalse(result.tool_activity.called)
        self.assertEqual(result.tool_activity.request_1["outcome"], "final_answer")
        self.assertEqual(result.tool_activity.usage.request_count, 1)

    def test_parameterized_tool_argument_summary_never_echoes_the_query(self):
        # B6: a tool with declared parameters must not be reported as called with "{}" ,
        # and the argument values must not reach the Activity projection at all.
        secret_query = "鳗鲡适宜溶氧范围"
        self.app.tool_registry = ToolRegistry(self.reader, self.app.diagnosis, knowledge=FakeKnowledge())
        self.app.tool_policy = ToolPolicy("analysis", True, (KNOWLEDGE,))
        result = self.run_analysis(self.call(KNOWLEDGE, json.dumps({"query": secret_query}, ensure_ascii=False)),
                                   self.final())
        data = result_to_dict(result)
        activity = data["tool_activity"]
        self.assertEqual(activity["tool_name"], KNOWLEDGE)
        self.assertEqual(activity["arguments_summary"], "参数已提供（内容未展示）")
        self.assertEqual(activity["result_status"], "NO_MATCH")
        self.assertNotIn(secret_query, json.dumps(activity, ensure_ascii=False))

    def test_disabled_model_failure_is_recorded_without_tool_execution(self):
        self.app.tool_policy = ToolPolicy("analysis", False, ())
        gateway = RecordingGateway()
        with patch.object(gateway, "complete", side_effect=GatewayError("READ_TIMEOUT")):
            result = self.run_analysis(gateway=gateway)
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.tool_activity.request_1["outcome"], "failed")
        self.assertEqual(result.tool_activity.request_1["error_code"], "READ_TIMEOUT")
        self.assertEqual(result.tool_activity.usage.request_count, 1)
        self.assertIsNone(result.usage.total_tokens)
        self.assertFalse(result.tool_activity.called)

    def test_enabled_model_direct_answer_does_not_force_tool_read(self):
        with patch.object(self.reader, "query", side_effect=AssertionError("no eager tools")):
            result = self.run_analysis(self.final())
        self.assertFalse(result.tool_activity.called)
        self.assertEqual(result.tool_activity.allowed_tools, (NAME,))
        self.assertEqual(result.tool_activity.request_2["outcome"], "not_started")
        self.assertTrue(result.structured_parse_ok)

    def test_success_shared_coordinator_context_registry_and_two_requests(self):
        result = self.run_analysis(self.call(), self.final())
        self.assertEqual(result.status, Status.COMPLETED)
        first, second = self.app.gateway.requests
        self.assertIs(first.tools[0], self.app.tool_registry.model_definitions()[0])
        self.assertIn("Observed Facts", first.messages[1].content)
        self.assertIn("Rule Results", first.messages[1].content)
        self.assertIn("RAG Evidence", first.messages[1].content)
        self.assertEqual(second.messages[:2], first.messages)
        self.assertEqual(second.messages[-2].role, "tool")
        self.assertEqual(second.messages[-2].tool_call_id, "analysis-call")
        self.assertEqual(second.messages[-1].role, "user")
        self.assertIn("recommendations", second.messages[-1].content)
        self.assertEqual(second.tool_choice, "none")
        self.assertIs(self.app.gateway.runtimes[0], self.app.gateway.runtimes[1])
        self.assertEqual(self.app.gateway.runtimes[0].max_retries, 0)
        self.assertEqual(result.tool_activity.snapshot_comparison, "consistent")
        self.assertIs(result.observed_facts.water_quality, self.initial)
        self.assertIs(self.store.get_current(), self.initial)
        self.assertEqual(result.reasoning_content, "fictional reasoning")

    def test_unknown_and_unsupported_gate_before_gateway(self):
        for support, error in ((Support.UNKNOWN,"OPTION_UNKNOWN"),(Support.UNSUPPORTED,"OPTION_UNSUPPORTED")):
            self.app.profiles = ProfileRegistry([replace(self.profile,capabilities=replace(self.profile.capabilities,tool_calling=support))],
                                              CredentialStore(process_env={}))
            result = self.run_analysis(self.final())
            self.assertEqual(result.error_code, error)
            self.assertEqual(self.app.gateway.requests, [])
            self.assertEqual(result.tool_activity.request_1["outcome"], "blocked")

    def test_no_data_is_tool_result_and_keeps_initial_facts(self):
        self.app.tool_registry = ToolRegistry(CurrentWaterQualityReader(CurrentSnapshotStore(),stale_after_s=300),self.app.diagnosis)
        result = self.run_analysis(self.call(),self.final())
        self.assertEqual(result.tool_activity.result_status,"NO_DATA")
        self.assertEqual(result.tool_activity.snapshot_comparison,"no_data")
        self.assertIs(result.observed_facts.water_quality,self.initial)
        self.assertTrue(result.uncertainty)

    def test_abnormal_current_tool_findings_come_from_diagnosis(self):
        for values, expected in (({"oxygen":2.2},"OXYGEN_CRITICAL_LOW"),
                                 ({"temp":34,"oxygen":2.2},"TEMP_CRITICAL_HIGH"),
                                 ({"temp":"invalid"},"SENSOR_INVALID")):
            self.initial = self.reading(**values); self.store.set_current(self.initial)
            result = self.run_analysis(self.call(),self.final())
            self.assertEqual(result.status,Status.COMPLETED)
            self.assertIn(expected,[f["code"] for f in result.tool_activity.tool_result["findings"]])
            self.assertEqual(result.rule_results,self.app.diagnosis.diagnose(self.initial))

    def test_query_time_stale_is_separate_and_does_not_mutate_original(self):
        self.app.tool_registry = ToolRegistry(CurrentWaterQualityReader(self.store, stale_after_s=300,
            clock=lambda: NOW + timedelta(hours=1)), self.app.diagnosis)
        result = self.run_analysis(self.call(),self.final())
        self.assertEqual(result.tool_activity.tool_result["water_quality"]["freshness"],"stale")
        self.assertEqual(self.initial.freshness.value,"fresh")
        self.assertEqual(result.tool_activity.snapshot_comparison,"different")
        self.assertTrue(any("不一致" in item for item in result.uncertainty))

    def test_apply_between_requests_never_overwrites_captured_facts(self):
        changed = self.reading(oxygen=2.2)
        gateway = RecordingGateway(self.call(),self.final()); original = gateway.complete
        def complete(request,runtime):
            response = original(request,runtime)
            if len(gateway.requests)==1:self.store.set_current(changed)
            return response
        gateway.complete=complete
        result=self.run_analysis(gateway=gateway)
        self.assertIs(result.observed_facts.water_quality,self.initial)
        self.assertEqual(result.rule_results,())
        self.assertEqual(result.tool_activity.tool_result["water_quality"]["dissolved_oxygen_mg_l"],2.2)
        self.assertEqual(result.tool_activity.snapshot_comparison,"different")

    def test_unknown_tool_and_bad_arguments_cannot_continue(self):
        for name,args,error in (("unregistered", "{}", "UNKNOWN_TOOL"),(NAME,'{"secret":"fictional-hidden"}',"INVALID_TOOL_ARGUMENTS")):
            result=self.run_analysis(self.call(name,args),self.final())
            self.assertEqual(result.error_code,error)
            self.assertTrue(result.tool_activity.requested)
            self.assertFalse(result.tool_activity.called)
            self.assertEqual(len(self.app.gateway.requests),1)
            self.assertNotIn("fictional-hidden",json.dumps(result_to_dict(result)))
            self.assertNotIn("unregistered",json.dumps(result_to_dict(result)))

    def test_multiple_calls_and_second_round_limit(self):
        first=ModelResponse(None,tool_calls=(ModelToolCall("a",NAME,"{}"),ModelToolCall("b",NAME,"{}")))
        result=self.run_analysis(first,self.final())
        self.assertEqual(result.error_code,"TOOL_CALL_LIMIT")
        self.assertFalse(result.tool_activity.called)
        result=self.run_analysis(self.call(),self.call(call_id="again"))
        self.assertEqual(result.error_code,"TOOL_ROUND_LIMIT")
        self.assertEqual(len(self.app.gateway.requests),2)
        self.assertFalse(result.structured_parse_ok)

    def test_execution_failure_is_safe(self):
        with patch.object(self.reader,"query",side_effect=RuntimeError("fictional-private-path")):
            result=self.run_analysis(self.call(),self.final())
        self.assertEqual(result.error_code,"TOOL_EXECUTION_ERROR")
        self.assertNotIn("fictional-private-path",json.dumps(result_to_dict(result)))

    def test_cancellation_after_tool_prevents_second_request(self):
        handle=RequestHandle();handle.start(); original=self.reader.query
        def query():
            view=original();handle.cancel();return view
        with request_scope(handle),patch.object(self.reader,"query",side_effect=query):
            result=self.run_analysis(self.call(),self.final())
        self.assertEqual(result.status,Status.CANCELLED)
        self.assertEqual(result.error_code,"USER_CANCELLED")
        self.assertEqual(len(self.app.gateway.requests),1)
        self.assertFalse(result.structured_parse_ok)

    def test_usage_trace_and_public_activity(self):
        result=self.run_analysis(self.call(),self.final())
        self.assertEqual(result.usage.total_tokens,24)
        self.assertEqual(result.tool_activity.usage.request_count,2)
        self.assertEqual(result.tool_activity.request_2["usage"]["total_tokens"],12)
        lines=[json.loads(line) for line in (self.root/"trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lines[0]["trace_id"],lines[1]["trace_id"])
        self.assertEqual(lines[-1]["tool_activity"]["request_2"]["outcome"],"final_answer")
        for forbidden in (FINAL,"fictional reasoning","Observed Facts",str(self.root)):
            self.assertNotIn(forbidden,json.dumps(lines))
        self.assertEqual(result_to_dict(result)["tool_activity"]["arguments_summary"],"{}")

    def test_streaming_enabled_rejected_disabled_preserved(self):
        self.app.gateway=RecordingGateway(self.final())
        events=list(self.app.analyze_stream(AnalysisRequest(Mode.CHAT,self.profile.profile_id,"当前水质？"),reading=self.initial))
        self.assertEqual(events[-1].data["error_code"],"TOOL_STREAMING_NOT_IMPLEMENTED")
        self.assertEqual(self.app.gateway.requests,[])
        self.app.tool_policy=ToolPolicy("analysis",False,())
        events=list(self.app.analyze_stream(AnalysisRequest(Mode.CHAT,self.profile.profile_id,"当前水质？"),reading=self.initial))
        self.assertEqual(events[-1].kind,"completed")
        self.assertEqual(events[-1].data["result"]["tool_activity"]["request_1"]["outcome"], "final_answer")
        self.assertEqual(events[-1].data["result"]["tool_activity"]["usage"]["request_count"], 1)

    def test_disabled_unsolicited_tool_still_rejected(self):
        self.app.tool_policy=ToolPolicy("analysis",False,())
        result=self.run_analysis(self.call())
        self.assertEqual(result.error_code,"UNEXPECTED_TOOL_CALL")
        self.assertFalse(result.tool_activity.called)

    def test_missing_second_usage_preserves_rounds_without_inventing_total(self):
        result=self.run_analysis(self.call(),ModelResponse(FINAL,finish_reason="stop"))
        self.assertEqual(result.tool_activity.usage.request_count,2)
        self.assertEqual(result.tool_activity.usage.reported_count,1)
        self.assertIsNone(result.usage.total_tokens)
        self.assertEqual(result.tool_activity.request_1["usage"]["total_tokens"],12)

    def test_cancel_after_first_model_never_executes_handler(self):
        handle=RequestHandle();handle.start();gateway=RecordingGateway(self.call(),self.final())
        original=gateway.complete
        def complete(request,runtime):
            response=original(request,runtime);handle.cancel();return response
        gateway.complete=complete
        with request_scope(handle),patch.object(self.reader,"query",side_effect=AssertionError("cancelled")):
            result=self.run_analysis(gateway=gateway)
        self.assertEqual(result.error_code,"USER_CANCELLED")
        self.assertEqual(len(gateway.requests),1)
        self.assertFalse(result.tool_activity.called)

    def test_credential_rotation_keeps_same_immutable_snapshot_for_two_rounds(self):
        env={"TEST_KEY":"fictional-before"}
        credentials=CredentialStore(process_env=env)
        profile=replace(self.profile,credential_ref="TEST_KEY",auth_spec=AuthSpec.REQUIRED_BEARER)
        self.app.profiles=ProfileRegistry([profile],credentials);self.app.resolve_secrets=True
        gateway=RecordingGateway(self.call(),self.final());original=gateway.complete
        def complete(request,runtime):
            response=original(request,runtime)
            env["TEST_KEY"]="fictional-after"
            return response
        gateway.complete=complete
        result=self.run_analysis(gateway=gateway)
        self.assertEqual(result.status,Status.COMPLETED)
        self.assertIs(gateway.runtimes[0].credential,gateway.runtimes[1].credential)
        self.assertEqual(gateway.runtimes[1].credential._for_adapter(),"fictional-before")
        self.assertEqual(credentials.resolve("TEST_KEY",AuthSpec.REQUIRED_BEARER)._for_adapter(),"fictional-after")
        text=json.dumps(result_to_dict(result))+(self.root/"trace.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("fictional-before",text);self.assertNotIn("fictional-after",text)

    def test_score_only_analysis_preserves_fixed_facts_and_generic_activity(self):
        score_name = "score_current_water_quality"
        self.app.tool_policy = ToolPolicy("analysis", True, (score_name,))
        self.initial = self.reading(temp=34,oxygen=2.2); self.store.set_current(self.initial)
        result = self.run_analysis(self.call(score_name), self.final())
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual([d.name for d in self.app.gateway.requests[0].tools], [score_name])
        self.assertEqual(result.tool_activity.tool_name, score_name)
        self.assertEqual(result.tool_activity.tool_result["score"], 68.0)
        self.assertEqual(result.tool_activity.result_status, "OK")
        self.assertIs(result.observed_facts.water_quality, self.initial)
        self.assertIn("OXYGEN_CRITICAL_LOW", [f.code for f in result.rule_results])
        self.assertTrue(result.structured_parse_ok)
        traces = [json.loads(line) for line in (self.root/"trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(traces[0]["tool_name"], score_name)
        self.assertNotIn("components", json.dumps(traces))

    def test_both_tools_exposed_but_only_one_selected_or_direct_answer(self):
        score_name = "score_current_water_quality"
        self.app.tool_policy = ToolPolicy("analysis", True, (NAME, score_name))
        for name in (NAME, score_name):
            result=self.run_analysis(self.call(name),self.final())
            self.assertEqual(result.tool_activity.tool_name,name)
            self.assertEqual(len(self.app.gateway.requests),2)
            self.assertEqual([d.name for d in self.app.gateway.requests[0].tools], [NAME,score_name])
        result=self.run_analysis(self.final())
        self.assertFalse(result.tool_activity.called)

    def test_both_tools_still_cannot_execute_two_calls(self):
        score_name="score_current_water_quality"
        self.app.tool_policy=ToolPolicy("analysis",True,(NAME,score_name))
        response=ModelResponse(None,tool_calls=(ModelToolCall("a",NAME,"{}"),ModelToolCall("b",score_name,"{}")))
        with patch.object(self.reader,"query",side_effect=AssertionError("no multi execution")):
            result=self.run_analysis(response)
        self.assertEqual(result.error_code,"TOOL_CALL_LIMIT")
        self.assertEqual(len(self.app.gateway.requests),1)

    def test_score_no_data_partial_and_invalid_still_finish(self):
        score_name="score_current_water_quality"
        self.app.tool_policy=ToolPolicy("analysis",True,(score_name,))
        for current, status in ((None,"NO_DATA"),(self.reading(ph=None),"PARTIAL"),(self.reading(ph="bad"),"NOT_SCORABLE")):
            if current is None:
                self.app.tool_registry=ToolRegistry(CurrentWaterQualityReader(CurrentSnapshotStore(),stale_after_s=300),self.app.diagnosis)
            else:
                self.store.set_current(current);self.app.tool_registry=ToolRegistry(self.reader,self.app.diagnosis)
            result=self.run_analysis(self.call(score_name),self.final())
            self.assertEqual(result.status,Status.COMPLETED)
            self.assertEqual(result.tool_activity.result_status,status)
            self.assertTrue(result.tool_activity.called)

    def test_followup_reinforces_json_without_repair_or_accepting_plain_html(self):
        for text, parsed in ((FINAL,True),("```json\n"+FINAL+"\n```",True),
                             ("普通回答",False),('<p>model text</p>',False),
                             ('{"inference":{},"recommendations":[]}',False),
                             ('{"inference":"ok","recommendations":[{}]}',False),
                             ('{"inference":"ok","recommendations":[],"uncertainty":{}}',False)):
            result=self.run_analysis(self.call(),ModelResponse(text,finish_reason="stop"))
            self.assertEqual(result.structured_parse_ok,parsed)
            self.assertEqual(result.generated_text,text)
            self.assertEqual(len(self.app.gateway.requests),2)
            second=self.app.gateway.requests[1]
            self.assertEqual(second.messages[0],self.app.gateway.requests[0].messages[0])
            self.assertEqual(second.messages[-2].role,"tool")
            self.assertIn("uncertainty",second.messages[-1].content)

    def test_assistant_score_policy_uses_same_coordinator_without_analysis_reminder(self):
        from fishery_ai.tool_conversation import ToolCallingService, MockToolGateway
        from fishery_ai.observability import JsonlTraceSink
        score_name="score_current_water_quality"
        runtime=self.app.profiles.snapshot(self.profile.profile_id)
        service=ToolCallingService(MockToolGateway(),self.app.tool_registry,JsonlTraceSink(self.root/"assistant.jsonl"),
                                   policy=ToolPolicy("assistant",True,(NAME,score_name)))
        result=service.converse("请给当前水质打一个分",runtime)
        self.assertEqual(result.status,Status.COMPLETED)
        self.assertEqual(result.tool_name,score_name)
        self.assertEqual(result.tool_result.payload["score"],100)
        self.assertIn("NOT PROFESSIONAL STANDARD",result.generated_text)
        service.policy=ToolPolicy("assistant",True,(NAME,))
        gateway=RecordingGateway(self.call(score_name))
        service.gateway=gateway
        result=service.converse("当前评分？",runtime)
        self.assertEqual(result.error_code,"TOOL_NOT_ALLOWED")


if __name__ == "__main__": unittest.main()
