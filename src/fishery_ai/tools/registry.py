"""Explicit static allowlist. No registration, discovery, or dynamic loading."""

from functools import partial
from types import MappingProxyType

from ..domain import DiagnosisService
from ..model_gateway import ModelToolDefinition
from ..telemetry.current import CurrentWaterQualityReader
from ..water_quality_scoring import WaterQualityScoringService
from .contracts import ToolDefinition, ToolError, ToolErrorCode
from .handlers.current_water_quality import get_current_water_quality
from .handlers.water_quality_score import score_current_water_quality

CURRENT_WATER_QUALITY = "get_current_water_quality"
WATER_QUALITY_SCORE = "score_current_water_quality"


class ToolRegistry:
    @staticmethod
    def registered_names() -> tuple[str, ...]:
        """Same fixed name used below; Policy may only restrict this allowlist."""
        return (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE)

    def __init__(self, reader: CurrentWaterQualityReader, diagnosis: DiagnosisService,
                 scoring: WaterQualityScoringService | None = None):
        definition = ModelToolDefinition(
            name=CURRENT_WATER_QUALITY,
            description="只读查询当前水质数值、状态、告警、数据质量、新鲜度和确定性诊断；不负责评分。当前评分、等级、分项评分应使用score_current_water_quality，不要同时调用两个Tool。无快照时返回NO_DATA。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )
        score_definition = ModelToolDefinition(name=WATER_QUALITY_SCORE,
            description="只读为当前水质计算实验评分、等级和分项评分；用于当前评分、打分、评级问题。内部已经读取当前Snapshot，同一轮不要再调用get_current_water_quality。EXPERIMENTAL / NOT PROFESSIONAL STANDARD；不是专业养殖标准。无参数，无快照时NO_DATA。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False})
        self._entries = MappingProxyType({definition.name: ToolDefinition(
            definition, partial(get_current_water_quality, reader=reader, diagnosis=diagnosis)),
            score_definition.name: ToolDefinition(score_definition,
                partial(score_current_water_quality, reader=reader, scoring=scoring or WaterQualityScoringService()))})

    def lookup(self, name: str) -> ToolDefinition:
        definition = self._entries.get(name)
        if definition is None:
            raise ToolError(ToolErrorCode.UNKNOWN_TOOL)
        return definition

    def model_definitions(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(item.model_definition for item in self._entries.values())
