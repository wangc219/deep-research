"""Generic bounded Deep Research loop shared by every business route."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from equipment_deep_research.orchestration.query_planning import QueryHistory, QueryPlanner, ResearchQuery


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


class QueryResearchExecutor(Protocol):
    async def execute_query(self, query: ResearchQuery, round_index: int) -> RoundEvidenceResult: ...


class ResearchLoop:
    def __init__(
        self,
        *,
        max_rounds: int = 5,
        max_queries_per_round: int = 6,
        query_concurrency: int = 4,
        planner: QueryPlanner | None = None,
    ) -> None:
        self.max_rounds = max(1, int(max_rounds))
        self.max_queries_per_round = max(1, min(32, int(max_queries_per_round)))
        self.query_concurrency = max(1, min(16, int(query_concurrency)))
        self.planner = planner or QueryPlanner()

    async def _execute_round(
        self,
        *,
        executor: ResearchRoundExecutor | QueryResearchExecutor,
        queries: list[ResearchQuery],
        round_index: int,
    ) -> RoundEvidenceResult:
        """Execute independent query tasks concurrently when the executor supports it.

        Existing executors can keep their batch method.  Search-backed
        executors may expose ``execute_query`` to avoid serially waiting for
        unrelated gaps; the loop then merges their typed results once, in a
        deterministic query order.
        """

        execute_query = getattr(executor, "execute_query", None)
        if not callable(execute_query):
            return await executor.execute_round(queries, round_index)
        semaphore = asyncio.Semaphore(self.query_concurrency)

        async def run(query: ResearchQuery) -> RoundEvidenceResult:
            async with semaphore:
                return await execute_query(query, round_index)

        tasks = [asyncio.create_task(run(query)) for query in queries]
        try:
            results = await asyncio.gather(*tasks)
        finally:
            # A failed query must not leave siblings consuming provider calls
            # or committing evidence after this research round has exited.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        evidence_ids: list[str] = []
        open_questions: list[str] = []
        conflicts: list[str] = []
        high_quality = 0
        for result in results:
            high_quality += max(0, int(result.new_high_quality_count))
            for target, values in (
                (evidence_ids, result.evidence_ids),
                (open_questions, result.open_questions),
                (conflicts, result.conflicts),
            ):
                for value in values:
                    text = str(value).strip()
                    if text and text not in target:
                        target.append(text)
        return RoundEvidenceResult(
            evidence_ids=evidence_ids,
            open_questions=open_questions,
            conflicts=conflicts,
            new_high_quality_count=high_quality,
        )

    async def run(self, *, route: str, executor: ResearchRoundExecutor | QueryResearchExecutor, initial_questions: list[str]) -> ResearchLoopResult:
        history: list[str] = []
        open_questions = list(initial_questions)
        conflicts: list[str] = []
        zero_gain = 0
        summaries: list[ResearchRoundSummary] = []
        for round_index in range(1, self.max_rounds + 1):
            try:
                queries = self.planner.plan_round(
                    route=route,
                    round_index=round_index,
                    open_questions=open_questions,
                    conflicts=conflicts,
                    prior_queries=history,
                    max_queries=self.max_queries_per_round,
                )
            except TypeError as exc:
                # Preserve the small historical planner protocol for callers
                # that inject a custom planner while still bounding its
                # output at the loop boundary.
                if "max_queries" not in str(exc):
                    raise
                queries = self.planner.plan_round(
                    route=route,
                    round_index=round_index,
                    open_questions=open_questions,
                    conflicts=conflicts,
                    prior_queries=history,
                )[: self.max_queries_per_round]
            if not queries:
                # The same wording is exhausted; request an explicitly newer
                # evidence slice rather than repeating the prior search.
                refresh_query = ResearchQuery(
                    f"{route} evidence update round {round_index}",
                    "freshness_refresh",
                    round_index,
                )
                queries = [refresh_query]
            history.extend(item.query for item in queries)
            attempted = QueryHistory(history)
            deferred_questions = [
                item for item in open_questions
                if item.strip() and not attempted.seen(item)
            ]
            deferred_conflicts = [
                item for item in conflicts
                if item.strip() and not attempted.seen(f"争议/反证：{item}")
            ]
            result = await self._execute_round(
                executor=executor,
                queries=queries,
                round_index=round_index,
            )
            zero_gain = zero_gain + 1 if result.new_high_quality_count == 0 else 0
            # A bounded batch cannot certify coverage for questions it never
            # received. Carry overflow forward even if this batch is complete.
            open_questions = list(dict.fromkeys([*deferred_questions, *result.open_questions]))
            conflicts = list(dict.fromkeys([*deferred_conflicts, *result.conflicts]))
            reason = None
            if not open_questions and not conflicts and result.new_high_quality_count > 0:
                reason = "coverage_and_quality_met"
            elif zero_gain >= 2:
                reason = "low_marginal_gain"
            elif round_index == self.max_rounds:
                reason = "max_rounds_reached"
            summaries.append(ResearchRoundSummary(round_index, queries, result.evidence_ids, open_questions, reason))
            if reason:
                return ResearchLoopResult(summaries, reason)
        return ResearchLoopResult(summaries, "max_rounds_reached")
