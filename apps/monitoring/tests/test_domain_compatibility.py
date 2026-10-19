"""MIG-1 differential evidence. Only this test intentionally imports old domain code."""
from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import datetime, timedelta, timezone
from itertools import product
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from apps.monitoring import water_contracts as water
from apps.monitoring.current import CurrentWaterQualityReader
from apps.monitoring.diagnosis import DiagnosisService
from apps.ai_service.runtime import sources


STAMP = datetime(2026, 10, 16, tzinfo=timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        default=lambda item: item.isoformat())


def outcome(call):
    try:
        value = call()
        return ('ok', canonical(asdict(value)) if hasattr(value, '__dataclass_fields__') else value)
    except Exception as error:
        return (type(error).__name__, str(error))


class WaterDomainCompatibilityTests(unittest.TestCase):
    def old(self):
        from fishery_ai import contracts, domain
        return contracts, domain

    def test_field_values_immutability_and_new_type_ownership(self):
        old, _ = self.old()
        self.assertEqual([f.name for f in fields(water.WaterQualityReading)],
                         [f.name for f in fields(old.WaterQualityReading)])
        for enum in ('Quality', 'Freshness'):
            self.assertEqual([(item.name,item.value) for item in getattr(water,enum)],
                             [(item.name,item.value) for item in getattr(old,enum)])
            self.assertIsNot(getattr(water,enum),getattr(old,enum))
        reading = water.WaterQualityReading(28,7.5,6.4,STAMP,STAMP,'fixture',water.Quality.VALID,water.Freshness.FRESH)
        with self.assertRaises(FrozenInstanceError): reading.source='changed'
        with self.assertRaisesRegex(ValueError,'quality must be a Quality value'):
            replace(reading,quality=old.Quality.VALID)
        with self.assertRaisesRegex(ValueError,'freshness must be a Freshness value'):
            replace(reading,freshness=old.Freshness.FRESH)
        self.assertIs(sources.Quality,water.Quality)
        self.assertIs(sources.Freshness,water.Freshness)
        self.assertIs(sources.WaterQualityReading,water.WaterQualityReading)

    def test_raw_normal_missing_invalid_and_physical_boundaries_match(self):
        old, _ = self.old()
        cases=[{}, {'temp':28,'ph':7.5,'oxygen':6.4}, {'temp':28,'oxygen':2.2},
            {'temp':None,'ph':'--','oxygen':''}, {'temp':'28','ph':True,'oxygen':'2.2'},
            {'temp':float('nan')}, {'oxygen':float('inf')}, {'ph':15},
            {'temp':-50,'ph':0,'oxygen':0}, {'temp':100,'ph':14,'oxygen':100},
            {'temp':-50.1,'ph':7.5,'oxygen':6.4}, {'temp':object()}, {'oxygen':10**1000}]
        for raw in cases:
            with self.subTest(case=len(str(raw))):
                def run(module):
                    return module.WaterQualityReading.from_raw(raw,observed_at=STAMP,
                        retrieved_at=STAMP+timedelta(seconds=31),source='fixture',stale_after_s=30)
                self.assertEqual(outcome(lambda:run(water)),outcome(lambda:run(old)))

    def test_constructor_rejections_and_timestamps_match(self):
        old, _ = self.old()
        cases=[{}, {'source':''}, {'temperature_c':None}, {'ph':float('nan')},
            {'dissolved_oxygen_mg_l':101}, {'observed_at':STAMP+timedelta(seconds=1)},
            {'observed_at':STAMP.replace(tzinfo=None)}, {'quality':'valid'}, {'freshness':'fresh'},
            {'quality':'partial','temperature_c':None,'ph':None,'dissolved_oxygen_mg_l':None}]
        for changes in cases:
            def run(module):
                values=dict(temperature_c=28,ph=7.5,dissolved_oxygen_mg_l=6.4,observed_at=STAMP,
                    retrieved_at=STAMP,source='fixture',quality=module.Quality.VALID,freshness=module.Freshness.FRESH)
                values.update(changes)
                if values['quality']=='partial': values['quality']=module.Quality.PARTIAL
                return module.WaterQualityReading(**values)
            self.assertEqual(outcome(lambda:run(water)),outcome(lambda:run(old)))
        for text in ('2026-10-16T00:00:00Z','2026-10-16T08:00:00+08:00',
                     '2026-10-16T00:00:00','invalid',None):
            self.assertEqual(outcome(lambda:water.parse_time(text)),outcome(lambda:old.parse_time(text)))
        for age in (-1,0,30,30.001,91):
            self.assertEqual(water.evaluate_freshness(STAMP,STAMP+timedelta(seconds=age),30).value,
                             old.evaluate_freshness(STAMP,STAMP+timedelta(seconds=age),30).value)
        for threshold in (True,-1,'30',float('nan'),float('inf'),10**1000):
            self.assertEqual(outcome(lambda:water.evaluate_freshness(STAMP,STAMP,threshold)),
                             outcome(lambda:old.evaluate_freshness(STAMP,STAMP,threshold)))

    def test_diagnosis_threshold_grid_quality_freshness_and_missing_values_match(self):
        old, old_domain = self.old()
        self.assertEqual(DiagnosisService.RULE_VERSION,old_domain.DiagnosisService.RULE_VERSION)
        for values in product((None,14.9,15,19.9,20,30,30.1,33,33.1),
                              (None,6.4,6.5,6.9,7,8.5,8.6,9,9.1),
                              (None,.9,1,2.9,3,4.9,5)):
            present=sum(value is not None for value in values)
            for quality,freshness in (('invalid','stale'),
                    ('valid' if present==3 else 'partial' if present else 'invalid','fresh')):
                rows=[]
                for module,service in ((old,old_domain.DiagnosisService()),(water,DiagnosisService())):
                    reading=module.WaterQualityReading(*values,STAMP,STAMP,'fixture',
                        module.Quality(quality),module.Freshness(freshness))
                    rows.append([asdict(item) for item in service.diagnose(reading)])
                self.assertEqual(*rows)

    def test_reader_reads_once_preserves_metadata_and_does_not_fill_no_data(self):
        old, _ = self.old()
        from fishery_ai.telemetry.current import CurrentWaterQualityReader as OldReader
        for age in (0,30,31,91):
            rows=[]
            for module,reader_type in ((old,OldReader),(water,CurrentWaterQualityReader)):
                reading=module.WaterQualityReading(28,7.5,2.2,STAMP,STAMP,'device:fixture',
                    module.Quality.VALID,module.Freshness.FRESH)
                source=SimpleNamespace(get_current=Mock(return_value=reading))
                clock=Mock(return_value=STAMP+timedelta(seconds=age))
                view=reader_type(source,stale_after_s=30,clock=clock).query()
                source.get_current.assert_called_once_with();clock.assert_called_once_with()
                self.assertEqual(reading.freshness.value,'fresh')
                rows.append(canonical(asdict(view)))
            self.assertEqual(*rows)
        source=SimpleNamespace(get_current=Mock(return_value=None));clock=Mock()
        self.assertIsNone(CurrentWaterQualityReader(source,stale_after_s=30,clock=clock).query())
        source.get_current.assert_called_once_with();clock.assert_not_called()

    def test_source_observation_acceptance_and_rejection_match_old_validator(self):
        from fishery_ai import assistant_sources as old_sources
        from apps.ai_service.runtime.tests.test_foundation import water_payload
        cases=[water_payload(),water_payload(status='NO_DATA'),water_payload(quality='partial'),
               water_payload(quality='invalid'),water_payload(freshness='stale')]
        for changes in ({'temperature_c':True},{'ph':'7.5'},{'quality':'unknown'},
                {'freshness':'unknown'},{'source':''},{'observed_at':'bad'},
                {'retrieved_at':'2026-10-15T00:00:00Z'},{'dissolved_oxygen_mg_l':float('inf')}):
            item=water_payload();item['water_quality'].update(changes);cases.append(item)
        item=water_payload();item['evaluated_at']='2026-10-15T00:00:00Z';cases.append(item)
        for payload in cases:
            self.assertEqual(canonical(sources._observation(payload)),
                             canonical(old_sources._observation(payload)))
