"""Bounded routing state machine for targeted post-gate recall tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.models import AgentRecommendation, RecallRequest


@dataclass(frozen=True)
class RecallRoute:
    recall: RecallRequest
    status: str
    target_agent_id: str | None
    recommendation: AgentRecommendation | None = None


@dataclass(frozen=True)
class RecallExecutionResult:
    recall: RecallRequest
    target_agent_id: str | None
    return_node: str
    status: str
    output_refs: list[str]


class RecallCoordinator:
    def __init__(self, *, max_per_target: int = 3, max_rounds: int = 5) -> None:
        self.max_per_target, self.max_rounds = max_per_target, max_rounds
        self._attempts: dict[str, int] = {}

    def route(self, recall: RecallRequest, registry: AgentRegistry, selected_agent_ids: list[str], *, round_index: int) -> RecallRoute:
        target = recall.target_agent_id
        if not target and recall.target_capability_tag:
            selected = [registry.get(item) for item in selected_agent_ids]
            candidates = registry.agents_for_capability(recall.target_capability_tag, selected)
            target = candidates[0].agent_id if candidates else None
        key = target or recall.target_key()
        attempts = self._attempts.get(key, 0)
        if round_index >= self.max_rounds or attempts >= self.max_per_target:
            return RecallRoute(replace(recall, status="limited"), "limited", target)
        if not target:
            tag = recall.target_capability_tag or "unknown"
            recommendation = AgentRecommendation(f"recommend-{recall.recall_id}", tag, "当前选择的 agent 无法覆盖再调缺口。", f"建议启用具备 {tag} 能力标签的 agent。")
            return RecallRoute(replace(recall, status="limited"), "limited", None, recommendation)
        self._attempts[key] = attempts + 1
        return RecallRoute(replace(recall, target_agent_id=target, status="routed"), "routed", target)

    def complete(self, routed: RecallRoute) -> RecallRoute:
        return replace(routed, recall=replace(routed.recall, status="completed"), status="completed")

    async def execute_pending(
        self,
        routed: RecallRoute,
        execute: Callable[[str, RecallRequest], Awaitable[list[str]]],
    ) -> RecallExecutionResult:
        """Execute only a routed target and return a structured resume token."""
        if routed.status != "routed" or not routed.target_agent_id:
            return RecallExecutionResult(
                routed.recall,
                routed.target_agent_id,
                routed.recall.return_node,
                routed.status,
                [],
            )
        refs = await execute(routed.target_agent_id, routed.recall)
        completed = self.complete(routed)
        return RecallExecutionResult(
            completed.recall,
            completed.target_agent_id,
            completed.recall.return_node,
            "completed",
            list(refs),
        )
