from __future__ import annotations

from dataclasses import dataclass

from equipment_deep_research.agents.registry import AgentDef


KNOWN_TOOLS = {
    "search_sources",
    "fetch_page",
    "create_evidence_card",
    "write_stage_output",
    "create_recall_request",
    "create_capability_image",
    "write_audit",
    "write_report",
}


@dataclass(frozen=True)
class ToolPermissionRegistry:
    known_tools: set[str]

    @classmethod
    def default(cls) -> "ToolPermissionRegistry":
        return cls(known_tools=set(KNOWN_TOOLS))

    def validate_agent_tools(self, agent: AgentDef) -> None:
        unknown = sorted(set(agent.tools) - self.known_tools)
        if unknown:
            raise ValueError(f"agent {agent.agent_id} declares unknown tools: {unknown}")

    def enforce_active_tool(self, agent: AgentDef, tool_name: str) -> None:
        if tool_name not in self.known_tools:
            raise ValueError(f"unknown tool: {tool_name}")
        if tool_name not in agent.tools:
            raise PermissionError(f"agent {agent.agent_id} cannot use tool {tool_name}")

