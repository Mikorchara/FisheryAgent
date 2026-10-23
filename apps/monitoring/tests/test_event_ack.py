"""EVT-3A uses fictional observations and temporary SQLite, never user instances."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import unittest
import uuid

from apps.management_web.app import create_app
from apps.management_web.instance import check_database, InstanceError
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.tests import test_event_management as management
from apps.monitoring.tests import test_event_lifecycle as lifecycle


class EventAckTests(unittest.TestCase):
    setUp = lifecycle.VisualLifecycleTests.setUp
    batch = lifecycle.VisualLifecycleTests.batch
    ingest = lifecycle.VisualLifecycleTests.ingest
    oxygen = management.EventManagementTests.oxygen
    water_events = management.EventManagementTests.water_events

    def current(self, code='OXYGEN_LOW'):
        return next(e for e in self.service.events() if e['code'] == code)

    def request(self, event=None):
        event = event or self.current()
        handling = event['handling']
        return dict(event_id=event['id'], cycle_id=handling['cycle_id'],
            grade_token=handling['grade_token'], grade_version=handling['grade_version'],
            revision=handling['revision'], request_id=str(uuid.uuid4()))

    def ack(self, event=None):
        return self.service.acknowledge_event(self.request(event))

    def test_first_ack_idempotency_snapshot_and_unchanged_observations(self):
        self.oxygen(4.2)
        event = self.current()
        request = self.request(event)
        before = self.repo.events()[0]['observation']
        first = self.service.acknowledge_event(request)
        self.assertEqual(first, self.service.acknowledge_event(request))
        current = self.current()
        self.assertEqual(current['handling']['state'], 'ACKNOWLEDGED')
        self.assertEqual(current['handling']['acked_at'], self.now.isoformat())
        self.assertEqual(current['handling']['history'][0]['actor_kind'], 'local_visitor')
        self.assertEqual(current['lifecycle_state'], 'ACTIVE')
        self.assertEqual(current['observation'], before)
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM event_actions').fetchone()[0], 1)
            raw = json.loads(db.execute('SELECT payload FROM events WHERE id=?', (event['id'],)).fetchone()[0])
            self.assertNotIn('handling', raw)
            snapshot = json.loads(db.execute('SELECT event_snapshot FROM event_actions').fetchone()[0])
            self.assertEqual(snapshot['last_batch_id'], raw['last_batch_id'])
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_REQUEST_CONFLICT'):
            self.service.acknowledge_event({**request, 'revision': 1})

    def test_same_grade_upgrade_extreme_and_downgrade_never_resurrect_old_ack(self):
        self.oxygen(4.2); self.ack()
        original = self.current()
        self.oxygen(4.1)
        self.assertEqual(self.current()['handling']['state'], 'ACKNOWLEDGED')
        self.oxygen(2.2)
        critical = self.current('OXYGEN_CRITICAL_LOW')
        self.assertEqual(critical['handling']['state'], 'PENDING')
        self.assertEqual(critical['handling']['cycle_id'], original['handling']['cycle_id'])
        self.ack(critical)
        self.oxygen(.5)  # Both severe grades are severity=critical, but ranks differ.
        extreme = self.current('OXYGEN_CRITICAL_EXTREME')
        self.assertEqual(extreme['handling']['state'], 'PENDING')
        self.assertEqual(extreme['handling']['grade_rank'], 3)
        self.ack(extreme)
        self.oxygen(4.2)
        low = self.current()
        self.assertEqual(low['handling']['state'], 'PENDING')
        self.assertEqual(low['handling']['action_count'], 3)
        self.assertGreater(low['handling']['revision'], original['handling']['revision'])

    def test_resolved_history_and_new_cycle_do_not_inherit_ack(self):
        self.oxygen(4.2); self.ack()
        old = self.current(); request = self.request(old)
        self.oxygen(6.4)
        history = self.current()
        self.assertFalse(history['handling']['can_ack'])
        self.assertEqual(history['handling']['action_count'], 1)
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_NOT_ACTIVE'):
            self.service.acknowledge_event(request)
        self.oxygen(4.2)
        new = next(e for e in self.water_events() if e['lifecycle_state'] == 'ACTIVE')
        self.assertNotEqual(new['handling']['cycle_id'], old['handling']['cycle_id'])
        self.assertEqual(new['handling']['action_count'], 0)

    def test_session_offline_missing_and_restart_preserve_manual_state(self):
        self.ingest('suspected_lesion')
        event = self.current('SUSPECTED_LESION'); self.ack(event)
        self.ingest('suspected_lesion', session='restarted-simulator')
        batch = self.batch(); batch['visual'] = None; self.service.ingest(batch)
        self.now += timedelta(seconds=91)
        event = self.current('SUSPECTED_LESION')
        self.assertEqual(event['lifecycle_state'], 'INDETERMINATE')
        self.assertEqual(event['handling']['state'], 'ACKNOWLEDGED')
        self.repo = MonitoringRepository(self.path, require_existing=True)
        self.service = MonitoringService(self.repo, clock=lambda: self.now)
        self.assertEqual(self.current('SUSPECTED_LESION')['handling']['action_count'], 1)
        self.assertEqual(self.current('SUSPECTED_LESION')['handling']['state'], 'ACKNOWLEDGED')

    def test_legacy_family_and_unknown_rule_are_read_only(self):
        self.oxygen(4.2)
        with self.repo.connection() as db:
            event = json.loads(db.execute('SELECT payload FROM events').fetchone()[0])
            event.pop('risk_family')
            db.execute('UPDATE events SET payload=?', (json.dumps(event),))
        event = self.current()
        self.assertTrue(event['risk_family']['inferred'])
        self.assertFalse(event['handling']['can_ack'])
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_UNAVAILABLE'):
            self.service.acknowledge_event(self.request(event))

    def test_revision_cycle_current_grade_and_concurrent_ack_guards(self):
        self.oxygen(4.2)
        old = self.request()
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_CONFLICT'):
            self.service.acknowledge_event({**old, 'cycle_id': '0'*64})
        self.oxygen(2.2)
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_TARGET_NOT_CURRENT'):
            self.service.acknowledge_event(old)
        event = self.current('OXYGEN_CRITICAL_LOW')
        first, second = self.request(event), self.request(event)
        other = MonitoringRepository(self.path, require_existing=True)
        def submit(repo, request):
            try:
                return repo.acknowledge_event(request, at=self.now)['status']
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: submit(*args), [(self.repo, first), (other, second)]))
        self.assertEqual(results.count('ACK_RECORDED'), 1)
        self.assertEqual(results.count('EVENT_ACK_CONFLICT'), 1)
        self.assertEqual(self.current('OXYGEN_CRITICAL_LOW')['handling']['action_count'], 1)

    def test_ack_pins_whole_cycle_against_single_bulk_and_automatic_retention(self):
        self.oxygen(4.2); self.ack(); self.oxygen(2.2); self.oxygen(6.4)
        ids = {e['id'] for e in self.water_events()}
        self.assertEqual(len(ids), 2)
        for event in self.water_events():
            self.assertFalse(event['deletable'])
            self.assertEqual(event['deletion_block_reason'], 'ACK_AUDIT_RETAINED')
            with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
                self.repo.prepare_event_deletion('single', event['id'])
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'], 0)
        self.repo.event_limit = 1
        for _ in range(4):
            self.oxygen(4.2); self.oxygen(6.4)
        self.assertTrue(ids <= {e['id'] for e in self.repo.events()})
        with self.repo.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM events WHERE id=?', (next(iter(ids)),))

    def test_rule_identity_change_does_not_inherit_ack(self):
        self.oxygen(4.2); self.ack()
        old = self.current()
        from unittest.mock import patch
        original = self.service._assess
        from dataclasses import replace
        def changed(*args):
            analysis = original(*args)
            return replace(analysis, findings=tuple(replace(f, rule=replace(f.rule, version='fixture-next-rule')) for f in analysis.findings))
        with patch.object(self.service, '_assess', side_effect=changed):
            self.oxygen(4.2)
        new = next(e for e in self.repo.events() if e['id'] != old['id'] and e['code'] == 'OXYGEN_LOW')
        self.assertNotEqual(new['handling']['cycle_id'], old['handling']['cycle_id'])
        self.assertEqual(new['handling']['action_count'], 0)

    def test_late_request_after_grade_roundtrip_and_wrong_version_are_rejected(self):
        self.oxygen(4.2)
        old = self.request()
        self.oxygen(2.2); self.oxygen(4.2)
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_CONFLICT'):
            self.service.acknowledge_event(old)
        request = self.request()
        for altered in ({'grade_version':'old-policy'},{'revision':True}):
            with self.assertRaises(ValueError):
                self.service.acknowledge_event(request|altered)
        self.service.acknowledge_event(request)
        self.repo = MonitoringRepository(self.path,require_existing=True)
        self.assertEqual(self.repo.acknowledge_event(request,at=self.now)['status'],'ACK_RECORDED')
        self.assertEqual(self.current()['handling']['action_count'],1)

    def test_failure_rolls_back_handling_action_and_membership_together(self):
        self.oxygen(4.2)
        value = self.request()
        with self.repo.connection() as db:
            db.execute("CREATE TRIGGER synthetic_ack_failure BEFORE INSERT ON event_actions BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaisesRegex(ValueError, 'EVENT_ACK_STORAGE_ERROR'):
            self.service.acknowledge_event(value)
        with self.repo.connection() as db:
            for table in ('event_actions','event_handling','event_handling_members'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.current()['lifecycle_state'],'ACTIVE')

    def test_devices_and_codes_are_independent(self):
        self.oxygen(4.2); self.ack()
        self.ingest('suspected_lesion','surface_anomaly',device='sim-pond-2')
        events = [e for e in self.service.events() if e['device_id']=='sim-pond-2' and e['channel']=='visual']
        self.ack(next(e for e in events if e['code']=='SUSPECTED_LESION'))
        untouched = next(e for e in self.service.events() if e['code']=='SURFACE_ANOMALY')
        self.assertEqual(untouched['handling']['state'],'PENDING')
        self.assertEqual(untouched['handling']['action_count'],0)

    def test_http_gate_strict_fields_history_and_safe_errors(self):
        self.oxygen(4.2)
        client = create_app(data_service=self.service).test_client()
        token = client.get('/api/bootstrap').get_json()['event_management']['write_token']
        headers = {'X-Management-Events': token}
        value = self.request()
        self.assertEqual(client.post('/api/events/ack', json=value).status_code, 403)
        for extra in ({'environ_overrides': {'REMOTE_ADDR':'192.0.2.4'}}, {'headers':{**headers,'Origin':'http://external.invalid'}}):
            self.assertEqual(client.post('/api/events/ack', json=value, **({'headers':headers}|extra)).status_code, 403)
        self.assertEqual(client.post('/api/events/ack', json={**value,'actor':'admin'}, headers=headers).status_code, 400)
        self.assertEqual(client.post('/api/events/ack', json=value, headers=headers).status_code, 200)
        self.assertEqual(client.post('/api/events/ack', json=value, headers=headers).status_code, 200)
        detail = client.get('/api/events/'+value['event_id']).get_json()
        self.assertEqual(detail['handling']['state'], 'ACKNOWLEDGED')
        self.assertNotIn('event_snapshot', detail['handling']['history'][0])


if __name__ == '__main__':
    unittest.main()
