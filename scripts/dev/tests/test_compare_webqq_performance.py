"""Offline experiment harness guards; no real SDK/QQ or user instance access."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import patch

DEV=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(DEV))
sys.path.insert(0,str(DEV.parents[1]))
from performance_observer import Observer,statistics
import compare_webqq_performance as bench


class ObserverTests(unittest.TestCase):
    def test_p95_is_withheld_for_small_or_missing_groups(self):
        self.assertIsNone(statistics([])['p95'])
        self.assertIsNone(statistics(range(29))['p95'])
        self.assertEqual(statistics(range(1,31))['p95'],29)

    def test_nested_spans_do_not_double_count_exclusive_time(self):
        obs=Observer();obs.active='sample'
        with obs.span('parent'):
            with obs.span('child'):pass
        summary=obs.summary('sample')
        self.assertEqual(summary['parent']['calls'],1)
        self.assertAlmostEqual(summary['parent']['exclusive_ms']+summary['child']['inclusive_ms'],
                               summary['parent']['inclusive_ms'],places=5)
        self.assertNotIn('secret',json.dumps(obs.events))

    def test_wrapping_preserves_result_exceptions_and_restores_alias(self):
        obs=Observer();obs.active='sample'
        def function(value):
            if value<0:raise ValueError('synthetic')
            return value+1
        wrapped=obs.wrap('call',function)
        self.assertEqual(wrapped(2),3)
        with self.assertRaises(ValueError):wrapped(-1)
        self.assertEqual(obs.summary('sample')['call']['calls'],2)
        self.assertFalse(any('synthetic' in str(e) for e in obs.events))

    def test_disabled_observer_records_no_spans(self):
        obs=Observer();obs.active='sample';obs.enabled=False
        with obs.span('unused'):pass
        self.assertEqual(obs.events,[])

    def test_alias_instrumentation_restores_original_objects(self):
        obs=Observer();obs.active='sample'
        module=ModuleType('apps._performance_test_only')
        def original():return 17
        module.first=module.second=original
        with patch.dict(sys.modules,{module.__name__:module}):
            with ExitStack() as stack:
                obs.aliases(stack,original,'alias')
                self.assertIsNot(module.first,original)
                self.assertEqual(module.first(),17);self.assertEqual(module.second(),17)
            self.assertIs(module.first,original);self.assertIs(module.second,original)
        self.assertEqual(obs.summary('sample')['alias']['calls'],2)


class ExperimentTests(unittest.TestCase):
    def test_requested_questions_and_templates_are_not_silently_coerced(self):
        values=bench.conditions('entry')
        self.assertEqual(len(values),6)
        self.assertEqual([v.model_expected for v in values],[True,True,True,False,True,False])
        self.assertTrue(values[4].followup)
        self.assertEqual({v.scenario for v in bench.conditions('core')},{'fresh','partial','stale','low'})

    def test_failed_samples_are_retained_and_not_counted_toward_p95(self):
        rows=[]
        for i in range(30):
            rows.append(dict(suite='core',condition='fresh',channel='web',phase='sample',
                observed=True,success=i!=0,error_code=None if i else 'TEST_FAILED',
                total_ms=i,stages={}))
        value=bench.aggregate(rows)[0]
        self.assertEqual(value['attempted'],30);self.assertEqual(value['successful'],29)
        self.assertEqual(value['failures'],['TEST_FAILED'])
        self.assertIsNone(value['metrics']['total_ms']['p95'])

    def test_cold_warmup_and_observer_probes_are_not_pooled_with_samples(self):
        rows=[dict(suite='core',condition='fresh',channel='web',phase=p,observed=True,
                   success=True,error_code=None,total_ms=1,stages={})
              for p in ('cold','warmup','observer_on','sample')]
        self.assertEqual(bench.aggregate(rows)[0]['successful'],1)

    def test_output_cannot_escape_project_performance_directory(self):
        with self.assertRaises(ValueError):bench.new_output(bench.ROOT/'outputs'/'qq-bot')
        with self.assertRaises(ValueError):bench.new_output(bench.ROOT.parent/'Fishery_Management')

    def test_report_and_csv_keep_failure_codes_without_message_text(self):
        with TemporaryDirectory(dir=bench.ROOT/'outputs'/'test-tmp') as temp:
            directory=Path(temp)
            rows=[dict(sample='fake',suite='entry',condition='q1',scenario='fresh',channel='web',
                phase='sample',observed=True,success=False,error_code='TEST_FAILED',total_ms=1,stages={})]
            bench.write_report(directory,rows,{'network_requests':0})
            report=json.loads((directory/'results.json').read_text('utf8'))
            self.assertFalse(report['success']);self.assertEqual(report['records'][0]['error_code'],'TEST_FAILED')
            self.assertTrue((directory/'samples.csv').exists());self.assertTrue((directory/'stages.csv').exists())

    def test_report_write_failure_is_not_retried_as_a_model_request(self):
        with TemporaryDirectory(dir=bench.ROOT/'outputs'/'test-tmp') as temp:
            with patch.object(Path,'write_text',side_effect=OSError('synthetic')):
                with self.assertRaises(OSError):bench.write_report(Path(temp),[],{})

    def test_measurement_refuses_short_benchmark_without_creating_output(self):
        with patch.object(bench,'new_output',side_effect=AssertionError('no output')):
            with self.assertRaises(SystemExit):bench.main(['--mode','benchmark','--samples','29'])

    def test_fixture_start_failure_is_recorded_without_retry(self):
        with patch.object(bench,'Fixture',side_effect=bench.BotError('SYNTHETIC_FAILURE')) as make:
            row=bench.measure('web',bench.conditions('core')[0],bench.ROOT,Observer(),'sample','sample')
        self.assertFalse(row['success']);self.assertEqual(row['error_code'],'SYNTHETIC_FAILURE')
        self.assertEqual(make.call_count,1)

    def test_synthetic_scenarios_really_have_expected_evidence(self):
        import tempfile
        saved=tempfile.tempdir
        try:
            with TemporaryDirectory(dir=bench.ROOT/'outputs'/'test-tmp') as temp:
                tempfile.tempdir=temp
                for condition in bench.conditions('core'):
                    fixture=bench.Fixture('web',condition,Path(temp),Observer())
                    try:
                        capture=fixture.case.producer.capture_water(bench.DEVICE)
                        quality=capture.analysis.data_quality
                        if condition.scenario=='stale':
                            self.assertEqual((quality.freshness,quality.connectivity),('stale','offline'))
                        elif condition.scenario=='partial':
                            self.assertEqual(quality.quality,'partial')
                        else:self.assertEqual(quality.quality,'valid')
                        if condition.scenario=='low':
                            self.assertTrue(any(f.code.startswith('OXYGEN_') and f.state.value=='HIT'
                                                for f in capture.analysis.findings))
                    finally:fixture.close()
        finally:tempfile.tempdir=saved


if __name__=='__main__':unittest.main()
