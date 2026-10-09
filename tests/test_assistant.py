"""Assistant S1: temporary stores and fictional credentials; all sockets blocked."""

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fishery_ai.assistant import (ALLOWED_PRESET_IDS, AssistantContextBuilder, AssistantError,
    AssistantHistoryTurn, AssistantRequest, AssistantService, assistant_profile)
from fishery_ai.contracts import Status, Usage, UsageSource, WaterQualityReading, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ModelResponse, ModelToolCall, MockGateway, ProfileRegistry
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.presets import preset_profiles
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tool_conversation import ToolCallingService
from fishery_ai.tools import ToolExecutor, ToolRegistry
from fishery_ai.tools.catalog import CATALOG
from fishery_ai.tools.policy import ToolPolicy
from fishery_ai.web import create_app


NOW = parse_time("2026-10-06T01:00:00Z")
QUERY = "get_current_water_quality"
SCORE = "score_current_water_quality"
KNOWLEDGE = "search_fishery_knowledge"
LOCAL = ALLOWED_PRESET_IDS[2]


class FakeKnowledgeService:
    """Binds the Knowledge Tool without an index; this module never calls it."""

    backend = "portable"

    def search(self, query, *, top_k=5, retrieved_at=None, intent_text=None):
        return ()
FAKE_KEY = "fictional-assistant-secret-not-real"


def final(text="概念回答", finish="stop", usage=None):
    return ModelResponse(text, usage=usage or Usage(), finish_reason=finish)


def call(name=QUERY, arguments="{}", call_id="assistant_call"):
    return ModelResponse(None, tool_calls=(ModelToolCall(call_id, name, arguments),), finish_reason="tool_calls")


class RecordingGateway(MockGateway):
    def __init__(self, *responses, callback=None):
        super().__init__(responses=responses)
        self.requests, self.runtimes, self.callback = [], [], callback

    def complete(self, request, runtime):
        self.requests.append(request); self.runtimes.append(runtime)
        if self.callback:
            self.callback(len(self.requests), request, runtime)
        return super().complete(request, runtime)


class AssistantFixture(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Assistant tests forbid network"))
            guard.start(); self.addCleanup(guard.stop)
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.trace = self.root / "trace.jsonl"
        self.traces = JsonlTraceSink(self.trace)
        self.now = NOW
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: self.now)
        self.registry = ToolRegistry(self.reader, DiagnosisService())
        self.profile = assistant_profile(LOCAL)
        self.credentials = CredentialStore(process_env={})
        self.runtime = ProfileRegistry([self.profile], self.credentials).snapshot(self.profile.profile_id)

    def reading(self, **changes):
        return WaterQualityReading.from_raw({"temp": 28, "ph": 7.5, "oxygen": 6, **changes},
            observed_at=NOW, retrieved_at=NOW, source="fictional:sensor", stale_after_s=300)

    def request(self, question="现在水质怎么样？", history=()):
        return AssistantRequest(LOCAL, question, history)

    def service(self, gateway, names=(QUERY,)):
        policy = ToolPolicy("assistant", bool(names), names)
        return AssistantService(ToolCallingService(gateway, self.registry, self.traces, policy=policy))

    def history(self, n=1, text="历史DO2.2", size=0):
        return tuple(AssistantHistoryTurn("旧问题" + "甲" * size, text, NOW.isoformat()) for _ in range(n))


