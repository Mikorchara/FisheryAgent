"""Pause-boundary tests, not evidence that process isolation is implemented."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend import sdk_process_adapter as adapter
from apps.ai_backend import sdk_process_worker as worker
from apps.ai_backend.sdk_process_protocol import (
    Decoder, PAUSED_CODE, ProtocolError, decode, encode,
)


class SDKProcessPausedTests(unittest.TestCase):
    def test_adapter_always_refuses_before_initialization_or_io(self):
        script=adapter.OfflineSDKProcessScript((dict(mode='normal',response={},chunks=[],delay=0),))
        authorization=adapter.SDKProcessAuthorization(('fake',),lambda: self.fail('authorization called'))
        with patch.object(adapter.OpenAICompatibleAdapter,'__init__') as base, \
             patch.object(adapter.subprocess,'Popen') as spawn, \
             patch.object(adapter.socket,'socket') as socket, \
             patch.object(adapter,'SDKJob') as job:
            for kwargs in ({},{'offline':script},{'authorization':authorization}):
                with self.subTest(kwargs=tuple(kwargs)):
                    with self.assertRaisesRegex(GatewayError,'^'+PAUSED_CODE+'$'):
                        adapter.ProcessOpenAICompatibleAdapter(**kwargs)
            for action in (base,spawn,socket,job):action.assert_not_called()

    def test_direct_session_cannot_start_a_process(self):
        budget=adapter.SDKProcessBudget()
        lease=budget.reserve()
        try:
            session=adapter.ProcessSession(lease,RequestHandle(),startup=1,grace=.1,
                launcher=lambda *a,**kw: self.fail('process started'))
            with patch.object(adapter.socket,'socket') as socket, patch.object(adapter,'SDKJob') as job:
                with self.assertRaisesRegex(GatewayError,'^'+PAUSED_CODE+'$'):session.start(0,0)
                socket.assert_not_called();job.assert_not_called()
            self.assertIsNone(session.process)
        finally:budget.finish(lease)
        self.assertEqual(budget.snapshot()['active'],0)

    def test_worker_python_entries_refuse_before_input_or_network(self):
        with patch.object(worker.socket,'create_connection') as connect, \
             patch.object(worker,'read_async') as read, patch.object(worker,'write_async') as write:
            with self.assertRaisesRegex(ProtocolError,'^'+PAUSED_CODE+'$'):worker.main()
            for call in (worker.run(None,{}),worker.execute(None,{})):
                with self.assertRaisesRegex(ProtocolError,'^'+PAUSED_CODE+'$'):asyncio.run(call)
            for action in (connect,read,write):action.assert_not_called()

    def test_direct_worker_command_exits_without_waiting_for_bootstrap(self):
        env={name:os.environ[name] for name in ('SystemRoot','WINDIR','TEMP','TMP') if name in os.environ}
        result=subprocess.run([sys.executable,'-I','-B',str(Path(worker.__file__).resolve())],
            input=b'',stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
            timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,2)
        self.assertEqual(result.stdout,b'')
        self.assertEqual(result.stderr.decode().strip(),PAUSED_CODE)

    def test_draft_json_frames_round_trip_without_pickle(self):
        value={'v':1,'kind':'test','message':'fictional only'}
        frame=encode(value);decoder=Decoder()
        decoder.feed(frame[:3]);self.assertIsNone(decoder.pop())
        decoder.feed(frame[3:]);self.assertEqual(decoder.pop(),value)
        self.assertIsNone(decoder.pop())

    def test_draft_protocol_rejects_ambiguous_or_invalid_json(self):
        for body in (b'{"v":1,"v":1}',b'{"v":true}',b'{"v":2}',b'{"v":1,"x":NaN}',b'[]'):
            with self.subTest(body=body):
                with self.assertRaises(ProtocolError):decode(body)


if __name__=='__main__':unittest.main()
