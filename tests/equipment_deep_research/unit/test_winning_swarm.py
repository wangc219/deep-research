from __future__ import annotations

from dataclasses import replace

import pytest

from equipment_deep_research.domain.models import (
    SpecialistTask,
    WinningContribution,
    WinningExpertAssessment,
    WinningHypothesis,
)
from equipment_deep_research.orchestration.blueprints import (
    build_discovery_blueprint,
    normalize_dynamic_subagents,
)
from equipment_deep_research.orchestration.execution_contracts import (
    apply_execution_profile_to_blueprint,
    resolve_execution_profile,
    swarm_quality_v1_profile,
    winning_swarm_dynamic_v2_profile,
)
from equipment_deep_research.orchestration.winning_swarm import (
    SWARM_SPECIALIST_ARCHETYPES,
    WinningSwarmController,
    normalize_winning_swarm_policy,
)
from equipment_deep_research.domain.models import ResearchProblem


def _hypothesis(**overrides: object) -> WinningHypothesis:
    payload = {
        "hypothesis_id": "hypothesis-1",
        "title": "分布式低成本拦截节点改变饱和防御成本交换",
        "nearest_public_baseline": "现有公开基线依赖少量高价值集中式拦截节点",
        "changed_confrontation_variable": "把单节点性能优势改为可快速补充的节点密度与任务接续",
        "mechanism_chain": ["分散部署", "局部感知与交战", "节点损耗后任务接续"],
        "direct_military_effects": ["提高区域拒止持续性", "缩短受威胁方向的防御空窗"],
        "equipment_forms": ["模块化无人拦截平台"],
        "project_function": "防空分队在饱和来袭与节点损耗条件下依靠模块化无人拦截平台持续实施物理拦截并续接区域拒止任务。",
        "system_interfaces": ["平台任务总线", "火控授权接口", "战术数据链接口"],
        "novelty_delta": "从集中式高价值节点转向可补充、可降级运行的分布式装备族",
        "evidence_ids": ["ev-1"],
        "counterevidence": ["复杂电磁环境可能降低局部协同质量"],
        "adversary_adaptations": ["对手转向诱饵和节点压制"],
        "failure_boundaries": ["局部感知完全失效时机制不成立"],
        "trl_constraints": ["关键载荷成熟度需按公开试验节点复核"],
        "cost_constraints": ["全寿命成本需与现役拦截方案比较"],
        "industrial_constraints": ["依赖模块化量产与战损补充能力"],
        "cross_scenario_results": ["弱网条件下降级运行，强干扰条件需独立测试"],
        "validation_plan": ["用对照场景测试节点损耗后的任务链闭合等级"],
        "evidence_boundary": "公开证据仅支持组成技术与试验节点，不证明完整作战效能",
        "implementation_path": "new",
        "merge_targets": ["S4"],
        "source_task_ids": ["task-source"],
        "residuals": [],
        "score": 0.9,
    }
    payload.update(overrides)
    return WinningHypothesis(**payload)


def test_swarm_profile_is_bounded_challenger_and_enables_blueprint_policy() -> None:
    profile = swarm_quality_v1_profile()
    blueprint = apply_execution_profile_to_blueprint(
        build_discovery_blueprint(ResearchProblem("test")),
        profile,
    )

    assert profile.profile_id == "swarm_quality_v1"
    assert profile.status == "challenger"
    assert profile.approved is False
    assert profile.parent_profile_id == "legacy_v1"
    assert blueprint["winning_swarm_policy"]["enabled"] is True
    assert blueprint["winning_swarm_policy"]["max_dynamic_instances"] == 12
    assert blueprint["winning_swarm_policy"]["max_concurrency"] == 6
    assert resolve_execution_profile("swarm_quality_v1") == profile


def test_dynamic_v2_profile_reserves_six_parallel_repair_instances() -> None:
    profile = winning_swarm_dynamic_v2_profile()
    blueprint = apply_execution_profile_to_blueprint(
        build_discovery_blueprint(ResearchProblem("dynamic graph")), profile
    )

    assert profile.status == "challenger"
    assert profile.parent_profile_id == "swarm_quality_v1"
    assert resolve_execution_profile("winning_swarm_dynamic_v2") == profile
    assert blueprint["winning_swarm_policy"]["policy_id"] == "winning_swarm_dynamic_v2"
    assert blueprint["winning_swarm_policy"]["expert_judge_enabled"] is True
    assert blueprint["winning_swarm_policy"]["expert_judge_required"] is True
    assert blueprint["winning_swarm_policy"]["finalist_minimum"] == 5
    assert blueprint["winning_swarm_policy"]["finalist_maximum"] == 7
    assert blueprint["winning_swarm_policy"]["mission_graph_target_instances"] == 12
    assert blueprint["winning_swarm_policy"]["expert_candidate_pool_maximum"] == 10
    assert blueprint["winning_swarm_policy"]["expert_repair_reserved_instances"] == 6
    assert blueprint["winning_swarm_policy"]["expert_repair_max_candidates"] == 6
    assert blueprint["runtime_budgets"]["maximum_quality_judge_model_calls"] == 3
    assert blueprint["runtime_budgets"]["maximum_swarm_model_calls"] == 20
    assert blueprint["runtime_budgets"]["codex_concurrency"] == 6
    assert blueprint["execution_contract"]["codex_concurrency"] == 6
    assert blueprint["winning_swarm_policy"]["max_dynamic_instances"] == 18
    assert blueprint["winning_swarm_policy"]["mission_graph_max_instances"] == 18
    assert blueprint["winning_swarm_policy"]["max_concurrency"] == 6
    assert blueprint["winning_swarm_policy"]["mission_graph_min_instances"] == 8


def test_policy_clamps_instance_concurrency_wave_and_gain_bounds() -> None:
    policy = normalize_winning_swarm_policy(
        {
            "enabled": True,
            "max_dynamic_instances": 999,
            "max_concurrency": 99,
            "max_waves": 9,
            "minimum_expected_gain": -1,
            "promotion": {
                "minimum_eligible_runs": 2,
                "minimum_positive_increment_rate": 0.2,
            },
        }
    )

    assert policy["max_dynamic_instances"] == 12
    assert policy["max_concurrency"] == 6
    assert policy["max_waves"] == 3
    assert policy["minimum_expected_gain"] == 0.0
    assert policy["promotion"]["minimum_eligible_runs"] == 10
    assert policy["promotion"]["minimum_positive_increment_rate"] == 0.70


