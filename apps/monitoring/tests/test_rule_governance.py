"""Offline governance contracts, per-metric scope and reliable event transitions."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from fishery_ai.domain import DiagnosisService
from apps.simulator.generator import Simulator, summarize_visual_frames
from apps.monitoring.contracts import FindingState, RuleIdentity, DataQuality
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.rules import assess_channel
from apps.management_web.app import create_app


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect','socket.socket.connect_ex','socket.socket.sendto','socket.getaddrinfo'):
            guard=patch(target,side_effect=AssertionError('offline governance'))
            guard.start();self.addCleanup(guard.stop)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'monitoring.sqlite3'
        self.repo=MonitoringRepository(self.path)
        self.now=datetime(2026,10,15,tzinfo=timezone.utc)
        self.sim=Simulator(start=self.now,session_id='governance')
        self.service=MonitoringService(self.repo,clock=lambda:self.now)

    def batch(self, oxygen=6.4):
        b=self.sim.advance();self.now=datetime.fromisoformat(b['timestamp'])
        self.set_metric(b,'dissolved_oxygen_mg_l',oxygen)
        # Make deterministic absence of visual signal, independent of random frames.
        b['visual']['anomaly_counts']=dict.fromkeys(b['visual']['anomaly_counts'],0)
        b['visual']['behavior_ratios']=dict(normal_activity=1,reduced_activity=0,feeding=0,feeding_anomaly=0,unknown=0)
        return b

    def set_metric(self,b,key,value,valid=10,invalid=0):
        b['water']['metrics'][key].update(mean=value,min=value,max=value,latest=value,
                                        valid_samples=valid,invalid_samples=invalid)

    def find(self,analysis,code):
        return next(f for f in analysis['findings'] if f['code']==code)

    def event(self,code='OXYGEN_CRITICAL_LOW'):
        return next(e for e in self.service.events() if e['code']==code and not e.get('superseded_by'))

    def test_valid_no_data_and_prototype_identity(self):
        empty=self.service.snapshot('sim-pond-1').analysis
        self.assertEqual(empty['status'],'NO_DATA');self.assertIsNone(empty['observation'])
        self.assertEqual(self.find(empty,'OXYGEN_LOW')['state'],'NOT_EVALUATED')
        b=self.batch(2.2);self.service.ingest(b)
        a=self.service.snapshot('sim-pond-1').analysis
        hit=self.find(a,'OXYGEN_CRITICAL_LOW')
        self.assertEqual(hit['state'],'HIT');self.assertEqual(hit['severity'],'critical')
        self.assertEqual(hit['rule']['publication_status'],'PROTOTYPE')
        self.assertEqual(hit['rule_version'],DiagnosisService.RULE_VERSION)
        self.assertEqual(hit['observation']['batch_id'],b['batch_id'])
        self.assertEqual(a['data_quality']['quality'],'valid')
        json.dumps(a,allow_nan=False)
        with self.assertRaises(ValueError):RuleIdentity('x','v1',('simulator',),'APPROVED')

    def test_invalid_metric_cannot_generate_risk_but_other_valid_metric_can(self):
        b=self.batch(2.2)
        self.set_metric(b,'temperature_c',34,valid=9,invalid=1)
        self.service.ingest(b)
        a=self.service.snapshot('sim-pond-1').analysis
        self.assertEqual(a['data_quality']['quality'],'invalid')
        self.assertEqual(self.find(a,'TEMP_CRITICAL_HIGH')['state'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(self.find(a,'OXYGEN_CRITICAL_LOW')['state'],'HIT')
        reader=self.service.bind('sim-pond-1').water_reader.query().reading
        self.assertIsNone(reader.temperature_c)
        self.assertNotIn('TEMP_CRITICAL_HIGH',[e['code'] for e in self.service.events()])

    def test_partial_coverage_is_not_complete_risk_or_normal_evidence(self):
        b=self.batch(2.2);self.set_metric(b,'ph',None,valid=0)
        self.service.ingest(b)
        a=self.service.snapshot('sim-pond-1').analysis
        self.assertEqual(a['data_quality']['quality'],'partial')
        self.assertEqual(self.find(a,'PH_LOW')['state'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(self.find(a,'OXYGEN_CRITICAL_LOW')['state'],'HIT')
        b=self.batch(2.2);self.set_metric(b,'dissolved_oxygen_mg_l',2.2,valid=4)
        self.service.ingest(b)
        a=self.service.snapshot('sim-pond-1').analysis
        self.assertEqual(self.find(a,'OXYGEN_CRITICAL_LOW')['state'],'INSUFFICIENT_EVIDENCE')
        trend=self.service.snapshot('sim-pond-1').trend[-1]
        self.assertIsNone(trend['dissolved_oxygen_mg_l'])
        self.assertEqual(trend['metric_quality']['dissolved_oxygen_mg_l'],'partial')
        self.assertEqual(self.event()['lifecycle_state'],'INDETERMINATE')

    def test_persistent_low_oxygen_missing_indeterminate_then_reliable_recovery(self):
        self.service.ingest(self.batch(2.2));first=self.event()
        second=self.batch(2.2);self.service.ingest(second);self.assertEqual(self.event()['id'],first['id'])
        b=self.batch();self.set_metric(b,'dissolved_oxygen_mg_l',None,valid=0)
        self.service.ingest(b);event=self.event()
        self.assertEqual(event['lifecycle_state'],'INDETERMINATE');self.assertNotIn('resolved_at',event)
        self.assertEqual(event['last_batch_id'],second['batch_id'])
        self.assertEqual(event['state_observation']['batch_id'],b['batch_id'])
        self.service.ingest(self.batch(2.2));self.assertEqual(self.event()['lifecycle_state'],'ACTIVE')
        b=self.batch(6.4);self.service.ingest(b)
        event=self.event();self.assertEqual(event['lifecycle_state'],'RESOLVED')
        self.assertEqual(event['status'],'closed');self.assertEqual(event['resolution_batch_id'],b['batch_id'])

    def test_stale_offline_queries_withdraw_certainty_without_database_mutation(self):
        self.service.ingest(self.batch(2.2));stored=self.repo.events();current=self.repo.read('sim-pond-1','water')
        self.now+=timedelta(seconds=31)
        a=self.service.snapshot('sim-pond-1').analysis
        self.assertEqual(self.find(a,'OXYGEN_CRITICAL_LOW')['state'],'NOT_EVALUATED')
        self.assertEqual(self.find(a,'SENSOR_STALE')['state'],'HIT')
        self.assertEqual(self.event()['lifecycle_state'],'INDETERMINATE')
        self.now+=timedelta(seconds=60)
        self.assertEqual(self.find(self.service.snapshot('sim-pond-1').analysis,'DEVICE_OFFLINE')['state'],'HIT')
        self.assertEqual(self.repo.events(),stored);self.assertEqual(self.repo.read('sim-pond-1','water'),current)

    def test_stale_recovery_window_does_not_resolve_old_abnormality(self):
        self.service.ingest(self.batch(2.2))
        b=self.batch(6.4);self.now+=timedelta(seconds=31);self.service.ingest(b)
        self.assertEqual(self.event()['lifecycle_state'],'INDETERMINATE')
        self.assertNotIn('resolved_at',self.event())

    def test_visual_signal_partial_absence_is_not_disease_or_recovery(self):
        b=self.batch();b['visual']['anomaly_counts']['suspected_lesion']=1
        self.service.ingest(b)
        event=self.event('SUSPECTED_LESION')
        self.assertEqual(event['lifecycle_state'],'ACTIVE');self.assertIn('非诊断',event['title'])
        b=self.batch();b['visual']['valid_frames']=1
        self.service.ingest(b)
        self.assertEqual(self.event('SUSPECTED_LESION')['lifecycle_state'],'INDETERMINATE')
        b=self.batch();b['visual']=summarize_visual_frames([None,None])
        self.service.ingest(b)
        self.assertEqual(self.event('SUSPECTED_LESION')['lifecycle_state'],'INDETERMINATE')
        b=self.batch();self.service.ingest(b)
        self.assertEqual(self.event('SUSPECTED_LESION')['lifecycle_state'],'RESOLVED')

    def test_partial_visual_positive_is_limited_confirmed_signal(self):
        b=self.batch();b['visual']['valid_frames']=1;b['visual']['anomaly_counts']['suspected_lesion']=1
        self.service.ingest(b)
        a=self.service.cameras()[0]['analysis'];f=self.find(a,'SUSPECTED_LESION')
        self.assertEqual(f['state'],'HIT');self.assertEqual(a['data_quality']['quality'],'partial')
        self.assertEqual(f['kind'],'VISUAL_SIGNAL');self.assertNotIn('diagnosis',f)

    def test_versions_never_silently_merge_and_critical_severity_preserved(self):
        self.service.ingest(self.batch(2.2));old=self.event()
        self.assertEqual(old['severity'],'critical');self.assertEqual(old['finding_severity'],'critical')
        class NextRules(DiagnosisService):RULE_VERSION='test-next-rule-version'
        self.service.diagnosis=NextRules()
        self.service.ingest(self.batch(2.2))
        new=self.event();self.assertNotEqual(new['id'],old['id'])
        prior=next(e for e in self.service.events() if e['id']==old['id'])
        self.assertEqual(prior['lifecycle_state'],'INDETERMINATE');self.assertNotIn('resolved_at',prior)
        self.assertEqual(prior['superseded_by'],new['id'])
        self.assertEqual(new['rule_version'],'test-next-rule-version')
        self.service.ingest(self.batch(2.2));self.assertEqual(self.event()['id'],new['id'])

    def test_channel_missing_and_different_windows_keep_independent_references(self):
        b=self.batch(2.2);self.service.ingest(b);water_batch=b['batch_id']
        b=self.batch();b['water']=None;self.service.ingest(b)
        water=self.service.snapshot('sim-pond-1').analysis;visual=self.service.cameras()[0]['analysis']
        self.assertEqual(water['observation']['batch_id'],water_batch)
        self.assertNotEqual(water['observation']['window_end'],visual['observation']['window_end'])
        empty=MonitoringService(self.repo,device_names={'sim-pond-2':'B'},clock=lambda:self.now)
        self.assertEqual(empty.snapshot('sim-pond-2').analysis['status'],'NO_DATA')
        self.assertEqual(empty.cameras()[0]['analysis']['status'],'NO_DATA')

    def test_legacy_records_not_rewritten_on_read_and_new_evidence_can_resolve(self):
        self.service.ingest(self.batch(2.2));event=self.event()
        with self.repo.connection() as db:
            raw=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(event['id'],)).fetchone()[0])
            for key in ('lifecycle_state','publication_status','rule_identity','observation'):raw.pop(key,None)
            raw['severity']='warning'
            original=json.dumps(raw);db.execute('UPDATE events SET payload=? WHERE id=?',(original,event['id']))
        read=self.event();self.assertEqual(read['lifecycle_state'],'INDETERMINATE')
        self.assertEqual(read['severity'],'critical');self.assertEqual(read['publication_status'],'PROTOTYPE')
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM events WHERE id=?',(event['id'],)).fetchone()[0],original)
        reopened=MonitoringService(MonitoringRepository(self.path),clock=lambda:self.now)
        self.assertEqual(reopened.events()[0]['id'],event['id'])
        self.service.ingest(self.batch(6.4));self.assertEqual(self.event()['lifecycle_state'],'RESOLVED')

    def test_analysis_contract_web_history_and_legacy_filters(self):
        self.service.ingest(self.batch(2.2));client=create_app(data_service=self.service).test_client()
        payload=client.get('/api/bootstrap').get_json()
        self.assertEqual(payload['monitoring']['analysis']['schema_version'],1)
        self.assertEqual(payload['cameras'][0]['analysis']['observation']['channel'],'visual')
        self.assertEqual(client.get('/api/events?status=ACTIVE').get_json()['items'][0]['severity'],'critical')
        self.assertEqual(len(client.get('/api/events?status=pending').get_json()['items']),1)
        history=client.get('/api/monitoring/history').get_json()['items']
        self.assertEqual(history[0]['summary']['metrics']['dissolved_oxygen_mg_l']['mean'],2.2)
        self.assertEqual(client.post('/api/ai/messages',json={}).status_code,503)
        result=self.service.snapshot('sim-pond-1').analysis
        result['findings'][0]['rule']['scope']=[]
        self.assertTrue(self.service.snapshot('sim-pond-1').analysis['findings'][0]['rule']['scope'])

    def test_pure_assessment_contract_rejects_scope_mismatch(self):
        b=self.batch();self.service.ingest(b)
        row=self.repo.read('sim-pond-1','water')
        a=assess_channel('sim-pond-1','water',row,evaluated_at=self.now,freshness='fresh',connectivity='online',diagnosis=DiagnosisService())
        with self.assertRaises(ValueError):replace(a,device_id='other')
        with self.assertRaises(ValueError):replace(a.findings[0],severity='critical',state=FindingState.CLEAR)
        with self.assertRaises(ValueError):replace(a.observation,window_duration_s=True)
        with self.assertRaises(ValueError):DataQuality('valid','fresh','online',(('ph',True,10),))
        with self.assertRaises(ValueError):replace(a,evaluated_at='2026-10-15T00:00:00')
        with self.assertRaises(ValueError):assess_channel('sim-pond-1','other',row,evaluated_at=self.now,freshness='fresh',connectivity='online',diagnosis=DiagnosisService())
        json.dumps(a.to_dict(),allow_nan=False)

    def test_rule_change_clear_evidence_cannot_resolve_old_version(self):
        self.service.ingest(self.batch(2.2));old=self.event()
        class NextRules(DiagnosisService):RULE_VERSION='changed-normal-contract'
        self.service.diagnosis=NextRules();self.service.ingest(self.batch(6.4))
        event=self.event();self.assertEqual(event['id'],old['id'])
        self.assertEqual(event['lifecycle_state'],'INDETERMINATE');self.assertNotIn('resolved_at',event)

    def test_different_staleness_and_connectivity_are_not_collapsed(self):
        self.service.ingest(self.batch(2.2));row=self.repo.read('sim-pond-1','water')
        a=assess_channel('sim-pond-1','water',row,evaluated_at=self.now,
            freshness='fresh',connectivity='offline',diagnosis=DiagnosisService()).to_dict()
        self.assertEqual(a['data_quality']['freshness'],'fresh')
        self.assertEqual(self.find(a,'OXYGEN_CRITICAL_LOW')['state'],'NOT_EVALUATED')

    def test_governance_policy_change_also_prevents_merging_or_recovery(self):
        self.service.ingest(self.batch(2.2));old=self.event()
        from apps.monitoring import rules
        original=rules.rule_identity
        def changed(code,channel,diagnosis):
            return replace(original(code,channel,diagnosis),assessment_policy_version='test-policy-v2')
        with patch.object(rules,'rule_identity',side_effect=changed):
            self.service.ingest(self.batch(2.2));new=self.event()
        self.assertNotEqual(new['id'],old['id'])
        stored=next(e for e in self.repo.events() if e['id']==old['id'])
        self.assertEqual(stored['lifecycle_state'],'INDETERMINATE');self.assertNotIn('resolved_at',stored)

    def test_entire_missing_and_invalid_windows_do_not_resolve(self):
        self.service.ingest(self.batch(2.2))
        for invalid in (0,10):
            b=self.batch()
            for key in b['water']['metrics']:self.set_metric(b,key,None,valid=0,invalid=invalid)
            self.service.ingest(b)
            self.assertEqual(self.event()['lifecycle_state'],'INDETERMINATE')
            self.assertEqual(self.service.snapshot('sim-pond-1').quality,'invalid' if invalid else 'missing')
            self.assertIsNotNone(self.service.bind('sim-pond-1').water_reader.query())

    def test_risk_severity_code_change_is_not_environment_recovery(self):
        self.service.ingest(self.batch(2.2));old=self.event()
        self.service.ingest(self.batch(.5))
        prior=self.event();self.assertEqual(prior['id'],old['id'])
        self.assertEqual(prior['lifecycle_state'],'INDETERMINATE')
        self.assertEqual(prior['state_reason'],'OTHER_RISK_CONDITION_ACTIVE')
        self.assertEqual(self.event('OXYGEN_CRITICAL_EXTREME')['lifecycle_state'],'ACTIVE')
        self.service.ingest(self.batch(4))
        self.assertEqual(self.event()['lifecycle_state'],'INDETERMINATE')
        self.assertEqual(self.event('OXYGEN_LOW')['severity'],'warning')
        self.service.ingest(self.batch(6.4))
        self.assertTrue(all(e['lifecycle_state']=='RESOLVED' for e in self.service.events()))


if __name__=='__main__':unittest.main()
