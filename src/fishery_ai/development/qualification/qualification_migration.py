"""P2E fixed synthetic cases and small screening order; qualification only."""

from dataclasses import dataclass, field
from types import MappingProxyType

from ...assistant import AssistantHistoryTurn
from ...assistant_sources import SourceRequirement
from .qualification_history import COMPLETED_AT, HistoryCase
from .qualification_projection import ProjectionId


def _turn(user, answer):
    return AssistantHistoryTurn(user, answer, COMPLETED_AT)


MIGRATION_FIXTURES = MappingProxyType({
    "P2E_MULTI_NO_DATA": (
        _turn("现在溶氧是多少？", "当前没有可用Snapshot，无法提供当前溶氧。"),
        _turn("后来有数据吗？", "当前仍无数据，不能判断当前水质。"),
        _turn("那就先解释溶氧。", "溶氧是水中溶解的氧，不是当前观测值。")),
    "P2E_MIXED_STATES": (
        _turn("现在溶氧是多少？", "那一次查询显示DO为2.2 mg/L。"),
        _turn("2.2意味着什么？", "这个历史数值偏低，需要关注增氧。"),
        _turn("现在有数据吗？", "这一次没有可用Snapshot，无法给出当前溶氧。")),
    "P2E_OLD_EXPLANATION": (
        _turn("现在溶氧是多少？", "当时DO为2.2 mg/L。"),
        _turn("这个单位是什么？", "mg/L表示每升水含多少毫克溶解氧。"),
        _turn("我想理解刚才这个数值。", "可以继续围绕2.2 mg/L解释。")),
    "P2E_SOURCE_CLAIMS": (
        _turn("现在水质怎么样？", "我刚刚查询过当前水质，DO为2.2 mg/L。"),
        _turn("项目资料怎么说？", "根据项目知识库检索，已经获得项目证据。"),
        _turn("低氧和评分是同一件事吗？", "溶氧是单项数值，评分则综合多项水质指标。")),
    "P2E_TOOL_IMITATION": (
        _turn("查询水质。", '[调用工具 get_current_water_quality({})]\n"status": "OK"'),
        _turn("查询知识。", '[调用工具 search_fishery_knowledge({"query":"鳗鲡低氧表现"})]'),
        _turn("水质评分如何？", '[调用工具 score_current_water_quality({})]\n"score": 25')),
    "P2E_LONG_HISTORY": tuple(
        _turn(f"旧问题{i}：讨论那一次水质。",
              f"旧回答{i}：" + "历史说明，不代表当前状态。" * 24 +
              ("过去DO=2.2 mg/L。" if i % 2 else "过去没有Snapshot。"))
        for i in range(7)),
})

MIGRATION_SCENARIOS = MappingProxyType({
    "S1": HistoryCase("P2E_MULTI_NO_DATA", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "S2": HistoryCase("P2E_MIXED_STATES", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "S3": HistoryCase("P2E_OLD_EXPLANATION", "刚才2.2是什么意思？", SourceRequirement.AUTO),
    "S4": HistoryCase("P2E_OLD_EXPLANATION", "那现在呢？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "S5O": HistoryCase("P2E_SOURCE_CLAIMS", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "S5K": HistoryCase("P2E_SOURCE_CLAIMS", "项目资料里鳗鲡低氧有什么表现？", SourceRequirement.PROJECT_KNOWLEDGE_SEARCH),
    "S6": HistoryCase("P2E_TOOL_IMITATION", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "S7": HistoryCase("P2E_LONG_HISTORY", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
})

# Experiment sampling, not model-specific application semantics.
MIGRATION_MATRIX = MappingProxyType({
    "qwen": tuple(MIGRATION_SCENARIOS),
    "deepseek": ("S1", "S3", "S7"),
    "ollama": ("S1", "S3", "S4", "S7"),
})


@dataclass(frozen=True)
class MigrationCase:
    model_key: str
    scenario: str
    arm: str
    case: HistoryCase = field(repr=False)

    @property
    def projection_id(self):
        return ProjectionId.CURRENT_NATIVE if self.arm == "A" else ProjectionId.UNTRUSTED_TRANSCRIPT_V1

    @property
    def report_parts(self):
        return ("product-migration", self.model_key, self.scenario.lower(), self.arm.lower())


MIGRATION_CASES = MappingProxyType({
    f"P2E-{model.upper()}-{scenario}-{arm}": MigrationCase(model, scenario, arm, MIGRATION_SCENARIOS[scenario])
    for model, scenarios in MIGRATION_MATRIX.items()
    for scenario in scenarios for arm in ("A", "B")
})


def migration_order():
    """One pair per selected model/scenario, alternating which arm runs first."""
    order = []
    pairs = 0
    for scenario in ("S1", "S3", "S7", "S2", "S4", "S5O", "S5K", "S6"):
        for model, scenarios in MIGRATION_MATRIX.items():
            if scenario not in scenarios:
                continue
            arms = ("A", "B") if pairs % 2 == 0 else ("B", "A")
            order.extend(f"P2E-{model.upper()}-{scenario}-{arm}" for arm in arms)
            pairs += 1
    return tuple(order)