def test_dynamic_v2_mission_graph_seeds_s1_s6_with_parallel_instances() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    graph = controller.build_mission_graph(
        topic="test mission",
        target_instances=15,
    )

    assert 8 <= len(graph.agent_instances) <= 16
    assert len(graph.agent_instances) == 15
    assert graph.maximum_concurrency == 6
    assert set(graph.s_node_seeds) == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert all(graph.s_node_seeds[node] for node in graph.s_node_seeds)
    assert len(graph.waves[0]) >= 4
    assert all(instance.allow_child_spawn is False for instance in graph.agent_instances)
    by_archetype = {item.archetype: item for item in graph.agent_instances}
    frontier = by_archetype["frontier_equipment_miner"]
    architect = by_archetype["equipment_realization_architect"]
    evidence = by_archetype["evidence_verifier"]
    trl = by_archetype["trl_cost_industrial_auditor"]
    validation = by_archetype["validation_experiment_designer"]
    reviewer = by_archetype["independent_portfolio_reviewer"]
    assert "direct_combat_equipment_generator" in by_archetype
    assert "remote_precision_munition_generator" in by_archetype
    assert "mass_scalable_combat_family_generator" in by_archetype
    assert "始终按query筛选" in SWARM_SPECIALIST_ARCHETYPES[
        "direct_combat_equipment_generator"
    ]["purpose"]
    assert "非穷尽观察镜头" in SWARM_SPECIALIST_ARCHETYPES[
        "remote_precision_munition_generator"
    ]["purpose"]
    assert "不是强制主题" in SWARM_SPECIALIST_ARCHETYPES[
        "mass_scalable_combat_family_generator"
    ]["purpose"]
    assert sum(item.mission_node == "S3" for item in graph.agent_instances) >= 5
    node_by_id = {
        item.instance_id: item.mission_node for item in graph.agent_instances
    }
    assert {node_by_id[item] for item in frontier.depends_on} == {"S1", "S2"}
    assert {node_by_id[item] for item in architect.depends_on} == {"S3"}
    assert {node_by_id[item] for item in evidence.depends_on} == {"S3"}
    assert {node_by_id[item] for item in trl.depends_on} == {"S4"}
    assert {node_by_id[item] for item in validation.depends_on} == {"S3", "S4"}
    assert validation.instance_id in reviewer.depends_on
    assert frontier.wave == by_archetype["disruptive_mechanism_generator"].wave
    assert evidence.wave == architect.wave
    assert graph.merge_strategy.startswith("artifact_ready_speculative_parallel")

    with pytest.raises(ValueError, match="may not recruit"):
        controller.govern_role_contract(
            {
                "archetype": "unsafe_role",
                "purpose": "unsafe",
                "allow_child_spawn": True,
            },
            mission_node="S4",
        )


def test_versioned_ledger_requires_rebase_and_builds_pareto_decision() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    ledger = controller.create_ledger([_hypothesis(hypothesis_id="h1")])
    stale = WinningContribution(
        contribution_id="c1",
        agent_instance_id="agent-1",
        role_contract_id="role-1",
        hypothesis_id="h1",
        merge_target="S5",
        base_ledger_version=0,
        hypothesis_patch={"findings": ["补充核验"], "evidence_boundary": "仅支持方向"},
        evidence_ids=["ev-2"],
        incremental_quality=0.05,
    )

    unchanged, stale_receipt = controller.merge_contribution(ledger, stale)
    assert unchanged.version == 1
    assert stale_receipt.status == "rebase_required"
    rebased = controller.rebase_contribution(stale, ledger)
    merged, receipt = controller.merge_contribution(ledger, rebased)
    assert merged.version == 2
    assert receipt.status == "merged"
    assert merged.parent_version == 1
    assert "ev-2" in merged.hypotheses[0].evidence_ids

    decision = controller.portfolio_decision(merged)
    assert decision.ledger_version == 2
    assert decision.pareto_front == ["h1"]
    assert decision.selected_hypothesis_ids == ["h1"]


def test_rejected_contribution_receipt_explains_acceptance_failure() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    ledger = controller.create_ledger([_hypothesis(hypothesis_id="h1")])
    contribution = WinningContribution(
        contribution_id="c-rejected",
        agent_instance_id="agent-s6",
        role_contract_id="role-s6",
        hypothesis_id="h1",
        merge_target="S6",
        base_ledger_version=ledger.version,
        hypothesis_patch={"validation_plan": ["开展对照试验"]},
        incremental_quality=0.0,
        accepted=False,
    )

    unchanged, receipt = controller.merge_contribution(ledger, contribution)

    assert unchanged.version == ledger.version
    assert receipt.status == "rejected"
    assert receipt.conflicts == ["contribution_not_accepted"]


def test_diverse_candidate_retention_reserves_specialist_equipment_lanes() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    generic = [
        replace(
            _hypothesis(hypothesis_id=f"generic-{index}", score=1.0),
            source_task_ids=[f"generic-source-{index}"],
        )
        for index in range(8)
    ]
    specialist_rows = [
        replace(
            _hypothesis(hypothesis_id=f"remote-{index}", score=0.9),
            source_task_ids=["remote-source"],
        )
        for index in range(2)
    ] + [
        replace(
            _hypothesis(hypothesis_id=f"mass-{index}", score=0.9),
            source_task_ids=["mass-source"],
        )
        for index in range(2)
    ]

    retained = controller.retain_diverse_candidates(
        [*generic, *specialist_rows],
        maximum=8,
        priority_source_groups=[{"remote-source"}, {"mass-source"}],
        quota_per_priority_group=2,
    )

    retained_ids = {item.hypothesis_id for item in retained}
    assert {"remote-0", "remote-1", "mass-0", "mass-1"} <= retained_ids
    assert len(retained) == 8


