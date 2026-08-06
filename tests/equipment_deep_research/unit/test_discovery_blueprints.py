from __future__ import annotations

from pathlib import Path

import pytest

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.blueprints import (
    BRANCH_BLUEPRINTS,
    build_discovery_blueprint,
    execution_waves_from_blueprint,
)
from equipment_deep_research.orchestration.runner import (
    _normalize_discovery_meta_review,
)


def test_maximized_waves_run_all_dependency_ready_agents_together() -> None:
    independent = AgentDef("independent", "Independent", "", ["threat"], [], {})
    upstream = AgentDef("upstream", "Upstream", "", ["scenario"], [], {})
    downstream = AgentDef(
        "downstream",
        "Downstream",
        "",
        ["equipment"],
        [],
        {},
        handoff_policy={"wait_for": ["upstream"]},
    )

    waves = execution_waves_from_blueprint(
        [upstream, downstream, independent],
        {"waves": [["upstream"], ["downstream"], ["independent"]]},
        maximize_parallelism=True,
    )

    assert [[agent.agent_id for agent in wave] for wave in waves] == [
        ["upstream", "independent"],
        ["downstream"],
    ]


def test_real_baseline_contract_runs_four_research_agents_before_synthesis() -> None:
    root = Path(__file__).parents[3]
    registry = AgentRegistry.load(root / "configs/equipment_deep_research/agents.yaml")
    selected = registry.select_agents(
        [
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "system_confrontation",
            "operational_employment",
        ]
    )

    waves = execution_waves_from_blueprint(
        selected,
        {
            "waves": [
                ["international_situation"],
                ["combat_scenario", "weapon_equipment"],
                ["system_confrontation", "operational_employment"],
            ]
        },
        maximize_parallelism=True,
    )

    assert [[agent.agent_id for agent in wave] for wave in waves] == [
        [
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "system_confrontation",
        ],
        ["operational_employment"],
    ]


def test_meta_review_cannot_activate_skipped_step_without_dynamic_callback() -> None:
    review = _normalize_discovery_meta_review(
        {
            "replan_required": True,
            "step_mode_overrides": [
                {"step": 1, "mode": "deep", "reason": "需要对手分析"}
            ],
        },
        {
            "primary_branch": "F",
            "runtime_route": "traditional_gap",
        },
        available_skills={},
        available_knowledge_pack_ids=[],
    )

    assert review["replan_required"] is False
    assert review["step_mode_overrides"] == []


def test_meta_review_can_activate_skipped_step_with_matching_dynamic_callback() -> None:
    review = _normalize_discovery_meta_review(
        {
            "replan_required": True,
            "step_mode_overrides": [
                {"step": 1, "mode": "deep", "reason": "需要对手分析"}
            ],
            "dynamic_subagents": [
                {
                    "display_name": "对手补充分析",
                    "purpose": "补充对手体系证据并合并到S1",
                    "trigger_gap": "F分支默认跳过S1但出现了明确对手体系缺口",
                    "merge_target": "S1",
                    "skill_ids": [],
                    "knowledge_pack_ids": [],
                }
            ],
        },
        {
            "primary_branch": "F",
            "runtime_route": "traditional_gap",
        },
        available_skills={},
        available_knowledge_pack_ids=[],
    )

    assert review["replan_required"] is True
    assert review["step_mode_overrides"][0]["step"] == 1


@pytest.mark.parametrize(
    ("code", "route", "specialist"),
    [
        ("A", "new_winning_mechanism", None),
        ("B", "traditional_gap", None),
        ("C", "war_case_learning", "case_research"),
        ("D", "new_winning_mechanism", "technology_radar"),
        ("E", "new_winning_mechanism", "opponent_monitoring"),
        ("F", "traditional_gap", "system_confrontation"),
        ("G", "new_winning_mechanism", "cross_domain_fusion"),
        ("H", "new_winning_mechanism", "nontraditional_security"),
    ],
)
def test_each_architecture_branch_builds_an_executable_blueprint(
    code: str,
    route: str,
    specialist: str | None,
) -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("test", discovery_branch=code)
    )

    assert blueprint["primary_branch"] == code
    assert blueprint["runtime_route"] == route
    assert blueprint["required_capability_tags"]
    assert blueprint["required_outputs"]
    assert blueprint["waves"]
    assert blueprint["initial_baseline_agent_ids"]
    assert blueprint["baseline_agent_plan"]
    if specialist:
        assert specialist in blueprint["specialist_agent_ids"]


