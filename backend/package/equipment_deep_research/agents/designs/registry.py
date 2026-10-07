"""Lazy registry for one-module-per-agent design implementations."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from typing import Iterable

from equipment_deep_research.agents.designs.base import AgentDesign


DEFAULT_AGENT_IDS = (
    "orchestrator",
    "international_situation",
    "combat_scenario",
    "weapon_equipment",
    "operational_employment",
    "scenario_divergence",
    "case_research",
    "technology_radar",
    "opponent_monitoring",
    "system_confrontation",
    "cross_domain_fusion",
    "nontraditional_security",
    "winning_mechanism",
    "convergence_fusion",
    "winning_s1_opponent",
    "winning_s2_operations",
    "winning_s3_breakthrough",
    "winning_s4_capability",
    "winning_s5_gap",
    "winning_s6_image",
    "deep_divergence_v1",
    "winning_step_critic",
    "winning_round_critic",
    "winning_dynamic_specialist",
    "auditor",
    "reporter",
)


class AgentDesignRegistry:
    def __init__(self, designs: Iterable[AgentDesign] = ()) -> None:
        self._designs: dict[str, AgentDesign] = {}
        for design in designs:
            self.register(design)

    @classmethod
    def load_default(cls) -> "AgentDesignRegistry":
        registry = cls()
        for agent_id in DEFAULT_AGENT_IDS:
            module = import_module(
                f"equipment_deep_research.agents.designs.{agent_id}"
            )
            design = module.DESIGN
            try:
                guidance_module = import_module(
                    "equipment_deep_research.agents.designs.guidance."
                    f"{agent_id}"
                )
            except ModuleNotFoundError as exc:
                if exc.name != (
                    "equipment_deep_research.agents.designs.guidance."
                    f"{agent_id}"
                ):
                    raise
            else:
                design = replace(design, guidance=guidance_module.GUIDANCE)
            registry.register(design)
        return registry

    def register(self, design: AgentDesign) -> None:
        agent_id = str(design.agent_id).strip()
        if not agent_id:
            raise ValueError("agent design requires a non-empty agent_id")
        if agent_id in self._designs:
            raise ValueError(f"duplicate agent design: {agent_id}")
        self._designs[agent_id] = design

    def get(self, agent_id: str) -> AgentDesign:
        try:
            return self._designs[agent_id]
        except KeyError as exc:
            raise KeyError(f"missing agent design: {agent_id}") from exc

    def validate_agent_ids(
        self,
        agent_ids: Iterable[str],
        *,
        allow_custom: bool = True,
    ) -> None:
        expected = set(agent_ids)
        missing = sorted(expected - self._designs.keys())
        if allow_custom:
            missing = [item for item in missing if item in DEFAULT_AGENT_IDS]
        if missing:
            raise ValueError(f"missing agent designs: {missing}")

    def all_agent_ids(self) -> list[str]:
        return sorted(self._designs)