def test_expert_repair_can_replace_unsupported_claims_with_bounded_portrait() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    speculative = replace(
        _hypothesis(hypothesis_id="h1"),
        equipment_forms=["未经验证的母弹异构子载荷"],
        novelty_delta="现场任意更换全部部段",
    )
    ledger = controller.create_ledger([speculative])
    repair = WinningContribution(
        contribution_id="winning-expert-repair-bounded",
        agent_instance_id="repair-agent",
        role_contract_id="repair-role",
        hypothesis_id="h1",
        merge_target="S4",
        base_ledger_version=ledger.version,
        hypothesis_patch={
            "findings": ["删除超出证据边界的装备构型"],
            "patch_mode": "replace_bounded_claims",
            "replace_fields": [
                "title",
                "changed_confrontation_variable",
                "mechanism_chain",
                "equipment_forms",
                "novelty_delta",
            ],
            "title": "JASSM-ER类受扰导航验证型",
            "changed_confrontation_variable": "卫星导航拒止下保持固定目标区进入",
            "mechanism_chain": ["防区外发射", "受扰导航保持", "固定目标区进入"],
            "equipment_forms": ["固定构型远程精确制导任务弹药"],
            "novelty_delta": "仅主张工厂级构型换产与任务软件更新",
        },
        incremental_quality=0.05,
        recommendation="revise",
        accepted=True,
    )

    merged, receipt = controller.merge_contribution(ledger, repair)

    assert receipt.status == "merged"
    assert merged.hypotheses[0].equipment_forms == [
        "固定构型远程精确制导任务弹药"
    ]
    assert merged.hypotheses[0].title == "JASSM-ER类受扰导航验证型"
    assert merged.hypotheses[0].changed_confrontation_variable == (
        "卫星导航拒止下保持固定目标区进入"
    )
    assert merged.hypotheses[0].mechanism_chain == [
        "防区外发射",
        "受扰导航保持",
        "固定目标区进入",
    ]
    assert merged.hypotheses[0].novelty_delta == (
        "仅主张工厂级构型换产与任务软件更新"
    )


def test_quality_expert_judge_normalizes_scores_and_blocks_weak_equipment_fit() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    strong = _hypothesis(hypothesis_id="strong")
    weak = _hypothesis(
        hypothesis_id="weak",
        title="通用算法与通信中台",
        equipment_forms=["通用算法中台"],
    )
    ledger = controller.create_ledger([strong, weak])
    strong_assessment = controller.expert_assessment_from_mapping(
        {
            "verdict": "pass",
            "dimension_scores": {
                "domain_relevance": 0.9,
                "equipment_capability_fit": 0.86,
                "innovation": 0.8,
                "military_value": 0.88,
                "causal_coherence": 0.84,
                "credibility": 0.8,
                "engineering_feasibility": 0.74,
                "robustness": 0.72,
            },
            "strengths": ["形成直接战斗装备落点"],
            "evidence_ids": ["ev-1", "invented"],
            "confidence": 0.82,
        },
        hypothesis=strong,
        blind_label="候选-01",
        valid_evidence_ids={"ev-1"},
        session_ref="session-judge",
    )
    weak_assessment = controller.expert_assessment_from_mapping(
        {
            "verdict": "pass",
            "dimension_scores": {
                "domain_relevance": 0.8,
                "equipment_capability_fit": 0.35,
                "innovation": 0.7,
                "military_value": 0.45,
                "causal_coherence": 0.65,
                "credibility": 0.7,
                "engineering_feasibility": 0.8,
                "robustness": 0.7,
            },
            "rejection_reasons": ["支撑能力没有绑定具体战斗装备"],
            "confidence": 0.75,
        },
        hypothesis=weak,
        blind_label="候选-02",
        valid_evidence_ids={"ev-1"},
        session_ref="session-judge",
    )

    assert strong_assessment.passed is True
    assert strong_assessment.evidence_ids == ["ev-1"]
    assert weak_assessment.passed is False
    assert strong_assessment.weighted_score != weak_assessment.weighted_score
    assert controller.policy["expert_repair_reserved_instances"] == 6
    assert controller.policy["expert_candidate_pool_maximum"] == 10
    assert (
        controller.repair_archetype_for_assessment(weak_assessment)
        == "equipment_capability_image_repairer"
    )

    assessments = {"strong": strong_assessment, "weak": weak_assessment}
    decision = controller.portfolio_decision(
        ledger,
        objective_scores={
            key: controller.expert_objective_scores(value)
            for key, value in assessments.items()
        },
        expert_assessments=assessments,
    )
    assert decision.selected_hypothesis_ids == ["strong"]
    assert decision.rejected_hypothesis_ids == ["weak"]
    assert decision.quality_judge_passed is True


def test_dynamic_v2_portfolio_keeps_five_to_seven_with_four_direct_equipment() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id=f"h{index}",
            title=(
                f"自主无人战斗平台{index}"
                if index <= 4
                else f"支撑体系{index}"
            ),
            equipment_forms=(
                [f"模块化无人拦截平台{index}"]
                if index <= 4
                else [f"通信算法中台{index}"]
            ),
            score=0.9 - index / 100,
        )
        for index in range(1, 7)
    ]
    ledger = controller.create_ledger(hypotheses)

    decision = controller.portfolio_decision(ledger)
    selected = [
        item
        for item in ledger.hypotheses
        if item.hypothesis_id in set(decision.selected_hypothesis_ids)
    ]

    assert 5 <= len(selected) <= 7
    assert sum(controller.is_direct_combat_equipment(item) for item in selected) >= 4


def test_dynamic_portfolio_prefers_distinct_equipment_families_before_variants() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
        }
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id="low-alt-1",
            title="低空可消耗察打无人机目标续接",
            equipment_forms=["低空可消耗察打无人机"],
        ),
        _hypothesis(
            hypothesis_id="low-alt-2",
            title="低空无人携弹平台近距补打",
            equipment_forms=["低空无人携弹平台"],
        ),
        _hypothesis(
            hypothesis_id="anti-rad-1",
            title="反辐射巡飞弹药压制窗口",
            equipment_forms=["反辐射巡飞弹药"],
        ),
        _hypothesis(
            hypothesis_id="anti-rad-2",
            title="反辐射巡飞效应器猎歼干扰源",
            equipment_forms=["反辐射巡飞效应器"],
        ),
        _hypothesis(
            hypothesis_id="ground",
            title="地射远程精确制导导弹",
            equipment_forms=["地面发射远程精确制导导弹"],
        ),
        _hypothesis(
            hypothesis_id="air",
            title="空射隐身防区外巡航导弹",
            equipment_forms=["空射防区外巡航导弹"],
        ),
        _hypothesis(
            hypothesis_id="cruise",
            title="低成本巡航效应器族",
            equipment_forms=["低成本巡航弹药"],
        ),
    ]
    decision = controller.portfolio_decision(
        controller.create_ledger(hypotheses)
    )
    selected = [
        item for item in hypotheses
        if item.hypothesis_id in decision.selected_hypothesis_ids
    ]
    counts = controller.equipment_family_counts(selected)

    assert len(selected) >= 5
    assert len(counts) >= 5
    assert max(counts.values()) == 1


