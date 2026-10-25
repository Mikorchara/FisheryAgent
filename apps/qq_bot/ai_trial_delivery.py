"""Phase-approved passive QQ transport. No Agent, retries or proactive messages."""
import threading

import httpx

from apps.ai_service.channel_trial import QwenTrialSession
from .contracts import BotError
from .transport import QQAPI


class TrialQQTransport:
    def __init__(self,api,trial):
        if (type(api) is not QQAPI or type(trial) is not QwenTrialSession
                or trial.approval.phase!='qq' or api.app_id!=trial.approval.app_id):
            raise BotError('TRIAL_QQ_COMPOSITION_REQUIRED')
        if trial.offline_test and type(api._client._transport) is not httpx.MockTransport:
            raise BotError('TRIAL_OFFLINE_HTTP_REQUIRED')
        trial.check()
        self.api,self.trial=api,trial
        self._connected=threading.Event();self._closed=threading.Event()

    @property
    def connected(self):return self._connected.is_set() and not self._closed.is_set()
    def reconnect(self):
        self.trial.check()
        if not self._closed.is_set():self._connected.set()
    def disconnect(self):self._connected.clear()
    def close(self):
        self._closed.set();self._connected.clear();self.api.close()

    def send(self,context,reply,*,clock,cancelled,before_post):
        def validate():
            if cancelled.is_set():raise BotError('AI_CANCELLED')
            if not self.connected:raise BotError('AI_GATEWAY_DISCONNECTED')
            self.trial.check();before_post()
        validate()
        return self.api.reply(reply,received_at=context.timestamp,now=clock(),before_post=validate)
