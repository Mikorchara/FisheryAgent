"""Managed content HTTP and actual Knowledge Tool over a shared isolated store."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from apps.ai_backend.tests.support import FakeSDK,sdk_tool,sdk_final,tool_chunks,final_chunks
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
import apps.ai_service.tests.test_unified_tools as fixture
from apps.ai_service.service import ManagementAssistantService
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService,CONTENT_SOURCE
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app

VALUE={'title':'蓝莓浮岛','category':'用户试验资料','body':'蓝莓浮岛的银鳞鱼采用独立观察记录。这是用户背景知识，不是当前监测事实。'}
WATER,KNOWLEDGE,HISTORY=fixture.WATER,fixture.KNOWLEDGE,fixture.HISTORY


class KnowledgeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.UnifiedToolsTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.content=KnowledgeContentService(KnowledgeRepository(f.root/'knowledge.sqlite3'))
        old=f.backend
        f.backend=ManagementAssistantService(f.monitoring,credentials=old.credentials,traces=old.traces,
            policy_directory=old.policy_store.directory,knowledge=self.content,
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=f.sdk.factory),
            execution_config=old._execution_config,streaming_config=old._streaming_config,unified_config=old._unified_config)
        f.web=ManagementAssistant(f.backend)
        self.app=create_app(data_service=f.monitoring,ai=f.web,knowledge_service=self.content)
        f.client=self.app.test_client();f.headers={'X-Management-AI':f.web.browser_token}
        self.client=f.client
        self.token=self.client.get('/api/knowledge').get_json()['write_token']
        self.headers={'X-Management-Knowledge':self.token}
        self.old=old

    def create(self):
        response=self.client.post('/api/knowledge',json=VALUE,headers=self.headers)
        self.assertEqual(response.status_code,201,response.get_json());return response.get_json()

    def test_actual_http_crud_search_versions_filters_and_restore(self):
        item=self.create();url='/api/knowledge/'+item['id']
        self.assertEqual(self.client.get(url).get_json()['body'],VALUE['body'])
        result=self.client.post('/api/knowledge/search',json={'query':'蓝莓浮岛'},headers=self.headers).get_json()
        hit=next(h for h in result['evidence'] if h['id']==item['id']);self.assertEqual(hit['source_version'],'1')
        edited=self.client.patch(url,json={**VALUE,'title':'银鳞红珊瑚','version':1,'body':'银鳞红珊瑚是新的养殖笔记内容。'},headers=self.headers).get_json()
        self.assertEqual(edited['version'],2)
        conflict=self.client.patch(url,json={**VALUE,'version':1},headers=self.headers)
        self.assertEqual(conflict.status_code,409)
        for status in ('DISABLED','DELETED','ACTIVE'):
            edited=self.client.post(url+'/status',json={'version':edited['version'],'status':status},headers=self.headers).get_json()
            hits=self.client.post('/api/knowledge/search',json={'query':'银鳞红珊瑚'},headers=self.headers).get_json()['evidence']
            self.assertEqual(any(h['id']==item['id'] for h in hits),status=='ACTIVE')
        rows=self.client.get('/api/knowledge?q=银鳞红珊瑚&category=用户试验资料').get_json()['items']
        self.assertEqual(len(rows),1);self.assertNotIn('body',rows[0])
        self.assertNotIn(str(self.fixture.root),json.dumps(rows))

    def test_content_without_ai_and_restart_through_actual_startup_factory(self):
        from apps.management_web.__main__ import knowledge_content
        service=knowledge_content(self.fixture.root)
        app=create_app(knowledge_service=service);client=app.test_client()
        token=client.get('/api/knowledge').get_json()['write_token']
        item=client.post('/api/knowledge',json=VALUE,headers={'X-Management-Knowledge':token}).get_json()
        self.assertEqual(knowledge_content(self.fixture.root).get(item['id'])['body'],VALUE['body'])
        self.assertFalse(client.get('/api/ai/status').get_json()['connected'])
        self.assertEqual(client.post('/api/ai/messages',json={}).status_code,503)

    def test_host_origin_loopback_token_type_size_and_unknown_fields(self):
        for options in ({'headers':{}},{'headers':{'X-Management-Knowledge':'wrong'}},
                        {'headers':{**self.headers,'Origin':'http://evil.invalid'}},
                        {'headers':self.headers,'base_url':'http://evil.invalid'},
                        {'headers':self.headers,'environ_overrides':{'REMOTE_ADDR':'10.1.1.1'}}):
            self.assertEqual(self.client.post('/api/knowledge',json=VALUE,**options).status_code,403)
        self.assertEqual(self.client.get('/api/knowledge',environ_overrides={'REMOTE_ADDR':'10.1.1.1'}).status_code,403)
        for value in ({**VALUE,'id':'arbitrary'},{**VALUE,'body':'x'*6001},[] ):
            self.assertEqual(self.client.post('/api/knowledge',json=value,headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/knowledge',data='x'*33000,headers=self.headers).status_code,413)
        self.assertEqual(self.client.post('/api/knowledge',data='{"title":"a","title":"b"}',content_type='application/json',headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/knowledge/user-invalid').status_code,400)
        self.assertEqual(self.client.get('/api/knowledge?q='+'x'*129).status_code,400)
        self.assertFalse(self.fixture.sdk.bodies)

    def test_builtins_readonly_no_match_and_bounded_test_evidence(self):
        item=self.client.get('/api/knowledge').get_json()['items'][0]
        self.assertEqual(self.client.patch('/api/knowledge/'+item['id'],json={**VALUE,'version':1},headers=self.headers).get_json()['error_code'],'BUILTIN_KNOWLEDGE_READ_ONLY')
        created=self.client.post('/api/knowledge',json={**VALUE,'body':'蓝莓浮岛'*1400},headers=self.headers).get_json()
        result=self.client.post('/api/knowledge/search',json={'query':'蓝莓浮岛'},headers=self.headers).get_json()
        self.assertLessEqual(result['result_count'],3)
        self.assertTrue(all(len(h['text'])<=801 for h in result['evidence']))
        result=self.client.post('/api/knowledge/search',json={'query':'🛰🛰🛰'},headers=self.headers).get_json()
        self.assertEqual(result['status'],'NO_MATCH');self.assertEqual(result['evidence'],[])
        for value in ({'query':'x','top_k':10},{'query':True},{'query':'bad\nquery'}):
            self.assertEqual(self.client.post('/api/knowledge/search',json=value,headers=self.headers).status_code,400)

    def test_managed_scope_exact_identity_and_no_qualification_inheritance(self):
        f=self.fixture
        for key in ('normal_scope_json','streaming_scope_json'):
            old=json.loads(getattr(self.old._unified_config,key));new=json.loads(getattr(f.backend._unified_config,key))
            changed={name for name in old if old[name]!=new[name]}
            self.assertEqual(changed,{'data_bindings'})
            self.assertEqual(new['data_bindings']['knowledge_source'],CONTENT_SOURCE)
            self.assertEqual(new['runtime'],old['runtime']);self.assertEqual(new['budget'],old['budget'])
        for config in (f.backend._execution_config,f.backend._streaming_config):
            for entry in config.releases:
                self.assertIsNone(entry.runtime.qualification_id);self.assertIsNone(entry.runtime.validated_at)
        self.content.create(VALUE)
        current=f.envelope();self.assertNotEqual(current['revision'],self.old.bootstrap('pond-a')['presets'][0]['execution']['revision'])
        with self.assertRaisesRegex(ValueError,'AI_KNOWLEDGE_SOURCE_MISMATCH'):
            create_app(data_service=f.monitoring,ai=f.web,knowledge_service=KnowledgeContentService(KnowledgeRepository(f.root/'other.sqlite3')))

    def test_real_registry_executor_normal_streaming_content_source_and_commit(self):
        item=self.create();f=self.fixture
        arguments=json.dumps({'query':'蓝莓浮岛'},ensure_ascii=False)
        for streaming in (False,True):
            with self.subTest(streaming=streaming):
                plans=[tool_chunks(KNOWLEDGE,'k1',arguments),final_chunks()] if streaming else [
                    sdk_tool(KNOWLEDGE,'k1',arguments,f.profile.model),sdk_final(model=f.profile.model)]
                result=f.send((KNOWLEDGE,),streaming,plans=plans)
                self.assertTrue(result['successful_turn'],result)
                payload=json.loads(next(m['content'] for m in f.sdk.bodies[1]['messages'] if m['role']=='tool'))
                evidence=next(h for h in payload['evidence'] if h['id']==item['id'])
                self.assertEqual(evidence['source_version'],'1');self.assertEqual(evidence['source'],item['source_id'])
                receipt=f.captured[0].source_ledger.entries[0].receipt
                self.assertTrue(receipt.project_search_completed);self.assertTrue(receipt.has_project_evidence)
                self.assertFalse(receipt.observation_query_completed);self.assertFalse(receipt.history_query_completed)
                self.assertTrue(all(b['max_tokens']==(512 if streaming else 1024) for b in f.sdk.bodies))
                safe=json.dumps(result)+f.backend.traces.path.read_text(encoding='utf-8')
                self.assertNotIn(VALUE['body'],safe)
                self.assertTrue(all(c.closed and (not c.stream or c.stream.closed) for c in f.sdk.clients))

    def test_current_history_paths_still_use_monitoring_and_do_not_search_knowledge(self):
        f=self.fixture
        for streaming in (False,True):
            with patch.object(self.content,'search',side_effect=AssertionError('no implicit knowledge retrieval')):
                result=f.send((WATER,HISTORY),streaming)
            self.assertTrue(result['successful_turn'],result)
            f.assert_delivery_and_sources((WATER,HISTORY))
            self.assertEqual(len(f.sdk.bodies),3)
