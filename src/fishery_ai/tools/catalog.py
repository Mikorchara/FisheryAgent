"""Static display metadata, never a source of handlers or execution permission."""

from dataclasses import asdict, dataclass
from .registry import CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE


@dataclass(frozen=True)
class ToolCatalogEntry:
    name: str
    display_name: str
    short_description: str
    detailed_description: str
    access_type: str = "READ ONLY"
    dev_only: bool = False
    planned: bool = False
    parameter_summary: str = "无；参数必须为 {}"
    experimental: bool = False


CATALOG = (
    ToolCatalogEntry(CURRENT_WATER_QUALITY, CURRENT_WATER_QUALITY,
        "读取当前 canonical 水质状态", "只读查询当前 Snapshot、query-time Freshness 与 DiagnosisService Findings；无快照时返回 NO_DATA。"),
    ToolCatalogEntry(WATER_QUALITY_SCORE, "水质评分", "当前水质的简单实验评分",
        "根据当前 canonical 水质计算实验分数；EXPERIMENTAL / NOT PROFESSIONAL STANDARD，不是专业水产养殖评分标准。",
        experimental=True),
    *(ToolCatalogEntry(f"testTool_{n}", f"testTool_{n}", "开发界面布局占位",
        "UI PLACEHOLDER；没有 Handler，不能保存到实际 Policy，不会发送给模型。",
        dev_only=True, parameter_summary="不适用；不可执行") for n in range(1, 4)),
)


def tool_catalog(registry):
    """Registry-owned definitions/handlers determine the live executable flag."""
    registered = {item.name for item in registry.model_definitions()}
    return tuple({**asdict(item), "registered": item.name in registered,
                  "executable": not item.dev_only and item.name in registered
                    and callable(registry.lookup(item.name).handler),
                  "modes": ["analysis", "assistant"]} for item in CATALOG)
