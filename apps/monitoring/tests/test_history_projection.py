"""Read-only history projection: ordering, session boundaries and legacy metadata."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import socket
import unittest
from unittest.mock import patch
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.management_web.app import create_app
from apps.simulator.generator import Simulator

class HistoryProjectionTests(unittest.TestCase):
    def setUp(self):
        for method in ('connect','connect_ex','sendto'):
            guard=patch.object(socket.socket,method,side_effect=AssertionError('network forbidden'))
            guard.start();self.addCleanup(guard.stop)
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.start=datetime(2026,10,14,tzinfo=timezone.utc);self.now=self.start
        self.repo=MonitoringRepository(Path(temp.name)/'history.sqlite3')
        self.service=MonitoringService(self.repo,device_names={'pond-a':'A','pond-b':'B'},clock=lambda:self.now)
        self.client=create_app(data_service=self.service).test_client()

    def ingest(self,batch):
        self.now=max(self.now,datetime.fromisoformat(batch['timestamp'])+timedelta(seconds=1))
        return self.service.ingest(batch)

    def test_restarts_and_out_of_order_api_are_device_channel_sorted_and_preserve_times(self):
        first=Simulator(start=self.start,device_id='pond-a',session_id='first')
        a,b=first.advance(),first.advance()
        self.ingest(b);self.ingest(a)
        restarted=Simulator(start=self.start+timedelta(seconds=90),device_id='pond-a',session_id='restarted').advance()
        self.ingest(restarted)
        other=Simulator(start=self.start+timedelta(seconds=90),device_id='pond-b',session_id='other').advance()
        self.ingest(other)
        before=[dict(r) for r in self.repo.history('pond-a','water')]
        trend=self.client.get('/api/monitoring?device=pond-a').get_json()['trend']
        api=self.client.get('/api/monitoring/history?device=pond-a&channel=water').get_json()['items']
        self.assertEqual([r['batch_id'] for r in trend],[a['batch_id'],b['batch_id'],restarted['batch_id']])
        self.assertEqual([r['session_id'] for r in trend],['first','first','restarted'])
        self.assertEqual([r['batch_id'] for r in api],[r['batch_id'] for r in trend])
        for item,raw in zip(trend,api):
            self.assertEqual(item['observed_at'],raw['observed_at'])
            self.assertEqual(item['received_at'],raw['received_at'])
            self.assertEqual(item['window_start'],raw['window']['start'])
            self.assertEqual(item['window_duration_s'],10)
            self.assertEqual(item['session_id'],raw['session_id'])
            self.assertEqual(raw['device_id'],'pond-a');self.assertEqual(raw['channel'],'water')
        self.assertEqual(before,self.repo.history('pond-a','water'))
        self.assertEqual(self.client.get('/api/monitoring/history?device=pond-b').get_json()['items'][0]['batch_id'],other['batch_id'])

    def test_late_same_time_records_remain_in_storage_with_deterministic_received_order(self):
        sim=Simulator(start=self.start,device_id='pond-a',session_id='main')
        first,second=sim.advance(),sim.advance();self.ingest(first);self.ingest(second)
        late=deepcopy(first);late.update(batch_id='late',session_id='late')
        late['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=None,min=None,max=None,latest=None,valid_samples=0)
        self.now+=timedelta(seconds=1);self.assertEqual(self.ingest(late)['status'],'out_of_order')
        trend=self.client.get('/api/monitoring?device=pond-a').get_json()['trend']
        self.assertEqual([r['batch_id'] for r in trend],[first['batch_id'],'late',second['batch_id']])
        self.assertEqual(trend[0]['observed_at'],trend[1]['observed_at'])
        self.assertIsNone(trend[1]['dissolved_oxygen_mg_l'])
        self.assertEqual(len(self.repo.history('pond-a','water')),3)
        self.assertEqual(self.repo.read('pond-a','water')['batch_id'],second['batch_id'])

    def test_pruned_batch_session_is_optional_and_does_not_remove_history(self):
        self.repo.batch_limit=1
        sim=Simulator(start=self.start,device_id='pond-a',session_id='main')
        self.ingest(sim.advance());self.ingest(sim.advance())
        trend=self.client.get('/api/monitoring?device=pond-a').get_json()['trend']
        self.assertEqual(len(trend),2);self.assertIsNone(trend[0]['session_id'])
        self.assertEqual(trend[1]['session_id'],'main')
        self.assertTrue(all(r['window_start'] for r in trend))
