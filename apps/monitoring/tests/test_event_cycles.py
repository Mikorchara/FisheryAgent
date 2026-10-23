"""SIMPLIFY-1 projection and whole-store cycle queries, isolated fixtures only."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from apps.management_web.app import create_app
from apps.monitoring.event_cycles import summarize_cycles
from apps.monitoring.tests import test_event_lifecycle as lifecycle
from apps.monitoring.tests import test_event_management as management


class EventCycleTests(unittest.TestCase):
    setUp = lifecycle.VisualLifecycleTests.setUp
    batch = lifecycle.VisualLifecycleTests.batch
    oxygen = management.EventManagementTests.oxygen
    water_events = management.EventManagementTests.water_events

    def test_upgrade_ack_recovery_keeps_originals_and_one_summary(self):
        self.oxygen(4.2)
        first = self.water_events()[0]
        self.oxygen(2.2)
        current = next(e for e in self.water_events() if e['lifecycle_state']=='ACTIVE')
        h = current['handling']
        self.service.acknowledge_event(dict(event_id=current['id'],cycle_id=h['cycle_id'],
            grade_token=h['grade_token'],grade_version=h['grade_version'],revision=h['revision'],
            request_id='187120ce-e51d-40bc-8369-0a7527789d40'))
        active = self.service.event_cycles()
        self.assertEqual(len(active),1)
        self.assertEqual(active[0]['id'],current['id'])
        self.assertEqual(active[0]['occurred_at'],first['occurred_at'])
        self.assertEqual(active[0]['cycle_summary']['count'],2)
        self.assertEqual(active[0]['handling']['state'],'ACKNOWLEDGED')
        self.oxygen(6.4)
        with self.repo.connection() as db:
            before = list(db.execute('SELECT payload FROM events ORDER BY id'))
        result = self.service.event_cycles()[0]
        self.assertEqual(result['lifecycle_state'],'RESOLVED')
        self.assertEqual(result['severity'],'critical')
        self.assertEqual(result['resolved_at'],self.now.isoformat())
        self.assertEqual(result['cycle_summary']['reading_label'],'异常时读数')
        self.assertEqual(result['handling']['action_count'],1)
        self.assertFalse(result['deletable'])
        self.assertEqual(result['deletion_block_reason'],'ACK_AUDIT_RETAINED')
        retained=[e for e in self.service.events() if e['code']=='OXYGEN_LOW']
        self.assertEqual(summarize_cycles(retained)[0]['severity'],'critical')
        with self.repo.connection() as db:
            self.assertEqual([tuple(r) for r in before],[tuple(r) for r in db.execute('SELECT payload FROM events ORDER BY id')])
        self.oxygen(4.2)
        self.assertEqual(len(self.service.event_cycles()),2)

    def test_unknown_old_records_devices_and_rule_identities_do_not_merge(self):
        self.oxygen(4.2); self.oxygen(2.2)
        self.now += timedelta(seconds=95)
        summary=self.service.event_cycles()[0]
        self.assertEqual(summary['lifecycle_state'],'INDETERMINATE')
        self.assertEqual(summary['severity'],'unknown')
        records=self.service.events()
        for e in records:
            e.pop('risk_family',None)
        self.assertEqual(len(summarize_cycles(records)),2)
        e=deepcopy(records[0]); e['id']='separate-device'; e['device_id']='sim-pond-2'
        self.assertEqual(len(summarize_cycles(records+[e])),3)
        old=deepcopy(records[0]);old.pop('rule_identity',None)
        old.update(status='closed',legacy_closed=True,lifecycle_state='INDETERMINATE',state_reason='LEGACY_UNREVIEWED')
        old_summary=summarize_cycles([old])[0]
        self.assertTrue(old_summary['legacy_closed'])
        self.assertEqual(old_summary['lifecycle_state'],'INDETERMINATE')
        self.assertEqual(old_summary['status'],'closed')

    def test_visual_recovery_keeps_active_until_third_clear(self):
        lifecycle.VisualLifecycleTests.ingest(self,'suspected_lesion')
        for count in range(1,4):
            lifecycle.VisualLifecycleTests.ingest(self)
            summary=next(e for e in self.service.event_cycles() if e['code']=='SUSPECTED_LESION')
            self.assertEqual(summary['lifecycle_state'],'ACTIVE' if count<3 else 'RESOLVED')
            self.assertEqual(summary['visual_recovery']['clear_count'],count)

    def test_full_store_grouping_precedes_combined_filtering_and_pagination(self):
        for _ in range(27):
            self.oxygen(4.2); self.oxygen(2.2); self.oxygen(6.4)
        self.assertEqual(len(self.service.events()),54)
        result=self.service.query_event_cycles(q='OXYGEN_LOW',severity='critical',status='RESOLVED',limit=5,offset=25)
        self.assertEqual((result['total'],len(result['items'])),(27,2))
        for minutes in (5,10,30,60):
            result=self.service.query_event_cycles(lookback_minutes=minutes)
            expected=[e for e in self.service.event_cycles() if datetime.fromisoformat(e['resolved_at'])>=self.now-timedelta(minutes=minutes)]
            self.assertEqual(result['total'],len(expected))

    def test_bootstrap_and_opt_in_http_view_keep_original_detail_and_ack(self):
        self.oxygen(4.2); self.oxygen(2.2)
        with create_app(data_service=self.service).test_client() as client:
            data=client.get('/api/bootstrap').json
            self.assertEqual((len(data['events']),len(data['event_cycles'])),(2,1))
            self.assertEqual(client.get('/api/events').json['total'],2)
            grouped=client.get('/api/events?view=cycles').json
            self.assertEqual(grouped['total'],1)
            event=client.get('/api/events/'+grouped['items'][0]['id']).json
            self.assertNotIn('cycle_summary',event)
            self.assertTrue(event['handling']['can_ack'])
            self.assertEqual(client.get('/api/events?view=bogus').status_code,400)
