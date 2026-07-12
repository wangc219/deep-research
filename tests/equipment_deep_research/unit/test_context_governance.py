from __future__ import annotations

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.domain.models import WorkingCheckpoint
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.checkpoint import CheckpointManager
from equipment_deep_research.harness.compaction import ContextCompactor, estimate_tokens
from equipment_deep_research.harness.context import ContextPack, ContextProjector


def _task() -> TaskEnvelope:
    return TaskEnvelope("task", "run", 1, None, "winning", [], "research", [], [], [], [], ["ResearchProblem", "BaselineFindingPacket"], [], {}, "stage", "L1")


def _agent() -> AgentDef:
    return AgentDef("winning", "Winning", "test", ["winning_mechanism"], [], {"visible_sections": ["baseline_packets"], "hide_other_agent_raw_sessions": True}, object_read_scopes=["ResearchProblem", "BaselineFindingPacket"])


def test_projector_only_exposes_structured_handoffs() -> None:
    store = DomainStore()
    # Empty storage still proves no raw-session section can enter the projection.
    pack = ContextProjector().project(_task(), _agent(), store)
    assert "raw_sessions" not in pack.sections
    assert set(pack.sections) == {"task", "baseline_packets"}


def test_checkpoint_merge_preserves_open_questions() -> None:
    checkpoint = WorkingCheckpoint("cp", "winning", 1, open_questions=["q1"])
    updated = CheckpointManager().update(checkpoint, status="active", open_questions=["q1", "q2"], next_actions=["search"])
    assert updated.open_questions == ["q1", "q2"]
    assert updated.status == "active"


def test_compaction_is_deterministic() -> None:
    pack = ContextPack("agent", {"task": {"id": "t"}, "findings": [{"evidence_ids": ["ev-1"], "open_questions": ["q1"]}] * 30})
    result_a, record_a = ContextCompactor().compact(pack, token_budget=120)
    result_b, record_b = ContextCompactor().compact(pack, token_budget=120)
    assert result_a.context_hash == result_b.context_hash
    assert record_a == record_b
    assert estimate_tokens(result_a) <= 120
    assert "ev-1" in str(result_a.sections)
