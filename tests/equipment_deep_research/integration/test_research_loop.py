from __future__ import annotations

import asyncio

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
