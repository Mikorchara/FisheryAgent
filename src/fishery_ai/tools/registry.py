"""Explicit static allowlist. No registration, discovery, or dynamic loading."""

from functools import partial
from types import MappingProxyType

from ..domain import DiagnosisService
from ..model_gateway import ModelToolDefinition
from ..telemetry.current import CurrentWaterQualityReader
from .contracts import ToolDefinition, ToolError, ToolErrorCode
from .water_quality import get_current_water_quality

CURRENT_WATER_QUALITY = "get_current_water_quality"


class ToolRegistry:
    @staticmethod
    def registered_names() -> tuple[str, ...]:
        """Same fixed name used below; Policy may only restrict this allowlist."""
        return (CURRENT_WATER_QUALITY,)

    def __init__(self, reader: CurrentWaterQualityReader, diagnosis: DiagnosisService):
        definition = ModelToolDefinition(
            name=CURRENT_WATER_QUALITY,
            description="只读查询当前水质、数据质量、新鲜度和确定性诊断；无快照时返回 NO_DATA。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )
        self._entries = MappingProxyType({definition.name: ToolDefinition(
            definition, partial(get_current_water_quality, reader=reader, diagnosis=diagnosis))})

    def lookup(self, name: str) -> ToolDefinition:
        definition = self._entries.get(name)
        if definition is None:
            raise ToolError(ToolErrorCode.UNKNOWN_TOOL)
        return definition

    def model_definitions(self) -> tuple[ModelToolDefinition, ...]:
        return tuple(item.model_definition for item in self._entries.values())
