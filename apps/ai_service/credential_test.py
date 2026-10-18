"""Explicit single-request connection checks, bounded in-memory save receipts, no secret logs."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import threading
import time

from apps.ai_backend.contracts import Mode
from apps.ai_backend.execution import RequestHandle, request_scope
from apps.ai_backend.model_gateway import GatewayError, ModelMessage, ModelRequest, ProfileRegistry
from apps.ai_backend.project_env import edit_env, EnvWriteError
from .runtime.assistant import assistant_profile
from .settings_store import SettingsError

TEST_TOKENS, TEST_TIMEOUT_S, RECEIPT_TTL_S = 8, 20, 300


class CredentialConnectionTests:
    def __init__(self, owner, gateway_factory):
        self.owner,self.gateway_factory=owner,gateway_factory
        self._salt=secrets.token_bytes(32)
        self._receipts={}
        self._lock=threading.RLock()
        self._running=threading.Lock()

    def _digest(self, secret):
        # Validate via the same writer contract; do not keep a second raw-key cache.
        try:
            edit_env(b'', 'TEST_API_KEY','create',secret)
            return hmac.digest(self._salt,secret.encode('utf-8'),hashlib.sha256)
        except UnicodeError:
            raise EnvWriteError('INVALID_CREDENTIAL_VALUE') from None

    def _prune(self):
        self._receipts={k:v for k,v in self._receipts.items() if v['expires']>time.monotonic()}

    def authorize_save(self,value):
        with self._lock:
            self._prune()
            token=value.get('test_token')
            receipt=self._receipts.pop(token,None) if isinstance(token,str) else None
            if (receipt is None or receipt['provider']!=value['provider'] or receipt['revision']!=value['revision']
                    or not hmac.compare_digest(receipt['digest'],self._digest(value['secret']))):
                raise SettingsError('CREDENTIAL_TEST_REQUIRED')

    @staticmethod
    def _error(code):
        if code in ('HTTP_401','HTTP_403'):return 'AUTHENTICATION_FAILED'
        if code=='HTTP_429':return 'RATE_LIMITED'
        if code in ('TIMEOUT','TOTAL_TIMEOUT','READ_TIMEOUT','CONNECT_TIMEOUT'):return 'TIMEOUT'
        if code in ('CONNECTION_ERROR','DNS_ERROR','TLS_ERROR','PROXY_ERROR'):return 'NETWORK_ERROR'
        return 'PROVIDER_ERROR'

    def run(self,value):
        if (not isinstance(value,dict) or set(value)!={'epoch','provider','source','secret','revision','confirm_network'}
                or value['epoch']!=self.owner.backend.epoch or not isinstance(value['provider'],str)
                or value['provider'] not in self.owner.CLOUDS or value['source'] not in ('input','saved')
                or value['confirm_network'] is not True):
            raise SettingsError('INVALID_CREDENTIAL_TEST')
        provider=value['provider'];current=self.owner.credential_status(provider)
        if value['source']=='input':
            if not current['editable']:raise SettingsError('CREDENTIAL_READ_ONLY')
            digest=self._digest(value['secret'])
            revision=current['revision']
        else:
            if value['secret'] is not None or current['availability']!='PRESENT':
                raise SettingsError('CREDENTIAL_NOT_CONFIGURED')
            revision=current['credential_revision']
        if value['revision']!=revision:
            raise SettingsError('ENV_REVISION_CONFLICT')
        if not self._running.acquire(blocking=False):
            raise SettingsError('CREDENTIAL_TEST_BUSY')
        started=time.monotonic();adapter=None
        try:
            profile=replace(assistant_profile(self.owner.CLOUDS[provider]),connect_timeout_s=5,
                read_timeout_s=TEST_TIMEOUT_S,total_timeout_s=TEST_TIMEOUT_S,max_retries=0)
            registry=ProfileRegistry([profile],self.owner.backend.credentials)
            runtime=(registry.snapshot(profile.profile_id,environ={profile.credential_ref:value['secret']})
                     if value['source']=='input' else registry.snapshot(profile.profile_id))
            runtime=replace(runtime,transport_output_token_limit=TEST_TOKENS)
            if value['source']=='saved' and runtime.credential.revision!=revision:
                raise SettingsError('ENV_REVISION_CONFLICT')
            handle=RequestHandle();handle.start();handle.limit_turn(TEST_TIMEOUT_S)
            try:
                adapter=self.gateway_factory()
                with request_scope(handle):
                    result=adapter.complete(ModelRequest(Mode.CHAT,(ModelMessage('user','Reply OK.'),)),runtime)
                if (result.tool_calls or result.finish_reason not in ('stop','length')
                        or adapter.request_attempts!=1 or not handle.io_closed):
                    raise GatewayError('INVALID_RESPONSE')
                after=self.owner.credential_status(provider)
                field='revision' if value['source']=='input' else 'credential_revision'
                if after[field]!=revision:raise SettingsError('CREDENTIAL_TEST_STALE')
                public={'success':True,'code':'CONNECTED','source':value['source']}
                handle.finish()
                if value['source']=='input':
                    with self._lock:
                        self._prune()
                        if len(self._receipts)>=64:
                            self._receipts.pop(next(iter(self._receipts)))
                        token=secrets.token_urlsafe(32)
                        self._receipts[token]={'provider':provider,'revision':revision,'digest':digest,
                            'expires':time.monotonic()+RECEIPT_TTL_S}
                    public.update(test_token=token,valid_for_s=RECEIPT_TTL_S)
            except GatewayError as error:
                handle.finish(error.code)
                public={'success':False,'code':self._error(error.code),'source':value['source']}
            except SettingsError as error:
                handle.finish(error.code)
                raise
            except Exception:
                handle.finish('SDK_ERROR')
                public={'success':False,'code':'PROVIDER_ERROR','source':value['source']}
            return {**public,'tested_at':datetime.now(timezone.utc).isoformat(),
                'request_count':getattr(adapter,'request_attempts',0),
                'latency_ms':round((time.monotonic()-started)*1000),'max_output_tokens':TEST_TOKENS}
        finally:
            self._running.release()
