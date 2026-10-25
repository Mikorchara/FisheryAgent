"""Explicit business Tool assembly; known Policy names never create handlers."""
from functools import partial
from apps.ai_backend.tools import ToolRegistry, ToolDefinition
from . import current_water_quality, fishery_knowledge, water_quality_history


# Legal stored selection only. No score Definition or Handler is assembled here.
WATER_QUALITY_SCORE = "score_current_water_quality"
KNOWN_TOOL_NAMES = (current_water_quality.CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE,
                    fishery_knowledge.SEARCH_FISHERY_KNOWLEDGE)
# The shared user Policy file keeps its original names. Candidates use an
# isolated Policy; product History assembly requires its own approved trial.
FORMAL_TOOL_NAMES = (current_water_quality.CURRENT_WATER_QUALITY, fishery_knowledge.SEARCH_FISHERY_KNOWLEDGE)
HISTORY_CANDIDATE_TOOL_NAMES = (*FORMAL_TOOL_NAMES, water_quality_history.WATER_QUALITY_HISTORY)


def bind_tools(monitoring, device_id, knowledge, *, formal=None, include_history=False):
    if type(include_history) is not bool:
        raise ValueError("INVALID_BUSINESS_TOOL_ASSEMBLY")
    if formal is not None and (water_quality_history.WATER_QUALITY_HISTORY in
            tuple(d.name for d in formal.model_definitions())) != include_history:
        raise ValueError("INVALID_BUSINESS_TOOL_ASSEMBLY")
    # One formal definition owner; only the frozen device's water Handler changes.
    water_definition = (formal.lookup(current_water_quality.WATER_DEFINITION.name).model_definition
        if formal else current_water_quality.WATER_DEFINITION)
    entries = [ToolDefinition(water_definition,
        partial(current_water_quality.water_payload, monitoring, device_id))]
    if knowledge is not None:
        entries.append(formal.lookup(fishery_knowledge.KNOWLEDGE_DEFINITION.name) if formal else ToolDefinition(
            fishery_knowledge.KNOWLEDGE_DEFINITION,
            partial(fishery_knowledge.search_fishery_knowledge, service=knowledge),
            validate_arguments=fishery_knowledge.validate_arguments))
    if include_history:
        definition = (formal.lookup(water_quality_history.WATER_QUALITY_HISTORY).model_definition
                      if formal else water_quality_history.HISTORY_DEFINITION)
        entries.append(ToolDefinition(definition,
            partial(water_quality_history.history_payload, monitoring=monitoring, device_id=device_id),
            validate_arguments=water_quality_history.validate_arguments))
    return ToolRegistry(entries)
