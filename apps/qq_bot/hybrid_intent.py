"""Finite free commands; all other natural language goes to the same Agent."""
from dataclasses import dataclass, field

from apps.ai_backend.model_gateway import GatewayError
from .hybrid_conversations import valid_question
from .intent import Intent

CONTRACT = 'qq-hybrid-routing@1'


@dataclass(frozen=True, repr=False)
class HybridIntent:
    question: str = field(repr=False)
    kind: str = field(default='agent', init=False)

    @property
    def focus(self):return self.question


def classify(text, *, topic=None, command_priority=True):
    if not valid_question(text):raise GatewayError('INVALID_HYBRID_QUESTION')
    text = text.strip()
    head = text.split(maxsplit=1)[0]
    if command_priority and head.lstrip('/').lower() in (
            'help', '帮助', '当前水质', '历史水质', '知识', '当前异常', '问ai', 'ai'):
        return Intent('fixed')
    if text == '/清空会话':return Intent('clear')
    if text.startswith('/'):return Intent('unsupported')
    plain = text.lower().strip('！!。，.?？ ')
    if plain in ('你好', '您好', 'hello', 'hi', '谢谢', '感谢'):return Intent('greeting')
    if plain in ('帮助', 'help', '你能做什么', '有什么功能', '怎么用'):
        return HybridHelp()
    return HybridIntent(text)


@dataclass(frozen=True)
class HybridHelp:
    kind: str = 'capabilities'
    text: str = ('可简短聊天、解释一般概念，并查询当前绑定设备的模拟水质。'
                 '其余普通自然语言可能调用模型并消费共享额度。'
                 '未开放项目知识库/历史AI分析、ACK、删除或设备控制；固定查询请用 /帮助。')
