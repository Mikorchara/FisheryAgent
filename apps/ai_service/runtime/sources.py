"""Internal turn-scoped receipts derived only from backend tool execution.

No message inspection, history projection, routing, transport or tool execution.
These receipts certify returned sources, not the truth of free-form model text.
"""

from dataclasses import dataclass
from enum import Enum
import math

from apps.monitoring.water_contracts import Freshness, Quality, WaterQualityReading, parse_time
from apps.ai_backend.tool_conversation import ModelExecutionStep, ToolConversationResult, ToolExecutionStep
from apps.ai_backend.tools.contracts import ToolStatus
from apps.monitoring.history import MAX_HISTORY_ROWS, LOOKBACK_MINUTES
from ..business_tools.current_water_quality import CURRENT_WATER_QUALITY
from ..business_tools.fishery_knowledge import SEARCH_FISHERY_KNOWLEDGE
from ..business_tools.registry import WATER_QUALITY_SCORE
from ..business_tools.water_quality_history import WATER_QUALITY_HISTORY, result_metadata as history_metadata

HISTORY_SOURCE_CONTRACT_VERSION = 'historical-water-receipt@1'


class SourceRequirement(str, Enum):
    AUTO = "AUTO"
    CURRENT_OBSERVATION_QUERY = "CURRENT_OBSERVATION_QUERY"
    CURRENT_SCORE_EVALUATION = "CURRENT_SCORE_EVALUATION"
    PROJECT_KNOWLEDGE_SEARCH = "PROJECT_KNOWLEDGE_SEARCH"
    HISTORICAL_WATER_QUERY = "HISTORICAL_WATER_QUERY"


class TurnSource(str, Enum):
    CURRENT_TOOL_OBSERVATION = "CURRENT_TOOL_OBSERVATION"
    CURRENT_TOOL_SCORE = "CURRENT_TOOL_SCORE"
    RETRIEVED_PROJECT_EVIDENCE = "RETRIEVED_PROJECT_EVIDENCE"
    HISTORICAL_WATER_OBSERVATIONS = "HISTORICAL_WATER_OBSERVATIONS"


