from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from equipment_deep_research.agents.provider import (
    ResponsesAgentProvider,
)
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.workflows.baseline_execution import (
    _baseline_frontier_inspiration_instruction,
    _baseline_output_schema,
)
from equipment_deep_research.agents.workflows.coordinator import _typed_packet_payload
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard, ResearchProblem
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.context import compact_packet_handoff
from equipment_deep_research.harness.recovery import _restore_worker_reports
from equipment_deep_research.harness.scheduler import WorkerReport
from equipment_deep_research.harness.winning_core import _winning_task_budget
from equipment_deep_research.orchestration.admission import PacketAdmissionGate
from equipment_deep_research.orchestration.blueprints import (
    build_discovery_blueprint,
    execution_waves_from_blueprint,
)
from equipment_deep_research.orchestration.execution_contracts import (
    OPTIMIZED_V2_CONTRACTS,
    apply_execution_profile_to_blueprint,
    optimized_v2_profile,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.orchestration.runner import (
    _build_military_value_handoff,
    _is_unavailable_baseline_boundary,
    _merge_blueprint_and_analyst_agent_ids,
    _military_handoff_evidence_index,
    _minimal_military_value_handoff,
    _report_indicator_portrait,
)


def test_recovery_preserves_baseline_and_recall_reports_from_same_agent() -> None:
    baseline = WorkerReport(
        agent_id="combat_scenario",
        status="completed",
        new_evidence_ids=["ev-1"],
        packet_id="packet-combat_scenario",
        handoff_summary="baseline",
        session_path="combat_scenario.jsonl",
        worker_report_id="worker-report-baseline",
        created_at="2026-08-06T18:00:00+00:00",
    )
    recall = WorkerReport(
        agent_id="combat_scenario",
        status="completed",
        new_evidence_ids=["ev-2"],
        packet_id="packet-combat_scenario-r2",
        handoff_summary="recall",
        session_path="combat_scenario.jsonl",
        worker_report_id="worker-report-recall",
        created_at="2026-08-06T19:00:00+00:00",
    )

    restored = _restore_worker_reports(
        [baseline.__dict__, recall.__dict__, recall.__dict__]
    )

    assert [item.packet_id for item in restored] == [
        "packet-combat_scenario",
        "packet-combat_scenario-r2",
    ]


def test_optimized_v2_manual_agents_are_added_without_replacing_defaults() -> None:
    effective, defaults, requested, additions = _merge_blueprint_and_analyst_agent_ids(
        blueprint_agent_ids=["combat_scenario", "weapon_equipment", "operational_employment"],
        specialist_agent_ids=["system_confrontation"],
        analyst_agent_ids=["international_situation", "weapon_equipment"],
        preserve_blueprint_defaults=True,
    )

    assert defaults == [
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
        "system_confrontation",
    ]
    assert requested == ["international_situation", "weapon_equipment"]
    assert additions == ["international_situation"]
    assert effective == [
        "combat_scenario",
        "weapon_equipment",
        "operational_employment",
        "system_confrontation",
        "international_situation",
    ]


def test_abc_v2_contracts_encode_required_counts_and_cohorts() -> None:
    a = OPTIMIZED_V2_CONTRACTS["A"]
    b = OPTIMIZED_V2_CONTRACTS["B"]
    c = OPTIMIZED_V2_CONTRACTS["C"]

    assert a.background_count == 3
    assert a.scenarios_per_background == (2, 2)
    assert a.physical_cohorts == ((1, 2), (3, 4, 5))
    assert "thirty_capability_indicators" in a.branch_products
    assert a.soft_deadline_seconds == 0
    assert a.wall_clock_deadlines_enabled is False
    assert a.hard_deadline_seconds == 0
    assert a.delivery_grace_seconds == 0
    assert a.absolute_deadline_seconds == 0
    assert a.maximum_delivery_model_calls == 8
    assert a.maximum_swarm_model_calls == 20
    assert a.maximum_quality_judge_model_calls == 2
    assert b.physical_cohorts == ((1, 2, 3), (4, 5))
    assert b.step_intensity[4] == b.step_intensity[5] == "deep"
    assert a.step_intensity[6] == b.step_intensity[6] == "deep"
    assert c.step_intensity[1] == c.step_intensity[2] == "skip"
    assert c.physical_cohorts == ((3, 4, 5),)
    assert "six_case_patterns" in c.branch_products
    assert OPTIMIZED_V2_CONTRACTS["D"].physical_cohorts == ((3, 4, 5),)
    assert OPTIMIZED_V2_CONTRACTS["E"].physical_cohorts == ((3, 4, 5),)
    assert OPTIMIZED_V2_CONTRACTS["F"].physical_cohorts == ((3, 4, 5),)


def test_v2_blueprint_reserves_reporter_delivery_lane() -> None:
    blueprint = apply_execution_profile_to_blueprint(
        build_discovery_blueprint(ResearchProblem("test", discovery_branch="A")),
        optimized_v2_profile(),
    )

    assert blueprint["runtime_budgets"] == {
        "maximum_model_calls": 10,
        "maximum_model_calls_with_residuals": 14,
        "maximum_searches": 12,
        "codex_concurrency": 8,
        "s6_codex_concurrency": 32,
        "reporter_codex_concurrency": 12,
        "wall_clock_deadlines_enabled": False,
        "soft_deadline_seconds": 0,
        "hard_deadline_seconds": 0,
        "delivery_grace_seconds": 0,
        "absolute_deadline_seconds": 0,
        "maximum_delivery_model_calls": 8,
        "maximum_reporter_model_calls": 36,
        "maximum_swarm_model_calls": 20,
        "maximum_quality_judge_model_calls": 2,
        "deadline_downshift_window_seconds": 240,
        "critical_fast_finalize_seconds": 0,
        "delivery_retry_reserve_seconds": 45,
        "fast_finalize_output_token_cap": 4200,
    }


def test_optimized_winning_wrapper_defers_elapsed_time_to_execution_contract() -> None:
    budget = _winning_task_budget(
        {
            "max_turns": 5,
            "max_tool_calls": 30,
            "max_tokens": 12000,
            "max_seconds": 900,
        },
        optimized_v2=True,
    )

    assert budget == {
        "max_turns": 1,
        "max_tool_calls": 1,
        "max_tokens": 9000,
    }


def test_v2_business_agents_run_as_one_query_dominant_parallel_wave() -> None:
    international = AgentDef("international_situation", "I", "", ["situation"], [], {})
    scenario = AgentDef("combat_scenario", "C", "", ["scenario"], [], {})
    equipment = AgentDef("weapon_equipment", "E", "", ["equipment"], [], {})
    blueprint = apply_execution_profile_to_blueprint(
        build_discovery_blueprint(ResearchProblem("test", discovery_branch="A")),
        optimized_v2_profile(),
    )

    waves = execution_waves_from_blueprint(
        [international, scenario, equipment],
        blueprint,
        maximize_parallelism=True,
    )

    assert [[item.agent_id for item in wave] for wave in waves] == [[
        "international_situation",
        "combat_scenario",
        "weapon_equipment",
    ]]
    assert blueprint["baseline_execution_mode"] == "query_dominant_isolated_parallel"
    assert blueprint["execution_contract"]["logical_agent_dag"]["S2"] == ("S1",)


def test_packet_admission_binds_claims_and_rejects_unverified_packet() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-1",
        agent_id="weapon_equipment",
        capability_tags=["equipment"],
        topic_focus="西太能力缺口",
        findings=["公开资料表明现役链路存在差距"],
        evidence_ids=["ev-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="完成",
        checkpoint="done",
    )
    public = EvidenceCard(
        "ev-1", "source", "https://example.com/a", "A", "claim", "excerpt", "p1", "accepted", "weapon_equipment"
    )
    gate = PacketAdmissionGate()
    bundle = gate.extract_claim_bundle(packet, {"ev-1": public}, downstream_targets=["S4"])
    accepted = gate.evaluate(packet, bundle, {"ev-1": public}, task_terms=["西太", "能力缺口"])
    rejected = gate.evaluate(packet, bundle, {}, task_terms=["无关主题"])

    assert accepted.status == "accepted"
    assert bundle.claims[0].source_urls == ("https://example.com/a",)
    assert rejected.status == "rejected"


def test_unavailable_baseline_is_preserved_as_obligation_not_fake_claim() -> None:
    store = DomainStore()
    boundary = BaselineFindingPacket(
        packet_id="packet-weapon-equipment",
        agent_id="weapon_equipment",
        capability_tags=["equipment", "capability_gap"],
        topic_focus="不完备信息条件下精确打击",
        findings=[],
        evidence_ids=[],
        confidence=0.0,
        coverage_notes=["未形成可验证领域结论"],
        open_questions=["S4/S5按具体候选补充最近公开基线"],
        handoff_summary="装备基线受限",
        checkpoint="limited",
        limitations=["Codex CLI timeout"],
        payload_type="baseline_availability_boundary_v1",
        payload={
            "availability": "unavailable",
            "downstream_obligations": ["S4候选级核验", "S5汇总未决证据"],
        },
        admission_status="limited",
    )
    store.add_baseline_packet(boundary)

    handoff = _build_military_value_handoff(store, topic=boundary.topic_focus)

    assert _is_unavailable_baseline_boundary(boundary) is True
    assert handoff["claims"] == []
    assert handoff["baseline_boundaries"] == [
        {
            "packet_id": "packet-weapon-equipment",
            "agent_id": "weapon_equipment",
            "availability": "unavailable",
            "limitations": ["Codex CLI timeout"],
            "open_questions": ["S4/S5按具体候选补充最近公开基线"],
            "downstream_obligations": ["S4候选级核验", "S5汇总未决证据"],
        }
    ]
    assert handoff["statistics"]["limited_baseline_count"] == 1


def test_baseline_frontier_inspiration_is_model_authored_and_preserved() -> None:
    instruction = _baseline_frontier_inspiration_instruction()
    schema = _baseline_output_schema(SimpleNamespace(output_contract={}))
    inspiration = {
        "signal": "分布式低成本效应器正在改变高端拦截弹的交换关系",
        "conventional_assumption_challenged": "高性能平台必须由同等级高性能武器对抗",
        "possible_military_discontinuity": "把单件性能竞争改为可持续规模交换",
        "query_relevance": "影响不确定目标条件下精确火力的可承受试探成本",
        "evidence_boundary": "公开资料只证明趋势，是否形成制胜不连续性仍待验证",
        "source_urls": ["https://example.com/frontier"],
        "downstream_question": "什么装备架构能把规模优势转为直接且可控的军事效应",
    }
    _, payload, version = _typed_packet_payload(
        "combat_scenario",
        {
            "scenario_framework": "场景",
            "enemy_coa": "对手行动",
            "critical_timeline": "时间窗",
            "environment_constraints": "环境",
            "scenario_branches": ["分支"],
            "capability_pressure_points": ["压力点"],
            "assumptions": ["假设"],
            "frontier_inspirations": [inspiration],
        },
    )

    assert "frontier_inspirations" in schema
    assert "开放旁视" in instruction
    assert "没有成立信号就返回空数组" in instruction
    assert "技术类别、装备族、创新维度或数量配额" in instruction
    assert "不得提前给出成品方案" in instruction
    assert version == "2.0"
    assert payload["frontier_inspirations"] == [inspiration]


def test_military_handoff_carries_compact_frontier_inspiration_after_baseline() -> None:
    store = DomainStore()
    evidence = EvidenceCard(
        "ev-frontier",
        "公开前沿研究",
        "https://example.com/frontier",
        "A",
        "分布式效应器改变精确火力交换关系",
        "公开材料摘要",
        "p1",
        "accepted",
        "combat_scenario",
    )
    store.add_evidence(evidence)
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-scenario-frontier",
            agent_id="combat_scenario",
            capability_tags=["scenario"],
            topic_focus="不确定条件下精确打击",
            findings=["公开资料形成一条基线观察。"],
            evidence_ids=["ev-frontier"],
            confidence=0.78,
            coverage_notes=[],
            open_questions=[],
            handoff_summary="场景基线",
            checkpoint="done",
            payload={
                "frontier_inspirations": [
                    {
                        "signal": "分布式低成本效应器正在改变高端精确火力的交换关系",
                        "conventional_assumption_challenged": "精确效果依赖高成本单发武器",
                        "possible_military_discontinuity": "从单发命中竞争转为可承受的持续效果竞争",
                        "query_relevance": "影响不确定目标条件下的试探与补击成本",
                        "evidence_boundary": "公开资料支持趋势，不证明具体装备方案成立",
                        "source_urls": ["https://example.com/frontier"],
                        "downstream_question": "何种直接作战装备能形成可控持续效果",
                    }
                ]
            },
            admission_status="accepted",
        )
    )

    handoff = _build_military_value_handoff(
        store, topic="不确定条件下精确打击"
    )

    assert handoff["statistics"]["frontier_inspiration_count"] == 1
    item = handoff["frontier_inspirations"][0]
    assert item["packet_id"] == "packet-scenario-frontier"
    assert item["evidence_ids"] == ["ev-frontier"]
    assert item["status"] == "optional_post_divergence_inspiration"
    assert "首次自由发散后" in handoff["frontier_inspiration_rule"]
    assert handoff["claims"] == []
    downstream_evidence = _military_handoff_evidence_index(store, handoff)
    assert [item["evidence_id"] for item in downstream_evidence] == ["ev-frontier"]


