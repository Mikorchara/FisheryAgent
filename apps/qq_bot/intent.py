"""Finite intent templates; neither a model router nor a business authority."""
from dataclasses import dataclass
import re
from apps.ai_service.channel_conversation import question_for


@dataclass(frozen=True)
class Intent:
    kind: str
    focus: str = 'all'
    @property
    def question(self):return question_for(self.focus)
    @property
    def text(self):
        return {'greeting':'你好，我是鱼类监测 AI 助手。可以询问当前绑定设备的水质。',
            'capabilities':'可解释当前绑定设备的模拟水质。知识、历史AI分析和写操作暂未开放；固定查询请用 /帮助。',
            'clarify':'请明确你想了解水温、pH还是溶解氧；旧对话不能证明当前水质。',
            'unsupported':'当前只支持当前水质问答，不能切换设备、查询知识或执行写操作；固定命令请用 /帮助。',
            'clear':'当前会话记忆已清空；没有修改监测事件或其他成员的会话。'}[self.kind]


@dataclass(frozen=True,repr=False)
class GatewayMention:
    owner: object
    app_id: str
    message_id: str
    raw_sha256: str


def classify(text,*,topic=None,command_priority=True):
    text=text.strip();head=text.split(maxsplit=1)[0] if text else ''
    if command_priority and head.lstrip('/').lower() in ('help','帮助','当前水质','历史水质','知识','当前异常','问ai','ai'):
        return Intent('fixed')
    if text=='/清空会话':return Intent('clear')
    if text.startswith('/') or any(w in text.lower() for w in (
            '删除','清理事件','ack','人工结束','控制','切换','修改','设置','provider','实例路径',
            '历史','过去','昨天','趋势','一小时','分钟','知识','是什么','原理','治疗','确诊')):
        return Intent('unsupported')
    focus=('dissolved_oxygen_mg_l' if re.search(r'溶解氧|溶氧|\bdo\b',text,re.I) else
           'ph' if re.search(r'ph|酸碱',text,re.I) else 'temperature_c' if re.search(r'水温|温度',text) else None)
    follow=bool(re.match(r'那|刚才|上述|然后',text)) or text.endswith(('呢','呢？','呢?'))
    if follow:
        return Intent('water',focus or topic) if topic is not None and (focus or '现在' in text) else Intent('clarify')
    if focus or '水质' in text or ('鱼塘' in text and any(w in text for w in ('现在','当前'))):
        return Intent('water',focus or 'all')
    if re.search(r'你能|能做什么|功能|怎么用|能力',text):return Intent('capabilities')
    if text.lower().strip('！!。，.?？ ') in ('你好','您好','hello','hi','谢谢','感谢'):
        return Intent('greeting')
    return Intent('clarify')
