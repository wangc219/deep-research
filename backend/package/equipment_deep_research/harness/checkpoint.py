"""Append-only working-checkpoint merge rules."""

from __future__ import annotations

from dataclasses import replace

from equipment_deep_research.domain.models import WorkingCheckpoint


_TRANSITIONS = {
    "pending": {"active"},
    "active": {"completed", "limited", "failed"},
    "completed": set(), "limited": set(), "failed": set(),
}


class CheckpointManager:
    def update(self, current: WorkingCheckpoint, **changes: object) -> WorkingCheckpoint:
        status = str(changes.pop("status", current.status))
        if status != current.status and status not in _TRANSITIONS.get(current.status, set()):
            raise ValueError(f"invalid checkpoint status transition: {current.status} -> {status}")
        return_node = str(changes.pop("return_node", current.return_node))
        return replace(
            current,
            status=status,
            return_node=return_node,
            completed_steps=_merge(current.completed_steps, changes.pop("completed_steps", ())),
            accepted_evidence_ids=_merge(current.accepted_evidence_ids, changes.pop("accepted_evidence_ids", ())),
            rejected_lead_ids=_merge(current.rejected_lead_ids, changes.pop("rejected_lead_ids", ())),
            open_questions=_merge(current.open_questions, changes.pop("open_questions", ())),
            conflicts=_merge(current.conflicts, changes.pop("conflicts", ())),
            next_actions=_merge(current.next_actions, changes.pop("next_actions", ())),
        )

    def project_for_agent(self, checkpoint: WorkingCheckpoint, agent_id: str) -> dict[str, object]:
        if checkpoint.agent_id != agent_id:
            return {}
        return checkpoint.to_dict()


def _merge(existing: list[str], appended: object) -> list[str]:
    result = list(existing)
    for item in appended if isinstance(appended, (list, tuple)) else ():
        value = str(item)
        if value and value not in result:
            result.append(value)
    return result