def test_case_packet_handoff_preserves_full_branch_packet() -> None:
    packet = BaselineFindingPacket(
        packet_id="case-1",
        agent_id="case_research",
        capability_tags=["case_reconstruction"],
        topic_focus="局部战争案例",
        findings=[f"规律-{index}" for index in range(10)],
        evidence_ids=["ev-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="完整案例Packet",
        checkpoint="done",
        payload={"case_patterns": [f"模式-{index}" for index in range(10)]},
        claim_bundle_ref="claims-case-1",
        admission_status="accepted",
    )

    handoff = compact_packet_handoff(packet)

    assert len(handoff["key_findings"]) == 10
    assert len(handoff["payload"]["case_patterns"]) == 10
    assert handoff["claim_bundle_ref"] == "claims-case-1"


def test_military_value_handoff_filters_rejected_and_generic_baseline_text() -> None:
    store = DomainStore()
    evidence = EvidenceCard(
        "ev-1",
        "公开研究",
        "https://example.com/military",
        "A",
        "任务链受压后火力闭环失效",
        "公开材料摘要",
        "p1",
        "accepted",
        "combat_scenario",
    )
    store.add_evidence(evidence)
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-scenario",
            agent_id="combat_scenario",
            capability_tags=["scenario"],
            topic_focus="西太反介入任务链",
            findings=[
                "强电磁压制会阻断分布式节点协同并延迟火力闭环，削弱远程打击与区域拒止效果。",
                "本Agent使用Harness和Skill完成了既定流程。",
            ],
            evidence_ids=["ev-1"],
            confidence=0.84,
            coverage_notes=[],
            open_questions=["弱网条件下替代链路能否维持任务持续性"],
            handoff_summary="完成场景分析",
            checkpoint="done",
            limitations=["对手快速切换备份节点时结论可能失效"],
            admission_status="accepted",
        )
    )
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-rejected",
            agent_id="weapon_equipment",
            capability_tags=["equipment"],
            topic_focus="西太反介入任务链",
            findings=["现役装备可提升打击与威慑能力。"],
            evidence_ids=["ev-1"],
            confidence=0.9,
            coverage_notes=[],
            open_questions=[],
            handoff_summary="未通过",
            checkpoint="done",
            admission_status="rejected",
        )
    )

    handoff = _build_military_value_handoff(
        store,
        topic="挖掘西太反介入体系下的装备能力缺口",
    )

    assert handoff["schema"] == "military_value_handoff_v1"
    assert len(handoff["claims"]) == 1
    claim = handoff["claims"][0]
    assert claim["packet_id"] == "packet-scenario"
    assert "打击歼灭" in claim["military_effects"]
    assert "S2" in claim["downstream_steps"]
    assert claim["source_urls"] == ["https://example.com/military"]
    assert "Harness" not in str(handoff)
    assert handoff["statistics"]["selected_claim_count"] == 1


