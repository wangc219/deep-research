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
    QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION,
    WinningSwarmController,
    normalize_weapon_candidate_title,
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
        "direct_military_effects": [
            "持续物理拦截饱和来袭目标",
            "缩短受威胁方向的防御空窗",
        ],
        "equipment_forms": ["模块化无人拦截平台"],
        "project_function": "防空分队在饱和来袭与节点损耗条件下依靠模块化无人拦截平台持续实施物理拦截并续接区域拒止任务。",
        "system_interfaces": ["平台任务总线", "火控授权接口", "战术数据链接口"],
        "novelty_delta": "从集中式高价值节点转向可补充、可降级运行的分布式装备族",
        "frontier_principle": "自主分布式任务接续与可消耗节点协同",
        "technology_discontinuity": "集中式节点的常规扩容无法在节点损耗后重建分布式交战权",
        "technology_horizon": "5-10年",
        "engineering_bottleneck": "弱网条件下的局部授权一致性与误击控制",
        "original_paradigm": "依靠少量高价值集中式节点维持区域拦截",
        "disruptive_shift": "把拦截权和任务接续能力分散到可损耗、可补充的自治节点",
        "independence_thesis": "改变交战权与战损接续关系，而非增加现役拦截节点数量",
        "naming_rationale": "名称对应分布式部署、低成本补充、直接拦截主装备与区域拒止战果",
        "decisive_advantage_thesis": "节点损耗后仍能接续物理拦截，使对手饱和攻击无法按预期打开防御空窗",
        "cross_query_distinction": "若目标不是饱和来袭或任务不是区域拒止，节点构型、拦截机理和名称均须重做",
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
    assert blueprint["winning_swarm_policy"]["foresight_first_enabled"] is True
    assert blueprint["winning_swarm_policy"]["frontier_evidence_relaxation"] is True
    assert blueprint["winning_swarm_policy"]["expert_judge_minimum_score"] == 0.68
    assert (
        blueprint["winning_swarm_policy"]["frontier_final_gate_minimum_score"] == 0.62
    )
    assert resolve_execution_profile("swarm_quality_v1") == profile


def test_dynamic_v2_profile_prioritizes_frontloaded_s3_capacity() -> None:
    profile = winning_swarm_dynamic_v2_profile()
    blueprint = apply_execution_profile_to_blueprint(
        build_discovery_blueprint(ResearchProblem("dynamic graph")), profile
    )

    assert profile.status == "challenger"
    assert profile.parent_profile_id == "swarm_quality_v1"
    assert resolve_execution_profile("winning_swarm_dynamic_v2") == profile
    assert blueprint["winning_swarm_policy"]["policy_id"] == "winning_swarm_dynamic_v2"
    assert blueprint["winning_swarm_policy"]["expert_judge_enabled"] is False
    assert blueprint["winning_swarm_policy"]["expert_judge_required"] is False
    assert blueprint["winning_swarm_policy"]["finalist_minimum"] == 2
    assert blueprint["winning_swarm_policy"]["finalist_maximum"] == 7
    assert blueprint["winning_swarm_policy"]["mission_graph_target_instances"] == 15
    assert blueprint["winning_swarm_policy"]["s3_winning_thesis_capacity"] == 8
    assert blueprint["winning_swarm_policy"]["expert_candidate_pool_maximum"] == 0
    assert blueprint["winning_swarm_policy"]["expert_repair_reserved_instances"] == 0
    assert blueprint["winning_swarm_policy"]["expert_repair_max_candidates"] == 0
    assert set(blueprint["winning_swarm_policy"]["archetypes"]) == {
        "weak_signal_scout",
        "disruptive_mechanism_generator",
        "innovative_equipment_dimension_generator",
        "independent_portfolio_reviewer",
    }
    assert blueprint["winning_swarm_policy"]["s3_empty_reallocation_max"] == 2
    assert blueprint["runtime_budgets"]["maximum_quality_judge_model_calls"] == 0
    assert blueprint["runtime_budgets"]["maximum_swarm_model_calls"] == 36
    assert blueprint["runtime_budgets"]["codex_concurrency"] == 6
    assert blueprint["runtime_budgets"]["s6_codex_concurrency"] == 6
    assert blueprint["execution_contract"]["codex_concurrency"] == 6
    assert blueprint["minimum_business_agents"] == 2
    assert blueprint["maximum_business_agents"] == 3
    assert blueprint["winning_swarm_policy"]["max_dynamic_instances"] == 21
    assert blueprint["winning_swarm_policy"]["mission_graph_max_instances"] == 21
    assert blueprint["winning_swarm_policy"]["max_concurrency"] == 6
    assert blueprint["winning_swarm_policy"]["mission_graph_min_instances"] == 8
    assert blueprint["winning_swarm_policy"]["foresight_first_enabled"] is True
    assert blueprint["winning_swarm_policy"]["frontier_evidence_relaxation"] is True
    assert (
        blueprint["winning_swarm_policy"]["frontier_expert_judge_minimum_score"] == 0.66
    )
    assert (
        blueprint["winning_swarm_policy"]["same_family_minimum_independent_axes"] == 2
    )


