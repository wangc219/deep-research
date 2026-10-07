from __future__ import annotations

from pathlib import Path

from equipment_deep_research.orchestration.query_planning import QueryHistory, QueryPlanner
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.blueprints import build_discovery_blueprint
from equipment_deep_research.orchestration.routes import RouteRegistry


ROOT = Path(__file__).parents[3]


def test_routes_cover_the_three_client_business_paths() -> None:
    routes = RouteRegistry.load(ROOT / "configs/equipment_deep_research/routes.yaml")
    chain = " ".join(routes.get("new_winning_mechanism").question_chain)
    assert all(term in chain for term in ["制胜机制", "作战运用打法", "体系组合"])
    assert {"equipment_baseline", "gap_matrix"} <= set(routes.get("traditional_gap").required_outputs)
    assert {"case_timeline", "new_tactics", "lessons", "future_directions"} <= set(routes.get("war_case_learning").required_outputs)


def test_round_two_queries_are_driven_by_evidence_gap_without_duplicates() -> None:
    queries = QueryPlanner().plan_round(route="traditional_gap", round_index=2, open_questions=["当前型号在强干扰条件下探测距离是多少？"], conflicts=[], prior_queries=["低空探测装备 参数"])
    assert any("强干扰" in query.query and "探测距离" in query.query for query in queries)
    assert all(query.query != "低空探测装备 参数" for query in queries)


def test_query_planner_prioritizes_conflicts_and_caps_near_duplicates() -> None:
    queries = QueryPlanner(max_queries_per_round=2).plan_round(
        route="traditional_gap",
        round_index=2,
        open_questions=[
            "当前型号在强干扰条件下探测距离是多少？",
            "当前型号在强干扰条件下的探测距离是多少？",
        ],
        conflicts=["公开来源对当前型号的航程存在冲突"],
        prior_queries=[],
    )

    assert queries[0].purpose == "counter_evidence"
    assert len(queries) == 2
    assert sum("探测距离" in item.query for item in queries) == 1


def test_auto_route_does_not_infer_case_learning_from_query_keywords() -> None:
    problem = ResearchProblem(
        topic="完整利用一个案例，从近年局部战争中挖掘我军装备发展需求"
    )

    assert problem.resolved_discovery_branch()["primary"] == "A"
    assert problem.resolved_route() == "new_winning_mechanism"

    blueprint = build_discovery_blueprint(
        problem,
        model_blueprint={"primary_branch": "C", "confidence": 0.91},
    )
    assert blueprint["primary_branch"] == "C"
    assert blueprint["runtime_route"] == "war_case_learning"


def test_query_history_preserves_search_operators_and_specific_questions():
    history = QueryHistory(['alpha -beta', 'Ｃ＋＋ performance'])
    assert history.should_run('alpha beta')
    assert not history.should_run('C++ performance')
    assert history.should_run('C performance')
    queries = QueryPlanner().plan_round(
        route='research', round_index=1, prior_queries=[], conflicts=[],
        open_questions=['storage latency', 'storage latency under heavy load'],
    )
    assert len(queries) == 2
