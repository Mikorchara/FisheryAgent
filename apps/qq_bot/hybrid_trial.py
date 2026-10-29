"""Explicit local operator consent for experimental real QQ General publication."""
from apps.ai_service.channel_hybrid_trial import (CONTRACT, prepared_scope, preparation_record,
    check_preparation, HybridRunAuthorizationAuthority, HybridTrialQwenTurn)
from apps.ai_service.channel_trial import PRESET, cost_reservation
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from .contracts import BotError
from .conversations import ConversationOptions
from .hybrid_conversations import HybridConversationStore
from .run_consent import RunLimits
from .session_run_trial import SessionTrialRun, SessionTrialLedger, selected_members, CONSENTS, ROOT
from .trial_configuration import inputs_snapshot, read_json
from .session_run import SessionRun
from apps.ai_service.channel_validation import validation_once

RISK = ('普通自然语言可能收费；General是实验性模型回答，不是现场事实或专业保证。'
    '有限文本防护可能误拦，也可能漏过隐含现场断言或知识错误；操作者须接受此剩余风险。'
    '需要监测结论时以本轮SIMULATOR来源和时效为准。失败、拒绝和送达未知不退额度、不重试。')


def preparation_path(mode='chat'):
    if mode != 'chat':raise BotError('HYBRID_TRIAL_CHAT_ONLY')
    return ROOT/'apps/ai_service/resources/qq_hybrid_real_trial.json'


def check_configuration(inputs,*,limits=RunLimits(),members=None,presentation_mode='chat'):
    if type(limits) is not RunLimits:raise BotError('INVALID_RUN_LIMITS')
    preparation_path(presentation_mode)
    access,ai,source,grant,_ = inputs_snapshot(inputs)
    selected = selected_members(inputs,access,grant,members)
    scope = prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
    check_preparation(read_json(preparation_path()),scope)
    return dict(code='HYBRID_TRIAL_CHECKED_APPROVAL_REQUIRED',contract=CONTRACT,status='candidate',
        scope_sha256=_hash(scope),preset=PRESET,provider=assistant_profile(PRESET).service_id,
        model=assistant_profile(PRESET).model,instance_id=source.instance_id,device_id=grant.device_id,
        data_root=str(source.data_root),group_ref=_hash(inputs.group_id)[:12],
        member_refs=[_hash(m)[:12] for m in selected],max_turns=limits.max_turns,seconds=limits.seconds,
        total_budget_cny=limits.total_budget_cny,reservation_per_turn_cny=str(cost_reservation()),
        total_reservation_cny=str(cost_reservation()*limits.max_turns),max_model_requests=2*limits.max_turns,
        requests_per_turn=2,output_tokens_per_request=512,seconds_per_turn=90,retries=0,
        presentation_mode='chat',qualification_id=None,general_publication_requires_operator_consent=True,
        residual_risk=RISK,credential_checked=False,business_instance_opened=False,
        network_requests=0,approval_created=False)


class HybridTrialLedger(SessionTrialLedger):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._plan.update(contract=CONTRACT,environment='EXPLICIT_EXPERIMENTAL_QQ_HYBRID')
    def report(self):return {**super().report(),'contract':CONTRACT}


class HybridTrialRun(SessionTrialRun):
    contract = CONTRACT
    consents = (*CONSENTS,'experimental_general_publication_residual_risk')
    configuration_check = staticmethod(check_configuration)
    preparation_check = staticmethod(check_preparation)
    preparation_path = staticmethod(preparation_path)
    authorization_authority = HybridRunAuthorizationAuthority

    def scope_for_options(self):return prepared_scope(self.options)
    def _check_configuration(self):
        if self.presentation_mode != 'chat':raise BotError('RUN_SCOPE_CHANGED')
        return validation_once(('hybrid-real-configuration',id(self)),
            lambda:SessionRun._check_configuration(self))
    def _new_store(self,monotonic):return HybridConversationStore(self.options,monotonic=monotonic)
    def _new_ledger(self,limits):
        return HybridTrialLedger(self.directory,scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest,limits=limits,clock=self.clock,monotonic=self.now)
    def _create_turn(self,lease,snapshot,validate):
        self.check()
        return HybridTrialQwenTurn(lease,run_authorization=self._authorization,
            authority=self.store.authority,conversation_epoch=self.base_service.epoch,
            options=self.options,snapshot=snapshot,validate=validate,
            claim=lambda:self.ledger.check_lease(lease),async_client_factory=self.factory,
            clock=self.clock,monotonic=self.now)
    def _verified_execution(self,session,report):
        result = getattr(session,'hybrid_result',None)
        return bool(result and result.publication and result.publication.allowed
            and report['model_requests']==(1 if result.branch=='general' else 2))