def test_frontier_candidate_metadata_survives_in_auditable_fields() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    task = SpecialistTask(
        task_id="frontier-task",
        agent_instance_id="frontier-agent",
        archetype="weak_signal_scout",
        display_name="前沿补全",
        wave=1,
        purpose="形成前沿候选",
        merge_target="S3",
    )
    candidate = controller.hypothesis_from_mapping(
        {
            "title": "非常规测量末制导微型歼灭弹",
            "nearest_public_baseline": "常规射频或光电制导微型弹药",
            "changed_confrontation_variable": "从依赖常规可观测特征转为利用新的目标物理响应",
            "mechanism_chain": ["获取非常规物理响应", "末段辨真", "精确毁伤"],
            "direct_military_effects": ["在欺骗遮蔽下完成真目标精确毁伤"],
            "equipment_forms": ["非常规测量制导微型精确毁伤弹"],
            "project_function": "打击单元在常规探测受骗时依靠该弹完成末段辨真与精确毁伤。",
            "novelty_delta": "把目标可观测性从常规频段扩展到新的物理响应",
            "frontier_principle": "非常规目标物理响应测量",
            "technology_discontinuity": "常规算法升级无法恢复不存在的可观测信息",
            "technology_horizon": "5-10年",
            "engineering_bottleneck": "弹载尺度下的信噪比和环境鲁棒性",
            "naming_rationale": "名称对应测量原理、末制导用途与微型精确毁伤主体",
            "decisive_advantage_thesis": "在常规感知链被欺骗时保留独立末段毁伤能力",
            "cross_query_distinction": "目标物理响应变化后传感构型与名称均需重做",
            "system_interfaces": ["弹载传感器", "末制导控制接口"],
            "adversary_adaptations": ["目标采用物理特征屏蔽"],
            "failure_boundaries": ["信噪比不足时判退"],
            "trl_constraints": ["需完成对抗环境样机试验"],
            "cost_constraints": ["单发成本需与常规微型弹药比较"],
            "industrial_constraints": ["关键传感器需可批量一致制造"],
            "cross_scenario_results": ["仅在对应目标物理响应存在时成立"],
            "validation_plan": ["与常规末制导方案进行盲测对照"],
            "implementation_path": "new",
        },
        task=task,
        valid_evidence_ids=set(),
        ordinal=1,
    )

    assert "前沿原理：非常规目标物理响应测量" in candidate.novelty_delta
    assert "不可由常规升级吸收" in candidate.novelty_delta
    assert (
        candidate.trl_constraints[0] == "关键工程瓶颈：弹载尺度下的信噪比和环境鲁棒性"
    )
    assert "前瞻窗口：5-10年" in candidate.trl_constraints


def test_frontloaded_diagnostics_record_missing_paradigm_without_rejecting() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )

    gate = controller.evaluate_gate(
        replace(
            _hypothesis(),
            original_paradigm="",
            disruptive_shift="",
            independence_thesis="",
        ),
        stage="final",
    )

    assert gate.passed is True
    assert "paradigm_shift_unproven" in gate.residuals


def test_frontloaded_diagnostics_record_discontinuity_gap_without_rejecting() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )

    gate = controller.evaluate_gate(
        replace(
            _hypothesis(),
            frontier_principle="",
            technology_discontinuity="",
            technology_horizon="",
            engineering_bottleneck="",
        ),
        stage="final",
    )

    assert gate.passed is True
    assert "frontier_discontinuity_unproven" in gate.residuals


@pytest.mark.parametrize(
    ("raw", "forms", "expected"),
    [
        (
            "S3-红队保留：抗诱骗闭环紧凑打一体游荡弹药分队",
            ["背负、车载或舰岸箱式发射的可消耗巡飞弹药"],
            "抗诱骗闭环紧凑打一体游荡弹药分队",
        ),
        (
            "前沿小单元侦打评一体巡飞毁伤弹：压缩发现、打击、评估、补击闭环",
            ["背负发射巡飞毁伤弹"],
            "前沿小单元侦打评一体巡飞毁伤弹",
        ),
        (
            "S3_颠覆分支：节点贴身可消耗空中雷区拦截器",
            ["箱式发射的低成本空中拦截弹"],
            "节点贴身可消耗空中雷区拦截器",
        ),
    ],
)
def test_weapon_candidate_title_removes_stage_labels_and_keeps_weapon_identity(
    raw: str,
    forms: list[str],
    expected: str,
) -> None:
    title = normalize_weapon_candidate_title(raw, forms)

    assert title == expected
    assert "S3" not in title


def test_weapon_candidate_title_preserves_query_specific_codename_and_identity() -> (
    None
):
    title = normalize_weapon_candidate_title(
        "S3-候选A：“影袭”低特征诱骗-压制-反辐射巡飞攻击弹",
        ["可消耗低特征诱骗-压制-反辐射巡飞攻击弹"],
    )

    assert title == "“影袭”低特征诱骗-压制-反辐射巡飞攻击弹"


def test_weapon_candidate_title_does_not_replace_agent_name_from_equipment_form() -> (
    None
):
    title = normalize_weapon_candidate_title(
        "内置效应器",
        ["伴随电子压制无人攻击机"],
    )

    assert title == "内置效应器"


def test_weapon_candidate_title_removes_form_and_interface_metadata() -> None:
    title = normalize_weapon_candidate_title(
        "空射可消耗无人诱饵弹 · 接口形态：任务前画像装订接口、与载机释放规划接口",
        ["形态：空射可消耗无人诱饵弹 · 接口形态：任务前画像装订接口"],
    )

    assert title == "空射可消耗无人诱饵弹"