def test_minimal_military_value_handoff_only_projects_mechanism_and_effects() -> None:
    projected = _minimal_military_value_handoff(
        {
            "schema": "military_value_handoff_v1",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "mechanism": "前沿边缘节点支撑海上拒止、前沿协同和就地快速任务化。",
                    "military_effects": ["拦截反制", "拒止制衡", "生存抗毁"],
                    "failure_boundary": "通信受扰时失效",
                    "evidence_ids": ["ev-1"],
                    "source_urls": ["https://example.com"],
                    "downstream_steps": ["S1"],
                    "confidence": 0.9,
                }
            ],
            "baseline_boundaries": [{"packet_id": "packet-1"}],
            "statistics": {"selected_claim_count": 1},
        }
    )

    assert set(projected) == {"claims"}
    assert projected["claims"] == [
        {
            "mechanism": "前沿边缘节点支撑海上拒止、前沿协同和就地快速任务化。",
            "military_effects": ["拦截反制", "拒止制衡", "生存抗毁"],
        }
    ]


def test_military_handoff_evidence_index_expands_selected_equipment_packet() -> None:
    store = DomainStore()
    for evidence_id, title in (
        ("ev-weapon_equipment-web-prsm", "PrSM budget"),
        ("ev-weapon_equipment-web-jassm", "JASSM AGM-158 program"),
        ("ev-weapon_equipment-web-barracuda", "Barracuda production"),
    ):
        store.add_evidence(
            EvidenceCard(
                evidence_id,
                title,
                f"https://example.com/{evidence_id}",
                "A",
                title,
                "公开材料摘要",
                "p1",
                "accepted",
                "weapon_equipment",
            )
        )
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-weapon-equipment",
            agent_id="weapon_equipment",
            capability_tags=["equipment"],
            topic_focus="远程精确打击",
            findings=["多层远程火力形成互补毁伤链。"],
            evidence_ids=[
                "ev-weapon_equipment-web-prsm",
                "ev-weapon_equipment-web-jassm",
                "ev-weapon_equipment-web-barracuda",
            ],
            confidence=0.82,
            coverage_notes=[],
            open_questions=[],
            handoff_summary="装备证据包",
            checkpoint="done",
            admission_status="accepted",
        )
    )

    rows = _military_handoff_evidence_index(
        store,
        {
            "claims": [
                {
                    "packet_id": "packet-weapon-equipment",
                    "evidence_ids": ["ev-weapon_equipment-web-prsm"],
                }
            ]
        },
    )

    assert [row["evidence_id"] for row in rows] == [
        "ev-weapon_equipment-web-prsm",
        "ev-weapon_equipment-web-jassm",
        "ev-weapon_equipment-web-barracuda",
    ]


