"""Fixed Chat/Advice orchestration with structured results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Protocol
import json
import re
import time
import uuid

from .contracts import (AnalysisRequest, AnalysisResult, KnowledgeEvidence, Mode,
                        ObservedFacts, RuleFinding, Status, Usage, WaterQualityReading, utcnow)
from .domain import DiagnosisService
from .knowledge import KnowledgeService
from .model_gateway import (GatewayError, ModelGateway, ModelMessage, ModelRequest,
                            ModelResponse, ProfileRegistry)
from .observability import JsonlTraceSink


class WaterQualityRepository(Protocol):
    def water_quality(self, scenario: str) -> WaterQualityReading: ...


@dataclass(frozen=True)
class AnalysisContext:
    mode: Mode
    question: str
    reading: WaterQualityReading
    findings: tuple[RuleFinding, ...]
    evidence: tuple[KnowledgeEvidence, ...]


def _value(value: float | None) -> str:
    return "--" if value is None else f"{value:g}"


def _build_model_request(context: AnalysisContext, request: AnalysisRequest) -> ModelRequest:
    reading = context.reading
    facts = (
        f"水温 {_value(reading.temperature_c)} °C；pH {_value(reading.ph)}；"
        f"溶氧 {_value(reading.dissolved_oxygen_mg_l)} mg/L。"
        f"观测时间 {reading.observed_at.isoformat()}；质量 {reading.quality.value}；"
        f"新鲜度 {reading.freshness.value}。"
    )
    rules = "\n".join(f"- [{item.code}/{item.severity}] {item.message}"
                      for item in context.findings) or "- 无阈值告警"
    evidence = "\n".join(f"- [{item.evidence_id}/{item.category}, source={item.source_id}, {item.score:.2f}] {item.text}"
                         for item in context.evidence) or "- 未检索到相关知识"
    task = ("请回答用户当前问题：" + context.question) if context.mode == Mode.CHAT else "请给出当前养殖环境的评估与管理建议。"
    system = (
        "你是鳗鲡养殖分析助手。传感器值、观测时间、规则结论、证据来源和模型身份由程序提供，"
        "不要编造或改写它们。只输出 JSON 对象，字段为 inference 字符串、"
        "recommendations 字符串数组、uncertainty 字符串数组。缺少数据时说明不确定性。"
    )
    user = f"当前水质：{facts}\n规则结果：\n{rules}\n检索证据：\n{evidence}\n任务：{task}"
    return ModelRequest(context.mode, (ModelMessage("system", system), ModelMessage("user", user)),
                        generation=request.generation, reasoning=request.reasoning)


def _parse_model_text(text: str) -> tuple[str, tuple[str, ...], tuple[str, ...], bool]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", candidate,
                          flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        data = json.loads(candidate)
        inference = data["inference"]
        recommendations = data["recommendations"]
        uncertainty = data.get("uncertainty", [])
        if (not isinstance(inference, str) or not isinstance(recommendations, list)
                or not isinstance(uncertainty, list)
                or not all(isinstance(item, str) for item in recommendations + uncertainty)):
            raise ValueError("wrong model schema")
        return inference, tuple(recommendations), tuple(uncertainty), True
    except (ValueError, TypeError, KeyError):
        return text, (), ("模型输出未能解析为结构化 JSON；原文保留在 generated_text 中。",), False


class Orchestrator:
    def __init__(self, repository: WaterQualityRepository, diagnosis: DiagnosisService,
                 knowledge: KnowledgeService, profiles: ProfileRegistry,
                 gateway: ModelGateway, traces: JsonlTraceSink,
                 *, clock: Callable[[], datetime] = utcnow,
                 id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
                 resolve_secrets: bool = True):
        self.repository = repository
        self.diagnosis = diagnosis
        self.knowledge = knowledge
        self.profiles = profiles
        self.gateway = gateway
        self.traces = traces
        self.clock = clock
        self.id_factory = id_factory
        self.resolve_secrets = resolve_secrets

    def analyze(self, request: AnalysisRequest, *, scenario: str = "normal") -> AnalysisResult:
        started_at = self.clock()
        start_tick = time.monotonic()
        request_id, trace_id = self.id_factory(), self.id_factory()
        runtime = self.profiles.snapshot(request.profile_id,
                                         environ=None if self.resolve_secrets else {})
        reading = self.repository.water_quality(scenario)
        findings = self.diagnosis.diagnose(reading)  # Always runs, including Advice.
        values = f"水温{_value(reading.temperature_c)} pH{_value(reading.ph)} 溶解氧{_value(reading.dissolved_oxygen_mg_l)}"
        query = (f"{request.question} {values}" if request.mode == Mode.CHAT
                 else f"{values} 养殖管理建议")
        evidence = self.knowledge.search(query, top_k=5 if request.mode == Mode.CHAT else 4,
                                         retrieved_at=started_at)
        context = AnalysisContext(request.mode, request.question, reading, findings, evidence)
        model_request = _build_model_request(context, request)
        try:
            response: ModelResponse = self.gateway.complete(model_request, runtime)
            inference, recommendations, uncertainty, parse_ok = _parse_model_text(response.text)
            result = AnalysisResult(
                request_id=request_id, trace_id=trace_id, status=Status.COMPLETED,
                runtime=runtime.public_info(), observed_facts=ObservedFacts(reading),
                rule_results=findings, evidence=evidence, inference=inference,
                recommendations=recommendations, uncertainty=uncertainty,
                generated_text=response.text, structured_parse_ok=parse_ok,
                usage=response.usage or Usage(),
            )
        except GatewayError as exc:
            result = AnalysisResult(
                request_id=request_id, trace_id=trace_id, status=Status.FAILED,
                runtime=runtime.public_info(), observed_facts=ObservedFacts(reading),
                rule_results=findings, evidence=evidence, inference="",
                recommendations=(), uncertainty=("模型调用失败；规则和证据仍可检查。",),
                generated_text="", structured_parse_ok=False, error_code=exc.code,
                error_option=exc.option,
            )
        finished_at = self.clock()
        self.traces.record(result, mode=request.mode, started_at=started_at,
                           finished_at=finished_at, total_ms=(time.monotonic() - start_tick) * 1000)
        return result


def result_to_dict(result: AnalysisResult) -> dict:
    """Public serialization contains only the safe RuntimeInfo, never the RuntimeSnapshot secret."""
    def convert(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        return value
    return convert(asdict(result))