@dataclass(frozen=True)
class TurnSourceReceipt:
    """Finite metadata, not a copy of values, scores, query or evidence text.

    Completed operations and available sources are independent: a valid NO_DATA
    or NO_MATCH completes an operation without granting its positive payload.
    Observation certifies an existing canonical snapshot, including an invalid
    one; quality/freshness/available_fields preserve its limitations.
    """

    sources: frozenset[TurnSource] = frozenset()
    tool_name: str | None = None
    tool_status: ToolStatus | None = None
    quality: Quality | None = None
    freshness: Freshness | None = None
    observed_at: str | None = None
    evaluated_at: str | None = None
    available_fields: tuple[str, ...] = ()
    observation_query_completed: bool = False
    score_evaluation_completed: bool = False
    project_search_completed: bool = False
    evidence_count: int = 0
    history_query_completed: bool = False
    history_range_start: str | None = None
    history_range_end: str | None = None
    history_window_count: int = 0
    history_reliable_windows: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "sources", frozenset(self.sources))
        object.__setattr__(self, "available_fields", tuple(self.available_fields))
        object.__setattr__(self, "history_reliable_windows", tuple(tuple(item) for item in self.history_reliable_windows))
        if (any(not isinstance(source, TurnSource) for source in self.sources)
                or any(key not in _WATER_FIELDS for key in self.available_fields)
                or any(type(value) is not bool for value in (
                    self.observation_query_completed, self.score_evaluation_completed,
                    self.project_search_completed, self.history_query_completed))
                or type(self.evidence_count) is not int or not 0 <= self.evidence_count <= 3):
            raise ValueError("invalid source receipt")
        if (type(self.history_window_count) is not int or not 0 <= self.history_window_count <= MAX_HISTORY_ROWS
                or len(self.history_reliable_windows) > 3
                or any(len(item) != 2 or item[0] not in _WATER_FIELDS or type(item[1]) is not int
                       or not 0 <= item[1] <= self.history_window_count for item in self.history_reliable_windows)
                or len({item[0] for item in self.history_reliable_windows}) != len(self.history_reliable_windows)):
            raise ValueError("invalid historical receipt")
        if self.history_query_completed:
            if (self.tool_name != WATER_QUALITY_HISTORY or self.observation_query_completed
                    or self.score_evaluation_completed or self.project_search_completed
                    or self.available_fields or self.quality is not None or self.freshness is not None
                    or self.observed_at is not None or not self.history_reliable_windows
                    or (parse_time(self.history_range_end) - parse_time(self.history_range_start)).total_seconds() not in tuple(m * 60 for m in LOOKBACK_MINUTES)
                    or self.evaluated_at != self.history_range_end
                    or self.sources != (frozenset({TurnSource.HISTORICAL_WATER_OBSERVATIONS})
                        if any(n for _, n in self.history_reliable_windows) else frozenset())):
                raise ValueError("invalid historical receipt")
        elif (self.history_range_start is not None or self.history_range_end is not None
                or self.history_window_count or self.history_reliable_windows
                or TurnSource.HISTORICAL_WATER_OBSERVATIONS in self.sources):
            raise ValueError("historical receipt requires completed query")

    @property
    def has_observation(self) -> bool:
        return TurnSource.CURRENT_TOOL_OBSERVATION in self.sources

    @property
    def has_score(self) -> bool:
        return TurnSource.CURRENT_TOOL_SCORE in self.sources

    @property
    def has_project_evidence(self) -> bool:
        return TurnSource.RETRIEVED_PROJECT_EVIDENCE in self.sources

    @property
    def has_historical_observations(self) -> bool:
        return TurnSource.HISTORICAL_WATER_OBSERVATIONS in self.sources

    def to_dict(self) -> dict:
        """Safe internal/qualification summary; not added to the Web response."""
        result = {"sources": sorted(source.value for source in self.sources),
                "tool_name": self.tool_name, "tool_status": self.tool_status.value if self.tool_status else None,
                "quality": self.quality.value if self.quality else None,
                "freshness": self.freshness.value if self.freshness else None,
                "observed_at": self.observed_at, "evaluated_at": self.evaluated_at,
                "available_fields": list(self.available_fields),
                "observation_query_completed": self.observation_query_completed,
                "score_evaluation_completed": self.score_evaluation_completed,
                "project_search_completed": self.project_search_completed,
                "has_observation": self.has_observation, "has_score": self.has_score,
                "has_project_evidence": self.has_project_evidence,
                "evidence_count": self.evidence_count}
        # Existing receipts retain byte-for-byte DTO compatibility. Historical
        # fields are not a second payload and are never Web-controlled.
        if self.tool_name == WATER_QUALITY_HISTORY:
            result.update(history_query_completed=self.history_query_completed,
                history_range={"start": self.history_range_start, "end": self.history_range_end},
                history_window_count=self.history_window_count,
                history_reliable_windows=dict(self.history_reliable_windows),
                has_historical_observations=self.has_historical_observations)
        return result


_WATER_FIELDS = ("temperature_c", "ph", "dissolved_oxygen_mg_l")
_COMPONENT_FIELDS = ("temperature", "ph", "dissolved_oxygen")


def _observation(payload):
    """Reuse the canonical contract, without reading a Store or copying rules."""
    water = payload.get("water_quality")
    if not isinstance(water, dict):
        return None
    try:
        reading = WaterQualityReading(
            *(water[key] for key in _WATER_FIELDS),
            observed_at=parse_time(water["observed_at"]),
            retrieved_at=parse_time(water["retrieved_at"]), source=water["source"],
            quality=Quality(water["quality"]), freshness=Freshness(water["freshness"]))
        evaluated = parse_time(payload["evaluated_at"])
        if evaluated < reading.retrieved_at:
            return None
        # bool is not a measurement, even though Python treats it as a number.
        if any(value is not None and type(value) not in (int, float)
               for value in (getattr(reading, key) for key in _WATER_FIELDS)):
            return None
        return {"quality": reading.quality, "freshness": reading.freshness,
                "observed_at": reading.observed_at.isoformat(),
                "evaluated_at": evaluated.isoformat(),
                "available_fields": tuple(key for key in _WATER_FIELDS if getattr(reading, key) is not None)}
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return None


