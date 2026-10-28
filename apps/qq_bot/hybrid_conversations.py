"""Hybrid-only RAM codec; reuse the original budgets, tickets, revision and CAS."""
from dataclasses import asdict, dataclass

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_hybrid import HybridHistoryAuthority, HybridHistorySnapshot
from apps.ai_service.runtime.assistant import AssistantHistoryTurn, MAX_QUESTION_BYTES
from .conversations import ConversationStore, _Turn

CONTRACT = 'qq-hybrid-history@1'


def valid_question(value):
    return type(value) is str and bool(value.strip()) and len(value.encode('utf8')) <= MAX_QUESTION_BYTES


@dataclass(frozen=True, repr=False)
class HybridTurn(_Turn):
    def projection(self):
        if self.source_flags == ('general', 'model_knowledge', 'NO_OBSERVATION'):
            text = '已接受的一般性AI答复，未作事实核验、未取得现场证据：\n' + self.text
        else:
            # Never project the old assistant's numeric readings as current facts.
            text = (f'已交付水质答复；观测时间{self.source_times}；来源/有效性{self.source_flags}。'
                    '这里只保留话题与时效，不包含当前读数；本轮需要现场事实时必须重新查询Tool。')
        return AssistantHistoryTurn(self.focus, text, self.accepted_at)


class HybridConversationStore(ConversationStore):
    snapshot_type = HybridHistorySnapshot
    turn_type = HybridTurn

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.authority = HybridHistoryAuthority(asdict(self.options), self._validate)

    def valid_focus(self, focus):return valid_question(focus)

    def commit(self, snapshot, **kwargs):
        if type(snapshot) is not HybridHistorySnapshot:
            raise GatewayError('INVALID_HYBRID_HISTORY')
        flags = kwargs.get('source_flags')
        if flags != ('general', 'model_knowledge', 'NO_OBSERVATION') and (
                type(flags) is not tuple or len(flags) != 4 or flags[0] != 'simulator'):
            raise GatewayError('INVALID_HYBRID_HISTORY_SOURCE')
        return super().commit(snapshot, **kwargs)
