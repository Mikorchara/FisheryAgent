"""Explicit static allowlist. No registration, discovery, or dynamic loading."""

from functools import partial
from types import MappingProxyType

from ..domain import DiagnosisService
from ..knowledge import KnowledgeService
from ..model_gateway import ModelToolDefinition
from ..telemetry.current import CurrentWaterQualityReader
from ..water_quality_scoring import WaterQualityScoringService
from .contracts import ToolDefinition, ToolError, ToolErrorCode
from .handlers.current_water_quality import get_current_water_quality
from .handlers.knowledge_search import search_fishery_knowledge
from .handlers.knowledge_search import validate_arguments as validate_knowledge_arguments
from .handlers.water_quality_score import score_current_water_quality

CURRENT_WATER_QUALITY = "get_current_water_quality"
WATER_QUALITY_SCORE = "score_current_water_quality"
SEARCH_FISHERY_KNOWLEDGE = "search_fishery_knowledge"

KNOWLEDGE_DESCRIPTION = (
    "只读检索项目内鳗鲡养殖背景知识；用于用户明确要求查询项目资料，或回答依赖项目特有资料的问题。"
    "query应表达要检索的主题。返回有限背景证据及来源，不代表当前水质或现场事实，不诊断现场疾病，不负责当前评分。"
    "NO_MATCH表示检索正常完成但无合格命中，不是执行错误；不得编造命中内容。"
)
KNOWLEDGE_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 512}},
    "required": ["query"],
    "additionalProperties": False,
}


class ToolRegistry:
    @staticmethod
    def registered_names() -> tuple[str, ...]:
        """Complete fixed name allowlist: Policy defaults and safe-output sanitizers.

        This is every name this codebase knows, not the set one instance can run.
        An instance binds only the tools whose dependencies it was given, so
        `model_definitions()` and `lookup()` stay consistent with each other and
        never advertise something they cannot resolve.
        """
        return (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE)

    def __init__(self, reader: CurrentWaterQualityReader, diagnosis: DiagnosisService,
                 scoring: WaterQualityScoringService | None = None,
                 knowledge: KnowledgeService | None = None):
        definition = ModelToolDefinition(
            name=CURRENT_WATER_QUALITY,
            description=("只读查询当前水质数值、状态、告警；用于确认当前系统水质及其追问，不负责评分、等级或分项评分。"
                         "返回当前快照的水质观测、数据质量、新鲜度、观测与评估时间及确定性诊断。"
                         "NO_DATA表示查询完成但无快照；存在快照时OK不代表数据一定有效、完整或新鲜，须按quality/freshness说明INVALID、PARTIAL或STALE。"
                         "查询不等于重新采样。"),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )
        score_definition = ModelToolDefinition(name=WATER_QUALITY_SCORE,
            description=("只读计算当前水质的实验评分、等级和分项评分；用于查询当前系统评分、打分或评级。"
                         "内部读取当前快照，同时返回参与评分的水质观测、质量、新鲜度及时间，无需再调用水质查询。"
                         "NO_DATA表示无快照；NOT_SCORABLE表示数据无效、没有可用评分；PARTIAL表示仅按可用分项评分，不是完整评分。"
                         "不提供疾病诊断。EXPERIMENTAL / NOT PROFESSIONAL STANDARD；不是专业养殖标准。"),
            parameters={"type": "object", "properties": {}, "additionalProperties": False})
        entries = {definition.name: ToolDefinition(
            definition, partial(get_current_water_quality, reader=reader, diagnosis=diagnosis)),
            score_definition.name: ToolDefinition(score_definition,
                partial(score_current_water_quality, reader=reader, scoring=scoring or WaterQualityScoringService()))}
        if knowledge is not None:
            # Bound only when the shared service is supplied: a registered entry
            # always has an executable handler, and an unbound name is simply not
            # exposed by this instance.
            entries[SEARCH_FISHERY_KNOWLEDGE] = ToolDefinition(
                ModelToolDefinition(SEARCH_FISHERY_KNOWLEDGE, KNOWLEDGE_DESCRIPTION, KNOWLEDGE_PARAMETERS),
                partial(search_fishery_knowledge, service=knowledge),
                validate_arguments=validate_knowledge_arguments)
        self._entries = MappingProxyType(entries)

    def lookup(self, name: str) -> ToolDefinition:
        definition = self._entries.get(name)
        if definition is None:
            raise ToolError(ToolErrorCode.UNKNOWN_TOOL)
        return definition

    def model_definitions(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(item.model_definition for item in self._entries.values())
