from __future__ import annotations

import json

from equipment_deep_research.agents.runtime_profiles import (
    build_codex_runtime_profile,
)
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.domain.research_focus import (
    BRANCH_REFERENCE_FOCUS,
    DISRUPTIVE_EQUIPMENT_SEEDS,
    REFERENCE_REQUIREMENT_OWNERS,
    disruptive_seed_context,
    select_disruptive_equipment_seeds,
)
from equipment_deep_research.orchestration.blueprints import (
    build_discovery_blueprint,
)


def test_reference_requirements_have_one_primary_owner() -> None:
    assert set(REFERENCE_REQUIREMENT_OWNERS) == set(range(1, 13))
    assert REFERENCE_REQUIREMENT_OWNERS[2] == "international_situation"
    assert REFERENCE_REQUIREMENT_OWNERS[3] == "F"
    assert REFERENCE_REQUIREMENT_OWNERS[12] == "D"


def test_each_branch_exposes_one_compact_reference_kernel() -> None:
    assert set(BRANCH_REFERENCE_FOCUS) == set("ABCDEFGH")
    for focus in BRANCH_REFERENCE_FOCUS.values():
        assert focus["task_kernel"]
        assert len(focus["task_kernel"]) <= 150


def test_blueprint_carries_only_the_selected_branch_reference_focus() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("穿透性制空与马赛克体系对抗", discovery_branch="F")
    )

    assert blueprint["reference_focus"]["source_items"] == [3, 6]
    assert "反穿透" in blueprint["reference_focus"]["task_kernel"]


def test_optimized_codex_runtime_keeps_short_branch_and_agent_lenses() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("量子信息与新质毁伤", discovery_branch="D")
    )
    blueprint["execution_profile_id"] = "optimized_v2"

    profile = build_codex_runtime_profile(
        "technology_radar",
        payload={"discovery_blueprint": blueprint},
        compact=True,
    )

    assert 1 <= len(profile["reference_expansion_lenses"]) <= 3
    assert profile["branch_focus"]["reference_focus"]["source_items"] == [4, 12]


def test_updated_reference_topics_resolve_without_future_war_case_misroute() -> None:
    cases = {
        "俄乌局部战争无人远程火力经验": "C",
        "量子信息与新质毁伤装备": "D",
        "金穹多层防御与预警拦截建设": "E",
        "穿透性制空和马赛克战体系": "F",
        "空天一体与无人潜航器网电融合": "G",
        "远海前出远程快打与第二岛链任务缺口": "B",
        "未来战争形态下的智能化大规模全域联合作战": "A",
    }
    for topic, expected in cases.items():
        problem = ResearchProblem(topic)
        assert problem.resolved_discovery_branch()["primary"] == expected

    assert (
        ResearchProblem(
            "未来战争形态下的智能化大规模全域联合作战"
        ).resolved_route()
        == "new_winning_mechanism"
    )


def test_all_twelve_disruptive_seed_directions_are_compact_and_unique() -> None:
    ids = [item["id"] for item in DISRUPTIVE_EQUIPMENT_SEEDS]
    assert ids == [
        "A1",
        "A2",
        "B1",
        "B2",
        "C1",
        "C2",
        "D1",
        "D2",
        "E1",
        "E2",
        "F1",
        "F2",
    ]
    for item in DISRUPTIVE_EQUIPMENT_SEEDS:
        assert len(item["shift"]) <= 50
        assert len(item["equipment_pull"]) <= 50
        assert len(item["checks"]) <= 50


def test_disruptive_seed_selector_prefers_query_relevance_and_dimension_diversity() -> None:
    cards = select_disruptive_equipment_seeds(
        "卫星致盲、数据链切断、GPS不可用条件下的无人远程精打",
        branch="F",
        agent_id="winning_s3_breakthrough",
    )

    assert 1 <= len(cards) <= 4
    assert cards[0]["id"] == "F2"
    assert len({item["dimension"] for item in cards}) >= 2
    assert all(item["selection_basis"] == "query_signal" for item in cards)


