from __future__ import annotations

from dataclasses import dataclass, field

from equipment_deep_research.domain.models import now_iso


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    run_id: str
    round_index: int
    parent_task_id: str | None
    target_agent_id: str
    target_capability_tags: list[str]
    objective: str
    research_questions: list[str]
    context_refs: list[str]
    evidence_refs: list[str]
    allowed_tools: list[str]
    object_read_scopes: list[str]
    object_write_scopes: list[str]
    budget: dict[str, int]
    return_contract: str
    return_node: str
    schema_version: str = "1.0"
    created_at: str = field(default_factory=now_iso)

    def validate(self) -> None:
        if not self.target_agent_id and not self.target_capability_tags:
            raise ValueError("task requires target agent or capability target")
        if not self.objective.strip() or not self.return_contract.strip():
            raise ValueError("task objective and return contract are required")


@dataclass(frozen=True)
class RecallEnvelope:
    recall_id: str
    source_layer: str
    target_agent_id: str | None
    target_capability_tag: str | None
    reason: str
    required_data: list[str]
    evidence_gaps: list[str]
    return_node: str
    urgency: str
    attempt: int
    status: str
    schema_version: str = "1.0"
    created_at: str = field(default_factory=now_iso)

    def target_key(self) -> str:
        return self.target_agent_id or self.target_capability_tag or "unroutable"
