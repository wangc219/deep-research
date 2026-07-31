"""Explainable decision rule for spawning focused subagents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubtaskCandidate:
    separable: bool
    context_isolation_gain: bool
    merge_contract: str
    budget_available: bool
    estimated_cost: int = 1


@dataclass(frozen=True)
class SubagentDecision:
    spawn: bool
    reasons: list[str]
    estimated_cost: int
    merge_node: str


class SubagentPolicy:
    def evaluate(self, candidate: SubtaskCandidate) -> SubagentDecision:
        reasons = []
        if not candidate.separable:
            reasons.append("任务不可独立拆分")
        if not candidate.context_isolation_gain:
            reasons.append("上下文隔离无收益")
        if not candidate.merge_contract:
            reasons.append("缺少可汇总的结构化回传契约")
        if not candidate.budget_available:
            reasons.append("预算不足")
        return SubagentDecision(not reasons, reasons or ["满足可拆分、隔离、可汇总和预算条件"], candidate.estimated_cost, candidate.merge_contract or "parent_context")