def test_dynamic_portfolio_replaces_duplicate_pareto_families_with_passed_alternatives() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
        }
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id="harop-a",
            title="抗失联HAROP类巡飞猎歼弹药",
            equipment_forms=["HAROP类长航时巡飞猎歼弹药"],
        ),
        _hypothesis(
            hypothesis_id="harop-b",
            title="批量可消耗低空巡飞猎歼弹药族",
            equipment_forms=["低空长航时巡飞猎歼弹药"],
        ),
        _hypothesis(
            hypothesis_id="barracuda-a",
            title="Barracuda-500M低空巡航攻击平台族",
            equipment_forms=["Barracuda-500M地面发射巡航攻击平台"],
        ),
        _hypothesis(
            hypothesis_id="barracuda-b",
            title="FAMM固定构型低成本巡航效应器族",
            equipment_forms=["FAMM低成本巡航效应器"],
        ),
        _hypothesis(
            hypothesis_id="prsm",
            title="PrSM类地射远程精确制导导弹",
            equipment_forms=["地面发射远程精确制导导弹"],
        ),
        _hypothesis(
            hypothesis_id="jassm",
            title="JASSM类空射防区外巡航导弹",
            equipment_forms=["空射隐身防区外巡航导弹"],
        ),
        _hypothesis(
            hypothesis_id="system-link",
            title="可消耗诱骗/电子压制无人效应器前导，反辐射巡飞猎歼装备接续",
            equipment_forms=["可消耗诱饵效应器", "反辐射巡飞猎歼装备"],
        ),
    ]
    scores = {
        "harop-a": {"quality": 0.95, "evidence": 0.80},
        "harop-b": {"quality": 0.80, "evidence": 0.95},
        "barracuda-a": {"quality": 0.94, "evidence": 0.81},
        "barracuda-b": {"quality": 0.81, "evidence": 0.94},
        "prsm": {"quality": 0.70, "evidence": 0.70},
        "jassm": {"quality": 0.69, "evidence": 0.69},
        "system-link": {"quality": 0.68, "evidence": 0.68},
    }

    decision = controller.portfolio_decision(
        controller.create_ledger(hypotheses),
        objective_scores=scores,
        expert_assessments={
            item.hypothesis_id: WinningExpertAssessment(
                assessment_id=f"assessment-{item.hypothesis_id}",
                hypothesis_id=item.hypothesis_id,
                blind_label=item.hypothesis_id,
                verdict="pass",
                passed=True,
                weighted_score=scores[item.hypothesis_id]["quality"],
                equipment_classification=(
                    "system_link"
                    if item.hypothesis_id == "system-link"
                    else "direct_combat"
                ),
            )
            for item in hypotheses
        },
    )
    selected = [
        item for item in hypotheses if item.hypothesis_id in decision.selected_hypothesis_ids
    ]
    direct_counts = controller.equipment_family_counts(
        [item for item in selected if item.hypothesis_id != "system-link"]
    )

    assert len(selected) == 5
    assert len(direct_counts) == 4
    assert max(direct_counts.values()) == 1
    assert {"prsm", "jassm", "system-link"} <= {
        item.hypothesis_id for item in selected
    }


def test_dynamic_coverage_does_not_stop_at_five_passes_with_only_four_direct_families() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
        }
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id="harop-a",
            title="HAROP类长航时巡飞猎歼弹药",
            equipment_forms=["HAROP类巡飞猎歼弹药"],
        ),
        _hypothesis(
            hypothesis_id="harop-b",
            title="批量低空巡飞猎歼弹药",
            equipment_forms=["低空巡飞猎歼弹药"],
        ),
        _hypothesis(
            hypothesis_id="barracuda-a",
            title="Barracuda-500M低成本巡航效应器",
            equipment_forms=["Barracuda-500M地面发射巡航效应器"],
        ),
        _hypothesis(
            hypothesis_id="barracuda-b",
            title="FAMM固定构型巡航效应器",
            equipment_forms=["FAMM低成本巡航效应器"],
        ),
        _hypothesis(
            hypothesis_id="prsm",
            title="PrSM类地射远程精确制导导弹",
            equipment_forms=["地面发射远程精确制导导弹"],
        ),
        _hypothesis(
            hypothesis_id="jassm",
            title="JASSM-ER类空射防区外巡航导弹",
            equipment_forms=["空射隐身防区外巡航导弹"],
        ),
        _hypothesis(
            hypothesis_id="system-link",
            title="诱骗压制效应器前导与反辐射巡飞猎歼体系联动",
            equipment_forms=["诱饵效应器", "反辐射巡飞猎歼装备"],
        ),
    ]

    def assessment(item: WinningHypothesis) -> WinningExpertAssessment:
        return WinningExpertAssessment(
            assessment_id=f"assessment-{item.hypothesis_id}",
            hypothesis_id=item.hypothesis_id,
            blind_label=item.hypothesis_id,
            verdict="pass",
            passed=True,
            weighted_score=0.82,
            equipment_classification=(
                "system_link"
                if item.hypothesis_id == "system-link"
                else "direct_combat"
            ),
        )

    assessments = {
        item.hypothesis_id: assessment(item) for item in hypotheses
    }
    ledger = controller.create_ledger(hypotheses)
    coverage = controller.passed_portfolio_coverage(ledger, assessments)

    assert coverage["passed_count"] == 7
    assert coverage["direct_combat_equipment_count"] == 6
    assert coverage["distinct_direct_equipment_family_count"] == 4
    assert coverage["preferred_distinct_direct_equipment"] == 5
    assert coverage["ready"] is False

    mald = _hypothesis(
        hypothesis_id="mald-j",
        title="MALD-J类固定构型空射可消耗诱饵/电子攻击效应器",
        equipment_forms=["MALD-J空射可消耗电子攻击效应器"],
    )
    hypotheses.append(mald)
    assessments[mald.hypothesis_id] = assessment(mald)
    coverage = controller.passed_portfolio_coverage(
        controller.create_ledger(hypotheses),
        assessments,
    )

    assert coverage["distinct_direct_equipment_family_count"] == 5
    assert coverage["ready"] is True