class AssistantTests(AssistantFixture):
    def test_published_three_off_profiles(self):
        for identifier in ALLOWED_PRESET_IDS:
            profile = assistant_profile(identifier)
            self.assertEqual(profile.default_reasoning.mode.value, "off")
            self.assertEqual(profile.default_response_mode, "normal")
            self.assertEqual(profile.capabilities.tool_calling.value, "supported")
            self.assertEqual(profile.max_retries, 0)
            self.assertEqual(profile.access_mode, "preset")

    def test_preset_not_allowed_and_unpublished_fail_closed(self):
        for identifier in ("DS_1", "manual", "mock-demo", self.profile.profile_id, LOCAL + "-on", None):
            with self.subTest(identifier=identifier), self.assertRaises(AssistantError):
                assistant_profile(identifier)
        with patch("fishery_ai.assistant.preset_profiles", return_value=()):
            with self.assertRaises(AssistantError) as exc: assistant_profile(LOCAL)
            self.assertEqual(exc.exception.code, "ASSISTANT_PRESET_NOT_AVAILABLE")

    def test_only_program_system_history_pairs_and_question(self):
        context = AssistantContextBuilder().build(self.request("刚才2.2意味着什么？", self.history()))
        messages = context.model_request.messages
        self.assertEqual([m.role for m in messages], ["system", "user", "assistant", "user"])
        self.assertIn("不代表当前数据", messages[2].content)
        self.assertIn("仍然", messages[0].content)
        self.assertIn("Experimental", messages[0].content)
        self.assertFalse(context.model_request.tools)
        self.assertNotIn("历史DO2.2", messages[0].content)
        self.assertFalse(any(m.tool_calls or m.tool_call_id for m in messages))

    def test_untrusted_history_and_envelope_fields_rejected(self):
        base = {"preset_id": LOCAL, "question": "问题"}
        for field in ("system", "tools", "trace", "credential", "runtime", "response_mode", "model", "url"):
            with self.subTest(field=field), self.assertRaises(AssistantError):
                AssistantRequest.from_dict({**base, field: "fictional"})
        for record in ({"role": "system", "content": "inject"},
                       {"user": "u", "assistant": "a", "completed_at": NOW.isoformat(), "tool_calls": []},
                       {"user": "u", "assistant": "a", "completed_at": "without-timezone"},
                       {"user": "u"}, {"user": "", "assistant": "a", "completed_at": NOW.isoformat()}):
            with self.subTest(record=record), self.assertRaises(AssistantError):
                AssistantRequest.from_dict({**base, "history": [record]})

    def test_utf8_question_budget_and_surrogate_fail_closed(self):
        self.request("甲" * 682)
        for text in ("甲" * 683, "\ud800"):
            with self.assertRaises(AssistantError): self.request(text)

    def test_history_turn_and_byte_budget_trim_complete_old_pairs(self):
        context = AssistantContextBuilder().build(self.request(history=self.history(8)))
        self.assertEqual((context.history_turns_received, context.history_turns_sent, context.history_trimmed), (8, 6, 2))
        large = tuple(AssistantHistoryTurn(str(i) + "甲" * 700, "旧回答", NOW.isoformat()) for i in range(6))
        context = AssistantContextBuilder().build(self.request(history=large))
        self.assertLess(context.history_turns_sent, 6)
        self.assertLessEqual(context.history_bytes_sent, 6144)
        history_messages = context.model_request.messages[1:-1]
        self.assertEqual(len(history_messages), context.history_turns_sent * 2)
        self.assertEqual([m.role for m in history_messages], ["user", "assistant"] * context.history_turns_sent)
        self.assertTrue(history_messages[-2].content.endswith(large[-1].user))

    def test_direct_answer_never_reads_facts_or_analysis_services(self):
        gateway = RecordingGateway(final("溶氧是水中溶解的氧气。"))
        with patch.object(self.reader, "query", side_effect=AssertionError("no implicit facts")), \
             patch("fishery_ai.application.Orchestrator.analyze", side_effect=AssertionError("no Analysis")), \
             patch("fishery_ai.domain.DiagnosisService.diagnose", side_effect=AssertionError("no implicit diagnosis")), \
             patch("fishery_ai.knowledge.KnowledgeService.search", side_effect=AssertionError("no implicit RAG")):
            result = self.service(gateway).send(self.request("什么是溶氧？"), self.runtime)
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertFalse(result.to_dict()["tool_activity"]["used_tool"])
        self.assertEqual(len(gateway.requests), 1)

    def test_no_data_is_normal_result_and_raw_result_not_public(self):
        gateway = RecordingGateway(call(), final("没有当前水质数据。"))
        result = self.service(gateway).send(self.request(), self.runtime)
        public = result.to_dict()
        self.assertEqual(public["tool_activity"]["tool_status"], "NO_DATA")
        self.assertTrue(public["successful_turn"])
        self.assertNotIn("tool_result", public)
        self.assertNotIn("tool_call_id", public)
        self.assertNotIn("messages", public)
        self.assertEqual(gateway.requests[1].tool_choice, "none")
        self.assertEqual([m.role for m in gateway.requests[1].messages][-2:], ["assistant", "tool"])

    def test_low_partial_invalid_stale_facts_go_only_to_tool_follow_up(self):
        for changes, stale in (({"oxygen": 2.2}, False), ({"ph": None}, False),
                               ({"oxygen": "invalid"}, False), ({}, True)):
            with self.subTest(changes=changes, stale=stale):
                original = self.reading(**changes); self.store.set_current(original)
                self.now = NOW + timedelta(hours=1) if stale else NOW
                gateway = RecordingGateway(call(), final("依据查询结果回答"))
                result = self.service(gateway).send(self.request(), self.runtime)
                self.assertEqual(result.status, Status.COMPLETED)
                self.assertEqual(len(gateway.requests[0].messages), 2)
                data = json.loads(gateway.requests[1].messages[-1].content)
                self.assertEqual(data["water_quality"]["freshness"], "stale" if stale else "fresh")
                if changes.get("oxygen") == 2.2:
                    self.assertIn("OXYGEN_CRITICAL_LOW", [f["code"] for f in data["findings"]])
                self.assertIs(self.store.get_current(), original)

    def test_score_policy_exposes_two_tools_but_executes_only_selected_score(self):
        self.store.set_current(self.reading(oxygen=2.2))
        gateway = RecordingGateway(call(SCORE), final("实验评分，不是专业标准"))
        result = self.service(gateway, (QUERY, SCORE)).send(self.request("当前评分？"), self.runtime)
        self.assertEqual([t.name for t in gateway.requests[0].tools], [QUERY, SCORE])
        self.assertEqual(result.to_dict()["tool_activity"]["tool_name"], SCORE)
        self.assertEqual(len(gateway.requests), 2)

    def test_water_and_score_activity_labels_match_the_catalog(self):
        # Step 10: response projections label tools from the Catalog, not from UI copies.
        expected = {entry.name: (entry.display_name, entry.short_description) for entry in CATALOG}
        self.store.set_current(self.reading(oxygen=2.2))
        for name in (QUERY, SCORE):
            with self.subTest(name=name):
                gateway = RecordingGateway(call(name), final("已读取结果"))
                activity = self.service(gateway, (QUERY, SCORE)).send(
                    self.request("现在水质怎么样？"), self.runtime).to_dict()["tool_activity"]
                self.assertEqual(activity["tool_name"], name)
                self.assertEqual((activity["display_name"], activity["display_summary"]), expected[name])

    def test_knowledge_activity_uses_catalog_labels_and_carries_no_water_fields(self):
        # Step 10: a Knowledge call must never be described with water-snapshot semantics.
        service = AssistantService(ToolCallingService(
            RecordingGateway(call(KNOWLEDGE, '{"query":"鳗鲡适宜溶氧"}'), final("背景资料说明")),
            ToolRegistry(self.reader, DiagnosisService(), knowledge=FakeKnowledgeService()),
            self.traces, policy=ToolPolicy("assistant", True, (KNOWLEDGE,))))
        public = service.send(self.request("鳗鲡适宜溶氧范围是多少？"), self.runtime).to_dict()
        activity = public["tool_activity"]
        self.assertTrue(public["successful_turn"])
        self.assertEqual(activity["tool_name"], KNOWLEDGE)
        self.assertEqual(activity["display_name"], "知识检索")
        self.assertEqual(activity["display_summary"],
            next(entry.short_description for entry in CATALOG if entry.name == KNOWLEDGE))
        self.assertIn("不代表当前水质", activity["display_summary"])
        # No service returned evidence, so this is the normal NO_MATCH outcome, not an error.
        self.assertEqual(activity["tool_status"], "NO_MATCH")
        self.assertIsNone(public["error_code"])
        for key in ("observed_at", "evaluated_at", "quality", "freshness"):
            self.assertNotIn(key, activity)
        self.assertNotIn("query", json.dumps(activity, ensure_ascii=False))

    def test_disabled_policy_no_tool_definition_no_read(self):
        gateway = RecordingGateway(final("没有授权Tool，无法查询"))
        with patch.object(self.reader, "query", side_effect=AssertionError("must not read")):
            result = self.service(gateway, ()).send(self.request(), self.runtime)
        self.assertFalse(gateway.requests[0].tools)
        self.assertEqual(result.status, Status.COMPLETED)

    def test_latest_query_uses_new_snapshot_old_result_never_replayed(self):
        self.store.set_current(self.reading(oxygen=2.2))
        first = self.service(RecordingGateway(call(), final("历史DO为2.2"))).send(self.request(), self.runtime)
        history = (AssistantHistoryTurn("现在水质怎么样？", first.final_text, first.completed_at),)
        self.store.set_current(self.reading(oxygen=6.5))
        gateway = RecordingGateway(call(), final("本轮查询DO6.5，不是旧2.2"))
        second = self.service(gateway).send(self.request("现在仍然是2.2吗？", history), self.runtime)
        self.assertIn("历史DO为2.2", gateway.requests[0].messages[2].content)
        self.assertFalse(any(m.role == "tool" or m.tool_calls for m in gateway.requests[0].messages))
        data = json.loads(gateway.requests[1].messages[-1].content)
        self.assertEqual(data["water_quality"]["dissolved_oxygen_mg_l"], 6.5)
        self.assertIn("6.5", second.final_text)
        # Mock fixtures assert the chosen path; this is not proof of real LLM compliance.
        gateway = RecordingGateway(final("刚才2.2是历史低氧读数"))
        with patch.object(self.reader, "query", side_effect=AssertionError("historical explanation need not query")):
            self.service(gateway).send(self.request("刚才2.2意味着什么？", history), self.runtime)

    def test_tool_limits_and_safe_failures_never_commit(self):
        multiple = ModelResponse(None, tool_calls=(ModelToolCall("a", QUERY, "{}"), ModelToolCall("b", SCORE, "{}")))
        cases = (([multiple], "TOOL_CALL_LIMIT"), ([call(), call()], "TOOL_ROUND_LIMIT"),
                 ([call("unknown_fixture")], "UNKNOWN_TOOL"), ([call(arguments='{"x":1}')], "INVALID_TOOL_ARGUMENTS"))
        for responses, code in cases:
            with self.subTest(code=code):
                gateway = RecordingGateway(*responses)
                result = self.service(gateway).send(self.request(), self.runtime)
                self.assertEqual(result.error_code, code)
                self.assertFalse(result.to_dict()["successful_turn"])
                self.assertEqual(result.final_text, "")
                self.assertLessEqual(len(gateway.requests), 2)

    def test_local_tool_error_safe_and_no_follow_up(self):
        gateway = RecordingGateway(call())
        with patch.object(self.reader, "query", side_effect=RuntimeError("fictional private path")):
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(result.error_code, "TOOL_EXECUTION_ERROR")
        self.assertNotIn("private", json.dumps(result.to_dict()))
        self.assertEqual(len(gateway.requests), 1)

    def test_final_commit_gate(self):
        for text, finish, code in (("半条", "length", "ASSISTANT_RESPONSE_TRUNCATED"),
                                  (" ", "stop", "ASSISTANT_RESPONSE_EMPTY"),
                                  ("回答", None, "ASSISTANT_RESPONSE_INCOMPLETE"),
                                  ("回答", "unknown_finish", "ASSISTANT_RESPONSE_INCOMPLETE")):
            with self.subTest(finish=finish, text=text):
                result = self.service(RecordingGateway(final(text, finish))).send(self.request(), self.runtime)
                self.assertEqual(result.error_code, code)
                self.assertFalse(result.to_dict()["successful_turn"])
                self.assertEqual(result.final_text, "")
                self.assertIsNone(result.completed_at)
                trace = json.loads(self.trace.read_text(encoding="utf-8").splitlines()[-1])
                self.assertEqual(trace["error_code"], code)

    def test_follow_up_truncation_does_not_submit_partial_answer(self):
        result = self.service(RecordingGateway(call(), final("部分", "length"))).send(self.request(), self.runtime)
        self.assertEqual(result.error_code, "ASSISTANT_RESPONSE_TRUNCATED")
        self.assertEqual(result.final_text, "")

    def test_cancel_first_request_before_tool(self):
        handle = RequestHandle(); handle.start()
        gateway = RecordingGateway(call(), callback=lambda *_: handle.cancel())
        with request_scope(handle), patch.object(self.reader, "query") as query:
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(result.status, Status.CANCELLED)
        query.assert_not_called(); self.assertEqual(len(gateway.requests), 1)

    def test_cancel_after_tool_before_follow_up(self):
        handle = RequestHandle(); handle.start()
        execute = ToolExecutor.execute
        def cancel_after(executor, tool_call):
            result = execute(executor, tool_call); handle.cancel(); return result
        gateway = RecordingGateway(call(), final())
        with request_scope(handle), patch.object(ToolExecutor, "execute", cancel_after):
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(result.error_code, "USER_CANCELLED")
        self.assertEqual(len(gateway.requests), 1)

    def test_cancel_immediately_before_executor_handler(self):
        handle = RequestHandle(); handle.start()
        execute = ToolExecutor.execute
        def cancel_before(executor, tool_call):
            handle.cancel(); return execute(executor, tool_call)
        with request_scope(handle), patch.object(ToolExecutor, "execute", cancel_before), \
             patch.object(self.reader, "query") as query:
            result = self.service(RecordingGateway(call())).send(self.request(), self.runtime)
        query.assert_not_called()
        self.assertEqual(result.error_code, "USER_CANCELLED")

    def test_cancel_second_request_and_no_partial_answer(self):
        handle = RequestHandle(); handle.start()
        gateway = RecordingGateway(call(), final("不应提交"), callback=lambda index, *_: handle.cancel() if index == 2 else None)
        with request_scope(handle):
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(result.final_text, "")
        self.assertEqual(handle.state, "CANCELLED")
        self.assertEqual(len(gateway.requests), 2)

    def test_cancel_commit_race_and_completion_wins_late_stop(self):
        handle = RequestHandle(); handle.start()
        service = self.service(RecordingGateway(final()))
        run_request = service.coordinator.run_request
        def cancel_before_commit(*args, **kwargs):
            result = run_request(*args, **kwargs); handle.cancel(); return result
        with request_scope(handle), patch.object(service.coordinator, "run_request", cancel_before_commit):
            result = service.send(self.request(), self.runtime)
        self.assertEqual(result.status, Status.CANCELLED)
        handle = RequestHandle(); handle.start()
        with request_scope(handle):
            result = self.service(RecordingGateway(final())).send(self.request(), self.runtime)
        handle.cancel()
        self.assertEqual(handle.state, "COMPLETED")
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_two_usage_runtime_and_policy_snapshot_unchanged(self):
        usage = Usage(input_tokens=3, output_tokens=2, total_tokens=5, source=UsageSource.PROVIDER)
        gateway = RecordingGateway(replace(call(), usage=usage), final(usage=usage))
        result = self.service(gateway).send(self.request(), self.runtime)
        self.assertIs(gateway.runtimes[0], gateway.runtimes[1])
        self.assertEqual(result.execution.usage.request_count, 2)
        self.assertEqual(result.execution.request_2.usage.total_tokens, 5)
        self.assertEqual(result.execution.usage.reported_count, 2)
        self.assertEqual(result.execution.usage.usage.total_tokens, 10)
        self.assertEqual(result.context.history_turns_sent, 0)

    def test_trace_and_repr_no_text_secret_or_tool_body(self):
        profile = assistant_profile(ALLOWED_PRESET_IDS[0])
        credentials = CredentialStore(process_env={profile.credential_ref: FAKE_KEY})
        runtime = ProfileRegistry([profile], credentials).snapshot(profile.profile_id)
        request = AssistantRequest(profile.preset_id, "fictional-private-question", self.history(text="private-old-answer"))
        gateway = RecordingGateway(final("provider echoed " + FAKE_KEY))
        result = self.service(gateway).send(request, runtime)
        self.assertNotIn(FAKE_KEY, json.dumps(result.to_dict()))
        trace = self.trace.read_text(encoding="utf-8")
        for marker in (FAKE_KEY, "private-question", "private-old-answer", "provider echoed", '"tool_result":', "control_token"):
            self.assertNotIn(marker, trace)
        for value in (request, request.history[0], result, result.context):
            self.assertNotIn("private-question", repr(value))
            self.assertNotIn(FAKE_KEY, repr(value))
        self.assertIn("history_turns_sent", trace)

    def test_wrong_runtime_rejected_before_gateway(self):
        gateway = RecordingGateway(final())
        for runtime in (replace(self.runtime, access_mode="managed"),
                        replace(self.runtime, default_response_mode="streaming"),
                        replace(self.runtime, max_retries=1)):
            with self.assertRaises(AssistantError): self.service(gateway).send(self.request(), runtime)
        self.assertFalse(gateway.requests)

    def test_malformed_tool_and_gateway_error_no_retry_or_commit(self):
        malformed = call()
        object.__setattr__(malformed.tool_calls[0], "id", "")
        result = self.service(RecordingGateway(malformed)).send(self.request(), self.runtime)
        self.assertEqual(result.error_code, "MODEL_TOOL_CALL_MALFORMED")
        gateway = RecordingGateway(final(), callback=lambda *_: (_ for _ in ()).throw(GatewayError("READ_TIMEOUT")))
        result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(result.error_code, "READ_TIMEOUT")
        self.assertEqual(len(gateway.requests), 1)
        self.assertFalse(result.to_dict()["successful_turn"])

    def test_trace_failure_cannot_commit_successful_turn(self):
        with patch.object(self.traces, "record_assistant", side_effect=OSError("fictional private path")):
            result = self.service(RecordingGateway(final())).send(self.request(), self.runtime)
        self.assertEqual(result.error_code, "TRACE_WRITE_ERROR")
        self.assertFalse(result.trace_recorded)
        self.assertEqual(result.final_text, "")
        self.assertNotIn("private path", repr(result))


    def test_safe_progress_observer_reports_actual_model_tool_model_phases(self):
        handle = RequestHandle(); handle.start()
        phases = []
        report = handle.report_phase
        def observe(phase):
            report(phase); phases.append(handle.public_info()["phase"])
        gateway = RecordingGateway(call(), final())
        with request_scope(handle), patch.object(handle, "report_phase", observe):
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertEqual(phases, ["REQUEST_1", "RUNNING_TOOL", "REQUEST_2"])
        self.assertEqual(result.status, Status.COMPLETED)
        report("REQUEST_1")
        self.assertEqual(handle.phase, "REQUEST_2")  # Terminal runs cannot regress their phase.
        with self.assertRaises(ValueError): report("fictional prompt text")


