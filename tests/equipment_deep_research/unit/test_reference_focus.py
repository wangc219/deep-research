from __future__ import annotations

import json

from equipment_deep_research.agents.runtime_profiles import (
    build_codex_runtime_profile,
)
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.domain.research_focus import (
    BRANCH_REFERENCE_FOCUS,
    DISRUPTIVE_EQUIPMENT_SEED_LIBRARY_VERSION,
    DISRUPTIVE_EQUIPMENT_SEEDS,
    REFERENCE_REQUIREMENT_OWNERS,
    disruptive_seed_context,
    disruptive_seed_pool_context,
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


def test_disruptive_paradigm_seed_library_v2_matches_twelve_seed_cards() -> None:
    assert DISRUPTIVE_EQUIPMENT_SEED_LIBRARY_VERSION == "v2"
    assert {
        item["id"]: (
            item["original_paradigm"],
            item["title"],
            item["research_relation"],
        )
        for item in DISRUPTIVE_EQUIPMENT_SEEDS
    } == {
        "A1": ("拦截经济学反转", "成本强加", "单件性能竞争→体系交换比竞争"),
        "A2": ("前线弹药工厂", "制造即战力", "后方库存→分布式按需制造"),
        "B1": ("徘徊火力云", "持续火力场", "临时发射→战区持续存在"),
        "B2": ("和平预置、战时激活", "预置任务节点", "战时部署→预先部署和可信激活"),
        "C1": ("毁平台转向毁节奏", "决策节奏对抗", "物理摧毁→压缩或扰乱决策周期"),
        "C2": ("越打越聪明", "战役内学习", "固定策略→批次间快速学习"),
        "D1": ("非动能点穴瘫痪", "功能压制", "结构毁伤→关键功能失效"),
        "D2": ("打击作为战略信号", "战略信号", "单纯毁伤→打击与认知效应结合"),
        "E1": ("任意传感器匹配最优射手", "火力即服务", "平台绑定→传感器与射手解耦"),
        "E2": ("蜂群对蜂群", "集群对抗生态", "单平台对抗→算法和种群对抗"),
        "F1": ("算法威慑、选择性透明", "可验证自主", "黑箱自主→可约束、可验证自主"),
        "F2": ("越降级越自主", "拒止环境自主", "网络依赖→断链条件下任务自治"),
    }


def test_dynamic_swarm_equipment_specialists_receive_v2_seed_cards() -> None:
    context = disruptive_seed_context(
        "强电磁压制下低成本无人蜂群精确打击",
        branch="D",
        agent_id="direct_combat_equipment_generator",
    )

    assert context["library_version"] == "v2"
    assert 1 <= len(context["cards"]) <= 3
    assert all("original_paradigm" in item for item in context["cards"])
    assert all("research_relation" in item for item in context["cards"])
    assert "不得复制种子标题作为装备名" in context["rule"]


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


def test_updated_reference_topics_are_routed_by_model_blueprint() -> None:
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
        assert problem.resolved_discovery_branch()["primary"] == "A"
        blueprint = build_discovery_blueprint(
            problem,
            model_blueprint={"primary_branch": expected, "confidence": 0.9},
        )
        assert blueprint["primary_branch"] == expected

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


def test_disruptive_seed_selector_does_not_invent_an_unmatched_exploration_card() -> None:
    cards = select_disruptive_equipment_seeds(
        "远域作战装备需求研究",
        branch="F",
        agent_id="winning_s3_breakthrough",
    )

    assert cards == []


def test_broad_weapon_query_receives_only_its_direct_reference_lens() -> None:
    cards = select_disruptive_equipment_seeds(
        "无人远程火力打击范式装备需求研究",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert cards[0]["id"] == "B1"
    assert cards[0]["selection_basis"] == "query_signal"
    assert len(cards) == 1


def test_single_cost_lens_does_not_trigger_prior_based_seed_filling() -> None:
    cards = select_disruptive_equipment_seeds(
        "西太高强度对抗中的低成本远程精打弹药",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert cards[0]["id"] == "A1"
    assert len(cards) == 1


def test_disruptive_seed_runtime_context_is_bounded_and_marks_seeds_as_hypotheses() -> None:
    context = disruptive_seed_context(
        "低成本弹药与传感器射手动态匹配",
        branch="A",
        agent_id="winning_s3_breakthrough",
    )

    assert len(context["cards"]) <= 4
    assert "dimension_index" not in context
    assert "不是事实" in context["rule"]
    assert "Codex应从完整Query自行发散" in context["rule"]
    assert "实战门" in context["rule"]
    assert "任务链断点" in context["rule"]
    assert "OTHER" in context["rule"]
    assert len(json.dumps(context, ensure_ascii=False)) < 1000


def test_complete_seed_pool_is_reserved_for_post_divergence_model_review() -> None:
    context = disruptive_seed_pool_context()

    assert len(context["cards"]) == len(DISRUPTIVE_EQUIPMENT_SEEDS)
    assert all(
        item["selection_basis"] == "post_divergence_model_review"
        for item in context["cards"]
    )
    assert "采用、重写、跨种子重构" in context["rule"]
    assert "不得按维度逐项覆盖" in context["rule"]


def test_broad_a2ad_query_is_left_to_codex_when_no_seed_directly_matches() -> None:
    context = disruptive_seed_context(
        "挖掘在西太反介入体系下的装备能力缺口",
        branch="F",
        agent_id="weapon_equipment",
    )

    assert context == {}


def test_optimized_winning_runtime_does_not_seed_first_s3_divergence() -> None:
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

    assert "disruptive_seed_context" not in profile


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
