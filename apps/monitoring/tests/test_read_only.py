"""Only new synthetic stores: DB permissions, snapshots, bounds and RW compatibility."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


class ReadOnlyRepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root/'monitoring.sqlite3'
        self.writer = MonitoringRepository(self.path)
        self.now = datetime(2026,10,25,tzinfo=timezone.utc)
        self.sim = Simulator(start=self.now, session_id='read-only-test')
        self.service = MonitoringService(self.writer, clock=lambda:self.now)
        self.ingest()

    def ingest(self):
        batch = self.sim.advance()
        self.now = datetime.fromisoformat(batch['timestamp'])
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2,min=2.2,max=2.2,latest=2.2)
        self.service.ingest(batch)

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_ro_query_only_and_all_mutations_rejected_without_change(self):
        before = self.fingerprint()
        reader = MonitoringRepository(self.path, read_only=True)
        statements = ["DELETE FROM events", "UPDATE current SET received_at='bad'",
                      'CREATE TABLE forbidden(id)', 'PRAGMA user_version=99',
                      'PRAGMA query_only=OFF', "ATTACH DATABASE ':memory:' AS other",
                      'PRAGMA journal_mode=WAL', 'VACUUM']
        for sql in statements:
            with self.subTest(sql=sql), reader.connection() as db:
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],1)
                with self.assertRaises(sqlite3.Error):
                    db.execute(sql)
        self.assertEqual(before,self.fingerprint())
        with reader.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)

    def test_missing_and_empty_never_create_or_initialize(self):
        missing = self.root/'absent-parent'/'missing.sqlite3'
        with self.assertRaises(sqlite3.Error):
            MonitoringRepository(missing,read_only=True)
        self.assertFalse(missing.parent.exists())
        empty = self.root/'empty.sqlite3'; empty.touch()
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_MONITORING_STORAGE_SCHEMA'):
            MonitoringRepository(empty,read_only=True)
        self.assertEqual(empty.stat().st_size,0)

    def test_v1_never_auto_migrates(self):
        old = self.root/'v1.sqlite3'
        with closing(sqlite3.connect(old)) as db:
            db.execute('PRAGMA user_version=1')
        before = old.read_bytes()
        with self.assertRaisesRegex(ValueError,'MONITORING_SCHEMA_UPGRADE_REQUIRED'):
            MonitoringRepository(old,read_only=True)
        self.assertEqual(before,old.read_bytes())

    def test_default_writer_still_ingests_and_reader_sees_new_commits(self):
        reader = MonitoringRepository(self.path,read_only=True)
        first = reader.read('sim-pond-1','water')['batch_id']
        self.ingest()
        self.assertNotEqual(first,reader.read('sim-pond-1','water')['batch_id'])
        self.assertFalse(self.writer.read_only)

    def test_sql_time_work_budget_and_connection_cleanup(self):
        reader = MonitoringRepository(self.path,read_only=True)
        started=time.monotonic()
        with reader.connection() as db, self.assertRaises(sqlite3.OperationalError):
            db.execute('''WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x)
                          SELECT sum(n) FROM x''').fetchone()
        self.assertLess(time.monotonic()-started,3)
        # No failed read connection/transaction holds a lock over the writer.
        self.ingest()
        self.assertIsNotNone(reader.read('sim-pond-1','water'))

    def test_wal_concurrent_reader_and_writer_do_not_use_immutable_snapshot(self):
        with self.writer.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
        reader = MonitoringRepository(self.path,read_only=True)
        with reader.connection() as db:
            db.execute('BEGIN')
            count=db.execute('SELECT count(*) FROM batches').fetchone()[0]
            self.ingest()
            self.assertEqual(count,db.execute('SELECT count(*) FROM batches').fetchone()[0])
        with reader.connection() as db:
            self.assertEqual(count+1,db.execute('SELECT count(*) FROM batches').fetchone()[0])
        with ThreadPoolExecutor(max_workers=4) as workers:
            values=list(workers.map(lambda _: reader.read('sim-pond-1','water')['batch_id'],range(16)))
        self.assertEqual(len(set(values)),1)

    def test_exclusive_lock_fails_in_bounded_time_then_recovers(self):
        reader = MonitoringRepository(self.path,read_only=True)
        with closing(sqlite3.connect(self.path)) as locked:
            locked.execute('BEGIN EXCLUSIVE')
            started=time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                reader.read('sim-pond-1','water')
            self.assertLess(time.monotonic()-started,1.5)
            locked.rollback()
        self.assertIsNotNone(reader.read('sim-pond-1','water'))

    def test_device_event_budget_cannot_silently_truncate(self):
        reader = MonitoringRepository(self.path,read_only=True)
        with reader.connection() as db:
            before=db.execute('SELECT count(*) FROM events').fetchone()[0]
        events,current=reader.capture_events('sim-pond-1')
        self.assertEqual(len(events),before)
        self.assertEqual(set(current),{'water','visual'})
        if before > 1:
            with self.assertRaisesRegex(ValueError,'EVENT_QUERY_LIMIT'):
                reader.capture_events('sim-pond-1',max_rows=1)
        with self.assertRaisesRegex(ValueError,'INVALID_EVENT_QUERY_LIMIT'):
            reader.capture_events('sim-pond-1',max_rows=257)
        self.assertEqual(reader.capture_events('other-device'),([],{}))

    def test_scoped_service_reuses_projection_and_does_not_read_ack_history(self):
        reader=MonitoringRepository(self.path,read_only=True)
        service=MonitoringService(reader,clock=lambda:self.now)
        from unittest.mock import patch
        with patch('apps.monitoring.repository.project_handling',side_effect=AssertionError('no global audit scan')):
            cycles=service.event_cycles(device_id='sim-pond-1')
        self.assertTrue(cycles)
        self.assertEqual({e['device_id'] for e in cycles},{'sim-pond-1'})
        self.assertEqual({(e['id'],e['lifecycle_state']) for e in cycles},
                         {(e['id'],e['lifecycle_state']) for e in self.service.event_cycles()})


if __name__ == '__main__':
    unittest.main()