class AssistantSelectionRulesTests(AssistantFixture):
    """Rules/schema and scripted model choices, not a deterministic intent router."""

    def test_selection_rules_are_in_program_system_for_every_question(self):
        rules = (
            "现在、当前或最新水质数值、状态、告警", "应使用get_current_water_quality",
            "评分、打分、评级或分项评分", "必须使用score_current_water_quality",
            "内部已经读取当前Snapshot", "同一轮不要再调用get_current_water_quality",
            "未调用score_current_water_quality时", "不得自行生成‘当前系统评分’",
            "当前事实追问", "必须本轮重新查询", "可以使用历史语境",
            "不得用旧历史值冒充当前事实", "不得伪造系统评分",
            "最多选择一个Tool、一个Tool round",
            # Step 9: Knowledge selection rules, phrased around what is still missing.
            "选择Tool看当前回答还缺什么信息",
            "需要当前事实而本轮尚未掌握时用get_current_water_quality",
            "需要项目特有的养殖背景资料时用search_fishery_knowledge",
            "不调用任何Tool",
            "只查询最关键的一项", "明确说明未查询的另一部分",
            "不得用一般常识冒充项目资料或现场事实",
            "不要仅因为Tool可用就试探性检索",
            "用户明确要求查询项目资料", "可以调用search_fishery_knowledge",
            "背景资料而非本轮观测", "不得表述为当前系统数据",
            "不得据此推断当前值", "不得凭印象编造项目内数据或标准",
            # Step 9 closeout: user-provided vs system-observed, tighter history rule,
            # multi-tool wording, explicit NO_MATCH semantics.
            "用户本轮明确提供的现场数值可作为用户提供的信息使用",
            "不得表述为系统当前观测值",
            "也未由get_current_water_quality返回时，不得声称系统掌握当前值",
            "历史中的旧现场值、旧状态、旧评分不能用于回答现在、当前或最新的事实问题",
            "或只是在解释历史内容本身时，不调用任何Tool",
            "NO_MATCH表示检索正常完成但没有合格的项目知识证据",
            "不是Tool执行错误", "不得编造命中内容",
            "即使多个Tool同时可用", "不得并行或顺序请求多个Tool",
        )
        for question in ("现在水质怎么样？", "当前评分多少？", "什么是溶氧？",
                         "现在还是旧值吗？", "刚才旧值是什么意思？"):
            context = AssistantContextBuilder().build(self.request(question, self.history()))
            system = context.model_request.messages[0]
            self.assertEqual(system.role, "system")
            for rule in rules:
                self.assertIn(rule, system.content)
            self.assertEqual(context.model_request.messages[-1].content, question)
            self.assertFalse(context.model_request.tools)  # Policy supplies schema later.

    def test_prompt_names_only_registered_tools_and_carries_no_schema_text(self):
        # Every snake_case token in the prompt must be a real registered tool name, so a
        # typo or a deleted tool cannot survive here. The reverse is deliberately not
        # asserted: the prompt need not mention every name the codebase knows.
        from fishery_ai.tools.registry import (CURRENT_WATER_QUALITY, SEARCH_FISHERY_KNOWLEDGE,
                                               WATER_QUALITY_SCORE)
        context = AssistantContextBuilder().build(self.request("什么是溶氧？", ()))
        prompt = context.model_request.messages[0].content
        # ASCII-only boundaries: CJK characters count as \w, so \b never fires here.
        mentioned = set(re.findall(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])", prompt))
        self.assertEqual(mentioned, {CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE})
        for name in mentioned:
            self.assertIn(name, ToolRegistry.registered_names())
        # Argument shapes belong to the Registry schema, not to this prompt.
        for token in ("additionalProperties", "minLength", "retrieved_at", "source_id", "raw score"):
            self.assertNotIn(token, prompt)

    def test_registry_and_catalog_descriptions_distinguish_query_and_score(self):
        from fishery_ai.tools.catalog import tool_catalog
        query, score = self.registry.model_definitions()
        self.assertIn("数值、状态、告警", query.description)
        self.assertIn("不负责评分", query.description)
        self.assertIn("评分、等级和分项评分", score.description)
        self.assertIn("内部已经读取当前Snapshot", score.description)
        self.assertIn("同一轮不要再调用get_current_water_quality", score.description)
        catalog = {item["name"]: item for item in tool_catalog(self.registry)}
        self.assertIn("不负责评分", catalog[QUERY]["short_description"])
        self.assertIn("内部已经读取当前Snapshot", catalog[SCORE]["detailed_description"])
        self.assertTrue(catalog[SCORE]["experimental"])
        for definition in (query, score):
            self.assertEqual(definition.parameters_dict(),
                {"type": "object", "properties": {}, "additionalProperties": False})

    def test_question_matrix_uses_scripted_single_choices_for_three_presets(self):
        self.store.set_current(self.reading(oxygen=6.4))
        cases = (
            ("现在水质怎么样？", QUERY, "当前DO为6.4"),
            ("当前水质评分、等级是多少？", SCORE, "这是本轮Tool返回的实验评分"),
            ("什么是溶氧？", None, "溶氧是水中溶解的氧气"),
            ("现在仍然是旧值2.2吗？", QUERY, "本轮查询为6.4，不是旧2.2"),
            ("刚才2.2 mg/L是什么意思？", None, "这是历史低氧读数的含义"),
        )
        for preset_id in ALLOWED_PRESET_IDS:
            profile = assistant_profile(preset_id)
            credentials = CredentialStore(process_env={profile.credential_ref: FAKE_KEY}
                                          if profile.credential_ref else {})
            runtime = ProfileRegistry([profile], credentials).snapshot(profile.profile_id)
            for question, selected, answer in cases:
                with self.subTest(preset=preset_id, question=question):
                    gateway = RecordingGateway(*(call(selected), final(answer)) if selected else (final(answer),))
                    with patch.object(self.reader, "query", wraps=self.reader.query) as read:
                        result = self.service(gateway, (QUERY, SCORE)).send(
                            AssistantRequest(preset_id, question, self.history()), runtime)
                    public = result.to_dict()
                    self.assertTrue(public["successful_turn"])
                    self.assertEqual(public["tool_activity"]["tool_name"], selected)
                    self.assertEqual(read.call_count, 1 if selected else 0)
                    self.assertEqual(len(gateway.requests), 2 if selected else 1)
                    self.assertEqual([t.name for t in gateway.requests[0].tools], [QUERY, SCORE])
                    self.assertEqual([m.role for m in gateway.requests[0].messages],
                                     ["system", "user", "assistant", "user"])
                    if selected:
                        self.assertEqual(gateway.requests[1].tool_choice, "none")
                        tool_data = json.loads(gateway.requests[1].messages[-1].content)
                        if selected == QUERY:
                            self.assertEqual(tool_data["water_quality"]["dissolved_oxygen_mg_l"], 6.4)
                        self.assertEqual(gateway.requests[1].messages[0].content,
                                         gateway.requests[0].messages[0].content)

    def test_no_authorized_score_refuses_or_rejects_without_fabricating_tool_result(self):
        gateway = RecordingGateway(final("评分Tool未授权，无法取得当前系统评分。"))
        with patch.object(self.reader, "query", side_effect=AssertionError("no automatic tool")):
            result = self.service(gateway).send(self.request("当前系统评分多少？", self.history()), self.runtime)
        self.assertFalse(result.to_dict()["tool_activity"]["used_tool"])
        self.assertEqual([t.name for t in gateway.requests[0].tools], [QUERY])
        self.assertIn("不得伪造系统评分", gateway.requests[0].messages[0].content)
        gateway = RecordingGateway(call(SCORE))
        with patch.object(self.reader, "query", side_effect=AssertionError("unauthorized handler")):
            refused = self.service(gateway).send(self.request("当前评分多少？"), self.runtime)
        self.assertEqual(refused.error_code, "TOOL_NOT_ALLOWED")
        self.assertFalse(refused.to_dict()["successful_turn"])
        self.assertEqual(len(gateway.requests), 1)

    def test_two_open_tools_still_reject_parallel_calls_before_execution(self):
        response = ModelResponse(None, tool_calls=(ModelToolCall("q", QUERY, "{}"),
                                                   ModelToolCall("s", SCORE, "{}")))
        gateway = RecordingGateway(response)
        with patch.object(self.reader, "query", side_effect=AssertionError("no multi-tool execution")):
            result = self.service(gateway, (QUERY, SCORE)).send(self.request("现在评分多少？"), self.runtime)
        self.assertEqual(result.error_code, "TOOL_CALL_LIMIT")
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(len(gateway.requests), 1)

    def test_plain_text_prompt_survives_follow_up_without_renderer_or_repair(self):
        gateway = RecordingGateway(call(), final("**模型未遵守纯文本提示**"))
        result = self.service(gateway).send(self.request(), self.runtime)
        for request in gateway.requests:
            system = request.messages[0].content
            self.assertIn("最终回答使用简洁纯文本", system)
            self.assertIn("不要输出Markdown表格、Markdown粗体或代码围栏", system)
        # Prompt is a constraint, not an output sanitizer or absolute compliance proof.
        self.assertEqual(result.final_text, "**模型未遵守纯文本提示**")


