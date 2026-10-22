"""EVT-2: risk families, complete-store interval queries and guarded deletion."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from apps.monitoring.repository import MonitoringRepository

from apps.management_web.app import create_app
from apps.monitoring.tests import test_event_lifecycle as lifecycle


class EventManagementTests(unittest.TestCase):
    setUp = lifecycle.VisualLifecycleTests.setUp
    batch = lifecycle.VisualLifecycleTests.batch
    ingest = lifecycle.VisualLifecycleTests.ingest

    def oxygen(self, value, **kwargs):
        batch = self.batch(**kwargs)
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=value, min=value, max=value, latest=value)
        self.service.ingest(batch)
        return batch

    def water_events(self):
        return [e for e in self.service.events() if e['code'].startswith('OXYGEN_')]

    def test_low_critical_improving_and_recovery_preserve_ids_and_family_evidence(self):
        first = self.oxygen(4.2)
        low = self.water_events()[0]
        second = self.oxygen(2.2)
        events = self.water_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(len({e['risk_family']['episode_id'] for e in events}), 1)
        old = next(e for e in events if e['id'] == low['id'])
        self.assertEqual(old['lifecycle_state'], 'INDETERMINATE')
        self.assertEqual(old['state_reason'], 'OTHER_RISK_CONDITION_ACTIVE')
        self.assertEqual(old['family_current_code'], 'OXYGEN_CRITICAL_LOW')
        self.assertEqual(next(e for e in old['family_members'] if e['id'] == old['id'])['state_reason'], 'OTHER_RISK_CONDITION_ACTIVE')
        self.oxygen(4.1)
        events = self.water_events()
        active = next(e for e in events if e['lifecycle_state'] == 'ACTIVE')
        self.assertEqual(active['id'], low['id'])
        self.assertEqual([t['code'] for t in active['risk_family']['transitions']],
            ['OXYGEN_LOW', 'OXYGEN_CRITICAL_LOW', 'OXYGEN_LOW'])
        self.assertEqual(active['risk_family']['transitions'][0]['batch_id'], first['batch_id'])
        self.assertEqual(active['risk_family']['transitions'][1]['metric']['mean'], 2.2)
        self.assertEqual(active['risk_family']['transitions'][1]['batch_id'], second['batch_id'])
        self.oxygen(6.4)
        self.assertTrue(all(e['lifecycle_state'] == 'RESOLVED' for e in self.water_events()))
        self.oxygen(4.2)
        new = next(e for e in self.water_events() if e['lifecycle_state'] == 'ACTIVE')
        self.assertNotEqual(new['risk_family']['episode_id'], low['risk_family']['episode_id'])

    def test_missing_offline_and_session_do_not_turn_grade_change_into_recovery(self):
        self.oxygen(4.2); self.oxygen(2.2, session='next-session')
        self.assertEqual(len(self.water_events()), 2)
        self.assertTrue(all(e['lifecycle_state'] != 'RESOLVED' for e in self.water_events()))
        batch = self.batch()
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=None, min=None, max=None, latest=None, valid_samples=0)
        self.service.ingest(batch)
        self.assertTrue(all(e['family_current_code'] is None for e in self.water_events()))
        self.now += timedelta(seconds=91)
        self.assertTrue(all(e['lifecycle_state'] == 'INDETERMINATE' for e in self.water_events()))
        self.assertTrue(all(e['state_reason'] == 'STALE_OR_OFFLINE' for e in self.water_events()))

    def test_different_devices_and_risk_directions_are_not_one_family(self):
        self.oxygen(4.2)
        self.oxygen(2.2, device='sim-pond-2')
        self.assertEqual(len({e['risk_family']['episode_id'] for e in self.water_events()}), 2)
        batch = self.batch()
        batch['water']['metrics']['temperature_c'].update(mean=10, min=10, max=10, latest=10)
        self.service.ingest(batch)
        batch = self.batch()
        batch['water']['metrics']['temperature_c'].update(mean=34, min=34, max=34, latest=34)
        self.service.ingest(batch)
        temps = [e for e in self.service.events() if e['code'].startswith('TEMP_')]
        self.assertEqual(len({e['risk_family']['key'] for e in temps}), 2)

    def closed(self):
        self.oxygen(2.2); self.oxygen(6.4)
        return self.water_events()[0]

    def test_time_ranges_overlap_open_attention_intervals_and_combine_filters(self):
        closed = self.closed()
        self.oxygen(4.2)
        self.now += timedelta(minutes=70)
        for minutes in (5, 10, 30, 60):
            result = self.service.query_events(lookback_minutes=minutes, q='溶氧', status='INDETERMINATE')
            self.assertEqual(result['total'], 1)
            self.assertNotEqual(result['items'][0]['id'], closed['id'])
        all_records = self.service.query_events(lookback_minutes=None)
        self.assertEqual(all_records['total'], 2)
        self.assertEqual(self.service.query_events(q='不存在')['total'], 0)

    def test_query_searches_entire_store_before_pagination_and_boundary_overlap(self):
        event = self.closed()
        with self.repo.connection() as db:
            for i in range(65):
                item = dict(event, id='historic-' + str(i), title='late-match' if i == 0 else 'other')
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (item['id'], item['device_id'], item['channel'], item['code'], json.dumps(item)))
        page = self.service.query_events(limit=10, offset=60)
        self.assertEqual(page['total'], 66)
        self.assertEqual(len(page['items']), 6)
        self.assertEqual(self.service.query_events(q='late-match')['total'], 1)
        self.now = datetime.fromisoformat(event['resolved_at']) + timedelta(minutes=5)
        self.assertEqual(self.service.query_events(lookback_minutes=5)['total'], 66)
        self.now += timedelta(seconds=1)
        self.assertEqual(self.service.query_events(lookback_minutes=5)['total'], 0)

    def test_single_delete_guards_state_references_duplicates_and_other_tables(self):
        self.oxygen(2.2)
        active = self.water_events()[0]
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
            self.repo.prepare_event_deletion('single', active['id'])
        self.oxygen(6.4)
        with self.repo.connection() as db:
            before = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                for name in ('history', 'batches', 'current', 'alerts', 'channel_contacts')}
        plan = self.repo.prepare_event_deletion('single', active['id'])
        result = self.repo.delete_events('single', active['id'], plan['revision'])
        self.assertEqual(result['deleted_count'], 1)
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_FOUND'):
            self.repo.delete_events('single', active['id'], plan['revision'])
        with self.repo.connection() as db:
            self.assertEqual(before, {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in before})
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_bulk_preview_revision_rejects_changed_candidates_and_preserves_active(self):
        self.closed()
        plan = self.repo.prepare_event_deletion('all_resolved')
        self.closed()
        with self.assertRaisesRegex(ValueError, 'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('all_resolved', None, plan['revision'])
        self.oxygen(4.2)
        plan = self.repo.prepare_event_deletion('all_resolved')
        self.assertEqual(plan['count'], 2)
        self.assertEqual(self.repo.delete_events('all_resolved', None, plan['revision'])['deleted_count'], 2)
        self.assertEqual(len(self.water_events()), 1)
        self.assertEqual(self.water_events()[0]['lifecycle_state'], 'ACTIVE')

    def test_linked_closed_legacy_and_invalid_ids_are_not_deletable(self):
        event = self.closed()
        with self.repo.connection() as db:
            db.execute('INSERT INTO alerts VALUES(?,?,?,?)', (event['device_id'], event['channel'], event['code'], event['id']))
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
            self.repo.prepare_event_deletion('single', event['id'])
        with self.assertRaisesRegex(ValueError, 'INVALID_EVENT_DELETE'):
            self.repo.prepare_event_deletion('single', '../database')
        with self.repo.connection() as db:
            db.execute('DELETE FROM alerts')
            old = deepcopy(event); old.pop('lifecycle_state'); old.pop('resolved_at')
            db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(old), event['id']))
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'], 0)
        self.assertTrue(any(e['id'] == event['id'] for e in self.service.query_events()['items']))
        self.assertEqual(self.service.query_events(lookback_minutes=5)['total'], 0)

    def test_commit_rechecks_links_and_actual_concurrent_payload_changes(self):
        event = self.closed()
        plan = self.repo.prepare_event_deletion('single', event['id'])
        writer = MonitoringRepository(self.path, require_existing=True)
        locked, release = Event(), Event()
        def change():
            with writer.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                altered = dict(event, description='concurrent fictional edit')
                db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(altered), event['id']))
                locked.set()
                if not release.wait(3):
                    raise RuntimeError('test coordination timeout')
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(change)
            self.assertTrue(locked.wait(3))
            deletion = pool.submit(self.repo.delete_events, 'single', event['id'], plan['revision'])
            release.set(); future.result(timeout=5)
            with self.assertRaisesRegex(ValueError, 'EVENT_DELETE_CONFLICT'):
                deletion.result(timeout=5)
        plan = self.repo.prepare_event_deletion('single', event['id'])
        with writer.connection() as db:
            db.execute('INSERT INTO alerts VALUES(?,?,?,?)', (event['device_id'], event['channel'], event['code'], event['id']))
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
            self.repo.delete_events('single', event['id'], plan['revision'])
        self.assertTrue(any(e['id'] == event['id'] for e in self.repo.events()))

    def test_bulk_zero_repeat_invalid_filters_and_history_evidence_survive_member_deletion(self):
        self.oxygen(4.2); self.oxygen(2.2); self.oxygen(6.4)
        events = self.water_events()
        member = events[0]
        plan = self.repo.prepare_event_deletion('single', member['id'])
        self.repo.delete_events('single', member['id'], plan['revision'])
        retained = self.water_events()[0]
        self.assertEqual(len(retained['risk_family']['transitions']), 3)
        self.assertTrue(any(t['event_id'] == member['id'] for t in retained['risk_family']['transitions']))
        plan = self.repo.prepare_event_deletion('all_resolved')
        self.repo.delete_events('all_resolved', None, plan['revision'])
        with self.assertRaisesRegex(ValueError, 'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('all_resolved', None, plan['revision'])
        empty = self.repo.prepare_event_deletion('all_resolved')
        self.assertEqual(empty['count'], 0)
        self.assertEqual(self.repo.delete_events('all_resolved', None, empty['revision'])['deleted_count'], 0)
        for values in ({'lookback_minutes': 7}, {'limit': 0}, {'offset': -1}, {'status': 'bogus'}):
            with self.assertRaisesRegex(ValueError, 'INVALID_EVENT_FILTER'):
                self.service.query_events(**values)

    def test_http_write_access_strict_body_preview_and_commit(self):
        event = self.closed()
        client = create_app(data_service=self.service).test_client()
        token = client.get('/api/bootstrap').get_json()['event_management']['write_token']
        headers = {'X-Management-Events': token}
        value = {'scope': 'single', 'event_id': event['id']}
        self.assertEqual(client.post('/api/events/deletion-preview', json=value).status_code, 403)
        self.assertEqual(client.post('/api/events/deletion-preview', json=value, headers=headers,
            environ_overrides={'REMOTE_ADDR': '192.0.2.20'}).status_code, 403)
        self.assertEqual(client.post('/api/events/deletion-preview', json=value,
            headers={**headers, 'Origin': 'http://external.invalid'}).status_code, 403)
        self.assertEqual(client.post('/api/events/deletion-preview', json={**value, 'status': 'RESOLVED'}, headers=headers).status_code, 400)
        plan = client.post('/api/events/deletion-preview', json=value, headers=headers).get_json()
        response = client.post('/api/events/delete', json={**value, 'revision': plan['revision']}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['deleted_count'], 1)
        self.assertEqual(client.get('/api/events/' + event['id']).status_code, 404)
        self.assertEqual(client.get('/api/events?lookback_minutes=5&limit=1&offset=0').get_json()['total'], 0)

    def test_superseded_reference_protects_target_from_hard_deletion(self):
        event = self.closed()
        with self.repo.connection() as db:
            source = dict(event, id='old-rule-event', status='pending', lifecycle_state='INDETERMINATE', superseded_by=event['id'])
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (source['id'], source['device_id'], source['channel'], source['code'], json.dumps(source)))
        self.assertFalse(next(e for e in self.repo.events() if e['id'] == event['id'])['deletable'])
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
            self.repo.prepare_event_deletion('single', event['id'])
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'], 0)


if __name__ == '__main__':
    unittest.main()