@pytest.mark.parametrize(
    ("topic", "branch"),
    [
        ("多源联通低轨韧性背景下风险研判", "B"),
        ("印度洋基地支撑强扰链路场景支撑研究", "B"),
        ("认知空间在台海关键通道态势研判", "H"),
        ("高消耗战场边缘智能影响响应研究", "D"),
    ],
)
def test_concise_benchmark_queries_do_not_fall_into_new_tactics_by_default(
    topic: str,
    branch: str,
) -> None:
    problem = ResearchProblem(topic)

    assert problem.resolved_discovery_branch()["primary"] == branch
    assert build_discovery_blueprint(problem)["primary_branch"] == branch


@pytest.mark.parametrize(
    "topic",
    [
        "印度洋基地支撑强扰链路场景支撑研究",
        "日本西南岛链无人作战研究",
        "东北亚高消耗战场边缘智能研究",
    ],
)
def test_external_region_queries_lock_in_international_situation_agent(
    topic: str,
) -> None:
    blueprint = build_discovery_blueprint(ResearchProblem(topic))
    plan = {
        item["agent_id"]: item["mode"]
        for item in blueprint["baseline_agent_plan"]
    }

    assert plan["international_situation"] == "required"
    assert "international_situation" in blueprint["initial_baseline_agent_ids"]


def test_narrow_domestic_equipment_query_does_not_force_situation_agent() -> None:
    blueprint = build_discovery_blueprint(ResearchProblem("某型现役雷达升级"))
    plan = {
        item["agent_id"]: item["mode"]
        for item in blueprint["baseline_agent_plan"]
    }

    assert plan["international_situation"] == "callback"
    assert "international_situation" not in blueprint["initial_baseline_agent_ids"]


def test_supplement_is_compressed_and_influences_blueprint_semantics() -> None:
    problem = ResearchProblem(
        "低成本远程弹药研究",
        supplemental_information=(
            "面向西太高强度对抗，如果可万枚级量产且单发成本低于拦截弹1/50，"
            "如何改变持续消耗、火力配系、弹药基数与后勤保障？"
        ),
    )

    blueprint = build_discovery_blueprint(problem)
    brief = blueprint["structured_query_brief"]

    assert brief["supplement_present"] is True
    assert brief["expansion_dimensions"] == [
        "任务对象与直接效果",
        "对手适应与失效边界",
        "装备形态与工程约束",
        "证据问题与淘汰条件",
        "成本交换与效费比",
        "规模化生产与工业动员",
    ]
    assert "international_situation" in blueprint["initial_baseline_agent_ids"]


