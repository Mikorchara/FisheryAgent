"""Synthetic SQLite only: operator end never asserts rule recovery."""
from datetime import timedelta
import json
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.tests import test_event_ack as ack


class ManualEndTests(unittest.TestCase):
    setUp=ack.EventAckTests.setUp
    batch=ack.EventAckTests.batch
    oxygen=ack.EventAckTests.oxygen
    water_events=ack.EventAckTests.water_events
    current=ack.EventAckTests.current
    request=ack.EventAckTests.request
    ack=ack.EventAckTests.ack

    def interrupted(self):
        self.oxygen(4.2);self.oxygen(2.2)
        self.now+=timedelta(seconds=95)
        return self.current('OXYGEN_CRITICAL_LOW')

    def value(self,e):
        p=self.service.preview_manual_end(e['id'])
        return dict(event_id=e['id'],revision=p['revision'],request_id=str(uuid.uuid4()),reason='设备已停用，人工结束旧提醒')

    def test_close_keeps_observation_alerts_and_never_resolves(self):
        e=self.interrupted();v=self.value(e)
        with self.repo.connection() as db:
            alerts=list(map(tuple,db.execute('select * from alerts')))
            history=list(map(tuple,db.execute('select * from history')))
        self.service.manual_end_event(v)
        cycles=self.service.event_cycles();self.assertEqual(len(cycles),1)
        self.assertTrue(cycles[0]['manual_end']['active'])
        self.assertEqual(cycles[0]['lifecycle_state'],'INDETERMINATE')
        self.assertIsNone(cycles[0]['resolved_at'])
        self.assertFalse(cycles[0]['manual_end']['can_end'])
        with self.assertRaisesRegex(ValueError,'EVENT_ACK_MANUALLY_ENDED'):
            self.ack(self.current('OXYGEN_CRITICAL_LOW'))
        self.assertEqual(self.service.query_event_cycles(status='MANUALLY_ENDED')['total'],1)
        self.assertEqual(self.service.query_event_cycles(status='INDETERMINATE')['total'],0)
        with self.repo.connection() as db:
            self.assertEqual(alerts,list(map(tuple,db.execute('select * from alerts'))))
            self.assertEqual(history,list(map(tuple,db.execute('select * from history'))))
            self.assertFalse(db.execute('pragma foreign_key_check').fetchall())
            self.assertEqual(db.execute('pragma user_version').fetchone()[0],2)

    def test_live_grade_change_and_recovery_cannot_be_ended(self):
        self.oxygen(4.2);self.oxygen(2.2)
        for e in self.water_events():
            with self.assertRaisesRegex(ValueError,'REQUIRES_INTERRUPTION'):
                self.service.preview_manual_end(e['id'])
        self.oxygen(6.4)
        with self.assertRaisesRegex(ValueError,'REQUIRES_INTERRUPTION'):
            self.service.preview_manual_end(self.current()['id'])

    def test_restart_unknown_keeps_end_fresh_hit_reopens_and_upgrade_reconfirms(self):
        e=self.interrupted();self.service.manual_end_event(self.value(e))
        self.service=MonitoringService(MonitoringRepository(self.path),clock=lambda:self.now)
        self.assertTrue(self.service.event_cycles()[0]['manual_end']['active'])
        self.now+=timedelta(seconds=10)
        self.assertTrue(self.service.event_cycles()[0]['manual_end']['active'])
        self.sim.skip_windows(11,10);self.oxygen(2.2)
        event=self.current('OXYGEN_CRITICAL_LOW')
        self.assertFalse(event['manual_end']['active'])
        self.assertEqual(len(event['manual_end']['history']),1)
        self.assertEqual(event['lifecycle_state'],'ACTIVE')

    def test_idempotency_conflicts_and_latest_observation_cas(self):
        e=self.interrupted();v=self.value(e)
        first=self.service.manual_end_event(v)
        self.assertEqual(first,self.service.manual_end_event(v))
        with self.assertRaisesRegex(ValueError,'REQUEST_CONFLICT'):
            self.service.manual_end_event({**v,'reason':'另一个原因'})
        self.sim.skip_windows(10,10);self.oxygen(2.2)
        self.now+=timedelta(seconds=95)
        stale=self.value(self.current('OXYGEN_CRITICAL_LOW'))
        with self.repo.connection() as db:
            db.execute("update channel_contacts set last_received_at=?",(self.now.isoformat(),))
        with self.assertRaisesRegex(ValueError,'EVENT_END_CONFLICT'):
            self.service.manual_end_event(stale)

    def test_legacy_single_record_supported_without_inferred_cycle_merge(self):
        e=self.interrupted()
        with self.repo.connection() as db:
            for row in db.execute('select id,payload from events').fetchall():
                raw=json.loads(row['payload']);raw.pop('risk_family',None)
                db.execute('update events set payload=? where id=?',(json.dumps(raw),row['id']))
        self.service.manual_end_event(self.value(e))
        result=self.service.event_cycles()
        self.assertEqual(len(result),2)
        self.assertEqual(sum(e['manual_end']['active'] for e in result),1)

    def test_http_permission_strict_payload_and_explicit_reason(self):
        e=self.interrupted()
        with create_app(data_service=self.service).test_client() as c:
            body={'event_id':e['id']}
            self.assertEqual(c.post('/api/events/manual-end-preview',json=body).status_code,403)
            token=c.get('/api/bootstrap').json['event_management']['write_token'];headers={'X-Management-Events':token}
            self.assertEqual(c.post('/api/events/manual-end-preview',json=body,headers=headers,environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,403)
            plan=c.post('/api/events/manual-end-preview',json=body,headers=headers)
            self.assertEqual(plan.status_code,200)
            value={**body,'revision':plan.json['revision'],'reason':'','request_id':str(uuid.uuid4())}
            self.assertEqual(c.post('/api/events/manual-end',json=value,headers=headers).status_code,400)
            self.assertEqual(c.post('/api/events/manual-end',json={**value,'reason':'停用旧设备'},headers=headers).status_code,200)

    def test_parallel_close_and_storage_failure_are_atomic(self):
        e=self.interrupted();v=self.value(e)
        with self.repo.connection() as db:
            db.execute("CREATE TRIGGER fail_manual_end BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaisesRegex(ValueError,'EVENT_END_STORAGE_ERROR'):
            self.service.manual_end_event(v)
        self.assertFalse(self.current()['manual_end']['history'])
        with self.repo.connection() as db:db.execute('drop trigger fail_manual_end')
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(self.service.manual_end_event,[v,v]))
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(self.current()['manual_end']['history']),1)

    def test_operator_history_survives_retention_and_protects_delete(self):
        e=self.interrupted();self.service.manual_end_event(self.value(e))
        self.repo.event_limit=1
        self.sim.skip_windows(10,10);self.oxygen(6.4)
        self.oxygen(4.2);self.oxygen(6.4)
        history=[e for e in self.service.events() if e['manual_end']['history']]
        self.assertEqual(len(history),2)
        self.assertTrue(all(not e['deletable'] for e in history))
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'],1)

    def test_missing_metric_is_not_recovery_and_other_devices_stay_independent(self):
        self.oxygen(4.2)
        missing=self.batch()
        missing['water']['metrics']['dissolved_oxygen_mg_l'].update(
            mean=None,min=None,max=None,latest=None,valid_samples=0)
        self.service.ingest(missing)
        e=self.current()
        self.service.manual_end_event(self.value(e))
        other=self.batch(device='sim-pond-2')
        other['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2,min=2.2,max=2.2,latest=2.2)
        self.service.ingest(other)
        current=[e for e in self.service.events() if e['device_id']=='sim-pond-2' and e['code']=='OXYGEN_CRITICAL_LOW'][0]
        self.assertFalse(current['manual_end']['active'])
        self.assertTrue(self.current()['manual_end']['active'])

    def test_new_grade_retains_audit_but_new_episode_does_not_inherit_end(self):
        self.oxygen(4.2);self.now+=timedelta(seconds=95)
        self.service.manual_end_event(self.value(self.current()))
        self.sim.skip_windows(10,10);self.oxygen(2.2)
        self.assertFalse(self.current('OXYGEN_CRITICAL_LOW')['manual_end']['active'])
        self.repo.event_limit=1;self.oxygen(6.4)
        retained=self.water_events()
        self.assertEqual(len(retained),2)
        self.assertTrue(all(e['manual_end']['history'] for e in retained))
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'],0)
        self.oxygen(4.2)
        current=next(e for e in self.water_events() if e['lifecycle_state']=='ACTIVE')
        self.assertFalse(current['manual_end']['active'])
        self.assertEqual(current['manual_end']['history'],[])