def test_weapon_candidate_title_strips_query_model_metatalk() -> None:
    title = normalize_weapon_candidate_title(
        "Query相关型号：低特征反辐射巡飞攻击弹",
        ["低特征反辐射巡飞攻击弹"],
    )

    assert title == "低特征反辐射巡飞攻击弹"


@pytest.mark.parametrize(
    "title",
    [
        "低空巡航对陆精打武器 · 内嵌INS、地形相关纠偏、末段景象匹配和源冲突拒绝逻辑的一体化巡航弹",
        "现役远程火箭弹加改型 · 配套地面装订、标定和健康检查设备作为保障接口，不构成候选主体",
    ],
)
def test_descriptive_component_inventory_is_preserved_without_local_gate(
    title: str,
) -> None:
    assert normalize_weapon_candidate_title(title, []) == title


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


def test_dynamic_v2_mission_graph_frontloads_quality_into_s5_before_s6_cards() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    graph = controller.build_mission_graph(
        topic="test mission",
        target_instances=15,
    )

    assert len(graph.agent_instances) == 13
    assert graph.maximum_concurrency == 6
    assert set(graph.s_node_seeds) == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert all(graph.s_node_seeds[node] for node in ("S1", "S2", "S3", "S4", "S5"))
    assert graph.s_node_seeds["S6"] == []
    assert len(graph.waves[0]) >= 4
    assert all(
        instance.allow_child_spawn is False for instance in graph.agent_instances
    )
    assert all(
        "当前唯一任务主题" in contract.purpose for contract in graph.role_contracts
    )
    assert all(
        "打击、歼灭、毁伤、杀伤" in contract.purpose
        for contract in graph.role_contracts
    )
    assert all(
        any("跨Query替换自检" in item for item in contract.methodology)
        for contract in graph.role_contracts
    )
    contracts_by_node = {
        node: [item for item in graph.role_contracts if item.mission_node == node]
        for node in ("S1", "S2", "S3", "S4", "S5", "S6")
    }
    assert all(
        any("不创建最终装备卡" in item for item in contract.methodology)
        for node in ("S1", "S2")
        for contract in contracts_by_node[node]
    )
    assert all(
        any("创建入口" in item for item in contract.methodology)
        for node in ("S3", "S4")
        for contract in contracts_by_node[node]
    )
    assert all(
        any("轻型创造会话" in item for item in contract.methodology)
        for node in ("S3", "S4")
        for contract in contracts_by_node[node]
    )
    assert all(
        any("retain、merge或reject" in item for item in contract.methodology)
        for contract in contracts_by_node["S5"]
    )
    assert not contracts_by_node["S6"]
    assert all(
        not any("至少两项" in item or "最低分" in item for item in contract.quality_gates)
        for contract in graph.role_contracts
    )
    by_archetype = {item.archetype: item for item in graph.agent_instances}
    reviewer = by_archetype["independent_portfolio_reviewer"]
    assert "equipment_realization_architect" not in by_archetype
    assert "direct_combat_equipment_generator" not in by_archetype
    assert "remote_precision_munition_generator" not in by_archetype
    assert "mass_scalable_combat_family_generator" not in by_archetype
    assert "validation_experiment_designer" not in by_archetype
    assert "trl_cost_industrial_auditor" not in by_archetype
    assert "evidence_verifier" not in by_archetype
    assert sum(item.mission_node == "S3" for item in graph.agent_instances) == 4
    assert sum(item.mission_node == "S4" for item in graph.agent_instances) == 4
    assert sum(item.mission_node == "S5" for item in graph.agent_instances) == 1
    assert reviewer.depends_on == []
    assert reviewer.wave == 1
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


def test_dynamic_v2_target_instances_controls_creator_capacity() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )

    small = controller.build_mission_graph(topic="focused query", target_instances=8)
    medium = controller.build_mission_graph(topic="broader query", target_instances=12)
    large = controller.build_mission_graph(topic="complex query", target_instances=15)

    assert len(small.agent_instances) == 8
    assert len(medium.agent_instances) == 12
    # The dynamic graph has a light 13-role ceiling even when
    # target capacity is larger; later semantic activation may use fewer.
    assert len(large.agent_instances) == 13
    assert sum(item.mission_node in {"S3", "S4"} for item in small.agent_instances) == 3
    assert sum(item.mission_node in {"S3", "S4"} for item in medium.agent_instances) == 7
    assert sum(item.mission_node in {"S3", "S4"} for item in large.agent_instances) == 8


