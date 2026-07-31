"""Generic bounded Deep Research loop shared by every business route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from equipment_deep_research.orchestration.query_planning import QueryPlanner, ResearchQuery


@dataclass(frozen=True)
class RoundEvidenceResult:
    evidence_ids: list[str]
    open_questions: list[str]
    conflicts: list[str]
    new_high_quality_count: int


@dataclass(frozen=True)
class ResearchRoundSummary:
    round_index: int
    queries: list[ResearchQuery]
    evidence_ids: list[str]
    open_questions: list[str]
    stop_reason: str | None = None


@dataclass(frozen=True)
class ResearchLoopResult:
    summaries: list[ResearchRoundSummary]
    stop_reason: str

    @property
    def round_count(self) -> int:
        return len(self.summaries)


class ResearchRoundExecutor(Protocol):
    async def execute_round(self, queries: list[ResearchQuery], round_index: int) -> RoundEvidenceResult: ...


class ResearchLoop:
    def __init__(self, *, max_rounds: int = 5, planner: QueryPlanner | None = None) -> None:
        self.max_rounds = max_rounds
        self.planner = planner or QueryPlanner()

    async def run(self, *, route: str, executor: ResearchRoundExecutor, initial_questions: list[str]) -> ResearchLoopResult:
        history: list[str] = []
        open_questions = list(initial_questions)
        conflicts: list[str] = []
        zero_gain = 0
        summaries: list[ResearchRoundSummary] = []
        for round_index in range(1, self.max_rounds + 1):
            queries = self.planner.plan_round(route=route, round_index=round_index, open_questions=open_questions, conflicts=conflicts, prior_queries=history)
            if not queries:
                # The same wording is exhausted; request an explicitly newer
                # evidence slice rather than repeating the prior search.
                queries = [ResearchQuery(f"{route} evidence update round {round_index}", "freshness_refresh", round_index)]
            history.extend(item.query for item in queries)
            result = await executor.execute_round(queries, round_index)
            zero_gain = zero_gain + 1 if result.new_high_quality_count == 0 else 0
            open_questions, conflicts = result.open_questions, result.conflicts
            reason = None
            if not open_questions and result.new_high_quality_count > 0:
                reason = "coverage_and_quality_met"
            elif zero_gain >= 2:
                reason = "low_marginal_gain"
            elif round_index == self.max_rounds:
                reason = "max_rounds_reached"
            summaries.append(ResearchRoundSummary(round_index, queries, result.evidence_ids, open_questions, reason))
            if reason:
                return ResearchLoopResult(summaries, reason)
        return ResearchLoopResult(summaries, "max_rounds_reached")