def test_model_query_brief_preserves_bounded_combat_weapon_divergence_fields() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("强电磁压制下精确打击任务续接装备研究"),
        model_blueprint={
            "structured_query_brief": {
                "combat_problem_frame": "在敌防空节点短时开机与导航拒止并存时续接纵深火力。",
                "enemy_target_profile": [f"目标{i}" for i in range(10)],
                "battle_phase_and_constraints": [f"阶段{i}" for i in range(12)],
                "required_direct_military_effects": [f"战果{i}" for i in range(9)],
                "weapon_design_variables": [f"变量{i}" for i in range(12)],
                "query_specific_weapon_architectures": [
                    f"Query专属武器架构{i}" for i in range(9)
                ],
                "equipment_project_hypotheses": [
                    {
                        "project_name": f"项目{i}",
                        "equipment_form": f"具体装备形态{i}",
                        "project_function": f"作战单元在约束{i}下完成任务动作并形成直接战果",
                        "query_causal_link": f"因果链{i}",
                        "design_variables": [f"变量{i}-{j}" for j in range(10)],
                    }
                    for i in range(9)
                ],
                "rejected_template_anchors": [f"拒绝模板{i}" for i in range(9)],
            }
        },
    )

    brief = blueprint["structured_query_brief"]
    assert brief["combat_problem_frame"].startswith("在敌防空节点")
    assert len(brief["enemy_target_profile"]) == 6
    assert len(brief["battle_phase_and_constraints"]) == 8
    assert len(brief["required_direct_military_effects"]) == 6
    assert len(brief["weapon_design_variables"]) == 8
    assert len(brief["query_specific_weapon_architectures"]) == 6
    assert brief["query_specific_weapon_architectures"][0] == "Query专属武器架构0"
    assert len(brief["equipment_project_hypotheses"]) == 6
    assert brief["equipment_project_hypotheses"][0]["project_name"] == "项目0"
    assert len(brief["equipment_project_hypotheses"][0]["design_variables"]) == 8
    assert len(brief["rejected_template_anchors"]) == 6


@pytest.mark.parametrize(
    ("route", "branch"),
    [
        ("new_winning_mechanism", "A"),
        ("traditional_gap", "B"),
        ("war_case_learning", "C"),
    ],
)
def test_explicit_research_route_remains_authoritative_without_branch_keywords(
    route: str,
    branch: str,
) -> None:
    assert ResearchProblem("通用研究题目", research_route=route).resolved_discovery_branch()[
        "primary"
    ] == branch


def test_model_blueprint_controls_required_reference_and_callback_agents() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("无人智能集群新战法", discovery_branch="A"),
        model_blueprint={
            "primary_branch": "A",
            "baseline_agent_plan": [
                {
                    "agent_id": "operational_employment",
                    "mode": "required",
                    "reason": "深度审查现有战法并生成新战法",
                },
                {
                    "agent_id": "combat_scenario",
                    "mode": "reference",
                    "reason": "提供任务场景压力",
                },
                {
                    "agent_id": "international_situation",
                    "mode": "callback",
                    "reason": "仅在战略背景缺口出现时补充",
                },
            ],
        },
        available_agent_capabilities={
            "operational_employment": ["operation"],
            "combat_scenario": ["scenario"],
            "international_situation": ["situation"],
            "weapon_equipment": ["equipment"],
        },
    )

    assert blueprint["initial_baseline_agent_ids"] == [
        "operational_employment",
        "combat_scenario",
    ]
    assert blueprint["callback_agent_ids"] == ["international_situation"]
    assert blueprint["semantic_agent_signals"] == []


def test_b_branch_preserves_background_scenario_chain_and_defers_overlapping_agents() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem(
            "西太反介入体系下现役装备作战运用与升级方向",
            discovery_branch="B",
        ),
        available_agent_capabilities={
            "international_situation": ["situation", "threat"],
            "combat_scenario": ["scenario"],
            "weapon_equipment": ["equipment", "capability_gap"],
            "operational_employment": ["operation", "coordination"],
            "system_confrontation": ["system_modeling"],
            "opponent_monitoring": ["opponent_monitoring"],
        },
    )

    assert blueprint["initial_baseline_agent_ids"] == [
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    ]
    assert set(blueprint["callback_agent_ids"]) >= {
        "system_confrontation",
    }
    assert len(blueprint["initial_baseline_agent_ids"]) == 4
    assert {
        item["agent_id"] for item in blueprint["semantic_agent_signals"]
    } >= {
        "international_situation",
        "system_confrontation",
        "weapon_equipment",
        "operational_employment",
    }


def test_topic_policy_does_not_expand_narrow_equipment_task_to_all_agents() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("某型现役雷达升级能力差距", discovery_branch="B"),
        available_agent_capabilities={
            "international_situation": ["situation"],
            "combat_scenario": ["scenario"],
            "weapon_equipment": ["equipment", "capability_gap"],
            "operational_employment": ["operation"],
            "system_confrontation": ["system_modeling"],
        },
    )

    assert blueprint["initial_baseline_agent_ids"] == [
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
    ]
    assert {"international_situation"} <= set(
        blueprint["callback_agent_ids"]
    )


