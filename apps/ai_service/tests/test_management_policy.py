"""Isolated Policy persistence/CAS; never touch the user's shared configuration."""
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import threading
from unittest.mock import patch

from apps.ai_backend.tools import ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicyError
from apps.ai_service.runtime.policy import UserToolPolicyStore
from apps.ai_service.management_policy import ManagementToolPolicyStore, _writer_lock
from apps.ai_service.business_tools.registry import FORMAL_TOOL_NAMES, WATER_QUALITY_SCORE
from apps.ai_service.business_tools.water_quality_history import WATER_QUALITY_HISTORY as HISTORY


class ManagementPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'policy'
        self.shared=UserToolPolicyStore(self.root,ToolRegistry([]))
        self.store=ManagementToolPolicyStore(self.root,self.shared)

    def test_no_startup_write_and_history_not_implicitly_authorized(self):
        self.assertFalse(self.root.exists())
        self.assertNotIn(HISTORY,self.store.snapshot().selected_tools)
        self.assertEqual(self.store.snapshot().source,'INHERITED_SHARED_POLICY')

    def test_first_save_preserves_choices_score_and_analysis_without_shared_write(self):
        value=self.shared.default_selections()
        value['modes']['assistant']['selected_tools']=[FORMAL_TOOL_NAMES[1],WATER_QUALITY_SCORE]
        self.shared.save(value); original=self.shared.path.read_bytes()
        initial=self.store.snapshot()
        saved=self.store.save([*initial.selected_tools,HISTORY],expected_revision=initial.revision)
        self.assertEqual(saved['selected_tools'],[*initial.selected_tools,HISTORY])
        self.assertEqual(self.shared.path.read_bytes(),original)
        # The legacy parser ignores the separate management file entirely.
        self.assertEqual(UserToolPolicyStore(self.root,ToolRegistry([])).load(),value)
        from fishery_ai.tools.policy import UserToolPolicyStore as PrototypePolicyStore
        from fishery_ai.tools.registry import ToolRegistry as PrototypeRegistry
        # Only static metadata is inspected; no domain Handler is executed.
        prototype_registry=PrototypeRegistry(None,None,scoring=object(),knowledge=object())
        self.assertEqual(PrototypePolicyStore(self.root,prototype_registry).load(),value)
        self.assertEqual(ManagementToolPolicyStore(self.root,self.shared).public(),saved)
        self.assertEqual(saved['source'],'MANAGEMENT_OVERRIDE')

    def test_cas_and_generation_prevent_stale_writer_and_aba(self):
        first=self.store.public()
        changed=self.store.save([HISTORY],expected_revision=first['revision'])
        for names in ([HISTORY],[],list(FORMAL_TOOL_NAMES)):
            with self.assertRaisesRegex(ToolPolicyError,'REVISION_MISMATCH'):
                self.store.save(names,expected_revision=first['revision'])
        restored=self.store.save(first['selected_tools'],expected_revision=changed['revision'])
        self.assertNotEqual(first['revision'],restored['revision'])

    def test_concurrent_stores_cannot_overwrite_same_revision(self):
        initial=self.store.public(); other=ManagementToolPolicyStore(self.root,self.shared)
        def write(store):
            try:
                store.save([HISTORY],expected_revision=initial['revision']); return 'saved'
            except ToolPolicyError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(write,(self.store,other)))
        self.assertEqual(results.count('saved'),1)
        self.assertTrue(set(results)-{'saved'} <= {'TOOL_POLICY_BUSY','TOOL_POLICY_REVISION_MISMATCH'})
        self.assertEqual(self.store.snapshot().generation,1)

    @unittest.skipUnless(os.name == 'nt', 'Windows byte-range locking')
    def test_first_lock_is_acquired_before_initialization_with_controlled_competitor(self):
        import msvcrt
        self.root.mkdir()
        path = self.root / '.management-policy.lock'
        acquired, release = threading.Event(), threading.Event()
        original = msvcrt.locking
        def pause_after_lock(fd, mode, count):
            original(fd, mode, count)
            if mode == msvcrt.LK_NBLCK and threading.current_thread().name == 'owner':
                acquired.set()
                if not release.wait(5):
                    raise RuntimeError('test interleaving timed out')
        failures = []
        def own():
            try:
                with _writer_lock(path):
                    pass
            except Exception as error:
                failures.append(error)
        with patch.object(msvcrt, 'locking', side_effect=pause_after_lock):
            owner = threading.Thread(target=own, name='owner')
            owner.start()
            try:
                self.assertTrue(acquired.wait(5))
                self.assertEqual(path.stat().st_size, 0)  # Locking beyond EOF.
                with self.assertRaisesRegex(ToolPolicyError, 'BUSY'):
                    self.store.save([], expected_revision=self.store.snapshot().revision)
                self.assertFalse(self.store.path.exists())
            finally:
                release.set(); owner.join(5)
        self.assertFalse(owner.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(path.read_bytes(), b'0')
        self.store.save([HISTORY], expected_revision=self.store.snapshot().revision)

    @unittest.skipUnless(os.name == 'nt', 'Windows byte-range locking')
    def test_lock_and_write_permission_errors_are_not_all_contention(self):
        import msvcrt
        for number, expected in ((errno.EACCES, 'BUSY'), (errno.EBADF, 'STORAGE_ERROR'),
                                 (errno.EPERM, 'STORAGE_ERROR')):
            with self.subTest(number=number), patch.object(msvcrt, 'locking',
                    side_effect=PermissionError(number, 'fake')), self.assertRaisesRegex(ToolPolicyError, expected):
                self.store.save([], expected_revision=self.store.snapshot().revision)
        # A permission failure in the protected write, rather than lock acquisition,
        # remains a genuine storage error and releases the lock.
        with patch('apps.ai_service.management_policy.os.replace',
                side_effect=PermissionError(errno.EACCES, 'fake')), self.assertRaisesRegex(ToolPolicyError, 'STORAGE_ERROR'):
            self.store.save([], expected_revision=self.store.snapshot().revision)
        self.store.save([], expected_revision=self.store.snapshot().revision)
        denied = PermissionError(errno.EACCES, 'fake');denied.winerror = 5
        with patch.object(msvcrt,'locking',side_effect=denied),self.assertRaisesRegex(ToolPolicyError,'STORAGE_ERROR'):
            self.store.save([],expected_revision=self.store.snapshot().revision)

    def test_invalid_values_never_write_and_corruption_fails_closed_on_restart(self):
        for names in (True,None,'get_water_quality_history',[HISTORY,HISTORY],['unknown'],[1]):
            with self.subTest(names=names),self.assertRaises(ToolPolicyError):
                self.store.save(names,expected_revision=self.store.snapshot().revision)
        self.assertFalse(self.root.exists())
        self.root.mkdir()
        for raw in (b'{',b'\xff',b'x'*8193,
                b'{"schema_version":1,"generation":1,"generation":2,"selected_tools":[]}',
                json.dumps({'schema_version':True,'generation':1,'selected_tools':[]}).encode()):
            self.store.path.write_bytes(raw)
            with self.assertRaises(ToolPolicyError): ManagementToolPolicyStore(self.root,self.shared)

    def test_atomic_failure_preserves_previous_configuration_and_cleans_temp(self):
        initial=self.store.save([],expected_revision=self.store.snapshot().revision)
        before=self.store.path.read_bytes()
        with patch('apps.ai_service.management_policy.os.replace',side_effect=OSError()), \
                self.assertRaises(ToolPolicyError):
            self.store.save([HISTORY],expected_revision=initial['revision'])
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_lock_busy_and_linked_files_fail_closed(self):
        self.root.mkdir()
        with _writer_lock(self.root/'.management-policy.lock'),self.assertRaisesRegex(ToolPolicyError,'BUSY'):
            self.store.save([],expected_revision=self.store.snapshot().revision)
        self.store.path.write_text('{}')
        import os
        os.link(self.store.path,self.root/'alias')
        with self.assertRaisesRegex(ToolPolicyError,'STORAGE_ERROR'): self.store.snapshot()
