"""QQ-only HTTPS and WSS boundary. No provider client, fallback or proactive send."""
import logging
import socket
import threading
import time
from dataclasses import dataclass, replace
from threading import RLock
from urllib.parse import urlsplit

import httpx
from .configuration import app_identifier, json_object
from .contracts import BotError, identifier, message_identifier

API = 'https://api.bot.qq.com'
GATEWAY_HOSTS = frozenset({'api.bot.qq.com', 'api.sgroup.qq.com'})
GATEWAY_CLOSE_SECONDS = 2


GATEWAY_DIAGNOSTIC_CODES = frozenset({
    'GATEWAY_URL_FIELD_MISSING', 'GATEWAY_URL_TYPE_INVALID',
    'GATEWAY_URL_PARSE_FAILED', 'GATEWAY_URL_PORT_INVALID', 'GATEWAY_URL_POLICY_REJECTED',
})


@dataclass(frozen=True)
class GatewayURLDiagnostic:
    """Only fixed enums and booleans; never retain URL components or response data."""
    reason_code: str
    stage: str
    url_present: bool
    url_type: str
    parse_ok: bool | None = None
    port_parse_ok: bool | None = None
    scheme_matches: bool | None = None
    hostname_matches: bool | None = None
    port_matches: bool | None = None
    path_matches: bool | None = None
    has_username: bool | None = None
    has_password: bool | None = None
    has_query: bool | None = None
    has_fragment: bool | None = None
    input_has_whitespace: bool | None = None
    input_has_controls: bool | None = None


class GatewayURLRejected(BotError):
    def __init__(self, diagnostic):
        super().__init__('GATEWAY_URL_REJECTED')  # Keep the existing public error contract.
        self.diagnostic = diagnostic


def gateway_url(value, *, url_present=True, stage='validation'):
    json_type = ('missing' if not url_present else
                 {str: 'string', type(None): 'null', bool: 'boolean', int: 'number',
                  float: 'number', dict: 'object', list: 'array'}.get(type(value), 'non_json'))
    diagnostic = GatewayURLDiagnostic('GATEWAY_URL_POLICY_REJECTED',
        stage if stage in ('validation', 'response') else 'validation', bool(url_present), json_type)
    if not url_present:
        raise GatewayURLRejected(replace(diagnostic, reason_code='GATEWAY_URL_FIELD_MISSING')) from None
    if not isinstance(value, str):
        raise GatewayURLRejected(replace(diagnostic, reason_code='GATEWAY_URL_TYPE_INVALID')) from None
    diagnostic = replace(diagnostic, input_has_whitespace=any(c.isspace() for c in value),
        input_has_controls=any(ord(c) < 32 or ord(c) == 127 for c in value))
    try:
        url = urlsplit(value)
        diagnostic = replace(diagnostic, parse_ok=True, scheme_matches=url.scheme == 'wss',
            hostname_matches=url.hostname in GATEWAY_HOSTS, path_matches=url.path in ('/websocket', '/websocket/'),
            has_username=bool(url.username), has_password=bool(url.password),
            has_query=bool(url.query), has_fragment=bool(url.fragment))
    except Exception:
        raise GatewayURLRejected(replace(diagnostic, reason_code='GATEWAY_URL_PARSE_FAILED', parse_ok=False)) from None
    try:
        diagnostic = replace(diagnostic, port_parse_ok=True, port_matches=url.port in (None, 443))
    except Exception:
        raise GatewayURLRejected(replace(diagnostic, reason_code='GATEWAY_URL_PORT_INVALID', port_parse_ok=False)) from None
    # Same allowlist and nonempty component checks as before. No URL rewriting.
    if (not all((diagnostic.scheme_matches, diagnostic.hostname_matches, diagnostic.port_matches,
                 diagnostic.path_matches)) or any((diagnostic.has_username, diagnostic.has_password,
                                                  diagnostic.has_query, diagnostic.has_fragment))):
        raise GatewayURLRejected(diagnostic) from None
    return value


class GatewayDeadline:
    """Enforce existing protocol deadlines independently of blocked sync I/O.

    websockets 15 may wait inside sendall(), a recv thread join or a protocol
    lock. Closing through its public close() would wait for that same lock.
    Abort only this connection's underlying socket, without taking the lock.
    """
    def __init__(self, emit, monotonic=time.monotonic):
        self.emit, self.now = emit, monotonic
        self._condition = threading.Condition()
        self._deadline, self._code, self._socket = None, None, None
        self.expired = None
        self._stopped = False
        self._thread = threading.Thread(target=self._watch, name='qq-ws-deadline')

    def __enter__(self):
        self._thread.start()
        return self

    def attach(self, ws):
        self._socket = ws.socket  # Pinned websockets 15 sync connection; no URL or credentials.

    def arm(self, deadline, code):
        with self._condition:
            if self.expired is None:
                self._deadline, self._code = deadline, code
                self._condition.notify_all()

    def _watch(self):
        with self._condition:
            while not self._stopped:
                if self._deadline is None:
                    self._condition.wait()
                    continue
                # Let recv(timeout=.5) and normal protocol checks finish first.
                remaining = self._deadline + .5 - self.now()
                if remaining > 0:
                    self._condition.wait(remaining)
                    continue
                self.expired = self._code
                break
            else:
                return
        try:
            self.emit(self.expired)
        finally:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # The library may have already closed it.
            finally:
                try:
                    self._socket.close()
                except OSError:
                    pass

    def __exit__(self, *args):
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        self._thread.join(2)
        if self._thread.is_alive():
            raise BotError('QQ_GATEWAY_WATCHDOG_STOP_FAILED')


