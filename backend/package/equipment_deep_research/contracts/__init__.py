"""Stable contracts shared by the domain adapters.

The contracts package is deliberately small and dependency-light.  Runtime
implementations may depend on these types, while the contracts themselves do
not depend on providers, orchestration, API or persistence implementations.
"""

from equipment_deep_research.contracts.catalog import (
    CONTRACT_CATALOG,
    OBJECT_SCOPE_CATALOG,
    TOOL_CATALOG,
    VISIBLE_SECTION_CATALOG,
)
from equipment_deep_research.contracts.agents import AgentCatalog, AgentSpec
from equipment_deep_research.contracts.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolHandler,
    ToolResult,
)
from equipment_deep_research.contracts.runtime import (
    BudgetRuntime,
    CardRuntime,
    ModelRuntime,
    SwarmRuntime,
)

__all__ = [
    "CONTRACT_CATALOG",
    "OBJECT_SCOPE_CATALOG",
    "TOOL_CATALOG",
    "VISIBLE_SECTION_CATALOG",
    "ToolCall",
    "ToolDefinition",
    "ToolExecutionContext",
    "ToolHandler",
    "ToolResult",
    "AgentCatalog",
    "AgentSpec",
    "BudgetRuntime",
    "CardRuntime",
    "ModelRuntime",
    "SwarmRuntime",
]