def _score_available(payload, observation):
    if observation is None or observation["quality"] == Quality.INVALID:
        return False
    status = payload.get("status")
    if ((status == "OK" and observation["quality"] != Quality.VALID)
            or (status == "PARTIAL" and observation["quality"] != Quality.PARTIAL)):
        return False

    def score_number(value):
        try:
            return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100
        except OverflowError:
            return False

    components = payload.get("components")
    expected = {component for component, key in zip(_COMPONENT_FIELDS, _WATER_FIELDS)
                if key in observation["available_fields"]}
    return (status in ("OK", "PARTIAL") and score_number(payload.get("score"))
            and payload.get("quality") == observation["quality"].value
            and payload.get("freshness") == observation["freshness"].value
            and payload.get("grade") in ("GOOD", "ACCEPTABLE", "WARNING", "CRITICAL")
            and isinstance(components, dict) and bool(expected) and set(components) == expected
            and all(isinstance(item, dict) and score_number(item.get("score"))
                    for item in components.values()))


def _empty_score(payload):
    """A valid negative evaluation has no fabricated score or components."""
    return all(key in payload and payload[key] == value for key, value in (
        ("score", None), ("grade", None), ("components", {})))


def _receipt_from_step(run: ToolConversationResult, step: ToolExecutionStep) -> TurnSourceReceipt:
    """Only consume correlated results from the existing coordinator/executor.

    A later model failure/cancellation does not erase a completed local read;
    it still cannot commit a successful Assistant turn. Unknown/malformed results
    fail closed and never grant sources. There is no deserialization from Web.
    """
    if not isinstance(run, ToolConversationResult):
        raise TypeError("receipt requires backend execution")
    tool = step.result
    model = next((item for item in run.steps if isinstance(item, ModelExecutionStep)
                  and item.request_index == step.model_request_index and item.seq < step.seq), None)
    if (tool is None or model is None or model.result.outcome != "tool_calls"
            or step.tool_name not in (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE, WATER_QUALITY_HISTORY)
            or tool.tool_name != step.tool_name or tool.tool_call_id != step.tool_call_id):
        return TurnSourceReceipt()
    empty = TurnSourceReceipt(tool_name=step.tool_name, tool_status=tool.status)
    if tool.status == ToolStatus.ERROR:
        return empty
    try:
        payload = tool.payload
    except (ValueError, TypeError):
        return empty
    if not isinstance(payload, dict) or payload.get("status") != tool.status.value:
        return empty
    if step.tool_name == WATER_QUALITY_HISTORY:
        metadata = history_metadata(payload) if step.handler_started and model.request_started else None
        if metadata is None:
            return empty
        sources = frozenset({TurnSource.HISTORICAL_WATER_OBSERVATIONS}) if any(
            count for _, count in metadata["history_reliable_windows"]) else frozenset()
        return TurnSourceReceipt(sources=sources, tool_name=step.tool_name, tool_status=tool.status, **metadata)
    if step.tool_name == SEARCH_FISHERY_KNOWLEDGE:
        items, count = payload.get("evidence"), payload.get("result_count")
        if not isinstance(items, list) or type(count) is not int or count != len(items) or not 0 <= count <= 3:
            return empty
        if tool.status == ToolStatus.NO_MATCH and count == 0:
            return TurnSourceReceipt(tool_name=step.tool_name, tool_status=tool.status,
                                     project_search_completed=True)
        if (tool.status == ToolStatus.OK and count > 0
                and all(isinstance(item, dict) and all(isinstance(item.get(key), str) and item[key].strip()
                        for key in ("id", "category", "source", "text")) for item in items)):
            return TurnSourceReceipt(frozenset({TurnSource.RETRIEVED_PROJECT_EVIDENCE}),
                step.tool_name, tool.status, project_search_completed=True, evidence_count=count)
        return empty
    if tool.status == ToolStatus.NO_DATA:
        if "water_quality" not in payload or payload["water_quality"] is not None:
            return empty
        if step.tool_name == CURRENT_WATER_QUALITY:
            valid = "findings" in payload and payload["findings"] == []
        else:
            valid = _empty_score(payload) and all(
                key in payload and payload[key] is None for key in ("quality", "freshness", "evaluated_at"))
        if not valid:
            return empty
        return TurnSourceReceipt(tool_name=step.tool_name, tool_status=tool.status,
            observation_query_completed=True,
            score_evaluation_completed=step.tool_name == WATER_QUALITY_SCORE)
    allowed_statuses = (ToolStatus.OK,) if step.tool_name == CURRENT_WATER_QUALITY else (
        ToolStatus.OK, ToolStatus.PARTIAL, ToolStatus.NOT_SCORABLE)
    if tool.status not in allowed_statuses:
        return empty
    observation = _observation(payload)
    if observation is None:
        return empty
    sources = {TurnSource.CURRENT_TOOL_OBSERVATION}
    evaluation_completed = False
    if step.tool_name == WATER_QUALITY_SCORE:
        if _score_available(payload, observation):
            sources.add(TurnSource.CURRENT_TOOL_SCORE)
            evaluation_completed = True
        elif tool.status == ToolStatus.NOT_SCORABLE:
            evaluation_completed = (_empty_score(payload) and observation["quality"] == Quality.INVALID
                and payload.get("quality") == observation["quality"].value
                and payload.get("freshness") == observation["freshness"].value)
    return TurnSourceReceipt(frozenset(sources), step.tool_name, tool.status, **observation,
        observation_query_completed=True, score_evaluation_completed=evaluation_completed)


