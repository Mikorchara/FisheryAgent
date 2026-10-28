"""Fake-only Hybrid Run, reusing the original persistent one-process quota ledger."""
from dataclasses import asdict
from pathlib import Path

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_hybrid import HybridQwenTurn, CONTRACT, prepared_scope, candidate_record
from apps.ai_service.channel_validation import ValidationBoundary, validation_once
from .conversations import ConversationOptions
from .hybrid_conversations import HybridConversationStore
from .run_consent import RunLedger
from .session_run import SessionRun
from .trial_configuration import read_json

ROOT = Path(__file__).resolve().parents[2]
NOTICE = ('除固定命令、常见问候、帮助及清空外，授权普通自然语言默认可能调用Qwen并消费共享额度；'
          '无Tool通常1请求，有Tool最多2请求，每Turn仍完整预留、失败不退款。'
          '本次仅Fake环境，General未作事实核验，未批准真实Provider/QQ或General自动发布。')


class HybridLedger(RunLedger):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._plan.update(contract=CONTRACT,environment='OFFLINE_FAKE_ONLY')

    def report(self):return {**super().report(),'contract':CONTRACT}


class HybridRun(SessionRun):
    def __init__(self,*args,**kwargs):
        self.boundary=ValidationBoundary()
        super().__init__(*args,**kwargs)

    def scope_for_options(self):return prepared_scope(self.options)
    def validation_scope(self):return self.boundary.scope()
    def _new_store(self,monotonic):return HybridConversationStore(self.options,monotonic=monotonic)

    def _new_ledger(self,limits):
        return HybridLedger(self.directory,scope_sha256=self.scope_sha256,
            bindings_sha256=self._binding_digest,limits=limits,clock=self.clock,monotonic=self.now)

    def _check_configuration(self):
        if not self.offline_test:raise GatewayError('HYBRID_FAKE_ONLY')
        def verify():
            super(HybridRun,self)._check_configuration()
            if read_json(ROOT/'apps/ai_service/resources/qq_hybrid_candidate.json')!=candidate_record(self.scope):
                raise GatewayError('HYBRID_SCOPE_REVIEW_REQUIRED')
        return validation_once(('hybrid-run-config',id(self)),verify)

    def _create_turn(self,lease,snapshot,validate):
        return HybridQwenTurn(lease,authority=self.store.authority,conversation_epoch=self.base_service.epoch,
            options=self.options,snapshot=snapshot,validate=validate,claim=lambda:self.ledger.check_lease(lease),
            async_client_factory=self.factory,clock=self.clock,monotonic=self.now,boundary=self.boundary)

    def _verified_execution(self,session,report):
        result=getattr(session,'hybrid_result',None)
        return (result is not None and result.publication is not None and result.publication.allowed
                and report['model_requests']==(1 if result.branch=='general' else 2))

    def plan(self):return {**super().plan(),'notice':NOTICE,'mode':'hybrid-fake-only'}