class AssistantWebTests(AssistantFixture):
    def setUp(self):
        super().setUp()
        self.factory = Mock(return_value=RecordingGateway(final()))
        self.app = self.make_app()
        self.client = self.app.test_client()
        csrf = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
        self.epoch = self.client.get("/api/assistant/bootstrap").get_json()["epoch"]

    def make_app(self, credentials=None):
        return create_app(trace_path=self.trace, custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", manual_experiments_dir=self.root / "experiments",
            scenario_templates_dir=self.root / "templates", tool_policy_dir=self.root / "policies",
            credential_store=credentials or CredentialStore(process_env={}), real_gateway_factory=self.factory)

    def post(self, **changes):
        control = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        return self.client.post("/api/assistant/chat", json={"preset_id": LOCAL, "question": "什么是溶氧？",
            "epoch": self.epoch, "confirm_network": True, "request_id": control["request_id"],
            "control_token": control["control_token"], **changes}, headers=self.headers)

    def test_bootstrap_no_facts_secret_or_connection_configuration(self):
        with patch.object(self.app.extensions["fishery_current_water_quality_reader"], "query", side_effect=AssertionError("no prefetch")):
            data = self.client.get("/api/assistant/bootstrap").get_json()
        self.assertEqual([p["preset_id"] for p in data["presets"]], list(ALLOWED_PRESET_IDS))
        self.assertEqual(data["default_preset_id"], ALLOWED_PRESET_IDS[0])
        self.assertEqual(data["fixed_mode"], {"thinking": "off", "response_mode": "normal"})
        self.assertEqual(data["tools"], [{"name": QUERY}])
        for field in ("credential", "base_url", "snapshot", "protocol", "capability"):
            self.assertNotIn(field, json.dumps(data))
        self.factory.assert_not_called()

    def test_chat_success_uses_existing_runtime_and_handle(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["result"]
        self.assertTrue(data["successful_turn"])
        self.assertEqual(data["history_turns_sent"], 0)
        self.assertFalse(data["tool_activity"]["used_tool"])
        gateway = self.factory.return_value
        self.assertEqual(gateway.runtimes[0].default_reasoning.mode.value, "off")
        self.assertEqual(gateway.runtimes[0].max_retries, 0)

    def test_web_status_observes_safe_phase_no_model_or_tool_payload(self):
        control = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        observed = []
        def observe(*_):
            response = self.client.post(f"/api/requests/{control['request_id']}/status",
                json={"control_token": control["control_token"]}, headers=self.headers)
            data = response.get_json(); observed.append(data)
            self.assertEqual(response.status_code, 200)
        self.factory.return_value = RecordingGateway(call(), final(), callback=observe)
        reader = self.app.extensions["fishery_current_water_quality_reader"]
        original = reader.query
        def query():
            observe(); return original()
        with patch.object(reader, "query", query):
            response = self.client.post("/api/assistant/chat", json={"preset_id": LOCAL,
                "question": "当前水质？", "epoch": self.epoch, "confirm_network": True,
                "request_id": control["request_id"], "control_token": control["control_token"]}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["phase"] for item in observed], ["REQUEST_1", "RUNNING_TOOL", "REQUEST_2"])
        for item in observed:
            self.assertFalse(set(item) & {"prompt", "messages", "tool_result", "credential", "control_token"})

    def test_epoch_restart_rejects_before_credentials_and_gateway(self):
        self.assertNotEqual(self.make_app().test_client().get("/api/assistant/bootstrap").get_json()["epoch"], self.epoch)
        response = self.post(epoch="old-epoch")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error_code"], "ASSISTANT_SESSION_EXPIRED")
        self.factory.assert_not_called()

    def test_preflight_rejections_release_prepared_handles(self):
        for i in range(12):
            response = self.post(preset_id="DS_1")
            self.assertEqual(response.get_json()["error_code"], "ASSISTANT_PRESET_NOT_ALLOWED")
        self.assertEqual(self.post().status_code, 200)

    def test_client_cannot_choose_on_streaming_or_arbitrary_target(self):
        for field in ("url", "service", "adapter", "model", "credential_ref", "thinking", "response_mode", "capability", "profile_id"):
            with self.subTest(field=field):
                self.assertEqual(self.post(**{field: "injected"}).status_code, 400)
        self.factory.assert_not_called()

    def test_missing_secret_and_network_confirmation_fail_closed(self):
        self.assertEqual(self.post(preset_id=ALLOWED_PRESET_IDS[0]).get_json()["error_code"], "SECRET_MISSING")
        self.assertEqual(self.post(confirm_network=False).get_json()["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        self.factory.assert_not_called()

    def test_web_policy_frozen_for_inflight_request(self):
        policy_store = self.app.extensions["fishery_tool_policy_store"]
        def rotate(*_):
            policy_store.save({"schema_version": 1, "modes": {
                "analysis": {"selected_tools": []}, "assistant": {"selected_tools": []}}})
        gateway = RecordingGateway(call(), final("NO_DATA"), callback=rotate)
        self.factory.return_value = gateway
        response = self.post(question="现在水质怎么样？")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["result"]["tool_activity"]["tool_status"], "NO_DATA")
        self.assertEqual(len(gateway.requests), 2)
        self.factory.return_value = RecordingGateway(final("无授权工具"))
        self.post()
        self.assertFalse(self.factory.return_value.requests[0].tools)

    def test_host_origin_csrf_and_no_cors(self):
        self.assertEqual(self.client.get("/api/assistant/bootstrap", headers={"Host": "evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/assistant/bootstrap", headers={"Origin": "http://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/assistant/chat", json={}).status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", self.client.get("/api/assistant/bootstrap").headers)

    def test_web_16k_limit_and_failed_final_gate(self):
        response = self.client.post("/api/assistant/chat", json={"question": "x" * 17000}, headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.factory.return_value = RecordingGateway(final("partial", "length"))
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["result"]["error_code"], "ASSISTANT_RESPONSE_TRUNCATED")

    def test_cloud_credential_snapshot_hot_rotation_and_no_legacy_fallback(self):
        profile = assistant_profile(ALLOWED_PRESET_IDS[0])
        # Only temporary, fictional sources; no project/user credential reads.
        private = self.root / "temporary-private.env"
        private.write_text(f"{profile.credential_ref}=fictional-private-key\n", encoding="utf-8")
        process = {profile.credential_ref: FAKE_KEY}
        credentials = CredentialStore(private, process_env=process)
        app = self.make_app(credentials)
        client = app.test_client()
        csrf = client.get("/api/credential-session").get_json()["csrf_token"]
        headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}
        epoch = client.get("/api/assistant/bootstrap").get_json()["epoch"]
        self.factory.return_value = RecordingGateway(call(), final("答案"))
        def rotate(index, *_):
            if index == 1: process[profile.credential_ref] = "fictional-rotated-key"
        self.factory.return_value.callback = rotate
        control = client.post("/api/requests", json={}, headers=headers).get_json()
        response = client.post("/api/assistant/chat", json={"preset_id": profile.preset_id,
            "question": "现在水质？", "epoch": epoch, "confirm_network": True,
            "request_id": control["request_id"], "control_token": control["control_token"]}, headers=headers)
        self.assertEqual(response.status_code, 200)
        runtimes = self.factory.return_value.runtimes
        self.assertIs(runtimes[0], runtimes[1])
        self.assertEqual(runtimes[1].credential._for_adapter(), FAKE_KEY)
        self.assertEqual(runtimes[1].credential.status.source, "PROCESS_ENV")
        self.assertEqual(credentials.resolve(profile.credential_ref, profile.auth_spec)._for_adapter(), "fictional-rotated-key")
        self.assertNotIn(FAKE_KEY, response.get_data(as_text=True))

    def test_cancel_uses_existing_web_control_and_no_commit(self):
        control = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        request_id, token = control["request_id"], control["control_token"]
        def cancel(*_):
            response = self.client.post(f"/api/requests/{request_id}/cancel", json={"control_token": token}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
        self.factory.return_value = RecordingGateway(call(), callback=cancel)
        response = self.client.post("/api/assistant/chat", json={"preset_id": LOCAL,
            "question": "当前水质？", "epoch": self.epoch, "confirm_network": True,
            "request_id": request_id, "control_token": token}, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["result"]["error_code"], "USER_CANCELLED")
        self.assertFalse(response.get_json()["result"]["successful_turn"])
        self.assertEqual(len(self.factory.return_value.requests), 1)

    def test_cloud_request_without_managed_resolver_or_legacy_file(self):
        (self.root / ".env").write_text("DEEPSEEK_API_KEY=fictional-legacy\n", encoding="utf-8")
        with patch("fishery_ai.capability_store.CapabilityStore.apply", side_effect=AssertionError("no Managed Evidence")), \
             patch.object(
                self.app.extensions["fishery_current_water_quality_reader"], "query", side_effect=AssertionError("no implicit facts")):
            response = self.post(preset_id=ALLOWED_PRESET_IDS[1])
        self.assertEqual(response.get_json()["error_code"], "SECRET_MISSING")
        self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