class QQAPI:
    def __init__(self, app_id, secret, *, client=None, monotonic=time.monotonic):
        self.app_id = app_identifier(app_id)
        self._secret, self._now = secret, monotonic
        self._client = client if client is not None else httpx.Client(
            timeout=httpx.Timeout(10, connect=5), trust_env=False, follow_redirects=False)
        self._owned = client is None
        self._token, self._expires = None, 0
        self._token_lock = RLock()

    def __repr__(self):
        return 'QQAPI(<redacted>)'

    def close(self):
        self._token = None
        if self._owned:
            self._client.close()

    def _request(self, method, path, *, authenticated=True, body=None,before_post=None):
        headers = {'Authorization': 'QQBot '+self.token()} if authenticated else {}
        started = self._now()
        try:
            if before_post is not None:before_post()  # After token refresh, immediately before HTTP submission.
            with self._client.stream(method, API+path, headers=headers, json=body) as response:
                if not 200 <= response.status_code < 300:
                    if response.status_code == 401:
                        self._token, self._expires = None, 0
                    raise BotError('QQ_HTTP_'+str(response.status_code))
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if self._now()-started > 10:
                        raise BotError('QQ_DELIVERY_UNKNOWN' if path.endswith('/messages') else 'QQ_HTTP_TIMEOUT')
                    if len(content) > 65536:
                        raise BotError('QQ_RESPONSE_TOO_LARGE')
                value = json_object(bytes(content))
            error = value.get('err_code', value.get('code', 0))
            if type(error) is not int or error != 0:
                raise BotError('QQ_API_'+str(error) if type(error) is int else 'QQ_API_ERROR')
            return value
        except BotError:
            raise
        except httpx.TransportError:
            # POST may already have reached QQ. Never retry an uncertain send.
            raise BotError('QQ_DELIVERY_UNKNOWN' if path.endswith('/messages') else 'QQ_HTTP_TIMEOUT') from None
        except Exception:
            raise BotError('QQ_HTTP_UNAVAILABLE') from None

    def token(self):
        with self._token_lock:
            return self._load_token()

    def _load_token(self):
        if self._token and self._now() < self._expires:
            return self._token
        try:
            snapshot = self._secret()
            secret = snapshot._for_adapter()
            if (not secret or not secret.isascii() or not secret.isprintable()
                    or len(secret) > 4096 or any(c.isspace() for c in secret)):
                raise BotError('QQ_SECRET_MISSING_OR_INVALID')
        except BotError:
            raise
        except Exception:
            raise BotError('QQ_CREDENTIAL_UNAVAILABLE') from None
        value = self._request('POST', '/app/getAppAccessToken', authenticated=False,
                              body={'appId': self.app_id, 'clientSecret': secret})
        token, duration = value.get('access_token'), value.get('expires_in')
        if isinstance(duration, str) and duration.isdigit():
            duration = int(duration)
        if (not isinstance(token, str) or not 1 <= len(token) <= 8192 or not token.isascii()
                or not token.isprintable() or any(c.isspace() for c in token)
                or type(duration) is not int or not 1 <= duration <= 7200):
            raise BotError('QQ_INVALID_TOKEN_RESPONSE')
        self._token, self._expires = token, self._now()+max(0, duration-60)
        return token

    def gateway(self):
        response = self._request('GET', '/gateway')
        return gateway_url(response.get('url'), url_present='url' in response, stage='response')

    def reply(self, reply, *, received_at, now,before_post=None):
        # Require an actual fresh incoming message context. No proactive entry.
        if not 0 <= (now-received_at).total_seconds() < 300:
            raise BotError('REPLY_EXPIRED')
        identifier(reply.group_id)
        message_identifier(reply.msg_id)
        if reply.msg_seq != 1 or reply.msg_type != 0 or not 1 <= len(reply.content) <= 1800:
            raise BotError('INVALID_REPLY')
        value = self._request('POST', '/v2/groups/'+reply.group_id+'/messages', body={
            'msg_type': 0, 'content': reply.content, 'msg_id': reply.msg_id, 'msg_seq': 1},
            before_post=before_post)
        if not isinstance(value.get('id'), str) or not value['id']:
            raise BotError('QQ_SEND_NOT_CONFIRMED')
        return True


def connect_gateway(url):
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise BotError('QQ_WEBSOCKETS_DEPENDENCY_MISSING') from None
    logger = logging.Logger('fishery.qq.wire.disabled', level=logging.CRITICAL+1)
    logger.addHandler(logging.NullHandler())
    return connect(gateway_url(url), proxy=None, open_timeout=10, close_timeout=GATEWAY_CLOSE_SECONDS,
        compression=None, max_size=65536, max_queue=4, ping_interval=None, logger=logger)
