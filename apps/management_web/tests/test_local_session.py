"""Exercise owned process lifecycle and real ten-second simulator HTTP locally."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen
from scripts.dev import local_session as entry


class LocalSessionTests(unittest.TestCase):
    def test_defaults_enable_only_approved_trials_and_switches_retain_original_cli(self):
        server,simulator=entry.commands('python','low_oxygen',8766,42)
        for flag in ('--enable-assistant','--assistant-streaming-trial','--assistant-multi-round-trial','--assistant-history-trial'):
            self.assertIn(flag,server)
        self.assertFalse(any('selection' in arg or 'candidate' in arg for arg in server))
        self.assertEqual(simulator[-2:],['--interval','10'])
        self.assertNotIn('--assistant-streaming-trial',entry.commands('python','normal',8766,42,streaming=False)[0])
        self.assertFalse(any('assistant' in arg for arg in entry.commands('python','normal',8766,42,assistant=False)[0]))

    def test_real_local_start_report_duplicate_rejection_and_interrupt_cleanup(self):
        with TemporaryDirectory() as temporary, socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1];reserve.close()
            children,output,commands=[],[],[]
            def launch(command,**kwargs):
                commands.append(command)
                if command[2]=='apps.management_web':
                    command=[sys.executable,str(Path(__file__).with_name('local_session_fixture.py')),
                             '--directory',temporary,'--port',str(port)]
                child=subprocess.Popen(command,**kwargs);children.append(child);return child
            started=time.monotonic();observed=False;checked=False
            def wait(seconds):
                nonlocal observed,checked
                if len(children)==2 and not checked:
                    with self.assertRaisesRegex(RuntimeError,'LOCAL_PORT_IN_USE'):
                        entry.require_free_port(port)
                    checked=True
                if len(children)==2 and time.monotonic()-started > 10:
                    with urlopen(f'http://127.0.0.1:{port}/api/monitoring',timeout=1) as response:
                        value=json.load(response)
                    observed='window_mean' in json.dumps(value) and 'simulator' in json.dumps(value)
                    if observed:raise KeyboardInterrupt()
                if time.monotonic()-started > 18:
                    raise AssertionError('ten-second report not observed')
                time.sleep(seconds)
            result=entry.run_local('low_oxygen',port,launch=launch,sleep=wait,emit=output.append)
            self.assertEqual(result,0);self.assertTrue(observed);self.assertTrue(checked)
            self.assertEqual(len(children),2);self.assertTrue(all(p.poll() is not None for p in children))
            deadline=time.monotonic()+2
            while True:
                try:
                    entry.require_free_port(port);break
                except RuntimeError:
                    if time.monotonic()>=deadline:raise
                    time.sleep(.05)  # Windows listener teardown can trail process exit.
            self.assertTrue((Path(temporary)/'isolated.sqlite3').is_file())
            self.assertNotIn('FISHERY_SIM_INGEST_TOKEN',''.join(output))

    def test_occupied_port_never_launches_or_kills_any_process(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
            with patch.object(entry.subprocess,'Popen') as launch,self.assertRaisesRegex(RuntimeError,'LOCAL_PORT_IN_USE'):
                entry.run_local(port=port,launch=launch)
            launch.assert_not_called()
            self.assertEqual(listener.getsockname()[1],port)

    def test_server_start_failure_cleans_only_owned_child(self):
        class Child:
            def poll(self):return 1
            def wait(self,timeout):return 1
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1];reserve.close()
            with self.assertRaisesRegex(RuntimeError,'LOCAL_SERVER_START_FAILED'):
                entry.run_local(port=port,launch=lambda *a,**kw:Child(),is_ready=lambda p:False)