def test_autonomous_mode_prepends_scenario_divergence_and_meta_loop() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem(
            "前沿技术机会",
            interaction_mode="autonomous",
            discovery_branch="D",
            max_rounds_hint=4,
        )
    )

    assert blueprint["waves"][0] == ["scenario_divergence"]
    assert blueprint["specialist_agent_ids"][0] == "scenario_divergence"
    assert "autonomous_discovery" in blueprint["required_capability_tags"]
    assert blueprint["loop_policy"] == {
        "inner_max_iterations": 1,
        "middle_max_cycles": 1,
        "outer_max_rounds": 2,
        "meta_max_cycles": 1,
    }


def test_expert_explicit_branch_cannot_be_overridden_by_model_blueprint() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("专家指定技术分支", discovery_branch="D"),
        model_blueprint={
            "primary_branch": "F",
            "secondary_branches": ["G"],
            "rationale": "model proposal",
        },
    )

    assert blueprint["primary_branch"] == "D"
    assert blueprint["secondary_branches"] == []
    assert blueprint["generated_by"] == "codex_orchestrator"


def test_blueprint_catalog_covers_exactly_a_through_h() -> None:
    assert list(BRANCH_BLUEPRINTS) == list("ABCDEFGH")


def test_first_three_branches_carry_architecture_final_output_contracts() -> None:
    outputs = {
        code: build_discovery_blueprint(
            ResearchProblem("test", discovery_branch=code)
        )["required_outputs"]
        for code in "ABC"
    }

    assert any("3种新战法+5种战法组合" in item for item in outputs["A"])
    assert any("8大能力域+30项能力指标" in item for item in outputs["A"])
    assert any("需求卡片" in item for item in outputs["B"])
    assert any("能力全景图" in item for item in outputs["B"])
    assert any("6条核心规律" in item for item in outputs["C"])
    assert any("3类高置信场景" in item for item in outputs["C"])
    assert all(any("深度研究主报告" in item for item in rows) for rows in outputs.values())


def test_other_driver_uses_nearest_branch_as_dynamic_runtime_base() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("复杂新型任务"),
        model_blueprint={
            "primary_branch": "G",
            "secondary_branches": [],
            "unmatched_driver": "跨域装备市场与民用供应链韧性联合牵引",
            "driver_scores": [
                {"branch": "G", "score": 0.74, "signals": ["跨域接口"]},
                {"branch": "H", "score": 0.61, "signals": ["跨部门边界"]},
            ],
            "focus_questions": ["供应链约束如何改变跨域能力优先级"],
            "custom_blueprint": {
                "driver_type": "跨域供应链韧性牵引",
                "required_capability_tags": ["cross_domain", "technology_readiness"],
                "preferred_agent_ids": [
                    "cross_domain_fusion",
                    "weapon_equipment",
                    "hallucinated_agent",
                ],
                "waves": [["cross_domain_fusion"], ["weapon_equipment"]],
                "dependencies": [
                    {
                        "upstream": "cross_domain_fusion",
                        "downstream": "weapon_equipment",
                        "handoff": "跨域接口与供应链压力点",
                    }
                ],
                "s1_s6_modes": {"3": "deep", "4": "deep", "5": "standard", "6": "deep"},
                "required_outputs": ["供应链韧性能力需求"],
                "stop_conditions": ["关键依赖与替代方案闭合"],
            },
            "confidence": 0.66,
        },
        available_agent_capabilities={
            "cross_domain_fusion": ["cross_domain"],
            "weapon_equipment": ["technology_readiness", "equipment"],
        },
    )

    assert blueprint["primary_branch"] == "G"
    assert blueprint["blueprint_mode"] == "meta_composed"
    assert blueprint["unmatched_driver"]
    assert blueprint["driver_scores"][0]["branch"] == "G"
    assert blueprint["focus_questions"] == ["供应链约束如何改变跨域能力优先级"]
    assert blueprint["custom_blueprint"]["preferred_agent_ids"] == [
        "cross_domain_fusion",
        "weapon_equipment",
    ]
    assert blueprint["waves"][:2] == [
        ["cross_domain_fusion"],
        ["weapon_equipment"],
    ]
    assert blueprint["adaptive_winning_step_modes"]["3"] == "deep"


