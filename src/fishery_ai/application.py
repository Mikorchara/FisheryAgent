"""Fixed Chat/Advice orchestration with structured results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Iterator, Protocol
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


@dataclass(frozen=True)
class AnalysisStreamEvent:
    kind: str
    data: dict


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
        "你是鳗鲡养殖分析助手。Observed Facts 是当前观测，Rule Results 是程序的确定性判断；"
        "RAG Evidence 仅是背景知识，不代表现场已发生其中描述的疾病。"
        "传感器值、观测时间、规则结论、证据来源和模型身份由程序提供，不要编造或改写。"
        "没有鱼体症状、检测结果或其他直接支持证据时，不得诊断具体疾病；"
        "没有足够疾病证据时，不得直接推荐具体药物、剂量或治疗方案。"
        "可以建议进一步观察、取样检测或显微镜检查。优先处理已确认的严重水质异常，特别是低溶氧。"
        "Inference 只写推断，Recommendations 只写建议，Uncertainty 写当前缺少的信息；"
        "若无疾病证据，应在 Uncertainty 中说明无法判断具体疾病。"
        "只输出 JSON 对象，字段为 inference 字符串、recommendations 字符串数组、"
        "uncertainty 字符串数组。"
    )
    user = (f"Observed Facts（当前观测）：{facts}\nRule Results（程序判断）：\n{rules}"
            f"\nRAG Evidence（仅供参考的背景知识）：\n{evidence}\n任务：{task}")
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

    def _retrieve_evidence(self, request: AnalysisRequest, reading: WaterQualityReading,
                           findings: tuple[RuleFinding, ...], started_at: datetime
                           ) -> tuple[KnowledgeEvidence, ...]:
        values = f"水温{_value(reading.temperature_c)} pH{_value(reading.ph)} 溶解氧{_value(reading.dissolved_oxygen_mg_l)}"
        query = (f"{request.question} {values}" if request.mode == Mode.CHAT
                 else f"{values} 养殖管理建议")
        rule_query = " ".join(f"{item.code} {item.message} {' '.join(item.facts_used)}"
                              for item in findings)
        query = f"{query} {rule_query}"
        return self.knowledge.search(query, top_k=5 if request.mode == Mode.CHAT else 4,
                                     retrieved_at=started_at, intent_text=request.question)

    def analyze(self, request: AnalysisRequest, *, scenario: str = "normal") -> AnalysisResult:
        started_at = self.clock()
        start_tick = time.monotonic()
        request_id, trace_id = self.id_factory(), self.id_factory()
        runtime = self.profiles.snapshot(request.profile_id,
                                         environ=None if self.resolve_secrets else {})
        reading = self.repository.water_quality(scenario)
        findings = self.diagnosis.diagnose(reading)  # Always runs, including Advice.
        evidence = self._retrieve_evidence(request, reading, findings, started_at)
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
                reasoning_content=response.reasoning_content,
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

    def analyze_stream(self, request: AnalysisRequest, *, scenario: str = "normal"
                       ) -> Iterator[AnalysisStreamEvent]:
        """Stream the same fixed analysis; only model transport differs from analyze()."""
        started_at = self.clock()
        start_tick = time.monotonic()
        request_id, trace_id = self.id_factory(), self.id_factory()
        yield AnalysisStreamEvent("analysis_started", {"request_id": request_id,
                                                       "trace_id": trace_id})
        runtime = None
        reading = None
        findings: tuple[RuleFinding, ...] = ()
        evidence: tuple[KnowledgeEvidence, ...] = ()
        chunks: list[str] = []
        reasoning_chunks: list[str] = []
        usage = Usage()
        usage_emitted = False
        ttft_ms: float | None = None
        try:
            runtime = self.profiles.snapshot(request.profile_id,
                                             environ=None if self.resolve_secrets else {})
            reading = self.repository.water_quality(scenario)
            yield AnalysisStreamEvent("facts_ready", {"observed_facts":
                _public_data(ObservedFacts(reading)), "runtime": _public_data(runtime.public_info())})
            findings = self.diagnosis.diagnose(reading)
            yield AnalysisStreamEvent("rules_ready", {"rule_results": _public_data(findings)})
            evidence = self._retrieve_evidence(request, reading, findings, started_at)
            yield AnalysisStreamEvent("evidence_ready", {"evidence": _public_data(evidence)})
            context = AnalysisContext(request.mode, request.question, reading, findings, evidence)
            stream = self.gateway.stream(_build_model_request(context, request), runtime)
            try:
                for event in stream:
                    if event.reasoning_delta:
                        reasoning_chunks.append(event.reasoning_delta)
                        yield AnalysisStreamEvent("reasoning_delta", {"delta": event.reasoning_delta})
                    if event.delta:
                        chunks.append(event.delta)
                        if ttft_ms is None:
                            ttft_ms = (time.monotonic() - start_tick) * 1000
                        yield AnalysisStreamEvent("content_delta", {"delta": event.delta})
                    if event.usage is not None:
                        usage = event.usage
                        usage_emitted = True
                        yield AnalysisStreamEvent("usage", {"usage": _public_data(usage)})
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            if not usage_emitted:
                yield AnalysisStreamEvent("usage", {"usage": _public_data(usage)})
            raw_text = "".join(chunks)
            inference, recommendations, uncertainty, parse_ok = _parse_model_text(raw_text)
            result = AnalysisResult(
                request_id=request_id, trace_id=trace_id, status=Status.COMPLETED,
                runtime=runtime.public_info(), observed_facts=ObservedFacts(reading),
                rule_results=findings, evidence=evidence, inference=inference,
                recommendations=recommendations, uncertainty=uncertainty,
                generated_text=raw_text, structured_parse_ok=parse_ok, usage=usage,
                reasoning_content="".join(reasoning_chunks) or None,
            )
            total_ms = (time.monotonic() - start_tick) * 1000
            self.traces.record(result, mode=request.mode, started_at=started_at,
                               finished_at=self.clock(), total_ms=total_ms)
            yield AnalysisStreamEvent("completed", {"result": result_to_dict(result),
                                                     "ttft_ms": round(ttft_ms, 3) if ttft_ms is not None else None,
                                                     "total_latency_ms": round(total_ms, 3)})
        except Exception as exc:
            code = exc.code if isinstance(exc, GatewayError) else "INTERNAL_ERROR"
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", code):
                code = "GATEWAY_ERROR"
            total_ms = (time.monotonic() - start_tick) * 1000
            if runtime is None or reading is None:
                yield AnalysisStreamEvent("failed", {"error_code": code,
                                                     "ttft_ms": None,
                                                     "total_latency_ms": round(total_ms, 3)})
                return
            result = AnalysisResult(
                request_id=request_id, trace_id=trace_id, status=Status.FAILED,
                runtime=runtime.public_info(), observed_facts=ObservedFacts(reading),
                rule_results=findings, evidence=evidence, inference="",
                recommendations=(), uncertainty=("模型调用失败；规则和证据仍可检查。",),
                generated_text="".join(chunks), structured_parse_ok=False,
                usage=usage, error_code=code,
                reasoning_content="".join(reasoning_chunks) or None,
            )
            self.traces.record(result, mode=request.mode, started_at=started_at,
                               finished_at=self.clock(), total_ms=total_ms)
            yield AnalysisStreamEvent("failed", {"result": result_to_dict(result),
                                                 "error_code": code,
                                                 "ttft_ms": round(ttft_ms, 3) if ttft_ms is not None else None,
                                                 "total_latency_ms": round(total_ms, 3)})


def _public_data(value):
    """Serialize public contracts; RuntimeSnapshot must never be passed here."""
    def convert(value):
        if hasattr(value, "__dataclass_fields__"):
            return convert(asdict(value))
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        return value
    return convert(value)


def result_to_dict(result: AnalysisResult) -> dict:
    """Public serialization contains only the safe RuntimeInfo, never the RuntimeSnapshot secret."""
    return _public_data(result)
