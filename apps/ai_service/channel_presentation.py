"""Conservative channel presentation: facts render; unverified prose never renders."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


PRESENTATION_CONTRACT='qq-current-facts-withheld-explanation@1'
_LABELS={
    'temperature_c':r'(?:水温|温度|temperature)',
    'ph':r'(?:pH|酸碱度)',
    'dissolved_oxygen_mg_l':r'(?:溶解氧|溶氧|DO)',
}


@dataclass(frozen=True)
class ExplanationAssessment:
    code: str
    allowed: bool = False
    general_fact_verifier: bool = False


def assess_explanation(text, source):
    """Diagnostic hints only. Even matching numbers do not prove a sentence safe.

    Conservative lexical checks may reject quoted/negated examples too. No raw
    model text or extracted readings are retained in the assessment/log contract.
    """
    if source is None:return ExplanationAssessment('SOURCE_UNAVAILABLE')
    if not isinstance(text,str) or not text.strip():return ExplanationAssessment('EXPLANATION_EMPTY')
    if len(text)>8192:return ExplanationAssessment('EXPLANATION_TOO_LONG')
    if source.source_kind=='simulator' and re.search(r'真实传感器|真实设备实测|现场实测',text):
        return ExplanationAssessment('SOURCE_CLAIM_CONFLICT')
    if not source.current_evidence_usable and re.search(r'全部正常|一切正常|实时正常|当前正常|已恢复健康',text):
        return ExplanationAssessment('OBSERVATION_LIMIT_CONFLICT')
    if re.search(r'(?:我|系统|机器人)?已(?:经)?(?:删除|确认|控制|修改规则|关闭设备|完成处置)',text):
        return ExplanationAssessment('UNSUPPORTED_ACTION_CLAIM')
    for metric in source.metrics:
        label=_LABELS.get(metric.id)
        if not label:continue
        for value in re.findall(label+r'\s*(?:为|是|=|：|:)\s*(-?\d+(?:\.\d+)?)',text,re.I):
            if metric.quality!='valid' or metric.value is None:
                return ExplanationAssessment('UNSUPPORTED_READING_CLAIM')
            try:
                if Decimal(value)!=Decimal(str(metric.value)):
                    return ExplanationAssessment('READING_CLAIM_CONFLICT')
            except InvalidOperation:return ExplanationAssessment('READING_CLAIM_CONFLICT')
    return ExplanationAssessment('UNVERIFIED_FREE_TEXT')


def render_channel_reply(result):
    assessment=assess_explanation(result.model_text,result.source)
    # No branch can expose model text. A future safe explanation policy needs a
    # separately reviewed contract/Scope; changing a boolean is not sufficient.
    return ('A. 系统事实（可信 Monitoring Tool）\n'+result.presentation+
        '\nB. 模型解释（与系统事实独立）\n未展示：本轮自由文本尚未可靠核验。'
        '\n质量、新鲜度及连接状态均为上述评估时刻的判断；发送时未重新采样。'),assessment