def test_report_indicator_portraits_preserve_s6_agent_differentiation() -> None:
    names = [
        "多模末制导反辐射防空压制导弹",
        "JASSM-ER类空射隐身防区外巡航导弹",
        "PrSM类地面发射远程精确制导导弹",
        "Barracuda-500M固定构型低成本巡航效应器",
        "批量可消耗低空无人携弹平台族",
    ]

    authored = [
        "以辐射源再捕获概率和压制窗口保持时间为轴，对照单模导引基线，诱饵下失配即判退。",
        "以防区外有效到达率和载机暴露时间为轴，对照现役空射基线，无法降低载机风险即判退。",
        "以射后转移完成时间和纵深毁伤闭环率为轴，对照现役地射基线，转移窗口失效即判退。",
        "以批次合格率和单位有效毁伤成本为轴，对照传统巡航弹基线，规模化优势不成立即判退。",
        "以同时在空平台数和授权后首轮释放时延为轴，对照有人平台基线，火力密度不足即判退。",
    ]
    portraits = [
        _report_indicator_portrait(
            SimpleNamespace(
                name=name,
                equipment_category=name,
                equipment_form=name,
                operational_mechanism="受扰条件下形成直接毁伤闭环",
                capability_gap="需分别校准任务指标",
                capability_type="upgrade" if index != 4 else "new_capability",
                indicator_portrait=authored[index],
            )
        )
        for index, name in enumerate(names)
    ]

    assert len(set(portraits)) == len(names)
    assert "辐射源再捕获概率" in portraits[0]
    assert "载机" in portraits[1]
    assert "射后转移" in portraits[2]
    assert "批次合格率" in portraits[3]
    assert "同时在空平台" in portraits[4]


