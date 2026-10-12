"""Fixed synthetic history for qualification only; never client-supplied content."""

from dataclasses import dataclass, field
from types import MappingProxyType

from ...assistant import AssistantHistoryTurn
from ...assistant_sources import SourceRequirement


COMPLETED_AT = "2026-10-01T00:00:00+00:00"
HISTORY_FIXTURES = MappingProxyType({
    "EMPTY": (),
    "OLD_DO_2_2": (AssistantHistoryTurn("现在溶氧是多少？", "当前溶氧 2.2 mg/L。", COMPLETED_AT),),
    "OLD_NO_DATA": (AssistantHistoryTurn("现在溶氧是多少？", "当前没有可用 Snapshot，因此无法给出当前溶氧。", COMPLETED_AT),),
    "OLD_SCORE_25": (AssistantHistoryTurn("当前水质评分多少？", "当前系统评分为 25/100，等级 D。", COMPLETED_AT),),
    "OLD_KNOWLEDGE_CLAIM": (AssistantHistoryTurn("鳗鲡低氧有什么表现？", "根据项目知识库检索结果，鳗鲡低氧时会出现若干表现……", COMPLETED_AT),),
})


def qualification_history(fixture_id):
    if isinstance(fixture_id, str) and fixture_id in HISTORY_FIXTURES:
        return HISTORY_FIXTURES[fixture_id]
    # Keep the prior fixture table and hashes intact; P2E is separately scoped.
    from .qualification_migration import MIGRATION_FIXTURES
    if not isinstance(fixture_id, str) or fixture_id not in MIGRATION_FIXTURES:
        raise ValueError("QUALIFICATION_HISTORY_FIXTURE_INVALID")
    return MIGRATION_FIXTURES[fixture_id]


@dataclass(frozen=True)
class HistoryCase:
    fixture_id: str
    question: str = field(repr=False)
    requirement: SourceRequirement


HISTORY_CASES = MappingProxyType({
    "H0": HistoryCase("EMPTY", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "H1": HistoryCase("OLD_DO_2_2", "现在还是 2.2 吗？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "H2": HistoryCase("OLD_NO_DATA", "现在溶氧是多少？", SourceRequirement.CURRENT_OBSERVATION_QUERY),
    "H3": HistoryCase("EMPTY", "当前水质评分多少？", SourceRequirement.CURRENT_SCORE_EVALUATION),
    "H4": HistoryCase("OLD_SCORE_25", "当前水质评分多少？", SourceRequirement.CURRENT_SCORE_EVALUATION),
    "H5": HistoryCase("OLD_DO_2_2", "刚才 2.2 是什么意思？", SourceRequirement.AUTO),
    "H6": HistoryCase("OLD_KNOWLEDGE_CLAIM", "项目资料里鳗鲡低氧有什么表现？", SourceRequirement.PROJECT_KNOWLEDGE_SEARCH),
})
HISTORY_PRESET = "dashscope-qwen38-flash-r1"
HISTORY_TOOLS = ("get_current_water_quality", "score_current_water_quality", "search_fishery_knowledge")