def test_disruptive_seed_selector_does_not_inject_priors_into_unrelated_query() -> None:
    cards = select_disruptive_equipment_seeds(
        "军队人力资源教育训练与组织管理研究",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert cards == []


def test_disruptive_seed_selector_allows_only_one_marked_exploration_card() -> None:
    cards = select_disruptive_equipment_seeds(
        "远域作战装备需求研究",
        branch="F",
        agent_id="winning_s3_breakthrough",
    )

    assert len(cards) == 1
    assert cards[0]["selection_basis"] == "bounded_exploration"


def test_broad_weapon_query_receives_one_diverse_challenge_lens() -> None:
    cards = select_disruptive_equipment_seeds(
        "无人远程火力打击范式装备需求研究",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert cards[0]["id"] == "B1"
    assert cards[0]["selection_basis"] == "query_signal"
    assert len(cards) == 2
    assert len({item["dimension"] for item in cards}) == 2
    assert sum(
        item["selection_basis"] == "bounded_exploration" for item in cards
    ) == 1


def test_single_cost_lens_is_challenged_without_filling_all_dimensions() -> None:
    cards = select_disruptive_equipment_seeds(
        "西太高强度对抗中的低成本远程精打弹药",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert cards[0]["id"] == "A1"
    assert len(cards) == 2
    assert len({item["dimension"] for item in cards}) == 2
    assert sum(
        item["selection_basis"] == "bounded_exploration" for item in cards
    ) == 1


def test_disruptive_seed_runtime_context_is_bounded_and_marks_seeds_as_hypotheses() -> None:
    context = disruptive_seed_context(
        "低成本弹药与传感器射手动态匹配",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert len(context["cards"]) <= 4
    assert "dimension_index" not in context
    assert "不是事实" in context["rule"]
    assert "2至3类" in context["rule"]
    assert "实战门" in context["rule"]
    assert "任务链断点" in context["rule"]
    assert "OTHER" in context["rule"]
    assert len(json.dumps(context, ensure_ascii=False)) < 1000


def test_broad_a2ad_query_gets_two_distinct_bounded_exploration_lenses() -> None:
    context = disruptive_seed_context(
        "挖掘在西太反介入体系下的装备能力缺口",
        branch="F",
        agent_id="weapon_equipment",
    )

    cards = context["cards"]
    assert len(cards) == 2
    assert len({item["dimension"] for item in cards}) == 2
    assert all(item["selection_basis"] == "bounded_exploration" for item in cards)
    assert len(json.dumps(context, ensure_ascii=False)) < 1200


def test_optimized_winning_runtime_keeps_selected_disruptive_seeds() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("拒止环境下无人远程精打", discovery_branch="F")
    )
    blueprint["execution_profile_id"] = "optimized_v2"

    profile = build_codex_runtime_profile(
        "winning_s3_breakthrough",
        payload={
            "query": "卫星致盲、链路中断和导航拒止条件下的无人远程精打",
            "discovery_blueprint": blueprint,
        },
        compact=True,
    )

    seed_context = profile["disruptive_seed_context"]
    assert 1 <= len(seed_context["cards"]) <= 4
    assert any(item["id"] == "F2" for item in seed_context["cards"])


def test_runtime_does_not_duplicate_seed_context_already_in_task_input() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("无人远程火力打击范式装备需求研究", discovery_branch="A")
    )
    blueprint["execution_profile_id"] = "optimized_v2"
    explicit = disruptive_seed_context(
        "无人远程火力打击范式装备需求研究",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    profile = build_codex_runtime_profile(
        "winning_s3_breakthrough",
        payload={
            "query": "无人远程火力打击范式装备需求研究",
            "execution_profile_id": "optimized_v2",
            "discovery_blueprint": blueprint,
            "disruptive_seed_context": explicit,
        },
        compact=True,
    )

    assert "disruptive_seed_context" not in profile
