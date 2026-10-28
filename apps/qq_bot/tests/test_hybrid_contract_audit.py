"""Hybrid research probes only: no new entry, Scope, Prompt or delivery permit.

The Web AUTO counterexample is deliberately accepted by the existing execution
contract. This is evidence that AUTO cannot be a QQ factual-publication gate,
not an acceptance test declaring fabricated current observations safe.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import GatewayError, ModelResponse, ModelToolCall
from apps.ai_service.channel import OfflineChannelProvider
from apps.ai_service.channel_chat_presentation import render_chat_reply
from apps.ai_service.channel_presentation import assess_explanation
from apps.ai_service.runtime.sources import SourceRequirement
from apps.ai_service.tests import test_service as web_fixture
from apps.qq_bot.conversations import ConversationKey, ConversationOptions, ConversationStore
from apps.qq_bot.tests import test_ai_coordinator as qq_fixture
from apps.qq_bot.tests import test_explanation as explanation_fixture

OBSERVATIONS = []


class HybridContractAuditTests(unittest.TestCase):
    @contextmanager
    def web(self, *responses):
        case = web_fixture.AIServiceTests(
            'test_direct_final_reuses_supplied_handle_and_commit_gate_without_http')
        case.setUp()
        try:
            case.gateway = web_fixture.RecordingGateway(*responses)
            yield case
        finally:
            self.assertTrue(case.doCleanups())

    @contextmanager
    def qq(self, *responses):
        case = qq_fixture.QQAIServiceTests(
            'test_legal_single_turn_reuses_loop_and_one_capture_no_keys_or_writes')
        case.setUp()
        try:
            case.provider = OfflineChannelProvider(responses)
            case.backend._offline_channel_provider = case.provider
            yield case
        finally:
            self.assertTrue(case.doCleanups())

    def test_web_shared_agent_can_answer_general_without_tool(self):
        with self.web(ModelResponse('溶解氧是水中溶解的氧气；这是一般概念说明。', finish_reason='stop')) as case:
            with patch.object(case.monitoring, 'capture_water',
                              side_effect=AssertionError('no current query for direct final')) as read:
                prepared = case.backend.prepare_turn(case.envelope(question='解释一下溶解氧的概念'))
                handle = RequestHandle()
                result = case.backend.execute_turn(prepared, handle)
            self.assertEqual(prepared.request.source_requirement, SourceRequirement.AUTO)
            self.assertTrue(result['successful_turn'])
            self.assertEqual((len(case.gateway.requests), read.call_count), (1, 0))
            self.assertEqual(case.gateway.requests[0].tool_choice, 'auto')
            self.assertEqual(handle.state, 'COMPLETED')
            OBSERVATIONS.append(dict(case='web_general', completed=True, model_calls=1, tool_reads=0))

    def test_web_shared_agent_can_choose_current_tool_with_two_calls(self):
        with self.web(ModelResponse(None, tool_calls=(ModelToolCall(
                'fake-water', 'get_current_water_quality', '{}'),), finish_reason='tool_calls'),
                ModelResponse('这是新建合成实例中的本轮工具回复。', finish_reason='stop')) as case:
            case.batch('pond-a', 2.2)
            with patch.object(case.monitoring, 'capture_water', wraps=case.monitoring.capture_water) as read:
                result = case.backend.execute_turn(case.backend.prepare_turn(
                    case.envelope(question='当前绑定鱼塘的水质怎么样？')), RequestHandle())
            self.assertTrue(result['successful_turn'])
            self.assertEqual((len(case.gateway.requests), read.call_count), (2, 1))
            self.assertEqual(case.gateway.requests[1].tool_choice, 'none')
            OBSERVATIONS.append(dict(case='web_tool', completed=True, model_calls=2, tool_reads=1))

    def test_web_auto_does_not_certify_current_claims_counterexample(self):
        with self.web(ModelResponse('我已查询你鱼塘的实时水质，全部正常。', finish_reason='stop')) as case:
            with patch.object(case.monitoring, 'capture_water',
                              side_effect=AssertionError('counterexample has no actual source')) as read:
                result = case.backend.execute_turn(case.backend.prepare_turn(
                    case.envelope(question='当前水质正常吗？')), RequestHandle())
            self.assertTrue(result['successful_turn'])
            self.assertEqual((len(case.gateway.requests), read.call_count), (1, 0))
            OBSERVATIONS.append(dict(case='auto_counterexample_not_publication_approval',
                                     completed=True, model_calls=1, tool_reads=0,
                                     factual_verification=False))

    def test_existing_qq_general_direct_final_is_rejected_by_source_gate(self):
        with self.qq(ModelResponse('一般来说，pH用于描述酸碱程度。', finish_reason='stop')) as case:
            with patch.object(case.source, 'capture_water', side_effect=AssertionError('no Tool')) as read:
                result = case.coordinator.execute(case.prepare(text='/问AI 解释pH的一般含义'))
            self.assertFalse(result.completed)
            self.assertEqual(result.error_code, 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
            self.assertEqual(result.model_text, '')
            OBSERVATIONS.append(dict(case='qq_general_current_contract', completed=False,
                                     model_calls=len(case.provider.requests), tool_reads=read.call_count,
                                     code=result.error_code))

    def test_existing_qq_unbacked_current_final_is_also_rejected(self):
        with self.qq(ModelResponse('你鱼塘当前全部正常，我已查过。', finish_reason='stop')) as case:
            with patch.object(case.source, 'capture_water', side_effect=AssertionError('no Tool')) as read:
                result = case.coordinator.execute(case.prepare(text='/问AI 现在水质如何？'))
            self.assertFalse(result.completed)
            self.assertEqual(result.error_code, 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
            OBSERVATIONS.append(dict(case='qq_forged_current', completed=False,
                                     model_calls=len(case.provider.requests), tool_reads=read.call_count,
                                     code=result.error_code))

    def test_auto_cannot_be_substituted_into_existing_qq_prepared_turn(self):
        with self.qq(ModelResponse('不应该执行', finish_reason='stop')) as case:
            plan = case.prepare()
            modified = replace(plan.prepared, request=replace(
                plan.prepared.request, source_requirement=SourceRequirement.AUTO))
            with self.assertRaisesRegex(GatewayError, 'INVALID_CHANNEL_CANDIDATE'):
                case.backend.execute_channel_turn(modified, plan.handle)
            self.assertEqual(case.provider.requests, [])

    def test_existing_qq_tool_does_not_license_unverified_prose(self):
        with self.qq(ModelResponse(None, tool_calls=(ModelToolCall(
                'fake-water', 'get_current_water_quality', '{}'),), finish_reason='tool_calls'),
                ModelResponse('当前溶解氧为8.8，已经保证鱼群健康。', finish_reason='stop')) as case:
            with patch.object(case.source, 'capture_water', wraps=case.source.capture_water) as read:
                result = case.coordinator.execute(case.prepare())
            self.assertTrue(result.completed)
            text, assessment = render_chat_reply(result)
            self.assertFalse(assessment.allowed)
            self.assertNotIn('8.8', text)
            self.assertNotIn('保证鱼群健康', text)
            self.assertIn('溶解氧：2.2', text)
            OBSERVATIONS.append(dict(case='qq_tool_free_prose_fallback', completed=True,
                                     model_calls=len(case.provider.requests), tool_reads=read.call_count,
                                     explanation_allowed=False))

    def test_proposed_general_json_is_not_an_existing_display_contract(self):
        candidate = {'contract': 'qq-hybrid-reply@1', 'kind': 'general',
                     'text': '一般性知识说明，不是本轮监测事实。'}
        result = assess_explanation(json.dumps(candidate), explanation_fixture.source())
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, 'EXPLANATION_CONTRACT_INVALID')

    def test_current_focus_history_is_not_general_dialogue_memory(self):
        store = ConversationStore(ConversationOptions(trigger_mode='mention_ai', memory_enabled=True))
        self.addCleanup(store.close)
        key = ConversationKey('fake-app', 'fake-group', 'fake-member', 'fake-instance',
                              'fake-device', 'permission', 'binding', 'policy', 'scope', 'epoch')
        with self.assertRaisesRegex(GatewayError, 'INVALID_CONVERSATION_KEY'):
            store.snapshot(key, focus='general')
        self.assertEqual(store.counts()['turns'], 0)
