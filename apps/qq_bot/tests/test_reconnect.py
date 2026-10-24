"""Loopback Gateway only; inject stalled I/O without disconnecting Windows networking."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import threading
import time
import unittest
from unittest.mock import Mock

from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.contracts import BotConfig, GroupAccess
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.tests.test_gateway import APP, GROUP, MEMBER, ready, event


class InterruptedSocket:
    """A stalled send/read only unblocks on underlying socket shutdown or test cleanup."""
    def __init__(self, socket):
        self.original = socket
        self.enabled = threading.Event()
        self.blocked = threading.Event()
        self.released = threading.Event()
        self.aborted = threading.Event()

    def __getattr__(self, name):
        return getattr(self.original, name)

    def wait(self):
        self.blocked.set()
        self.released.wait()  # Test finally always releases; production guard must abort sooner.

    def sendall(self, data, *args, **kwargs):
        if self.enabled.is_set():
            self.wait()
        return self.original.sendall(data, *args, **kwargs)

    def shutdown(self, how):
        self.aborted.set()
        self.released.set()
        return self.original.shutdown(how)

    def close(self):
        self.released.set()
        return self.original.close()


class ReconnectTests(unittest.TestCase):
    @contextmanager
    def local_gateway(self, mode, seconds=12):
        try:
            from websockets.sync.client import connect
            from websockets.sync.server import serve
        except ImportError:
            self.skipTest('optional QQ dependency not installed')
        codes, packets, failures, connections = [], [], [], []
        timed_out, replied_after_resume = threading.Event(), threading.Event()
        fault = None
        accepts = 0
        first_timestamp = None
        def handler(ws):
            nonlocal accepts, first_timestamp
            accepts += 1
            connection_number = accepts
            try:
                ws.send('{"op":10,"d":{"heartbeat_interval":1000}}')
                identify = json.loads(ws.recv(timeout=3))
                packets.append(identify)
                if connection_number == 1:
                    ws.send(json.dumps(ready()))
                    first = event(msg_id='before-outage')
                    first['d']['timestamp'] = datetime.now(timezone.utc).isoformat()
                    first_timestamp = first['d']['timestamp']
                    ws.send(json.dumps(first))
                elif mode == 'reidentify' and connection_number == 2:
                    ws.send('{"op":9,"d":false}')
                    ws.recv(timeout=3)  # Client must close this invalid Resume session.
                    return
                else:
                    if mode == 'reidentify':
                        ws.send(json.dumps(ready()))
                    # Resume backlog precedes RESUMED, including an already-seen message ID.
                    for seq, msg_id in ((3, 'before-outage'), (4, 'after-outage')):
                        value = event(seq=seq, msg_id=msg_id)
                        value['d']['timestamp'] = first_timestamp if msg_id == 'before-outage' else datetime.now(timezone.utc).isoformat()
                        ws.send(json.dumps(value))
                    if mode != 'reidentify':
                        ws.send('{"op":0,"s":5,"t":"RESUMED","d":""}')
                while True:
                    message = json.loads(ws.recv(timeout=5))
                    packets.append(message)
                    if connection_number > 1 and message['op'] == 1:
                        ws.send('{"op":11}')
                    # First connection is a blackhole: no ACK, EOF or application errors.
            except Exception:
                pass
        config = BotConfig(APP, (GroupAccess(GROUP, 'sim-pond-1', (MEMBER,), ()),))
        adapter = QQAdapter(config, ReadOnlyQueries(None, None, live=True), mode='QQ_PASSIVE_READY')
        api = Mock(app_id=APP)
        api.token.return_value = 'fictional-token'
        api.gateway.return_value = 'wss://api.bot.qq.com/websocket/'
        replies = []
        def reply(value, **kw):
            replies.append(value.msg_id)
            if value.msg_id == 'after-outage' and ('QQ_GATEWAY_RESUMED' in codes or
                    mode == 'reidentify' and codes.count('QQ_GATEWAY_READY') >= 2):
                replied_after_resume.set()
        api.reply.side_effect = reply
        def emit(code, **kw):
            codes.append(code)
            if code == 'QQ_GATEWAY_READY' and fault is not None:
                fault.enabled.set()
            if (code == 'QQ_GATEWAY_RESUMED' or mode == 'reidentify' and code == 'QQ_GATEWAY_READY') and 'after-outage' in replies:
                replied_after_resume.set()
            if code in ('HEARTBEAT_TIMEOUT', 'GATEWAY_CLOSE_TIMEOUT', 'QQ_RUN_DURATION_REACHED'):
                timed_out.set()
        with serve(handler, '127.0.0.1', 0) as server:
            serving = threading.Thread(target=server.serve_forever)
            serving.start()
            address = 'ws://127.0.0.1:'+str(server.socket.getsockname()[1])
            def connector(_):
                nonlocal fault
                raw = connect(address, proxy=None, ping_interval=None, close_timeout=2)
                connections.append(raw)
                if len(connections) == 1 and mode in ('send', 'recv', 'close'):
                    fault = InterruptedSocket(raw.socket)
                    raw.socket = fault
                    if mode == 'recv':
                        original_recv = raw.recv
                        def recv(*args, **kwargs):
                            if fault.enabled.is_set():
                                fault.wait()  # Model recv's internal join after EOF.
                            return original_recv(*args, **kwargs)
                        raw.recv = recv
                    elif mode == 'close':
                        original_close = raw.close
                        def close(*args, **kwargs):
                            fault.wait()  # Model a close waiting for the protocol lock.
                            return original_close(*args, **kwargs)
                        raw.close = close
                    if mode != 'send':
                        fault.sendall = fault.original.sendall
                return raw
            gateway = QQGateway(APP, api, adapter, connector=connector, emit=emit)
            def run():
                try:
                    gateway.run(seconds)
                except Exception as error:
                    failures.append(getattr(error, 'code', type(error).__name__))
            running = threading.Thread(target=run)
            started = time.monotonic()
            running.start()
            try:
                yield codes, packets, replies, timed_out, replied_after_resume, started, lambda: fault
            finally:
                gateway.stop.set()
                if fault is not None:
                    fault.released.set()
                for connection in connections:
                    try:
                        connection.socket.shutdown(2)
                    except OSError:
                        pass
                running.join(4)
                server.shutdown()
                serving.join(3)
                self.assertFalse(running.is_alive(), 'Gateway must not outlive test cleanup')
                self.assertFalse(serving.is_alive())
                self.assertFalse(gateway._worker.is_alive())
                self.assertTrue(all(not connection.recv_events_thread.is_alive() for connection in connections))
                self.assertFalse(any(t.name == 'qq-ws-deadline' for t in threading.enumerate()))
                self.assertEqual(failures, [])

    def test_blocked_write_is_detected_without_relying_on_recv_timeout(self):
        with self.local_gateway('send') as (codes, packets, replies, expired, restored, started, get_fault):
            self.assertTrue(expired.wait(3.5), 'stalled heartbeat send stayed silent beyond ACK deadline')
            self.assertTrue(get_fault().aborted.wait(.5))
            self.assertTrue(restored.wait(4), 'new messages must work after Resume')
            self.assertIn('QQ_GATEWAY_RESUMED', codes)
            self.assertEqual(replies.count('after-outage'), 1)

    def test_blackhole_missing_ack_reconnects_and_restores_queue(self):
        with self.local_gateway('blackhole') as (codes, packets, replies, expired, restored, started, get_fault):
            self.assertTrue(expired.wait(3.5))
            self.assertTrue(restored.wait(4))
            self.assertLess(time.monotonic()-started, 8)
            self.assertEqual(packets[0]['op'], 2)
            self.assertTrue(any(p['op'] == 6 for p in packets))
            self.assertEqual(replies.count('before-outage'), 1)
            self.assertEqual(replies.count('after-outage'), 1)
            self.assertIn('DUPLICATE', codes)

    def test_stuck_recv_join_is_aborted_and_reconnected(self):
        with self.local_gateway('recv') as (codes, packets, replies, expired, restored, started, get_fault):
            self.assertTrue(expired.wait(3.5))
            self.assertTrue(get_fault().aborted.wait(.5))
            self.assertTrue(restored.wait(4))

    def test_stuck_close_does_not_hide_timeout_or_block_reconnect(self):
        with self.local_gateway('close') as (codes, packets, replies, expired, restored, started, get_fault):
            self.assertTrue(expired.wait(5), 'close must not hide the heartbeat timeout indefinitely')
            self.assertTrue(restored.wait(4))
            self.assertIn('GATEWAY_CLOSE_TIMEOUT', codes)

    def test_invalid_resume_reidentifies_and_accepts_new_messages(self):
        with self.local_gateway('reidentify') as (codes, packets, replies, expired, restored, started, get_fault):
            self.assertTrue(expired.wait(3.5))
            self.assertTrue(restored.wait(5))
            self.assertEqual([p['op'] for p in packets if p['op'] in (2, 6)], [2, 6, 2])
            self.assertEqual(replies.count('before-outage'), 1)
            self.assertEqual(replies.count('after-outage'), 1)

    def test_run_duration_also_bounds_stalled_io_and_does_not_retry(self):
        with self.local_gateway('recv', seconds=1) as (codes, packets, replies, expired, restored, started, get_fault):
            self.assertTrue(expired.wait(2.5))
            self.assertIn('QQ_RUN_DURATION_REACHED', codes)
            self.assertTrue(get_fault().aborted.wait(.5))
            self.assertEqual([p['op'] for p in packets if p['op'] in (2, 6)], [2])


if __name__ == '__main__':
    unittest.main()
