"""Immutable per-turn authorization; application owns stored policy/defaults."""
from dataclasses import dataclass

class ToolPolicyError(ValueError):
    def __init__(self, code="INVALID_TOOL_POLICY"):
        self.code = code
        super().__init__(code)  # Never echo config content or file paths.


@dataclass(frozen=True)
class ToolPolicy:
    mode: str
    llm_tool_calling: bool
    exposed_tools: tuple[str, ...]

    def __post_init__(self):
        if (self.mode not in ("analysis", "assistant") or type(self.llm_tool_calling) is not bool
                or not isinstance(self.exposed_tools, (tuple, list))
                or any(not isinstance(name, str) or not name for name in self.exposed_tools)
                or len(set(self.exposed_tools)) != len(self.exposed_tools)
                or (not self.llm_tool_calling and self.exposed_tools)):
            raise ToolPolicyError()
        object.__setattr__(self, "exposed_tools", tuple(self.exposed_tools))

    def validate_registry(self, registry):
        from .contracts import ToolError
        for name in self.exposed_tools:
            try:
                registry.lookup(name)
            except ToolError:
                raise ToolPolicyError("UNKNOWN_POLICY_TOOL") from None

    def allows(self, name: str) -> bool:
        return self.llm_tool_calling and name in self.exposed_tools

    def model_definitions(self, registry):
        self.validate_registry(registry)
        # Definitions remain Registry-owned; no second JSON Schema or handler map.
        return tuple(definition for definition in registry.model_definitions()
                     if self.allows(definition.name) and callable(registry.lookup(definition.name).handler))
