"""Approved instance composition on new isolated data; no QQ, secrets or user DBs."""
from contextlib import closing, redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.cli import main
from apps.qq_bot.configuration import load_access
from apps.qq_bot.contracts import BotError
from apps.qq_bot.monitoring_source import InstanceMonitoring, load_monitoring_config
from apps.qq_bot.offline import GROUP, MEMBER, network_blocked, packet
from apps.qq_bot.service import ReadOnlyQueries

APP_ID = '123456789'


class MonitoringSourceTests(unittest.TestCase):
    def setUp(self):
        guard=network_blocked();guard.__enter__();self.addCleanup(guard.__exit__,None,None,None)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.instance=self.root/'isolated';self.instance.mkdir()
        self.path=self.instance/'monitoring.sqlite3'
        self.writer=MonitoringRepository(self.path)
        self.now=datetime(2026,10,25,tzinfo=timezone.utc)
        self.service=MonitoringService(self.writer,device_names={'sim-pond-1':'one','sim-pond-2':'two'},clock=lambda:self.now)
        self.sim=Simulator(start=self.now,session_id='bot2b-synthetic')
        self.ingest()
        self.config_path=self.root/'source.json'
        self.config_value=dict(schema_version=1,instance_id='isolated-test',data_root=str(self.instance),devices=['sim-pond-1'])
        self.write_config()
        self.access_path=self.root/'access.json'
        self.access_path.write_text(json.dumps(dict(schema_version=1,app_id=APP_ID,groups=[dict(
            group_id=GROUP,device_id='sim-pond-1',members=[MEMBER],capabilities=['current','history','events','knowledge'])])),encoding='utf-8')
        self.access=load_access(self.access_path)
        self.seq=0

    def ingest(self,oxygen=2.2,*,lesion=False):
        batch=self.sim.advance();self.now=datetime.fromisoformat(batch['timestamp'])
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen,min=oxygen,max=oxygen,latest=oxygen)
        batch['visual']['anomaly_counts']=dict.fromkeys(batch['visual']['anomaly_counts'],0)
        batch['visual']['anomaly_counts']['suspected_lesion']=int(lesion)
        batch['visual']['behavior_ratios']=dict(normal_activity=1,reduced_activity=0,feeding=0,feeding_anomaly=0,unknown=0)
        self.service.ingest(batch)
        return batch

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config_value),encoding='utf-8')

    def source(self):
        config=load_monitoring_config(self.config_path);config.check_bindings(self.access)
        return InstanceMonitoring(config,clock=lambda:self.now)

    def adapter(self):
        return QQAdapter(self.access,ReadOnlyQueries(self.source(),None,instance_id='isolated-test'),clock=lambda:self.now)

    def send(self,adapter,text,**kwargs):
        self.seq+=1
        return adapter.receive(packet(text,self.now,msg_id='synthetic-'+str(self.seq),**kwargs),transport_app_id=APP_ID)

    def cli(self,*args):
        output=StringIO()
        with redirect_stdout(output),redirect_stderr(StringIO()):
            result=main(list(args))
        return result,output.getvalue()

    def test_all_reads_leave_database_bytes_schema_and_state_unchanged(self):
        before=self.path.read_bytes()
        adapter=self.adapter()
        for command in ('/当前水质','/历史水质 10','/历史水质 30','/历史水质 60','/当前异常'):
            self.seq=0 # fresh adapter avoids exercising the separate existing rate limit here
            result=self.send(self.adapter(),command)
            self.assertEqual(result.code,'OK',command)
            self.assertIn('SIMULATOR',result.reply.content)
            self.assertIn('isolated-test',result.reply.content)
        self.assertEqual(before,self.path.read_bytes())
        self.assertFalse((self.instance/'knowledge.sqlite3').exists())
        self.assertEqual(self.send(adapter,'/知识 溶解氧').code,'CAPABILITY_DENIED')
        self.assertEqual(self.send(adapter,'/AI 解释').code,'AI_DISABLED')

    def test_missing_stale_offline_are_unknown_not_normal(self):
        source=self.source()
        with self.writer.connection() as db:
            db.execute("DELETE FROM current WHERE channel='water'")
        text=ReadOnlyQueries(source,None,instance_id='test').current('sim-pond-1')
        self.assertIn('missing',text)
        self.now+=timedelta(minutes=5)
        result=self.send(self.adapter(),'/当前异常')
        self.assertEqual(result.code,'OK')
        self.assertIn('状态待核实',result.reply.content)
        self.assertNotIn('异常中',result.reply.content)

    def test_empty_valid_instance_does_not_seed_or_report_normal(self):
        empty=self.root/'empty';empty.mkdir();MonitoringRepository(empty/'monitoring.sqlite3')
        self.config_value['data_root']=str(empty);self.write_config()
        adapter=self.adapter()
        result=self.send(adapter,'/当前异常')
        self.assertEqual(result.code,'OK');self.assertIn('状态未知',result.reply.content)
        history=self.send(adapter,'/历史水质 10')
        self.assertIn('NO_DATA',history.reply.content)
        with closing(sqlite3.connect(empty/'monitoring.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM batches').fetchone()[0],0)

    def test_cross_device_group_and_member_denied_before_data_read(self):
        source=self.source()
        with self.assertRaisesRegex(BotError,'MONITORING_DEVICE_NOT_APPROVED'):
            source.capture_water('sim-pond-2')
        for command in ('/当前水质 sim-pond-2','/当前异常 ../other','/历史水质 10 sim-pond-2'):
            self.assertEqual(self.send(self.adapter(),command).code,'INVALID_ARGUMENTS')
        adapter=self.adapter()
        with patch.object(adapter._queries,'_capture',side_effect=AssertionError('must authorize first')):
            self.assertIsNone(self.send(adapter,'/当前水质',member='other-member').reply)
            self.assertIsNone(self.send(adapter,'/当前水质',group='other-group').reply)
        self.config_value['devices']=['sim-pond-2'];self.write_config()
        with self.assertRaisesRegex(BotError,'MONITORING_DEVICE_NOT_APPROVED'):
            load_monitoring_config(self.config_path).check_bindings(self.access)

    def test_corrupt_missing_old_schema_and_wrong_path_fail_closed(self):
        for filename,body in (('missing',None),('corrupt',b'not sqlite'),('zero',b'')):
            root=self.root/filename;root.mkdir()
            if body is not None:(root/'monitoring.sqlite3').write_bytes(body)
            self.config_value['data_root']=str(root);self.write_config()
            with self.assertRaises(BotError):self.source()
            if body is None:self.assertFalse((root/'monitoring.sqlite3').exists())
        root=self.root/'old';root.mkdir();old=root/'monitoring.sqlite3'
        with closing(sqlite3.connect(old)) as db:db.execute('PRAGMA user_version=1')
        self.config_value['data_root']=str(root);self.write_config();before=old.read_bytes()
        with self.assertRaisesRegex(BotError,'MONITORING_SCHEMA_UPGRADE_REQUIRED'):self.source()
        self.assertEqual(before,old.read_bytes())

    def test_config_rejects_fallback_relative_network_and_extra_fields(self):
        original=deepcopy(self.config_value)
        for change in ({'data_root':'outputs/demo-instance'}, {'data_root':r'\\server\share'},
                       {'devices':[]},{'devices':['sim-pond-1','sim-pond-1']},
                       {'schema_version':True},{'credential':'forbidden'},{'instance_id':'../x'}):
            self.config_value=original|change;self.write_config()
            with self.assertRaisesRegex(BotError,'INVALID_MONITORING_CONFIG'):load_monitoring_config(self.config_path)

    def test_path_links_and_file_replacement_rejected(self):
        source=self.source()
        other=self.instance/'replacement.sqlite3';MonitoringRepository(other)
        # These are both disposable synthetic databases; replacement is an attack fixture.
        self.path.rename(self.instance/'original.sqlite3');other.rename(self.path)
        with self.assertRaisesRegex(BotError,'MONITORING_DATABASE_REPLACED'):source.capture_water('sim-pond-1')
        linked=self.root/'linked';linked.mkdir()
        try:(linked/'monitoring.sqlite3').hardlink_to(self.path)
        except OSError:self.skipTest('hardlinks unavailable')
        self.config_value['data_root']=str(linked);self.write_config()
        with self.assertRaisesRegex(BotError,'MONITORING_PATH_REJECTED'):self.source()

    def test_event_row_mismatch_and_query_overflow_never_show_partial_all_clear(self):
        source=self.source()
        with self.writer.connection() as db:
            raw=json.loads(db.execute('SELECT payload FROM events LIMIT 1').fetchone()[0])
            for index in range(257):
                copy=dict(raw,id='extra-'+str(index))
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(copy['id'],copy['device_id'],copy['channel'],copy['code'],json.dumps(copy)))
        with self.assertRaisesRegex(BotError,'EVENT_QUERY_LIMIT'):source.event_cycles(device_id='sim-pond-1')
        with self.writer.connection() as db:
            db.execute("DELETE FROM events WHERE id LIKE 'extra-%'")
            raw['device_id']='sim-pond-2'
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(raw),raw['id']))
        with self.assertRaisesRegex(BotError,'MONITORING_READ_FAILED'):source.event_cycles(device_id='sim-pond-1')

    def test_static_config_check_opens_no_instance_and_no_credentials(self):
        with patch('apps.qq_bot.monitoring_source.InstanceMonitoring',side_effect=AssertionError('no instance')), \
             patch('apps.qq_bot.cli.secret_supplier',side_effect=AssertionError('no credentials')):
            result,text=self.cli('--check-config','--access-file',str(self.access_path),'--monitoring-config',str(self.config_path))
        self.assertEqual(result,0);self.assertIn('QQ_ACCESS_CONFIG_VALID',text)

    def test_explicit_preflight_no_network_no_credentials(self):
        before=self.path.read_bytes()
        with patch('apps.qq_bot.cli.secret_supplier',side_effect=AssertionError('no credentials')):
            result,text=self.cli('--check-monitoring','--access-file',str(self.access_path),'--monitoring-config',str(self.config_path))
        self.assertEqual(result,0);self.assertIn('QQ_MONITORING_READ_ONLY_READY',text)
        self.assertEqual(before,self.path.read_bytes());self.assertNotIn(str(self.instance),text)

    def test_live_assembly_uses_fake_transport_and_masks_knowledge(self):
        adapters=[]
        def factory(app,api,adapter,**kwargs):adapters.append(adapter);return Mock()
        with patch('apps.qq_bot.cli.QQAPI') as api,patch('apps.qq_bot.cli.QQGateway',side_effect=factory), \
             patch('apps.qq_bot.cli.secret_supplier',return_value=Mock()), \
             patch('apps.qq_bot.cli.importlib.util.find_spec',return_value=True):
            result,_=self.cli('--connect','--access-file',str(self.access_path),'--monitoring-config',str(self.config_path),'--confirm-qq-network')
        self.assertEqual(result,0);self.assertNotIn('knowledge',adapters[0].config.groups[0].capabilities)
        self.assertIsNone(adapters[0]._queries._knowledge);api.return_value.close.assert_called_once()

    def test_fictional_and_instance_modes_are_mutually_exclusive(self):
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit):
            main(['--connect','--access-file',str(self.access_path),'--fictional-data',
                  '--monitoring-config',str(self.config_path),'--confirm-qq-network'])

    def test_visual_recovery_uses_existing_three_clear_rule(self):
        source=self.source();self.ingest(lesion=True)
        for count in range(4):
            if count:self.ingest()
            event=next(e for e in source.event_cycles(device_id='sim-pond-1') if e['code']=='SUSPECTED_LESION')
            self.assertEqual(event['visual_recovery']['clear_count'],count)
            self.assertEqual(event['lifecycle_state'],'RESOLVED' if count==3 else 'ACTIVE')
            if count in (1,2):
                self.assertIn('恢复观察中',ReadOnlyQueries(source,None,instance_id='test').events('sim-pond-1'))

    def test_risk_cycle_level_changes_remain_one_cycle_and_do_not_write_ack(self):
        self.ingest(6.4);self.ingest(4.2);self.ingest(2.2)
        source=self.source();before=self.path.read_bytes()
        active=[e for e in source.event_cycles(device_id='sim-pond-1') if e['lifecycle_state']=='ACTIVE']
        self.assertEqual(len(active),1)
        self.assertEqual(active[0]['title'],'溶解氧低')
        self.assertEqual(active[0]['cycle_summary']['count'],2)
        self.assertEqual(before,self.path.read_bytes())

    def test_manual_end_is_preserved_not_misreported_as_rule_recovery(self):
        source=self.source();self.now+=timedelta(seconds=95)
        event=next(e for e in self.service.events() if e['code']=='OXYGEN_CRITICAL_LOW')
        preview=self.service.preview_manual_end(event['id'])
        self.service.manual_end_event(dict(event_id=event['id'],revision=preview['revision'],
            request_id=str(uuid.uuid4()),reason='隔离测试设备停止'))
        event=next(e for e in source.event_cycles(device_id='sim-pond-1') if e['code']=='OXYGEN_CRITICAL_LOW')
        self.assertTrue(event['manual_end']['active'])
        self.assertEqual(event['lifecycle_state'],'INDETERMINATE')
        text=ReadOnlyQueries(source,None,instance_id='test').events('sim-pond-1')
        self.assertIn('人工结束不代表规则恢复',text)
        self.assertIn('状态未知',text)

    def test_other_device_invalid_payload_is_not_read_or_projected(self):
        source=self.source()
        with self.writer.connection() as db:
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',('foreign-device','sim-pond-2','water','OXYGEN_LOW','not JSON'))
        self.assertTrue(source.event_cycles(device_id='sim-pond-1'))

    def test_large_payload_and_family_budget_fail_without_partial_projection(self):
        source=self.source()
        with self.writer.connection() as db:
            event=json.loads(db.execute('SELECT payload FROM events LIMIT 1').fetchone()[0])
            enlarged=dict(event,padding='x'*65536)
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(enlarged),event['id']))
        with self.assertRaisesRegex(BotError,'EVENT_QUERY_LIMIT'):source.event_cycles(device_id='sim-pond-1')
        with self.writer.connection() as db:
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(event),event['id']))
            for index in range(16):
                copy=dict(event,id='same-family-'+str(index))
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(copy['id'],copy['device_id'],copy['channel'],copy['code'],json.dumps(copy)))
        with self.assertRaisesRegex(BotError,'EVENT_QUERY_LIMIT'):source.event_cycles(device_id='sim-pond-1')

        # Legacy inference must not create a quadratic family-members projection.
        with self.writer.connection() as db:
            for row in db.execute('SELECT id,payload FROM events').fetchall():
                legacy=json.loads(row['payload']);legacy.pop('risk_family',None)
                db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(legacy),row['id']))
        with self.assertRaisesRegex(BotError,'EVENT_QUERY_LIMIT'):source.event_cycles(device_id='sim-pond-1')

    def test_new_session_missing_channel_does_not_refresh_old_observation(self):
        source=self.source()
        batch=self.sim.advance();self.now=datetime.fromisoformat(batch['timestamp'])
        batch['session_id']='new-session';batch['batch_id']='new-session-first';batch['water']=None
        self.service.ingest(batch)
        self.now+=timedelta(seconds=95)
        text=ReadOnlyQueries(source,None,instance_id='test').current('sim-pond-1')
        self.assertIn('offline',text)
        self.assertIn('2026-10-25T00:00:10',text)
        event=next(e for e in source.event_cycles(device_id='sim-pond-1') if e['code']=='OXYGEN_CRITICAL_LOW')
        self.assertEqual(event['lifecycle_state'],'INDETERMINATE')

    def test_failure_is_safe_and_duplicate_does_not_repeat_read(self):
        adapter=self.adapter();raw=packet('/当前水质',self.now)
        with patch.object(adapter._queries,'_capture',side_effect=BotError('MONITORING_READ_FAILED')) as read:
            first=adapter.receive(raw,transport_app_id=APP_ID)
            second=adapter.receive(raw,transport_app_id=APP_ID)
        self.assertEqual(first.code,'MONITORING_READ_FAILED');self.assertIsNone(first.reply)
        self.assertEqual(second.code,'DUPLICATE');read.assert_called_once()


if __name__ == '__main__':
    unittest.main()
