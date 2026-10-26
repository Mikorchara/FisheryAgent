"""Authenticated QQ Gateway lifecycle; one bounded read worker, no AI or notifications."""
from datetime import datetime, timezone
import json
from queue import Queue, Empty, Full
import re
import threading
import time

from .configuration import app_identifier, json_object
from .contracts import BotError, decode, identifier
from .transport import GATEWAY_CLOSE_SECONDS, GATEWAY_DIAGNOSTIC_CODES, GatewayDeadline, connect_gateway

INTENTS = 1 << 25
FATAL_CLOSES = {4001, 4002, 4004, 4010, 4011, 4012, 4013, 4014, 4914, 4915}
RETRYABLE = {'QQ_HTTP_UNAVAILABLE', 'QQ_HTTP_TIMEOUT', 'GATEWAY_DISCONNECTED',
             'GATEWAY_RECONNECT', 'HEARTBEAT_TIMEOUT', 'GATEWAY_AUTH_TIMEOUT',
             'GATEWAY_HELLO_TIMEOUT', 'GATEWAY_CLOSE_TIMEOUT'}


def audit(code, **fields):
    """Safe JSON lines, no packet text, IDs, credentials, headers or exception text."""
    code = code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}', str(code)) else 'QQ_UNEXPECTED_ERROR'
    allowed = {key: value for key, value in fields.items() if key in (
               'attempt', 'count', 'close_code', 'heartbeat_ms', 'retry_delay_seconds')
               and type(value) is int}
    if code in GATEWAY_DIAGNOSTIC_CODES:
        allowed['diagnostic_version'] = 1
        for key in ('url_present', 'parse_ok', 'port_parse_ok', 'scheme_matches', 'hostname_matches',
                    'port_matches', 'path_matches', 'has_username', 'has_password', 'has_query',
                    'has_fragment', 'input_has_whitespace', 'input_has_controls'):
            value = fields.get(key)
            if value is None or type(value) is bool:
                allowed[key] = value
        for key, values in (('stage', ('response', 'validation')),
                            ('url_type', ('missing', 'string', 'null', 'boolean', 'number',
                                          'object', 'array', 'non_json'))):
            value = fields.get(key)
            if type(value) is str and value in values:
                allowed[key] = value
    print(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'code': code, **allowed}), flush=True)


def normalize(packet, bot_id=None):
    """Drop platform metadata (including message_scene auth tokens), not business gates."""
    if packet.get('t') != 'GROUP_AT_MESSAGE_CREATE' or type(packet.get('op')) is not int or packet.get('op') != 0:
        raise BotError('UNSUPPORTED_EVENT')
    data = packet.get('d')
    if not isinstance(data, dict):
        raise BotError('INVALID_PACKET')
    if data.get('attachments') or data.get('ark_data') or data.get('msg_elements'):
        raise BotError('UNSUPPORTED_MESSAGE_TYPE')
    content = data.get('content')
    if isinstance(content, str) and bot_id:
        # Current docs say prefix stripped; accept only our own leading legacy mention.
        for prefix in ('<@'+bot_id+'>', '<@!'+bot_id+'>'):
            if content.lstrip().startswith(prefix):
                content = content.lstrip()[len(prefix):].lstrip()
                break
    author = data.get('author')
    if not isinstance(author, dict):
        raise BotError('INVALID_PACKET')
    minimal = {'op': 0, 't': 'GROUP_AT_MESSAGE_CREATE', 'd': {
        'id': data.get('id'), 'group_openid': data.get('group_openid'),
        'timestamp': data.get('timestamp'), 'content': content, 'message_type': data.get('message_type', 0),
        'author': {'member_openid': author.get('member_openid'), 'bot': author.get('bot', False)}}}
    try:
        raw = json.dumps(minimal, ensure_ascii=True, allow_nan=False).encode()
    except (ValueError, UnicodeError):
        raise BotError('INVALID_PACKET') from None
    message = decode(raw)
    return raw, message


