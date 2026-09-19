"""Backward-compatible import location for tool contracts.

New code should import from :mod:`equipment_deep_research.contracts.tools`.
The re-export keeps existing plugins and integrations source-compatible while
removing the provider/harness dependency on the concrete tools package.
"""

from equipment_deep_research.contracts.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolHandler,
    ToolResult,
)

__all__ = ["ToolCall", "ToolDefinition", "ToolExecutionContext", "ToolHandler", "ToolResult"]
