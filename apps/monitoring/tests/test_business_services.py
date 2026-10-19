"""Pure services and transaction integration: no model or external network."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from apps.monitoring.diagnosis import DiagnosisService
from apps.simulator.generator import Simulator
from apps.monitoring.analysis import DomainAnalysisService
from apps.monitoring.events import EventService
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.rules import assess_channel
from apps.monitoring.service import MonitoringService
from apps.management_web.app import create_app


class BusinessServiceTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect','socket.socket.connect_ex','socket.socket.sendto','socket.getaddrinfo'):
            guard=patch(target,side_effect=AssertionError('offline business services'))
            guard.start();self.addCleanup(guard.stop)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.repo=MonitoringRepository(Path(temp.name)/'test.sqlite3')
        self.now=datetime(2026,10,15,tzinfo=timezone.utc)
        self.sim=Simulator(start=self.now,session_id='services')
        self.service=MonitoringService(self.repo,clock=lambda:self.now)

    def batch(self,oxygen=2.2):
        b=self.sim.advance();self.now=datetime.fromisoformat(b['timestamp'])
        b['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen,min=oxygen,max=oxygen,latest=oxygen)
        b['visual']['anomaly_counts']=dict.fromkeys(b['visual']['anomaly_counts'],0)
        b['visual']['behavior_ratios']=dict(normal_activity=1,reduced_activity=0,feeding=0,feeding_anomaly=0,unknown=0)
        return b

    def test_one_analysis_entry_matches_rules_web_and_future_consumer(self):
        self.service.ingest(self.batch())
        row=self.repo.read('sim-pond-1','water')
        expected=assess_channel('sim-pond-1','water',row,evaluated_at=self.now,
            freshness='fresh',connectivity='online',diagnosis=DiagnosisService())
        before=deepcopy(row)
        self.assertEqual(self.service.analysis('sim-pond-1'),expected)
        self.assertEqual(self.service.snapshot('sim-pond-1').analysis,expected.to_dict())
        public=create_app(data_service=self.service).test_client().get('/api/bootstrap').get_json()
        self.assertEqual(public['monitoring']['analysis'],create_app(data_service=self.service).test_client().get('/api/monitoring').get_json()['analysis'])
        self.assertEqual(row,before)
        self.assertEqual(self.service.cameras()[0]['analysis'],self.service.analysis('sim-pond-1','visual').to_dict())
        context=self.service.bind('sim-pond-1')
        self.assertEqual(context.analysis(),expected)
        self.assertEqual(context.analysis('visual'),self.service.analysis('sim-pond-1','visual'))

    def test_diagnosis_not_recomputed_for_state_projection(self):
        self.service.ingest(self.batch())
        with patch.object(self.service.diagnosis,'diagnose',wraps=self.service.diagnosis.diagnose) as calc:
            self.service.snapshot('sim-pond-1');self.assertEqual(calc.call_count,1)
        with patch.object(self.service.domain_analysis,'evaluate',wraps=self.service.domain_analysis.evaluate) as calc:
            self.service.events();self.assertEqual(calc.call_count,1)

    def test_pure_event_transition_does_not_mutate_inputs_and_query_cannot_resolve(self):
        b=self.batch();self.service.ingest(b)
        event=self.repo.events()[0];existing={event['code']:event};before=deepcopy(existing)
        a=self.service.analysis('sim-pond-1')
        result=EventService().transition(existing,a,id_factory=lambda:'fixed-new-id')
        self.assertEqual(len(result.updates),1);self.assertEqual(result.inserts,())
        self.assertEqual(existing,before)
        result.updates[0]['rule_identity']['scope']=[]
        self.assertTrue(event['rule_identity']['scope'])
        b=self.batch(6.4)
        row={'device_id':b['device_id'],'batch_id':b['batch_id'],'observed_at':b['timestamp'],
             'received_at':b['timestamp'],'payload':{'window':b['window'],'data':b['water']}}
        clear=self.service.domain_analysis.evaluate('sim-pond-1','water',row,evaluated_at=self.now)
        read=EventService().project(event,clear)
        self.assertEqual(read['lifecycle_state'],'INDETERMINATE');self.assertNotIn('resolved_at',read)
        changes=EventService().transition(existing,clear)
        self.assertEqual(changes.updates[0]['lifecycle_state'],'RESOLVED')
        self.assertEqual(changes.resolved_codes,(event['code'],))

    def test_event_failure_after_water_update_rolls_back_every_table(self):
        initial=self.batch();self.service.ingest(initial)
        tables=('batches','history','current','events','alerts','channel_contacts')
        def capture():
            with self.repo.connection() as db:
                return {name:[tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in tables}
        before=capture();b=self.batch(2.2)
        original=self.repo.event_service.transition
        def fail_visual(existing,assessment,**kwargs):
            if assessment.channel=='visual':raise RuntimeError('injected offline failure')
            return original(existing,assessment,**kwargs)
        with patch.object(self.repo.event_service,'transition',side_effect=fail_visual):
            with self.assertRaises(RuntimeError):self.service.ingest(b)
        self.assertEqual(capture(),before)

    def test_duplicate_and_out_of_order_never_execute_event_transition(self):
        old=self.batch();new=self.batch();self.service.ingest(new)
        with patch.object(self.repo.event_service,'transition',side_effect=AssertionError('not an event update')):
            self.assertEqual(self.service.ingest(new)['status'],'duplicate')
            self.assertEqual(self.service.ingest(old)['status'],'out_of_order')

    def test_device_channel_and_evaluation_time_boundaries(self):
        self.service.ingest(self.batch());row=self.repo.read('sim-pond-1','water')
        domain=DomainAnalysisService()
        with self.assertRaises(ValueError):domain.evaluate('other-device','water',row,evaluated_at=self.now)
        with self.assertRaises(ValueError):domain.evaluate('sim-pond-1','water',row,evaluated_at=self.now-timedelta(seconds=1))
        with self.assertRaises(ValueError):domain.evaluate('sim-pond-1','water',row,evaluated_at=self.now.replace(tzinfo=None))
        event=self.repo.events()[0];other=deepcopy(event);other['device_id']='other-device'
        a=self.service.analysis('sim-pond-1')
        with self.assertRaises(ValueError):EventService().transition({other['code']:other},a)
        with self.assertRaises(ValueError):EventService().project(other,a)
        with self.assertRaises(ValueError):self.service.analysis('sim-pond-1','unknown')

    def test_capture_clock_follows_read_and_independent_windows_are_preserved(self):
        first=self.batch();self.service.ingest(first)
        next_batch=self.batch();next_batch['water']=None;self.service.ingest(next_batch)
        water=self.service.analysis('sim-pond-1');visual=self.service.analysis('sim-pond-1','visual')
        self.assertNotEqual(water.observation.window_end,visual.observation.window_end)
        original=self.repo.capture
        def read_and_move_clock(*args):
            value=original(*args);self.now+=timedelta(seconds=31);return value
        with patch.object(self.repo,'capture',side_effect=read_and_move_clock):
            snapshot=self.service.snapshot('sim-pond-1')
        self.assertEqual(snapshot.freshness,'stale')
        self.assertEqual(snapshot.evaluated_at,self.now.isoformat())


if __name__=='__main__':unittest.main()