class QQGateway:
    def __init__(self, app_id, api, adapter=None, *, connector=connect_gateway,
                 emit=audit, discover=None, clock=None, monotonic=time.monotonic,offline_router=None,trial_router=None):
        self.app_id = app_identifier(app_id)
        if api.app_id != self.app_id or (adapter is not None and (
                adapter.config.app_id != self.app_id or adapter.mode != 'QQ_PASSIVE_READY')):
            raise BotError('QQ_APP_CONTEXT_MISMATCH')
        if (adapter is None) == (discover is None):
            raise BotError('INVALID_GATEWAY_MODE')
        if offline_router is not None:
            from .ai_routing import OfflineQQAIRouter,OfflineGatewayAPI
            if (type(offline_router) is not OfflineQQAIRouter or type(api) is not OfflineGatewayAPI
                    or connector is connect_gateway or offline_router.adapter is not adapter):
                raise BotError('OFFLINE_GATEWAY_COMPOSITION_REQUIRED')
        if trial_router is not None:
            from .ai_routing import TrialQQAIRouter
            from .ai_trial_delivery import TrialQQTransport,ConversationQQTransport
            if (offline_router is not None or type(trial_router) is not TrialQQAIRouter
                    or type(trial_router.scheduler.gateway) not in (TrialQQTransport,ConversationQQTransport)
                    or trial_router.scheduler.gateway.api is not api or trial_router.adapter is not adapter):
                raise BotError('TRIAL_QQ_COMPOSITION_REQUIRED')
            trial_router.check_liveness()
        self.offline_router=offline_router
        self.trial_router=trial_router
        self.router=offline_router if offline_router is not None else trial_router
        self.api, self.adapter, self.connector, self.emit, self.discover = api, adapter, connector, emit, discover
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.now = monotonic
        self.stop = threading.Event()
        self._queue = Queue(maxsize=4)
        self._worker = None
        self._session, self._seq, self._bot_id = None, None, None
        self._discovered, self._revoked = set(), set()
        self._deadline = 0
        self._active_guard=None
        self._dispatch_context=threading.local()
        if self.router is not None and self.router.coordinator.conversations is not None:self.router.bind_gateway(self)

    def _work(self):
        while not self.stop.is_set():
            try:
                item = self._queue.get(timeout=.2)
                raw,message=item[:2];mention=item[2] if len(item)==3 else None
            except Empty:
                continue
            try:
                if self.stop.is_set() or message.group_id in self._revoked:
                    continue
                if self.router is not None:
                    code,_result=self.router.receive(raw,transport_app_id=self.app_id,mention=mention)
                    self.emit(code)
                    continue  # Router owns ALL replies; never also call api.reply.
                result = self.adapter.receive(raw, transport_app_id=self.app_id)
                self.emit(result.code)
                if result.reply is not None and not self.stop.is_set() and message.group_id not in self._revoked:
                    self.api.reply(result.reply, received_at=message.timestamp, now=self.clock())
                    self.emit('QQ_REPLY_ACCEPTED')
            except BotError as error:
                self.emit(error.code)
            except Exception:
                self.emit('QQ_WORKER_ERROR')
            finally:
                self._queue.task_done()

    def _dispatch(self, packet):
        if packet.get('t') == 'GROUP_DEL_ROBOT':
            data = packet.get('d') or {}
            group = data.get('group_openid') if isinstance(data, dict) else None
            if self.adapter and group in {g.group_id for g in self.adapter.config.groups}:
                self._revoked.add(group)
                if self.router is not None:self.router.revoke_group(group)
                self.emit('QQ_GROUP_REMOVED')
            return
        if packet.get('t') != 'GROUP_AT_MESSAGE_CREATE':
            return
        try:
            raw, message = normalize(packet, self._bot_id)
            if self.discover is not None:
                pair = (message.group_id, message.member_id)
                if pair not in self._discovered and len(self._discovered) < 10:
                    self._discovered.add(pair)
                    self.discover(*pair)
                return  # Never reply, create a business service or resolve data here.
            if message.group_id in self._revoked:
                self.emit('QQ_GROUP_REMOVED')
                return
            mention=None
            if (self.router is not None and self.router.coordinator.conversations is not None
                    and getattr(self._dispatch_context,'authenticated',False)):
                mention=self.router.mention_context(raw,self,message)
            self._queue.put_nowait((raw, message,mention))
        except Full:
            self.emit('QQ_QUEUE_FULL')
        except BotError as error:
            self.emit(error.code)

    def _dispatch_authenticated(self,packet):
        self._dispatch_context.authenticated=True
        try:self._dispatch(packet)
        finally:self._dispatch_context.authenticated=False

    def request_stop(self):
        """Cancel only this owned connection; do not wait for console input or recv."""
        self.stop.set();guard=self._active_guard
        if guard is not None and guard._socket is not None:guard.arm(self.now(),'QQ_CANCELLED')

    def _pump(self, ws, guard=None):
        def arm(deadline, code):
            if guard is not None:
                if self._deadline < deadline:
                    deadline, code = self._deadline, 'QQ_RUN_DURATION_REACHED'
                guard.arm(deadline, code)
        arm(self.now()+10, 'GATEWAY_HELLO_TIMEOUT')
        self.emit('QQ_GATEWAY_WAIT_HELLO')
        first = json_object(ws.recv(timeout=10))
        interval = (first.get('d') or {}).get('heartbeat_interval') if isinstance(first.get('d'), dict) else None
        if (first.get('op') != 10 or type(interval) is not int or not 1000 <= interval <= 300000):
            raise BotError('INVALID_GATEWAY_HELLO')
        self.emit('QQ_HEARTBEAT_CONFIGURED', heartbeat_ms=interval)
        interval /= 1000
        ready, waiting_ack = False, False
        started, next_heartbeat = self.now(), self.now()+interval
        def arm_liveness():
            deadline = next_heartbeat if waiting_ack else next_heartbeat+interval
            code = 'HEARTBEAT_TIMEOUT'
            if not ready and started+15 < deadline:
                deadline, code = started+15, 'GATEWAY_AUTH_TIMEOUT'
            arm(deadline, code)
        arm_liveness()
        token = 'QQBot '+self.api.token()
        resuming = bool(self._session and self._seq is not None)
        if resuming:
            identify = {'op': 6, 'd': {'token': token, 'session_id': self._session, 'seq': self._seq}}
        else:
            identify = {'op': 2, 'd': {'token': token, 'intents': INTENTS, 'shard': [0, 1]}}
        self.emit('QQ_GATEWAY_RESUMING' if resuming else 'QQ_GATEWAY_IDENTIFYING')
        ws.send(json.dumps(identify))
        while not self.stop.is_set() and self.now() < self._deadline:
            if self.trial_router is not None:self.trial_router.check_liveness()
            if not ready and self.now()-started > 15:
                raise BotError('GATEWAY_AUTH_TIMEOUT')
            if self.now() >= next_heartbeat:
                if waiting_ack:
                    raise BotError('HEARTBEAT_TIMEOUT')
                waiting_ack, next_heartbeat = True, self.now()+interval
                arm_liveness()  # Arm before send; sendall itself can stall.
                ws.send(json.dumps({'op': 1, 'd': self._seq}))
                self.emit('QQ_HEARTBEAT_SENT')
            try:
                packet = json_object(ws.recv(timeout=min(.5, max(.01, next_heartbeat-self.now()))))
            except TimeoutError:
                continue
            op = packet.get('op')
            if type(op) is not int:
                raise BotError('INVALID_GATEWAY_PACKET')
            if op == 11:
                waiting_ack = False
                self.emit('QQ_HEARTBEAT_ACK')
            elif op == 1:
                waiting_ack = True
                arm_liveness()
                ws.send(json.dumps({'op': 1, 'd': self._seq}))
                self.emit('QQ_HEARTBEAT_SENT')
            elif op == 7:
                raise BotError('GATEWAY_RECONNECT')
            elif op == 9:
                if packet.get('d') is not True:
                    self._session, self._seq = None, None
                raise BotError('GATEWAY_RECONNECT')
            elif op == 0:
                seq = packet.get('s')
                if type(seq) is not int or seq < 0:
                    raise BotError('INVALID_GATEWAY_SEQUENCE')
                if packet.get('t') == 'READY':
                    data = packet.get('d')
                    if not isinstance(data, dict):
                        raise BotError('INVALID_GATEWAY_READY')
                    self._session = identifier(data.get('session_id'))
                    self._bot_id = identifier((data.get('user') or {}).get('id'))
                    application = data.get('application')
                    if application and (not isinstance(application, dict) or str(application.get('id')) != self.app_id):
                        raise BotError('QQ_APP_CONTEXT_MISMATCH')
                    ready, self._seq = True, seq
                    self.emit('QQ_GATEWAY_READY')
                elif packet.get('t') == 'RESUMED' and self._session:
                    ready, self._seq = True, seq
                    self.emit('QQ_GATEWAY_RESUMED')
                # Official Resume replays missed Dispatch frames BEFORE RESUMED.
                # Only a connection with an existing authenticated session may do this.
                elif (ready or resuming) and (self._seq is None or seq > self._seq):
                    self._dispatch_authenticated(packet)
                    self._seq = seq
                elif not (ready or resuming):
                    raise BotError('QQ_EVENT_BEFORE_AUTH')
            arm_liveness()

    def run(self, seconds=600):
        if type(seconds) is not int or not 1 <= seconds <= 3600:
            raise BotError('INVALID_RUN_DURATION')
        self._deadline = self.now()+seconds
        try:
            if self.adapter:
                self._worker = threading.Thread(target=self._work, name='qq-readonly-worker')
                self._worker.start()
            for attempt in range(4):
                if self.trial_router is not None:self.trial_router.check_liveness()
                if self.stop.is_set() or self.now() >= self._deadline:
                    if not self.stop.is_set():
                        self.emit('QQ_RUN_DURATION_REACHED')
                    break
                guard = GatewayDeadline(self.emit, self.now)
                self._active_guard=guard
                self.emit('QQ_GATEWAY_CONNECTING', attempt=attempt+1)
                try:
                    with guard:
                        with self.connector(self.api.gateway()) as ws:
                            if self.router is not None:self.router.connected()
                            guard.attach(ws)
                            try:
                                self._pump(ws, guard)
                            finally:
                                if self.router is not None:self.router.disconnected()
                                self.emit('QQ_GATEWAY_CLOSING')
                                guard.arm(self.now()+GATEWAY_CLOSE_SECONDS, 'GATEWAY_CLOSE_TIMEOUT')
                        if guard.expired:
                            raise BotError(guard.expired)
                    if self.now() >= self._deadline:
                        self.emit('QQ_RUN_DURATION_REACHED')
                    return
                except KeyboardInterrupt:
                    self.emit('QQ_CANCELLED')
                    return
                except Exception as error:
                    if isinstance(error, BotError) and error.code == 'QQ_GATEWAY_WATCHDOG_STOP_FAILED':
                        raise  # Never start another guard while this one's cleanup failed.
                    if guard.expired == 'QQ_RUN_DURATION_REACHED':
                        return
                    close = getattr(getattr(error, 'rcvd', None), 'code', None)
                    if close in FATAL_CLOSES:
                        raise BotError('QQ_GATEWAY_CLOSE_'+str(close)) from None
                    if close in (4006, 4007) or type(close) is int and 4900 <= close <= 4913:
                        self._session, self._seq = None, None
                    if guard.expired:
                        code = guard.expired
                    elif isinstance(error, BotError):
                        if error.code not in RETRYABLE:
                            raise
                        code = error.code
                    else:
                        code = 'GATEWAY_DISCONNECTED'
                    self.emit(code, attempt=attempt+1)
                    if attempt == 3:
                        raise BotError('QQ_RECONNECT_LIMIT') from None
                    self.emit('QQ_GATEWAY_RETRY_WAIT', attempt=attempt+1, retry_delay_seconds=2**attempt)
                    self.stop.wait(min(2**attempt, max(0, self._deadline-self.now())))
        finally:
            self.stop.set()
            try:
                # Close owned fake I/O before joining the receive worker. It may
                # be inside a fixed reply while connection setup itself failed.
                if self.router is not None:self.router.close()
            finally:
                if self._worker and self._worker.ident is not None:
                    self._worker.join(3 if self.router is not None else None)
                    if self._worker.is_alive():raise BotError('QQ_WORKER_STOP_FAILED')
            self.emit('QQ_STOPPED')