def test_dynamic_v2_keeps_s3_s4_role_contracts_open_before_dimension_selection() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    graph = controller.build_mission_graph(
        topic="海峡拒止",
        query_theses=[
            {
                "project_name": "静默坐底拒止器",
                "equipment_form": "坐底封装释放武器",
                "project_function": "在海峡出口预置并触发拒止",
                "query_causal_link": "把持续追踪改为要道触发",
                "target_and_phase": "敌潜航器穿越阶段",
                "direct_military_effect": "迫使绕行或中止穿越",
            },
            {
                "project_name": "尾流反捕获拦截弹",
                "equipment_form": "尾流寻的自主拦截弹",
                "project_function": "在失去声学接触后沿尾流再捕获",
                "query_causal_link": "把接触中断改为物理痕迹续接",
                "target_and_phase": "高速脱离阶段",
                "direct_military_effect": "恢复拦截窗口并实施毁伤",
            },
        ],
    )

    creative_instances = [
        item for item in graph.agent_instances if item.mission_node in {"S3", "S4"}
    ]
    creative_contracts = [
        item for item in graph.role_contracts if item.mission_node in {"S3", "S4"}
    ]
    s3_instances = [item for item in creative_instances if item.mission_node == "S3"]
    s4_instances = [item for item in creative_instances if item.mission_node == "S4"]
    assert len(s3_instances) == 4
    assert len(s4_instances) == 4
    assert all(
        item.archetype == "innovative_equipment_dimension_generator"
        for item in creative_instances
    )
    assert all("开放创新武器" in item.display_name for item in creative_instances)
    assert all("静默坐底拒止器" not in item.purpose for item in creative_contracts)
    assert all("尾流反捕获拦截弹" not in item.purpose for item in creative_contracts)
    assert all(
        "独立检验Query蓝图制胜命题" not in item.purpose
        for item in creative_contracts
    )
    assert all(
        any("轻型创造会话" in step for step in item.methodology)
        for item in creative_contracts
    )


def test_dynamic_v2_does_not_frontload_blueprint_equipment_names_into_s3() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    theses = [
        {
            "project_name": f"query-angle-{index}",
            "equipment_form": f"specific-weapon-{index}",
            "project_function": f"independent-breakpoint-{index}",
            "query_causal_link": f"changed-variable-{index}",
            "target_and_phase": f"target-phase-{index}",
            "direct_military_effect": f"direct-result-{index}",
        }
        for index in range(1, 8)
    ]

    graph = controller.build_mission_graph(
        topic="query-led multi-angle mission",
        target_instances=15,
        query_theses=theses,
    )

    creative_contracts = [
        item for item in graph.role_contracts if item.mission_node in {"S3", "S4"}
    ]
    assert len(creative_contracts) == 8
    assert all(
        all(f"query-angle-{index}" not in contract.purpose for index in range(1, 8))
        for contract in creative_contracts
    )
    assert all(
        any(step.startswith("从Query语义开放发散候选") for step in item.methodology)
        for item in creative_contracts
    )
    assert "不默认两字代号" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "名称不是候选摘要" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "而不是字段拼装任务" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "统一系列标记" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "未来装备体系中真实存在" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "构型意象型" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "原理突破型" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "装备专名型" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "核心物理意象＋装备身份" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "自然现象或生物意象＋新型装备" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "代号＋装备类别" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "原理突破＋装备身份" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "不是模板、配额或分类覆盖任务" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "功能/动作短语＋装备类别尾词" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "不建立意象词库、后缀表、字符串评分或本地命名硬门" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
    assert "frontier_principle" in QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION


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
                "original_paradigm",
                "disruptive_shift",
                "independence_thesis",
            ],
            "title": "JASSM-ER类受扰导航验证型",
            "changed_confrontation_variable": "卫星导航拒止下保持固定目标区进入",
            "mechanism_chain": ["防区外发射", "受扰导航保持", "固定目标区进入"],
            "equipment_forms": ["固定构型远程精确制导任务弹药"],
            "novelty_delta": "仅主张工厂级构型换产与任务软件更新",
            "original_paradigm": "依赖卫星导航持续可用",
            "disruptive_shift": "固定目标区进入不再以卫星导航连续可用为前提",
            "independence_thesis": "改变导航依赖关系而非增加射程或战斗部",
        },
        incremental_quality=0.05,
        recommendation="revise",
        accepted=True,
    )

    merged, receipt = controller.merge_contribution(ledger, repair)

    assert receipt.status == "merged"
    assert merged.hypotheses[0].equipment_forms == ["固定构型远程精确制导任务弹药"]
    assert merged.hypotheses[0].title == "JASSM-ER类受扰导航验证型"
    assert merged.hypotheses[0].changed_confrontation_variable == (
        "卫星导航拒止下保持固定目标区进入"
    )
    assert merged.hypotheses[0].mechanism_chain == [
        "防区外发射",
        "受扰导航保持",
        "固定目标区进入",
    ]
    assert merged.hypotheses[0].novelty_delta == ("仅主张工厂级构型换产与任务软件更新")
    assert merged.hypotheses[0].original_paradigm == "依赖卫星导航持续可用"
    assert merged.hypotheses[0].disruptive_shift == (
        "固定目标区进入不再以卫星导航连续可用为前提"
    )