def test_harop_and_generic_loitering_munition_share_one_broad_family() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id="harop-cache",
            title="Harop类间歇链路目标证据缓存升级",
            equipment_forms=["固定构型长航时巡飞猎歼弹药"],
        ),
        _hypothesis(
            hypothesis_id="generic-loiter",
            title="分布式巡飞弹药目标再确认与补射",
            equipment_forms=["箱式发射长航时巡飞弹药"],
        ),
        _hypothesis(
            hypothesis_id="low-alt-carrier",
            title="批量可消耗低空无人携弹平台族",
            equipment_forms=["车载批量发射低空无人携弹平台"],
        ),
    ]

    counts = controller.equipment_family_counts(hypotheses)

    assert counts["loitering_munition"] == 2
    assert counts["low_altitude_unmanned_strike"] == 1
    assert len(counts) == 2


def test_dynamic_portfolio_prefers_five_distinct_direct_weapons_over_system_link() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
        }
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id="harop",
            title="HAROP类巡飞猎歼弹药",
            equipment_forms=["HAROP类巡飞猎歼弹药"],
        ),
        _hypothesis(
            hypothesis_id="barracuda",
            title="Barracuda-500M低成本巡航效应器",
            equipment_forms=["Barracuda-500M巡航效应器"],
        ),
        _hypothesis(
            hypothesis_id="prsm",
            title="PrSM类地射远程精确制导导弹",
            equipment_forms=["地面发射远程精确制导导弹"],
        ),
        _hypothesis(
            hypothesis_id="jassm",
            title="JASSM-ER类空射防区外巡航导弹",
            equipment_forms=["空射隐身防区外巡航导弹"],
        ),
        _hypothesis(
            hypothesis_id="mald-j",
            title="MALD-J类固定构型空射可消耗诱饵/电子攻击效应器",
            equipment_forms=["MALD-J空射可消耗电子攻击效应器"],
        ),
        _hypothesis(
            hypothesis_id="system-link",
            title="诱骗压制效应器前导与反辐射巡飞猎歼体系联动",
            equipment_forms=["诱饵效应器", "反辐射巡飞猎歼装备"],
        ),
    ]
    scores = {
        item.hypothesis_id: {
            "quality": 0.99 if item.hypothesis_id == "system-link" else 0.80,
            "evidence": 0.90,
        }
        for item in hypotheses
    }
    assessments = {
        item.hypothesis_id: WinningExpertAssessment(
            assessment_id=f"assessment-{item.hypothesis_id}",
            hypothesis_id=item.hypothesis_id,
            blind_label=item.hypothesis_id,
            verdict="pass",
            passed=True,
            weighted_score=scores[item.hypothesis_id]["quality"],
            equipment_classification=(
                "system_link"
                if item.hypothesis_id == "system-link"
                else "direct_combat"
            ),
        )
        for item in hypotheses
    }

    decision = controller.portfolio_decision(
        controller.create_ledger(hypotheses),
        objective_scores=scores,
        expert_assessments=assessments,
    )

    assert set(decision.selected_hypothesis_ids) == {
        "harop",
        "barracuda",
        "prsm",
        "jassm",
        "mald-j",
    }
    assert "system-link" not in decision.selected_hypothesis_ids


def test_dynamic_re_review_reuses_unassessed_ledger_breadth_and_upgrade() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "expert_candidate_pool_maximum": 10,
        }
    )
    passed = [
        _hypothesis(
            hypothesis_id=f"loiter-{index}",
            title=f"HAROP类反舰巡飞猎歼弹药{index}",
            equipment_forms=["HAROP类反舰巡飞猎歼弹药"],
        )
        for index in range(1, 4)
    ]
    unassessed = [
        _hypothesis(
            hypothesis_id="ground-upgrade",
            title="地射远程精确制导导弹断链重捕获",
            equipment_forms=["地面发射远程精确制导导弹"],
            implementation_path="upgrade",
        ),
        _hypothesis(
            hypothesis_id="air-missile",
            title="空射防区外反舰巡航导弹自主复核",
            equipment_forms=["空射防区外反舰巡航导弹"],
        ),
        _hypothesis(
            hypothesis_id="mald",
            title="MALD-J类可消耗电子攻击效应器",
            equipment_forms=["MALD-J空射可消耗电子攻击效应器"],
        ),
        _hypothesis(
            hypothesis_id="low-alt",
            title="低空可消耗反舰无人携弹平台",
            equipment_forms=["低空可消耗反舰无人携弹平台"],
        ),
        _hypothesis(
            hypothesis_id="maritime",
            title="舰射远程反舰导弹自主续接",
            equipment_forms=["舰射远程反舰导弹"],
        ),
    ]
    assessments = {
        item.hypothesis_id: WinningExpertAssessment(
            assessment_id=f"assessment-{item.hypothesis_id}",
            hypothesis_id=item.hypothesis_id,
            blind_label=item.hypothesis_id,
            verdict="pass",
            passed=True,
            weighted_score=0.82,
            equipment_classification="unmanned_combat",
        )
        for item in passed
    }

    selected = controller.select_unassessed_portfolio_candidates(
        controller.create_ledger([*passed, *unassessed]),
        assessments,
        maximum=5,
    )

    assert len(selected) == 5
    assert selected[0] == "ground-upgrade"
    assert {"air-missile", "mald", "low-alt", "maritime"} <= set(selected)


def test_dynamic_portfolio_keeps_one_passed_upgrade_when_available() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
        }
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id=f"new-{index}",
            title=f"无人远程精确打击装备{index}",
            equipment_forms=[f"无人远程精确打击导弹{index}"],
            score=0.95 - index / 100,
        )
        for index in range(1, 6)
    ]
    hypotheses.append(
        _hypothesis(
            hypothesis_id="upgrade",
            title="地射反舰导弹断链重捕获升级",
            equipment_forms=["地面发射远程反舰导弹"],
            implementation_path="upgrade",
            score=0.70,
        )
    )
    assessments = {
        item.hypothesis_id: WinningExpertAssessment(
            assessment_id=f"assessment-{item.hypothesis_id}",
            hypothesis_id=item.hypothesis_id,
            blind_label=item.hypothesis_id,
            verdict="pass",
            passed=True,
            weighted_score=item.score,
            equipment_classification=(
                "upgrade" if item.hypothesis_id == "upgrade" else "direct_combat"
            ),
        )
        for item in hypotheses
    }

    decision = controller.portfolio_decision(
        controller.create_ledger(hypotheses),
        objective_scores={
            item.hypothesis_id: {"quality": item.score, "evidence": item.score}
            for item in hypotheses
        },
        expert_assessments=assessments,
    )

    assert len(decision.selected_hypothesis_ids) == 5
    assert "upgrade" in decision.selected_hypothesis_ids
    assert decision.quality_judge_passed is True


