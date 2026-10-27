"""New synthetic directories only; ownership uses real OS processes and handles."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.qq_bot.contracts import BotError
from apps.qq_bot.run_consent import RunLedger, RunLimits, RunOwner


class RunConsentTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.now=datetime(2026,10,27,tzinfo=timezone.utc);self.tick=0.

    def ledger(self,turns=5,total='8.02',**kwargs):
        ledger=RunLedger(self.root,scope_sha256='a'*64,bindings_sha256='b'*64,
            limits=RunLimits(max_turns=turns,total_budget_cny=total),clock=lambda:self.now,
            monotonic=lambda:self.tick,**kwargs)
        self.addCleanup(ledger.close);ledger.approve(ledger.plan(),confirmed=True);return ledger

    def reserve(self,ledger,key='message',member='member-a'):
        return ledger.reserve(message_key=key,fingerprint=key,member_id=member,
            instance_id='instance',device_id='pond',app_id='app',group_id='group')

    def test_five_reservations_are_decimal_conservative_and_not_refunded(self):
        ledger=self.ledger()
        for i in range(5):ledger.check_lease(self.reserve(ledger,str(i)))
        state=ledger.report()
        self.assertEqual(state['reserved_cost_cny'],'8.013825')
        self.assertEqual(state['reserved_model_requests'],10)
        with self.assertRaisesRegex(BotError,'RUN_TURN_LIMIT'):self.reserve(ledger,'six')
        self.assertEqual(state,ledger.report())

    def test_budget_insufficient_does_not_reduce_turn_count(self):
        with self.assertRaisesRegex(BotError,'RUN_BUDGET_INSUFFICIENT'):self.ledger(total='2.00')

    def test_one_to_five_turn_limits_and_no_float_budget(self):
        for n in range(1,6):self.assertEqual(RunLimits(max_turns=n).max_turns,n)
        for n in (0,6,True,2.0):
            with self.assertRaises(BotError):RunLimits(max_turns=n)
        with self.assertRaises(BotError):RunLimits(total_budget_cny=8.02)

    def test_duplicate_whole_run_and_conflicting_fingerprint(self):
        ledger=self.ledger();lease=self.reserve(ledger)
        with self.assertRaisesRegex(BotError,'RUN_MESSAGE_ALREADY_USED'):self.reserve(ledger)
        with self.assertRaisesRegex(BotError,'RUN_MESSAGE_CONFLICT'):
            ledger.reserve(message_key='message',fingerprint='changed',member_id='member-a',
                instance_id='instance',device_id='pond',app_id='app',group_id='group')
        ledger.check_lease(lease);self.assertEqual(ledger.report()['consumed_turns'],1)

    def test_two_members_race_last_slot(self):
        ledger=self.ledger(turns=1)
        def run(i):
            try:self.reserve(ledger,str(i),'member-'+str(i));return 'OK'
            except BotError as error:return error.code
        with ThreadPoolExecutor(max_workers=4) as pool:codes=list(pool.map(run,range(4)))
        self.assertEqual(codes.count('OK'),1);self.assertEqual(ledger.report()['consumed_turns'],1)

    def test_last_issued_lease_is_valid_after_balance_empty(self):
        ledger=self.ledger(turns=1);lease=self.reserve(ledger)
        with self.assertRaises(BotError):ledger.can_admit()
        ledger.check_lease(lease)

    def test_expiry_uses_wall_and_monotonic_and_cannot_rearm(self):
        ledger=self.ledger();lease=self.reserve(ledger);self.tick=1800
        with self.assertRaisesRegex(BotError,'RUN_EXPIRED'):ledger.check_lease(lease)
        self.tick=0
        with self.assertRaisesRegex(BotError,'RUN_EXPIRED'):ledger.can_admit()

    def test_wall_expiry_and_close_reject_old_lease(self):
        ledger=self.ledger();lease=self.reserve(ledger);self.now+=timedelta(minutes=31)
        with self.assertRaises(BotError):ledger.check_lease(lease)
        ledger.close()
        with self.assertRaises(BotError):ledger.check_lease(lease)

    def test_forged_lease_and_json_consent_are_not_execution_authority(self):
        ledger=self.ledger();lease=self.reserve(ledger)
        with self.assertRaises(Exception):ledger.check_lease(replace(lease,sequence=2))
        with self.assertRaises(BotError):ledger.approve(json.loads(json.dumps(ledger.plan())),confirmed=True)
        with self.assertRaises(BotError):ledger.approve(ledger.plan(),confirmed=False)

    def test_ledger_write_failure_and_fsync_failure_are_sticky(self):
        ledger=self.ledger()
        with patch.object(ledger,'_append',side_effect=OSError('fake failure')):
            with self.assertRaisesRegex(BotError,'RUN_LEDGER_FAILED'):self.reserve(ledger)
        with self.assertRaisesRegex(BotError,'RUN_LEDGER_FAILED'):self.reserve(ledger,'new')

    def test_fsync_failure_prevents_lease_and_keeps_consumption(self):
        ledger=self.ledger()
        with patch('apps.qq_bot.run_consent.os.fsync',side_effect=OSError('fake fsync')):
            with self.assertRaisesRegex(BotError,'RUN_LEDGER_FAILED'):self.reserve(ledger)
        self.assertEqual(ledger.report()['consumed_turns'],1)
        self.assertEqual(ledger.report()['state'],'HALTED')

    def test_io_is_not_inside_budget_lock(self):
        ledger=self.ledger();append=ledger._append
        def check(record):
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(ledger.report).result(timeout=1)['consumed_turns'],1)
            return append(record)
        with patch.object(ledger,'_append',side_effect=check):self.reserve(ledger)

    def test_missing_or_changed_journal_stops_run(self):
        ledger=self.ledger();self.reserve(ledger)
        with patch.object(ledger,'_journal_intact',return_value=False):
            with self.assertRaisesRegex(BotError,'RUN_LEDGER_FAILED'):self.reserve(ledger,'new')
        with self.assertRaises(BotError):ledger.check()

    def child(self,body,*args):
        return subprocess.run([sys.executable,'-X','utf8','-B','-c',body,*map(str,args)],
            cwd=Path(__file__).resolve().parents[3],capture_output=True,text=True,timeout=15)

    def test_real_other_process_cannot_claim_same_approval_live_or_after_close(self):
        owner=RunOwner(self.root,'c'*32,'d'*64);self.addCleanup(owner.close)
        code="from pathlib import Path;import sys;from apps.qq_bot.run_consent import RunOwner;from apps.qq_bot.contracts import BotError\ntry:\n o=RunOwner(Path(sys.argv[1]),'c'*32,'d'*64);o.close();print('BAD')\nexcept BotError as e:print(e.code)"
        self.assertEqual(self.child(code,self.root).stdout.strip(),'RUN_APPROVAL_ALREADY_USED')
        owner.close()
        self.assertEqual(self.child(code,self.root).stdout.strip(),'RUN_APPROVAL_ALREADY_USED')

    def test_crashed_owner_releases_handle_but_not_one_use_claim(self):
        code="from pathlib import Path;import os,sys;from apps.qq_bot.run_consent import RunOwner;o=RunOwner(Path(sys.argv[1]),'e'*32,'f'*64);os._exit(0)"
        result=self.child(code,self.root);self.assertEqual(result.returncode,0)
        with self.assertRaisesRegex(BotError,'RUN_APPROVAL_ALREADY_USED'):RunOwner(self.root,'e'*32,'f'*64)

    def test_two_real_processes_compete_for_one_new_claim(self):
        code="from pathlib import Path;import sys;from apps.qq_bot.run_consent import RunOwner;from apps.qq_bot.contracts import BotError\nsys.stdin.readline()\ntry:\n o=RunOwner(Path(sys.argv[1]),'3'*32,'4'*64);print('CREATED',flush=True);o.close()\nexcept BotError as e:print(e.code,flush=True)"
        children=[subprocess.Popen([sys.executable,'-B','-c',code,str(self.root)],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=Path(__file__).resolve().parents[3]) for _ in range(2)]
        try:
            for child in children:child.stdin.write('GO\n');child.stdin.flush()
            results=[child.communicate(timeout=15) for child in children]
            self.assertEqual(sorted(out.strip() for out,_ in results),['CREATED','RUN_APPROVAL_ALREADY_USED'])
            self.assertTrue(all(child.returncode==0 for child in children))
        finally:
            for child in children:
                if child.poll() is None:child.terminate();child.wait(timeout=5)

    def test_new_run_cannot_import_old_plan_even_when_claim_file_copied(self):
        ledger=self.ledger();old=ledger.plan();self.reserve(ledger);ledger.close()
        other=RunLedger(self.root,scope_sha256='a'*64,bindings_sha256='b'*64)
        self.addCleanup(other.close)
        with self.assertRaisesRegex(BotError,'INVALID_RUN_APPROVAL'):other.approve(old,confirmed=True)
        self.assertEqual(other.report()['state'],'UNAPPROVED')

    @unittest.skipUnless(os.name=='nt','Windows share/delete semantics')
    def test_windows_live_claim_cannot_be_deleted_or_renamed(self):
        owner=RunOwner(self.root,'1'*32,'2'*64);self.addCleanup(owner.close)
        with self.assertRaises(OSError):owner.path.unlink()
        with self.assertRaises(OSError):owner.path.rename(self.root/'renamed')
        owner.check()

    def test_existing_consent_rejects_forked_or_other_process_identity(self):
        ledger=self.ledger()
        with patch('apps.qq_bot.run_consent.os.getpid',return_value=-1):
            with self.assertRaisesRegex(BotError,'RUN_PROCESS_MISMATCH'):ledger.check()

