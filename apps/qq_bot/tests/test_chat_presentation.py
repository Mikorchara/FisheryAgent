"""Same source/closed plan, session-only compact view; no network or databases."""
from dataclasses import replace
import json
import unittest

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel import SourceRule
from apps.ai_service.channel_chat_presentation import render_chat_reply, validate_mode
from apps.ai_service.channel_presentation import render_channel_reply
from apps.qq_bot.tests import test_explanation as fixture


class ChatPresentationTests(unittest.TestCase):
    def render(self, *, source=None, focus='all', plan=None, **kwargs):
        text=json.dumps(fixture.document() if plan is None else plan)
        return render_chat_reply(fixture.result(text,source),focus=focus,**kwargs)

    def test_focus_uses_source_values_without_reprinting_other_valid_metrics(self):
        text,assessment=self.render(focus='dissolved_oxygen_mg_l')
        self.assertTrue(assessment.allowed)
        self.assertIn('溶解氧：6.5 mg/L',text)
        self.assertNotIn('水温：',text);self.assertNotIn('pH：',text)
        self.assertIn('SIMULATOR',text);self.assertIn('北京时间 UTC+08',text)
        self.assertIn('2026-10-26 08:00:00',text)
        self.assertIn('AI 建议（已校验，未执行）',text)
        self.assertNotIn('A. 系统事实',text)

    def test_detailed_renderer_remains_original_abc(self):
        result=fixture.result(json.dumps(fixture.document()))
        detailed,a=render_channel_reply(result)
        chat,b=render_chat_reply(result,focus='ph')
        self.assertTrue(a.allowed and b.allowed)
        for label in ('A. 系统事实','B. 模型解释','C. 来源与限制'):
            self.assertIn(label,detailed)
        self.assertIn('水温：25.0',detailed);self.assertLess(len(chat),len(detailed))

    def test_unasked_severe_hit_is_always_visible(self):
        s=replace(fixture.source(),rule_hits=(SourceRule('OXYGEN_CRITICAL_LOW','critical','溶氧低（2.2 mg/L）'),))
        text,a=self.render(source=s,focus='temperature_c',plan=fixture.document(
            metrics=['temperature_c'],rules=['OXYGEN_CRITICAL_LOW'],advice=['review_rules']))
        self.assertTrue(a.allowed);self.assertIn('2.2 mg/L',text);self.assertIn('严重',text)
        self.assertNotIn('未触发',text)

    def test_unasked_missing_ph_prevents_whole_pond_normal_claim(self):
        s=replace(fixture.source(),quality='partial',current_evidence_usable=False,
            metrics=tuple(replace(m,value=None,quality='missing') if m.id=='ph' else m for m in fixture.source().metrics))
        text,a=self.render(source=s,focus='dissolved_oxygen_mg_l',plan=fixture.document(context='limited'))
        self.assertTrue(a.allowed);self.assertIn('pH：数据不足（缺测）',text)
        self.assertIn('不能完整确认',text);self.assertNotIn('pH：7',text)
        self.assertNotIn('未触发水质',text)

    def test_stale_offline_remain_retained_values_not_current_measurements(self):
        s=replace(fixture.source(),freshness='stale',connectivity='offline',current_evidence_usable=False)
        text,a=self.render(source=s,plan=fixture.document(context='limited'))
        self.assertTrue(a.allowed)
        for label in ('数据过期','设备离线','留存读数','未重新采样'):self.assertIn(label,text)
        self.assertNotIn('当前正常',text)

    def test_invalid_metric_value_is_not_printed(self):
        s=replace(fixture.source(),quality='invalid',current_evidence_usable=False,
            metrics=tuple(replace(m,value=99,quality='invalid') if m.id=='ph' else m for m in fixture.source().metrics))
        text,a=self.render(source=s,plan=fixture.document(context='limited'))
        self.assertTrue(a.allowed);self.assertIn('无效',text);self.assertNotIn('99',text)

    def test_unknown_timestamps_are_not_replaced_by_current_time(self):
        s=replace(fixture.source(),observed_at='invalid',evaluated_at='2026-10-26T01:00:00')
        text,_=self.render(source=s)
        self.assertIn('观测 未知；评估 未知',text)
        self.assertNotIn('未触发水质',text)

    def test_unverified_free_text_never_reaches_chat(self):
        result=fixture.result('溶解氧实时为99，已删除事件 PRIVATE_MODEL_CANARY')
        text,a=render_chat_reply(result)
        self.assertFalse(a.allowed);self.assertNotIn('PRIVATE_MODEL_CANARY',text)
        self.assertNotIn('99',text);self.assertIn('仅展示系统事实',text)

    def test_length_does_not_truncate_facts_or_safety_warnings(self):
        with self.assertRaisesRegex(GatewayError,'AI_REPLY_TOO_LONG'):self.render(max_chars=40)
        with self.assertRaisesRegex(GatewayError,'AI_REPLY_TOO_LONG'):self.render(max_chars=True)

    def test_unknown_focus_or_display_mode_is_rejected(self):
        with self.assertRaisesRegex(GatewayError,'INVALID_CONVERSATION_TOPIC'):self.render(focus='other-device')
        with self.assertRaisesRegex(GatewayError,'INVALID_SESSION_PRESENTATION'):validate_mode('FREE_TEXT')

    def test_no_data_unknown_is_not_called_offline_or_normal(self):
        s=replace(fixture.source(),status='NO_DATA',observed_at=None,received_at=None,
            quality='missing',freshness='unknown',connectivity='never_received',current_evidence_usable=False,
            metrics=tuple(replace(m,value=None,quality='missing') for m in fixture.source().metrics))
        text,a=self.render(source=s,plan=fixture.document(context='limited'))
        self.assertTrue(a.allowed);self.assertIn('尚无可用观测',text);self.assertIn('时效未知',text)
        self.assertNotIn('设备离线',text);self.assertNotIn('未触发水质',text)
