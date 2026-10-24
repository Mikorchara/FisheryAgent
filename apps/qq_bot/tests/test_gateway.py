"""Gateway lifecycle with fake QQ frames; local socket test never reaches QQ."""
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from io import StringIO
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.contracts import BotConfig, BotError, GroupAccess
from apps.qq_bot.gateway import QQGateway, INTENTS, audit, normalize
from apps.qq_bot.offline import packet
from apps.qq_bot.service import ReadOnlyQueries

APP, GROUP, MEMBER = '123456789', 'fictional-group', 'fictional-member'
NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


def event(command='help', seq=2, **options):
    value = json.loads(packet(command, NOW, **options))
    value['s'] = seq
    return value


def ready(seq=1):
    return {'op': 0, 's': seq, 't': 'READY', 'd': {'session_id': 'session-fixture',
        'user': {'id': 'bot-fixture'}, 'application': {'id': APP}}}


class Clock:
    value = 0.0
    def __call__(self):
        return self.value


class FakeSocket:
    def __init__(self, clock, frames=(), ack=True):
        self.clock, self.frames, self.ack = clock, list(frames), ack
        self.sent = []
    def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        if value['op'] == 1 and self.ack:
            self.frames.append({'op': 11})
    def recv(self, timeout):
        if self.frames:
            value = self.frames.pop(0)
            if isinstance(value, Exception):
                raise value
            return json.dumps(value)
        self.clock.value += timeout
        raise TimeoutError()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock(app_id=APP)
        self.api.token.return_value = 'fictional-token'
        self.api.gateway.return_value = 'wss://api.bot.qq.com/websocket/'
        self.config = BotConfig(APP, (GroupAccess(GROUP, 'sim-pond-1', (MEMBER,), ()),))
        self.queries = ReadOnlyQueries(None, None, live=True)
        self.adapter = QQAdapter(self.config, self.queries, mode='QQ_PASSIVE_READY', clock=lambda: NOW)
        self.codes, self.found = [], []
        self.clock = Clock()
        self.gateway = self.make()

    def make(self, **options):
        return QQGateway(APP, self.api, options.pop('adapter', self.adapter),
            emit=lambda code, **kw: self.codes.append(code), clock=lambda: NOW,
            monotonic=self.clock, **options)

    def worker(self):
        self.gateway._worker = threading.Thread(target=self.gateway._work)
        self.gateway._worker.start()
        def cleanup():
            self.gateway.stop.set()
            self.gateway._worker.join(3)
            self.assertFalse(self.gateway._worker.is_alive())
        self.addCleanup(cleanup)

    def dispatch(self, value):
        self.gateway._dispatch(value)
        self.gateway._queue.join()

    def test_live_help_reuses_adapter_and_passive_context(self):
        self.worker()
        self.dispatch(event())
        reply = self.api.reply.call_args.args[0]
        self.assertIn('BOT-1B', reply.content)
        self.assertNotIn('OFFLINE', reply.content)
        self.assertEqual(self.api.reply.call_args.kwargs, {'received_at': NOW, 'now': NOW})

    def test_group_and_member_denied_before_any_query_or_reply(self):
        self.worker()
        with patch.object(self.queries, 'execute', side_effect=AssertionError('no query')):
            self.dispatch(event(group='unknown'))
            self.dispatch(event(member='unknown'))
        self.assertEqual(self.codes, ['GROUP_DENIED', 'MEMBER_DENIED'])
        self.api.reply.assert_not_called()

    def test_metadata_token_is_discarded_and_only_own_mention_stripped(self):
        value = event('<@!bot-fixture> help')
        value['d']['message_scene'] = {'auth_token': 'PRIVATE-METADATA'}
        value['d']['author']['member_role'] = 'owner'
        raw, message = normalize(value, 'bot-fixture')
        self.assertEqual(message.content, 'help')
        self.assertNotIn(b'PRIVATE', raw)
        self.assertNotIn(b'member_role', raw)
        _, other = normalize(event('<@someone-else> help'), 'bot-fixture')
        self.assertEqual(other.content, '<@someone-else> help')

    def test_attachments_bot_and_nontext_fail_closed(self):
        for key, value in (('attachments', [{}]), ('ark_data', {'x': 1}), ('msg_elements', [{}]),
                           ('message_type', 2)):
            body = event(); body['d'][key] = value
            with self.subTest(key=key), self.assertRaises(BotError):
                normalize(body)
        body = event(); body['d']['author']['bot'] = True
        with self.assertRaisesRegex(BotError, 'BOT_MESSAGE_IGNORED'):
            normalize(body)

    def test_duplicate_fresh_sequence_does_not_reply_twice(self):
        self.worker()
        self.dispatch(event(seq=2))
        self.dispatch(event(seq=3))
        self.assertEqual(self.api.reply.call_count, 1)
        self.assertIn('DUPLICATE', self.codes)

    def test_shared_rate_limit_and_read_capabilities_still_apply(self):
        self.worker()
        for n in range(7):
            self.dispatch(event('/当前水质', msg_id='fixture-'+str(n)))
        self.assertEqual(self.api.reply.call_count, 6)
        self.assertEqual(self.codes.count('CAPABILITY_DENIED'), 6)
        self.assertIn('RATE_LIMITED', self.codes)

    def test_group_removal_revokes_queued_and_later_messages(self):
        self.gateway._dispatch(event())
        self.gateway._dispatch({'t': 'GROUP_DEL_ROBOT', 'd': {'group_openid': GROUP}})
        self.worker()
        self.gateway._queue.join()
        self.dispatch(event(msg_id='later'))
        self.api.reply.assert_not_called()
        self.assertIn('QQ_GROUP_REMOVED', self.codes)

    def test_queue_is_bounded(self):
        for n in range(10):
            self.gateway._dispatch(event(msg_id='fixture-'+str(n)))
        self.assertEqual(self.gateway._queue.qsize(), 4)
        self.assertEqual(self.codes.count('QQ_QUEUE_FULL'), 6)

    def test_discovery_has_no_business_adapter_or_replies_and_is_bounded(self):
        gateway = self.make(adapter=None, discover=lambda *pair: self.found.append(pair))
        for n in range(15):
            gateway._dispatch(event(member='member-'+str(n)))
        self.assertEqual(len(self.found), 10)
        self.api.reply.assert_not_called()
        self.assertIsNone(gateway._worker)

    def test_identify_ready_heartbeat_and_sequence_dedup(self):
        self.gateway._deadline = 3.1
        socket = FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': 1000}},
                                        ready(), event(), event()])
        with patch.object(self.gateway, '_dispatch') as dispatch:
            self.gateway._pump(socket)
        self.assertEqual(socket.sent[0], {'op': 2, 'd': {'token': 'QQBot fictional-token',
            'intents': INTENTS, 'shard': [0, 1]}})
        dispatch.assert_called_once()
        self.assertTrue(any(p == {'op': 1, 'd': 2} for p in socket.sent))
        self.assertIn('QQ_GATEWAY_READY', self.codes)

    def test_missing_heartbeat_ack_requests_reconnect(self):
        self.gateway._deadline = 5
        socket = FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': 1000}}, ready()], ack=False)
        with self.assertRaisesRegex(BotError, 'HEARTBEAT_TIMEOUT'):
            self.gateway._pump(socket)

    def test_resume_and_invalid_session_reset(self):
        self.gateway._session, self.gateway._seq = 'session-fixture', 18
        self.gateway._deadline = 2
        socket = FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': 1000}},
            {'op': 0, 's': 19, 't': 'RESUMED'}, {'op': 9, 'd': False}])
        with self.assertRaisesRegex(BotError, 'GATEWAY_RECONNECT'):
            self.gateway._pump(socket)
        self.assertEqual(socket.sent[0]['op'], 6)
        self.assertEqual(socket.sent[0]['d']['seq'], 18)
        self.assertIsNone(self.gateway._session)
        self.assertIsNone(self.gateway._seq)

    def test_pre_auth_event_mismatched_app_and_bad_hello_rejected(self):
        bad_ready = ready(); bad_ready['d']['application']['id'] = '987654321'
        for frames, expected in (([event()], 'QQ_EVENT_BEFORE_AUTH'),
                                  ([bad_ready], 'QQ_APP_CONTEXT_MISMATCH')):
            self.gateway._deadline = 5
            socket = FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': 1000}}, *frames])
            with self.subTest(expected=expected), self.assertRaisesRegex(BotError, expected):
                self.gateway._pump(socket)
        with self.assertRaisesRegex(BotError, 'INVALID_GATEWAY_HELLO'):
            self.gateway._pump(FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': True}}]))

    def test_resume_replays_missed_events_before_resumed(self):
        self.gateway._session, self.gateway._seq = 'session-fixture', 18
        self.gateway._deadline = 2
        socket = FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': 1000}},
            event(seq=19), {'op': 0, 's': 20, 't': 'RESUMED', 'd': ''}])
        with patch.object(self.gateway, '_dispatch') as dispatch:
            self.gateway._pump(socket)
        dispatch.assert_called_once()
        self.assertEqual(self.gateway._seq, 20)
        self.assertIn('QQ_GATEWAY_RESUMED', self.codes)

    def test_resume_duplicate_sequence_before_resumed_is_ignored(self):
        self.gateway._session, self.gateway._seq = 'session-fixture', 18
        self.gateway._deadline = 2
        socket = FakeSocket(self.clock, [{'op': 10, 'd': {'heartbeat_interval': 1000}},
            event(seq=18), event(seq=19), {'op': 0, 's': 20, 't': 'RESUMED', 'd': ''}])
        with patch.object(self.gateway, '_dispatch') as dispatch:
            self.gateway._pump(socket)
        dispatch.assert_called_once()

    def test_fatal_permission_close_and_cleanup(self):
        error = RuntimeError('must never log raw error')
        error.rcvd = Mock(code=4014)
        connector = Mock(side_effect=error)
        gateway = self.make(connector=connector)
        with self.assertRaisesRegex(BotError, 'QQ_GATEWAY_CLOSE_4014'):
            gateway.run(1)
        connector.assert_called_once()
        self.assertFalse(gateway._worker.is_alive())
        self.assertIn('QQ_STOPPED', self.codes)

    def test_reconnect_limit_uses_same_adapter_and_joins_worker(self):
        connector = Mock(side_effect=OSError('raw endpoint private'))
        gateway = self.make(connector=connector)
        with patch.object(gateway.stop, 'wait', return_value=False):
            with self.assertRaisesRegex(BotError, 'QQ_RECONNECT_LIMIT'):
                gateway.run(10)
        self.assertEqual(connector.call_count, 4)
        self.assertIs(gateway.adapter, self.adapter)
        self.assertFalse(gateway._worker.is_alive())

    def test_safe_audit_never_serializes_unapproved_fields(self):
        output = StringIO()
        with redirect_stdout(output):
            audit('QQ_READY', secret='fictional-secret', body='message', group='private-id', attempt=2)
            audit('raw text that must not be printed')
        rows = [json.loads(row) for row in output.getvalue().splitlines()]
        self.assertEqual(set(rows[0]), {'at', 'code', 'attempt'})
        self.assertEqual(rows[1]['code'], 'QQ_UNEXPECTED_ERROR')
        self.assertNotIn('private', output.getvalue())

    def test_diagnostic_audit_allows_only_fixed_enums_and_boolean_fields(self):
        output = StringIO()
        with redirect_stdout(output):
            audit('GATEWAY_URL_POLICY_REJECTED', stage='response', url_type='string', url_present=True,
                  parse_ok=True, has_query=True, path_matches=False, hostname_matches='PRIVATE-HOST',
                  scheme_matches=1, url='wss://PRIVATE-URL', body={'PRIVATE': 'BODY'},
                  secret='PRIVATE-SECRET', exception='PRIVATE-STACK', diagnostic_version='PRIVATE')
            audit('GATEWAY_URL_TYPE_INVALID', stage='PRIVATE-STAGE', url_type='PRIVATE-TYPE')
        rows = [json.loads(row) for row in output.getvalue().splitlines()]
        self.assertEqual((rows[0]['diagnostic_version'], rows[0]['stage'], rows[0]['url_type']),
                         (1, 'response', 'string'))
        self.assertTrue(rows[0]['has_query'])
        self.assertFalse(rows[0]['path_matches'])
        self.assertNotIn('hostname_matches', rows[0])
        self.assertNotIn('scheme_matches', rows[0])
        self.assertNotIn('stage', rows[1])
        self.assertNotIn('url_type', rows[1])
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_real_websockets_library_loopback_wire_and_shutdown(self):
        try:
            from websockets.sync.client import connect
            from websockets.sync.server import serve
        except ImportError:
            self.skipTest('optional QQ dependency not installed')
        wire, received = [], threading.Event()
        def handler(ws):
            ws.send(json.dumps({'op': 10, 'd': {'heartbeat_interval': 1000}}))
            wire.append(json.loads(ws.recv(timeout=2)))
            ws.send(json.dumps(ready()))
            value = event(); value['d']['timestamp'] = datetime.now(timezone.utc).isoformat()
            ws.send(json.dumps(value))
            try:
                while True:
                    wire.append(json.loads(ws.recv(timeout=2)))
                    ws.send('{"op":11}')
            except Exception:
                pass
        self.api.reply.side_effect = lambda *a, **k: received.set()
        adapter = QQAdapter(self.config, self.queries, mode='QQ_PASSIVE_READY')
        with serve(handler, '127.0.0.1', 0) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            port = server.socket.getsockname()[1]
            gateway = QQGateway(APP, self.api, adapter, emit=lambda *a, **kw: None,
                connector=lambda _: connect('ws://127.0.0.1:'+str(port), proxy=None, close_timeout=1))
            try:
                gateway.run(2)
            finally:
                server.shutdown()
                thread.join(3)
        self.assertTrue(received.is_set())
        self.assertEqual(wire[0]['op'], 2)
        self.assertTrue(any(p['op'] == 1 for p in wire))
        self.assertFalse(thread.is_alive())
        self.assertFalse(gateway._worker.is_alive())


if __name__ == '__main__':
    unittest.main()
