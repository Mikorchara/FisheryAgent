"""Session-only concise view of the same source and closed explanation contract."""
from datetime import datetime, timedelta, timezone
import math

from apps.ai_backend.model_gateway import GatewayError
from .channel_presentation import assess_explanation, ExplanationAssessment, _Plan, _usable

CONTRACT = 'qq-current-chat-presentation@1'
MODES = ('chat', 'detailed')
LABELS = {'temperature_c': '水温', 'ph': 'pH', 'dissolved_oxygen_mg_l': '溶解氧'}
STATES = {'valid': '有效', 'partial': '部分有效', 'invalid': '无效', 'missing': '缺测',
          'fresh': '新鲜', 'stale': '过期', 'unknown': '未知', 'online': '在线',
          'offline': '离线', 'never_received': '尚未接收'}
ADVICE = {'verify_observation': '请人工核对后续观测。',
          'review_rules': '请人工复核规则与观测证据，不自动处置。',
          'check_reporting': '建议检查模拟数据上报、质量和时间。',
          'continue_observation': '可继续观察后续窗口，单窗口不代表长期趋势。'}
BEIJING = timezone(timedelta(hours=8), '北京时间')


def validate_mode(mode):
    if type(mode) is not str or mode not in MODES:
        raise GatewayError('INVALID_SESSION_PRESENTATION')
    return mode


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(BEIJING).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, AttributeError, OverflowError):
        return '未知'


def _valid(metric):
    return (metric.quality == 'valid' and type(metric.value) in (int, float)
            and math.isfinite(metric.value))


def render_chat_reply(result, *, focus='all', max_chars=1600):
    if focus not in ('all', *LABELS):
        raise GatewayError('INVALID_CONVERSATION_TOPIC')
    source = result.source
    if source is None or source.source_kind != 'simulator':
        raise GatewayError('CHANNEL_SOURCE_UNAVAILABLE')
    assessment = (assess_explanation(result.model_text, source)
        if result.completed and result.error_code is None else ExplanationAssessment('BACKEND_NOT_COMPLETED'))
    observed, evaluated = _time(source.observed_at), _time(source.evaluated_at)
    usable = _usable(source) and observed != '未知' and evaluated != '未知'
    lines = [f'SIMULATOR 模拟数据 · {source.device_id}']
    if not usable:
        lines.append('当前状态不能完整确认。')
    warnings = []
    if source.freshness != 'fresh':
        warnings.append('数据过期' if source.freshness == 'stale' else '时效未知')
    if source.connectivity != 'online':
        warnings.append({'offline': '设备离线', 'never_received': '尚未接收上报'}.get(
            source.connectivity, '连接状态未知'))
    if warnings:
        lines.append('、'.join(warnings) + '；以下仅为留存读数。')
    if observed == '未知' or evaluated == '未知':
        lines.append('观测或评估时间未知，不能据此判断当前状态。')
    if source.status == 'NO_DATA':
        lines.append('尚无可用观测。')
    selected = [m for m in source.metrics if focus == 'all' or m.id == focus]
    for metric in selected:
        if metric.id not in LABELS:
            raise GatewayError('CHANNEL_SOURCE_INVALID')
        value = (str(metric.value) + (' ' + metric.unit if metric.unit else '') if _valid(metric)
                 else '数据不足（' + STATES.get(metric.quality, '未知') + '）')
        lines.append(LABELS[metric.id] + '：' + value)
    # Focus never conceals an unrelated missing/invalid metric or a rule HIT.
    for metric in source.metrics:
        if metric not in selected and not _valid(metric):
            lines.append(LABELS[metric.id] + '：数据不足（' + STATES.get(metric.quality, '未知') + '）')
    if source.rule_hits:
        lines.append('系统实验规则：' + '；'.join(r.message + '（' +
            {'critical': '严重', 'warning': '提醒', 'info': '提示'}.get(r.severity, r.severity) + '）'
            for r in source.rule_hits) + '。不替代专业判断。')
    elif usable:
        lines.append('本窗口未触发水质实验规则，不等于专业健康判断。')
    footer = (f'观测 {observed}；评估 {evaluated}（北京时间 UTC+08）。\n评估时：' +
        '/'.join(STATES.get(v, '未知') for v in (source.quality, source.freshness, source.connectivity)) +
        '；查询未重新采样。')
    facts = '\n'.join(lines)
    fallback = facts + '\nAI 解释未通过校验，仅展示系统事实。\n' + footer
    if type(max_chars) is not int or max_chars < 1:
        raise GatewayError('AI_REPLY_TOO_LONG')
    if assessment.allowed and type(assessment._plan) is _Plan:
        text = (facts + '\nAI 建议（已校验，未执行）：' +
                ''.join(ADVICE[name] for name in assessment._plan.advice) + '\n' + footer)
        if len(text) <= max_chars:
            return text, assessment
        assessment = ExplanationAssessment('EXPLANATION_REPLY_BUDGET_EXCEEDED')
    if len(fallback) > max_chars:
        raise GatewayError('AI_REPLY_TOO_LONG')
    return fallback, assessment