def test_quality_expert_judge_normalizes_scores_and_respects_codex_verdict() -> None:
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
                "decisive_advantage": 0.86,
                "query_specificity": 0.84,
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
            "verdict": "revise",
            "dimension_scores": {
                "domain_relevance": 0.8,
                "equipment_capability_fit": 0.35,
                "innovation": 0.7,
                "military_value": 0.45,
                "decisive_advantage": 0.35,
                "query_specificity": 0.40,
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
    assert controller.policy["expert_repair_reserved_instances"] == 0
    assert controller.policy["expert_candidate_pool_maximum"] == 0
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
    assert decision.selected_hypothesis_ids == ["strong", "weak"]
    assert decision.rejected_hypothesis_ids == []
    assert decision.quality_judge_passed is True


def test_quality_expert_can_retain_payload_title_with_diagnostic_residual() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    hypothesis = _hypothesis(
        hypothesis_id="payload-title",
        title="形态：远程低成本突防巡航弹，内置主杀伤体、末段诱压释放舱和有限末段确认载荷",
        equipment_forms=["远程母子攻击弹"],
    )

    assessment = controller.expert_assessment_from_mapping(
        {
            "verdict": "pass",
            "dimension_scores": {
                dimension: 0.9
                for dimension in (
                    "domain_relevance",
                    "equipment_capability_fit",
                    "innovation",
                    "military_value",
                    "decisive_advantage",
                    "query_specificity",
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
        blind_label="候选-01",
        valid_evidence_ids={"ev-1"},
        session_ref="session-title-gate",
    )

    assert assessment.passed is True
    assert assessment.verdict == "pass"
    assert "equipment_not_concrete" not in assessment.residuals
    assert assessment.rejection_reasons == []


def test_dynamic_v2_does_not_claim_direct_equipment_without_expert_classification() -> (
    None
):
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id=f"h{index}",
            title=(f"自主无人战斗平台{index}" if index <= 4 else f"支撑体系{index}"),
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

    assert 1 <= len(selected) <= 12
    assert sum(controller.is_direct_combat_equipment(item) for item in selected) == 0


def test_dynamic_portfolio_retains_all_reliable_independent_weapons_up_to_s6_capacity() -> (
    None
):
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    hypotheses = [
        _hypothesis(
            hypothesis_id=f"weapon-{index}",
            title=f"Query专属精确打击武器{index}",
            equipment_forms=[f"Query专属精确打击弹药{index}"],
            changed_confrontation_variable=f"第{index}项独立任务矛盾",
            direct_military_effects=[f"形成第{index}项独立直接战果"],
        )
        for index in range(1, 9)
    ]

    decision = controller.portfolio_decision(controller.create_ledger(hypotheses))

    assert len(decision.selected_hypothesis_ids) == 7
    assert decision.selected_hypothesis_ids == [
        item.hypothesis_id for item in hypotheses[:7]
    ]


def test_dynamic_portfolio_backfills_promising_revise_weapons_as_pending() -> None:
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
            hypothesis_id=f"weapon-{index}",
            title=f"前瞻窗口精确打击武器{index}",
            equipment_forms=[f"前瞻窗口精确打击导弹{index}"],
        )
        for index in range(1, 6)
    ]
    dimensions = {
        name: 0.74
        for name in (
            "domain_relevance",
            "equipment_capability_fit",
            "innovation",
            "military_value",
            "decisive_advantage",
            "query_specificity",
            "causal_coherence",
            "credibility",
            "engineering_feasibility",
            "robustness",
        )
    }
    assessments = {
        item.hypothesis_id: WinningExpertAssessment(
            assessment_id=f"assessment-{item.hypothesis_id}",
            hypothesis_id=item.hypothesis_id,
            blind_label=item.hypothesis_id,
            verdict="pass" if index == 1 else "revise",
            passed=index == 1,
            weighted_score=0.74,
            dimension_scores=dimensions,
            equipment_classification="direct_combat",
        )
        for index, item in enumerate(hypotheses, start=1)
    }

    decision = controller.portfolio_decision(
        controller.create_ledger(hypotheses),
        expert_assessments=assessments,
    )

    assert len(decision.selected_hypothesis_ids) == 5
    assert decision.quality_judge_passed is True
    assert set(decision.selected_hypothesis_ids) == {
        item.hypothesis_id for item in hypotheses
    }


def test_dynamic_portfolio_does_not_drop_same_family_candidates_by_lexical_family() -> (
    None
):
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
            "preferred_distinct_direct_equipment": 5,
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
    decision = controller.portfolio_decision(controller.create_ledger(hypotheses))
    selected = [
        item
        for item in hypotheses
        if item.hypothesis_id in decision.selected_hypothesis_ids
    ]
    assert len(selected) >= 5
    assert {"anti-rad-1", "anti-rad-2"} <= {item.hypothesis_id for item in selected}


def test_dynamic_portfolio_uses_expert_objectives_without_family_replacement() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
            "preferred_distinct_direct_equipment": 5,
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
        item
        for item in hypotheses
        if item.hypothesis_id in decision.selected_hypothesis_ids
    ]
    assert len(selected) == 5
    assert {"harop-a", "harop-b", "barracuda-a", "barracuda-b"} <= {
        item.hypothesis_id for item in selected
    }
    assert "system-link" not in {item.hypothesis_id for item in selected}


def test_dynamic_coverage_defers_independence_to_semantic_codex_clustering() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "finalist_minimum": 5,
            "finalist_maximum": 5,
            "preferred_distinct_direct_equipment": 5,
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

    assessments = {item.hypothesis_id: assessment(item) for item in hypotheses}
    ledger = controller.create_ledger(hypotheses)
    coverage = controller.passed_portfolio_coverage(ledger, assessments)

    assert coverage["passed_count"] == 7
    assert coverage["direct_combat_equipment_count"] == 6
    assert coverage["distinct_direct_equipment_family_count"] == 6
    assert coverage["preferred_distinct_direct_equipment"] == 0
    assert coverage["family_breadth_is_preference"] is False
    assert coverage["same_family_independence_conflicts"] == []
    assert coverage["semantic_independence_authority"] == (
        "independent_codex_five_axis_clustering"
    )
    assert coverage["ready"] is True

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

    assert coverage["distinct_direct_equipment_family_count"] == 7
    assert coverage["same_family_independence_conflicts"] == []
    assert coverage["ready"] is True


def test_local_code_does_not_infer_broad_equipment_families() -> None:
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

    assert len(counts) == 3
    assert set(counts.values()) == {1}
    assert all(key.startswith("semantic:") for key in counts)


def test_dynamic_portfolio_prefers_five_distinct_direct_weapons_over_system_link() -> (
    None
):
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


def test_dynamic_re_review_reuses_unassessed_ledger_without_upgrade_quota() -> None:
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
    assert set(selected) == {
        "air-missile",
        "ground-upgrade",
        "low-alt",
        "mald",
        "maritime",
    }


def test_dynamic_portfolio_does_not_force_lower_scored_upgrade_into_capacity() -> None:
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
    assert "upgrade" not in decision.selected_hypothesis_ids
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
        {"t1", "t2"} <= {item.task_id for item in batch} for batch in batches
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


def test_initial_plan_is_non_recursive_and_targeted_plan_respects_remaining_budget() -> (
    None
):
    controller = WinningSwarmController({"enabled": True})
    plan = controller.plan_initial(
        topic="test", execution_profile_id="swarm_quality_v1"
    )

    assert len(plan.tasks) == 3
    assert {task.wave for task in plan.tasks} == {1}
    assert all(task.allow_child_spawn is False for task in plan.tasks)
    assert not {
        "direct_combat_equipment_generator",
        "remote_precision_munition_generator",
        "mass_scalable_combat_family_generator",
    } & {task.archetype for task in plan.tasks}

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


def test_narrative_quality_note_does_not_recruit_a_repair_archetype() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )

    assert controller.archetype_for_residual("causal_chain_broken") == (
        "adversary_counter_adaptation_red_team"
    )
    assert controller.archetype_for_residual("causal_chain_broken已补强") == ""
    assert controller.archetype_for_residual("该问题已在S3闭合") == ""


