"""Launcher checks and owned Windows consoles, fictional metadata and no QQ/Provider network."""
from contextlib import closing, redirect_stdout
import ctypes
from ctypes import wintypes as wt
from io import StringIO
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from scripts.dev import prototype_stack as stack, local_session
from apps.qq_bot.tests import test_session_run as fixture_module

ROOT = stack.ROOT


def alive(pid, terminate=False):
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]; k.OpenProcess.restype = wt.HANDLE
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]; k.CloseHandle.argtypes = [wt.HANDLE]
    k.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    h = k.OpenProcess(1 if terminate else 0x100000, False, pid)
    if not h: return False
    try:
        if terminate: k.TerminateProcess(h, 1); return True
        return k.WaitForSingleObject(h, 0) == 0x102
    finally: k.CloseHandle(h)


@unittest.skipUnless(os.name == 'nt', 'Windows console/job integration')
class PrototypeStackTests(unittest.TestCase):
    def setUp(self):
        connect_ex = socket.socket.connect_ex
        self.fixture = fixture_module.SessionRunTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        def loopback_only(connection, address):
            if address[0] != '127.0.0.1': raise AssertionError('no external network')
            return connect_ex(connection, address)
        local_probe = patch.object(socket.socket, 'connect_ex', loopback_only)
        local_probe.start(); self.addCleanup(local_probe.stop)
        self.root = self.fixture.root
        self.demo, self.config = self.root/'launcher-instance', self.root/'launcher-config'
        self.source = self.root/'original-request.json'
        self.source.write_text(json.dumps(self.fixture.inputs.dictionary()), encoding='utf8')
        for name, value in [('DEMO', self.demo), ('CONFIG', self.config), ('SOURCE', self.source)]:
            p = patch.object(stack, name, value); p.start(); self.addCleanup(p.stop)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); self.port = probe.getsockname()[1]

    def wait(self, condition, timeout=25):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            if condition(): return
            time.sleep(.1)
        self.fail('owned console condition timed out')

    def record(self, directory, role):
        try: return json.loads((directory/(role+'.status.json')).read_text())
        except (OSError, ValueError): return {}

    def count(self):
        with closing(sqlite3.connect((self.demo/'monitoring.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
            return db.execute('SELECT count(*) FROM batches').fetchone()[0]

    def test_prepare_references_metadata_without_touching_old_instance_and_refuses_partial(self):
        before = self.fixture.instance.joinpath('monitoring.sqlite3').read_bytes()
        original = self.source.read_bytes()
        stack.prepare_demo(True)
        self.assertEqual(self.fixture.instance.joinpath('monitoring.sqlite3').read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertTrue((self.demo/'knowledge.sqlite3').is_file())
        inputs, summary = stack.selected()
        self.assertEqual(inputs.access_file, self.fixture.inputs.access_file)
        self.assertEqual(inputs.ai_config, self.fixture.inputs.ai_config)
        self.assertEqual(inputs.policy_directory, self.fixture.inputs.policy_directory)
        self.assertEqual(summary['data_root'], str(self.demo))
        self.assertEqual(summary['instance_id'], 'prototype-daily')
        self.assertEqual(self.count(), 0)
        stack.prepare_demo(True)
        (self.demo/'knowledge.sqlite3').unlink()  # Newly created synthetic fixture only.
        with self.assertRaises(Exception): stack.prepare_demo(True)
        self.assertFalse((self.demo/'knowledge.sqlite3').exists())

    def test_check_never_opens_sqlite_credentials_or_network_and_unknown_directories_refused(self):
        from apps.ai_backend.credentials import CredentialStore
        with (patch('sqlite3.connect', side_effect=AssertionError('no database')),
              patch.object(CredentialStore, 'resolve', side_effect=AssertionError('no key')),
              patch('socket.create_connection', side_effect=AssertionError('no network'))):
            root, checked = stack.preflight(with_bot=True, port=self.port)
            self.assertEqual(root, self.demo)
            self.assertTrue(checked['prepare_required'])
            self.assertFalse(self.demo.exists())
            self.assertFalse(self.config.exists())
        self.demo.mkdir()
        with self.assertRaises(Exception): stack.prepare_demo()
        self.assertEqual(list(self.demo.iterdir()), [])
        with self.assertRaisesRegex(RuntimeError, 'PROTOTYPE_OUTPUT_PATH_REQUIRED'):
            stack.local_output(ROOT/'apps')

    def test_seven_menu_choices_default_retry_exit_and_old_cli_noninteractive(self):
        for n, expected in enumerate(local_session.DEMO_SCENARIOS, 1):
            self.assertEqual(local_session.choose_scenario(read=lambda _:str(n), emit=lambda _:None), expected)
        answers = iter(['bad', ''])
        self.assertEqual(local_session.choose_scenario(read=lambda _:next(answers), emit=lambda _:None)[0], 'normal')
        self.assertIsNone(local_session.choose_scenario(read=lambda _:'0', emit=lambda _:None))
        with patch.object(local_session, 'run_local', return_value=0) as run:
            self.assertEqual(local_session.main(['--scenario', 'low_oxygen']), 0)
            self.assertFalse(run.call_args.kwargs['show_terminals'])
            self.assertFalse(run.call_args.kwargs['interactive_scenario'])

    def test_original_hybrid_cli_still_requires_operator_approval_before_credentials_or_network(self):
        stack.prepare_demo(True)
        from apps.qq_bot.hybrid_trial_cli import main
        from apps.ai_backend.credentials import CredentialStore
        directory = self.root/'denied'; directory.mkdir()
        with patch('apps.qq_bot.session_run_trial_cli.console_challenge', return_value=False), \
             patch.object(CredentialStore, 'resolve', side_effect=AssertionError('no key')), \
             patch('socket.create_connection', side_effect=AssertionError('no network')), redirect_stdout(StringIO()):
            code = main(['--run', '--request-file', str(self.config/'request.json'), '--directory', str(directory),
                '--confirm-instance-read', '--confirm-provider-network', '--confirm-qq-network',
                '--enable-mention-ai', '--confirm-general-experimental'])
        self.assertEqual(code, 1)
        report = json.loads((directory/'result.json').read_text())
        self.assertEqual(report['code'], 'SESSION_OPERATOR_CANCELLED')
        self.assertEqual(report['quota']['consumed_turns'], 0)

    def start(self, *, menu_input=None, bot=True, interactive=True):
        stack.prepare_demo(bot)
        # Instrument only child creation. Fake Bot occupies a genuine third console;
        # product paths have no fake/auto-approval switch.
        inject = '''import sys,json,subprocess,asyncio
sys.path.insert(0,sys.argv.pop(1))
from pathlib import Path
base=Path(sys.argv.pop(1));answer=json.loads(sys.argv.pop(1))
from scripts.dev import prototype_stack as stack
stack.DEMO=base/'launcher-instance';stack.CONFIG=base/'launcher-config';stack.SOURCE=base/'original-request.json'
real=subprocess.Popen
fake="""import sys,types,time
sys.path.insert(0,sys.argv.pop(1))
module=types.ModuleType('apps.qq_bot.hybrid_trial_cli')
def run(args):
    assert '--run' in args and '--confirm-general-experimental' in args
    while True:time.sleep(.1)
module.main=run;sys.modules[module.__name__]=module
from scripts.dev.prototype_console import main
raise SystemExit(main())"""
def launch(command,**options):
    if '--role' in command:
        role=command[command.index('--role')+1]
        if role=='bot':
            at=next(i for i,v in enumerate(command) if v.endswith('prototype_console.py'))
            command=[*command[:at],'-c',fake,sys.path[0],*command[at+1:]]
        if role=='simulator' and answer is not None:options['stdin']=subprocess.PIPE
        child=real(command,**options)
        if role=='simulator' and answer is not None:
            child.stdin.write(answer.encode());child.stdin.close()
        return child
    return real(command,**options)
subprocess.Popen=launch
raise SystemExit(stack.main())'''
        log = self.root/('controller-'+str(time.monotonic_ns())+'.log')
        output = log.open('wb'); self.addCleanup(output.close)
        args = ['--port', str(self.port), '--no-assistant']  # No private credentials in console integration fixtures.
        if bot: args += ['--with-bot']
        if interactive: args += ['--interactive-scenario']
        child = subprocess.Popen([sys.executable, '-X', 'utf8', '-I', '-B', '-u', '-c', inject,
            str(ROOT), str(self.root), json.dumps(menu_input), *args], cwd=ROOT,
            stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        directory = [None]
        def cleanup():
            if directory[0] is not None: stack.request_stop(directory[0])
            try: child.wait(timeout=35)
            except subprocess.TimeoutExpired:
                if directory[0] is not None:
                    pid = json.loads((directory[0]/'stack.json').read_text())['controller_pid']
                    alive(pid, terminate=True)
                if child.poll() is None: child.terminate()
                child.wait(timeout=8)
        self.addCleanup(cleanup)
        def started():
            for line in log.read_text(encoding='utf8', errors='replace').splitlines():
                try: value = json.loads(line)
                except ValueError: continue
                if value.get('code') == 'PROTOTYPE_STACK_STARTING':
                    directory[0] = Path(value['run_directory']); return True
            return child.poll() is not None
        self.wait(started)
        self.assertIsNotNone(directory[0], log.read_text(encoding='utf8', errors='replace'))
        return child, directory[0]

    def test_three_consoles_menu_waits_stop_bot_leaves_pair_and_stops_owned_tree(self):
        child, directory = self.start()
        self.wait(lambda: all(self.record(directory, r).get('state') == 'RUNNING' for r in ('web', 'simulator', 'bot')))
        records = [self.record(directory, r) for r in ('web', 'simulator', 'bot')]
        self.assertEqual(len({r['pid'] for r in records}), 3)
        self.assertEqual(len({r['console_hwnd'] for r in records}), 3)
        time.sleep(10.5)
        self.assertEqual(self.count(), 0)
        stack.request_stop(directory, 'bot')
        self.wait(lambda:self.record(directory, 'bot').get('state') == 'EXITED')
        self.assertIsNone(child.poll())
        self.assertTrue(alive(self.record(directory, 'web')['pid']))
        stack.request_stop(directory); child.wait(timeout=35)
        self.wait(lambda:not any(alive(r['pid']) for r in records))

    def test_menu_selection_reports_and_bot_crash_leaves_web_simulator_running(self):
        child, directory = self.start(menu_input='bad\n7\n')
        self.wait(lambda:self.count()>0)
        self.assertIn('oxygen_drop_recovery', (directory/'simulator.log').read_text(encoding='utf8'))
        pid = self.record(directory, 'bot')['pid']; alive(pid, terminate=True)
        before = self.count(); self.wait(lambda:self.count()>before, timeout=16)
        self.assertIsNone(child.poll())
        stack.request_stop(directory); child.wait(timeout=35)
        self.assertNotEqual(child.returncode, 0)

    def test_menu_zero_exits_without_reporting_and_port_conflict_preserves_external_listener(self):
        child, directory = self.start(menu_input='0\n')
        child.wait(timeout=35)
        self.assertEqual(self.count(), 0)
        self.assertTrue((directory/'result.json').is_file())
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            with self.assertRaisesRegex(RuntimeError, 'LOCAL_PORT_IN_USE'):
                stack.preflight(port=listener.getsockname()[1])
            self.assertEqual(listener.getsockname()[0], '127.0.0.1')

    def test_powershell_relative_request_check_and_bom(self):
        stack.prepare_demo(True)
        request = str((self.config/'request.json').relative_to(ROOT))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-File',
            str(ROOT/'scripts/dev/Start-PrototypeStack.ps1'), '-Check', '-WithBot',
            '-RequestFile', request, '-Port', str(self.port)], cwd=ROOT, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertIn(b'PROTOTYPE_STACK_CHECKED', result.stdout)
        for name in ('Start-PrototypeStack.ps1', 'Stop-PrototypeStack.ps1', 'run_local.ps1'):
            self.assertTrue((ROOT/'scripts/dev'/name).read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_default_stack_enables_web_assistant_and_explicit_disable_is_retained(self):
        for options,expected in (([],True),(['--no-assistant'],False)):
            with patch.object(stack,'launch_stack',return_value=0) as launch:
                self.assertEqual(stack.main(options),0)
                self.assertEqual(launch.call_args.kwargs['assistant'],expected)
