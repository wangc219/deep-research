from __future__ import annotations

import asyncio
import pytest

from equipment_deep_research.orchestration.research_loop import ResearchLoop, RoundEvidenceResult


class _Executor:
    def __init__(self, results: list[RoundEvidenceResult]) -> None:
        self.results = results

    async def execute_round(self, queries, round_index):
        assert queries and round_index > 0
        return self.results.pop(0)


def test_loop_runs_second_round_for_open_question() -> None:
    result = asyncio.run(ResearchLoop().run(route="traditional_gap", executor=_Executor([
        RoundEvidenceResult(["ev-1"], ["强干扰参数？"], [], 1),
        RoundEvidenceResult(["ev-2"], [], [], 1),
    ]), initial_questions=["当前能力缺口？"]))
    assert result.round_count == 2
    assert result.stop_reason == "coverage_and_quality_met"


def test_loop_stops_on_low_marginal_gain() -> None:
    result = asyncio.run(ResearchLoop().run(route="war_case_learning", executor=_Executor([
        RoundEvidenceResult([], ["q"], [], 0), RoundEvidenceResult([], ["q"], [], 0),
    ]), initial_questions=["q"]))
    assert result.stop_reason == "low_marginal_gain"


def test_loop_executes_independent_queries_concurrently() -> None:
    active = 0
    peak = 0

    class _QueryExecutor:
        async def execute_query(self, query, round_index):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return RoundEvidenceResult([query.query], [], [], 1)

        async def execute_round(self, queries, round_index):
            raise AssertionError("query-level execution should be selected")

    result = asyncio.run(
        ResearchLoop(query_concurrency=2, max_rounds=1).run(
            route="traditional_gap",
            executor=_QueryExecutor(),
            initial_questions=["问题一", "问题二", "问题三"],
        )
    )
    assert peak == 2
    assert result.summaries[0].evidence_ids == ["问题一", "问题二", "问题三"]


def test_query_only_executor_handles_single_query_and_unresolved_conflicts():
    class Executor:
        async def execute_query(self, query, round_index):
            return RoundEvidenceResult(
                ['ev'], [], ['source disagreement'] if round_index == 1 else [], 1,
            )

    result = asyncio.run(ResearchLoop().run(
        route='research', executor=Executor(), initial_questions=['initial question'],
    ))
    assert result.round_count == 2
    assert result.summaries[1].queries[0].purpose == 'counter_evidence'
    assert result.stop_reason == 'coverage_and_quality_met'


def test_failed_query_cancels_siblings_before_round_returns():
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class Executor:
            async def execute_query(self, query, round_index):
                if query.query == 'failure':
                    await started.wait()
                    raise RuntimeError('query failed')
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        with pytest.raises(RuntimeError, match='query failed'):
            await ResearchLoop().run(
                route='research', executor=Executor(), initial_questions=['failure', 'sibling'],
            )
        assert cancelled.is_set()

    asyncio.run(run())


def test_query_limit_keeps_unattempted_questions_for_later_rounds():
    calls = []

    class Executor:
        async def execute_query(self, query, round_index):
            calls.append(query.query)
            return RoundEvidenceResult([query.query], [], [], 1)

    result = asyncio.run(ResearchLoop(max_queries_per_round=2).run(
        route='research', executor=Executor(), initial_questions=['alpha', 'beta', 'gamma'],
    ))
    assert calls == ['alpha', 'beta', 'gamma']
    assert result.round_count == 2
    assert result.summaries[0].open_questions == ['gamma']
    assert result.stop_reason == 'coverage_and_quality_met'
