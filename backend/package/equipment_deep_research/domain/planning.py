from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from equipment_deep_research.domain.models import now_iso


@dataclass(frozen=True)
class ResearchPlanNode:
    node_id: str
    node_type: str
    depends_on: list[str]
    status: str
    target_agent_id: str
    capability_tags: list[str]
    schema_version: str = "1.0"
    created_at: str = field(default_factory=now_iso)

    def validate(self) -> None:
        if not self.node_id.strip() or not self.node_type.strip() or not self.status.strip():
            raise ValueError("plan node id, type, and status are required")
        if self.node_id in self.depends_on:
            raise ValueError("plan node cannot depend on itself")
        if not self.target_agent_id and not self.capability_tags:
            raise ValueError("plan node requires target agent or capability target")


@dataclass(frozen=True)
class ResearchPlanGraph:
    nodes: list[ResearchPlanNode]
    plan_id: str = field(default_factory=lambda: f"plan-{uuid4()}")
    schema_version: str = "1.0"
    created_at: str = field(default_factory=now_iso)

    def ready_nodes(self) -> list[ResearchPlanNode]:
        status_by_id = {node.node_id: node.status for node in self.nodes}
        return [
            node
            for node in self.nodes
            if node.status == "pending"
            and all(status_by_id.get(dependency) == "completed" for dependency in node.depends_on)
        ]
