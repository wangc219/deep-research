from dataclasses import replace

from equipment_deep_research.domain.models import (
    AuditResult,
    BaselineFindingPacket,
    EvidenceCard,
    WinningMechanismStageOutput,
)
from equipment_deep_research.orchestration.winning_reasoning import SixStepReasoner
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.orchestration.winning import WinningMechanismEngine
from equipment_deep_research.orchestration.capability_portrait import (
    assemble_capability_portrait_modules,
)
from equipment_deep_research.orchestration.reporting import audit_run, render_report
from equipment_deep_research.orchestration.runner import (
    _codex_loops_recorded,
    _persisted_winning_loop_kinds,
    _reconcile_final_audit_status,
)


def test_six_steps_are_linked_and_evidence_backed() -> None:
    packet = BaselineFindingPacket(
        "p", "a", ["threat"], "topic", ["finding"], ["ev"], 0.8, [], [], "handoff", "cp"
    )
    evidence = EvidenceCard(
        "ev",
        "source",
        "https://example.org/a",
        "B",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "a",
    )
    result = SixStepReasoner().run(
        topic="topic",
        route="new_winning_mechanism",
        packets=[packet],
        evidence=[evidence],
    )
    assert result.winning_paths.input_refs == [result.defense_decomposition.object_id]
    assert result.effect_chain.input_refs == [result.winning_paths.object_id]
    assert result.capability_mapping.input_refs == [result.effect_chain.object_id]
    assert result.gap_matrix.input_refs == [result.capability_mapping.object_id]
    assert result.image_drafts[0].input_refs == [result.gap_matrix.object_id]
    assert all(
        node.evidence_ids and 0 <= node.confidence <= 1
        for node in result.critical_nodes()
    )


def test_six_steps_project_model_reasoning_nodes_and_govern_next_actions() -> None:
    packet = BaselineFindingPacket(
        "packet-1",
        "a",
        ["threat"],
        "topic",
        ["finding"],
        ["ev"],
        0.8,
        [],
        [],
        "handoff",
        "cp",
    )
    evidence = EvidenceCard(
        "ev",
        "source",
        "https://example.org/a",
        "B",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "a",
    )
    result = SixStepReasoner().run(
        topic="topic",
        route="new_winning_mechanism",
        packets=[packet],
        evidence=[evidence],
        model_analysis={
            "reasoning_nodes": {
                "1": {
                    "recognition": "模型形成的S1可审计认识",
                    "evidence_refs": ["ev", "invalid-ref"],
                    "confidence": 1.4,
                    "next_action": {
                        "action": "parallel",
                        "target_step": 3,
                        "reason": "S2按蓝图跳过，直接并入S3。",
                    },
                },
            },
            "winning_step_plan": [
                {"step": 1, "execution_mode": "deep"},
                {"step": 2, "execution_mode": "skip"},
                {"step": 3, "execution_mode": "deep"},
                {"step": 4, "execution_mode": "deep"},
                {"step": 5, "execution_mode": "skip"},
                {"step": 6, "execution_mode": "deep"},
            ],
        },
    )

    assert result.defense_decomposition.summary == "模型形成的S1可审计认识"
    assert result.defense_decomposition.evidence_ids == ["ev"]
    assert result.defense_decomposition.confidence == 1.0
    assert result.defense_decomposition.next_action == {
        "action": "parallel",
        "target_step": 3,
        "reason": "S2按蓝图跳过，直接并入S3。",
    }
    assert result.winning_paths.next_action["target_step"] == 3
    assert result.image_drafts[0].next_action["action"] == "stop"


def test_winning_engine_records_six_steps_in_trace_and_stage_refs() -> None:
    packet = BaselineFindingPacket(
        "p", "a", ["threat"], "topic", ["finding"], ["ev"], 0.8, [], [], "handoff", "cp"
    )
    evidence = EvidenceCard(
        "ev",
        "source",
        "https://example.org/a",
        "B",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "a",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)
    stages, _, _ = WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
    )
    assert (
        sum(
            event.event_type == "winning_reasoning_step_completed"
            for event in trace.events
        )
        == 6
    )
    assert all(stage.outputs["reasoning_refs"] for stage in stages)
    assert len(store.winning_inputs) == 1
    assert len(store.knowledge_projections) == 1
    assert len(store.reasoning_nodes) == 6
    input_pack = next(iter(store.winning_inputs.values()))
    resources = next(iter(store.knowledge_projections.values()))
    assert input_pack.problem_frame["objective"] == "回答需要发展具备什么功能的产品"
    assert resources.input_id == input_pack.input_id
    assert len(resources.theory_tools) == 5
    assert len(resources.question_chain) >= 4
    assert all(node.claim_ids == [] for node in store.reasoning_nodes.values())


def test_deadline_fallback_does_not_emit_fixed_weapon_images() -> None:
    packet = BaselineFindingPacket(
        "packet-fallback",
        "weapon_equipment",
        ["equipment", "capability_gap", "technology_readiness"],
        "从近年局部战争中挖掘无人远程精确打击装备需求",
        ["高消耗与强干扰条件要求低成本规模化武器"],
        ["ev-fallback"],
        0.8,
        [],
        [],
        "形成装备基线与差距",
        "complete",
    )
    evidence = EvidenceCard(
        "ev-fallback",
        "公开装备资料",
        "https://example.org/fallback",
        "B",
        "公开材料支持无人化和精确火力趋势判断",
        "公开材料正文",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)

    _, images, _ = WinningMechanismEngine().run(
        topic=packet.topic_focus,
        route="war_case_learning",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
        model_analysis={},
    )

    assert images == []