def test_other_driver_rejects_custom_agent_dependency_cycle() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("新型复合驱动任务"),
        model_blueprint={
            "primary_branch": "F",
            "unmatched_driver": "复合驱动",
            "custom_blueprint": {
                "preferred_agent_ids": ["a", "b"],
                "waves": [["a"], ["b"]],
                "dependencies": [
                    {"upstream": "a", "downstream": "b"},
                    {"upstream": "b", "downstream": "a"},
                ],
            },
        },
        available_agent_capabilities={"a": ["scenario"], "b": ["equipment"]},
    )

    assert blueprint["blueprint_mode"] == "dynamic_extension"
    assert blueprint["custom_blueprint"]["dependency_cycle_rejected"] is True
    assert blueprint["custom_blueprint"]["preferred_agent_ids"] == []


def test_blueprint_normalizes_bounded_dynamic_codex_subagent_contract() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("需要供应链韧性专用分析"),
        model_blueprint={
            "primary_branch": "G",
            "unmatched_driver": "跨域能力与供应链韧性复合驱动",
            "dynamic_subagents": [
                {
                    "display_name": "供应链韧性研究Agent",
                    "purpose": "评估关键部件、产能和替代路线对跨域能力形成的约束",
                    "trigger_gap": "固定Agent缺少供应链韧性专用视角",
                    "required_capability_tags": ["supply_chain_resilience"],
                    "skill_ids": ["codex_deep_search_shared", "unknown_skill"],
                    "knowledge_pack_ids": ["equipment_ontology", "unknown_pack"],
                    "methodology": ["建立关键依赖", "比较替代路线"],
                    "quality_gates": ["结论可追溯"],
                    "output_fields": ["dependencies", "alternatives"],
                    "merge_target": "S5",
                    "stop_conditions": ["关键依赖和替代路线闭合"],
                    "max_output_tokens": 9999,
                }
            ],
        },
        available_skills={
            "codex_deep_search_shared": {
                "shared": True,
                "allowed_tools": ["search_sources", "fetch_page"],
                "knowledge_pack_ids": ["public_evidence_index"],
            }
        },
        available_knowledge_pack_ids=[
            "public_evidence_index",
            "equipment_ontology",
        ],
    )

    dynamic = blueprint["dynamic_subagents"][0]
    assert dynamic["agent_instance_id"].startswith("dynamic-")
    assert dynamic["skill_ids"] == ["codex_deep_search_shared"]
    assert dynamic["knowledge_pack_ids"] == [
        "public_evidence_index",
        "equipment_ontology",
    ]
    assert dynamic["allowed_tools"] == ["search_sources", "fetch_page"]
    assert dynamic["merge_target"] == "S5"
    assert dynamic["max_output_tokens"] == 3200


def test_unmatched_driver_without_valid_dynamic_contract_does_not_invent_agent() -> None:
    blueprint = build_discovery_blueprint(
        ResearchProblem("现有业务Agent可以覆盖的复合任务"),
        model_blueprint={
            "primary_branch": "G",
            "unmatched_driver": "跨域接口与保障韧性复合牵引",
            "dynamic_subagents": [],
        },
        available_skills={
            "codex_deep_search_shared": {
                "shared": True,
                "allowed_tools": ["search_sources"],
                "knowledge_pack_ids": ["public_evidence_index"],
            }
        },
        available_knowledge_pack_ids=["public_evidence_index"],
    )

    assert blueprint["unmatched_driver"]
    assert blueprint["dynamic_subagents"] == []
