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
            description="只读查询当前水质、数据质量、新鲜度和确定性诊断；无快照时返回 NO_DATA。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )
        score_definition = ModelToolDefinition(name=WATER_QUALITY_SCORE,
            description="只读为当前 canonical 水质计算简单实验评分、分项分数和等级。EXPERIMENTAL / NOT PROFESSIONAL STANDARD；不是专业养殖标准。无参数，无快照时 NO_DATA。",
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
