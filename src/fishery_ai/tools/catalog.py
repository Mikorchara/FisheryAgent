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
        "当前水质数值、状态与告警；不负责评分", "只读查询当前Snapshot、query-time Freshness与DiagnosisService Findings；不负责评分。评分、等级、分项评分使用score_current_water_quality，同一轮不要同时调用两个Tool。无快照时返回NO_DATA。"),
    ToolCatalogEntry(WATER_QUALITY_SCORE, "水质评分", "当前水质实验评分、等级与分项评分",
        "内部已经读取当前Snapshot，计算实验评分、等级、分项评分；同一轮不要再调用get_current_water_quality。EXPERIMENTAL / NOT PROFESSIONAL STANDARD，不是专业水产养殖评分标准。",
        experimental=True),
)


def tool_catalog(registry):
    """Registry-owned definitions/handlers determine the live executable flag."""
    registered = {item.name for item in registry.model_definitions()}
    return tuple({**asdict(item), "registered": item.name in registered,
                  "executable": not item.dev_only and item.name in registered
                    and callable(registry.lookup(item.name).handler),
                  "modes": ["analysis", "assistant"]} for item in CATALOG)