def test_winning_engine_turns_critic_evidence_gap_into_bounded_targeted_recall() -> None:
    packet = BaselineFindingPacket(
        "p",
        "weapon_equipment",
        ["equipment", "capability_gap", "technology_readiness"],
        "topic",
        ["finding"],
        ["ev"],
        0.82,
        [],
        [],
        "handoff",
        "cp",
    )
    evidence = EvidenceCard(
        "ev",
        "source",
        "https://example.org/a",
        "A",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)

    stages, _, _ = WinningMechanismEngine().run(
        topic="topic",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": [
                "equipment",
                "capability_gap",
                "technology_readiness",
            ],
        },
        model_analysis={
            "evidence_supplement_pending": True,
            "targeted_evidence_requests": [
                {
                    "question": "补充日期化集成测试证据",
                    "target_agent_id": "weapon_equipment",
                    "affected_steps": [4, 5, 6],
                    "source_preferences": ["官方测试报告"],
                    "reason": "决定能力缺口是否已部分满足",
                }
            ],
        },
    )

    recall = stages[-1].recall_requests[0]
    assert recall.target_agent_id == "weapon_equipment"
    assert recall.return_node == "L3"
    assert "补充日期化集成测试证据" in recall.required_data
    assert stages[-1].gate_passed is False


def test_risk_based_gate_keeps_calibration_request_as_validation_backlog() -> None:
    packet = BaselineFindingPacket(
        "p-validation-backlog",
        "weapon_equipment",
        ["equipment", "capability_gap", "technology_readiness"],
        "topic",
        ["finding"],
        ["ev-validation-backlog"],
        0.82,
        [],
        [],
        "handoff",
        "cp-validation-backlog",
    )
    evidence = EvidenceCard(
        "ev-validation-backlog",
        "source",
        "https://example.org/validation-backlog",
        "A",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)
    model_analysis = {
        "defense_decomposition": ["threat"],
        "winning_paths": ["path"],
        "effect_chain": ["discover-control-defeat"],
        "capability_mapping": ["equipment mapping"],
        "gap_assessment": [{"capability": "interceptor", "grade": "gap"}],
        "s6_quality_gate_passed": True,
        "s6_quality_gate_failed": False,
        "middle_loop_limited": True,
        "evidence_supplement_pending": True,
        "targeted_evidence_requests": [
            {
                "question": "补充型号级成本交换试验数据",
                "target_agent_id": "weapon_equipment",
                "affected_steps": [6],
                "source_preferences": ["官方试验报告"],
                "reason": "进一步校准型号化边界",
            }
        ],
        "concept_directions": [
            {
                "name": "低成本近程拦截弹能力",
                "type": "new_capability",
                "function": "把可信预警航迹转化为末段拦截",
                "equipment_form": "车载近程制导拦截弹发射单元",
                "operational_mechanism": "由融合航迹触发火控分配并完成末段拦截",
                "military_value": "提高要地低空拒止能力",
                "direct_evidence_refs": ["ev-validation-backlog"],
                "failure_boundary": "航迹延迟或分类错误时不进入交战",
                "verification": "验证闭环时延、误射率和成本交换边界",
                "confidence": 0.78,
            }
        ],
    }

    stages, images, _ = WinningMechanismEngine(risk_based_gates=True).run(
        topic="topic",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": [
                "equipment",
                "capability_gap",
                "technology_readiness",
            ],
        },
        model_analysis=model_analysis,
    )

    assert [stage.gate_passed for stage in stages] == [True, True, True]
    assert stages[-1].recall_requests == []
    backlog = stages[-1].outputs["validation_backlog"]
    assert backlog[0]["classification"] == "calibration_backlog"
    assert backlog[0]["gate_impact"] == "non_blocking"


def test_risk_based_targeted_evidence_is_advisory_without_direct_evidence() -> None:
    packet = BaselineFindingPacket(
        "p-blocking-evidence",
        "weapon_equipment",
        ["equipment", "capability_gap", "technology_readiness"],
        "topic",
        ["finding"],
        ["ev-blocking-evidence"],
        0.82,
        [],
        [],
        "handoff",
        "cp-blocking-evidence",
    )
    evidence = EvidenceCard(
        "ev-blocking-evidence",
        "source",
        "https://example.org/blocking-evidence",
        "A",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)

    stages, images, _ = WinningMechanismEngine(risk_based_gates=True).run(
        topic="topic",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": [
                "equipment",
                "capability_gap",
                "technology_readiness",
            ],
        },
        model_analysis={
            "defense_decomposition": ["threat"],
            "winning_paths": ["path"],
            "effect_chain": ["discover-control-defeat"],
            "capability_mapping": ["equipment mapping"],
            "gap_assessment": [{"capability": "interceptor", "grade": "gap"}],
            "s6_quality_gate_passed": True,
            "evidence_supplement_pending": True,
            "targeted_evidence_requests": [
                {
                    "question": "补充直接装备试验证据",
                    "target_agent_id": "weapon_equipment",
                }
            ],
            "concept_directions": [
                {
                    "name": "缺证方向",
                    "type": "new_capability",
                    "equipment_form": "近程拦截弹",
                    "operational_mechanism": "预警触发拦截",
                    "direct_evidence_refs": [],
                    "failure_boundary": "航迹不足时失效",
                    "verification": "开展闭环试验",
                    "confidence": 0.78,
                }
            ],
        },
    )

    assert stages[-1].gate_passed is True
    assert stages[-1].recall_requests == []
    assert not any("缺少有效直接证据" in reason for reason in stages[-1].gate_reasons)
    assert images[0].evidence_ids == []


