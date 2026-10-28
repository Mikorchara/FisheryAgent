"""Shared Gateway routing: exact Fake by default, separate approved operator trial path."""
from dataclasses import replace
import threading

from .ai_coordinator import QQAIMessageContext
from .ai_scheduler import QQAIJobScheduler
from .adapter import QQAdapter
from .configuration import app_identifier
from .contracts import BotError,decode
from .intent import classify,GatewayMention
from .ai_delivery import OfflineQQGateway
from apps.ai_backend.model_gateway import GatewayError


class OfflineGatewayAPI:
    """No HTTP/token supplier; also catches accidental bypass of the shared owner."""
    def __init__(self,app_id):self.app_id=app_identifier(app_id)
    def token(self):return 'offline-gateway-token'
    def gateway(self):return 'wss://api.bot.qq.com/websocket/'
    def reply(self,*args,**kwargs):raise BotError('SHARED_REPLY_OWNER_REQUIRED')


class OfflineQQAIRouter:
    def __init__(self,adapter,scheduler):
        if (type(scheduler) is not QQAIJobScheduler or adapter.config!=scheduler.coordinator.access
                or adapter.mode!='QQ_PASSIVE_READY'):
            raise BotError('INVALID_OFFLINE_ROUTING_COMPOSITION')
        self.adapter,self.scheduler=adapter,scheduler
        self.owner=scheduler.delivery.passive
        self.coordinator=scheduler.coordinator
        self._closed=threading.Event()
        self._revoked=set()
        self._ingress=QQAdapter(adapter.config,None,clock=self.owner.clock)
        if self.coordinator.conversations is not None and type(scheduler.gateway) is not OfflineQQGateway:
            from .ai_trial_delivery import ConversationQQTransport,SessionQQTransport
            valid=(type(scheduler.gateway) is ConversationQQTransport
                and scheduler.gateway.trial is self.coordinator.conversation_trial) or (
                type(scheduler.gateway) is SessionQQTransport and scheduler.gateway.trial is self.coordinator.session_run)
            if not valid:
                raise BotError('QQ_CONVERSATION_FAKE_ONLY')

    def bind_gateway(self,owner):
        if self.coordinator._mention_owner not in (None,owner):raise BotError('QQ_GATEWAY_ALREADY_BOUND')
        self.coordinator._mention_owner=owner

    def mention_context(self,raw,owner,message):
        import hashlib
        if self.coordinator._mention_owner is not owner:raise BotError('AI_AUTHENTICATED_MENTION_REQUIRED')
        return GatewayMention(owner,self.adapter.config.app_id,message.message_id,hashlib.sha256(raw).hexdigest())

    def receive(self,raw,*,transport_app_id,mention=None):
        outcome=self._ingress.admit_offline(raw,transport_app_id=transport_app_id,
            operation=lambda _message,_access:self._receive(raw,transport_app_id=transport_app_id,mention=mention))
        return outcome if isinstance(outcome,tuple) else (outcome.code,None)

    def _receive(self,raw,*,transport_app_id,mention=None):
        message=decode(raw)
        if message.group_id in self._revoked:return 'GROUP_DENIED',None
        head=message.content.split(maxsplit=1)[0];store=self.coordinator.conversations
        ai=head=='/问AI'
        if store is not None:
            fixed=self.coordinator.classify(message.content).kind=='fixed' and not ai
            unknown_slash=message.content.startswith('/') and head not in ('/问AI','/清空会话') and not fixed
            if not fixed and not unknown_slash and (ai or head=='/清空会话' or store.options.trigger_mode=='mention_ai'):
                try:
                    if not ai and head!='/清空会话':self.coordinator.validate_mention(raw,message,mention,transport_app_id)
                    key,topic=self.coordinator.conversation_context(message)
                    text=(message.content.split(maxsplit=1)[1] if len(message.content.split(maxsplit=1))==2 else '') if ai else message.content
                    intent=self.coordinator.classify(text,topic=topic,command_priority=not ai)
                    if intent.kind=='clear':
                        key=self.coordinator.clear_conversation(message);self.scheduler.cancel_conversation(key)
                    if not self.coordinator.is_agent_intent(intent):return self._fixed(message,transport_app_id,intent.text,ai_key=key)
                    ai=True
                except (BotError,GatewayError) as error:return error.code,None
        if ai:
            try:return 'AI_ADMITTED',self.scheduler.submit(raw,transport_app_id=transport_app_id,mention=mention)
            except BotError as error:
                # Only explicit AI-authorized users get safe busy/disabled errors.
                # Replays, identity denial and transport failures are never replied to twice.
                if error.code not in ('BUSY','AI_SESSION_BUSY','AI_DISABLED'):
                    return error.code,None
                if error.code!='AI_DISABLED':self.coordinator._permission(message)
                result=self.adapter.receive(raw,transport_app_id=transport_app_id)
                if result.reply is None:return result.code,None
                text={'BUSY':'AI_BUSY：队列已满，请稍后发送新消息。',
                    'AI_SESSION_BUSY':'AI_SESSION_BUSY：当前会话已有任务，请等待本轮结束。',
                    'AI_DISABLED':'AI_DISABLED：未启用真实AI调用。'}[error.code]
                return self._fixed(message,transport_app_id,text)
        result=self.adapter.receive(raw,transport_app_id=transport_app_id)
        if result.reply is None:return result.code,None
        return self._fixed(message,transport_app_id,result.reply.content)

    def _fixed(self,message,app_id,text,*,ai_key=None):
        access=self.adapter.config
        def validate():
            if self._closed.is_set():raise BotError('AI_CANCELLED')
            if not self.scheduler.gateway.connected:raise BotError('AI_GATEWAY_DISCONNECTED')
            if access!=self.coordinator.access or self.adapter.config!=access:
                raise BotError('CHANNEL_AUTHORIZATION_CHANGED')
            group=next((g for g in access.groups if g.group_id==message.group_id),None)
            if group is None or message.member_id not in group.members or app_id!=access.app_id:
                raise BotError('AI_NOT_AUTHORIZED')
            if message.group_id in self._revoked:raise BotError('AI_NOT_AUTHORIZED')
            if not 0<=(self.owner.clock()-message.timestamp).total_seconds()<285:
                raise BotError('AI_REPLY_EXPIRED')
            if ai_key is not None and self.coordinator.conversation_context(message)[0]!=ai_key:
                raise BotError('CHANNEL_AUTHORIZATION_CHANGED')
        context=QQAIMessageContext(app_id,message.group_id,message.member_id,message.message_id,
            message.timestamp,0,'')  # Fixed commands never acquire an AI execution plan.
        receipt=self.owner.send(context,text,self._closed,validate)
        return receipt.code,receipt

    def connected(self):self.scheduler.gateway.reconnect()
    def disconnected(self):
        self.scheduler.gateway.disconnect()
        self.scheduler.cancel_all(reason='AI_GATEWAY_DISCONNECTED')
    def revoke_group(self,group_id):
        self._revoked.add(group_id)
        access=replace(self.coordinator.access,groups=tuple(replace(g,capabilities=())
            if g.group_id==group_id else g for g in self.coordinator.access.groups))
        self.coordinator.reconfigure(self.coordinator.config,access=access)
        self.adapter.config=access
        self._ingress.config=access
    def close(self):
        self._closed.set()
        try:self.scheduler.close()
        finally:
            if self.coordinator.conversations is not None:self.coordinator.conversations.close()


class TrialQQAIRouter(OfflineQQAIRouter):
    """Same ingress, scheduler and reply owner, with a separate phase-approved transport."""
    def __init__(self,adapter,scheduler):
        from .ai_trial_delivery import TrialQQTransport,ConversationQQTransport,SessionQQTransport
        valid=(type(scheduler.gateway) is TrialQQTransport
            and scheduler.gateway.trial is scheduler.coordinator.service._channel_trial) or (
            type(scheduler.gateway) is ConversationQQTransport
            and scheduler.gateway.trial is scheduler.coordinator.conversation_trial) or (
            type(scheduler.gateway) is SessionQQTransport and scheduler.gateway.trial is scheduler.coordinator.session_run)
        if not valid:
            raise BotError('TRIAL_QQ_COMPOSITION_REQUIRED')
        super().__init__(adapter,scheduler)

    def check_liveness(self):
        self.scheduler.gateway.trial.check()
