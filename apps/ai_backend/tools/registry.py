"""Explicit static bindings only; no discovery, defaults or business imports."""
from types import MappingProxyType
from .contracts import ToolDefinition, ToolError, ToolErrorCode
from ..model_gateway import ModelToolDefinition

class ToolRegistry:
    def __init__(self, definitions):
        entries = tuple(definitions)
        if (any(not isinstance(item, ToolDefinition)
                or not isinstance(item.model_definition, ModelToolDefinition)
                or not callable(item.handler) for item in entries)
                or len({item.model_definition.name for item in entries}) != len(entries)):
            raise ValueError("invalid static Tool bindings")
        self._entries = MappingProxyType({item.model_definition.name:item for item in entries})

    def registered_names(self):
        return tuple(self._entries)

    def lookup(self, name):
        if name not in self._entries:
            raise ToolError(ToolErrorCode.UNKNOWN_TOOL)
        return self._entries[name]

    def model_definitions(self):
        return tuple(item.model_definition for item in self._entries.values())
