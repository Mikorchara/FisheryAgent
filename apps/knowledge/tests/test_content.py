from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.knowledge.retrieval import KnowledgeService
from apps.knowledge.tests.support import seed
from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService, MAX_BODY_CHARS

VALUE={'title':'蓝莓浮岛','category':'试验资料','body':'蓝莓浮岛是本机演示的独立知识标记，不是现场事实。'}


class KnowledgeContentTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'knowledge.sqlite3'
        seed(self.path)
        self.service=KnowledgeContentService(KnowledgeRepository(self.path))

    def test_create_edit_disable_delete_restore_and_restart(self):
        item=self.service.create(VALUE)
        first=next(hit for hit in self.service.search('蓝莓浮岛') if hit.evidence_id==item['id'])
        self.assertEqual(first.source_version,'1');self.assertIn(item['id'],first.source_id)
        edited=self.service.edit(item['id'],{**VALUE,'title':'银鳞玫瑰温棚','version':1,'body':'银鳞玫瑰温棚是修改后的独立背景知识。'})
        self.assertEqual(edited['version'],2)
        self.assertFalse(any(hit.evidence_id==item['id'] and '蓝莓浮岛' in hit.text for hit in self.service.search('蓝莓浮岛')))
        self.assertEqual(next(h for h in self.service.search('银鳞玫瑰温棚') if h.evidence_id==item['id']).source_version,'2')
        for state in ('DISABLED','ACTIVE','DELETED'):
            edited=self.service.set_status(item['id'],{'version':edited['version'],'status':state})
            hits=self.service.search('银鳞玫瑰温棚')
            self.assertEqual(any(h.evidence_id==item['id'] for h in hits),state=='ACTIVE')
        restarted=KnowledgeContentService(KnowledgeRepository(self.path))
        self.assertEqual(restarted.get(item['id'])['status'],'DELETED')
        edited=restarted.set_status(item['id'],{'version':edited['version'],'status':'ACTIVE'})
        self.assertTrue(any(h.evidence_id==item['id'] for h in restarted.search('银鳞玫瑰温棚')))

    def test_builtin_editable_and_original_retrieval_parity(self):
        from fishery_ai.knowledge import KnowledgeService as LegacyKnowledgeService
        resource=files('fishery_ai').joinpath('resources/knowledge/eel_knowledge.json')
        before=resource.read_bytes();original=LegacyKnowledgeService(resource)
        expected=original.search('鳗鲡低氧表现',top_k=3)
        actual=self.service.search('鳗鲡低氧表现',top_k=3)
        self.assertEqual([(h.evidence_id,h.text,h.score,h.source_id,h.source_version) for h in actual],
                         [(h.evidence_id,h.text,h.score,h.source_id,h.source_version) for h in expected])
        item=self.service.list()['items'][0]
        edited=self.service.edit(item['id'],{**VALUE,'version':1})
        self.assertEqual(edited['source_version'],'2')
        self.assertEqual(edited['original_source_id'],item['source_id'])
        self.assertNotEqual(edited['source_id'],item['source_id'])
        self.service.set_status(item['id'],{'version':2,'status':'DISABLED'})
        self.assertEqual(resource.read_bytes(),before)
        self.assertEqual(KnowledgeContentService(KnowledgeRepository(self.path)).get(item['id'])['status'],'DISABLED')

    def test_strict_content_versions_filters_and_path_rejection(self):
        for changes in ({'title':''},{'category':'x'*41},{'body':'x'*(MAX_BODY_CHARS+1)},
                        {'body':'\ud800'},{'title':'hidden\x00'},{'body':True},{'id':'arbitrary'}):
            with self.subTest(changes=repr(changes)[:45]),self.assertRaises(KnowledgeError):
                self.service.create({**VALUE,**changes})
        item=self.service.create(VALUE)
        for invalid in (True,1.0,'1',None,0):
            with self.assertRaises(KnowledgeError):self.service.edit(item['id'],{**VALUE,'version':invalid})
        for key in ('../private','C:\\private','user-unknown','/etc/passwd'):
            with self.assertRaises(KnowledgeError):self.service.get(key)
        with self.assertRaises(KnowledgeError):self.service.list(query='x'*129)
        with self.assertRaises(KnowledgeError):self.service.list(offset=True)
        selected=self.service.list(query='蓝莓浮岛',category=VALUE['category'])
        self.assertEqual(selected['total'],1);self.assertNotIn('body',selected['items'][0])

    def test_duplicate_id_capacity_write_failure_and_cas_never_corrupt_store(self):
        with patch('apps.knowledge.repository.uuid.uuid4',return_value=SimpleNamespace(hex='a'*32)):
            item=self.service.create(VALUE)
            with self.assertRaisesRegex(KnowledgeError,'CONFLICT'):self.service.create(VALUE)
        with patch('apps.knowledge.repository.MAX_USER_RECORDS',1),self.assertRaisesRegex(KnowledgeError,'LIMIT'):
            self.service.create(VALUE)
        with patch('apps.knowledge.repository.MAX_TOTAL_BODY_CHARS',len(VALUE['body'])),self.assertRaisesRegex(KnowledgeError,'LIMIT'):
            self.service.create(VALUE)
        with patch('apps.knowledge.repository.MAX_TOTAL_BODY_CHARS',1),self.assertRaisesRegex(KnowledgeError,'LIMIT'):
            self.service.edit(item['id'],{**VALUE,'version':1})
        with patch('apps.knowledge.repository.sqlite3.connect',side_effect=sqlite3.OperationalError('private path')):
            with self.assertRaisesRegex(KnowledgeError,'^KNOWLEDGE_STORAGE_ERROR$'):self.service.create(VALUE)
        with self.assertRaisesRegex(KnowledgeError,'CONFLICT'):
            self.service.edit(item['id'],{**VALUE,'version':2})
        self.assertEqual(self.service.get(item['id'])['version'],1)
        self.assertEqual(self.service.list(category=VALUE['category'])['total'],1)
        with self.service.repository.connection(write=True) as db:
            db.execute("CREATE TRIGGER reject_revision BEFORE UPDATE ON knowledge_revision BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaisesRegex(KnowledgeError,'STORAGE_ERROR'):self.service.create(VALUE)
        self.assertEqual(self.service.list(category=VALUE['category'])['total'],1)
        with self.service.repository.connection(write=True) as db:db.execute('DROP TRIGGER reject_revision')

    def test_concurrent_edit_one_winner_and_complete_index_snapshot(self):
        item=self.service.create(VALUE)
        def edit(body):
            try:return self.service.edit(item['id'],{**VALUE,'title':'红珊瑚','version':1,'body':body})['version']
            except KnowledgeError as error:return error.code
        with ThreadPoolExecutor(2) as pool:
            result=list(pool.map(edit,['完整第一版红珊瑚','完整第二版红珊瑚']))
        self.assertEqual(sorted(map(str,result)),['2','KNOWLEDGE_CONFLICT'])
        entered,release=threading.Event(),threading.Event();original=KnowledgeService.search
        def pause(index,*args,**kwargs):
            entered.set();self.assertTrue(release.wait(5));return original(index,*args,**kwargs)
        with ThreadPoolExecutor(1) as pool,patch.object(KnowledgeService,'search',pause):
            pending=pool.submit(self.service.search,'红珊瑚')
            self.assertTrue(entered.wait(5))
            self.service.edit(item['id'],{**VALUE,'title':'蓝珊瑚','version':2,'body':'新版本蓝珊瑚独立内容'})
            release.set();old=pending.result()
        self.assertEqual(next(h for h in old if h.evidence_id==item['id']).source_version,'2')
        fresh=next(h for h in self.service.search('蓝珊瑚') if h.evidence_id==item['id'])
        self.assertEqual(fresh.source_version,'3');self.assertNotIn('红珊瑚',fresh.text)

    def test_other_service_updates_cache_and_empty_corpus_is_no_match(self):
        self.service.search('蓝莓浮岛')
        other=KnowledgeContentService(KnowledgeRepository(self.path));item=other.create(VALUE)
        self.assertTrue(any(h.evidence_id==item['id'] for h in self.service.search('蓝莓浮岛')))
        for row in self.service.list()['items']:
            self.service.set_status(row['id'],{'version':row['version'],'status':'DISABLED'})
        self.assertEqual(self.service.search('任何词'),())
