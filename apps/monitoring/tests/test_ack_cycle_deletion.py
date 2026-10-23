"""Explicit deletion of an ended ACK cycle; synthetic temporary SQLite only."""
import json
import unittest
from datetime import timedelta

from apps.management_web.app import create_app
from apps.monitoring.tests import test_event_ack as ack


class AckCycleDeletionTests(unittest.TestCase):
    setUp = ack.EventAckTests.setUp
    batch = ack.EventAckTests.batch
    oxygen = ack.EventAckTests.oxygen
    water_events = ack.EventAckTests.water_events
    current = ack.EventAckTests.current
    request = ack.EventAckTests.request
    ack = ack.EventAckTests.ack

    def cycle(self, ended=True):
        self.oxygen(4.2); self.ack()
        self.oxygen(2.2); self.ack(self.current('OXYGEN_CRITICAL_LOW'))
        target = self.current('OXYGEN_CRITICAL_LOW')
        if ended:
            self.oxygen(6.4)
        return target['id']

    def counts(self):
        with self.repo.connection() as db:
            return {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in
                ('events','event_actions','event_handling','event_handling_members','history','batches','current','alerts','channel_contacts')}

    def test_ended_cycle_deletes_its_members_and_ack_atomically_and_preserves_observations(self):
        target=self.cycle()
        before=self.counts()
        self.assertTrue(self.current()['can_delete_ack_cycle'])
        plan=self.repo.prepare_event_deletion('ack_cycle',target)
        self.assertEqual((plan['count'],plan['ack_count']),(2,2))
        result=self.repo.delete_events('ack_cycle',target,plan['revision'])
        self.assertEqual((result['deleted_count'],result['deleted_ack_count']),(2,2))
        after=self.counts()
        for t in ('events','event_actions','event_handling','event_handling_members'):
            self.assertEqual(after[t],0)
        for t in ('history','batches','current','alerts','channel_contacts'):
            self.assertEqual(after[t],before[t])
        with self.repo.connection() as db:
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
        with self.assertRaisesRegex(ValueError,'EVENT_NOT_FOUND'):
            self.repo.delete_events('ack_cycle',target,plan['revision'])
        self.oxygen(4.2)
        self.assertFalse(self.current()['handling']['confirmed'])

    def test_active_or_unknown_cannot_be_deleted_and_old_bulk_protection_stays(self):
        target=self.cycle(False)
        with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_NOT_ENDED'):
            self.repo.prepare_event_deletion('ack_cycle',target)
        self.now += timedelta(seconds=95)
        self.assertFalse(self.current()['can_delete_ack_cycle'])
        with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_NOT_ENDED'):
            self.repo.prepare_event_deletion('ack_cycle',target)
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'],0)
        with self.assertRaisesRegex(ValueError,'EVENT_NOT_DELETABLE'):
            self.repo.prepare_event_deletion('single',target)

    def test_revision_and_storage_failure_roll_back_ack_and_members(self):
        target=self.cycle()
        plan=self.repo.prepare_event_deletion('ack_cycle',target)
        with self.repo.connection() as db:
            db.execute('UPDATE event_handling SET revision=revision+1')
        with self.assertRaisesRegex(ValueError,'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('ack_cycle',target,plan['revision'])
        plan=self.repo.prepare_event_deletion('ack_cycle',target)
        before=self.counts()
        with self.repo.connection() as db:
            db.execute("CREATE TRIGGER fail_cycle_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaisesRegex(ValueError,'EVENT_DELETE_STORAGE_ERROR'):
            self.repo.delete_events('ack_cycle',target,plan['revision'])
        self.assertEqual(self.counts(),before)

    def test_external_reference_or_missing_member_is_rejected(self):
        target=self.cycle()
        with self.repo.connection() as db:
            e=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(target,)).fetchone()[0])
            clone={**e,'id':'external-reference','superseded_by':target}
            clone.pop('risk_family')
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(clone['id'],clone['device_id'],clone['channel'],clone['code'],json.dumps(clone)))
        with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_REFERENCED'):
            self.repo.prepare_event_deletion('ack_cycle',target)
        with self.repo.connection() as db:
            db.execute('DELETE FROM events WHERE id=?',('external-reference',))
            db.execute('DELETE FROM event_handling_members WHERE event_id=?',(target,))
        with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_MEMBERS_CHANGED'):
            self.repo.prepare_event_deletion('ack_cycle',self.current()['id'])

    def test_http_requires_local_permission_preview_and_confirmation(self):
        target=self.cycle()
        with create_app(data_service=self.service).test_client() as client:
            value={'scope':'ack_cycle','event_id':target}
            self.assertEqual(client.post('/api/events/deletion-preview',json=value).status_code,403)
            token=client.get('/api/bootstrap').json['event_management']['write_token']
            headers={'X-Management-Events':token}
            self.assertEqual(client.post('/api/events/deletion-preview',json=value,headers=headers,
                environ_overrides={'REMOTE_ADDR':'192.0.2.5'}).status_code,403)
            preview=client.post('/api/events/deletion-preview',json=value,headers=headers)
            self.assertEqual(preview.status_code,200)
            self.assertEqual(preview.json['ack_count'],2)
            bad=client.post('/api/events/delete',json={**value,'revision':'0'*64},headers=headers)
            self.assertEqual(bad.status_code,409)
            good=client.post('/api/events/delete',json={**value,'revision':preview.json['revision']},headers=headers)
            self.assertEqual(good.status_code,200)
            self.assertEqual(good.json['deleted_ack_count'],2)

    def test_confirmation_means_last_grade_not_any_historical_ack(self):
        self.oxygen(4.2);self.ack()
        self.assertTrue(self.current()['handling']['confirmed'])
        self.assertEqual(self.service.event_cycles()[0]['title'],'溶解氧偏低')
        self.oxygen(2.2)
        self.assertFalse(self.current('OXYGEN_CRITICAL_LOW')['handling']['confirmed'])
        self.assertEqual(self.service.event_cycles()[0]['title'],'溶解氧低')
        self.ack(self.current('OXYGEN_CRITICAL_LOW'))
        self.oxygen(4.2)
        self.assertFalse(self.current()['handling']['confirmed'])
        self.oxygen(6.4)
        self.assertFalse(self.current()['handling']['confirmed'])
        self.assertGreater(self.current()['handling']['action_count'],0)

    def test_other_risk_cycles_and_restart_remain_intact(self):
        target=self.cycle()
        plan=self.repo.prepare_event_deletion('ack_cycle',target)
        self.oxygen(4.2);self.ack()
        active=self.current()['id']
        self.repo.delete_events('ack_cycle',target,plan['revision'])
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.service import MonitoringService
        restarted=MonitoringService(MonitoringRepository(self.path),clock=lambda:self.now)
        remaining=restarted.event_cycles()
        self.assertEqual(len(remaining),1)
        self.assertEqual(remaining[0]['id'],active)
        self.assertTrue(remaining[0]['handling']['confirmed'])
        self.assertEqual(remaining[0]['handling']['action_count'],1)
        self.assertFalse(remaining[0]['can_delete_ack_cycle'])
