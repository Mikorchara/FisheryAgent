"""Generic contracts and static execution; handlers are supplied by the application."""
from .contracts import ToolDefinition, ToolError, ToolErrorCode, ToolExecutionResult, ToolStatus
from .executor import ToolExecutor
from .registry import ToolRegistry
