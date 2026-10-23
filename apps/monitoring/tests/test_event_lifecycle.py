"""EVT-1: isolated observations, transactional recovery and restart compatibility."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator, summarize_visual_frames


class VisualLifecycleTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.getaddrinfo'):
            guard = patch(target, side_effect=AssertionError('EVT-1 offline test'))
            guard.start()
            self.addCleanup(guard.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'monitoring.sqlite3'
        self.start = self.now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        self.sim = Simulator(start=self.start, seed=42, session_id='evt1')
        self.repo = MonitoringRepository(self.path)
        self.service = MonitoringService(self.repo, clock=lambda: self.now,
            device_names={'sim-pond-1': '模拟池1', 'sim-pond-2': '模拟池2'})

    def batch(self, *codes, duration=10, session=None, device='sim-pond-1'):
        batch = self.sim.advance(duration)
        self.now = datetime.fromisoformat(batch['timestamp'])
        batch['visual']['anomaly_counts'] = dict.fromkeys(batch['visual']['anomaly_counts'], 0)
        batch['visual']['behavior_ratios'] = dict(normal_activity=1, reduced_activity=0,
            feeding=0, feeding_anomaly=0, unknown=0)
        for code in codes:
            batch['visual']['anomaly_counts'][code] = 1
        if session:
            batch['session_id'] = session
            batch['batch_id'] = session + '-' + str(batch['sequence'])
        if device != batch['device_id']:
            batch['device_id'] = device
            batch['batch_id'] = device + '-' + batch['batch_id']
        return batch

    def ingest(self, *codes, **kwargs):
        batch = self.batch(*codes, **kwargs)
        self.service.ingest(batch)
        return batch

    def events(self, code='SUSPECTED_LESION', device='sim-pond-1', projected=False):
        source = self.service if projected else self.repo
        return [e for e in source.events() if e['code'] == code and e['device_id'] == device]

    def event(self, **kwargs):
        return self.events(**kwargs)[0]

    def count(self):
        return self.event()['visual_recovery']['clear_count']

    def test_hit_and_three_continuous_clear_windows(self):
        first = self.ingest('suspected_lesion')
        original = self.event()
        self.ingest('suspected_lesion')
        self.assertEqual(self.event()['id'], original['id'])
        for count in (1, 2):
            self.ingest()
            self.assertEqual(self.count(), count)
            self.assertEqual(self.event()['lifecycle_state'], 'ACTIVE')
            self.assertEqual(self.event(projected=True)['lifecycle_state'], 'ACTIVE')
            self.assertNotIn('resolved_at', self.event())
        final = self.ingest()
        resolved = self.event()
        self.assertEqual(resolved['lifecycle_state'], 'RESOLVED')
        self.assertEqual(resolved['resolved_at'], final['timestamp'])
        self.assertEqual(resolved['resolution_batch_id'], final['batch_id'])
        self.assertEqual(resolved['batch_id'], first['batch_id'])
        self.ingest('suspected_lesion')
        self.assertEqual(len(self.events()), 2)
        self.assertNotEqual(self.event()['id'], original['id'])

    def test_hit_cancels_recovery_and_severity_can_change(self):
        self.ingest('suspected_lesion')
        original = self.event()['id']
        self.ingest(); self.ingest()
        self.ingest('suspected_lesion')
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.event()['id'], original)
        self.ingest()
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.event(projected=True)['lifecycle_state'], 'ACTIVE')
        original_assess = self.service._assess
        def critical(*args):
            analysis = original_assess(*args)
            return replace(analysis, findings=tuple(replace(f, severity='critical')
                if f.code == 'SUSPECTED_LESION' and f.state.value == 'HIT' else f for f in analysis.findings))
        with patch.object(self.service, '_assess', side_effect=critical):
            self.ingest('suspected_lesion')
        self.assertEqual(self.event()['id'], original)
        self.assertEqual(self.event()['severity'], 'critical')

    def test_missing_invalid_partial_stale_windows_reset_recovery(self):
        for kind in ('missing', 'invalid', 'partial', 'stale'):
            with self.subTest(kind=kind):
                self.ingest('suspected_lesion'); self.ingest(); self.ingest()
                batch = self.batch()
                if kind == 'missing':
                    batch['visual'] = None
                elif kind == 'invalid':
                    batch['visual'] = summarize_visual_frames([None, None])
                elif kind == 'partial':
                    batch['visual']['valid_frames'] = 10
                else:
                    self.now += timedelta(seconds=31)
                self.service.ingest(batch)
                event = self.event()
                self.assertEqual(event['lifecycle_state'], 'INDETERMINATE')
                self.assertEqual(self.count(), 0)
                self.assertNotIn('resolved_at', event)
                self.ingest()
                self.assertEqual(self.count(), 1)
                self.assertEqual(len(self.events()), 1)

    def test_gap_overlap_sequence_gap_and_new_session_reset_without_duplicate(self):
        for kind in ('gap', 'overlap', 'sequence', 'session'):
            with self.subTest(kind=kind):
                self.ingest('suspected_lesion'); self.ingest(); self.ingest()
                original = self.event()['id']
                if kind == 'gap':
                    self.sim.advance(10)
                batch = self.batch(session='new-session' if kind == 'session' else None)
                if kind == 'overlap':
                    batch['window']['start'] = (datetime.fromisoformat(batch['window']['start']) - timedelta(seconds=1)).isoformat()
                    batch['window']['duration_s'] = 11
                elif kind == 'sequence':
                    batch['sequence'] += 100
                self.service.ingest(batch)
                self.assertEqual(self.count(), 1)
                self.assertEqual(self.event()['id'], original)
                self.assertEqual(self.event()['visual_recovery']['continuity'], 'interrupted')
                self.assertNotIn('resolved_at', self.event())
                self.ingest('suspected_lesion', session='hit-session')
                self.assertEqual(self.event()['id'], original)
                self.assertEqual(self.count(), 0)

    def test_restart_preserves_two_clear_windows_but_offline_gap_cannot_accumulate(self):
        self.ingest('suspected_lesion'); self.ingest(); self.ingest()
        original = self.event()['id']
        self.repo = MonitoringRepository(self.path, require_existing=True)
        self.service = MonitoringService(self.repo, clock=lambda: self.now)
        self.assertEqual(self.count(), 2)
        self.ingest()
        self.assertEqual(self.event()['lifecycle_state'], 'RESOLVED')
        self.ingest('suspected_lesion'); self.ingest(); self.ingest()
        self.now += timedelta(seconds=91)
        stored = deepcopy(self.repo.events())
        unknown = self.event(projected=True)
        self.assertEqual(unknown['lifecycle_state'], 'INDETERMINATE')
        self.assertEqual(unknown['visual_recovery']['clear_count'], 0)
        self.assertEqual(self.repo.events(), stored)
        self.sim.advance(60); self.sim.advance(30)
        self.ingest()
        self.assertEqual(self.count(), 1)
        self.assertNotEqual(self.event()['id'], original)

    def test_previous_evidence_expired_even_when_current_window_is_fresh(self):
        self.ingest('suspected_lesion'); self.ingest(); self.ingest()
        batch = self.batch()
        self.now += timedelta(seconds=30)
        self.service.ingest(batch)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.event()['lifecycle_state'], 'ACTIVE')

    def test_duplicate_queries_and_out_of_order_do_not_advance_or_reset_count(self):
        hit = self.ingest('suspected_lesion')
        clear = self.ingest()
        for _ in range(3):
            self.service.events()
            self.service.ingest(clear)
        self.assertEqual(self.count(), 1)
        older = deepcopy(hit)
        older.update(batch_id='old-distinct', sequence=100)
        self.assertEqual(self.service.ingest(older)['status'], 'out_of_order')
        self.assertEqual(self.count(), 1)

    def test_devices_codes_and_water_recovery_remain_independent(self):
        self.ingest('suspected_lesion', 'surface_anomaly')
        self.ingest('surface_anomaly')
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.event(code='SURFACE_ANOMALY')['visual_recovery']['clear_count'], 0)
        self.ingest('suspected_lesion', device='sim-pond-2')
        self.assertEqual(self.event(device='sim-pond-2')['visual_recovery']['clear_count'], 0)
        batch = self.batch()
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
        self.service.ingest(batch)
        self.assertEqual(self.event(code='OXYGEN_CRITICAL_LOW')['lifecycle_state'], 'ACTIVE')
        self.ingest()
        self.assertEqual(self.event(code='OXYGEN_CRITICAL_LOW')['lifecycle_state'], 'RESOLVED')

    def test_active_events_survive_bounded_history_and_restart(self):
        self.repo = MonitoringRepository(self.path, event_limit=2)
        self.service = MonitoringService(self.repo, clock=lambda: self.now)
        self.ingest('suspected_lesion')
        original = self.event()['id']
        for _ in range(4):
            batch = self.batch('suspected_lesion')
            batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
            self.service.ingest(batch)
            self.ingest('suspected_lesion')
        self.assertEqual(self.event()['id'], original)
        self.assertEqual(len(self.events()), 1)
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT event_id FROM alerts WHERE code=?', ('SUSPECTED_LESION',)).fetchone()[0], original)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_legacy_payload_read_is_nonmutating_then_starts_new_clear_run(self):
        self.ingest('suspected_lesion')
        event = self.event()
        event.pop('visual_recovery', None)
        with self.repo.connection() as db:
            original = json.dumps(event)
            db.execute('UPDATE events SET payload=? WHERE id=?', (original, event['id']))
        self.assertEqual(self.event(projected=True)['id'], event['id'])
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM events WHERE id=?', (event['id'],)).fetchone()[0], original)
        self.ingest()
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.event()['id'], event['id'])

    def test_default_300_retention_keeps_active_and_indeterminate_links(self):
        self.ingest('suspected_lesion', 'surface_anomaly')
        originals = {e['id'] for e in self.repo.events()}
        batch = self.batch('suspected_lesion'); batch['visual'] = None
        self.service.ingest(batch)
        with self.repo.connection() as db:
            sample = self.event()
            for i in range(305):
                old = dict(sample, id='resolved-history-' + str(i), status='closed', lifecycle_state='RESOLVED')
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (old['id'], old['device_id'], 'visual', old['code'], json.dumps(old)))
        self.ingest('suspected_lesion', 'surface_anomaly')
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 302)
            self.assertEqual({r[0] for r in db.execute('SELECT event_id FROM alerts')}, originals)

    def test_failure_rolls_back_event_progress_current_history_and_alerts(self):
        self.ingest('suspected_lesion'); self.ingest(); self.ingest()
        stored = self.repo.events()
        previous = self.repo.read('sim-pond-1', 'visual')
        batch = self.batch()
        with patch.object(self.repo.event_service, 'transition', side_effect=RuntimeError('synthetic rollback')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic rollback'):
                self.service.ingest(batch)
        self.assertEqual(self.repo.events(), stored)
        self.assertEqual(self.repo.read('sim-pond-1', 'visual'), previous)
        self.service.ingest(batch)
        self.assertEqual(self.event()['lifecycle_state'], 'RESOLVED')

    def test_delayed_visual_before_known_missing_window_cannot_restore_certainty(self):
        self.ingest('suspected_lesion'); self.ingest()
        delayed = self.batch()
        missing = self.batch(); missing['visual'] = None
        self.service.ingest(missing)
        self.service.ingest(delayed)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.event(projected=True)['lifecycle_state'], 'INDETERMINATE')
        self.ingest()
        self.assertEqual(self.count(), 1)

    def test_partial_positive_remains_same_episode_and_invalid_request_does_not_supply_clear(self):
        self.ingest('suspected_lesion'); self.ingest()
        original = self.event()['id']
        batch = self.batch('suspected_lesion'); batch['visual']['valid_frames'] = 1
        self.service.ingest(batch)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.event()['id'], original)
        self.assertEqual(self.event()['lifecycle_state'], 'ACTIVE')
        invalid = self.batch(); invalid['visual']['anomaly_counts']['suspected_lesion'] = -1
        with self.assertRaises(ValueError):
            self.service.ingest(invalid)
        self.ingest()
        self.assertEqual(self.count(), 1)

    def test_http_bootstrap_detail_and_resolved_history(self):
        self.ingest('suspected_lesion'); self.ingest()
        client = create_app(data_service=self.service).test_client()
        response = client.get('/api/bootstrap').get_json()
        event = next(e for e in response['events'] if e['code'] == 'SUSPECTED_LESION')
        self.assertEqual(event['lifecycle_state'], 'ACTIVE')
        self.assertEqual(event['visual_recovery']['clear_count'], 1)
        self.assertEqual(client.get('/api/events/' + event['id']).status_code, 200)
        self.ingest(); self.ingest()
        history = client.get('/api/events?status=RESOLVED').get_json()['items']
        self.assertTrue(any(e['id'] == event['id'] for e in history))

    def test_seed42_600_seconds_reduces_spurious_cycles(self):
        sim = Simulator(start=self.start, scenario='suspected_disease', seed=42, session_id='evt1-seed42')
        for _ in range(60):
            batch = sim.advance(10)
            self.now = datetime.fromisoformat(batch['timestamp'])
            self.service.ingest(batch)
        for code in ('SUSPECTED_LESION', 'SURFACE_ANOMALY', 'SUSPECTED_DEAD'):
            self.assertEqual(len(self.events(code=code)), 2 if code == 'SUSPECTED_DEAD' else 1, code)
            self.assertEqual(self.event(code=code)['lifecycle_state'], 'ACTIVE', code)
        self.assertEqual(sum(e['lifecycle_state'] == 'RESOLVED' for e in self.events(code='SUSPECTED_DEAD')), 1)


if __name__ == '__main__':
    unittest.main()
