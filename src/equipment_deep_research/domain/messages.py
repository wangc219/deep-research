from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from equipment_deep_research.domain.models import new_stable_id, now_iso
from equipment_deep_research.domain.proposals import freeze_plain, thaw_plain


FINALIZE_TASK_ID = "finalize:winning-report"


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


@dataclass(frozen=True)
class TurnSnapshot:
    message_refs: Sequence[str]
    context_hash: str
    active_tool_names: Sequence[str]
    model_name: str
    model_options: Mapping[str, Any]
    budget_remaining: Mapping[str, Any]
    turn_index: int
    snapshot_id: str = field(default_factory=lambda: new_stable_id("turn-snapshot"))
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.turn_index < 1:
            raise ValueError("turn_index must be positive")
        object.__setattr__(self, "message_refs", tuple(self.message_refs))
        object.__setattr__(self, "active_tool_names", tuple(self.active_tool_names))
        object.__setattr__(
            self,
            "model_options",
            cast(Mapping[str, Any], freeze_plain(self.model_options)),
        )
        object.__setattr__(
            self,
            "budget_remaining",
            cast(Mapping[str, Any], freeze_plain(self.budget_remaining)),
        )

    def to_plain(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "turn_index": self.turn_index,
            "message_refs": list(self.message_refs),
            "context_hash": self.context_hash,
            "active_tool_names": list(self.active_tool_names),
            "model_name": self.model_name,
            "model_options": thaw_plain(self.model_options),
            "budget_remaining": thaw_plain(self.budget_remaining),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AgentExecutionResult:
    execution_id: str
    task_id: str
    agent_id: str
    status: str
    output_refs: Sequence[str] = field(default_factory=tuple)
    evidence_ids: Sequence[str] = field(default_factory=tuple)
    checkpoint_id: str | None = None
    error: str | None = None
    snapshots: Sequence[TurnSnapshot] = field(default_factory=tuple)
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        snapshots = tuple(self.snapshots)
        if not all(isinstance(snapshot, TurnSnapshot) for snapshot in snapshots):
            raise TypeError("snapshots must contain only TurnSnapshot values")
        object.__setattr__(self, "output_refs", tuple(self.output_refs))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "snapshots", snapshots)

    def to_plain(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "output_refs": list(self.output_refs),
            "evidence_ids": list(self.evidence_ids),
            "checkpoint_id": self.checkpoint_id,
            "error": self.error,
            "snapshots": [snapshot.to_plain() for snapshot in self.snapshots],
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class RunCheckpoint:
    run_id: str
    checkpoint_id: str
    completed_task_ids: list[str]
    pending_task_ids: list[str]
    round_index: int
    budget_remaining: dict[str, int]
    status: str = "running"
    task_statuses: dict[str, str] = field(default_factory=dict)
    topic: str = ""
    research_route: str = ""
    resolved_route: str = ""
    selected_agent_ids: list[str] = field(default_factory=list)
    source_materials: list[dict[str, Any]] = field(default_factory=list)
    worker_reports: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "fake"
    config_fingerprint: str = ""
    resume_count: int = 0
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"

    def validate(self) -> None:
        if not self.run_id or not self.checkpoint_id:
            raise ValueError("run checkpoint requires run_id and checkpoint_id")
        if self.status not in {"running", "completed"}:
            raise ValueError(f"invalid run checkpoint status: {self.status}")
        if self.round_index < 0 or self.resume_count < 0:
            raise ValueError("run checkpoint counters must be non-negative")
        completed = set(self.completed_task_ids)
        pending = set(self.pending_task_ids)
        if completed & pending:
            raise ValueError("completed and pending task ids must not overlap")
        if any(
            status not in {"pending", "running", "completed"}
            for status in self.task_statuses.values()
        ):
            raise ValueError("invalid task status in run checkpoint")
        if len(self.selected_agent_ids) != len(set(self.selected_agent_ids)):
            raise ValueError("selected agent ids must be unique")
        expected_task_ids = {
            *(f"baseline:{agent_id}" for agent_id in self.selected_agent_ids),
            FINALIZE_TASK_ID,
        }
        if set(self.task_statuses) != expected_task_ids:
            raise ValueError("task statuses do not match selected agents")
        status_completed = {
            task_id
            for task_id, status in self.task_statuses.items()
            if status == "completed"
        }
        status_pending = {
            task_id
            for task_id, status in self.task_statuses.items()
            if status == "pending"
        }
        if completed != status_completed or pending != status_pending:
            raise ValueError("task status lists are inconsistent")
        if self.status == "completed" and (
            self.pending_task_ids
            or any(status != "completed" for status in self.task_statuses.values())
        ):
            raise ValueError("completed run checkpoint cannot contain unfinished tasks")

    @classmethod
    def from_plain(cls, payload: Mapping[str, Any]) -> "RunCheckpoint":
        checkpoint = cls(
            run_id=str(payload["run_id"]),
            checkpoint_id=str(payload["checkpoint_id"]),
            completed_task_ids=[str(item) for item in payload["completed_task_ids"]],
            pending_task_ids=[str(item) for item in payload["pending_task_ids"]],
            round_index=int(payload["round_index"]),
            budget_remaining={
                str(key): int(value)
                for key, value in cast(Mapping[str, Any], payload["budget_remaining"]).items()
            },
            status=str(payload.get("status", "running")),
            task_statuses={
                str(key): str(value)
                for key, value in cast(
                    Mapping[str, Any], payload.get("task_statuses", {})
                ).items()
            },
            topic=str(payload.get("topic", "")),
            research_route=str(payload.get("research_route", "")),
            resolved_route=str(payload.get("resolved_route", "")),
            selected_agent_ids=[
                str(item) for item in payload.get("selected_agent_ids", [])
            ],
            source_materials=[
                dict(cast(Mapping[str, Any], item))
                for item in payload.get("source_materials", [])
            ],
            worker_reports=[
                dict(cast(Mapping[str, Any], item))
                for item in payload.get("worker_reports", [])
            ],
            mode=str(payload.get("mode", "fake")),
            config_fingerprint=str(payload.get("config_fingerprint", "")),
            resume_count=int(payload.get("resume_count", 0)),
            created_at=str(payload["created_at"]),
            schema_version=str(payload["schema_version"]),
        )
        checkpoint.validate()
        return checkpoint
