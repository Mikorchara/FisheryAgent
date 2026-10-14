"""Offline unified data, ingestion, ordering, lifecycle and future-reader contracts."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from apps.management_web.app import create_app
from apps.monitoring.contracts import IngestionError, strict_json, validate_batch
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from fishery_ai.domain import DiagnosisService


class PipelineTests(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("network disabled"))
            guard.start()
            self.addCleanup(guard.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)/"monitoring.sqlite3"
        self.start = datetime(2026, 10, 14, tzinfo=timezone.utc)
        self.now = self.start+timedelta(seconds=10)
        self.repo = MonitoringRepository(self.path, history_limit=3, batch_limit=6, event_limit=20)
        self.service = MonitoringService(self.repo, clock=lambda: self.now)
        self.sim = Simulator(start=self.start, session_id="test-session")
        self.batch = self.sim.advance()
        self.token = "f"*64  # Fictional local-development access token, never a Provider secret.
        self.client = create_app(data_service=self.service, ingestion_token=self.token).test_client()

    def post(self, batch, **kwargs):
        return self.client.post('/api/ingestion/batches', json=batch,
            headers={"X-Simulator-Token": self.token}, **kwargs)

    def ingest_next(self):
        batch = self.sim.advance()
        self.now = self.start+timedelta(seconds=self.sim.elapsed_s)
        self.service.ingest(batch)
        return batch

    def test_empty_is_no_data_not_demo(self):
        d = self.client.get('/api/bootstrap').get_json()
        self.assertEqual(d['data_mode'], 'simulator')
        self.assertEqual(d['monitoring']['quality'], 'missing')
        self.assertTrue(all(m['value'] is None for m in d['monitoring']['metrics']))
        self.assertIsNone(d['cameras'][0]['summary'])
        self.assertEqual(d['events'], [])
        self.assertIsNone(self.service.bind('sim-pond-1').water_reader.query())

    def test_weighted_frame_statistics_survive_ingestion_storage_and_web(self):
        from apps.simulator.generator import summarize_visual_frames
        frames=[dict(visible_fish_count=2,lengths_cm=[10]*2,anomalies=(),behavior='normal_activity'),
                dict(visible_fish_count=8,lengths_cm=[20]*6,anomalies=(),behavior='normal_activity'),
                dict(visible_fish_count=0,lengths_cm=[],anomalies=(),behavior='unknown'),None]
        self.batch['visual']=summarize_visual_frames(frames)
        self.assertEqual(self.post(self.batch).status_code,200)
        summary=self.client.get('/api/bootstrap').get_json()['cameras'][0]['summary']
        self.assertEqual(summary,self.batch['visual'])
        self.assertEqual(summary['length']['average_length_cm'],17.5)
        self.assertEqual(summary['length']['length_sample_count'],8)
        self.assertEqual(summary['length']['valid_frame_count'],2)
        self.assertAlmostEqual(summary['visible_fish_count'],10/3)
        self.assertEqual(self.repo.history('sim-pond-1','visual')[0]['payload']['data'],summary)

    def test_additive_frame_metadata_validated_and_legacy_v1_accepted(self):
        from copy import deepcopy
        from apps.monitoring.contracts import validate_batch
        for change in (
            lambda b:b['visual'].update(valid_frames=True),
            lambda b:b['visual'].update(valid_frames=21),
            lambda b:b['visual'].update(valid_frames=0),
            lambda b:b['visual']['length'].update(valid_frame_count=1),
            lambda b:b['visual']['length'].update(valid_frame_count=True),
            lambda b:b['visual'].update(unrecognized_stat=1),
        ):
            b=deepcopy(self.batch);change(b)
            with self.assertRaises(IngestionError):validate_batch(b,now=self.now,device_ids=('sim-pond-1',))
        legacy=deepcopy(self.batch)
        del legacy['visual']['valid_frames'];del legacy['visual']['length']['valid_frame_count']
        self.assertEqual(self.post(legacy).status_code,200)
        self.assertEqual(self.service.cameras()[0]['summary'],legacy['visual'])

    def test_invalid_visual_frames_are_missing_not_normal_or_signal_recovery(self):
        from apps.simulator.generator import summarize_visual_frames
        self.batch['visual']['anomaly_counts']['suspected_lesion']=1
        self.service.ingest(self.batch)
        b=self.sim.advance();self.now=datetime.fromisoformat(b['timestamp'])
        b['visual']=summarize_visual_frames([None,None])
        self.service.ingest(b)
        camera=self.service.cameras()[0]
        self.assertEqual(camera['signal_status'],'no_valid_frames')
        self.assertIsNone(camera['summary']['visible_fish_count'])
        self.assertIsNone(camera['summary']['length']['average_length_cm'])
        event=next(e for e in self.service.events() if e['code']=='SUSPECTED_LESION')
        self.assertEqual(event['status'],'pending')

    def test_empty_device_registry_and_invalid_time_policy_fail_closed(self):
        empty=MonitoringService(self.repo,device_names={},clock=lambda:self.now)
        data=create_app(data_service=empty).test_client().get('/api/bootstrap').get_json()
        self.assertEqual(data['devices'],[])
        self.assertIsNone(data['monitoring'])
        self.assertEqual(data['connections'][0]['status'],'never_received')
        with self.assertRaises(IngestionError):empty.ingest(self.batch)
        for stale,offline in ((True,90),(30,float('inf')),(30,20),(0,90)):
            with self.assertRaises(ValueError):MonitoringService(self.repo,stale_after_s=stale,offline_after_s=offline)

    def test_complete_batch_pages_and_canonical_reader_share_source(self):
        self.assertEqual(self.post(self.batch).get_json()['updated_channels'], ['water', 'visual'])
        d = self.client.get('/api/bootstrap').get_json()
        water, visual = d['monitoring'], d['cameras'][0]
        self.assertEqual(water['batch_id'], visual['batch_id'])
        self.assertEqual(water['window'], visual['window'])
        self.assertEqual(water['aggregation'], 'window_mean')
        self.assertEqual(water['metrics'][0]['valid_samples'], 10)
        view = self.service.bind('sim-pond-1').water_reader.query()
        self.assertEqual(view.reading.dissolved_oxygen_mg_l, water['metrics'][2]['value'])
        self.assertEqual(view.reading.observed_at.isoformat(), water['observed_at'])
        self.assertEqual(view.reading.retrieved_at.isoformat(), water['received_at'])
        self.assertEqual(water['source_kind'], visual['source_kind'])
        self.assertIsNone(visual['stream_url'])

    def test_query_time_freshness_and_offline_are_read_only(self):
        self.service.ingest(self.batch)
        original = self.repo.read('sim-pond-1', 'water')
        self.now += timedelta(seconds=31)
        self.assertEqual(self.service.snapshot('sim-pond-1').freshness, 'stale')
        self.assertEqual(self.service.snapshot('sim-pond-1').connectivity, 'online')
        self.now += timedelta(seconds=60)
        self.assertEqual(self.service.snapshot('sim-pond-1').connectivity, 'offline')
        self.assertEqual(self.service.cameras()[0]['status'], 'offline')
        self.assertEqual(self.service.bind('sim-pond-1').water_reader.query().reading.freshness.value, 'stale')
        self.assertEqual(self.repo.read('sim-pond-1', 'water'), original)

    def test_duplicate_idempotency_and_conflict(self):
        self.assertEqual(self.post(self.batch).status_code, 200)
        self.assertEqual(self.post(self.batch).get_json()['status'], 'duplicate')
        self.assertEqual(len(self.repo.history('sim-pond-1', 'water')), 1)
        changed = deepcopy(self.batch)
        changed['visual']['visible_fish_count'] += 1
        self.assertEqual(self.post(changed).status_code, 409)
        self.assertEqual(self.repo.read('sim-pond-1', 'water')['batch_id'], self.batch['batch_id'])

    def test_late_and_out_of_order_history_never_rolls_back_current_or_events(self):
        later = self.sim.advance()
        self.now += timedelta(seconds=10)
        self.service.ingest(later)
        self.assertEqual(self.service.ingest(self.batch)['status'], 'out_of_order')
        self.assertEqual(self.repo.read('sim-pond-1', 'water')['batch_id'], later['batch_id'])
        self.assertEqual([r['batch_id'] for r in self.repo.history('sim-pond-1', 'water')], [self.batch['batch_id'], later['batch_id']])
        self.assertEqual(self.service.events(), [])
        late_service = MonitoringService(self.repo, clock=lambda: self.now+timedelta(seconds=400))
        with self.assertRaisesRegex(IngestionError, 'OBSERVATION_TIME_REJECTED'):
            late_service.ingest(self.sim.advance())

    def test_equal_timestamp_new_batch_rejected_atomically(self):
        self.service.ingest(self.batch)
        changed = deepcopy(self.batch)
        changed.update(batch_id='another-batch', session_id='another-session')
        self.assertEqual(self.post(changed).get_json()['error_code'], 'OBSERVATION_CONFLICT')
        self.assertEqual(len(self.repo.history('sim-pond-1', 'water')), 1)

    def test_channels_independent_and_missing_never_filled(self):
        self.batch['water'] = None
        self.service.ingest(self.batch)
        self.assertIsNone(self.service.bind('sim-pond-1').water_reader.query())
        self.assertIsNotNone(self.service.cameras()[0]['summary'])
        later = self.sim.advance()
        later['visual'] = None
        self.now += timedelta(seconds=10)
        self.service.ingest(later)
        self.now += timedelta(seconds=25)
        self.assertEqual(self.service.snapshot('sim-pond-1').freshness, 'fresh')
        self.assertEqual(self.service.cameras()[0]['freshness'], 'stale')

    def test_physical_invalid_rejected_not_turned_into_good_reading(self):
        for value in (True, '7', float('nan'), -1, 101):
            with self.subTest(value=value):
                invalid = deepcopy(self.batch)
                invalid['water']['metrics']['dissolved_oxygen_mg_l']['mean'] = value
                self.assertEqual(self.post(invalid).status_code, 400)
        self.assertIsNone(self.repo.read('sim-pond-1', 'water'))

    def test_schema_and_statistics_fail_closed(self):
        mutations = [lambda b: b.update(schema_version=True), lambda b: b.update(sequence=True),
            lambda b: b.update(source_kind='sensor'), lambda b: b.update(device_id='../../private'),
            lambda b: b.update(device_id='other-device'), lambda b: b.update(timestamp='not-time'),
            lambda b: b['window'].update(duration_s=20), lambda b: b.update(water=None, visual=None),
            lambda b: b['water']['metrics']['ph'].update(unit='mg/L'),
            lambda b: b['water']['metrics']['ph'].update(valid_samples=11),
            lambda b: b['water']['metrics']['ph'].update(min=8),
            lambda b: b['visual']['behavior_ratios'].update(unknown=.9),
            lambda b: b['visual']['anomaly_counts'].update(suspected_lesion=21),
            lambda b: b['visual']['length'].update(average_length_cm=20, length_sample_count=1),
            lambda b: b['visual'].update(model_version='../model')]
        for mutate in mutations:
            b = deepcopy(self.batch)
            mutate(b)
            with self.subTest(batch=b['batch_id']):
                self.assertIn(self.post(b).status_code, (400, 403))
        self.assertEqual(self.repo.history('sim-pond-1', 'water'), [])

    def test_aware_timestamp_future_and_duplicate_json_fields(self):
        for text in ('2026-10-14T00:00:10', '2026-10-14T00:00:11+00:00'):
            b = deepcopy(self.batch)
            b['timestamp'] = b['window']['end'] = text
            self.assertEqual(self.post(b).status_code, 400)
        with self.assertRaises(IngestionError):
            strict_json('{"schema_version":1,"schema_version":1}')
        response = self.client.post('/api/ingestion/batches', data='['*1000,
            content_type='application/json', headers={'X-Simulator-Token': self.token})
        self.assertEqual(response.status_code, 400)

    def test_local_auth_origin_size_and_disabled_gate(self):
        self.assertEqual(create_app().test_client().post('/api/ingestion/batches').get_json()['error_code'], 'INGESTION_DISABLED')
        self.assertEqual(self.client.post('/api/ingestion/batches', json=self.batch).status_code, 403)
        self.assertEqual(self.post(self.batch, environ_overrides={'REMOTE_ADDR': '10.0.0.1'}).status_code, 403)
        self.assertEqual(self.client.post('/api/ingestion/batches', json=self.batch,
            headers={'X-Simulator-Token': self.token, 'Origin':'http://localhost'}).status_code, 403)
        self.assertEqual(self.client.post('/api/ingestion/batches', data='x'*9000,
            headers={'X-Simulator-Token': self.token}).status_code, 413)
        self.assertEqual(self.client.post('/api/ingestion/batches', json=self.batch,
            headers={'X-Simulator-Token': self.token}, base_url='http://evil.invalid').status_code, 403)
        with self.assertRaisesRegex(ValueError, 'INVALID_INGESTION_CONFIG'):
            create_app(data_service=self.service, ingestion_token='bad')
        self.assertEqual(self.repo.events(), [])

    def test_partial_and_invalid_keep_sample_proof_and_domain_semantics(self):
        for scenario, quality in (('partial','partial'), ('invalid','invalid')):
            sim = Simulator(start=self.start, session_id='status-'+scenario, scenario=scenario)
            b = sim.advance()
            self.service.ingest(b)
            snap = self.service.snapshot('sim-pond-1')
            self.assertEqual(snap.quality, quality)
            self.assertIn('SENSOR_INVALID' if scenario=='invalid' else 'SENSOR_PARTIAL', [f['code'] for f in snap.findings])
            if scenario=='invalid':
                self.assertEqual(snap.metrics[1].invalid_samples, 10)
                self.assertEqual(snap.metrics[1].quality, 'invalid')
                self.assertIsNone(snap.metrics[1].value)
            self.start += timedelta(seconds=10)
            self.now += timedelta(seconds=10)
        b = Simulator(start=self.now, session_id='all-invalid').advance()
        for stat in b['water']['metrics'].values():
            stat.update(mean=None, min=None, max=None, latest=None, valid_samples=0, invalid_samples=10)
        self.now = datetime.fromisoformat(b['timestamp'])
        self.service.ingest(b)
        self.assertEqual(self.service.snapshot('sim-pond-1').quality, 'invalid')
        self.assertIsNotNone(self.service.bind('sim-pond-1').water_reader.query())

    def test_event_episode_dedup_recovery_and_received_batch_links(self):
        sim = Simulator(start=self.start-timedelta(seconds=120), scenario='combined_anomaly', session_id='events')
        sim.advance(60)
        b = sim.advance(60)
        self.now = datetime.fromisoformat(b['timestamp'])
        self.service.ingest(b)
        first = self.service.events()
        self.assertTrue(first)
        for _ in range(3):
            b = sim.advance()
            self.now = datetime.fromisoformat(b['timestamp'])
            self.service.ingest(b)
        events = self.service.events()
        # Stable high anomalies; counts may vary but required persistent signals remain one episode.
        code_ids = {e['code']:e['id'] for e in first}
        for event in events:
            if event['code'] in code_ids:
                self.assertEqual(event['id'], code_ids[event['code']])
            self.assertEqual(event['source_kind'], 'simulator')
            self.assertTrue(event['batch_id'])
            self.assertTrue(event['received_at'])
        sim.switch_scenario('normal')
        b = sim.advance()
        self.now = datetime.fromisoformat(b['timestamp'])
        self.service.ingest(b)
        self.assertTrue(all(e['status']=='closed' for e in self.service.events()))

    def test_history_bounds_and_restart_preserve_current(self):
        self.service.ingest(self.batch)
        for _ in range(8):self.ingest_next()
        self.assertEqual(len(self.repo.history('sim-pond-1', 'water')), 3)
        with self.repo.connection() as db:
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],6)
        reopened = MonitoringService(MonitoringRepository(self.path), clock=lambda:self.now)
        self.assertEqual(reopened.snapshot('sim-pond-1').batch_id, self.service.snapshot('sim-pond-1').batch_id)
        restarted = Simulator(start=self.now, session_id='restarted')
        b = restarted.advance()
        self.now += timedelta(seconds=10)
        self.assertEqual(reopened.ingest(b)['status'], 'accepted')

    def test_device_context_frozen_not_changed_by_web_query(self):
        service = MonitoringService(self.repo, device_names={'sim-pond-1':'A','sim-pond-2':'B'}, clock=lambda:self.now)
        service.ingest(self.batch)
        context = service.bind('sim-pond-1')
        web = create_app(data_service=service).test_client()
        web.get('/api/bootstrap?device=sim-pond-2')
        self.assertEqual(context.device_id, 'sim-pond-1')
        self.assertIsNotNone(context.water_reader.query())
        self.assertIsNone(service.bind('sim-pond-2').water_reader.query())

    def test_findings_from_domain_and_read_response_mutation_isolated(self):
        self.service.ingest(self.batch)
        view = self.service.bind('sim-pond-1').water_reader.query()
        snapshot = self.service.snapshot('sim-pond-1')
        self.assertEqual(snapshot.findings, tuple(asdict(f) for f in DiagnosisService().diagnose(view.reading)))
        self.assertEqual(snapshot.rule_version, DiagnosisService.RULE_VERSION)
        snapshot.window['end'] = 'tampered'
        self.assertNotEqual(self.service.snapshot('sim-pond-1').window['end'], 'tampered')
        payload = self.client.get('/api/bootstrap').get_json()
        self.assertNotIn(self.token, json.dumps(payload))
        self.assertNotIn('Authorization',json.dumps(payload))
        self.assertEqual(self.client.post('/api/ai/messages',json={}).status_code,503)

    def test_history_api_validation_and_channel_statistics(self):
        self.service.ingest(self.batch)
        for channel in ('water', 'visual'):
            items = self.client.get('/api/monitoring/history?channel='+channel).get_json()['items']
            self.assertEqual(len(items),1)
            self.assertEqual(items[0]['source_kind'],'simulator')
            self.assertEqual(items[0]['batch_id'],self.batch['batch_id'])
        for query in ('channel=other','limit=bad','limit=0','limit=4','device=../private'):
            self.assertEqual(self.client.get('/api/monitoring/history?'+query).status_code,400)
        self.assertEqual(create_app().test_client().get('/api/monitoring/history').status_code,503)

    def test_concurrent_duplicate_and_failed_batch_transaction_rollback(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.service.ingest(self.batch),range(2)))
        self.assertEqual(sorted(r['status'] for r in results),['accepted','duplicate'])
        visual_only=deepcopy(self.batch)
        visual_only.update(batch_id='visual-only-new',session_id='new-session')
        visual_only['timestamp']=visual_only['window']['end']=(self.now+timedelta(seconds=10)).isoformat()
        visual_only['window']['start']=self.now.isoformat()
        visual_only['water']=None
        self.now+=timedelta(seconds=10)
        self.service.ingest(visual_only)
        # Water updates first, then the visual timestamp conflicts: rollback both changes.
        conflict=deepcopy(visual_only)
        conflict.update(batch_id='atomic-conflict',session_id='another-session')
        conflict['water']=self.batch['water']
        before=self.repo.read('sim-pond-1','visual')
        before_water=self.repo.read('sim-pond-1','water')
        with self.assertRaises(IngestionError):self.service.ingest(conflict)
        self.assertEqual(self.repo.read('sim-pond-1','visual'),before)
        self.assertEqual(self.repo.read('sim-pond-1','water'),before_water)
        self.assertEqual(len(self.repo.history('sim-pond-1','visual')),2)
        self.assertEqual(len(self.repo.history('sim-pond-1','water')),1)

    def test_delayed_report_is_online_but_stale_and_original_preserved(self):
        self.now+=timedelta(seconds=60)
        self.service.ingest(self.batch)
        snapshot=self.service.snapshot('sim-pond-1')
        self.assertEqual(snapshot.connectivity,'online')
        self.assertEqual(snapshot.freshness,'stale')
        self.assertNotEqual(snapshot.received_at,snapshot.observed_at)
        self.assertIn('SENSOR_STALE',[f['code'] for f in snapshot.findings])

    def test_out_of_order_contact_is_online_without_refreshing_observation(self):
        latest=self.sim.advance()
        self.now+=timedelta(seconds=10)
        self.service.ingest(latest)
        original_received=self.repo.read('sim-pond-1','water')['received_at']
        self.now+=timedelta(seconds=100)
        self.assertEqual(self.service.ingest(self.batch)['status'],'out_of_order')
        snapshot=self.service.snapshot('sim-pond-1')
        self.assertEqual(snapshot.connectivity,'online')
        self.assertEqual(snapshot.freshness,'stale')
        self.assertEqual(snapshot.received_at,original_received)
        self.assertEqual(snapshot.last_reported_at,self.now.isoformat())
        self.assertEqual(snapshot.batch_id,latest['batch_id'])

    def test_unknown_storage_version_rejected_without_rewriting_data(self):
        import sqlite3
        from contextlib import closing
        path=self.path.parent/'unknown.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA user_version=99')
            db.execute('CREATE TABLE original (text_value TEXT)')
            db.execute("INSERT INTO original VALUES('keep')")
            db.commit()
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_MONITORING_STORAGE_SCHEMA'):
            MonitoringRepository(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)
            self.assertEqual(db.execute('SELECT * FROM original').fetchone()[0],'keep')


if __name__ == '__main__':unittest.main()
