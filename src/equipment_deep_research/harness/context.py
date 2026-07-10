from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.store import DomainStore


@dataclass(frozen=True)
class ContextPack:
    agent_id: str
    sections: dict[str, Any]


class ContextPackBuilder:
    def build_for_baseline_agent(
        self,
        *,
        agent: AgentDef,
        topic: str,
        research_route: str,
        store: DomainStore,
        recall_request: dict[str, Any] | None = None,
    ) -> ContextPack:
        del store
        sections = {
            "task": {"topic": topic, "research_route": research_route},
            "source_policy": {
                "public_sources_only": True,
                "white_list_required_for_formal_evidence": True,
            },
            "own_checkpoint": "",
            "recall_request": recall_request or {},
        }
        allowed = set(agent.context_policy.get("visible_sections", []))
        if allowed:
            sections = {key: value for key, value in sections.items() if key in allowed}
        return ContextPack(agent_id=agent.agent_id, sections=sections)

    def build_for_winning_mechanism(
        self,
        *,
        topic: str,
        research_route: str,
        store: DomainStore,
        coverage: dict[str, Any],
    ) -> ContextPack:
        return ContextPack(
            agent_id="winning_mechanism",
            sections={
                "task": {"topic": topic, "research_route": research_route},
                "baseline_summaries": [
                    {
                        "agent_id": packet.agent_id,
                        "capability_tags": packet.capability_tags,
                        "handoff_summary": packet.handoff_summary,
                        "confidence": packet.confidence,
                        "open_questions": packet.open_questions,
                    }
                    for packet in store.baseline_packets.values()
                ],
                "evidence_index": store.evidence_index(),
                "coverage": coverage,
                "checkpoints": [
                    packet.checkpoint for packet in store.baseline_packets.values()
                ],
            },
        )