def test_optimized_v2_executes_s1_s2_as_one_physical_call() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    phases: list[str] = []
    captured_inputs: list[dict[str, object]] = []

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del agent_id, system, max_output_tokens
        phases.append(phase)
        captured_inputs.append(payload)
        if "logical_results" in output_schema:
            logical = {}
            for step, schema in output_schema["logical_results"].items():
                logical[step] = {
                    key: (
                        0.8
                        if key == "confidence"
                        else {
                            "recognition": step,
                            "evidence_refs": ["packet-1"],
                            "confidence": 0.8,
                            "next_action": {"action": "continue", "target_step": 3, "reason": "done"},
                        }
                        if key == "reasoning_node"
                        else []
                    )
                    for key in schema
                }
            return json.dumps({"logical_results": logical}, ensure_ascii=False)
        raise AssertionError(f"unexpected phase: {phase}")

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "test",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {"primary_branch": "A"},
                "packets": [
                    {
                        "packet_id": "packet-1",
                        "agent_id": "combat_scenario",
                        "capability_tags": ["raw-tag"],
                        "handoff_summary": "场景压力指向任务链受扰后的打击与反制闭环。" * 20,
                        "findings": ["高价值发现"] * 10,
                        "payload": {"scenario_framework": ["场景"] * 20},
                        "evidence_ids": [f"ev-{index}" for index in range(20)],
                        "open_questions": ["原始开放问题"] * 10,
                    }
                ],
                "military_value_handoff": {
                    "schema": "military_value_handoff_v1",
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "claim_type": "inference",
                            "source_agent_id": "combat_scenario",
                            "packet_id": "packet-1",
                            "military_effects": ["打击歼灭", "拦截反制"],
                            "mechanism": "强电磁压力会延迟任务链并削弱打击反制闭环。",
                            "mission_condition": "任务区弱网强扰",
                            "failure_boundary": "存在替代链路时需重新验证",
                            "evidence_ids": ["ev-1"],
                            "source_urls": ["https://example.com/ev-1"],
                            "confidence": 0.82,
                            "downstream_steps": ["S1", "S2"],
                        }
                    ],
                },
                "evidence_index": [],
                "resume_steps": [1, 2],
                "execution_profile_id": "optimized_v2",
                "execution_contract": OPTIMIZED_V2_CONTRACTS["A"].to_dict(),
            }
        )
    )

    assert phases == ["winning_cohort-s1-s2"]
    cohort_input = captured_inputs[0]
    assert cohort_input["execution_profile_id"] == "optimized_v2"
    assert cohort_input["query"] == "test"
    assert cohort_input["discovery_blueprint"]["execution_profile_id"] == "optimized_v2"
    assert "coverage" not in cohort_input
    assert "packet_index" in cohort_input
    assert all(
        item["role_contract"]["objective"]
        and item["role_contract"]["military_test"]
        and item["role_contract"]["quality_gate"]
        for item in cohort_input["logical_contracts"]
    )
    assert all(
        "output_schema" not in item and item["required_output_fields"]
        for item in cohort_input["logical_contracts"]
    )
    assert all(
        item["role_contract"]["military_divergence_contract"]["primary_anchor"]
        == "query_military_problem"
        and item["role_contract"]["military_divergence_contract"][
            "minimum_competing_mechanisms"
        ]
        == 3
        for item in cohort_input["logical_contracts"]
    )
    assert "three_tactic_concepts" in cohort_input["required_branch_products"]
    assert cohort_input["packets"] == []
    assert cohort_input["packet_index"] == [
        {
            "packet_id": "packet-1",
            "agent_id": "combat_scenario",
            "evidence_ids": ["ev-0", "ev-1", "ev-2"],
            "confidence": None,
        }
    ]
    assert len(cohort_input["secondary_cross_agent_constraints"]) == 1
    handoff_claim = cohort_input["secondary_cross_agent_constraints"][0]
    assert set(handoff_claim) == {"mechanism", "military_effects"}
    assert handoff_claim["mechanism"].startswith("强电磁压力")
    assert cohort_input["analysis_priority"]["primary"] == [
        "current_agent_specialist_role_and_method",
        "query_military_problem",
        "direct_combat_value",
    ]
    assert "handoff_summary" not in str(cohort_input)
    completed = [row for row in result["subagent_runs"] if row.get("status") == "completed"]
    assert [row["step"] for row in completed] == [1, 2]
    assert all(row["physical_cohort_id"] == "cohort-s1-s2" for row in completed)