def test_three_routes_do_not_generate_local_fallback_images() -> None:
    for route in (
        "new_winning_mechanism",
        "traditional_gap",
        "war_case_learning",
    ):
        packet = BaselineFindingPacket(
            f"p-{route}",
            "a",
            ["threat"],
            "topic",
            ["finding"],
            ["ev"],
            0.8,
            [],
            [],
            "handoff",
            "cp",
        )
        evidence = EvidenceCard(
            "ev",
            "source",
            "https://example.org/a",
            "B",
            "claim",
            "excerpt",
            "p:1",
            "quality",
            "a",
        )
        store, trace = DomainStore(), TraceStore()
        store.add_baseline_packet(packet)
        store.add_evidence(evidence)
        _, images, _ = WinningMechanismEngine().run(
            topic="topic",
            route=route,
            store=store,
            trace=trace,
            coverage={"missing_required_tags": [], "coverage_passed": True},
        )
        assert images == []


def test_model_directions_are_all_preserved_as_capability_images() -> None:
    packet = BaselineFindingPacket(
        "p",
        "a",
        ["equipment", "capability_gap", "technology_readiness"],
        "topic",
        ["finding"],
        ["ev-1", "ev-2"],
        0.8,
        [],
        [],
        "handoff",
        "cp",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    for evidence_id in ("ev-1", "ev-2"):
        store.add_evidence(
            EvidenceCard(
                evidence_id,
                "source",
                f"https://example.org/{evidence_id}",
                "B",
                "claim",
                "excerpt",
                "p:1",
                "quality",
                "a",
            )
        )

    _, images, _ = WinningMechanismEngine().run(
        topic="topic",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
        model_analysis={
            "winning_paths": ["压缩发现到处置的任务闭环"],
            "effect_chain": ["受扰条件下保持感知连续性并恢复协同"],
            "capability_mapping": ["将任务韧性映射为开放接口与抗扰重构功能"],
            "concept_directions": [
                {
                    "name": "方向一",
                    "priority": "P1",
                    "type": "upgrade",
                    "function": "功能一",
                    "feasibility": 4,
                    "horizon": "near",
                    "direct_evidence_refs": ["ev-1"],
                    "derived_from": ["reasoning-S4", "reasoning-S5"],
                    "verification": "验证一",
                    "military_value": "提升现役平台在强干扰条件下的任务连续性与体系贡献度",
                    "depth_mechanism": "以开放接口和链路重构削弱单点失效影响",
                    "strike_countermeasure_value": "增强对电子压制和链路中断的抗扰、反制与恢复能力",
                    "novelty": "用软件定义任务重构替代固定功能升级",
                    "foresight": "面向智能化干扰与低成本饱和手段持续演化",
                    "uncertainty_boundary": "公开材料尚不能证明极端频谱环境下的能力保持率",
                    "equipment_form": "开放式任务系统与抗扰通信改装套件",
                    "operational_mechanism": "在链路受扰时通过边缘自治和多路径重构保持最低任务闭环",
                    "development_path": "近期完成软件和接口改装，中期开展跨平台体系联试",
                    "baseline_system": "现役无人任务平台的任务计算机、数据链与火力协同接口",
                    "upgrade_package": ["开放式任务计算模块", "抗扰多链路网关", "边缘火力协同软件"],
                    "combat_effect_uplift": "在主链路受压后继续形成目标共享、火力协同和任务重组能力",
                    "strike_chain_contribution": "缩短目标发现到火力分配闭环，并提高受扰后的打击任务续接能力",
                    "upgrade_boundary": "若平台能源、算力和接口余量无法支撑跨平台协同，则转入新型任务节点研制",
                    "capability_portrait": "面向强干扰条件下的任务链断点，形成开放式任务系统与抗扰通信改装套件，通过边缘自治、多路径重构和软件定义任务编排，使现役平台在主链路失效后仍能维持最低感知、决策和协同闭环；该方向不是简单提升通信功率，而是重构平台对体系网络的依赖方式，并以跨平台联试决定后续硬件改装范围。",
                },
                {
                    "name": "方向二",
                    "priority": "P2",
                    "type": "new_capability",
                    "function": "功能二",
                    "feasibility": 3,
                    "horizon": "mid",
                    "direct_evidence_refs": ["ev-2"],
                    "verification": "验证二",
                },
                {
                    "name": "方向三",
                    "priority": "P3",
                    "type": "upgrade",
                    "function": "功能三",
                    "feasibility": 3,
                    "horizon": "mid",
                    "direct_evidence_refs": ["invalid", "ev-2"],
                    "verification": "验证三",
                },
            ]
        },
    )

    assert [item.name for item in images] == [
        "方向一",
        "方向二",
        "方向三",
    ]
    assert [item.capability_id for item in images] == [
        "cap-upgrade-001",
        "cap-new-001",
        "cap-upgrade-002",
    ]
    assert images[0].evidence_ids == ["ev-1"]
    assert images[2].evidence_ids == ["ev-2"]
    upgrade = images[0]
    assert "压缩发现到处置的任务闭环" in upgrade.source_winning_logic
    assert "任务连续性" in upgrade.military_utility
    assert "电子压制" in upgrade.strike_countermeasure_value
    assert "软件定义" in upgrade.novelty
    assert "智能化干扰" in upgrade.foresight
    assert upgrade.capability_image == upgrade.deep_capability_portrait
    assert "关键作战流程" in upgrade.deep_capability_portrait
    assert "制胜逻辑机理" in upgrade.deep_capability_portrait
    assert "开放式任务系统" in upgrade.equipment_category
    assert "边缘自治" in upgrade.operational_mechanism
    assert upgrade.development_path.startswith("近期完成")
    assert upgrade.baseline_system.startswith("现役无人任务平台")
    assert "开放式任务计算模块" in upgrade.upgrade_package
    assert "火力协同" in upgrade.combat_effect_uplift
    assert "打击任务续接" in upgrade.strike_chain_contribution
    assert "转入新型任务节点研制" in upgrade.upgrade_boundary
    assert upgrade.agent_contributions == ["a：handoff"]
    assert upgrade.evidence_basis[0].startswith("a（ev-1）")
    assert "reasoning-S4" in upgrade.reasoning_refs
    assert "公开材料尚不能证明" in upgrade.operational_constraints[0]


def test_s6_final_weapon_set_cannot_be_replaced_by_upstream_abstract_direction() -> None:
    packet = BaselineFindingPacket(
        "packet-s6-identity",
        "weapon_equipment",
        ["equipment", "capability_gap", "technology_readiness"],
        "强干扰远程精确打击",
        ["形成六项具体武器装备方向"],
        ["ev-s6-identity"],
        0.82,
        [],
        [],
        "S6最终组合已通过门禁",
        "cp-s6-identity",
    )
    evidence = EvidenceCard(
        "ev-s6-identity",
        "公开来源",
        "https://example.org/s6-identity",
        "B",
        "公开材料支持远程精确打击装备研究",
        "公开摘要",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)
    final_names = [
        "现役远程火箭炮弱链精确打击升级",
        "抗扰拒打远程精确导弹",
        "低信息侦打巡飞弹",
        "反辐射巡飞弹猎杀",
        "分布式猎歼远火车",
        "被动末端制导滑翔弹",
    ]

    _, images, _ = WinningMechanismEngine().run(
        topic="强干扰、弱通信条件下低信息依赖精确打击装备研究",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
        model_analysis={
            "winning_paths": ["低信息条件下保持远程精确毁伤闭环"],
            "s4_concept_directions": [
                "强扰断链条件分布式目标指示与连续火力协同能力"
            ],
            "concept_directions": [
                {
                    "name": name,
                    "type": "upgrade" if index == 0 else "new_capability",
                    "direct_evidence_refs": ["ev-s6-identity"],
                    "military_value": "直接形成远程打击、猎歼、压制或毁伤效果",
                    "equipment_form": name,
                    "operational_mechanism": "在受扰条件下完成目标确认与直接火力交战",
                    "capability_portrait": (
                        "概述：面向错误场景，针对无关任务，以同一错误装备画像描述全部候选。"
                    ),
                }
                for index, name in enumerate(final_names)
            ],
            "s6_quality_gate_passed": True,
        },
    )

    assert [item.name for item in images] == final_names
    assert [item.name for item in store.capability_images.values()] == final_names
    assert not any("分布式目标指示与连续火力协同能力" in item.name for item in images)
    assert len({item.deep_capability_portrait for item in images}) == len(final_names)
    assert all(
        item.name in item.deep_capability_portrait and "错误场景" not in item.deep_capability_portrait
        for item in images
    )


def test_quality_limited_s6_modules_remain_authoritative_for_delivery() -> None:
    packet = BaselineFindingPacket(
        "packet-s6-limited",
        "weapon_equipment",
        ["equipment"],
        "低空反无人",
        ["形成具体装备能力画像"],
        ["ev-s6-limited"],
        0.8,
        [],
        [],
        "S6画像已完成，仅保留非阻断编辑提示",
        "cp-s6-limited",
    )
    evidence = EvidenceCard(
        "ev-s6-limited",
        "公开来源",
        "https://example.org/s6-limited",
        "B",
        "公开材料支持低空反无人装备研究",
        "公开摘要",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    modules = {
        "overview": "测试拦截弹面向低空目标密集来袭，改变逐目标消耗关系并形成直接拦截战果。",
        "technology_implementation": "弹载被动传感器与任务计算机完成目标发现、认领和末段制导，关键接口落在导引头、飞控与战斗部。",
        "operational_process": "发射单元完成授权与空域装订，弹体进入拦阻区后自主认领目标，作用后复核剩余威胁并退出。",
        "capability_effects": "形成不依赖逐目标火控通道的并行拦截能力，使后续波次无法利用再装填空窗突防。",
        "winning_logic": "把高价单发对廉价数量的旧交换改为低成本并行拦阻，迫使对手分散编组并延长暴露时间。",
    }
    expected_portrait = assemble_capability_portrait_modules(modules)
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)

    _, images, _ = WinningMechanismEngine().run(
        topic="低空反无人装备研究",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
        model_analysis={
            "winning_paths": ["低成本并行拦阻"],
            "concept_directions": [
                {
                    "name": "测试拦截弹",
                    "type": "new_capability",
                    "equipment_form": "低成本自主拦截弹",
                    "military_value": "形成低空直接拦截战果",
                    "direct_evidence_refs": ["ev-s6-limited"],
                    "capability_portrait": "被供应商压平的旧整卡字符串",
                    "capability_portrait_modules": modules,
                    "semantic_consistency_check": {"consistent": True},
                    "s6_authoring_status": "authored_quality_limited",
                }
            ],
            "s6_quality_gate_passed": True,
        },
    )

    assert len(images) == 1
    assert images[0].deep_capability_portrait == expected_portrait
    assert images[0].capability_image == expected_portrait
    assert images[0].portrait_authoring_status == "s6_authored_semantically_consistent"


def test_structured_baseline_does_not_trigger_local_capability_image_generation() -> None:
    packet = BaselineFindingPacket(
        "p",
        "weapon_equipment",
        ["equipment"],
        "topic",
        ["finding"],
        ["ev"],
        0.8,
        [],
        [],
        "handoff",
        "cp",
        analysis_sections={
            "current_parameters": [
                {
                    "parameter": "系统可用度",
                    "value": "需按演训基线测量",
                    "confidence": "中",
                },
            ],
            "capability_constraints": [
                {"constraint": "弱网环境", "effect": "跨平台协同能力下降"},
            ],
        },
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(
        EvidenceCard(
            "ev",
            "source",
            "https://example.org/a",
            "B",
            "claim",
            "excerpt",
            "p:1",
            "quality",
            "a",
        )
    )

    _, images, _ = WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
    )

    assert images == []


def test_report_uses_normative_capability_image_sections() -> None:
    packet = BaselineFindingPacket(
        "p", "a", ["threat"], "topic", ["finding"], ["ev"], 0.8, [], [], "handoff", "cp"
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(
        EvidenceCard(
            "ev",
            "source",
            "https://example.org/a",
            "B",
            "claim",
            "excerpt",
            "p:1",
            "quality",
            "a",
        )
    )
    WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        trace=trace,
        coverage={"missing_required_tags": [], "coverage_passed": True},
    )
    audit = audit_run(
        store=store,
        coverage={"coverage_passed": True},
        max_rounds=2,
        analyst_confirmed=True,
    )

    report = render_report(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        coverage={"coverage_passed": True, "provided_tags": ["threat"]},
        audit=audit,
    )

    for heading in [
        "## 1. 核心结论",
        "## 2. 分支深度综合研判与军事运用价值",
        "## 3. 新战法发现分支专用输出",
        "## 4. 装备能力画像与建设优先序",
        "### 主矛盾、效果链断点与制胜判断",
        "### 打击、反制、抗毁与持续作战价值",
        "### 未来战争演化、建设时序与验证边界",
        "完整证据索引与推理回溯",
        "## 5. 建设演进路径",
        "## 6. 证据边界与后续验证",
    ]:
        assert heading in report.body
    assert "**深度能力画像。**" not in report.body

    for forbidden in [
        "#### 四维能力画像研判",
        "#### 专业 Agent 贡献",
        "#### 证据依据",
        "#### 指标与度量口径",
        "**军事价值性**",
        "**深度性**",
        "**前瞻性**",
        "**新颖性**",
    ]:
        assert forbidden not in report.body
    assert len(report.body) < 14_000

    synthesized = render_report(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        coverage={"coverage_passed": True, "provided_tags": ["threat"]},
        audit=audit,
        executive_summary=(
            "### 主矛盾与制胜判断\n\n跨能力综合判断，不按能力卡片逐项复述。\n\n"
            "### 打击反制与未来演化\n\n说明任务链闭合、反制恢复和未来触发条件。"
        ),
        prefer_model_report=True,
    )
    assert "跨能力综合判断，不按能力卡片逐项复述" in synthesized.body
    assert "### 打击反制与未来演化" in synthesized.body
    assert "**深度能力画像。**" not in synthesized.body


def test_l2_and_l3_create_layer_specific_recall_requests() -> None:
    packet = BaselineFindingPacket(
        "p",
        "a",
        ["threat"],
        "topic",
        ["finding"],
        ["ev"],
        0.8,
        [],
        [],
        "handoff",
        "cp",
    )
    evidence = EvidenceCard(
        "ev",
        "source",
        "https://example.org/a",
        "B",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "a",
    )

    l2_store, l2_trace = DomainStore(), TraceStore()
    l2_store.add_baseline_packet(packet)
    l2_store.add_evidence(evidence)
    l2_stages, _, _ = WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=l2_store,
        trace=l2_trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": [
                "situation",
                "threat",
                "scenario",
                "equipment",
                "operation",
                "capability_gap",
            ],
        },
    )
    assert l2_stages[1].recall_requests[0].return_node == "L2"
    assert (
        l2_stages[1].recall_requests[0].target_capability_tag == "technology_readiness"
    )

    l3_store, l3_trace = DomainStore(), TraceStore()
    l3_store.add_baseline_packet(packet)
    l3_store.add_evidence(evidence)
    l3_stages, _, _ = WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=l3_store,
        trace=l3_trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": [
                "situation",
                "threat",
                "scenario",
                "equipment",
                "operation",
                "technology_readiness",
            ],
        },
    )
    assert l3_stages[2].recall_requests[0].return_node == "L3"
    assert l3_stages[2].recall_requests[0].target_capability_tag == "capability_gap"


