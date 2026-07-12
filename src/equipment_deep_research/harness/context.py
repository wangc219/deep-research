"""Projection-only context construction for isolated subagents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.domain.models import to_plain
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.compaction import ContextCompactor


@dataclass(frozen=True)
class ContextPolicy:
    visible_sections: tuple[str, ...]
    max_items_per_section: int = 12
    token_budget: int = 5000
    hide_raw_sessions: bool = True

    @classmethod
    def from_agent(cls, agent: AgentDef) -> "ContextPolicy":
        raw = agent.context_policy
        return cls(tuple(raw.get("visible_sections", ())), int(raw.get("max_items_per_section", 12)), int(raw.get("token_budget", 5000)), bool(raw.get("hide_other_agent_raw_sessions", True)))


@dataclass(frozen=True)
class ContextPack:
    agent_id: str
    sections: dict[str, Any]

    @property
    def context_hash(self) -> str:
        content = json.dumps(self.sections, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


class ContextProjector:
    def __init__(self, *, compactor: ContextCompactor | None = None) -> None:
        self.compactor = compactor or ContextCompactor()

    def project(self, task: TaskEnvelope, agent: AgentDef, store: DomainStore) -> ContextPack:
        policy = ContextPolicy.from_agent(agent)
        sections: dict[str, Any] = {"task": {"objective": task.objective, "research_questions": task.research_questions, "return_node": task.return_node}}
        if "EvidenceCard" in agent.object_read_scopes:
            sections["evidence_index"] = store.evidence_index()[:policy.max_items_per_section]
        if "BaselineFindingPacket" in agent.object_read_scopes:
            sections["baseline_packets"] = [
                {"agent_id": packet.agent_id, "capability_tags": packet.capability_tags, "handoff_summary": packet.handoff_summary, "confidence": packet.confidence, "open_questions": packet.open_questions, "evidence_ids": packet.evidence_ids}
                for packet in list(store.baseline_packets.values())[:policy.max_items_per_section]
            ]
        if "WinningMechanismStageOutput" in agent.object_read_scopes:
            sections["stage_outputs"] = [to_plain(item) for item in list(store.stage_outputs.values())[:policy.max_items_per_section]]
        if "CapabilityImageItem" in agent.object_read_scopes:
            sections["capability_images"] = [to_plain(item) for item in list(store.capability_images.values())[:policy.max_items_per_section]]
        visible = set(policy.visible_sections)
        sections = {key: value for key, value in sections.items() if key == "task" or key in visible}
        pack = ContextPack(agent.agent_id, sections)
        return self.compactor.compact(pack, token_budget=policy.token_budget)[0]


class ContextPackBuilder:
    """Compatibility facade used by the current scheduler."""
    def __init__(self) -> None:
        self.projector = ContextProjector()

    def build_for_baseline_agent(self, *, agent: AgentDef, topic: str, research_route: str, store: DomainStore, recall_request: dict[str, Any] | None = None) -> ContextPack:
        sections = {"task": {"topic": topic, "research_route": research_route}, "evidence_policy": {"public_sources_only": True, "quality_threshold_required_for_formal_evidence": True}, "own_checkpoint": "", "recall_request": recall_request or {}}
        allowed = set(agent.context_policy.get("visible_sections", ()))
        return ContextPack(agent.agent_id, {key: value for key, value in sections.items() if key in allowed})

    def build_for_winning_mechanism(self, *, topic: str, research_route: str, store: DomainStore, coverage: dict[str, Any]) -> ContextPack:
        return ContextPack("winning_mechanism", {"task": {"topic": topic, "research_route": research_route}, "baseline_summaries": [{"agent_id": p.agent_id, "capability_tags": p.capability_tags, "handoff_summary": p.handoff_summary, "confidence": p.confidence, "open_questions": p.open_questions} for p in store.baseline_packets.values()], "evidence_index": store.evidence_index(), "coverage": coverage, "checkpoints": [p.checkpoint for p in store.baseline_packets.values()]})