def test_optional_round_critic_budget_skip_does_not_fail_s_chain() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del agent_id, system, payload, max_output_tokens
        if phase == "winning_round_review":
            raise RuntimeError(
                "Harness v2 soft budget reached; optional model call skipped"
            )
        if "logical_results" in output_schema:
            return json.dumps(
                {
                    "logical_results": {
                        step: {
                            "confidence": 0.8,
                            "reasoning_node": {
                                "recognition": step,
                                "evidence_refs": ["packet-1"],
                                "confidence": 0.8,
                                "next_action": {
                                    "action": "continue",
                                    "target_step": 3,
                                    "reason": "done",
                                },
                            },
                        }
                        for step in output_schema["logical_results"]
                    }
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"unexpected phase: {phase}")

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "test",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {"primary_branch": "A"},
                "packets": [
                    {"packet_id": "packet-1", "agent_id": "combat_scenario"}
                ],
                "evidence_index": [],
                "resume_steps": [1, 2],
                "execution_profile_id": "optimized_v2",
                "execution_contract": OPTIMIZED_V2_CONTRACTS["A"].to_dict(),
            }
        )
    )

    assert result["round_critic_budget_skipped"] is True
    assert result["subagent_runs"][0]["physical_cohort_id"] == "cohort-s1-s2"
    assert any(
        row.get("event") == "budget_skip" for row in result["loop_trace"]
    )


