"""Isolated legacy migration, parity and export tests; never reads a user's DB."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.knowledge.migration import migrate, prepare, legacy_reference
from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.knowledge.tests.support import LEGACY_JSON


class UnifiedKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.old=self.root/'old.sqlite3';self.target=self.root/'new.sqlite3'
        self.ids=['user-'+'a'*32,'user-'+'b'*32]
        with closing(sqlite3.connect(self.old,isolation_level=None)) as db:
            db.executescript('''CREATE TABLE knowledge_records(id TEXT PRIMARY KEY,title TEXT,category TEXT,
                body TEXT,version INTEGER,status TEXT,updated_at TEXT);
                CREATE TABLE builtin_state(id TEXT PRIMARY KEY,version INTEGER,status TEXT,updated_at TEXT);
                CREATE TABLE knowledge_revision(id INTEGER PRIMARY KEY,revision INTEGER);
                INSERT INTO knowledge_revision VALUES(1,5);''')
            db.executemany('INSERT INTO knowledge_records VALUES(?,?,?,?,?,?,?)',[
                (self.ids[0],'蓝莓浮岛','试验资料','蓝莓浮岛是用户创建的背景资料。',3,'ACTIVE','2026-10-18T01:00:00+00:00'),
                (self.ids[1],'珊瑚测试','试验资料','已删除的资料仍可恢复。',2,'DELETED','2026-10-18T01:00:00+00:00')])
        self.original_hash=hashlib.sha256(self.old.read_bytes()).hexdigest()
        self.json_hash=hashlib.sha256(LEGACY_JSON.read_bytes()).hexdigest()

    def apply(self):
        self.plan=migrate(self.old,self.target,LEGACY_JSON)
        return migrate(self.old,self.target,LEGACY_JSON,apply=True,approved_plan_sha256=self.plan['plan_sha256'])

    def assert_sources_unchanged(self):
        self.assertEqual(hashlib.sha256(self.old.read_bytes()).hexdigest(),self.original_hash)
        self.assertEqual(hashlib.sha256(LEGACY_JSON.read_bytes()).hexdigest(),self.json_hash)

    def test_migration_preserves_all_records_versions_and_builtin_states_with_backup(self):
        key='builtin-'+hashlib.sha256('wq_temperature'.encode()).hexdigest()[:24]
        with closing(sqlite3.connect(self.old,isolation_level=None)) as db:
            db.execute('INSERT INTO builtin_state VALUES(?,?,?,?)',(key,4,'DISABLED','2026-10-18T01:00:00+00:00'))
        self.original_hash=hashlib.sha256(self.old.read_bytes()).hexdigest()
        result=self.apply();self.assertEqual(result['builtin_count'],31);self.assertEqual(result['user_count'],2)
        self.assertEqual(result['total_count'],33);self.assertEqual(result['integrity'],'ok')
        service=KnowledgeContentService(KnowledgeRepository(self.target,require_existing=True))
        self.assertEqual(service.get(self.ids[0])['version'],3)
        self.assertEqual(service.get(self.ids[1])['status'],'DELETED')
        self.assertEqual(service.get(key)['version'],4);self.assertEqual(service.get(key)['status'],'DISABLED')
        _,records,_=service.repository.snapshot()
        self.assertEqual(len({r['evidence_id'] for r in records}),33)
        backup=self.target.parent/'backups'/result['backup_id']
        self.assertEqual(prepare(backup/'previous-knowledge.sqlite3',backup/'eel_knowledge.json')[0],{k:v for k,v in self.plan.items() if k not in ('status','applied')})
        self.assert_sources_unchanged()

    def test_idempotence_never_overwrites_later_edits_and_changed_sources_refused(self):
        self.apply();service=KnowledgeContentService(KnowledgeRepository(self.target))
        item=service.list()['items'][0]
        edited=service.edit(item['id'],dict(title='红珊瑚新资料',category='自定义',body='红珊瑚新资料替换原内容。',version=item['version']))
        target_before=self.target.read_bytes()
        result=migrate(self.old,self.target,LEGACY_JSON,apply=True)
        self.assertEqual(result['status'],'ALREADY_MIGRATED');self.assertEqual(target_before,self.target.read_bytes())
        self.assertEqual(service.get(item['id']),edited)
        with closing(sqlite3.connect(self.old,isolation_level=None)) as db:db.execute('UPDATE knowledge_revision SET revision=revision+1')
        with self.assertRaisesRegex(KnowledgeError,'TARGET_EXISTS'):migrate(self.old,self.target,LEGACY_JSON,apply=True)
        self.assertEqual(target_before,self.target.read_bytes())

    def test_dry_run_plan_change_failure_and_no_overwrite_preserve_sources(self):
        plan=migrate(self.old,self.target,LEGACY_JSON);self.assertFalse(self.target.exists())
        self.assertFalse((self.root/'backups').exists())
        with self.assertRaisesRegex(KnowledgeError,'PLAN_CHANGED'):
            migrate(self.old,self.target,LEGACY_JSON,apply=True,approved_plan_sha256='wrong')
        with patch.object(KnowledgeRepository,'insert',side_effect=KnowledgeError('fixture abort')):
            with self.assertRaisesRegex(KnowledgeError,'fixture abort'):
                migrate(self.old,self.target,LEGACY_JSON,apply=True,approved_plan_sha256=plan['plan_sha256'])
        self.assertFalse(self.target.exists());self.assertFalse(list(self.root.glob('.migration-*')))
        self.assert_sources_unchanged()
        self.target.write_bytes(b'existing unrelated file')
        with self.assertRaisesRegex(KnowledgeError,'TARGET_EXISTS'):migrate(self.old,self.target,LEGACY_JSON)
        self.assertEqual(self.target.read_bytes(),b'existing unrelated file')

    def test_bad_legacy_and_user_data_abort_without_target_or_source_changes(self):
        bad=self.root/'invalid.json';bad.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(KnowledgeError,'SOURCE_INVALID'):migrate(self.old,self.target,bad)
        with closing(sqlite3.connect(self.old,isolation_level=None)) as db:db.execute("UPDATE knowledge_records SET status='unknown'")
        before=self.old.read_bytes()
        with self.assertRaisesRegex(KnowledgeError,'SOURCE_INVALID'):migrate(self.old,self.target,LEGACY_JSON)
        self.assertFalse(self.target.exists());self.assertEqual(before,self.old.read_bytes())
        with self.assertRaisesRegex(KnowledgeError,'SAME_PATH'):migrate(self.old,self.old,LEGACY_JSON)

    def test_retrieval_parity_old_evidence_and_new_local_type_for_all_builtin_queries(self):
        from fishery_ai.knowledge import KnowledgeService as Old
        old=Old(LEGACY_JSON)
        plan=migrate(None,self.target,LEGACY_JSON)
        migrate(None,self.target,LEGACY_JSON,apply=True,approved_plan_sha256=plan['plan_sha256'])
        service=KnowledgeContentService(KnowledgeRepository(self.target))
        timestamp=datetime(2026,10,18,tzinfo=timezone.utc)
        queries=[c['text'].split('。')[0] for c in old.chunks]+['低氧表现','水质耦合关系','白点病','投喂率','🛰🛰🛰']
        for query in queries:
            with self.subTest(query=query):
                actual=service.search(query,retrieved_at=timestamp,top_k=3)
                expected=old.search(query,retrieved_at=timestamp,top_k=3)
                # Source title was supplied by the R2D-3A projection, not the old Evidence constructor.
                self.assertEqual([{k:v for k,v in asdict(h).items() if k!='source_title'} for h in actual],
                                 [{k:v for k,v in asdict(h).items() if k!='source_title'} for h in expected])
                self.assertTrue(all(type(h).__module__=='apps.knowledge.evidence' for h in actual))

    def test_imported_edit_retrieval_restart_and_exports_are_one_snapshot(self):
        self.apply();service=KnowledgeContentService(KnowledgeRepository(self.target))
        item=service.list()['items'][0];original=service.get(item['id'])
        edited=service.edit(item['id'],dict(title='红珊瑚玫瑰',category='人工资料',body='红珊瑚玫瑰是新的独立养殖背景资料。',version=item['version']))
        hits=service.search('红珊瑚玫瑰',top_k=100)
        matched=[h for h in hits if h.evidence_id==legacy_reference(LEGACY_JSON).chunks[0]['id']]
        self.assertEqual(len(matched),1);self.assertIn('红珊瑚玫瑰',matched[0].text)
        self.assertEqual(matched[0].source_version,str(edited['version']))
        self.assertEqual(edited['original_source_id'],original['source_id'])
        for status in ('DISABLED','DELETED','ACTIVE'):
            edited=service.set_status(item['id'],{'version':edited['version'],'status':status})
            self.assertEqual(any(h.evidence_id==matched[0].evidence_id for h in service.search('红珊瑚玫瑰',top_k=100)),status=='ACTIVE')
        restarted=KnowledgeContentService(KnowledgeRepository(self.target,require_existing=True))
        self.assertEqual(restarted.get(item['id']),edited)
        before=self.target.read_bytes()
        for selection in ('all','active'):
            payload,mime,name=restarted.export(format='json',status=selection);data=json.loads(payload)
            self.assertEqual(data['count'],33 if selection=='all' else 32)
            markdown,_,mdname=restarted.export(format='markdown',status=selection)
            for record in data['items']:
                for field in ('id','body','source_id','source_version','original_source_id'):
                    self.assertIn(record[field],markdown.decode())
            self.assertNotIn('/',name);self.assertNotIn('\\',mdname)
            self.assertLess(len(payload),2*1024*1024)
        for value in ('../../private','sqlite','html'):
            with self.assertRaises(KnowledgeError):service.export(format=value)
        self.assertEqual(before,self.target.read_bytes());self.assert_sources_unchanged()

    def test_product_requires_explicit_database_and_no_runtime_legacy_import_or_read(self):
        self.apply()
        code='''
import sys,importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*a):
  if name=='fishery_ai' or name.startswith('fishery_ai.'):raise AssertionError(name)
sys.meta_path.insert(0,Block())
from pathlib import Path
from unittest.mock import patch
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
with patch.object(Path,'read_text',side_effect=AssertionError('no resource text read')):
 s=KnowledgeContentService(KnowledgeRepository(sys.argv[1],require_existing=True))
 assert s.search('蓝莓浮岛')
'''
        run=subprocess.run([sys.executable,'-c',code,str(self.target)],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        from apps.management_web.__main__ import knowledge_content
        with self.assertRaisesRegex(KnowledgeError,'MIGRATION_REQUIRED'):knowledge_content(self.root)
        self.assertFalse((self.root/'apps/knowledge_data').exists())

    def test_cli_dry_run_safe_metadata_and_hash_then_explicit_apply(self):
        command=[sys.executable,'-m','apps.knowledge','--source',str(self.old),'--target',str(self.target),'--legacy-json',str(LEGACY_JSON)]
        dry=subprocess.run([*command,'--dry-run'],capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(dry.returncode,0,dry.stderr);plan=json.loads(dry.stdout)
        self.assertFalse(self.target.exists());self.assertNotIn('蓝莓',dry.stdout);self.assertNotIn(str(self.root),dry.stdout)
        run=subprocess.run([*command,'--apply','--plan-sha256',plan['plan_sha256']],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout)['status'],'MIGRATED')
        self.assert_sources_unchanged()

    def test_sqlite_backup_includes_committed_wal_and_never_overwrites(self):
        from apps.knowledge.migration import backup
        self.apply()
        with closing(sqlite3.connect(self.target,isolation_level=None)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("UPDATE knowledge_records SET title='WAL committed fixture' WHERE id=?",(self.ids[0],))
            destination=self.root/'separate-backup.sqlite3'
            self.assertEqual(backup(self.target,destination)['status'],'BACKED_UP')
            with closing(sqlite3.connect(destination)) as copy:
                self.assertEqual(copy.execute('SELECT title FROM knowledge_records WHERE id=?',(self.ids[0],)).fetchone()[0],'WAL committed fixture')
            before=destination.read_bytes()
            with self.assertRaisesRegex(KnowledgeError,'TARGET_EXISTS'):backup(self.target,destination)
            self.assertEqual(before,destination.read_bytes())

    def test_concurrent_publication_cannot_replace_a_new_target(self):
        plan=migrate(self.old,self.target,LEGACY_JSON)
        def race(stage,target):
            Path(target).write_bytes(b'concurrent target must survive')
            raise FileExistsError()
        with patch('apps.knowledge.migration.os.link',side_effect=race):
            with self.assertRaisesRegex(KnowledgeError,'STORAGE_ERROR'):
                migrate(self.old,self.target,LEGACY_JSON,apply=True,approved_plan_sha256=plan['plan_sha256'])
        self.assertEqual(self.target.read_bytes(),b'concurrent target must survive')
        self.assert_sources_unchanged();self.assertFalse(list(self.root.glob('.migration-*')))

    def test_startup_does_not_initialize_an_existing_empty_or_legacy_target(self):
        self.target.write_bytes(b'')
        for path in (self.target,self.old):
            before=path.read_bytes()
            with self.assertRaisesRegex(KnowledgeError,'MIGRATION_REQUIRED'):
                KnowledgeRepository(path,require_existing=True)
            self.assertEqual(path.read_bytes(),before)