def test_resume_from_l3_reuses_passed_l1_and_l2() -> None:
    packet = BaselineFindingPacket(
        "p",
        "a",
        ["equipment", "technology_readiness"],
        "topic",
        ["finding"],
        ["ev"],
        0.8,
        [],
        [],
        "handoff",
        "cp",
    )
    evidence = EvidenceCard(
        "ev",
        "source",
        "https://example.org/a",
        "B",
        "claim",
        "excerpt",
        "p:1",
        "quality",
        "a",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)
    first, _, _ = WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": ["equipment", "technology_readiness"],
        },
    )
    store.stage_outputs.clear()
    store.capability_images.clear()
    resumed, _, _ = WinningMechanismEngine().run(
        topic="topic",
        route="new_winning_mechanism",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": ["equipment", "technology_readiness", "capability_gap"],
        },
        attempt=2,
        resume_from="L3",
        prior_stages=first,
    )
    assert resumed[0].stage_id == first[0].stage_id
    assert resumed[1].stage_id == first[1].stage_id
    assert resumed[2].stage_id == "stage-L3-r2"


def test_risk_based_gates_accept_grounded_s_chain_without_duplicate_tag_recall() -> None:
    packet = BaselineFindingPacket(
        "packet-risk",
        "system_confrontation",
        ["system_model"],
        "体系对抗",
        ["公开证据支持体系节点失效与替代链判断"],
        ["ev-risk"],
        0.68,
        [],
        [],
        "完成体系分析",
        "done",
    )
    evidence = EvidenceCard(
        "ev-risk",
        "公开来源",
        "https://example.org/risk",
        "B",
        "体系节点存在可验证的级联失效压力",
        "公开材料摘要",
        "p:1",
        "quality",
        "system_confrontation",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)
    stages, _, _ = WinningMechanismEngine(risk_based_gates=True).run(
        topic="体系韧性",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": ["technology_readiness", "capability_gap"],
            "coverage_passed": False,
            "provided_tags": ["system_model"],
        },
        model_analysis={
            "defense_decomposition": ["对手体系依赖"],
            "winning_paths": ["替代链保持反制闭环"],
            "effect_chain": ["节点受压—替代链切换—任务续接"],
            "capability_mapping": ["弹性组网与任务重构"],
            "gap_assessment": [
                {"capability": "任务重构", "grade": "部分差距", "basis": "ev-risk"}
            ],
            "concept_directions": [
                {"name": "弹性任务重构能力", "type": "upgrade"}
            ],
            "confidence": 0.75,
        },
    )

    assert all(stage.gate_passed for stage in stages)
    assert all(not stage.recall_requests for stage in stages)
    assert stages[0].outputs["coverage_limits"] == [
        "technology_readiness",
        "capability_gap",
    ]
    assert stages[1].outputs["validation_source"] == "S步骤结构化验证"