@pytest.mark.parametrize(
    "title",
    [
        "内置数枚非常轻型鱼雷、反UUV水下弹药或声学标记器",
        "2至数枚轻型鱼雷、反UUV小型拦截器",
        "反UUV水下弹药或可抛投声学标记器火力",
        "短程反UUV效应器或标记载荷",
        "弹药化声学浮标/水下短期节点",
        "小型反UUV效应器舱与环境采样载荷",
        "轻型鱼雷/反UUV拦截弹药模块",
    ],
)
def test_frontloaded_local_gate_does_not_classify_payload_wording(
    title: str,
) -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    hypothesis = _hypothesis(
        title=title,
        equipment_forms=[title],
    )

    gate = controller.evaluate_gate(hypothesis, stage="final")

    assert gate.passed is True
    assert "equipment_not_concrete" not in gate.residuals


@pytest.mark.parametrize(
    "title",
    [
        "“沉界”大排量武装猎潜无人潜航器",
        "“断缆”百吨级远海无人水面反潜截击艇",
        "雷达与高功率微波复合反无人效应车",
    ],
)
def test_frontloaded_gate_keeps_single_compound_weapon_identity(title: str) -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        _hypothesis(title=title, equipment_forms=[title]),
        stage="final",
    )

    assert "equipment_not_concrete" not in gate.residuals


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
    ready, pruned = controller.ready_tasks([recursive], completed_task_ids=set())
    assert ready == []
    assert pruned == [recursive]


def test_contribution_requires_exact_hypothesis_and_merge_target_and_cleans_evidence() -> (
    None
):
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
    assert (
        controller.contribution_projection(
            contribution,
            hypothesis_id=task.hypothesis_id,
            merge_target=task.merge_target,
        )
        is not None
    )
    assert (
        controller.contribution_projection(
            contribution,
            hypothesis_id=task.hypothesis_id,
            merge_target="S6",
        )
        is None
    )

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
    assert contribution.incremental_quality == 0.01
    assert contribution.findings == []
    assert contribution.equipment_forms == ["潜射低特征多模反舰巡航弹药"]