def test_core_schedule_parallelizes_only_dependency_safe_s_agents() -> None:
    controller = WinningSwarmController({"enabled": True})

    schedule = controller.plan_core_schedule(
        active_steps=[1, 2, 3, 4, 5, 6],
        step_modes={step: "deep" for step in range(1, 7)},
        physical_cohorts=[(3, 4, 5)],
    )

    assert schedule["logical_waves"] == [
        {"wave": 1, "core_agents": ["S1", "S2"], "parallel": True},
        {"wave": 2, "core_agents": ["S3"], "parallel": False},
        {"wave": 3, "core_agents": ["S4"], "parallel": False},
        {"wave": 4, "core_agents": ["S5"], "parallel": False},
        {"wave": 5, "core_agents": ["S6"], "parallel": False},
    ]
    assert schedule["physical_cohorts"] == [["S3", "S4", "S5"]]
    assert schedule["dependencies"]["S6"] == ["S4", "S5"]
    assert schedule["merge_strategy"] == "isolated_result_then_topological_commit"

    branch_schedule = controller.plan_core_schedule(
        active_steps=[3, 4, 6],
        step_modes={1: "skip", 2: "skip", 3: "deep", 4: "deep", 5: "skip", 6: "deep"},
    )
    assert [row["core_agents"] for row in branch_schedule["logical_waves"]] == [
        ["S3"],
        ["S4"],
        ["S6"],
    ]

    contracted_dependencies = controller.core_dependencies_from_dag(
        {"S1": ["combat_scenario"], "S2": ["S1"], "S3": ["S2"]}
    )
    contracted_schedule = controller.plan_core_schedule(
        active_steps=[1, 2, 3],
        dependency_map=contracted_dependencies,
    )
    assert [row["core_agents"] for row in contracted_schedule["logical_waves"]] == [
        ["S1"],
        ["S2"],
        ["S3"],
    ]


def test_specialist_batches_enforce_candidate_merge_conflict_and_concurrency() -> None:
    controller = WinningSwarmController({"enabled": True, "max_concurrency": 2})

    def task(task_id: str, hypothesis_id: str, merge_target: str) -> SpecialistTask:
        return SpecialistTask(
            task_id=task_id,
            agent_instance_id=f"agent-{task_id}",
            archetype="evidence_verifier",
            display_name=task_id,
            wave=2,
            purpose="test",
            merge_target=merge_target,
            hypothesis_id=hypothesis_id,
        )

    batches = controller.conflict_free_batches(
        [
            task("t1", "h1", "S5"),
            task("t2", "h1", "S5"),
            task("t3", "h1", "S4"),
            task("t4", "h2", "S5"),
        ]
    )

    assert all(len(batch) <= 2 for batch in batches)
    assert any({item.task_id for item in batch} == {"t1", "t3"} for batch in batches)
    assert not any(
        {"t1", "t2"} <= {item.task_id for item in batch}
        for batch in batches
    )


def test_dynamic_specialist_contract_accepts_twelve_and_binds_hypothesis() -> None:
    rows = [
        {
            "display_name": f"specialist-{index}",
            "purpose": "补充一个边界清晰的质量残差",
            "trigger_gap": "evidence_insufficient",
            "merge_target": "S5",
        }
        for index in range(13)
    ]

    normalized = normalize_dynamic_subagents(
        rows,
        available_skills={},
        available_knowledge_pack_ids=[],
    )

    assert len(normalized) == 12
    assert all(item["hypothesis_id"] for item in normalized)
    assert all(item["allow_child_spawn"] is False for item in normalized)


def test_initial_plan_is_non_recursive_and_targeted_plan_respects_remaining_budget() -> None:
    controller = WinningSwarmController({"enabled": True})
    plan = controller.plan_initial(topic="test", execution_profile_id="swarm_quality_v1")

    assert len(plan.tasks) == 4
    assert {task.wave for task in plan.tasks} == {1}
    assert all(task.allow_child_spawn is False for task in plan.tasks)

    hypothesis = _hypothesis(
        residuals=["evidence_insufficient", "counter_adaptation_unresolved"]
    )
    gate = controller.evaluate_gate(
        replace(hypothesis, evidence_ids=[], evidence_boundary=""),
        stage="breadth",
    )
    targeted = controller.plan_targeted(
        [hypothesis],
        [gate],
        topic="test",
        used_instances=11,
    )

    assert len(targeted) == 1
    assert targeted[0].wave == 2
    assert targeted[0].allow_child_spawn is False


def test_dependency_scheduler_prunes_recursive_or_failed_dependency_tasks() -> None:
    controller = WinningSwarmController({"enabled": True})
    source = _hypothesis(source_task_ids=["task-source"])
    task = controller.plan_targeted(
        [replace(source, residuals=["evidence_insufficient"])],
        [
            controller.evaluate_gate(
                replace(
                    source,
                    evidence_ids=[],
                    evidence_boundary="",
                ),
                stage="breadth",
            )
        ],
        topic="test",
        used_instances=4,
    )[0]

    ready, pruned = controller.ready_tasks(
        [task],
        completed_task_ids=set(),
        failed_task_ids={"task-source"},
    )
    assert ready == []
    assert pruned == [task]

    recursive = replace(task, allow_child_spawn=True, depends_on=[])
    ready, pruned = controller.ready_tasks(
        [recursive], completed_task_ids=set()
    )
    assert ready == []
    assert pruned == [recursive]