def test_dynamic_swarm_semantics_close_l1_l3_without_exact_situation_tag() -> None:
    packet = BaselineFindingPacket(
        "packet-semantic-swarm",
        "weapon_equipment",
        ["equipment"],
        "远海断链打击",
        ["公开材料支撑断链条件下的武器运用与失效边界判断"],
        ["ev-semantic-swarm"],
        0.61,
        [],
        [],
        "动态蜂群形成装备组合",
        "done",
    )
    analysis = {
        "s6_quality_gate_passed": True,
        "s6_quality_gate_failed": False,
        "winning_swarm": {
            "final_equipment_portfolio": [
                {
                    "name": "断链续攻自主巡飞打击弹",
                    "operational_mechanism": "在主链路失效后自主完成目标复核与交战",
                    "failure_boundary": "目标类别无法确认时终止攻击",
                }
            ],
            "portfolio_quality_gate": {"passed": True},
        },
        "capability_synthesis": [
            {"combat_problem": "压制下任务链中断", "winning_logic": "缩短再授权链"}
        ],
    }
    engine = WinningMechanismEngine(risk_based_gates=True)
    coverage = {
        "missing_required_tags": ["situation"],
        "coverage_passed": False,
        "provided_tags": ["equipment"],
    }
    l1 = engine._l1(
        topic="远海断链打击",
        route="new_winning_mechanism",
        packets=[packet],
        evidence_ids=["ev-semantic-swarm"],
        coverage=coverage,
        stage_id="stage-L1",
        model_analysis=analysis,
    )
    l2 = engine._l2(
        topic="远海断链打击",
        route="new_winning_mechanism",
        l1=l1,
        evidence_ids=["ev-semantic-swarm"],
        coverage=coverage,
        stage_id="stage-L2",
        model_analysis=analysis,
    )
    l3 = engine._l3(
        topic="远海断链打击",
        route="new_winning_mechanism",
        l1=l1,
        l2=l2,
        evidence_ids=["ev-semantic-swarm"],
        coverage=coverage,
        stage_id="stage-L3",
        model_analysis=analysis,
    )

    assert [l1.gate_passed, l2.gate_passed, l3.gate_passed] == [True, True, True]
    assert l1.recall_requests == []
    assert l2.recall_requests == []
    assert l3.recall_requests == []
    assert l1.outputs["semantic_gate"]["exact_tag_gaps_are_non_blocking"] is True


