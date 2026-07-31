from __future__ import annotations

from dataclasses import replace

import pytest

from equipment_deep_research.domain.models import (
    SpecialistTask,
    WinningContribution,
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


def test_dynamic_v2_profile_enables_six_concurrency_and_sixteen_instance_budget() -> None:
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
    assert blueprint["runtime_budgets"]["maximum_quality_judge_model_calls"] == 2
    assert blueprint["runtime_budgets"]["maximum_swarm_model_calls"] == 16
    assert blueprint["winning_swarm_policy"]["max_dynamic_instances"] == 16
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
    graph = controller.build_mission_graph(topic="test mission")

    assert 8 <= len(graph.agent_instances) <= 16
    assert len(graph.agent_instances) == 12
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
