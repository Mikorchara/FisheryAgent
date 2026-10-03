"""Offline research fixtures; do not expand the package/UI scenario catalog."""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import socket
import unittest

from fishery_ai.application import result_to_dict
from fishery_ai.composition import RESOURCE_ROOT, build_offline_demo
from fishery_ai.contracts import (AnalysisRequest, DetectionSummary, Freshness, Mode,
                                  Quality, WaterQualityReading, parse_time)
from fishery_ai.domain import DiagnosisService
from fishery_ai.repositories import MockRepository


PROPOSED_CASES = (
    ('temp_low', 18, 7.5, 6.4, False, Quality.VALID, ('TEMP_LOW',)),
    ('temp_extreme_low', 14, 7.5, 6.4, False, Quality.VALID, ('TEMP_CRITICAL_LOW',)),
    ('temp_high', 31, 7.5, 6.4, False, Quality.VALID, ('TEMP_HIGH',)),
    ('temp_extreme_high', 34, 7.5, 6.4, False, Quality.VALID, ('TEMP_CRITICAL_HIGH',)),
    ('ph_low', 28, 6.8, 6.4, False, Quality.VALID, ('PH_LOW',)),
    ('ph_extreme_low', 28, 6.4, 6.4, False, Quality.VALID, ('PH_CRITICAL_LOW',)),
    ('ph_high', 28, 8.8, 6.4, False, Quality.VALID, ('PH_HIGH',)),
    ('ph_extreme_high', 28, 9.1, 6.4, False, Quality.VALID, ('PH_CRITICAL_HIGH',)),
    ('oxygen_warning', 28, 7.5, 4, False, Quality.VALID, ('OXYGEN_LOW',)),
    ('oxygen_extreme', 28, 7.5, 0.9, False, Quality.VALID, ('OXYGEN_CRITICAL_EXTREME',)),
    ('oxygen_high_no_rule', 28, 7.5, 12, False, Quality.VALID, ()),
    ('hot_low_oxygen', 34, 7.5, 2.2, False, Quality.VALID,
     ('TEMP_CRITICAL_HIGH', 'OXYGEN_CRITICAL_LOW')),
    ('ph_high_low_oxygen', 28, 9.1, 2.2, False, Quality.VALID,
     ('PH_CRITICAL_HIGH', 'OXYGEN_CRITICAL_LOW')),
    ('multi_critical', 34, 9.1, 0.9, False, Quality.VALID,
     ('TEMP_CRITICAL_HIGH', 'PH_CRITICAL_HIGH', 'OXYGEN_CRITICAL_EXTREME')),
    ('partial_low_oxygen', 28, None, 2.2, False, Quality.PARTIAL,
     ('SENSOR_PARTIAL', 'OXYGEN_CRITICAL_LOW')),
    ('stale_low_oxygen', 28, 7.5, 2.2, True, Quality.VALID,
     ('SENSOR_STALE', 'OXYGEN_CRITICAL_LOW')),
    ('partial_stale_low_oxygen', 28, None, 2.2, True, Quality.PARTIAL,
     ('SENSOR_PARTIAL', 'SENSOR_STALE', 'OXYGEN_CRITICAL_LOW')),
    ('invalid_temp_low_oxygen', 'bad', 7.5, 2.2, False, Quality.INVALID,
     ('SENSOR_INVALID', 'OXYGEN_CRITICAL_LOW')),
    ('all_missing', None, None, None, False, Quality.INVALID, ('SENSOR_INVALID',)),
)


class WaterQualityMatrixTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.create_connection', 'socket.getaddrinfo', 'socket.socket.sendto'):
            blocker = patch(target, side_effect=AssertionError('offline matrix forbids network'))
            blocker.start()
            self.addCleanup(blocker.stop)
        self.service = DiagnosisService()
        self.observed = parse_time('2026-09-27T00:00:00Z')
        self.repository = MockRepository(RESOURCE_ROOT.joinpath('mock/scenarios.json'))

    def reading(self, temp=28, ph=7.5, oxygen=6.4, *, age=20, stale_after=300):
        return WaterQualityReading.from_raw({'temp': temp, 'ph': ph, 'oxygen': oxygen},
            observed_at=self.observed, retrieved_at=self.observed + timedelta(seconds=age),
            source='mock:matrix-only', stale_after_s=stale_after)

    def codes(self, reading):
        return tuple(f.code for f in self.service.diagnose(reading))

    def test_current_packaged_catalog_values_times_sources_and_quality(self):
        expected = {
            'normal': (7.5, 20, Quality.VALID, (), 6.4),
            'low_oxygen': (7.5, 20, Quality.VALID, ('OXYGEN_CRITICAL_LOW',), 2.2),
            'partial': (None, 20, Quality.PARTIAL, ('SENSOR_PARTIAL',), 6.4),
            'stale': (7.5, 3620, Quality.VALID, ('SENSOR_STALE',), 6.4),
            'partial_stale': (None, 3620, Quality.PARTIAL, ('SENSOR_PARTIAL', 'SENSOR_STALE'), 6.4),
        }
        self.assertEqual(set(self.repository.data['water_quality']), set(expected))
        for name, (ph, age, quality, codes, oxygen) in expected.items():
            with self.subTest(name=name):
                reading = self.repository.water_quality(name)
                self.assertEqual((reading.temperature_c, reading.ph, reading.dissolved_oxygen_mg_l),
                                 (28, ph, oxygen))
                self.assertEqual((reading.retrieved_at-reading.observed_at).total_seconds(), age)
                self.assertEqual(reading.retrieved_at, parse_time('2026-09-27T00:00:20Z'))
                self.assertEqual(reading.source, self.repository.data['water_quality'][name]['source'])
                self.assertEqual(reading.quality, quality)
                self.assertEqual(reading.freshness, Freshness.STALE if age > 300 else Freshness.FRESH)
                self.assertEqual(self.codes(reading), codes)

    def check_boundaries(self, field, cases):
        for boundary, codes in cases:
            for value, code in zip((boundary - .01, boundary, boundary + .01), codes):
                with self.subTest(field=field, boundary=boundary, value=value):
                    findings = self.service.diagnose(self.reading(**{field: value}))
                    self.assertEqual(tuple(f.code for f in findings), (code,) if code else ())
                    if findings:
                        expected_fact = {'temp': 'temperature_c', 'ph': 'ph',
                                         'oxygen': 'dissolved_oxygen_mg_l'}[field]
                        self.assertEqual(findings[0].facts_used, (expected_fact,))
                        self.assertEqual(findings[0].rule_version, 'fishery-production-c400b7a-v1')
                        self.assertEqual(findings[0].severity, 'critical' if 'CRITICAL' in code else 'warning')

    def test_temperature_three_point_boundaries(self):
        self.check_boundaries('temp', (
            (15, ('TEMP_CRITICAL_LOW', 'TEMP_LOW', 'TEMP_LOW')),
            (20, ('TEMP_LOW', None, None)), (30, (None, None, 'TEMP_HIGH')),
            (33, ('TEMP_HIGH', 'TEMP_HIGH', 'TEMP_CRITICAL_HIGH'))))

    def test_ph_three_point_boundaries(self):
        self.check_boundaries('ph', (
            (6.5, ('PH_CRITICAL_LOW', 'PH_LOW', 'PH_LOW')),
            (7, ('PH_LOW', None, None)), (8.5, (None, None, 'PH_HIGH')),
            (9, ('PH_HIGH', 'PH_HIGH', 'PH_CRITICAL_HIGH'))))

    def test_oxygen_three_point_boundaries(self):
        self.check_boundaries('oxygen', (
            (1, ('OXYGEN_CRITICAL_EXTREME', 'OXYGEN_CRITICAL_LOW', 'OXYGEN_CRITICAL_LOW')),
            (3, ('OXYGEN_CRITICAL_LOW', 'OXYGEN_LOW', 'OXYGEN_LOW')),
            (5, ('OXYGEN_LOW', None, None))))

    def test_proposed_fixture_matrix_keeps_quality_and_numeric_findings_independent(self):
        for name, temp, ph, oxygen, stale, quality, expected in PROPOSED_CASES:
            with self.subTest(name=name):
                reading = self.reading(temp, ph, oxygen, age=3620 if stale else 20)
                self.assertEqual(reading.quality, quality)
                self.assertEqual(reading.freshness, Freshness.STALE if stale else Freshness.FRESH)
                self.assertEqual(self.codes(reading), expected)
                self.assertTrue(all(f.rule_version == self.service.RULE_VERSION
                                    for f in self.service.diagnose(reading)))

    def test_invalid_values_vs_missing_are_not_zeros(self):
        for field, values in (
            ('temp', ('bad', float('nan'), float('inf'), -51, 101)),
            ('ph', ('bad', float('-inf'), -.1, 14.1)),
            ('oxygen', ('bad', float('nan'), -1, 101))):
            for value in values:
                with self.subTest(field=field, kind=type(value).__name__):
                    reading = self.reading(**{field: value})
                    self.assertEqual(reading.quality, Quality.INVALID)
                    self.assertEqual(self.codes(reading), ('SENSOR_INVALID',))
        for missing in (None, '', '--'):
            reading = self.reading(ph=missing)
            self.assertEqual(reading.quality, Quality.PARTIAL)
            self.assertIsNone(reading.ph)
        self.assertEqual(self.reading('28', '7.5', '6.4').quality, Quality.VALID)
        omitted = WaterQualityReading.from_raw({'temp': 28, 'oxygen': 2.2},
            observed_at=self.observed, retrieved_at=self.observed, source='mock:missing-key', stale_after_s=300)
        self.assertIsNone(omitted.ph)
        self.assertEqual(self.codes(omitted), ('SENSOR_PARTIAL', 'OXYGEN_CRITICAL_LOW'))
        self.assertEqual(self.reading(oxygen=100).quality, Quality.VALID)
        self.assertEqual(self.codes(self.reading(oxygen=100)), ())
        self.assertEqual(self.codes(self.reading(oxygen=0)), ('OXYGEN_CRITICAL_EXTREME',))

    def test_stale_policy_exact_boundary_and_bad_time_contracts(self):
        self.assertEqual(self.reading(age=300).freshness, Freshness.FRESH)
        self.assertEqual(self.reading(age=301).freshness, Freshness.STALE)
        self.assertEqual(self.reading(age=3620, stale_after=4000).freshness, Freshness.FRESH)
        self.assertEqual(self.reading(age=0, stale_after=0).freshness, Freshness.FRESH)
        for kwargs in ({'age': -1}, {'stale_after': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.reading(**kwargs)
        with self.assertRaises(ValueError):
            parse_time('2026-09-27T00:00:00')

    def test_detection_fixtures_remain_separate_and_default_observed_facts_have_no_detection(self):
        for name, count, mean in (('normal', 2, .905), ('count_jump', 7, 6.18 / 7)):
            summary = DetectionSummary.from_event(self.repository.detection(name))
            self.assertEqual(summary.count, count)
            self.assertAlmostEqual(summary.mean_confidence, mean)
        with TemporaryDirectory() as directory:
            orchestrator, _ = build_offline_demo(trace_path=Path(directory) / 'trace.jsonl')
            for mode in (Mode.CHAT, Mode.ADVICE):
                result = orchestrator.analyze(AnalysisRequest(mode, 'cloud-demo', 'water quality?'),
                                              scenario='partial_stale')
                self.assertIsNone(result.observed_facts.detection_summary)
                self.assertEqual(result_to_dict(result)['observed_facts']['water_quality']['ph'], None)

    def test_matrix_network_protection(self):
        with self.assertRaisesRegex(AssertionError, 'offline matrix forbids network'):
            socket.getaddrinfo('example.invalid', 443)