def test_risk_gate_recalls_for_no_evidence_not_low_confidence() -> None:
    packet = BaselineFindingPacket(
        "packet-low-confidence",
        "weapon_equipment",
        ["equipment"],
        "前瞻装备",
        ["新质装备仍处于概念验证阶段"],
        ["ev-low-confidence"],
        0.42,
        [],
        ["公开证据较少"],
        "形成有限置信判断",
        "done",
    )
    engine = WinningMechanismEngine(risk_based_gates=True)
    coverage = {
        "missing_required_tags": ["situation"],
        "coverage_passed": False,
        "provided_tags": ["equipment"],
    }
    analysis = {
        "capability_synthesis": [
            {
                "name": "跨介质自主猎歼装备",
                "winning_logic": "以跨域机动打破固定防御扇区",
            }
        ],
        "concept_directions": [
            {"name": "跨介质自主猎歼装备", "type": "new_capability"}
        ],
    }

    low_confidence = engine._l1(
        topic="前瞻装备",
        route="new_winning_mechanism",
        packets=[packet],
        evidence_ids=["ev-low-confidence"],
        coverage=coverage,
        stage_id="stage-L1",
        model_analysis=analysis,
    )
    no_evidence = engine._l1(
        topic="前瞻装备",
        route="new_winning_mechanism",
        packets=[replace(packet, evidence_ids=[])],
        evidence_ids=[],
        coverage=coverage,
        stage_id="stage-L1-no-evidence",
        model_analysis=analysis,
    )

    assert low_confidence.gate_passed is True
    assert low_confidence.recall_requests == []
    assert low_confidence.outputs["semantic_gate"]["low_confidence_is_warning"] is True
    assert no_evidence.gate_passed is False
    assert len(no_evidence.recall_requests) == 1
    assert no_evidence.recall_requests[0].target_capability_tag is None
    assert "没有可追溯公开证据" in no_evidence.recall_requests[0].reason


