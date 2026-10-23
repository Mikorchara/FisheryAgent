"""Read-only wording evidence must not alter the stored lifecycle or observations."""

from datetime import timedelta
import json
import unittest

from apps.management_web.app import create_app
from apps.monitoring.tests import test_event_management as management
from apps.monitoring.tests import test_event_lifecycle as lifecycle


class EventWordingTests(unittest.TestCase):
    setUp = lifecycle.VisualLifecycleTests.setUp
    batch = lifecycle.VisualLifecycleTests.batch
    ingest = lifecycle.VisualLifecycleTests.ingest
    oxygen = management.EventManagementTests.oxygen
    water_events = management.EventManagementTests.water_events

    def stored(self):
        with self.repo.connection() as db:
            return db.execute('SELECT id,payload FROM events ORDER BY id').fetchall()

    def test_upgrade_and_other_grade_changes_are_projection_only(self):
        self.oxygen(4.2); self.oxygen(2.2)
        before = self.stored()
        low = next(e for e in self.water_events() if e['code'] == 'OXYGEN_LOW')
        self.assertEqual(low['family_level_change'], 'UPGRADED')
        member = next(e for e in low['family_members'] if e['id'] == low['id'])
        self.assertEqual(member['family_level_change'], 'UPGRADED')
        self.assertEqual(member['family_current_code'], 'OXYGEN_CRITICAL_LOW')
        self.assertEqual(low['state_reason'], 'OTHER_RISK_CONDITION_ACTIVE')
        self.assertEqual(self.stored(), before)
        self.oxygen(4.1)
        critical = next(e for e in self.water_events() if e['code'] == 'OXYGEN_CRITICAL_LOW')
        self.assertEqual(critical['family_level_change'], 'CHANGED')
        self.assertEqual(critical['lifecycle_state'], 'INDETERMINATE')

    def test_stale_offline_and_missing_observations_have_distinct_read_evidence(self):
        self.ingest('suspected_lesion')
        before = self.stored()
        self.now += timedelta(seconds=31)
        event = next(e for e in self.service.events() if e['code'] == 'SUSPECTED_LESION')
        self.assertEqual(event['current_data_quality']['freshness'], 'stale')
        self.assertEqual(event['current_data_quality']['connectivity'], 'online')
        self.now += timedelta(seconds=60)
        event = next(e for e in self.service.events() if e['code'] == 'SUSPECTED_LESION')
        self.assertEqual(event['current_data_quality']['connectivity'], 'offline')
        self.assertEqual(self.stored(), before)
        batch = self.batch(); batch['visual'] = None
        self.now = self.start + timedelta(seconds=20)
        self.service.ingest(batch)
        event = next(e for e in self.service.events() if e['code'] == 'SUSPECTED_LESION')
        self.assertEqual(event['state_reason'], 'VISUAL_OBSERVATION_MISSING')
        self.assertEqual(event['lifecycle_state'], 'INDETERMINATE')

    def test_invalid_evidence_and_three_window_resolution_keep_original_states(self):
        self.ingest('suspected_lesion')
        batch = self.batch()
        batch['visual']['valid_frames'] = 10
        self.service.ingest(batch)
        event = next(e for e in self.service.events() if e['code'] == 'SUSPECTED_LESION')
        self.assertEqual(event['current_data_quality']['quality'], 'partial')
        self.assertEqual(event['state_reason'], 'FRAME_COVERAGE_INSUFFICIENT')
        for count in (1, 2, 3):
            self.ingest()
            event = next(e for e in self.service.events() if e['code'] == 'SUSPECTED_LESION')
            self.assertEqual(event['lifecycle_state'], 'RESOLVED' if count == 3 else 'ACTIVE')

    def test_legacy_records_and_http_readers_share_evidence_without_backfill(self):
        self.oxygen(4.2); self.oxygen(2.2)
        with self.repo.connection() as db:
            for event_id, payload in db.execute('SELECT id,payload FROM events').fetchall():
                event = json.loads(payload)
                event.pop('risk_family', None)
                db.execute('UPDATE events SET payload=? WHERE id=?', (json.dumps(event), event_id))
        before = self.stored()
        client = create_app(data_service=self.service).test_client()
        bootstrap = client.get('/api/bootstrap').get_json()['events']
        event = next(e for e in bootstrap if e['code'] == 'OXYGEN_LOW')
        self.assertTrue(event['risk_family']['inferred'])
        self.assertEqual(event['family_level_change'], 'UPGRADED')
        listing = client.get('/api/events').get_json()['items']
        detail = client.get('/api/events/' + event['id']).get_json()
        for projection in (next(e for e in listing if e['id'] == event['id']), detail):
            for key in ('lifecycle_state', 'state_reason', 'family_level_change', 'current_data_quality'):
                self.assertEqual(projection[key], event[key])
        self.assertEqual(self.stored(), before)


if __name__ == '__main__':
    unittest.main()
