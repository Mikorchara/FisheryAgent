"""D1 offline tests: MockToolGateway renders by tool name, never by guessing shape.

The water mock text must stay byte-identical; unknown or malformed tool results
must fall back safely instead of raising. No network, no real model.
"""

import json
import unittest
from unittest.mock import patch

from fishery_ai.assistant import ALLOWED_PRESET_IDS, assistant_profile
from fishery_ai.contracts import Mode, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.model_gateway import (ModelMessage, ModelRequest, ModelToolCall, ModelToolDefinition,
                                      ProfileRegistry)
from fishery_ai.tool_conversation import (FALLBACK_TOOLS, MOCK_DRIVABLE_TOOLS, UNRENDERED_TEXT,
                                         UNAUTHORIZED_TOOL_TEXT, MockToolGateway)
from fishery_ai.tools.registry import CURRENT_WATER_QUALITY, KNOWLEDGE_PARAMETERS, WATER_QUALITY_SCORE


LOCAL = ALLOWED_PRESET_IDS[2]
KNOWLEDGE = "search_fishery_knowledge"
NO_DATA_TEXT = "离线 Mock：没有当前水质数据，请先显式 Apply 情景或取得快照。"
WATER_TEXT = ("离线 Mock：水温 28 ℃，pH 7.5，溶氧 6.4 mg/L。"
              "质量 valid；新鲜度 fresh。确定性诊断：溶氧充足。")
SCORE_TEXT = ("离线 Mock：实验评分 88.5，等级 GOOD，状态 OK。"
              "EXPERIMENTAL / NOT PROFESSIONAL STANDARD；不是专业养殖标准。")


def water_payload(**water_changes):
    water = {"temperature_c": 28, "ph": 7.5, "dissolved_oxygen_mg_l": 6.4,
             "quality": "valid", "freshness": "fresh"}
    water.update(water_changes)
    return {"status": "OK", "water_quality": water, "findings": [{"message": "溶氧充足"}]}


def score_payload(**changes):
    payload = {"status": "OK", "score": 88.5, "grade": "GOOD",
               "scoring_version": "experimental-water-quality-score-v1"}
    payload.update(changes)
    return payload


def definition(name):
    return ModelToolDefinition(name, "fixture definition", {"type": "object", "properties": {}})


def offered(name):
    """Real Knowledge parameters, so a fixture cannot hide a required argument."""
    if name == KNOWLEDGE:
        return ModelToolDefinition(name, "fixture definition", KNOWLEDGE_PARAMETERS)
    return definition(name)


def second_request(payload, *, name=CURRENT_WATER_QUALITY, call_id="call_1", assistant_call_id=None):
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ModelRequest(Mode.CHAT, (
        ModelMessage("system", "fixture system"),
        ModelMessage("user", "现在水质怎么样？"),
        ModelMessage("assistant", None,
                     tool_calls=(ModelToolCall(assistant_call_id or call_id, name, "{}"),)),
        ModelMessage("tool", body, tool_call_id=call_id),
    ), tools=(definition(name),), tool_choice="none")


def first_request(question, *, names=(CURRENT_WATER_QUALITY,)):
    return ModelRequest(Mode.CHAT, (ModelMessage("system", "fixture system"),
                                    ModelMessage("user", question)),
                        tools=tuple(definition(name) for name in names), tool_choice="auto")


class MockToolGatewayTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("D1 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        profile = assistant_profile(LOCAL)
        self.runtime = ProfileRegistry([profile], CredentialStore(process_env={})).snapshot(
            profile.profile_id)
        self.gateway = MockToolGateway()

    def second(self, payload, **kwargs):
        return self.gateway.complete(second_request(payload, **kwargs), self.runtime)

    def first(self, question, **kwargs):
        return self.gateway.complete(first_request(question, **kwargs), self.runtime)

    # -- existing water mock text is unchanged -------------------------------

    def test_water_quality_text_is_unchanged(self):
        response = self.second(water_payload())
        self.assertEqual(response.text, WATER_TEXT)
        self.assertEqual(response.finish_reason, "stop")

    def test_water_quality_missing_value_keeps_the_placeholder(self):
        response = self.second(water_payload(ph=None))
        self.assertIn("pH 缺失", response.text)
        self.assertIn("水温 28 ℃", response.text)

    def test_water_quality_without_findings_says_no_alarm(self):
        payload = water_payload()
        payload["findings"] = []
        self.assertIn("确定性诊断：无阈值告警。", self.second(payload).text)

    def test_water_quality_no_data_text_is_unchanged(self):
        payload = {"status": "NO_DATA", "water_quality": None, "findings": []}
        self.assertEqual(self.second(payload).text, NO_DATA_TEXT)

    def test_score_text_is_unchanged(self):
        self.assertEqual(self.second(score_payload(), name=WATER_QUALITY_SCORE).text, SCORE_TEXT)

    def test_score_no_data_keeps_the_same_no_data_text(self):
        payload = {"status": "NO_DATA", "score": None, "grade": None}
        self.assertEqual(self.second(payload, name=WATER_QUALITY_SCORE).text, NO_DATA_TEXT)

    # -- dispatch is by tool name, not by payload keys -----------------------

    def test_unknown_tool_never_reads_another_tools_payload(self):
        # A complete water-quality payload under a different tool name must NOT be
        # rendered as water quality. This is the exact regression D1 fixes.
        response = self.second(water_payload(), name=KNOWLEDGE)
        self.assertEqual(response.text, UNRENDERED_TEXT)

    def test_unknown_tool_payload_shape_does_not_raise(self):
        payload = {"status": "NO_MATCH", "retrieval_mode": "portable",
                   "result_count": 0, "evidence": []}
        response = self.second(payload, name=KNOWLEDGE)
        self.assertEqual(response.text, UNRENDERED_TEXT)
        self.assertEqual(response.finish_reason, "stop")

    def test_water_tool_with_unexpected_shape_falls_back(self):
        self.assertEqual(self.second({"status": "OK"}).text, UNRENDERED_TEXT)

    def test_score_tool_with_unexpected_shape_falls_back(self):
        self.assertEqual(self.second({"status": "OK"}, name=WATER_QUALITY_SCORE).text, UNRENDERED_TEXT)

    # -- correlation uses tool_call_id --------------------------------------

    def test_correlation_uses_the_tool_call_id(self):
        response = self.second(water_payload(), call_id="call_1", assistant_call_id="call_other")
        self.assertEqual(response.text, UNRENDERED_TEXT)

    def test_missing_tool_message_falls_back(self):
        request = ModelRequest(Mode.CHAT, (ModelMessage("system", "fixture system"),
                                          ModelMessage("user", "现在水质怎么样？")),
                               tools=(definition(CURRENT_WATER_QUALITY),), tool_choice="none")
        self.assertEqual(self.gateway.complete(request, self.runtime).text, UNRENDERED_TEXT)

    def test_non_object_tool_content_falls_back(self):
        self.assertEqual(self.second("[1, 2]").text, UNRENDERED_TEXT)

    # -- first request behavior is untouched --------------------------------

    def test_concept_question_still_answers_directly(self):
        oxygen = self.first("什么是溶氧？")
        self.assertFalse(oxygen.tool_calls)
        self.assertIn("未读取当前水质", oxygen.text)
        other = self.first("养殖要注意什么？")
        self.assertFalse(other.tool_calls)
        self.assertIn("这是概念回答", other.text)

    def test_current_question_still_calls_the_water_tool(self):
        response = self.first("现在水质怎么样？")
        self.assertEqual(response.tool_calls[0].function_name, CURRENT_WATER_QUALITY)
        self.assertEqual(response.tool_calls[0].arguments_json, "{}")

    def test_scoring_question_prefers_the_score_tool_when_authorized(self):
        response = self.first("当前水质评分多少？", names=(WATER_QUALITY_SCORE, CURRENT_WATER_QUALITY))
        self.assertEqual(response.tool_calls[0].function_name, WATER_QUALITY_SCORE)

    def test_desired_tool_fallback_stays_unchanged(self):
        # Directional degradation (D1b): without the score tool, a scoring question
        # reads the current facts instead. Still one call, still "{}".
        response = self.first("当前水质评分多少？", names=(CURRENT_WATER_QUALITY,))
        self.assertEqual(response.tool_calls[0].function_name, CURRENT_WATER_QUALITY)

    def test_current_question_without_tools_explains_the_policy(self):
        request = ModelRequest(Mode.CHAT, (ModelMessage("system", "fixture system"),
                                          ModelMessage("user", "现在水质怎么样？")))
        response = self.gateway.complete(request, self.runtime)
        self.assertFalse(response.tool_calls)
        self.assertIn("当前 Policy 未允许", response.text)

    # -- D1b: directional fallback, never a positional substitute -------------

    def test_current_question_never_degrades_to_the_score_tool(self):
        # Regression the old request.tools[0] fallback got wrong: reading the current
        # facts must not be answered from a score.
        response = self.first("现在水质怎么样？", names=(WATER_QUALITY_SCORE,))
        self.assertFalse(response.tool_calls)
        self.assertEqual(response.finish_reason, "stop")
        self.assertEqual(response.text, UNAUTHORIZED_TOOL_TEXT)

    def test_desired_tool_is_checked_before_its_fallback(self):
        # Offered order must not decide: the wanted tool wins wherever it sits.
        response = self.first("当前水质评分多少？", names=(CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE))
        self.assertEqual(response.tool_calls[0].function_name, WATER_QUALITY_SCORE)

    def test_knowledge_is_never_chosen_or_borrowed(self):
        for question in ("现在水质怎么样？", "当前水质评分多少？"):
            with self.subTest(question=question):
                response = self.first(question, names=(KNOWLEDGE,))
                self.assertFalse(response.tool_calls)
                self.assertEqual(response.finish_reason, "stop")
                self.assertEqual(response.text, UNAUTHORIZED_TOOL_TEXT)

    def test_knowledge_next_to_a_water_tool_is_still_ignored(self):
        response = self.first("现在水质怎么样？", names=(KNOWLEDGE, CURRENT_WATER_QUALITY))
        self.assertEqual(response.tool_calls[0].function_name, CURRENT_WATER_QUALITY)

    def test_the_mock_never_emits_an_uncallable_tool_call(self):
        # Invariant: every call this fixture produces targets a tool it can drive with
        # "{}" - and offering a parameterized tool changes nothing about that.
        questions = ("现在水质怎么样？", "当前水质评分多少？", "现在打分是多少", "什么是溶氧？")
        # The empty offer is covered separately: tool_choice requires a non-empty list.
        offers = ((CURRENT_WATER_QUALITY,), (WATER_QUALITY_SCORE,), (KNOWLEDGE,),
                  (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE), (WATER_QUALITY_SCORE, CURRENT_WATER_QUALITY),
                  (CURRENT_WATER_QUALITY, KNOWLEDGE), (WATER_QUALITY_SCORE, KNOWLEDGE),
                  (KNOWLEDGE, WATER_QUALITY_SCORE, CURRENT_WATER_QUALITY))
        self.assertEqual(set(FALLBACK_TOOLS), set(MOCK_DRIVABLE_TOOLS))
        catalog = {name: offered(name).parameters_dict() for name in
                   (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, KNOWLEDGE)}
        self.assertEqual(catalog[KNOWLEDGE].get("required"), ["query"])
        produced = 0
        for question in questions:
            for names in offers:
                response = self.first(question, names=names)
                for call in response.tool_calls:
                    produced += 1
                    self.assertIn(call.function_name, MOCK_DRIVABLE_TOOLS)
                    self.assertNotIn("required", catalog[call.function_name])
                    self.assertEqual(call.arguments_json, "{}")
        self.assertGreater(produced, 0)


if __name__ == "__main__":
    unittest.main()