def test_contribution_requires_exact_hypothesis_and_merge_target_and_cleans_evidence() -> None:
    controller = WinningSwarmController({"enabled": True})
    hypothesis = _hypothesis(residuals=["evidence_insufficient"])
    task = controller.plan_targeted(
        [hypothesis],
        [
            controller.evaluate_gate(
                replace(hypothesis, evidence_ids=[], evidence_boundary=""),
                stage="breadth",
            )
        ],
        topic="test",
        used_instances=4,
    )[0]
    payload = {
        "hypothesis_id": task.hypothesis_id,
        "merge_target": task.merge_target,
        "findings": ["补充公开试验节点并明确证据不支持完整作战效能"],
        "evidence_ids": ["ev-1", "invented-id"],
        "evidence_boundary": "仅支持组成技术存在",
        "residuals_resolved": ["evidence_insufficient"],
        "incremental_quality": 0.08,
    }

    contribution = controller.contribution_from_mapping(
        payload,
        task=task,
        valid_evidence_ids={"ev-1"},
    )
    assert contribution.accepted is True
    assert contribution.evidence_ids == ["ev-1"]
    updated = controller.apply_contribution(hypothesis, contribution)
    assert task.task_id in updated.source_task_ids
    assert task.merge_target in updated.merge_targets
    assert controller.contribution_projection(
        contribution,
        hypothesis_id=task.hypothesis_id,
        merge_target=task.merge_target,
    ) is not None
    assert controller.contribution_projection(
        contribution,
        hypothesis_id=task.hypothesis_id,
        merge_target="S6",
    ) is None

    with pytest.raises(ValueError, match="merge boundary"):
        controller.contribution_from_mapping(
            {**payload, "merge_target": "S6"},
            task=task,
            valid_evidence_ids={"ev-1"},
        )


def test_w2_retains_structured_query_weapon_delta_without_generic_findings() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "minimum_expected_gain": 0.05,
        }
    )
    task = SpecialistTask(
        task_id="w2-query-weapon",
        agent_instance_id="w2-specialist",
        archetype="mechanism_stress_tester",
        display_name="W2定向挑战",
        wave=2,
        purpose="challenge one query-specific weapon",
        merge_target="S4",
        hypothesis_id="h-query",
        expected_quality_gain=0.05,
    )
    contribution = controller.contribution_from_mapping(
        {
            "hypothesis_id": "h-query",
            "merge_target": "S4",
            "findings": [],
            "equipment_forms": ["潜射低特征多模反舰巡航弹药"],
            "direct_military_effects": ["重创或击沉高速机动水面舰艇"],
            "mechanism_chain_updates": ["水下隐蔽接近后多向发射", "末段多模再捕获"],
            "novelty_delta": "把单向空射突防改为跨域多向末段夹击",
            "evidence_ids": ["ev-anti-ship"],
            "evidence_boundary": "公开证据只支撑相邻装备基线，不证明拟议构型效能",
            "failure_boundaries": ["末段无法形成可靠目标证据时拒打"],
            "incremental_quality": 0.01,
            "recommendation": "retain",
        },
        task=task,
        valid_evidence_ids={"ev-anti-ship"},
    )

    assert contribution.accepted is True
    assert contribution.incremental_quality == 0.05
    assert contribution.findings == []
    assert contribution.equipment_forms == ["潜射低特征多模反舰巡航弹药"]


def test_candidate_dedup_final_gate_and_unsupported_precision_rejection() -> None:
    controller = WinningSwarmController({"enabled": True})
    first = _hypothesis(hypothesis_id="h1", score=0.9)
    duplicate = _hypothesis(hypothesis_id="h2", score=0.8)
    unique, merges = controller.deduplicate_hypotheses([duplicate, first])

    assert [item.hypothesis_id for item in unique] == ["h1"]
    assert merges[0]["source_hypothesis_id"] == "h2"

    finalists, rejected, gates = controller.select_finalists([first])
    assert [item.hypothesis_id for item in finalists] == ["h1"]
    assert rejected == []
    assert gates[0].passed is True

    unsupported = _hypothesis(
        hypothesis_id="h3",
        evidence_ids=[],
        mechanism_chain=["公开材料未支撑但声称效能提升35%"],
    )
    gate = controller.evaluate_gate(unsupported, stage="final")
    assert gate.passed is False
    assert "unsupported_precision" in gate.residuals


def test_finalist_capacity_rejection_has_auditable_reason() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "finalist_maximum": 4, "finalist_minimum": 2}
    )
    candidates = [
        _hypothesis(hypothesis_id=f"h{index}")
        for index in range(1, 6)
    ]

    finalists, rejected, gates = controller.select_finalists(candidates)
    gate_by_id = {item.hypothesis_id: item for item in gates}

    assert len(finalists) == 4
    assert len(rejected) == 1
    reason = gate_by_id[rejected[0].hypothesis_id].rejection_reasons
    assert reason
    assert "候选组合容量上限" in reason[0]


def test_semantic_hypothesis_match_recovers_obsolete_candidate_id() -> None:
    controller = WinningSwarmController({"enabled": True})
    obsolete = _hypothesis(hypothesis_id="obsolete", score=0.8)
    canonical = replace(
        obsolete,
        hypothesis_id="canonical",
        score=0.9,
        evidence_ids=["ev-1", "ev-2"],
    )
    unrelated = replace(
        _hypothesis(hypothesis_id="unrelated"),
        title="完全不同的保障网络",
        mechanism_chain=["保障节点汇聚库存信息"],
        equipment_forms=["保障信息系统"],
    )

    assert controller.semantic_hypothesis_match(
        obsolete,
        [unrelated, canonical],
    ) == "canonical"


def test_final_gate_requires_structured_system_interfaces() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(_hypothesis(), system_interfaces=[]),
        stage="final",
    )

    assert gate.passed is False
    assert "system_interfaces_missing" in gate.residuals


def test_dynamic_final_gate_requires_explicit_project_function() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(_hypothesis(), project_function=""),
        stage="final",
    )

    assert gate.passed is False
    assert "project_function_missing" in gate.residuals


def test_dynamic_final_gate_rejects_mixed_public_weapon_families() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(
            _hypothesis(),
            title="批量可消耗低空无人携弹压制平台族",
            equipment_forms=[
                "MALD类诱骗压制型；AARGM-ER反辐射型；Harop巡飞猎歼型"
            ],
            evidence_ids=["ev-weapon_equipment-web-mald"],
        ),
        stage="final",
    )

    assert gate.passed is False
    assert "mixed_primary_equipment_families" in gate.residuals


def test_dynamic_final_gate_requires_weapon_object_evidence_for_direct_weapon() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(
            _hypothesis(),
            title="长航时反舰巡飞弹药",
            equipment_forms=["长航时反舰巡飞弹药"],
            evidence_ids=["ev-operational_employment-web-generic"],
        ),
        stage="final",
    )

    assert gate.passed is False
    assert "equipment_object_evidence_missing" in gate.residuals


