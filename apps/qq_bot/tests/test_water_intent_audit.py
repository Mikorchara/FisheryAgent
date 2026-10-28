"""BOT-3G-A characterisation, not an implementation of the proposed new routes.

All instances, approvals, SDK responses and QQ events are synthetic. Socket and
credential guards come from the existing typed Session fixture. Rebaseline these
expectations only after the paid-route/Scope design receives explicit approval.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import unittest
from unittest.mock import patch

from apps.qq_bot.intent import classify
from apps.qq_bot.tests import test_session_run_trial as fixture


# family, question, current outcome without history, with accepted oxygen topic.
# Human-labelled current behaviour; several rows intentionally expose gaps.
CLARIFY = ('clarify', 'all')
ALL = ('water', 'all')
PH = ('water', 'ph')
OXYGEN = ('water', 'dissolved_oxygen_mg_l')
UNSUPPORTED = ('unsupported', 'all')
CORPUS = (
    ('reliability', '现在的数据可靠吗？', CLARIFY, CLARIFY),
    ('reliability', '这些监测数据靠谱吗？', CLARIFY, CLARIFY),
    ('reliability', '水质数据可靠吗？', ALL, ALL),
    ('reliability', '当前pH数据可靠吗？', PH, PH),
    ('oxygen_risk', '有没有低氧风险？', CLARIFY, CLARIFY),
    ('oxygen_risk', '鱼塘现在会不会缺氧？', ALL, ALL),
    ('oxygen_risk', '溶氧会不会过低？', OXYGEN, OXYGEN),
    ('oxygen_risk', '当前溶解氧有没有异常？', OXYGEN, OXYGEN),
    ('uncertainty', '为什么不能确认水质正常？', ALL, ALL),
    ('uncertainty', '为什么现在不能说水质正常？', ALL, ALL),
    ('uncertainty', '为什么还不能确认正常？', CLARIFY, CLARIFY),
    ('uncertainty', '那为什么不能确认水质正常？', CLARIFY, CLARIFY),
    ('freshness', '当前监测数据是不是过期了？', CLARIFY, CLARIFY),
    ('freshness', '数据还是最新的吗？', CLARIFY, CLARIFY),
    ('freshness', '现在水质数据是不是过期了？', ALL, ALL),
    ('freshness', '这些pH数据是不是旧的？', PH, PH),
    ('missing_ph', 'pH缺测会有什么影响？', PH, PH),
    ('missing_ph', 'pH没有数据会影响判断吗？', PH, PH),
    ('missing_ph', 'pH缺测是什么意思？', UNSUPPORTED, UNSUPPORTED),
    ('missing_ph', '没有pH能判断水质正常吗？', PH, PH),
    ('next_action', '那现在应该怎么办？', CLARIFY, OXYGEN),
    ('next_action', '那该怎么办？', CLARIFY, CLARIFY),
    ('next_action', '现在应该怎么办？', CLARIFY, CLARIFY),
    ('next_action', '那溶解氧该怎么办？', CLARIFY, OXYGEN),
    ('suitability', '现在适合养鱼吗？', CLARIFY, CLARIFY),
    ('suitability', '现在水质适合养鱼吗？', ALL, ALL),
    ('suitability', '这个鱼塘适不适合养鱼？', CLARIFY, CLARIFY),
    ('suitability', '可以保证鱼健康吗？', CLARIFY, CLARIFY),
    ('control', '你好', ('greeting', 'all'), ('greeting', 'all')),
    ('control', '你能做什么？', ('capabilities', 'all'), ('capabilities', 'all')),
    ('control', '/帮助', ('fixed', 'all'), ('fixed', 'all')),
    ('control', '/清空会话', ('clear', 'all'), ('clear', 'all')),
    ('control', '/未知指令 水质', UNSUPPORTED, UNSUPPORTED),
    ('control', '请控制增氧泵', UNSUPPORTED, UNSUPPORTED),
    ('control', '过去一小时水质怎么变化？', UNSUPPORTED, UNSUPPORTED),
    ('control', '请介绍水质助手功能', ALL, ALL),
)
OBSERVATIONS = []


def corpus_projection():
    rows = []
    for family, question, no_history, with_topic in CORPUS:
        for label, topic, expected in (
                ('no_history', None, no_history),
                ('accepted_oxygen_topic', 'dissolved_oxygen_mg_l', with_topic)):
            actual = classify(question, topic=topic)
            rows.append(dict(family=family, question=question, context=label,
                             kind=actual.kind, focus=actual.focus,
                             baseline_matches=(actual.kind, actual.focus) == expected))
    return rows


class WaterIntentAuditTests(unittest.TestCase):
    @contextmanager
    def run_fixture(self, *, turns=2, quality='valid', oxygen=6.5, stale=False):
        case = fixture.SessionRunTrialTests(
            'test_once_approved_five_typed_turns_resources_and_current_sources')
        case.setUp()
        try:
            case.ingest(quality, oxygen=oxygen)
            if stale:
                case.now += timedelta(seconds=122)
            case.compose(turns=turns)
            yield case
        finally:
            self.assertTrue(case.doCleanups())

    def observe(self, name, case, *, routes, reads):
        quota = case.host.ledger.report()
        entry = dict(case=name, routes=dict(Counter(routes)),
                     fake_model_http=len(case.http), monitoring_reads=reads,
                     reserved_turns=quota['consumed_turns'],
                     reserved_model_requests=quota['reserved_model_requests'],
                     reserved_cost_cny=quota['reserved_cost_cny'])
        OBSERVATIONS.append(entry)
        return entry

    def test_corpus_current_routes_not_claimed_as_future_acceptance(self):
        rows = corpus_projection()
        self.assertEqual(len(rows), 72)
        for row in rows:
            with self.subTest(question=row['question'], context=row['context']):
                self.assertTrue(row['baseline_matches'])

    def test_question_rewrite_loses_requested_reason_not_just_metric(self):
        # These are the same paid question today, despite distinct user intent.
        self.assertEqual(classify('水质数据可靠吗？').question,
                         classify('为什么不能确认水质正常？').question)
        self.assertEqual(classify('pH缺测会有什么影响？').question,
                         classify('当前pH是多少？').question)
        self.assertNotIn('缺测影响', classify('pH缺测会有什么影响？').question)

    def test_current_free_templates_do_not_reserve_or_query(self):
        with self.run_fixture(turns=1) as case:
            questions = ('现在的数据可靠吗？', '有没有低氧风险？',
                         '当前监测数据是不是过期了？', '现在适合养鱼吗？',
                         '你好', '你能做什么？', '请控制增氧泵', '过去一小时水质怎么变化？')
            routes = []
            self.assertEqual(case.access.member_per_minute, 6)
            with patch.object(case.host.monitoring, 'capture_water',
                              side_effect=AssertionError('template must not query')) as capture:
                for index, question in enumerate(questions):
                    expected = 'QQ_REPLY_API_ACCEPTED' if index < 6 else 'RATE_LIMITED'
                    self.assertEqual(case.receive(question)[0], expected)
                    routes.append(classify(question).kind if index < 6 else 'rate_denied')
            row = self.observe('templates', case,
                routes=routes, reads=capture.call_count)
            self.assertEqual(row['reserved_turns'], 0)
            self.assertEqual(row['fake_model_http'], 0)
            self.assertEqual(row['monitoring_reads'], 0)

    def test_existing_water_and_ph_routes_spend_independent_turns(self):
        with self.run_fixture(turns=2) as case:
            before = hashlib.sha256(case.path.read_bytes()).hexdigest()
            with patch.object(case.host.monitoring, 'capture_water',
                              wraps=case.host.monitoring.capture_water) as capture:
                for question in ('为什么不能确认水质正常？', 'pH缺测会有什么影响？'):
                    self.assertEqual(case.ask(question)['history_code'], 'HISTORY_COMMITTED')
            row = self.observe('existing_paid', case, routes=['water', 'water'], reads=capture.call_count)
            self.assertEqual((row['reserved_turns'], row['fake_model_http'], row['monitoring_reads']), (2, 4, 2))
            self.assertEqual(before, hashlib.sha256(case.path.read_bytes()).hexdigest())

    def test_action_needs_accepted_topic_then_reads_new_current_data(self):
        with self.run_fixture(turns=2) as case:
            self.assertEqual(case.receive('那现在应该怎么办？')[0], 'QQ_REPLY_API_ACCEPTED')
            self.assertEqual(case.http, [])
            with patch.object(case.host.monitoring, 'capture_water',
                              wraps=case.host.monitoring.capture_water) as capture:
                self.assertEqual(case.ask('当前溶解氧是多少？')['history_code'], 'HISTORY_COMMITTED')
                case.ingest(oxygen=2.2)
                self.assertEqual(case.ask('那现在应该怎么办？')['history_code'], 'HISTORY_COMMITTED')
            source = case.host.sessions[-1].source
            self.assertEqual(next(m.value for m in source.metrics if m.id == 'dissolved_oxygen_mg_l'), 2.2)
            self.assertTrue(source.rule_hits)
            self.assertNotIn('溶解氧：6.5', case.posts[-1]['content'])
            row = self.observe('action_followup', case, routes=['clarify', 'water', 'water'], reads=capture.call_count)
            self.assertEqual((row['reserved_turns'], row['fake_model_http'], row['monitoring_reads']), (2, 4, 2))

    def test_topic_switch_and_history_do_not_create_extra_model_requests(self):
        with self.run_fixture(turns=3) as case:
            focuses = []
            with patch.object(case.host.monitoring, 'capture_water',
                              wraps=case.host.monitoring.capture_water) as capture:
                for question in ('现在水质怎么样？', '那溶解氧呢？', '那pH呢？'):
                    self.assertEqual(case.ask(question)['history_code'], 'HISTORY_COMMITTED')
                    focuses.append(next(iter(case.host.store._sessions.values())).turns[-1].focus)
            self.assertEqual(focuses, ['all', 'dissolved_oxygen_mg_l', 'ph'])
            row = self.observe('topic_switch', case, routes=['water'] * 3, reads=capture.call_count)
            self.assertEqual((row['reserved_turns'], row['fake_model_http'], row['monitoring_reads']), (3, 6, 3))

    def test_quality_grid_uses_domain_findings_not_raw_oxygen_thresholds(self):
        for name, quality, oxygen, stale in (
                ('fresh_valid', 'valid', 6.5, False),
                ('partial_missing', 'missing', 6.5, False),
                ('stale_offline', 'valid', 6.5, True),
                ('fresh_low_hit', 'valid', 2.2, False),
                ('stale_low_not_evaluated', 'valid', 2.2, True)):
            with self.subTest(name=name), self.run_fixture(
                    turns=1, quality=quality, oxygen=oxygen, stale=stale) as case:
                before = hashlib.sha256(case.path.read_bytes()).hexdigest()
                with patch.object(case.host.monitoring, 'capture_water',
                                  wraps=case.host.monitoring.capture_water) as capture:
                    self.assertEqual(case.ask('当前水温是多少？')['history_code'], 'HISTORY_COMMITTED')
                source = case.host.sessions[-1].source
                text = case.posts[-1]['content']
                self.assertIn('SIMULATOR', text)
                if quality == 'missing':
                    self.assertEqual(source.quality, 'partial')
                    self.assertIn('pH：数据不足（缺测）', text)
                if stale:
                    self.assertEqual((source.freshness, source.connectivity), ('stale', 'offline'))
                    self.assertEqual(source.rule_hits, ())
                    for warning in ('数据过期', '设备离线', '留存读数', '不能完整确认'):
                        self.assertIn(warning, text)
                    self.assertNotIn('系统实验规则', text)
                    self.assertNotIn('未触发水质实验规则', text)
                elif name == 'fresh_low_hit':
                    self.assertTrue(any(r.code == 'OXYGEN_CRITICAL_LOW' for r in source.rule_hits))
                    self.assertIn('严重', text)
                    self.assertIn('系统实验规则', text)
                else:
                    self.assertEqual(source.rule_hits, ())
                self.assertNotIn('当前正常', text)
                row = self.observe(name, case, routes=['water'], reads=capture.call_count)
                self.assertEqual((row['reserved_turns'], row['fake_model_http'], row['monitoring_reads']), (1, 2, 1))
                self.assertEqual(before, hashlib.sha256(case.path.read_bytes()).hexdigest())

    def test_unauthorized_member_and_revoked_group_are_free_denials(self):
        with self.run_fixture(turns=1) as case:
            with patch.object(case.host.monitoring, 'capture_water',
                              side_effect=AssertionError('denied must not query')) as capture:
                self.assertEqual(case.receive('当前水质如何？', member='intruder')[0], 'MEMBER_DENIED')
                case.router.revoke_group('group-a')
                self.assertEqual(case.receive('当前水质如何？')[0], 'GROUP_DENIED')
            row = self.observe('authorization_denial', case, routes=['denied', 'denied'], reads=capture.call_count)
            self.assertEqual((row['reserved_turns'], row['fake_model_http']), (0, 0))

    def test_duplicate_and_exhaustion_do_not_spend_again(self):
        with self.run_fixture(turns=1) as case:
            case.gateway._dispatch_authenticated(json.loads(case.packet(text='当前水质如何？')))
            raw, _, proof = case.gateway._queue.get_nowait()
            case.gateway._queue.task_done()
            with patch.object(case.host.monitoring, 'capture_water',
                              wraps=case.host.monitoring.capture_water) as capture:
                code, task = case.router.receive(raw, transport_app_id=fixture.APP, mention=proof)
                self.assertEqual(code, 'AI_ADMITTED')
                self.assertEqual(case.scheduler.wait(task, 95)['history_code'], 'HISTORY_COMMITTED')
                self.assertEqual(case.router.receive(raw, transport_app_id=fixture.APP, mention=proof)[0], 'DUPLICATE')
                self.assertEqual(case.receive('当前pH是多少？')[0], 'RUN_TURN_LIMIT')
            row = self.observe('duplicate_and_limit', case,
                routes=['water', 'duplicate', 'quota_denied'], reads=capture.call_count)
            self.assertEqual((row['reserved_turns'], row['fake_model_http'], row['monitoring_reads']), (1, 2, 1))

    def test_untrusted_mention_has_zero_model_and_ledger_effect(self):
        with self.run_fixture(turns=1) as case:
            raw = case.packet(text='@机器人 当前水质如何？')
            with patch.object(case.host.monitoring, 'capture_water',
                              side_effect=AssertionError('forged mention must not query')) as capture:
                self.assertEqual(case.router.receive(raw, transport_app_id=fixture.APP)[0],
                                 'AI_AUTHENTICATED_MENTION_REQUIRED')
            row = self.observe('untrusted_mention', case, routes=['denied'], reads=capture.call_count)
            self.assertEqual((row['reserved_turns'], row['fake_model_http']), (0, 0))