@dataclass(frozen=True)
class TurnSourceLedgerEntry:
    execution_seq: int
    model_request_index: int
    tool_round: int
    receipt: TurnSourceReceipt

    def __post_init__(self):
        if (any(type(value) is not int or value < 1 for value in (
                self.execution_seq, self.model_request_index, self.tool_round))
                or not isinstance(self.receipt, TurnSourceReceipt)):
            raise ValueError("invalid source ledger entry")


@dataclass(frozen=True)
class TurnSourceLedger:
    """Per-execution proofs, never a merged current reading or Web input."""
    entries: tuple[TurnSourceLedgerEntry, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "entries", tuple(self.entries))
        if (any(not isinstance(item, TurnSourceLedgerEntry) for item in self.entries)
                or any(left.execution_seq >= right.execution_seq
                       for left, right in zip(self.entries, self.entries[1:]))):
            raise ValueError("invalid source ledger order")

    @property
    def single_receipt(self) -> TurnSourceReceipt:
        """Fail closed rather than silently choosing a last receipt in future modes."""
        if len(self.entries) > 1:
            raise ValueError("single receipt requires single tool execution")
        return self.entries[0].receipt if self.entries else TurnSourceReceipt()

    def to_dict(self) -> dict:
        return {"entries": [{"execution_seq": item.execution_seq,
            "model_request_index": item.model_request_index, "tool_round": item.tool_round,
            "receipt": item.receipt.to_dict()} for item in self.entries]}


def ledger_from_execution(run: ToolConversationResult) -> TurnSourceLedger:
    """Only returned backend results earn entries; never inspect messages or history."""
    if not isinstance(run, ToolConversationResult):
        raise TypeError("ledger requires backend execution")
    return TurnSourceLedger(tuple(TurnSourceLedgerEntry(step.seq, step.model_request_index,
        step.tool_round, _receipt_from_step(run, step)) for step in run.steps
        if isinstance(step, ToolExecutionStep) and step.result is not None))


def receipt_from_execution(run: ToolConversationResult) -> TurnSourceReceipt:
    """Read-only single-execution compatibility projection from the ledger."""
    return ledger_from_execution(run).single_receipt


def requirement_satisfied(requirement: SourceRequirement, receipt: TurnSourceReceipt) -> bool:
    """Completed operation, independent of payload availability or model text."""
    if not isinstance(requirement, SourceRequirement) or not isinstance(receipt, TurnSourceReceipt):
        raise TypeError("typed requirement and receipt required")
    if requirement == SourceRequirement.AUTO:
        return True
    if requirement == SourceRequirement.CURRENT_OBSERVATION_QUERY:
        return receipt.observation_query_completed
    if requirement == SourceRequirement.CURRENT_SCORE_EVALUATION:
        return receipt.score_evaluation_completed
    if requirement == SourceRequirement.PROJECT_KNOWLEDGE_SEARCH:
        return receipt.project_search_completed
    return receipt.history_query_completed


def requirement_satisfied_by_ledger(requirement: SourceRequirement, ledger: TurnSourceLedger) -> bool:
    """A matching completed operation in this turn; no payload/time merging."""
    if not isinstance(requirement, SourceRequirement) or not isinstance(ledger, TurnSourceLedger):
        raise TypeError("typed requirement and ledger required")
    return requirement == SourceRequirement.AUTO or any(
        requirement_satisfied(requirement, item.receipt) for item in ledger.entries)