def test_post_recall_risk_gate_accepts_grounded_evidence_at_calibrated_floor() -> None:
    packet = BaselineFindingPacket(
        "packet-post-recall",
        "weapon_equipment",
        ["equipment", "technology_readiness", "capability_gap"],
        "远海保障",
        ["补证后形成可审计的装备差距判断"],
        ["ev-post-recall"],
        0.62,
        [],
        [],
        "定向补证完成",
        "done",
    )
    evidence = EvidenceCard(
        "ev-post-recall",
        "公开来源",
        "https://example.org/post-recall",
        "B",
        "补证支持任务链恢复判断",
        "公开材料摘要",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)

    stages, _, _ = WinningMechanismEngine(risk_based_gates=True).run(
        topic="远海保障",
        route="traditional_gap",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": ["equipment", "technology_readiness", "capability_gap"],
        },
        attempt=2,
        resume_from="L1",
        model_analysis={
            "defense_decomposition": ["对手压制维修与补给节点"],
            "winning_paths": ["以分布式保障维持拒止闭环"],
            "effect_chain": ["节点受压—快速恢复—任务续接"],
            "capability_mapping": ["抗毁维修与多路径保障"],
            "gap_assessment": [
                {"capability": "保障恢复", "grade": "关键差距", "basis": "ev-post-recall"}
            ],
            "concept_directions": [{"name": "分布式保障恢复能力", "type": "upgrade"}],
        },
    )

    assert stages[0].stage_id == "stage-L1-r2"
    assert stages[0].gate_passed is True
    assert stages[0].recall_requests == []


def test_optimized_audit_accepts_confidence_calibrated_by_passed_stage_gates() -> None:
    store = DomainStore()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L1",
            layer="L1",
            title="制胜逻辑",
            outputs={},
            confidence=0.65,
            evidence_ids=["ev"],
            gate_passed=True,
            gate_reasons=[],
        )
    )
    audit = audit_run(
        store=store,
        coverage={"coverage_passed": True},
        max_rounds=2,
        analyst_confirmed=True,
        risk_based_confidence=True,
    )

    assert audit.status == "approved"
    assert audit.checks["confidence_ge_70"] is True


def test_legacy_s6_quality_failure_is_advisory_to_stage_and_audit() -> None:
    packet = BaselineFindingPacket(
        "packet-s6-gate",
        "weapon_equipment",
        ["equipment", "capability_gap", "technology_readiness"],
        "局部战争装备需求",
        ["无人作战与精确火力需要形成独立方向"],
        ["ev-s6-gate"],
        0.82,
        [],
        [],
        "形成装备发展基线",
        "cp-s6-gate",
    )
    evidence = EvidenceCard(
        "ev-s6-gate",
        "source",
        "https://example.org/s6-gate",
        "B",
        "公开战例支持装备方向审查",
        "excerpt",
        "p:1",
        "quality",
        "weapon_equipment",
    )
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)

    stages, _, _ = WinningMechanismEngine(risk_based_gates=True).run(
        topic="局部战争装备需求",
        route="war_case_learning",
        store=store,
        trace=trace,
        coverage={
            "missing_required_tags": [],
            "coverage_passed": True,
            "provided_tags": ["equipment", "capability_gap", "technology_readiness", "lessons"],
        },
        model_analysis={
            "defense_decomposition": ["低空与精确火力威胁"],
            "winning_paths": ["形成无人作战与精确打击组合"],
            "effect_chain": ["发现—火力分配—毁伤"],
            "capability_mapping": ["无人平台与导弹弹药"],
            "gap_assessment": [{"capability": "精确火力", "grade": "关键差距"}],
            "concept_directions": [
                {"name": "无人侦察系统", "type": "new_capability"}
            ],
            "s6_quality_gate_failed": True,
            "s6_quality_gate_passed": False,
            "s6_quality_gate_issues": ["缺少与query契合的独立导弹方向"],
        },
    )

    assert [stage.gate_passed for stage in stages] == [True, True, True]
    assert not any(
        "S6能力画像质量门未通过" in item
        for item in stages[0].gate_reasons
    )
    assert not any(
        "S6能力画像质量门未通过" in item
        for item in stages[2].gate_reasons
    )
    audit = audit_run(
        store=store,
        coverage={"coverage_passed": True},
        max_rounds=2,
        analyst_confirmed=True,
        risk_based_confidence=True,
    )
    assert audit.checks["stage_gates_passed"] is True


def test_persisted_loop_trace_survives_report_only_resume() -> None:
    store = DomainStore()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L3",
            layer="L3",
            title="能力图像",
            outputs={
                "core_agent_analysis": {
                    "loop_trace": [
                        {"loop": "inner", "step": 6, "passed": True},
                        {"loop": "middle", "cycle": 1, "passed": True},
                    ]
                }
            },
            confidence=0.8,
            evidence_ids=["ev"],
            gate_passed=True,
            gate_reasons=[],
        )
    )

    assert _persisted_winning_loop_kinds(store) == {"inner", "middle"}