def test_deadline_approach_keeps_s6_diagnostics_nonblocking_without_fallback(
    monkeypatch,
) -> None:
    class RealLikeProvider(ScriptedFakeProvider):
        pass

    backend = RealLikeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "soft_deadline_seconds": 600,
            "hard_deadline_seconds": 900,
            "deadline_downshift_window_seconds": 240,
            "critical_fast_finalize_seconds": 120,
            "delivery_grace_seconds": 120,
            "absolute_deadline_seconds": 1020,
        }
    )
    provider._run_started_at -= 700
    phases: list[str] = []

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del agent_id, system, payload, output_schema, max_output_tokens
        phases.append(phase)
        return json.dumps(
            {
                "concept_directions": [],
                "capability_image_drafts": [],
                "upstream_coverage": [],
                "branch_products": {},
                "evidence_validation": {
                    "all_ids_valid": True,
                    "invalid_ids": [],
                    "mismatched_claims": [],
                },
                "assumptions": [],
                "open_questions": [],
                "confidence": 0.8,
                "reasoning_node": {
                    "recognition": "保留首次能力画像",
                    "evidence_refs": [],
                    "confidence": 0.8,
                    "next_action": {
                        "action": "stop",
                        "target_step": 6,
                        "reason": "截止收敛",
                    },
                },
            },
            ensure_ascii=False,
        )

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._capability_direction_quality_issues",
        lambda result, *, handoff=None: [
            "S6第1项未说明具体作战阶段、任务对象及打击/反制效果"
        ],
    )

    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "test",
                "research_route": "cross_domain_fusion",
                "discovery_blueprint": {"primary_branch": "G"},
                "packets": [],
                "evidence_index": [],
                "resume_steps": [6],
                "execution_profile_id": "optimized_v2",
                "execution_contract": OPTIMIZED_V2_CONTRACTS["G"].to_dict(),
            }
        )
    )

    assert len(phases) == 1
    assert all(phase.startswith("winning_s6_image") for phase in phases)
    assert result["s6_quality_gate_passed"] is True
    assert result["s6_quality_gate_failed"] is False
    assert result["s6_quality_gate_limited"] is True
    assert "deadline_evidence_bounded_finalize" not in phases
    assert "transport_bounded_portfolio_closeout" not in phases


