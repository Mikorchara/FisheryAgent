"""Experimental @2 General release guard; not a semantic fact verifier.

Only the new operator-approved QQ Hybrid trial uses this version. Old Fake,
research and Water contracts retain their own meaning.
"""
from dataclasses import replace
import json
import re
import unicodedata

from .hybrid_presentation import HybridPresentation, REFUSAL, _general_safe, present as legacy_present

CONTRACT = 'qq-hybrid-reply@2'


class OutputError(ValueError):
    def __init__(self, code):self.code = code


def document(text):
    if type(text) is not str:raise OutputError('HYBRID_JSON_TYPE')
    if len(text.encode('utf8')) > 4096:raise OutputError('HYBRID_JSON_TOO_LARGE')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:raise OutputError('HYBRID_JSON_DUPLICATE_FIELD')
            result[key] = value
        return result
    def constant(_):raise OutputError('HYBRID_JSON_NONFINITE')
    try:value = json.loads(text, object_pairs_hook=unique, parse_constant=constant)
    except OutputError:raise
    except (ValueError, TypeError, RecursionError):raise OutputError('HYBRID_JSON_SYNTAX') from None
    if type(value) is not dict:raise OutputError('HYBRID_JSON_OBJECT_REQUIRED')
    if value.get('contract') != CONTRACT:raise OutputError('HYBRID_ENVELOPE_VERSION')
    fields = {'general': {'contract','kind','text'}, 'water': {'contract','kind','plan'}}
    kind = value.get('kind')
    if type(kind) is not str or kind not in fields or set(value) != fields[kind]:
        raise OutputError('HYBRID_ENVELOPE_FIELDS')
    if kind == 'water' and type(value['plan']) is not dict:raise OutputError('HYBRID_PLAN_TYPE')
    return value


def general_safe(text):
    if (type(text) is not str or not text.strip() or len(text) > 600
            or any(unicodedata.category(c) in ('Cc','Cf','Cs') and c not in '\n\t' for c in text)):
        return False
    normalized = unicodedata.normalize('NFKC',text).casefold()
    # Denials are narrowly recognized whole clauses, never a blanket exemption
    # for every sentence containing 不. A positive clause is checked separately.
    denials = (
        r'(?:我|本助手|系统|本轮)?(?:不能|无法|没有|尚未)(?:仅凭聊天|据此)?'
        r'(?:确认|保证|判断)(?:当前|现场|鱼群|水质|鱼塘|池塘|的|已经|是否|安全|正常|健康|适养|无风险|恢复)+',
        r'(?:不能|无法)仅凭聊天(?:确诊|诊断)鱼病',
        r'(?:我|本助手|系统|本轮)?(?:没有|尚未|不能|无法)(?:查询|读取)(?:当前|实时|现场|监测|的|数据|水质)+',
        r'(?:我|本助手|系统)?(?:不能|不会|无法)(?:执行|控制|删除|修改|操作)(?:设备|规则|事件|记录|配置|或|和|、)+',
    )
    clauses = re.split(r'[。！？!?；;，,\n]|但是|不过|然而|但', normalized)
    for clause in clauses:
        clause = ''.join(clause.split()).strip()
        if not clause:continue
        if any(re.fullmatch(pattern,clause) for pattern in denials):continue
        if not _general_safe(clause):return False
        if re.search(r'(?:您那里|你那里|你那儿|那边|现场|此时).{0,32}(?:稳|安心|放心|没问题|安全|正常|适养)',clause):
            return False
        if re.search(r'(?:已|已经)(?:启动|停止|打开|关闭|设置|执行|处理|完成)',clause):return False
    return True


def present(result):
    try:value = document(result.model_text)
    except (OutputError, UnicodeError) as error:
        code = getattr(error,'code','HYBRID_JSON_ENCODING')
        if result.branch == 'general':return HybridPresentation(REFUSAL,code,False,'general',False)
        fallback = legacy_present(replace(result,model_text='{}'))
        return replace(fallback,code=code)
    if result.branch == 'general':
        if value['kind'] != 'general':return HybridPresentation(REFUSAL,'HYBRID_SOURCE_REQUIRED',False,'general',False)
        if not general_safe(value['text']):return HybridPresentation(REFUSAL,'GENERAL_PUBLICATION_REJECTED',False,'general',False)
        return HybridPresentation('实验性 AI 一般回答（非现场监测结论）：\n'+value['text'].strip(),
            'GENERAL_EXPERIMENTAL_CONTRACT_VALID',True,'general',True)
    # Actual Tool steps force the original closed Water assessment; no free prose.
    value['contract'] = 'qq-hybrid-reply@1'
    assessed = legacy_present(replace(result,model_text=json.dumps(value,ensure_ascii=False)))
    return replace(assessed,text='本轮监测摘要（SIMULATOR；不代替一般知识解释）：\n'+assessed.text)
