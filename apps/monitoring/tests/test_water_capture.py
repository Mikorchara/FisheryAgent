"""One capture, separate Web / Tool projections; temporary SQLite, no Provider."""

from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timedelta
import json
from unittest.mock import patch
import unittest

from apps.management_web.ai_adapter import project_water_tool, water_payload
from apps.monitoring.contracts import metric_quality
from apps.monitoring.service import project_water_snapshot
import apps.monitoring.tests.test_business_services as fixture


DEVICE = 'sim-pond-1'


class WaterCaptureTests(unittest.TestCase):
    setUp = fixture.BusinessServiceTests.setUp
    batch = fixture.BusinessServiceTests.batch

    def test_current_capture_reads_once_classifies_once_and_diagnoses_once(self):
        self.service.ingest(self.batch())
        with patch.object(self.repo, 'read', wraps=self.repo.read) as read, \
             patch.object(self.repo, 'capture', side_effect=AssertionError('no Web history')), \
             patch.object(self.repo, 'history', side_effect=AssertionError('no history query')), \
             patch('apps.monitoring.contracts.metric_quality', wraps=metric_quality) as classify, \
             patch.object(self.service.diagnosis, 'diagnose', wraps=self.service.diagnosis.diagnose) as diagnose:
            capture = self.service.capture_water(DEVICE)
            read.assert_called_once_with(DEVICE, 'water')
            self.assertEqual(classify.call_count, 3)
            diagnose.assert_called_once()
            with patch.object(self.service.domain_analysis, 'capture_water', side_effect=AssertionError('no reanalysis')):
                web, tool = project_water_snapshot(capture), project_water_tool(capture)
            self.assertEqual(classify.call_count, 3)
            diagnose.assert_called_once()
        self.assertEqual(web.batch_id, tool['batch_id'])

    def test_same_capture_yields_matching_facts_rules_quality_and_time(self):
        self.service.ingest(self.batch())
        capture = self.service.capture_water(DEVICE)
        web, tool = project_water_snapshot(capture), project_water_tool(capture)
        self.assertEqual(web.device_id, tool['device_id'])
        self.assertEqual(web.batch_id, tool['batch_id'])
        self.assertEqual(web.evaluated_at, tool['evaluated_at'])
        self.assertEqual(web.received_at, tool['water_quality']['retrieved_at'])
        self.assertEqual(web.observed_at, tool['water_quality']['observed_at'])
        self.assertEqual(web.window, tool['window'])
        self.assertEqual(web.aggregation, tool['aggregation'])
        self.assertEqual(web.source_kind, tool['source_kind'])
        self.assertEqual(web.analysis['data_quality'], tool['data_quality'])
        self.assertEqual(tool['water_quality']['source'], capture.reading.source)
        for metric in web.metrics:
            self.assertEqual(tool['water_quality'][metric.id], metric.value)
            self.assertEqual(tool['metrics'][metric.id]['unit'], metric.unit)
        for actual, expected in zip(tool['findings'], capture.analysis.findings):
            self.assertEqual(actual['code'], expected.code)
            self.assertEqual(actual['state'], expected.state.value)
            self.assertEqual(actual['facts_used'], list(expected.facts_used))
            self.assertEqual(actual['rule'], asdict(expected.rule))
            self.assertNotIn('observation', actual)
        self.assertEqual(web.rule_version, tool['rule_version'])

    def test_capture_detached_from_new_batch_and_projections_cannot_mutate_it(self):
        self.service.ingest(self.batch(2.2))
        capture = self.service.bind(DEVICE).capture_water()
        before = project_water_tool(capture)
        self.service.ingest(self.batch(6.4))
        self.assertEqual(project_water_tool(capture), before)
        new = self.service.capture_water(DEVICE)
        self.assertNotEqual(capture.analysis.observation.batch_id, new.analysis.observation.batch_id)
        self.assertEqual(new.reading.dissolved_oxygen_mg_l, 6.4)
        tool, web = project_water_tool(capture), project_water_snapshot(capture)
        tool['findings'][0]['rule']['scope'] = []
        tool['data_quality']['coverage'] = []
        web.analysis['findings'].clear()
        web.window['end'] = 'changed'
        self.assertEqual(project_water_tool(capture), before)
        with self.assertRaises(FrozenInstanceError): capture.metrics[0].mean = 0

    def test_new_ingestion_between_read_and_analysis_cannot_mix_batches(self):
        old = self.batch(2.2); self.service.ingest(old)
        new = self.batch(6.4)
        original = self.repo.read
        def read_then_ingest(*args):
            row = original(*args)
            self.service.ingest(new)
            return row
        with patch.object(self.repo, 'read', side_effect=read_then_ingest) as read:
            capture = self.service.capture_water(DEVICE)
        read.assert_called_once_with(DEVICE, 'water')
        tool = project_water_tool(capture)
        self.assertEqual(tool['batch_id'], old['batch_id'])
        self.assertEqual(tool['water_quality']['dissolved_oxygen_mg_l'], 2.2)
        self.assertEqual(tool['water_quality']['observed_at'], old['timestamp'])
        self.assertTrue(all(f.observation.batch_id == old['batch_id'] for f in capture.analysis.findings))
        self.assertEqual(self.repo.read(DEVICE, 'water')['batch_id'], new['batch_id'])

    def test_analysis_entry_and_web_keep_single_capture_evaluation(self):
        self.service.ingest(self.batch())
        with patch.object(self.repo, 'read', wraps=self.repo.read) as read, \
             patch.object(self.service.diagnosis, 'diagnose', wraps=self.service.diagnosis.diagnose) as diagnose:
            assessment = self.service.analysis(DEVICE)
            read.assert_called_once_with(DEVICE, 'water'); diagnose.assert_called_once()
        with patch.object(self.repo, 'capture', wraps=self.repo.capture) as read, \
             patch.object(self.service.diagnosis, 'diagnose', wraps=self.service.diagnosis.diagnose) as diagnose:
            web = self.service.snapshot(DEVICE)
            read.assert_called_once_with(DEVICE, 'water'); diagnose.assert_called_once()
        self.assertEqual(web.analysis, assessment.to_dict())

    def test_tool_does_not_call_web_or_analysis_query(self):
        self.service.ingest(self.batch())
        with patch.object(self.service, 'snapshot', side_effect=AssertionError('not a Web DTO')), \
             patch.object(self.service, 'analysis', side_effect=AssertionError('no second read')), \
             patch.object(self.repo, 'read', wraps=self.repo.read) as read:
            tool = water_payload(self.service, DEVICE)
        read.assert_called_once_with(DEVICE, 'water')
        self.assertEqual(tool['status'], 'OK')

    def test_current_query_evaluation_clock_follows_read_and_updates_without_mutation(self):
        self.service.ingest(self.batch())
        original = self.repo.read
        def delayed_read(*args):
            row = original(*args); self.now += timedelta(seconds=31); return row
        with patch.object(self.repo, 'read', side_effect=delayed_read):
            capture = self.service.capture_water(DEVICE)
        self.assertEqual(capture.reading.freshness.value, 'stale')
        self.assertEqual(capture.analysis.evaluated_at, self.now.isoformat())
        self.assertEqual(self.repo.read(DEVICE, 'water')['observed_at'], capture.analysis.observation.observed_at)
        self.assertTrue(all(f.state.value=='NOT_EVALUATED' for f in capture.analysis.findings if f.kind=='WATER_RISK'))

    def test_no_data_no_snapshot_no_observation_not_normal(self):
        capture = self.service.capture_water(DEVICE)
        tool, web = project_water_tool(capture), project_water_snapshot(capture)
        self.assertEqual(tool['status'], 'NO_DATA')
        self.assertIsNone(tool['water_quality']); self.assertEqual(tool['findings'], [])
        self.assertEqual(tool['data_quality']['quality'], 'missing')
        self.assertEqual(tool['connectivity'], 'never_received')
        self.assertIsNone(tool['batch_id']); self.assertEqual(capture.metrics, ())
        self.assertEqual(web.quality, 'missing')
        self.assertTrue(all(m.value is None for m in web.metrics))

    def test_partial_invalid_all_missing_and_incomplete_coverage(self):
        for mode, dq, canonical in [('missing_do', 'partial', 'partial'),
                                   ('partial_do', 'partial', 'partial'),
                                   ('invalid_do', 'invalid', 'invalid'),
                                   ('all_missing', 'missing', 'invalid')]:
            with self.subTest(mode=mode):
                b = self.batch()
                stats = b['water']['metrics']
                if mode == 'all_missing':
                    for stat in stats.values():
                        stat.update(mean=None,min=None,max=None,latest=None,valid_samples=0,invalid_samples=0)
                elif mode == 'partial_do':
                    stats['dissolved_oxygen_mg_l']['valid_samples'] -= 1
                else:
                    stats['dissolved_oxygen_mg_l'].update(mean=None,min=None,max=None,latest=None,
                        valid_samples=0,invalid_samples=1 if mode=='invalid_do' else 0)
                self.service.ingest(b)
                capture = self.service.capture_water(DEVICE)
                web, tool = project_water_snapshot(capture), project_water_tool(capture)
                self.assertEqual(tool['status'], 'OK')  # A received window exists.
                self.assertEqual(web.quality, dq)
                self.assertEqual(tool['data_quality']['quality'], dq)
                self.assertEqual(tool['water_quality']['quality'], canonical)
                self.assertIsNone(tool['water_quality']['dissolved_oxygen_mg_l'])
                self.assertEqual(tool['data_quality']['coverage'], asdict(capture.analysis.data_quality)['coverage'])
                oxygen = [f for f in tool['findings'] if f['kind']=='WATER_RISK' and 'dissolved_oxygen_mg_l' in f['facts_used']]
                self.assertTrue(all(f['state']=='INSUFFICIENT_EVIDENCE' for f in oxygen))

    def test_stale_offline_keep_received_values_but_never_confirm_risk_or_recovery(self):
        self.service.ingest(self.batch(2.2))
        first = self.service.capture_water(DEVICE)
        for age, connectivity in [(31, 'online'), (91, 'offline')]:
            self.now = datetime.fromisoformat(first.analysis.observation.observed_at) + timedelta(seconds=age)
            capture = self.service.capture_water(DEVICE)
            web, tool = project_water_snapshot(capture), project_water_tool(capture)
            self.assertEqual(tool['water_quality']['dissolved_oxygen_mg_l'], 2.2)
            self.assertEqual(tool['water_quality']['freshness'], 'stale')
            self.assertEqual(tool['connectivity'], connectivity)
            self.assertEqual(web.last_reported_at, tool['last_reported_at'])
            self.assertTrue(all(f['state']=='NOT_EVALUATED' for f in tool['findings'] if f['kind']=='WATER_RISK'))
        self.assertEqual(first.reading.freshness.value, 'fresh')

    def test_tool_dto_bounded_and_smaller_without_losing_unassessed_findings(self):
        for oxygen in (2.2, 6.4):
            self.service.ingest(self.batch(oxygen))
            capture = self.service.capture_water(DEVICE)
            tool = project_water_tool(capture)
            web = project_water_snapshot(capture)
            size = len(json.dumps(tool, ensure_ascii=False, separators=(',',':')).encode())
            # Before: full Web analysis plus a second HIT finding list.
            old = {key: tool[key] for key in ('status', 'water_quality', 'evaluated_at', 'rule_version',
                'device_id', 'source_kind', 'batch_id', 'window', 'aggregation', 'connectivity')}
            old.update(analysis=web.analysis, findings=web.findings)
            old_size = len(json.dumps(old, ensure_ascii=False, separators=(',',':')).encode())
            self.assertLess(size, 10000)
            self.assertLess(size, old_size * .8)
            for key in ('analysis','trend','label','minimum','maximum','latest','value'):
                self.assertNotIn('"'+key+'":', json.dumps(tool))
            self.assertEqual(len(tool['findings']), len(capture.analysis.findings))
            self.assertEqual(tool['projection_version'], 'management-current-water@1')
            self.assertEqual(tool['statistics_version'], 'window_mean-v1')

    def test_device_and_view_validation_remains_closed(self):
        with self.assertRaises(ValueError): self.service.capture_water('unregistered')
        with self.assertRaises(ValueError): self.service.snapshot(DEVICE, 'demo')
