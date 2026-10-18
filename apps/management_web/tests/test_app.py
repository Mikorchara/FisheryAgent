"""Offline R1 API and independent-startup tests. Never assemble the AI Runtime."""
import json
import socket
import unittest
from unittest.mock import patch

from apps.management_web.app import create_app
from apps.management_web.services import DemoMonitoring


class ManagementTests(unittest.TestCase):
    def setUp(self):
        knowledge=patch('apps.management_web.__main__.knowledge_content')
        self.knowledge_factory=knowledge.start();self.addCleanup(knowledge.stop)
        for name in ("connect", "connect_ex", "sendto"):
            guard=patch.object(socket.socket,name,side_effect=AssertionError("network disabled"))
            guard.start();self.addCleanup(guard.stop)
        self.app=create_app();self.client=self.app.test_client()

    def test_independent_shell_and_assets(self):
        page=self.client.get('/')
        self.assertEqual(page.status_code,200)
        self.assertIn('鱼境',page.get_data(as_text=True))
        for asset in ('app.js','components.js','view-model.js','services.js','styles.css'):
            response=self.client.get('/static/'+asset)
            self.assertEqual(response.status_code,200);response.close()
        page.close()

    def test_bootstrap_explicit_demo_and_unconnected_services(self):
        d=self.client.get('/api/bootstrap').get_json()
        self.assertEqual(d['schema_version'],1);self.assertEqual(d['data_mode'],'demo')
        self.assertFalse(d['ai']['connected']);self.assertEqual(d['ai']['models'],[])
        self.assertTrue(all(c['stream_url'] is None and not c['detections'] for c in d['cameras']))
        self.assertTrue(all(f['download_url'] is None and f['index_status']=='not_indexed' for f in d['files']))
        self.assertTrue(all(e['source_kind']=='demo' and e['attachments']==[] for e in d['events']))
        self.assertNotIn('credential',json.dumps(d).lower())

    def test_monitoring_quality_freshness_and_no_fallback_values(self):
        for view,quality,freshness in [('available','valid','fresh'),('stale','valid','stale'),
            ('partial','partial','fresh'),('invalid','invalid','fresh'),('missing','missing','unknown')]:
            with self.subTest(view=view):
                d=self.client.get('/api/monitoring?device=demo-a&view='+view).get_json()
                self.assertEqual(d['quality'],quality);self.assertEqual(d['freshness'],freshness)
                self.assertEqual(d['source_kind'],'demo')
                if view in ('missing','invalid'):
                    self.assertTrue(all(m['value'] is None for m in d['metrics']))
                    self.assertEqual(d['trend'],[])
                if view=='partial':self.assertIsNone(d['metrics'][2]['value'])

    def test_demo_query_does_not_refresh_observation_or_mutate_shared_state(self):
        first=self.client.get('/api/monitoring').get_json()
        self.client.get('/api/monitoring?view=stale')
        last=self.client.get('/api/monitoring').get_json()
        self.assertEqual(first['observed_at'],last['observed_at'])
        self.assertEqual(first['metrics'],last['metrics'])

    def test_monitoring_adapter_injection_without_demo_ids(self):
        class Replacement(DemoMonitoring):
            def devices(self):return [{'id':'db-site-1','name':'连接区域'}]
            def snapshot(self,device_id,view='available'):
                self.selected=device_id
                return super().snapshot('demo-a',view)
        service=Replacement();app=create_app(monitoring=service)
        d=app.test_client().get('/api/bootstrap').get_json()
        self.assertEqual(d['devices'][0]['id'],'db-site-1');self.assertEqual(service.selected,'db-site-1')

    def test_filters_and_safe_details(self):
        items=self.client.get('/api/events?severity=warning&status=pending').get_json()['items']
        self.assertEqual(len(items),1)
        detail=self.client.get('/api/events/'+items[0]['id']).get_json()
        self.assertEqual(detail['attachments'],[])
        self.assertEqual(len(self.client.get('/api/files?category=设备说明').get_json()['items']),1)
        self.assertEqual(self.client.get('/api/files/unknown').status_code,404)
        self.assertEqual(self.client.get('/api/files?q='+('x'*129)).status_code,400)

    def test_local_security_and_all_mutating_operations_unavailable(self):
        self.assertEqual(self.client.get('/api/bootstrap',base_url='http://evil.invalid').status_code,403)
        self.assertEqual(self.client.get('/api/bootstrap',headers={'Origin':'http://evil.invalid'}).status_code,403)
        with patch('apps.management_web.services.UnavailableAI.send',side_effect=AssertionError('must not run')):
            self.assertEqual(self.client.post('/api/ai/messages',json={'question':'test'}).status_code,503)
            self.assertEqual(self.client.post('/api/ai/messages',data='x'*9000).status_code,413)
        for path in ('/api/events','/api/files','/api/settings','/api/scenario/apply'):
            self.assertIn(self.client.post(path,json={}).status_code,(404,405))
        response=self.client.get('/')
        self.assertNotIn('Access-Control-Allow-Origin',response.headers)
        self.assertIn("script-src 'self'",response.headers['Content-Security-Policy']);response.close()

    def test_invalid_device_and_demo_state_fail_closed(self):
        for query in ('device=../private','view=not-a-view'):
            response=self.client.get('/api/monitoring?'+query)
            self.assertEqual(response.status_code,400)
            self.assertEqual(response.get_json(),{'error_code':'INVALID_SELECTION'})

    def test_startup_separate_port_local_only_no_dotenv(self):
        from apps.management_web.__main__ import main
        with patch('sys.argv',['management_web','--legacy-demo']),patch('apps.management_web.__main__.create_app') as factory,patch('builtins.print'):
            main()
        factory.return_value.run.assert_called_once_with(host='127.0.0.1',port=8766,debug=False,load_dotenv=False)

    def test_normal_startup_uses_shared_store_without_reading_device_token(self):
        import os
        from apps.management_web.__main__ import main
        original_get=os.environ.get
        def guarded(key,*args):
            if key=='FISHERY_SIM_INGEST_TOKEN':raise AssertionError('read-only startup must not read token')
            return original_get(key,*args)
        with patch('sys.argv',['management_web']),patch('apps.monitoring.repository.MonitoringRepository') as repository,patch('apps.monitoring.service.MonitoringService') as service,patch('apps.management_web.__main__.create_app') as factory,patch('apps.management_web.__main__.os.environ.get',side_effect=guarded),patch('builtins.print'):
            main()
        service.assert_called_once_with(repository.return_value)
        self.assertIs(factory.call_args.kwargs['data_service'],service.return_value)
        self.assertIsNone(factory.call_args.kwargs['ingestion_token'])
        factory.return_value.run.assert_called_once_with(host='127.0.0.1',port=8766,debug=False,load_dotenv=False)

    def test_ingestion_startup_requires_explicit_flag_and_valid_development_token(self):
        import io
        import os
        from apps.management_web.__main__ import main
        original_get=os.environ.get
        for value,allowed in (('',False),('fake-token',False),('t'*64,True)):
            def supplied(key,*args):
                return value if key=='FISHERY_SIM_INGEST_TOKEN' else original_get(key,*args)
            with self.subTest(allowed=allowed),patch('sys.argv',['management_web','--enable-ingestion']),patch('apps.management_web.__main__.os.environ.get',side_effect=supplied),patch('apps.management_web.__main__.create_app') as factory,patch('apps.monitoring.repository.MonitoringRepository') as repository,patch('apps.monitoring.service.MonitoringService'),patch('sys.stderr',new_callable=io.StringIO),patch('builtins.print'):
                if allowed:
                    main()
                    self.assertEqual(factory.call_args.kwargs['ingestion_token'],value)
                else:
                    with self.assertRaises(SystemExit):main()
                    repository.assert_not_called()
                    factory.assert_not_called()


if __name__=='__main__':unittest.main()
