"""Daily path consolidation: disposable synthetic sources only, no credentials."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.management_paths import ManagementPaths
from apps.management_web.instance import initialize_instance
from scripts.dev.prepare_prototype_data import prepare_daily_data,legacy_paths,database_summary,digest


class DailyDataTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name); (self.root/'apps').mkdir()

    def seed(self):
        source=ManagementPaths.resolve(self.root,data_root=self.root/'seed')
        initialize_instance(source)
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.service import MonitoringService
        from apps.simulator.generator import Simulator
        now=datetime.now(timezone.utc)
        service=MonitoringService(MonitoringRepository(source.monitoring),clock=lambda:now)
        service.ingest(Simulator(start=now-timedelta(seconds=10),seed=42).advance(10))
        old=legacy_paths(self.root)
        for path in (old.monitoring,old.knowledge):path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source.monitoring,old.monitoring);shutil.copyfile(source.knowledge,old.knowledge)
        old.settings.write_text('{"fictional_preference":"preserve"}',encoding='utf8')
        old.policy_directory.mkdir(); (old.policy_directory/'tool_policies.json').write_text('{"fictional":true}')
        (old.policy_directory/'.management-policy.lock').write_text('not configuration')
        return old

    def test_copy_preserves_database_records_schema_settings_policy_and_originals(self):
        old=self.seed(); paths=ManagementPaths.resolve(self.root)
        hashes={path:digest(path) for path in (old.monitoring,old.knowledge,old.settings)}
        with patch('socket.create_connection',side_effect=AssertionError('no network')):
            report=prepare_daily_data(self.root)
        self.assertEqual(report['code'],'PROTOTYPE_DAILY_DATA_COPIED')
        for kind,src,dst in [('MONITORING',old.monitoring,paths.monitoring),('KNOWLEDGE',old.knowledge,paths.knowledge)]:
            self.assertEqual(database_summary(src,kind),database_summary(dst,kind))
        self.assertGreater(report['databases']['MONITORING']['counts']['batches'],0)
        self.assertTrue(all(digest(path)==value for path,value in hashes.items()))
        self.assertEqual(paths.settings.read_bytes(),old.settings.read_bytes())
        self.assertEqual((paths.policy_directory/'tool_policies.json').read_bytes(),(old.policy_directory/'tool_policies.json').read_bytes())
        self.assertFalse((paths.policy_directory/'.management-policy.lock').exists())
        self.assertFalse(paths.traces.exists())
        self.assertFalse(report['credentials_copied']); self.assertFalse(report['schema_changed'])

    def test_existing_target_or_incomplete_source_never_overwritten_or_filled(self):
        old=self.seed(); old.knowledge.unlink()  # Disposable synthetic source only.
        with self.assertRaisesRegex(RuntimeError,'LEGACY_INCOMPLETE'):prepare_daily_data(self.root)
        target=self.root/'apps/data';target.mkdir();(target/'sentinel').write_text('keep')
        with self.assertRaisesRegex(RuntimeError,'TARGET_EXISTS'):prepare_daily_data(self.root)
        self.assertEqual((target/'sentinel').read_text(),'keep')

    def test_corrupt_source_refused_without_creating_target(self):
        old=self.seed();old.knowledge.write_bytes(b'fictional broken sqlite')
        with self.assertRaises(ValueError):prepare_daily_data(self.root)
        self.assertFalse((self.root/'apps/data').exists())

    def test_explicit_first_install_empty_only_when_no_legacy_files_exist(self):
        report=prepare_daily_data(self.root)
        self.assertEqual(report['code'],'PROTOTYPE_DAILY_CREATED_EMPTY')
        paths=ManagementPaths.resolve(self.root)
        self.assertEqual(database_summary(paths.monitoring,'MONITORING')['counts']['batches'],0)

    def test_copy_failure_keeps_sources_and_never_publishes_partial_target(self):
        old=self.seed();before=digest(old.monitoring)
        with patch('scripts.dev.prepare_prototype_data.shutil.copyfile',side_effect=OSError('fake failure')):
            with self.assertRaisesRegex(RuntimeError,'STAGE_PRESERVED'):prepare_daily_data(self.root)
        self.assertFalse((self.root/'apps/data').exists());self.assertEqual(digest(old.monitoring),before)

    def test_defaults_resolve_one_root_without_opening_or_creating_anything(self):
        with patch('sqlite3.connect',side_effect=AssertionError('paths do not open SQLite')):
            p=ManagementPaths.resolve(self.root)
            self.assertEqual(p.data_root,self.root/'apps/data')
            self.assertEqual(p.monitoring.parent,p.knowledge.parent)
            self.assertEqual(p.settings.parent,p.data_root)
            self.assertEqual(p.policy_directory.parent,p.data_root)
        self.assertFalse(p.data_root.exists())
