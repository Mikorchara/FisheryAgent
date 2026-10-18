"""Static display metadata, never a source of handlers or execution permission."""

from dataclasses import asdict, dataclass
from ..business_tools.current_water_quality import CURRENT_WATER_QUALITY
from ..business_tools.fishery_knowledge import SEARCH_FISHERY_KNOWLEDGE
from ..business_tools.registry import WATER_QUALITY_SCORE
from ..business_tools.water_quality_history import WATER_QUALITY_HISTORY


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
    # experimental=False is deliberate: that flag renders as "NOT PROFESSIONAL
    # STANDARD", which is a scoring claim. Knowledge search makes no scoring
    # claim; its caveats live in the description text instead.
    ToolCatalogEntry(SEARCH_FISHERY_KNOWLEDGE, "知识检索",
        "只读检索项目内鳗鲡养殖背景知识；不代表当前水质，也不做现场诊断",
        "只读检索管理端统一 SQLite 文本知识库，包含导入资料与用户内容，保留每条来源及版本。结果是背景证据而非现场事实，无合格命中时返回NO_MATCH（不是错误）。检索基线尚未做评测，知识块也没有逐条文献出处，因此不得当作专业养殖或用药依据。",
        parameter_summary="query: string（必填，1–512 字符）"),
    ToolCatalogEntry(WATER_QUALITY_HISTORY, "历史水质查询",
        "查询有限历史窗口统计与数据覆盖；不是当前观测",
        "独立本地实验：最近10/30/60分钟的窗口均值、质量、覆盖和缺口；不证明当前状态、持续低氧或恢复。"
        "NO_DATA表示无完整匹配窗口，PARTIAL保留实际限制；需维护者启动开关及用户授权。",
        parameter_summary="lookback_minutes: 10/30/60；metrics: 可选的水质指标列表"),
)



def catalog_display(name: str) -> dict:
    """Display-only labels for one tool name, for response projections.

    Says how a tool should be *labelled* to a human. Never consulted when
    deciding whether a tool may run, and never a source of handlers or schemas.
    Unknown names yield no labels rather than an invented one.
    """
    for entry in CATALOG:
        if entry.name == name:
            return {"display_name": entry.display_name, "display_summary": entry.short_description}
    return {}