def test_quality_swarm_sessions_survive_report_only_architecture_audit() -> None:
    assert _codex_loops_recorded(
        mode="real",
        execution_profile_id="swarm_quality_v1",
        event_types=set(),
        persisted_loop_kinds=set(),
        session_agents={
            "winning_swarm_controller",
            "specialist-1234",
        },
    )


def test_final_report_reconciliation_clears_non_substantive_limited_status() -> None:
    checks = {
        "consistency": True,
        "stage_gates_passed": True,
        "confidence_ge_70": False,
        "coverage": True,
        "user_confirmation": True,
        "round_limit": True,
        "source_materialization": True,
    }
    audit = AuditResult(
        audit_id="audit-001",
        status="limited",
        checks=checks,
        comments=["报告模型曾采用降级路径。"],
    )

    reconciled = _reconcile_final_audit_status(audit, optimized_v2=True)

    assert reconciled.status == "approved"
    assert reconciled.checks["confidence_ge_70"] is True


def test_final_report_reconciliation_does_not_treat_publication_confirmation_as_quality_failure() -> None:
    checks = {
        "consistency": True,
        "stage_gates_passed": True,
        "confidence_ge_70": True,
        "coverage": True,
        "user_confirmation": False,
        "round_limit": True,
        "source_materialization": True,
    }
    audit = AuditResult(
        audit_id="audit-001",
        status="limited",
        checks=checks,
        comments=["分析师尚未确认，本次报告只能作为待审稿，不能作为正式发布版本。"],
    )

    reconciled = _reconcile_final_audit_status(audit, optimized_v2=True)

    assert reconciled.status == "approved"
    assert reconciled.checks["user_confirmation"] is False
    assert any("正式发布仍待人工确认" in item for item in reconciled.comments)


def test_final_report_reconciliation_preserves_real_quality_failure() -> None:
    checks = {
        "consistency": True,
        "stage_gates_passed": True,
        "confidence_ge_70": True,
        "coverage": False,
        "user_confirmation": False,
        "round_limit": True,
        "source_materialization": True,
    }
    audit = AuditResult(
        audit_id="audit-001",
        status="limited",
        checks=checks,
        comments=["覆盖不足。"],
    )

    reconciled = _reconcile_final_audit_status(audit, optimized_v2=True)

    assert reconciled.status == "limited"
    assert reconciled.checks["coverage"] is False


def test_final_report_reconciliation_preserves_failed_expert_judgement() -> None:
    audit = AuditResult(
        audit_id="audit-001",
        status="limited",
        checks={
            "consistency": True,
            "stage_gates_passed": True,
            "confidence_ge_70": True,
            "coverage": True,
            "user_confirmation": True,
            "round_limit": True,
            "source_materialization": True,
            "expert_judge_passed": False,
        },
        comments=["质量专家评判未通过。"],
    )

    reconciled = _reconcile_final_audit_status(audit, optimized_v2=True)

    assert reconciled.status == "limited"
    assert reconciled.checks["expert_judge_passed"] is False


def test_audit_accepts_reader_materialized_source() -> None:
    store = DomainStore()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L1",
            layer="L1",
            title="制胜逻辑",
            outputs={},
            confidence=0.8,
            evidence_ids=["ev"],
            gate_passed=True,
            gate_reasons=[],
        )
    )

    audit = audit_run(
        store=store,
        coverage={"coverage_passed": True},
        max_rounds=2,
        analyst_confirmed=True,
        source_materials=[{"status": "reader_fetched"}],
    )

    assert audit.checks["source_materialization"] is True
    assert audit.status == "approved"


def test_audit_rejects_source_failure_diagnostics() -> None:
    store = DomainStore()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L1",
            layer="L1",
            title="制胜逻辑",
            outputs={},
            confidence=0.8,
            evidence_ids=["ev"],
            gate_passed=True,
            gate_reasons=[],
        )
    )

    audit = audit_run(
        store=store,
        coverage={"coverage_passed": True},
        max_rounds=2,
        analyst_confirmed=True,
        source_materials=[
            {"status": "fetch_failed"},
            {"status": "fetch_blocked"},
            {"status": "network_safety_rejected"},
        ],
    )

    assert audit.checks["source_materialization"] is False
    assert audit.status == "limited"


def test_audit_uses_real_confirmation_and_round_count() -> None:
    audit = audit_run(
        store=DomainStore(),
        coverage={"coverage_passed": True},
        max_rounds=2,
        current_rounds=3,
        analyst_confirmed=False,
    )
    assert audit.checks["user_confirmation"] is False
    assert audit.checks["round_limit"] is False


def test_audit_never_approves_failed_winning_stage_gate() -> None:
    store = DomainStore()
    store.add_stage_output(
        WinningMechanismStageOutput(
            stage_id="stage-L1",
            layer="L1",
            title="gate limited",
            outputs={},
            confidence=0.9,
            evidence_ids=["ev-1"],
            gate_passed=False,
            gate_reasons=["coverage missing"],
        )
    )

    audit = audit_run(
        store=store,
        coverage={"coverage_passed": True},
        max_rounds=2,
        current_rounds=1,
        analyst_confirmed=True,
    )

    assert audit.status == "limited"
    assert audit.checks["stage_gates_passed"] is False
    assert any("L1" in comment for comment in audit.comments)
