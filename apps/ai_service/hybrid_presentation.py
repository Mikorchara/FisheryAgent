"""Fake-only publication decisions, not a universal semantic fact verifier."""
from dataclasses import dataclass, field, replace
import json
import re
import unicodedata

from .channel_chat_presentation import render_chat_reply
from .channel_presentation import assess_explanation, _unique, _not_constant

CONTRACT = 'qq-hybrid-reply@1'
GENERAL_MAX_CHARS = 600
MAX_BYTES = 4096
REFUSAL = '本轮回复未通过展示检查；没有可核实的现场结论。请明确提问或查询当前水质。'


@dataclass(frozen=True)
class HybridPresentation:
    text: str = field(repr=False)
    code: str
    allowed: bool
    branch: str
    history_allowed: bool
    facts_only: bool = False
    general_fact_verifier: bool = False


def _document(text):
    if type(text) is not str or len(text.encode('utf8')) > MAX_BYTES:
        raise ValueError('size')
    value = json.loads(text, object_pairs_hook=_unique, parse_constant=_not_constant)
    if type(value) is not dict or value.get('contract') != CONTRACT:
        raise ValueError('contract')
    if value.get('kind') == 'general' and set(value) == {'contract', 'kind', 'text'}:
        return value
    if value.get('kind') == 'water' and set(value) == {'contract', 'kind', 'plan'} and type(value['plan']) is dict:
        return value
    raise ValueError('shape')


def _general_safe(text):
    if (type(text) is not str or not text.strip() or len(text) > GENERAL_MAX_CHARS
            or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') and c not in '\n\t' for c in text)):
        return False
    normalized = ''.join(unicodedata.normalize('NFKC', text).casefold().split())
    # Conservative publication checks, NOT a business-intent admission allowlist.
    patterns = (
        r'已(?:经)?(?:读取|查询|检索|确认|删除|控制|修改|关闭|完成处置|打开设备)',
        r'(?:当前|现在|实时|此刻|这会儿|目前).{0,48}(?:水质|鱼塘|池塘|溶解氧|溶氧|ph|水温|正常|安全|恢复|低氧|放心)',
        r'(?:你的|你那边|这个|该|本).{0,12}(?:鱼塘|池塘|设备).{0,40}(?:正常|安全|健康|恢复|低氧|放心)',
        r'(?:水质|鱼塘|池塘).{0,40}(?:正常|安全|健康|恢复|很好|适养)',
        r'(?:溶解氧|溶氧|水温|ph)\s*(?:为|是|[:=])?\s*[-+]?\d',
        r'\d(?:[\d.,]*)(?:mg/l|℃|°c)',
        r'(?:规则命中|确诊|已经治愈|已恢复健康|保证.{0,12}(?:健康|适养|安全)|[药用]量|处方)',
        r'(?:toolreceipt|observation_query_completed|source_summary|can_deliver|can_send|<\|system\|>|系统指令[:：])',
        r'(?:i(?:have)?(?:queried|checked|read)|current(?:water|pond|ph|oxygen)|realtimedata)',
    )
    return not any(re.search(pattern, normalized) for pattern in patterns)


def present(result):
    """result.branch comes from actual execution steps, never the model's kind."""
    try:
        document = _document(result.model_text)
        parse_code = None
    except (ValueError, TypeError, UnicodeError, RecursionError):
        document, parse_code = {}, 'HYBRID_OUTPUT_INVALID'
    if result.branch == 'general':
        if document.get('kind') != 'general':
            return HybridPresentation(REFUSAL, parse_code or 'HYBRID_SOURCE_REQUIRED', False, 'general', False)
        text = document['text']
        if not _general_safe(text):
            return HybridPresentation(REFUSAL, 'GENERAL_PUBLICATION_REJECTED', False, 'general', False)
        return HybridPresentation('一般说明（AI生成，非现场结论）：\n' + text.strip(),
                                  'GENERAL_DRAFT_ACCEPTED_FAKE_ONLY', True, 'general', True)
    # A Tool was executed: no General prose can escape through this branch.
    plan = document.get('plan') if document.get('kind') == 'water' else None
    serialized = json.dumps(plan, ensure_ascii=False, allow_nan=False) if plan is not None else '{}'
    assessment = assess_explanation(serialized, result.source)
    focus = assessment._plan.metrics[0] if assessment.allowed and len(assessment._plan.metrics) == 1 else 'all'
    text, assessed = render_chat_reply(replace(result, model_text=serialized), focus=focus)
    code = assessed.code if plan is not None else parse_code or 'HYBRID_KIND_RECEIPT_MISMATCH'
    return HybridPresentation(text, code, assessed.allowed, 'water', True, not assessed.allowed)
