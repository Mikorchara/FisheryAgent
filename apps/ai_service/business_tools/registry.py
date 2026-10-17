"""Explicit business Tool assembly; known Policy names never create handlers."""
from functools import partial
from apps.ai_backend.tools import ToolRegistry, ToolDefinition
from . import current_water_quality, fishery_knowledge


# Legal stored selection only. No score Definition or Handler is assembled here.
WATER_QUALITY_SCORE = "score_current_water_quality"
KNOWN_TOOL_NAMES = (current_water_quality.CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE,
                    fishery_knowledge.SEARCH_FISHERY_KNOWLEDGE)


def bind_tools(monitoring, device_id, knowledge, *, formal=None):
    # One formal definition owner; only the frozen device's water Handler changes.
    water_definition = (formal.lookup(current_water_quality.WATER_DEFINITION.name).model_definition
        if formal else current_water_quality.WATER_DEFINITION)
    knowledge_entry = (formal.lookup(fishery_knowledge.KNOWLEDGE_DEFINITION.name) if formal else ToolDefinition(
        fishery_knowledge.KNOWLEDGE_DEFINITION,
        partial(fishery_knowledge.search_fishery_knowledge, service=knowledge),
        validate_arguments=fishery_knowledge.validate_arguments))
    return ToolRegistry((ToolDefinition(water_definition,
        partial(current_water_quality.water_payload, monitoring, device_id)), knowledge_entry))
