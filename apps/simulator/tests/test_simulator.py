"""Deterministic producer and scheduler tests, no Provider or HTTP network."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from apps.simulator.generator import Simulator, WaterQualityGenerator, VisualDetectionGenerator, summarize_visual_frames
from apps.simulator.scenarios import SCENARIOS, at_time
from apps.simulator.__main__ import run, main
from apps.simulator.transport import HttpReporter, ReportError
from apps.monitoring.contracts import validate_batch


class SimulatorTests(unittest.TestCase):
    start = datetime(2026,10,14,tzinfo=timezone.utc)

    def create(self, **kwargs):
        return Simulator(start=self.start, session_id='fixed-session', **kwargs)

    def test_seed_and_timeline_repeat_exactly(self):
        a,b = self.create(),self.create()
        for _ in range(20):self.assertEqual(a.advance(),b.advance())
        c=self.create(seed=1)
        self.assertNotEqual(self.create().advance()['water'],c.advance()['water'])

    def test_all_handwritten_scenarios_validate_each_channel(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                sim=self.create(scenario=scenario)
                for _ in range(20):
                    batch=sim.advance()
                    if batch is not None:
                        validate_batch(batch, now=datetime.fromisoformat(batch['timestamp']), device_ids=('sim-pond-1',))

    def test_offline_timeline_stops_reporting(self):
        sim=self.create(scenario='device_offline')
        self.assertIsNotNone(sim.advance())
        self.assertIsNotNone(sim.advance())
        self.assertIsNone(sim.advance())
        self.assertIsNone(sim.advance())
        sim.switch_scenario('normal')
        batch=sim.advance()
        self.assertEqual(batch['sequence'],4)
        self.assertEqual(batch['window']['start'],(self.start+timedelta(seconds=40)).isoformat())

    def test_water_continuous_degradation_and_window_statistics(self):
        sim=self.create(scenario='low_oxygen')
        values=[sim.advance()['water']['metrics']['dissolved_oxygen_mg_l']['mean'] for _ in range(12)]
        self.assertGreater(values[0],values[-1])
        self.assertTrue(all(abs(a-b)<.5 for a,b in zip(values,values[1:])))
        stat=self.create().advance()['water']['metrics']['temperature_c']
        self.assertLessEqual(stat['min'],stat['mean'])
        self.assertLessEqual(stat['mean'],stat['max'])
        self.assertEqual(stat['valid_samples'],10)

    def test_sampling_period_independent_of_report_and_visual_window(self):
        sim=self.create(sample_period_s=2,frame_period_s=1)
        batch=sim.advance(10)
        self.assertEqual(batch['water']['sample_count'],5)
        self.assertEqual(batch['visual']['frames_processed'],10)
        self.assertEqual(batch['window']['duration_s'],10)
        self.assertIsNone(batch['visual']['length']['average_length_cm'])
        self.assertEqual(batch['visual']['length']['length_sample_count'],0)
        self.assertNotIn('stream_url',batch['visual'])

    def test_visual_sampling_cannot_change_water_random_stream(self):
        a,b=self.create(frame_period_s=.5),self.create(frame_period_s=1)
        for _ in range(6):self.assertEqual(a.advance()['water'],b.advance()['water'])

    def test_invalid_periods_and_targets_no_network(self):
        for value in (True,0,-1,float('nan'),61,'10'):
            with self.assertRaises(ValueError):self.create().advance(value)
        with self.assertRaises(ValueError):self.create(sample_period_s=3).advance(10)
        for url in ('https://127.0.0.1:8766','http://remote.invalid:8766','http://user:pass@localhost:8766','http://localhost:8766/?x=1','http://localhost:8766/else'):
            with self.assertRaises(ValueError):HttpReporter(url,'f'*64)

    def test_scheduler_default_ten_seconds_and_cleanup(self):
        now=[0]
        waits=[]
        sent=[]
        class Reporter:
            closed=False
            def send(self,batch):sent.append(batch);return {'status':'accepted'}
            def close(self):self.closed=True
        reporter=Reporter()
        def sleep(delay):waits.append(delay);now[0]+=delay
        run(self.create(),reporter,windows=3,monotonic=lambda:now[0],sleep=sleep,emit=lambda _:None)
        self.assertEqual(waits,[10,10,10])
        self.assertEqual(len(sent),3)
        self.assertEqual([b['sequence'] for b in sent],[0,1,2])
        self.assertTrue(reporter.closed)

    def test_failure_or_stop_never_retries_and_closes(self):
        for error in (ReportError('REPORT_TRANSPORT_ERROR'),KeyboardInterrupt()):
            class Reporter:
                calls=0
                closed=False
                def send(self,_):self.calls+=1;raise error
                def close(self):self.closed=True
            r=Reporter()
            with self.assertRaises(type(error)):
                run(self.create(),r,windows=3,monotonic=lambda:0,sleep=lambda _:None,emit=lambda _:None)
            self.assertEqual(r.calls,1)
            self.assertTrue(r.closed)

    def test_dry_run_never_reads_token_or_constructs_transport(self):
        import os
        original_get=os.environ.get
        def guarded(key,*args):
            if key=='FISHERY_SIM_INGEST_TOKEN':raise AssertionError('no credential')
            return original_get(key,*args)
        with patch('apps.simulator.__main__.HttpReporter',side_effect=AssertionError('no transport')),patch('apps.simulator.__main__.os.environ.get',side_effect=guarded),patch('builtins.print'):
            self.assertEqual(main(['--dry-run','--windows','2']),0)

    def test_transport_bounds_response_closes_and_safe_errors(self):
        reporter=HttpReporter('http://127.0.0.1:8766','f'*64)
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value=response
        response.read.return_value=b'{"status":"accepted"}'
        with patch.object(reporter._opener,'open',return_value=response) as send:
            self.assertEqual(reporter.send(self.create().advance())['status'],'accepted')
            self.assertEqual(send.call_count,1)
        response.__exit__.assert_called_once()
        response.read.return_value=b'x'*2049
        with patch.object(reporter._opener,'open',return_value=response):
            with self.assertRaisesRegex(ReportError,'REPORT_RESPONSE_INVALID'):reporter.send(self.create().advance())
        reporter.close()
        self.assertEqual(reporter._token,'')

    def test_handwritten_calibration_and_unknown_behavior_are_explicit(self):
        from apps.simulator.scenarios import Phase
        with patch.dict(SCENARIOS, {'custom-test': (Phase(0,calibrated=True,unknown_behavior=1,feeding=0,reduced_activity=0),)}):
            batch=self.create(scenario='custom-test').advance()
        self.assertEqual(batch['visual']['behavior_ratios']['unknown'],1)
        length=batch['visual']['length']
        self.assertEqual(length['calibration'],'simulated')
        self.assertGreater(length['length_sample_count'],0)
        self.assertLessEqual(length['valid_frame_count'],20)
        self.assertIsNotNone(length['average_length_cm'])
        validate_batch(batch,now=datetime.fromisoformat(batch['timestamp']),device_ids=('sim-pond-1',))

    def test_exact_water_means_filter_quality_at_each_sample(self):
        def state_at(t):
            state=at_time(SCENARIOS['normal'],t)
            state.update(temperature_c=10+t,ph=5+t/10,dissolved_oxygen_mg_l=1+t/2)
            if 4 <= t <= 6:state['missing_metric']='temperature_c'
            if 7 <= t <= 9:state['invalid_metric']='temperature_c'
            return state
        generator=WaterQualityGenerator(42,1)
        with patch.object(generator.random,'uniform',return_value=0):
            result=generator.generate(0,10,state_at(10),state_at)
        temperature=result['metrics']['temperature_c']
        self.assertEqual(temperature,dict(unit='°C',mean=14,min=11,max=20,latest=20,valid_samples=4,invalid_samples=3))
        self.assertEqual(result['metrics']['ph']['mean'],5.55)
        self.assertEqual(result['metrics']['dissolved_oxygen_mg_l']['mean'],3.75)
        # Invalid end state cannot erase earlier valid samples.
        state_at_end=lambda t:dict(state_at(1),invalid_metric='temperature_c' if t==10 else None)
        with patch.object(generator.random,'uniform',return_value=0):
            last=generator.generate(0,10,state_at_end(10),state_at_end)['metrics']['temperature_c']
        self.assertEqual((last['valid_samples'],last['invalid_samples'],last['mean']),(9,1,11))

    def test_water_missing_and_nonfinite_values_never_become_zero(self):
        for metric_value,invalid_count in ((None,0),(float('nan'),10)):
            state=at_time(SCENARIOS['normal'],0)
            state['ph']=metric_value
            result=WaterQualityGenerator(42,1).generate(0,10,state,lambda _:state)['metrics']['ph']
            self.assertEqual(result['valid_samples'],0)
            self.assertEqual(result['invalid_samples'],invalid_count)
            for key in ('mean','min','max','latest'):self.assertIsNone(result[key])

    def test_weighted_length_zero_fish_invalid_frames_and_independent_signals(self):
        frames=[dict(visible_fish_count=2,lengths_cm=[10,10],anomalies=('suspected_lesion','surface_anomaly'),behavior='feeding'),
                dict(visible_fish_count=8,lengths_cm=[20]*6,anomalies=('suspected_lesion',),behavior='feeding_anomaly'),
                dict(visible_fish_count=0,lengths_cm=[],anomalies=(),behavior='unknown'),None]
        result=summarize_visual_frames(frames)
        self.assertEqual(result['length']['average_length_cm'],17.5)
        self.assertEqual(result['length']['length_sample_count'],8)
        self.assertEqual(result['length']['valid_frame_count'],2)
        self.assertEqual(result['frames_processed'],4)
        self.assertEqual(result['valid_frames'],3)
        self.assertAlmostEqual(result['visible_fish_count'],10/3)
        self.assertEqual(result['anomaly_counts'],dict(suspected_lesion=2,surface_anomaly=1,suspected_dead=0))
        self.assertEqual(result['behavior_ratios']['feeding'],1/3)
        self.assertEqual(result['behavior_ratios']['unknown'],1/3)
        for frames in ([None,None],[dict(visible_fish_count=0,lengths_cm=[],anomalies=(),behavior='unknown')]):
            summary=summarize_visual_frames(frames)
            self.assertIsNone(summary['length']['average_length_cm'])
            self.assertEqual(summary['length']['length_sample_count'],0)
            self.assertEqual(summary['visible_fish_count'],None if frames[0] is None else 0)

    def test_visual_validity_and_calibration_are_per_frame(self):
        def state_at(t):
            return dict(at_time(SCENARIOS['normal'],t),visual_online=t>2,calibrated=t==3)
        generator=VisualDetectionGenerator(42,1)
        with patch.object(generator.random,'randint',side_effect=[2,1,0]):
            result=generator.generate(0,4,state_at(4),state_at)
        self.assertEqual(result['valid_frames'],2)
        self.assertEqual(result['visible_fish_count'],1)
        self.assertEqual(result['length']['length_sample_count'],1)
        self.assertEqual(result['length']['valid_frame_count'],1)

    def test_scheduler_stall_skips_windows_without_catchup_burst(self):
        now=[0];sent=[];waits=[]
        class Reporter:
            closed=False
            def send(self,batch):
                sent.append((now[0],batch))
                if len(sent)==1:now[0]+=95
                return {'status':'accepted'}
            def close(self):self.closed=True
        def sleep(delay):waits.append(delay);now[0]+=delay
        sim=self.create();r=Reporter()
        run(sim,r,windows=3,monotonic=lambda:now[0],sleep=sleep,emit=lambda _:None,
            switch_to='water_only',switch_after=50)
        self.assertEqual([t for t,_ in sent],[10,105,110])
        self.assertEqual(waits,[10,5])
        self.assertEqual([b['sequence'] for _,b in sent],[0,9,10])
        self.assertEqual(sent[1][1]['window']['start'],(self.start+timedelta(seconds=90)).isoformat())
        self.assertEqual(sent[1][1]['window']['end'],(self.start+timedelta(seconds=100)).isoformat())
        self.assertIsNone(sent[1][1]['visual'])
        self.assertEqual(sent[1][1]['water']['sample_count'],10)
        self.assertTrue(r.closed)


if __name__=='__main__':unittest.main()
