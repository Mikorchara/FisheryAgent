"""Only subprocess mocks; no Provider, credentials, user data, or real child runs."""
from contextlib import redirect_stderr
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.manual_real_tests import run_qualification as entry


class ManualTestEntryTests(unittest.TestCase):
    def test_defaults_to_one_original_cli_dry_run(self):
        for target, filename in entry.TARGETS.items():
            with self.subTest(target=target), patch.object(entry.subprocess, 'run',
                    return_value=SimpleNamespace(returncode=0)) as child:
                self.assertEqual(entry.main(['--target', target, '--case', 'valid-history']), 0)
                child.assert_called_once()
                command = child.call_args.args[0]
                self.assertEqual(command, [entry.sys.executable, str(entry.ROOT/'scripts/qualification'/filename),
                                          '--case', 'valid-history', '--dry-run'])
                self.assertEqual(child.call_args.kwargs, {'cwd': entry.ROOT})

    def test_explicit_confirmation_and_hash_are_forwarded_once_not_stored(self):
        with patch.object(entry.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as child:
            code = entry.main(['--target', 'management-history', '--case', 'partial-history',
                              '--confirm-network', '--plan-sha256', 'a'*64, '--review-answer'])
        self.assertEqual(code, 1)
        child.assert_called_once()
        self.assertEqual(child.call_args.args[0][-4:], ['--confirm-network', '--plan-sha256', 'a'*64, '--review-answer'])
        self.assertNotIn('--dry-run', child.call_args.args[0])
        self.assertNotIn('shell', child.call_args.kwargs)

    def test_bad_consent_target_and_argument_injection_never_start_child(self):
        base = ['--target', 'management-history', '--case', 'valid-history']
        for extra in (['--confirm-network'], ['--confirm-network', '--plan-sha256', 'stale'],
                      ['--dry-run', '--confirm-network'], ['--review-answer'],
                      ['--confirm-net'], ['--case', '--confirm-network'], ['--target', '../unexpected.py']):
            with self.subTest(extra=extra), patch.object(entry.subprocess, 'run') as child, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit): entry.main(base + extra)
                child.assert_not_called()

    def test_child_error_is_preserved_without_retry(self):
        with patch.object(entry.subprocess, 'run', return_value=SimpleNamespace(returncode=2)) as child:
            self.assertEqual(entry.main(['--target', 'management-streaming', '--case', 'current-water']), 2)
        child.assert_called_once()

    def test_wrong_workspace_never_starts_child(self):
        with patch.object(entry.Path, 'cwd', return_value=entry.ROOT.parent), \
                patch.object(entry.subprocess, 'run') as child, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                entry.main(['--target', 'management-history', '--case', 'no-data'])
        child.assert_not_called()