def test_expert_repairs_prioritize_passed_system_links_for_combat_quota() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "expert_repair_max_candidates": 3,
        }
    )

    def assessment(
        hypothesis_id: str,
        *,
        verdict: str,
        classification: str,
        score: float,
    ):
        hypothesis = replace(_hypothesis(), hypothesis_id=hypothesis_id)
        return controller.expert_assessment_from_mapping(
            {
                "verdict": verdict,
                "dimension_scores": {
                    "domain_relevance": score,
                    "equipment_capability_fit": score,
                    "innovation": score,
                    "military_value": score,
                    "causal_coherence": score,
                    "credibility": score,
                    "engineering_feasibility": score,
                    "robustness": score,
                },
                "equipment_classification": classification,
                "evidence_ids": ["ev-1"],
            },
            hypothesis=hypothesis,
            blind_label=hypothesis_id,
            valid_evidence_ids={"ev-1"},
            session_ref="session",
        )

    rows = {
        item.hypothesis_id: item
        for item in [
            assessment("system-1", verdict="pass", classification="system_link", score=0.86),
            assessment("system-2", verdict="pass", classification="system_link", score=0.84),
            assessment("system-3", verdict="pass", classification="support_only", score=0.82),
            assessment("revise-1", verdict="revise", classification="upgrade", score=0.80),
        ]
    }

    selected = controller.select_expert_repair_assessments(rows)

    assert [item.hypothesis_id for item in selected] == [
        "system-1",
        "system-2",
        "system-3",
    ]
    assert controller.is_direct_combat_equipment(
        _hypothesis(), rows["system-1"]
    ) is False


def test_expert_repairs_prioritize_failed_direct_images_before_passed_links() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "expert_repair_max_candidates": 3,
        }
    )

    def assessment(hypothesis_id: str, verdict: str, classification: str, score: float):
        hypothesis = replace(_hypothesis(), hypothesis_id=hypothesis_id)
        return controller.expert_assessment_from_mapping(
            {
                "verdict": verdict,
                "dimension_scores": {
                    dimension: score
                    for dimension in (
                        "domain_relevance",
                        "equipment_capability_fit",
                        "innovation",
                        "military_value",
                        "causal_coherence",
                        "credibility",
                        "engineering_feasibility",
                        "robustness",
                    )
                },
                "equipment_classification": classification,
                "evidence_ids": ["ev-1"],
            },
            hypothesis=hypothesis,
            blind_label=hypothesis_id,
            valid_evidence_ids={"ev-1"},
            session_ref="session",
        )

    rows = {
        item.hypothesis_id: item
        for item in (
            assessment("link-pass", "pass", "system_link", 0.90),
            assessment("direct-revise", "revise", "direct_combat", 0.80),
            assessment("unmanned-revise", "revise", "unmanned_combat", 0.78),
        )
    }

    selected = controller.select_expert_repair_assessments(rows)

    assert [item.hypothesis_id for item in selected] == [
        "direct-revise",
        "unmanned-revise",
        "link-pass",
    ]


def test_expert_repairs_prioritize_missing_direct_equipment_family() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "expert_repair_max_candidates": 1,
        }
    )
    passed = _hypothesis(
        hypothesis_id="passed-loitering",
        title="反辐射巡飞弹药",
        equipment_forms=["反辐射巡飞弹药"],
    )
    duplicate = _hypothesis(
        hypothesis_id="duplicate-loitering",
        title="反辐射巡飞弹关机再捕获",
        equipment_forms=["反辐射巡飞弹药"],
    )
    missing = _hypothesis(
        hypothesis_id="missing-air-missile",
        title="空射防区外反舰导弹再捕获",
        equipment_forms=["空射防区外反舰导弹"],
    )

    def row(
        hypothesis: WinningHypothesis,
        *,
        verdict: str,
        score: float,
    ) -> WinningExpertAssessment:
        return controller.expert_assessment_from_mapping(
            {
                "verdict": verdict,
                "dimension_scores": {
                    dimension: score
                    for dimension in (
                        "domain_relevance",
                        "equipment_capability_fit",
                        "innovation",
                        "military_value",
                        "causal_coherence",
                        "credibility",
                        "engineering_feasibility",
                        "robustness",
                    )
                },
                "equipment_classification": "direct_combat",
                "evidence_ids": ["ev-1"],
            },
            hypothesis=hypothesis,
            blind_label=hypothesis.hypothesis_id,
            valid_evidence_ids={"ev-1"},
            session_ref="session",
        )

    assessments = {
        "passed-loitering": row(passed, verdict="pass", score=0.84),
        "duplicate-loitering": row(duplicate, verdict="revise", score=0.82),
        "missing-air-missile": row(missing, verdict="revise", score=0.77),
    }
    hypotheses = {
        item.hypothesis_id: item for item in (passed, duplicate, missing)
    }

    selected = controller.select_expert_repair_assessments(
        assessments,
        hypotheses=hypotheses,
    )

    assert [item.hypothesis_id for item in selected] == [
        "missing-air-missile"
    ]


def test_equipment_family_uses_primary_weapon_before_companion_weapon() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    anti_ship = _hypothesis(
        title="发射后自主再捕获反舰导弹",
        equipment_forms=[
            "具备多模导引的远程反舰导弹",
            "与反辐射压制弹药成组使用的反舰打击弹药族",
        ],
    )

    assert controller.equipment_family_signature(anti_ship) == (
        "guided_missile_or_munition"
    )

    prsm = _hypothesis(
        title="PrSM Increment 2多模末制导验证型",
        equipment_forms=["HIMARS兼容的PrSM陆基远程反舰试验弹"],
    )
    assert controller.equipment_family_signature(prsm) == (
        "ground_launched_precision_missile"
    )


def test_promotion_requires_ten_runs_seventy_percent_and_no_hard_failures() -> None:
    controller = WinningSwarmController({"enabled": True})

    assert controller.promotion_candidate(
        archetype="evidence_verifier",
        eligible_runs=9,
        positive_increment_runs=9,
        evidence_hard_failures=0,
        permission_hard_failures=0,
    ) is None
    assert controller.promotion_candidate(
        archetype="evidence_verifier",
        eligible_runs=10,
        positive_increment_runs=7,
        evidence_hard_failures=1,
        permission_hard_failures=0,
    ) is None

    record = controller.promotion_candidate(
        archetype="evidence_verifier",
        eligible_runs=10,
        positive_increment_runs=7,
        evidence_hard_failures=0,
        permission_hard_failures=0,
    )
    assert record is not None
    assert record.status == "offline_evaluation_pending"
    assert record.human_approved is False