def test_internal_workflow_commentary_never_enters_user_facing_candidate_fields() -> (
    None
):
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    task = SpecialistTask(
        task_id="s5-clean-handoff",
        agent_instance_id="s5-agent",
        archetype="evidence_verifier",
        display_name="证据核验",
        wave=3,
        purpose="verify one candidate",
        merge_target="S5",
        hypothesis_id="h-clean",
        expected_quality_gain=0.05,
    )

    contribution = controller.contribution_from_mapping(
        {
            "hypothesis_id": "h-clean",
            "merge_target": "S5",
            "findings": ["S5建议收窄验收轴；该审计意见保留在内部记录"],
            "mechanism_chain_updates": [
                "S5建议把核心可验收轴改为机动包线收缩",
                "武器先压缩目标机动包线，再由末段自主寻的实施毁伤",
            ],
            "validation_plan": [
                "以对照试验测量目标机动包线与有效毁伤率变化",
                "以每次有效毁伤成本作为S6判退指标",
            ],
            "direct_military_effects": ["迫使目标减速并暴露关键部位"],
            "evidence_boundary": "S5 Agent要求回到S4补写对象证据",
            "failure_boundaries": [
                "S5质量门认为仍需补写",
                "末段目标确认不足时放弃攻击",
            ],
            "evidence_ids": ["ev-1"],
            "incremental_quality": 0.06,
            "recommendation": "retain",
        },
        task=task,
        valid_evidence_ids={"ev-1"},
    )

    assert contribution.findings == ["S5建议收窄验收轴；该审计意见保留在内部记录"]
    assert contribution.mechanism_chain_updates == [
        "武器先压缩目标机动包线，再由末段自主寻的实施毁伤"
    ]
    assert contribution.validation_plan == [
        "以对照试验测量目标机动包线与有效毁伤率变化"
    ]
    assert contribution.evidence_boundary == ""
    assert contribution.failure_boundaries == ["末段目标确认不足时放弃攻击"]


def test_candidate_dedup_and_unsupported_precision_diagnostic() -> None:
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
    assert gate.passed is True
    assert "unsupported_precision" in gate.residuals


def test_same_family_candidates_are_not_blocked_by_local_operational_axes() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    first = _hypothesis(
        hypothesis_id="uuv-1",
        title="前置猎潜无人潜航器",
        equipment_forms=["大排量武装无人潜航器"],
    )
    wording_variant = replace(
        first,
        hypothesis_id="uuv-2",
        title="外缘接触保管无人潜航器",
        score=0.8,
    )

    assert controller.operational_independence_axes(first, wording_variant) == []
    conflicts = controller.same_family_independence_conflicts([first, wording_variant])
    assert conflicts == []
    unique, merges = controller.deduplicate_hypotheses([wording_variant, first])
    assert len(unique) == 1
    assert merges

    independent_variant = replace(
        first,
        hypothesis_id="uuv-3",
        title="坐底封装反潜拒止无人潜航器",
        equipment_forms=["坐底封装释放式无人潜航拒止器"],
        project_function="布设分队在海峡出口预置坐底武器，对穿越目标实施限域拒止。",
        changed_confrontation_variable="把持续追踪转化为要道预置和触发式拒止",
        mechanism_chain=["母平台投送", "坐底静默值班", "目标触发后释放效应器"],
        direct_military_effects=["封锁要道并迫使敌方潜航器绕行"],
        validation_plan=["验证坐底留置时间、触发边界和安全回收"],
        failure_boundaries=["海床条件不支持稳定留置时判退"],
    )
    axes = controller.operational_independence_axes(first, independent_variant)
    assert len(axes) >= 2
    assert (
        controller.same_family_independence_conflicts([first, independent_variant])
        == []
    )
    unique, _ = controller.deduplicate_hypotheses([first, independent_variant])
    assert {item.hypothesis_id for item in unique} == {"uuv-1", "uuv-3"}

    assessments = {
        item.hypothesis_id: WinningExpertAssessment(
            assessment_id=f"assessment-{item.hypothesis_id}",
            hypothesis_id=item.hypothesis_id,
            blind_label=item.hypothesis_id,
            verdict="pass",
            passed=True,
            weighted_score=0.82,
            equipment_classification="direct_combat",
        )
        for item in (first, independent_variant)
    }
    coverage = controller.passed_portfolio_coverage(
        controller.create_ledger([first, independent_variant]),
        assessments,
    )
    assert coverage["distinct_direct_equipment_family_count"] == 2
    assert coverage["same_family_independence_conflicts"] == []
    assert coverage["ready"] is True


def test_finalist_capacity_rejection_has_auditable_reason() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "finalist_maximum": 4, "finalist_minimum": 2}
    )
    candidates = [_hypothesis(hypothesis_id=f"h{index}") for index in range(1, 6)]

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

    assert (
        controller.semantic_hypothesis_match(
            obsolete,
            [unrelated, canonical],
        )
        == "canonical"
    )


def test_final_diagnostics_record_missing_structured_system_interfaces() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(_hypothesis(), system_interfaces=[]),
        stage="final",
    )

    assert gate.passed is True
    assert "system_interfaces_missing" in gate.residuals


def test_dynamic_final_diagnostics_record_missing_project_function() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(_hypothesis(), project_function=""),
        stage="final",
    )

    assert gate.passed is True
    assert "project_function_missing" in gate.residuals


def test_dynamic_final_gate_defers_mixed_public_family_semantics_to_codex() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(
            _hypothesis(),
            title="批量可消耗低空无人携弹压制平台族",
            equipment_forms=["MALD类诱骗压制型；AARGM-ER反辐射型；Harop巡飞猎歼型"],
            evidence_ids=["ev-weapon_equipment-web-mald"],
        ),
        stage="final",
    )

    assert "mixed_primary_equipment_families" not in gate.residuals


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
            implementation_path="upgrade",
        ),
        stage="final",
    )

    assert gate.passed is True
    assert "equipment_object_evidence_missing" in gate.residuals


