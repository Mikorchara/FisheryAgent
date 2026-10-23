"""Legacy closure is historical evidence, not a newly verified rule recovery."""

import json
import unittest

from apps.management_web.app import create_app
from apps.monitoring.event_records import deletable
from apps.monitoring.tests import test_event_lifecycle as lifecycle
from apps.monitoring.tests import test_event_management as management


class LegacyClosedEventTests(unittest.TestCase):
    setUp = lifecycle.VisualLifecycleTests.setUp
    batch = lifecycle.VisualLifecycleTests.batch
    oxygen = management.EventManagementTests.oxygen
    water_events = management.EventManagementTests.water_events
    closed = management.EventManagementTests.closed

    def legacy(self):
        event = self.closed()
        with self.repo.connection() as db:
            raw = json.loads(db.execute('SELECT payload FROM events WHERE id=?', (event['id'],)).fetchone()[0])
            for key in ('lifecycle_state', 'state_reason', 'rule_identity', 'risk_family'):
                raw.pop(key, None)
            db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(raw), event['id']))
        return raw

    def test_closed_legacy_is_readable_and_deletable_without_rewriting_evidence(self):
        raw = self.legacy()
        with self.repo.connection() as db:
            payload = db.execute('SELECT payload FROM events WHERE id=?', (raw['id'],)).fetchone()[0]
        event = next(e for e in self.service.events() if e['id'] == raw['id'])
        self.assertTrue(event['legacy_closed'])
        self.assertEqual(event['lifecycle_state'], 'INDETERMINATE')
        self.assertEqual(event['state_reason'], 'LEGACY_UNREVIEWED')
        self.assertEqual(event['resolved_at'], raw['resolved_at'])
        self.assertTrue(event['deletable'])
        self.assertFalse(event['handling']['can_ack'])
        self.assertEqual(event['handling']['action_count'], 0)
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM events WHERE id=?', (raw['id'],)).fetchone()[0], payload)
            before = {t: db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                for t in ('history', 'batches', 'current', 'alerts', 'event_actions')}
        plan = self.repo.prepare_event_deletion('single', raw['id'])
        self.assertEqual((plan['count'], plan['legacy_count']), (1, 1))
        self.assertEqual(self.repo.delete_events('single', raw['id'], plan['revision'])['deleted_count'], 1)
        with self.repo.connection() as db:
            self.assertEqual(before, {t: db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before})

    def test_incomplete_inconsistent_or_pending_legacy_is_never_cleanup_evidence(self):
        raw = self.legacy()
        variants = [dict(status='pending'), dict(resolved_at=None), dict(resolved_at='invalid'),
            dict(resolved_at='2026-10-23T00:00:00'), dict(resolved_at='2026-10-22T23:59:59+00:00'),
            dict(occurred_at=None), dict(last_observed_at='invalid'),
            dict(last_observed_at='2026-10-24T00:00:00+00:00'),
            dict(lifecycle_state='INDETERMINATE', legacy_closed=True), dict(lifecycle_state='ACTIVE')]
        for fields in variants:
            with self.subTest(fields=fields):
                altered = {**raw, **fields}
                self.assertFalse(deletable(altered))
                with self.repo.connection() as db:
                    db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(altered), raw['id']))
                with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
                    self.repo.prepare_event_deletion('single', raw['id'])
        self.assertFalse(deletable(raw, linked=True))
        self.assertFalse(deletable(raw, referenced=True))
        self.assertFalse(deletable(raw, audited=True))

    def test_bulk_counts_legacy_and_modern_without_changing_state_or_deleting_active(self):
        raw = self.legacy()
        modern = self.closed()
        self.oxygen(4.2)
        active = next(e for e in self.water_events() if e['lifecycle_state'] == 'ACTIVE')
        self.assertNotIn('legacy_closed', active)
        self.assertNotIn('legacy_closed', next(e for e in self.water_events() if e['id'] == modern['id']))
        plan = self.repo.prepare_event_deletion('all_resolved')
        self.assertEqual((plan['count'], plan['legacy_count']), (2, 1))
        self.assertEqual(self.repo.delete_events('all_resolved', None, plan['revision'])['deleted_count'], 2)
        self.assertEqual([e['id'] for e in self.service.events()], [active['id']])

    def test_links_references_and_ack_audit_continue_to_block_legacy_deletion(self):
        raw = self.legacy()
        self.oxygen(4.2)
        active = next(e for e in self.water_events() if e['lifecycle_state'] == 'ACTIVE')
        h = active['handling']
        self.service.acknowledge_event(dict(event_id=active['id'], cycle_id=h['cycle_id'],
            grade_token=h['grade_token'], grade_version=h['grade_version'], revision=h['revision'],
            request_id='c26de02c-63ec-4b82-8ea0-5721d4e761ec'))
        with self.repo.connection() as db:
            current = json.loads(db.execute('SELECT payload FROM events WHERE id=?', (active['id'],)).fetchone()[0])
            current['superseded_by'] = raw['id']
            db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(current), active['id']))
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
            self.repo.prepare_event_deletion('single', raw['id'])
        with self.repo.connection() as db:
            current.pop('superseded_by')
            db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(current), active['id']))
            db.execute('INSERT INTO event_handling_members VALUES(?,?)', (raw['id'], h['cycle_id']))
        event = next(e for e in self.service.events() if e['id'] == raw['id'])
        self.assertFalse(event['deletable'])
        self.assertEqual(event['deletion_block_reason'], 'ACK_AUDIT_RETAINED')
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'], 0)

    def test_new_link_between_legacy_preview_and_commit_is_rejected(self):
        raw = self.legacy()
        plan = self.repo.prepare_event_deletion('single', raw['id'])
        with self.repo.connection() as db:
            db.execute('INSERT INTO alerts VALUES(?,?,?,?)', (raw['device_id'], raw['channel'], raw['code'], raw['id']))
        self.assertFalse(next(e for e in self.service.events() if e['id'] == raw['id'])['deletable'])
        with self.assertRaisesRegex(ValueError, 'EVENT_NOT_DELETABLE'):
            self.repo.delete_events('single', raw['id'], plan['revision'])
        self.assertTrue(any(e['id'] == raw['id'] for e in self.repo.events()))

    def test_http_exposes_legacy_closure_but_requires_local_token_and_preview_revision(self):
        raw = self.legacy()
        app = create_app(data_service=self.service)
        with app.test_client() as client:
            event = client.get('/api/events/'+raw['id']).json
            self.assertTrue(event['legacy_closed'])
            self.assertFalse(event['handling']['can_ack'])
            value = dict(scope='single', event_id=raw['id'])
            self.assertEqual(client.post('/api/events/deletion-preview', json=value).status_code, 403)
            token = client.get('/api/bootstrap').json['event_management']['write_token']
            headers = {'X-Management-Events': token}
            preview = client.post('/api/events/deletion-preview', json=value, headers=headers)
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.json['legacy_count'], 1)
            self.assertEqual(client.post('/api/events/delete', json={**value, 'revision':'0'*64}, headers=headers).status_code, 409)
            result = client.post('/api/events/delete', json={**value, 'revision':preview.json['revision']}, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['deleted_count'], 1)
            self.assertEqual(client.get('/api/events/'+raw['id']).status_code, 404)


if __name__ == '__main__':
    unittest.main()
