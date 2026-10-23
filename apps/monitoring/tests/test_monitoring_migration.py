"""Explicit v1 -> v2 migration, tested only on disposable synthetic databases."""

from pathlib import Path
from contextlib import closing
from contextlib import redirect_stderr
import io
import sqlite3
import subprocess
import sys
import json
import unittest
from unittest.mock import patch

from apps.management_web.instance import check_database, InstanceError
from apps.monitoring.migrate import inspect_database, upgrade_database
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.schema import BASE_COLUMNS
from apps.monitoring.tests import test_event_lifecycle as lifecycle
from apps.monitoring.tests import test_event_management as management


class MonitoringMigrationTests(unittest.TestCase):
    setUp = lifecycle.VisualLifecycleTests.setUp
    batch = lifecycle.VisualLifecycleTests.batch
    oxygen = management.EventManagementTests.oxygen

    def legacy(self):
        self.oxygen(4.2); self.oxygen(2.2); self.oxygen(6.4)
        with self.repo.connection() as db:
            db.execute('DROP TABLE event_actions')
            db.execute('DROP TABLE event_handling_members')
            db.execute('DROP TABLE event_handling')
            db.execute('PRAGMA user_version=1')
        return self.path.with_name('pre-evt3a.sqlite3')

    def test_dry_run_and_normal_startup_leave_v1_untouched(self):
        self.legacy()
        before = self.path.read_bytes()
        report = inspect_database(self.path)
        self.assertEqual(report['status'], 'UPGRADE_READY')
        self.assertEqual(report['schema_version'], 1)
        for existing in (False, True):
            with self.assertRaisesRegex(ValueError, 'MONITORING_SCHEMA_UPGRADE_REQUIRED'):
                MonitoringRepository(self.path, require_existing=existing)
        with self.assertRaisesRegex(InstanceError, 'MONITORING_DATABASE_UPGRADE_REQUIRED'):
            check_database(self.path, 'MONITORING')
        self.assertEqual(self.path.read_bytes(), before)

    def test_backup_upgrade_keeps_all_original_rows_schema_and_is_idempotent(self):
        backup = self.legacy()
        before = inspect_database(self.path)['business_tables']
        result = upgrade_database(self.path, backup, writers_stopped=True)
        self.assertEqual(result['status'], 'UPGRADED_AND_VERIFIED')
        self.assertEqual(inspect_database(self.path)['business_tables'], before)
        self.assertEqual(inspect_database(backup)['business_tables'], before)
        self.assertEqual(inspect_database(backup)['schema_version'], 1)
        self.assertEqual(inspect_database(self.path)['schema_version'], 2)
        self.assertEqual(upgrade_database(self.path, backup, writers_stopped=True)['status'], 'ALREADY_CURRENT')
        MonitoringRepository(self.path, require_existing=True)
        check_database(self.path, 'MONITORING')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM event_actions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM event_handling').fetchone()[0], 0)

    def test_no_silent_writer_override_backup_overwrite_or_partial_schema(self):
        backup = self.legacy()
        with self.assertRaisesRegex(ValueError, 'WRITERS_STOP_CONFIRMATION_REQUIRED'):
            upgrade_database(self.path, backup)
        backup.write_bytes(b'fictional existing backup')
        with self.assertRaisesRegex(ValueError, 'BACKUP_ALREADY_EXISTS'):
            upgrade_database(self.path, backup, writers_stopped=True)
        self.assertEqual(backup.read_bytes(), b'fictional existing backup')
        fresh = backup.with_name('failed-step-backup.sqlite3')
        def fail(db):
            db.execute('CREATE TABLE partial_should_rollback(id INTEGER)')
            raise RuntimeError('synthetic migration failure')
        with patch('apps.monitoring.migrate.add_handling_tables',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'synthetic migration failure'):
                upgrade_database(self.path, fresh, writers_stopped=True)
        self.assertEqual(inspect_database(self.path)['schema_version'], 1)
        self.assertEqual(inspect_database(fresh)['schema_version'], 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='partial_should_rollback'").fetchone())

    def test_committed_wal_backup_and_actual_cli_dry_run(self):
        backup = self.legacy()
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE channel_contacts SET last_received_at='2026-10-23T00:00:40+00:00'")
            writer.commit()
            self.assertTrue(self.path.with_name(self.path.name+'-wal').exists())
            before = inspect_database(self.path)['business_tables']
            result = subprocess.run([sys.executable,'-I','-B',str(Path(__file__).parents[1]/'migrate.py'),
                '--database',str(self.path),'--dry-run'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'],'UPGRADE_READY')
            upgrade_database(self.path,backup,writers_stopped=True)
            self.assertEqual(inspect_database(backup)['business_tables'],before)
            self.assertEqual(inspect_database(self.path)['business_tables'],before)

    def test_actual_web_entry_refuses_v1_before_knowledge_credentials_or_server(self):
        self.legacy()
        from apps.management_web.__main__ import main
        before = self.path.read_bytes()
        errors = io.StringIO()
        with (patch('apps.management_web.__main__.knowledge_content',side_effect=AssertionError('must not read knowledge')),
                patch('apps.management_web.__main__.create_app',side_effect=AssertionError('must not serve'))):
            with redirect_stderr(errors), self.assertRaises(SystemExit) as stopped:
                main(['--project-root',str(self.path.parent),'--data-root',str(self.path.parent)])
        self.assertEqual(stopped.exception.code,2)
        self.assertIn('MONITORING_DATABASE_UPGRADE_REQUIRED',errors.getvalue())
        self.assertIn('migrate.py',errors.getvalue())
        self.assertEqual(self.path.read_bytes(),before)

    def test_invalid_active_reference_is_rejected_without_repair_or_backup_creation(self):
        backup = self.legacy()
        with self.repo.connection() as db:
            db.execute('INSERT INTO alerts VALUES (?,?,?,?)',('sim-pond-1','water','OXYGEN_LOW','missing-event'))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'MONITORING_EVENT_REFERENCES_INVALID'):
            upgrade_database(self.path,backup,writers_stopped=True)
        self.assertFalse(backup.exists())
        self.assertEqual(self.path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