def test_frontier_new_weapon_can_pass_with_analogous_evidence_and_low_priority_gaps() -> (
    None
):
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    gate = controller.evaluate_gate(
        replace(
            _hypothesis(),
            title="前沿多模反辐射巡飞导弹",
            equipment_forms=["前沿多模反辐射巡飞导弹"],
            evidence_ids=["ev-operational_employment-web-analogous"],
            counterevidence=[],
            adversary_adaptations=[],
            failure_boundaries=[],
            trl_constraints=[],
            cost_constraints=[],
            industrial_constraints=[],
            cross_scenario_results=[],
            validation_plan=[],
            implementation_path="new",
        ),
        stage="final",
    )

    assert gate.passed is True
    assert "equipment_object_evidence_missing" not in gate.residuals
    assert "counter_adaptation_unresolved" in gate.residuals
    assert "validation_route_missing" in gate.residuals


def test_frontier_allowance_keeps_zero_evidence_or_missing_boundary_nonblocking() -> (
    None
):
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "swarm_quality_v1"}
    )

    no_evidence = controller.evaluate_gate(
        replace(_hypothesis(), evidence_ids=[]), stage="final"
    )
    no_boundary = controller.evaluate_gate(
        replace(_hypothesis(), evidence_boundary=""), stage="final"
    )

    assert no_evidence.passed is True
    assert "evidence_insufficient" in no_evidence.residuals
    assert no_boundary.passed is True
    assert "evidence_insufficient" in no_boundary.residuals


def test_expert_repairs_prioritize_passed_system_links_for_combat_quota() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "swarm_quality_v1",
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
                    "decisive_advantage": score,
                    "query_specificity": score,
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
            assessment(
                "system-1", verdict="pass", classification="system_link", score=0.86
            ),
            assessment(
                "system-2", verdict="pass", classification="system_link", score=0.84
            ),
            assessment(
                "system-3", verdict="pass", classification="support_only", score=0.82
            ),
            assessment(
                "revise-1", verdict="revise", classification="upgrade", score=0.80
            ),
        ]
    }

    selected = controller.select_expert_repair_assessments(rows)

    assert [item.hypothesis_id for item in selected] == [
        "system-1",
        "system-2",
        "system-3",
    ]
    assert (
        controller.is_direct_combat_equipment(_hypothesis(), rows["system-1"]) is False
    )


def test_expert_repairs_prioritize_failed_direct_images_before_passed_links() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "swarm_quality_v1",
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
                        "decisive_advantage",
                        "query_specificity",
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


def test_expert_repairs_follow_expert_score_not_local_equipment_family() -> None:
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
                        "decisive_advantage",
                        "query_specificity",
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
    hypotheses = {item.hypothesis_id: item for item in (passed, duplicate, missing)}

    selected = controller.select_expert_repair_assessments(
        assessments,
        hypotheses=hypotheses,
    )

    assert [item.hypothesis_id for item in selected] == ["duplicate-loitering"]


def test_semantic_duplicate_is_not_selected_for_expert_repair() -> None:
    controller = WinningSwarmController(
        {
            "enabled": True,
            "policy_id": "winning_swarm_dynamic_v2",
            "expert_repair_max_candidates": 2,
        }
    )
    hypothesis = _hypothesis(hypothesis_id="duplicate-candidate")
    assessment = controller.expert_assessment_from_mapping(
        {
            "verdict": "revise",
            "dimension_scores": {
                dimension: 0.82
                for dimension in (
                    "domain_relevance",
                    "equipment_capability_fit",
                    "innovation",
                    "military_value",
                    "decisive_advantage",
                    "query_specificity",
                    "causal_coherence",
                    "credibility",
                    "engineering_feasibility",
                    "robustness",
                )
            },
            "equipment_classification": "direct_combat",
            "rejection_reasons": ["semantic_duplicate: 与候选A属于同一制胜命题"],
            "residuals": ["semantic_duplicate"],
            "evidence_ids": ["ev-1"],
        },
        hypothesis=hypothesis,
        blind_label="duplicate-candidate",
        valid_evidence_ids={"ev-1"},
        session_ref="session",
    )

    assert (
        controller.select_expert_repair_assessments(
            {hypothesis.hypothesis_id: assessment},
            hypotheses={hypothesis.hypothesis_id: hypothesis},
        )
        == []
    )


def test_equipment_family_signature_is_opaque_semantic_identity() -> None:
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

    anti_ship_signature = controller.equipment_family_signature(anti_ship)
    assert anti_ship_signature.startswith("semantic:")

    prsm = _hypothesis(
        title="PrSM Increment 2多模末制导验证型",
        equipment_forms=["HIMARS兼容的PrSM陆基远程反舰试验弹"],
    )
    prsm_signature = controller.equipment_family_signature(prsm)
    assert prsm_signature.startswith("semantic:")
    assert prsm_signature != anti_ship_signature


def test_promotion_requires_ten_runs_seventy_percent_and_no_hard_failures() -> None:
    controller = WinningSwarmController({"enabled": True})

    assert (
        controller.promotion_candidate(
            archetype="evidence_verifier",
            eligible_runs=9,
            positive_increment_runs=9,
            evidence_hard_failures=0,
            permission_hard_failures=0,
        )
        is None
    )
    assert (
        controller.promotion_candidate(
            archetype="evidence_verifier",
            eligible_runs=10,
            positive_increment_runs=7,
            evidence_hard_failures=1,
            permission_hard_failures=0,
        )
        is None
    )

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