def test_s6_only_local_diagnostics_do_not_start_optional_round_rereview() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)

    def schema_value(key, schema):
        if key == "confidence":
            return 0.6
        if key == "reasoning_node":
            return {
                "recognition": "保留S6残差结果",
                "evidence_refs": [],
                "confidence": 0.6,
                "next_action": {
                    "action": "stop",
                    "target_step": 6,
                    "reason": "等待门控",
                },
            }
        if isinstance(schema, dict):
            return {}
        return []

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del agent_id, system, payload, max_output_tokens
        if phase == "winning_round_review":
            return json.dumps(
                {
                    "passed": False,
                    "rerun_from_step": 6,
                    "issues": ["S6置信度需复核"],
                    "affected_fields": [],
                    "rerun_guidance": ["仅修订S6"],
                    "rerun_steps": [6],
                    "requires_new_evidence": False,
                    "evidence_requests": [],
                },
                ensure_ascii=False,
            )
        if phase == "winning_round_rereview":
            raise RuntimeError(
                "Harness v2 soft budget reached; optional model call skipped"
            )
        return json.dumps(
            {
                key: schema_value(key, schema)
                for key, schema in output_schema.items()
            },
            ensure_ascii=False,
        )

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "test",
                "research_route": "war_case_learning",
                "discovery_blueprint": {"primary_branch": "C"},
                "packets": [],
                "evidence_index": [],
                "resume_steps": [6],
                "execution_profile_id": "optimized_v2",
                "execution_contract": OPTIMIZED_V2_CONTRACTS["C"].to_dict(),
            }
        )
    )

    assert "round_rereview_budget_skipped" not in result
    assert "concept_directions" in result
    assert result.get("middle_loop_limited", False) is False
    assert result["s6_quality_gate_passed"] is True
    assert not any(
        row.get("event") == "deterministic_rereview"
        for row in result["loop_trace"]
    )
