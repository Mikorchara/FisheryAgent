"""Lexical cache only: no TTL, cross-thread sharing or execution I/O scope."""
from contextvars import copy_context
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import os
import threading
import unittest
from unittest.mock import patch

from apps.ai_service.channel_validation import (ValidationBoundary,implementation_sha256,
    validation_active,validation_once)


class ValidationBoundaryTests(unittest.TestCase):
    def test_reuses_only_within_same_boundary_and_preserves_same_mtime_changes(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'code.py';path.write_bytes(b'old')
            boundary=ValidationBoundary();original=Path.read_bytes
            with patch.object(Path,'read_bytes',autospec=True,side_effect=original) as read:
                with boundary.scope():
                    first=implementation_sha256(path)
                    with boundary.scope():self.assertEqual(first,implementation_sha256(path))
                self.assertEqual(read.call_count,1)
                stat=path.stat();path.write_bytes(b'new');os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                with boundary.scope():self.assertNotEqual(first,implementation_sha256(path))
                self.assertEqual(read.call_count,2)
            self.assertFalse(validation_active())

    def test_copied_context_in_another_thread_does_not_share_snapshot(self):
        boundary=ValidationBoundary();calls=[]
        with boundary.scope():
            validation_once('key',lambda:calls.append('parent'))
            context=copy_context()
            def work():
                self.assertFalse(validation_active())
                validation_once('key',lambda:calls.append('worker'))
            thread=threading.Thread(target=lambda:context.run(work));thread.start();thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(calls,['parent','worker'])

    def test_failed_check_is_not_cached_and_context_always_closes(self):
        boundary=ValidationBoundary()
        with self.assertRaises(ValueError),boundary.scope():
            validation_once('failure',lambda:(_ for _ in ()).throw(ValueError()))
        self.assertFalse(validation_active())
        with boundary.scope():self.assertEqual(validation_once('failure',lambda:17),17)

    def test_other_authority_and_later_boundary_receive_fresh_evidence(self):
        a,b=ValidationBoundary(),ValidationBoundary();calls=[]
        with a.scope():
            validation_once('key',lambda:calls.append(1))
            with b.scope():validation_once('key',lambda:calls.append(2))
            validation_once('key',lambda:calls.append(3))
        with a.scope():validation_once('key',lambda:calls.append(4))
        self.assertEqual(calls,[1,2,4])
