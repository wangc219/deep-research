from __future__ import annotations

import asyncio

import pytest

from equipment_deep_research.agents.workflows.orchestrator import (
    _deep_dialogue_technology_column_publishable,
    deep_contextual_dialogue,
)
from equipment_deep_research.agents.workflows.coordinator import _swarm_provider_isolation_id
from equipment_deep_research.deep_thinking import build_reference_capability


def _closed_proposal(name: str, *, angle: str = "任务链重构") -> dict:
    return {
        "name": name,
        "winning_angle": angle,
        "innovation_thesis": f"{name}改写发现与打击顺序",
        "changed_assumption": "发射后必须立即攻击",
        "equipment_form": "可潜伏展开的任务节点",
        "operational_mechanism": "贴附潜伏后按局部态势协同作用",
        "decisive_target": "高价值机动平台关键任务舱段",
        "direct_damage_mechanism": "进入脆弱区后释放定向物理效应造成结构破坏",
        "mission_kill_criterion": "目标关键任务舱段失效并退出当前任务周期",
        "direct_military_effects": "延迟触发并压缩目标机动窗口",
        "disruptive_difference": "从一次性弹药转为潜伏任务节点",
    }


_TECHNOLOGY_COLUMN_FIXTURE = (
    "联网检索公开论文、专利和标准后，比较现有集成、邻域迁移与前沿新技术三条路线，"
    "推荐以邻域迁移为主路径、现有集成为备选。核心瓶颈是复杂环境下作用稳定性与能量供给，"
    "攻关顺序为原理闭合、工程集成再到能力闭环；技术落装在载荷和控制接口，直接作用于目标识别与末端作用对象，"
    "通过新器件赋能并打开作战窗口。公开事实、类比迁移和研发推演分开说明，成熟度、迁移断点和验证边界明确。"
)


def test_deep_contextual_dialogue_runs_bounded_multi_agent_council() -> None:
    calls: list[tuple[str, str, dict, dict, int, str]] = []

    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            calls.append((agent_id, prompt, payload, schema, budget, phase))
            if phase == "deep_contextual_dialogue_divergence":
                role = payload["council_role"]["role"]
                return {
                    "agent_summary": f"{role}形成独立方向",
                    "proposals": [_closed_proposal(f"{role}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                assert len(payload["council_packets"]) == 3
                assert payload["adjudication_mission"]["primary_goal"]
                return {
                    "review_summary": "保留能夺先机制衡的颠覆方向，淘汰线性升级",
                    "mission_focus": "在 Query 局势下以杀伤链反转夺取先机并制衡对手",
                    "selection_order": ["候选甲", "候选乙"],
                    "candidate_reviews": [
                        {
                            "candidate_name": "候选甲",
                            "verdict": "keep",
                            "winning_logic_class": "disruptive",
                            "discontinuity_score": 0.9,
                            "mechanism_closure_score": 0.85,
                            "adversarial_resilience_score": 0.8,
                            "initiative_advantage_score": 0.88,
                            "query_scenario_fit_score": 0.86,
                            "direct_damage_closure_score": 0.9,
                            "distinctness_score": 0.8,
                            "initiative_claim": "更早进入并迫使对手暴露",
                            "counterbalance_claim": "以潜伏节点制衡高价值平台",
                            "decisive_issue": "真正改写进入时机",
                            "required_revision": "",
                        }
                    ],
                }
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                content = (
                    _TECHNOLOGY_COLUMN_FIXTURE
                    if payload["current_column"]["key"]
                    == "technology_implementation"
                    else f"{payload['current_column']['label']}完整正文"
                )
                return {"content": content}
            assert phase == "deep_contextual_dialogue_synthesis"
            assert len(payload["council_packets"]) == 3
            assert payload["adjudication"]["review_summary"]
            return {
                "visible_summary": ["基于已有卡片继续推演"],
                "selection_rationale": "经交叉审议形成稳定方向",
                "concept_directions": [{
                    "name": "新质候选",
                    "winning_angle": "任务链重构",
                    "changed_assumption": "发射后必须立即攻击",
                    "equipment_form": "可潜伏展开的任务节点",
                    "operational_mechanism": "贴附潜伏后按局部态势协同作用",
                    "decisive_target": "高价值机动平台关键任务舱段",
                    "direct_damage_mechanism": "进入脆弱区后释放定向物理效应造成结构破坏",
                    "mission_kill_criterion": "目标关键任务舱段失效并退出当前任务周期",
                    "direct_military_effects": "延迟触发并压缩目标机动窗口",
                    "disruptive_difference": "从一次性弹药转为潜伏任务节点",
                    "stable": True,
                }],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": _TECHNOLOGY_COLUMN_FIXTURE,
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
            }

    result = deep_contextual_dialogue(
        Host(), {"query": "单装备", "authoring_requested": True}
    )
    assert result["visible_summary"] == ["基于已有卡片继续推演"]
    assert len(calls) == 5
    divergence_calls = [item for item in calls if item[-1] == "deep_contextual_dialogue_divergence"]
    assert len(divergence_calls) == 3
    assert len({item[0] for item in divergence_calls}) == 3
    assert all("内部维度" in item[1] or "多维发散" in item[1] for item in divergence_calls)
    agent_id, prompt, payload, _schema, _budget, phase = next(
        item
        for item in calls
        if item[-1] == "deep_contextual_dialogue_synthesis"
    )
    assert agent_id == "deep_thinking_dialogue"
    assert phase == "deep_contextual_dialogue_synthesis"
    assert _budget == 7000
    # The wording may distinguish a hard prohibition ("绝不") from a
    # user-facing instruction ("不要"), but the contract is the same: this
    # entrypoint must not dispatch or simulate the baseline S1-S6 workflow.
    assert "颠覆传统制胜逻辑" in prompt or "先机制衡" in prompt
    assert "普通增程、增速、增精度" in prompt
    assert "A—O 命名类型" in prompt
    assert "命名重点核心 + 武器身份" in prompt
    assert all("命名重点核心 + 武器身份" in item[1] for item in divergence_calls)
    assert all("random_naming_style_assignment" in item[2] for item in divergence_calls)
    assert all("assumption_inversion" in item[1] for item in divergence_calls)
    assert all(
        item[2]["council_role"]["branching_protocol"]["branch_count"] == 3
        for item in divergence_calls
    )
    assert all(
        "战创灵境" in str(item[2].get("deep_parent_context", {}).get("identity", ""))
        for item in divergence_calls
    )
    column_calls = [item for item in calls if item[-1].startswith("deep_contextual_dialogue_s6_column_")]
    assert column_calls == []
    critic_prompt = next(
        item[1] for item in calls if item[-1] == "deep_contextual_dialogue_critique"
    )
    assert "先机" in critic_prompt
    assert "制衡" in critic_prompt
    assert "Query" in critic_prompt
    assert "incremental" in critic_prompt
    assert result["adjudication"]["mission_focus"]
    assert result["adjudication"]["candidate_reviews"][0]["verdict"] == "keep"
    assert "random_naming_style_assignment" in payload
    assigned = payload["random_naming_style_assignment"]["candidate_order"]
    assert len(assigned) == 3
    assert len({item["code"] for item in assigned}) == 3
    assert {item["code"] for item in assigned} <= set("ABCDEFGHIJKLMNO")
    assert "direct_evidence_refs" not in str(_schema)
    assert "validation_plan" not in str(_schema)
    assert "workflow_dispatch" not in payload
    assert result["orchestration"] == {
        "pattern": "internal_multidim_divergence_adversarial_review_synthesis",
        "rounds": 3,
        "phases": ["internal_multidim_divergence", "adversarial_review", "direction_synthesis"],
        "divergence_axes": [
            "颠覆·机理·链反转",
            "直接毁伤·末端效应·目标失能",
            "反适应·制衡·边界",
        ],
        "internal_dimensions": [
            "颠覆传统作战",
            "新质制胜逻辑",
            "任务链/杀伤链反转",
            "直接杀伤效应闭合",
            "目标脆弱性与末端作用",
            "感知/电磁赋能向物理毁伤兑现",
            "反适应韧性",
            "独特制衡手段",
            "边界条件突变",
        ],
        "requested_agents": 5,
        "completed_divergence_agents": 3,
        "degraded": False,
        "quality_gate_passed": False,
        "finalization_status": "awaiting_user_confirmation",
    }
    assert [item["round"] for item in result["agent_dialogue"]] == [
        "divergence", "divergence", "divergence", "critique", "synthesis"
    ]
    assert all(
        item.get("axis")
        for item in result["agent_dialogue"]
        if item["round"] == "divergence"
    )
    assert result["adjudication"]["candidate_reviews"][0]["verdict"] == "keep"
    assert result["adjudication"]["candidate_reviews"][0]["winning_logic_class"] == "disruptive"
    assert result["quality_gate"]["block_reasons"] == []
    assert result["capability_card_draft"] == {}
    assert result["concept_directions"][0]["innovation_variant_name"] == "新质候选"


def test_council_packet_keeps_three_counterfactual_branches_for_adjudication() -> None:
    from equipment_deep_research.agents.workflows.orchestrator import (
        _compact_council_packets_for_critic,
        _public_council_packet,
    )

    proposals = [
        {
            "name": f"分支{i}",
            "branch_id": f"b{i}",
            "branch_type": branch,
            "novelty_delta": f"改变第{i}个核心假设",
            "counterfactual_test": f"若{i}号边界不成立则回退",
            "research_probe": f"检索{i}号机理的公开可行性",
            "changed_assumption": f"假设{i}",
            "equipment_form": f"构型{i}",
            "operational_mechanism": f"机理{i}",
            "direct_military_effects": f"效果{i}",
            "disruptive_difference": f"差异{i}",
            "decisive_target": "目标任务舱段",
            "direct_damage_mechanism": "直接物理作用",
            "mission_kill_criterion": "任务失能",
        }
        for i, branch in enumerate(
            ("assumption_inversion", "mechanism_mutation", "boundary_inversion"),
            start=1,
        )
    ] + [{"name": "不应外抛的第四分支", "equipment_form": "构型"}]
    packet = _public_council_packet(
        {"agent_summary": "矩阵发散", "proposals": proposals},
        {"agent_id": "seat", "role": "三席", "axis": "正交"},
    )
    assert len(packet["proposals"]) == 3
    assert {item["branch_type"] for item in packet["proposals"]} == {
        "assumption_inversion",
        "mechanism_mutation",
        "boundary_inversion",
    }
    compact = _compact_council_packets_for_critic([packet])
    assert len(compact[0]["proposals"]) == 3
    assert all(item["counterfactual_test"] for item in compact[0]["proposals"])
    assert all(item["research_probe"] for item in compact[0]["proposals"])


def test_deep_dialogue_waits_for_user_confirmation_before_s6_authoring() -> None:
    calls: list[str] = []
    progress: list[dict] = []

    class Host:
        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, _prompt, payload, _schema, _budget, *, phase):
            calls.append(phase)
            if phase == "deep_contextual_dialogue_divergence":
                return {
                    "agent_summary": f"{agent_id}形成独立方向",
                    "proposals": [_closed_proposal(f"{agent_id}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                return {
                    "review_summary": "首选方向具备颠覆价值",
                    "mission_focus": "以任务链反转夺取先机",
                    "selection_order": ["确认前候选"],
                }
            assert phase == "deep_contextual_dialogue_synthesis"
            return {
                "visible_summary": ["候选已完成价值判断"],
                "selection_rationale": "机理与直接毁伤闭合",
                "concept_directions": [
                    {**_closed_proposal("确认前候选"), "stable": True}
                ],
            }

    result = deep_contextual_dialogue(
        Host(),
        {"query": "单装备", "authoring_requested": False},
    )

    assert not any(phase.startswith("deep_contextual_dialogue_s6_column_") for phase in calls)
    assert all(item.get("stage") != "s6_authoring" for item in progress)
    assert result["capability_card_draft"] == {}
    assert result["finalization_status"] == "awaiting_user_confirmation"
    assert result["quality_gate"]["direction_ready"] is True
    assert result["quality_gate"]["publishable"] is False
    assert result["orchestration"]["phases"][-1] == "direction_synthesis"


def test_deep_dialogue_technology_column_requires_retrieval_and_engineering_closure() -> None:
    assert _deep_dialogue_technology_column_publishable(_TECHNOLOGY_COLUMN_FIXTURE)
    assert not _deep_dialogue_technology_column_publishable(
        "采用先进材料、人工智能和无人化组件提升系统性能。"
    )


def test_normalize_adjudication_rejects_incremental_and_reranks_by_initiative() -> None:
    from equipment_deep_research.agents.workflows.orchestrator import _normalize_adjudication

    packets = [
        {
            "proposals": [
                {"name": "潜伏先机节点"},
                {"name": "增程换壳弹"},
            ]
        }
    ]
    result = _normalize_adjudication(
        {
            "review_summary": "原始摘要",
            "candidate_reviews": [
                {
                    "candidate_name": "增程换壳弹",
                    "verdict": "keep",
                    "winning_logic_class": "incremental",
                    "discontinuity_score": 0.2,
                    "mechanism_closure_score": 0.9,
                    "initiative_advantage_score": 0.2,
                    "query_scenario_fit_score": 0.2,
                    "adversarial_resilience_score": 0.2,
                    "distinctness_score": 0.2,
                },
                {
                    "candidate_name": "潜伏先机节点",
                    "verdict": "keep",
                    "winning_logic_class": "disruptive",
                    "discontinuity_score": 0.92,
                    "mechanism_closure_score": 0.88,
                    "initiative_advantage_score": 0.9,
                    "query_scenario_fit_score": 0.87,
                    "direct_damage_closure_score": 0.92,
                    "adversarial_resilience_score": 0.84,
                    "distinctness_score": 0.8,
                    "initiative_claim": "先手进入压缩决策窗",
                    "counterbalance_claim": "以低成本节点制衡高价值平台",
                },
            ],
            "selection_order": ["增程换壳弹", "潜伏先机节点"],
        },
        packets,
    )

    by_name = {item["candidate_name"]: item for item in result["candidate_reviews"]}
    assert by_name["增程换壳弹"]["verdict"] == "reject"
    assert by_name["潜伏先机节点"]["verdict"] == "keep"
    assert result["selection_order"][0] == "潜伏先机节点"
    assert "先机" in result["mission_focus"] or "制衡" in result["mission_focus"]


def test_normalize_adjudication_backfills_missing_reviews_and_selects() -> None:
    from equipment_deep_research.agents.workflows.orchestrator import _normalize_adjudication

    packets = [
        {
            "role": "新质颠覆架构 Agent",
            "proposals": [_closed_proposal("蜂巢式自适应攻击无人机")],
        },
        {
            "role": "直接毁伤机理 Agent",
            "proposals": [_closed_proposal("增程换壳弹")],
        },
    ]
    result = _normalize_adjudication(
        {"review_summary": "", "candidate_reviews": [], "selection_order": []},
        packets,
    )

    by_name = {item["candidate_name"]: item for item in result["candidate_reviews"]}
    assert result["adjudication_complete"] is True
    assert by_name["蜂巢式自适应攻击无人机"]["verdict"] == "keep"
    assert by_name["增程换壳弹"]["verdict"] == "reject"
    assert result["selection_order"][0] == "蜂巢式自适应攻击无人机"
    assert "增程换壳弹" not in result["selection_order"]


def test_normalize_adjudication_preserves_seat_diversity_when_scores_are_close() -> None:
    from equipment_deep_research.agents.workflows.orchestrator import _normalize_adjudication

    packets = [
        {"role": "席位A", "proposals": [_closed_proposal("A1"), _closed_proposal("A2")]},
        {"role": "席位B", "proposals": [_closed_proposal("B1")]},
        {"role": "席位C", "proposals": [_closed_proposal("C1")]},
    ]
    result = _normalize_adjudication(
        {"selection_order": ["A1", "A2", "B1", "C1"]}, packets
    )
    assert result["selection_order"][:3] == ["A1", "B1", "C1"]


def test_deep_contextual_dialogue_completes_adjudication_when_critic_fails() -> None:
    progress: list[dict] = []

    class Host:
        def _emit_deep_dialogue_progress(self, row):
            progress.append(row)

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                return {
                    "agent_summary": f"{agent_id}形成直接毁伤候选",
                    "proposals": [_closed_proposal(f"{agent_id}候选")],
                }
            if phase.startswith("deep_contextual_dialogue_critique"):
                raise TimeoutError("critic unavailable")
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                content = (
                    _TECHNOLOGY_COLUMN_FIXTURE
                    if payload["current_column"]["key"]
                    == "technology_implementation"
                    else f"{payload['current_column']['label']}完整正文"
                )
                return {"content": content}
            return {
                "visible_summary": ["本地裁决后完成成卡"],
                "selection_rationale": "按已回填裁决继续",
                "concept_directions": [
                    {
                        **_closed_proposal("蜂巢式自适应攻击无人机"),
                        "stable": True,
                    }
                ],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": _TECHNOLOGY_COLUMN_FIXTURE,
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
            }

    result = deep_contextual_dialogue(Host(), {"query": "单装备"})
    assert result["adjudication"]["adjudication_complete"] is True
    assert result["adjudication"]["candidate_reviews"]
    assert result["adjudication"]["selection_order"]
    assert {item["verdict"] for item in result["adjudication"]["candidate_reviews"]} <= {
        "keep",
        "revise",
        "reject",
    }
    critique_events = [
        item
        for item in progress
        if item.get("stage") == "council_critique" and item.get("kind") == "answer"
    ]
    assert critique_events
    assert critique_events[-1]["status"] == "completed"
    assert critique_events[-1]["proposal_names"]


def test_deep_contextual_dialogue_compacts_agent_handoffs() -> None:
    captured: dict[str, list[dict]] = {}
    captured_prompts: dict[str, list[str]] = {}

    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            captured.setdefault(phase, []).append(payload)
            captured_prompts.setdefault(phase, []).append(prompt)
            if phase == "deep_contextual_dialogue_divergence":
                return {"agent_summary": "独立提案", "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "通过", "selection_order": []}
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                content = (
                    _TECHNOLOGY_COLUMN_FIXTURE
                    if payload["current_column"]["key"]
                    == "technology_implementation"
                    else "栏正文" * 2000
                )
                return {"content": content}
            return {"visible_summary": [], "concept_directions": []}

    deep_contextual_dialogue(
        Host(),
        {
            "run_id": "run-context-budget",
            "topic": "装备创新",
            "question": "形成直接毁伤新质装备",
            "authoring_requested": False,
            "existing_result": {"id": "canonical", "raw": "旧结果" * 6000},
            "evidence_index": [{"text": "证据" * 6000}],
            "deep_parent_context": {
                "source_equipment": {
                    "name": "基线巡飞弹",
                    "equipment_form": "分布式巡飞弹",
                    "failure_boundary": "不应传递",
                    "evidence": "不应传递",
                },
                "prior_expert_questions": ["历史问题" * 1000] * 8,
                "prior_round_conclusions": "上一轮结论" * 1000,
                "raw_session": "不应传递",
            },
        },
    )

    divergence = captured["deep_contextual_dialogue_divergence"]
    assert len(divergence) == 3
    assert all("existing_result" not in item for item in divergence)
    assert all("evidence_index" not in item for item in divergence)
    assert all("raw_session" not in str(item) for item in divergence)
    assert all(len(str(item)) < 9000 for item in divergence)
    assert all(
        "[Active procedural skills" in prompt
        for prompt in captured_prompts["deep_contextual_dialogue_divergence"]
    )
    assert all(
        item["deep_parent_context"]["source_equipment"]["name"]
        == "基线巡飞弹"
        for item in divergence
    )

    critic = captured["deep_contextual_dialogue_critique"][0]
    assert "random_naming_style_assignment" not in critic
    assert len(critic["council_packets"]) == 3
    assert all("random_naming_style_assignment" in item for item in divergence)
    first_codes = [
        item["random_naming_style_assignment"]["candidate_order"][0]["code"]
        for item in divergence
    ]
    assert len(set(first_codes)) == 3
    assert {item["code"] for row in divergence for item in row["random_naming_style_assignment"]["candidate_order"]} <= set("ABCDEFGHIJKLMNO")

    synthesis = captured["deep_contextual_dialogue_synthesis"][0]
    assert "random_naming_style_assignment" in synthesis
    assert "existing_result" not in synthesis

    # A council handoff is analysis-only. S6 receives a separate confirmed
    # turn after this direction has been committed to working memory.
    columns = [
        payload
        for phase, payloads in captured.items()
        if phase.startswith("deep_contextual_dialogue_s6_column_")
        for payload in payloads
    ]
    assert columns == []


def test_deep_contextual_dialogue_degrades_when_one_proposer_fails() -> None:
    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if agent_id == "deep_dialogue_adversary_red_team":
                raise TimeoutError("bounded role timeout")
            if phase == "deep_contextual_dialogue_divergence":
                return {"agent_summary": "保留提案", "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "按单路角色继续", "selection_order": []}
            return {"visible_summary": ["降级完成"], "concept_directions": []}

    result = deep_contextual_dialogue(Host(), {"query": "单装备"})

    assert result["visible_summary"] == ["降级完成"]
    assert result["orchestration"]["degraded"] is True
    assert result["orchestration"]["completed_divergence_agents"] == 2
    assert result["orchestration"]["requested_agents"] == 5


def test_deep_contextual_dialogue_preserves_ranked_candidates_when_synthesis_fails() -> None:
    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                return {
                    "agent_summary": f"{agent_id}形成直接毁伤候选",
                    "proposals": [_closed_proposal(f"{agent_id}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                return {
                    "review_summary": "优先保留任务节点直接失能方向",
                    "mission_focus": "以物理毁伤闭合任务失能",
                    "selection_order": ["deep_dialogue_terminal_effect_architect候选"],
                }
            raise TimeoutError("final authoring deadline")

    result = deep_contextual_dialogue(
        Host(), {"query": "单装备", "authoring_requested": False}
    )

    assert result["deep_divergence_status"] == "partial"
    assert result["finalization_status"] == "awaiting_user_confirmation"
    assert result["quality_gate"]["publishable"] is False
    assert result["quality_gate"]["non_blocking"] is True
    assert result["research_assessment"]["research_complete"] is True
    assert result["orchestration"]["degraded"] is True
    assert result["concept_directions"][0]["name"] == (
        "deep_dialogue_terminal_effect_architect候选"
    )
    assert result["concept_directions"][0]["decisive_target"]
    assert result["concept_directions"][0]["direct_damage_mechanism"]
    assert result["concept_directions"][0]["mission_kill_criterion"]
    assert result["quality_gate"]["block_reasons"] == []
    assert result["quality_gate"]["non_blocking"] is True


def test_deep_contextual_dialogue_retries_synthesis_with_compact_payload() -> None:
    synthesis_phases: list[str] = []

    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                return {
                    "agent_summary": f"{agent_id}形成直接毁伤候选",
                    "proposals": [_closed_proposal(f"{agent_id}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                return {
                    "review_summary": "优先保留任务节点直接失能方向",
                    "mission_focus": "以物理毁伤闭合任务失能",
                    "selection_order": ["deep_dialogue_terminal_effect_architect候选"],
                }
            if phase.startswith("deep_contextual_dialogue_synthesis"):
                synthesis_phases.append(phase)
            if phase == "deep_contextual_dialogue_synthesis":
                raise TimeoutError("first authoring transport timeout")
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                content = (
                    _TECHNOLOGY_COLUMN_FIXTURE
                    if payload["current_column"]["key"]
                    == "technology_implementation"
                    else f"{payload['current_column']['label']}完整正文"
                )
                return {"content": content}
            assert phase == "deep_contextual_dialogue_synthesis_retry"
            assert budget == 6500
            assert len(payload["council_packets"]) == 3
            assert all(len(item["proposals"]) <= 2 for item in payload["council_packets"])
            return {
                "visible_summary": ["自动续写完成五栏成卡"],
                "selection_rationale": "直接毁伤闭合且具备非对称制衡",
                "concept_directions": [
                    {
                        **_closed_proposal("续写候选"),
                        "stable": True,
                    }
                ],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": _TECHNOLOGY_COLUMN_FIXTURE,
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
            }

    result = deep_contextual_dialogue(
        Host(), {"query": "单装备", "authoring_requested": False}
    )

    assert synthesis_phases == [
        "deep_contextual_dialogue_synthesis",
        "deep_contextual_dialogue_synthesis_retry",
    ]
    assert result["finalization_status"] == "awaiting_user_confirmation"
    assert result["orchestration"]["quality_gate_passed"] is False
    assert result["quality_gate"]["publishable"] is False


def test_deep_contextual_dialogue_drops_thin_linear_upgrades() -> None:
    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                return {
                    "agent_summary": "只给了名字",
                    "proposals": [{"name": f"{agent_id}-增速版", "winning_angle": "增程增速"}],
                }
            if phase == "deep_contextual_dialogue_critique":
                raise AssertionError("thin proposals must not reach critique")
            return {"visible_summary": []}

    try:
        deep_contextual_dialogue(Host(), {"query": "单装备"})
        raise AssertionError("expected empty council to raise")
    except RuntimeError as exc:
        assert "no proposals" in str(exc)


def test_deep_contextual_dialogue_keeps_incomplete_s6_as_non_blocking_draft() -> None:
    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                return {"agent_summary": "独立提案", "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "需要补全", "selection_order": []}
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                return {"content": "只有概述"}
            raise AssertionError(f"unexpected phase: {phase}")

    result = deep_contextual_dialogue(
        Host(),
        {
            "query": "单装备",
            "question": "/card",
            "authoring_requested": True,
            "deep_parent_context": {
                "working_memory": {
                    "candidate_directions": [_closed_memory_direction()],
                    "finalization_status": "awaiting_user_confirmation",
                }
            },
        },
    )

    assert result["finalization_status"] == "candidate_ready"
    assert result["quality_gate"]["publishable"] is True
    assert result["quality_gate"]["non_blocking"] is True
    assert result["quality_gate"]["candidate_reviews"][0]["closure_score"] == 1.0
    assert result["orchestration"]["quality_gate_passed"] is True
    assert result["quality_gate"]["block_reasons"] == []
    assert any("S6" in gap for gap in result["research_gaps"])


def test_deep_contextual_dialogue_emits_live_mid_phase_progress() -> None:
    progress: list[dict] = []

    class Host:
        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                role = payload["council_role"]["role"]
                return {
                    "agent_summary": f"{role}形成独立方向",
                    "proposals": [_closed_proposal(f"{role}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                return {
                    "review_summary": "保留颠覆方向",
                    "mission_focus": "夺取先机制衡",
                    "selection_order": ["候选甲"],
                    "candidate_reviews": [
                        {
                            "candidate_name": "候选甲",
                            "verdict": "keep",
                            "winning_logic_class": "disruptive",
                            "discontinuity_score": 0.9,
                            "mechanism_closure_score": 0.85,
                            "adversarial_resilience_score": 0.8,
                            "initiative_advantage_score": 0.88,
                            "query_scenario_fit_score": 0.86,
                            "direct_damage_closure_score": 0.9,
                            "distinctness_score": 0.8,
                        }
                    ],
                }
            return {
                "visible_summary": ["完整总结"],
                "selection_rationale": "保留可写入画像的方向",
                "concept_directions": [{
                    "name": "新质候选",
                    "winning_angle": "任务链重构",
                    "changed_assumption": "发射后必须立即攻击",
                    "equipment_form": "可潜伏展开的任务节点",
                    "operational_mechanism": "贴附潜伏后按局部态势协同作用",
                    "decisive_target": "高价值机动平台关键任务舱段",
                    "direct_damage_mechanism": "进入脆弱区后释放定向物理效应造成结构破坏",
                    "mission_kill_criterion": "目标关键任务舱段失效并退出当前任务周期",
                    "direct_military_effects": "延迟触发并压缩目标机动窗口",
                    "disruptive_difference": "从一次性弹药转为潜伏任务节点",
                    "stable": True,
                }],
                "capability_card_draft": {
                    "overview": "完整概述",
                    "technology_implementation": _TECHNOLOGY_COLUMN_FIXTURE,
                    "operational_process": "完整关键作战流程",
                    "capability_effects": "完整能力与作战效果",
                    "winning_logic": "完整制胜逻辑机理",
                },
            }

    result = deep_contextual_dialogue(
        Host(), {"query": "单装备", "authoring_requested": False}
    )

    stages = [item.get("stage") for item in progress]
    assert "s3_divergence" in stages
    assert "council_critique" in stages
    assert "s4_mapping" in stages
    assert "s6_authoring" not in stages
    answer_rows = [item for item in progress if item.get("kind") == "answer" and item.get("text")]
    assert len(answer_rows) >= 3
    assert any(item.get("round") == "divergence" for item in answer_rows)
    assert any(item.get("round") == "critique" for item in answer_rows)
    assert any(item.get("round") == "synthesis" for item in answer_rows)
    assert result["quality_gate"]["publishable"] is False


def test_deep_dialogue_roles_receive_distinct_stable_provider_sessions() -> None:
    agent_ids = [
        "deep_dialogue_doctrine_breaker",
        "deep_dialogue_terminal_effect_architect",
        "deep_dialogue_adversary_red_team",
        "deep_dialogue_adversarial_judge",
        "deep_thinking_dialogue",
    ]
    first = [
        _swarm_provider_isolation_id(agent_id, {"input": {"run_id": "run-council"}})
        for agent_id in agent_ids
    ]
    replay = [
        _swarm_provider_isolation_id(agent_id, {"input": {"run_id": "run-council"}})
        for agent_id in agent_ids
    ]

    assert first == replay
    assert all(item.startswith("deep-dialogue-") for item in first)
    assert len(set(first)) == len(agent_ids)


def test_reference_capability_exposes_canonical_equipment_and_effect_fields() -> None:
    artifact = build_reference_capability(
        run_id="run-1",
        query="低空目标拦截",
        candidate={
            "name": "参考拦截无人机",
            "equipment_form": "末段拦截无人机",
            "hypothesis_id": "hypothesis-1",
            "card_binding_id": "binding-1",
            "operational_mechanism": "弹上复核压缩末段交战窗口",
            "direct_military_effects": "直接拦截低空目标",
            "failure_boundary": "强干扰条件下识别可能退化",
            "validation_plan": "开展仿真与实装复核",
            "evidence_ids": ["ev-1"],
        },
    )

    assert artifact["equipment_form"] == "末段拦截无人机"
    assert artifact["equipment_forms"] == ["末段拦截无人机"]
    assert artifact["primary_equipment_identity"] == "参考拦截无人机"
    assert artifact["operational_mechanism"] == "弹上复核压缩末段交战窗口"
    assert artifact["mechanism_chain"] == artifact["operational_mechanism"]
    assert artifact["direct_military_effects"] == "直接拦截低空目标"
    assert artifact["military_value"] == artifact["direct_military_effects"]
    assert artifact["failure_boundary"] == "强干扰条件下识别可能退化"
    assert artifact["validation_plan"] == "开展仿真与实装复核"
    assert artifact["portrait_authoring_status"] == "pending_s6_authoring"
    assert artifact["analysis_provenance_status"] == "pending_authoring"
    assert artifact["capability_card_status"] == "analysis_only_pending_authoring"
    assert artifact["capability_portrait_modules"] == {
        "overview": "",
        "technology_implementation": "",
        "operational_process": "",
        "capability_effects": "",
        "winning_logic": "",
    }


def test_innovation_capability_uses_variant_identity_and_s6_five_modules() -> None:
    artifact = build_reference_capability(
        run_id="run-innovation",
        query="穿透遮蔽空间",
        candidate={
            "name": "折脊穿隙攻击无人机",
            "source_equipment_identity": "折脊穿隙攻击无人机",
            "innovation_variant_name": "折脊蜂巢潜伏节点",
            "innovation_equipment_form": "可贴附展开的潜伏式任务节点",
            "innovation_thesis": "由一次性穿隙攻击器改造成可潜伏协同节点",
            "winning_angle": "任务链重构",
            "changed_assumption": "进入目标区后必须立即攻击",
            "novelty": "从弹药变为可重构任务节点",
            "operational_mechanism": "贴附潜伏后按局部态势展开并协同作用",
            "direct_military_effects": "延迟触发并压缩目标机动窗口",
            "hypothesis_id": "innovation-1",
            "capability_card_draft": {
                "overview": "五栏概述",
                "technology_implementation": "五栏装备与技术实现",
                "operational_process": "五栏关键作战流程",
                "capability_effects": "五栏能力与作战效果",
                "winning_logic": "五栏制胜逻辑机理",
            },
        },
    )

    assert artifact["name"] == "折脊蜂巢潜伏节点"
    assert artifact["source_equipment_identity"] == "折脊穿隙攻击无人机"
    assert artifact["equipment_form"] == "可贴附展开的潜伏式任务节点"
    assert artifact["winning_angle"] == "任务链重构"
    assert artifact["capability_portrait_modules"] == {
        "overview": "五栏概述",
        "technology_implementation": "五栏装备与技术实现",
        "operational_process": "五栏关键作战流程",
        "capability_effects": "五栏能力与作战效果",
        "winning_logic": "五栏制胜逻辑机理",
    }


@pytest.mark.parametrize("task_count", [1, 2])
def test_real_runtime_planner_controls_probe_count_and_quality_dimensions(task_count: int) -> None:
    progress: list[dict] = []
    planner_tasks = [
        {
            "task_id": f"dimension-{index}",
            "role": f"制胜维度探针 {index}",
            "axis": f"独立研究轴 {index}",
            "question": f"如何验证制胜维度 {index}？",
            "lens": "寻找先机、最低成本反制和直接物理毁伤闭环。",
            "internal_dimensions": ["先机来源", "反例", "验证边界"],
            "winning_logic_dimension": f"非对称制胜维度 {index}",
            "countermeasure_dimension": f"对手最低成本反制 {index}",
            "direct_damage_closure": "构型到直接物理毁伤再到任务失能",
            "query_scenario_fit": "贴合当前 Query 场景",
            "merge_contract": "返回结论、反例、边界和下一验证问题",
        }
        for index in range(1, task_count + 1)
    ]

    class Host:
        supports_agent_runtime = True

        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            del prompt, schema, budget
            if phase == "deep_contextual_dialogue_task_planning":
                return {
                    "planning_summary": "按不同制胜维度拆分",
                    "winning_logic_dimensions": [
                        item["winning_logic_dimension"] for item in planner_tasks
                    ],
                    "tasks": planner_tasks,
                }
            if phase == "deep_contextual_dialogue_divergence":
                return {
                    "agent_summary": payload["council_role"]["role"],
                    "proposals": [_closed_proposal(f"{agent_id}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                return {
                    "review_summary": "按制胜维度完成对抗裁决",
                    "mission_focus": "夺取先机并保持非对称收益",
                    "candidate_reviews": [],
                    "selection_order": [],
                }
            assert phase == "deep_contextual_dialogue_synthesis"
            return {
                "visible_summary": ["完成动态探针综合"],
                "selection_rationale": "按实际探针维度收敛",
                "concept_directions": [],
                "capability_card_draft": {},
            }

    result = deep_contextual_dialogue(Host(), {"query": "验证动态制胜逻辑"})
    assert result["orchestration"]["planned_probe_count"] == task_count
    assert result["orchestration"]["requested_agents"] == task_count + 2
    starts = [
        row for row in progress
        if row.get("event_type") == "deep_agent_started"
        and row.get("parallel_group") == "deep_dialogue_council"
    ]
    assert len(starts) == task_count
    assert {row["total_count"] for row in starts} == {task_count}
    assert {row["parallelism"] for row in starts} == {task_count}
    assert set(result["orchestration"]["winning_logic_dimensions"]) == {
        item["winning_logic_dimension"] for item in planner_tasks
    }


def test_real_runtime_planner_failure_degrades_to_one_generic_probe() -> None:
    progress: list[dict] = []

    class Host:
        supports_agent_runtime = True

        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            del prompt, payload, schema, budget
            if phase == "deep_contextual_dialogue_task_planning":
                raise TimeoutError("planner unavailable")
            if phase == "deep_contextual_dialogue_divergence":
                return {"agent_summary": agent_id, "proposals": [_closed_proposal("降级候选")]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "完成", "mission_focus": "夺取先机", "candidate_reviews": [], "selection_order": []}
            assert phase == "deep_contextual_dialogue_synthesis"
            return {"visible_summary": ["完成"], "selection_rationale": "单探针降级", "concept_directions": [], "capability_card_draft": {}}

    result = deep_contextual_dialogue(Host(), {"query": "规划器故障恢复"})
    assert result["orchestration"]["planned_probe_count"] == 1
    assert result["orchestration"]["planning_source"] == "fallback"
    assert result["orchestration"]["requested_agents"] == 3
    starts = [
        row for row in progress
        if row.get("event_type") == "deep_agent_started"
        and row.get("parallel_group") == "deep_dialogue_council"
    ]
    assert len(starts) == 1
    assert starts[0]["total_count"] == starts[0]["parallelism"] == 1


def test_deep_contextual_dialogue_reports_council_results_in_completion_order() -> None:
    progress: list[dict] = []
    delays = {
        "deep_dialogue_doctrine_breaker": 0.03,
        "deep_dialogue_terminal_effect_architect": 0.01,
        "deep_dialogue_adversary_red_team": 0.02,
    }

    class Host:
        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                await asyncio.sleep(delays[agent_id])
                return {"agent_summary": agent_id, "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "通过", "mission_focus": "夺取先机", "selection_order": []}
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                return {"content": _TECHNOLOGY_COLUMN_FIXTURE}
            if phase == "deep_contextual_dialogue_synthesis":
                return {
                    "visible_summary": ["完成"], "selection_rationale": "通过",
                    "concept_directions": [],
                    "capability_card_draft": {
                        "overview": "概述", "technology_implementation": _TECHNOLOGY_COLUMN_FIXTURE,
                        "operational_process": "流程", "capability_effects": "效果", "winning_logic": "逻辑",
                    },
                }
            raise AssertionError(phase)

    deep_contextual_dialogue(Host(), {"query": "单装备"})
    starts = [item for item in progress if item.get("parallel_group") == "deep_dialogue_council" and item.get("role") and item.get("kind") == "summary"]
    completions = [item for item in progress if item.get("parallel_group") == "deep_dialogue_council" and item.get("kind") == "answer"]
    assert [item["role"] for item in completions] == [
        "直接毁伤机理 Agent", "反适应制衡 Agent", "新质颠覆架构 Agent"
    ]
    assert len(starts) == 3
    assert all(item["event_type"] == "deep_agent_started" for item in starts)
    assert all(item["event_type"] == "deep_agent_completed" for item in completions)
    assert all(item["parallel"] is True and item["parallelism"] == 3 for item in starts + completions)
    for completion in completions:
        matching = next(item for item in starts if item["role"] == completion["role"])
        assert progress.index(matching) < progress.index(completion)
    handoffs = [item for item in progress if item.get("event_type") == "deep_agent_handoff"]
    assert [(item["from_agent_id"], item["to_agent_id"]) for item in handoffs] == [
        ("deep_dialogue_council", "deep_dialogue_adversarial_judge"),
        ("deep_dialogue_adversarial_judge", "deep_thinking_dialogue"),
    ]
    assert handoffs[0]["deliverable_refs"]


def test_deep_contextual_dialogue_reports_failed_branch_and_handoffs_survivors() -> None:
    progress: list[dict] = []

    class Host:
        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                if agent_id == "deep_dialogue_doctrine_breaker":
                    raise TimeoutError("branch deadline")
                return {"agent_summary": agent_id, "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "通过", "mission_focus": "夺取先机", "selection_order": []}
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                return {"content": _TECHNOLOGY_COLUMN_FIXTURE}
            if phase == "deep_contextual_dialogue_synthesis":
                return {
                    "visible_summary": ["完成"],
                    "selection_rationale": "通过",
                    "concept_directions": [],
                    "capability_card_draft": {},
                }
            raise AssertionError(phase)

    result = deep_contextual_dialogue(Host(), {"query": "单装备"})

    failed = [item for item in progress if item.get("event_type") == "deep_agent_failed"]
    assert failed[0]["agent_id"] == "deep_dialogue_doctrine_breaker"
    handoff = next(item for item in progress if item.get("event_type") == "deep_agent_handoff")
    assert handoff["completed_count"] == 2
    assert result["orchestration"]["completed_divergence_agents"] == 2
    assert result["orchestration"]["degraded"] is True


def test_deep_contextual_dialogue_uses_query_weapons_as_leap_baseline() -> None:
    captured: dict[str, list] = {}

    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            captured.setdefault(phase, []).append((prompt, payload))
            if phase == "deep_contextual_dialogue_divergence":
                return {"agent_summary": "独立提案", "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "通过", "mission_focus": "夺取先机", "selection_order": []}
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                return {"content": _TECHNOLOGY_COLUMN_FIXTURE}
            return {
                "visible_summary": ["完成"],
                "selection_rationale": "通过",
                "concept_directions": [],
            }

    deep_contextual_dialogue(
        Host(),
        {
            "topic": "低空精确打击",
            "question": "形成新质颠覆装备",
            "deep_parent_context": {
                "source_equipment": {
                    "name": "折脊穿隙攻击无人机",
                    "equipment_form": "折叠穿隙攻击器",
                },
                "query_weapons": [
                    {
                        "name": "折脊穿隙攻击无人机",
                        "equipment_form": "折叠穿隙攻击器",
                    },
                    {
                        "name": "协同压制蜂群",
                        "equipment_form": "低成本诱饵集群",
                    },
                ],
            },
        },
    )

    divergence_prompt, divergence_payload = captured["deep_contextual_dialogue_divergence"][0]
    assert "query_weapons" in divergence_payload["deep_parent_context"]
    assert "协同压制蜂群" in str(divergence_payload["deep_parent_context"]["query_weapons"])
    assert "query_weapons" in divergence_prompt
    assert "现有装备" in divergence_prompt
    critic_prompt = captured["deep_contextual_dialogue_critique"][0][0]
    assert "query_weapons" in critic_prompt


def test_deep_contextual_dialogue_progress_is_monotonic() -> None:
    progress_values: list[float] = []

    class LiveHost:
        def _emit_deep_dialogue_progress(self, row):
            progress_values.append(float(row.get("progress") or 0))

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                return {"agent_summary": "独立提案", "proposals": [_closed_proposal(agent_id)]}
            if phase == "deep_contextual_dialogue_critique":
                return {"review_summary": "通过", "mission_focus": "夺取先机", "selection_order": []}
            if phase.startswith("deep_contextual_dialogue_s6_column_"):
                return {"content": _TECHNOLOGY_COLUMN_FIXTURE}
            return {"visible_summary": ["完成"], "selection_rationale": "通过", "concept_directions": []}

    deep_contextual_dialogue(LiveHost(), {"query": "单装备"})
    assert progress_values
    assert progress_values == sorted(progress_values)
    assert progress_values[-1] >= 0.89
    assert any(value >= 0.20 for value in progress_values)


def test_deep_contextual_dialogue_applies_steering_before_critique() -> None:
    captured: dict[str, dict] = {}

    class Host:
        def __init__(self) -> None:
            self.claimed = False

        def _claim_deep_dialogue_steers(self, stage):
            if stage == "council_critique" and not self.claimed:
                self.claimed = True
                return [
                    {
                        "steer_id": "steer-1",
                        "mode": "interrupt_steer",
                        "content": "放弃高成本平台，优先可快速部署构型",
                    }
                ]
            return []

        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            if phase == "deep_contextual_dialogue_divergence":
                role = payload["council_role"]["role"]
                return {
                    "agent_summary": f"{role}完成提案",
                    "proposals": [_closed_proposal(f"{role}候选")],
                }
            if phase == "deep_contextual_dialogue_critique":
                captured["critic"] = payload
                return {
                    "review_summary": "按最新约束重新排序",
                    "mission_focus": "优先快速部署",
                    "selection_order": [],
                    "candidate_reviews": [],
                }
            captured["synthesis"] = payload
            return {
                "visible_summary": ["已吸收生成中的新约束"],
                "selection_rationale": "快速部署优先",
                "concept_directions": [],
                "capability_card_draft": {},
            }

    result = deep_contextual_dialogue(
        Host(), {"query": "单装备", "authoring_requested": False}
    )

    assert captured["critic"]["steering_inputs"][0]["mode"] == "interrupt_steer"
    assert "快速部署" in captured["critic"]["steering_inputs"][0]["content"]
    assert captured["synthesis"]["steering_inputs"] == captured["critic"]["steering_inputs"]
    assert result["visible_summary"] == ["已吸收生成中的新约束"]


def _closed_memory_direction(name: str = "潜伏先机节点") -> dict:
    return {
        "name": name,
        "winning_angle": "任务链重构",
        "changed_assumption": "发射后必须立即攻击",
        "equipment_form": "可潜伏展开的任务节点",
        "operational_mechanism": "贴附潜伏后按局部态势协同作用",
        "decisive_target": "高价值机动平台关键任务舱段",
        "direct_damage_mechanism": "进入脆弱区后释放定向物理效应造成结构破坏",
        "mission_kill_criterion": "目标关键任务舱段失效并退出当前任务周期",
        "direct_military_effects": "延迟触发并压缩目标机动窗口",
        "disruptive_difference": "从一次性弹药转为潜伏任务节点",
        "stable": True,
    }


def test_memory_command_inspects_working_memory_without_council() -> None:
    class Host:
        async def _run_core_json(self, *_args, **_kwargs):
            raise AssertionError(" /memory must not start the research council")

    result = deep_contextual_dialogue(
        Host(),
        {
            "query": "单装备",
            "question": "/memory",
            "authoring_requested": False,
            "deep_parent_context": {
                "working_memory": {
                    "current_objective": "闭合直接毁伤判据",
                    "latest_summary": ["保留潜伏先机方向"],
                    "selection_rationale": "机理与直接毁伤闭合",
                    "candidate_directions": [_closed_memory_direction()],
                    "decisions": [
                        {
                            "candidate": "潜伏先机节点",
                            "verdict": "keep",
                            "reason": "改写进入时机",
                        }
                    ],
                    "open_questions": ["反制后如何保持收益？"],
                    "finalization_status": "awaiting_user_confirmation",
                }
            },
        },
    )

    assert result["runtime"]["tools"] == ["inspect_memory"]
    assert result["orchestration"]["pattern"] == "memory_inspect"
    assert result["orchestration"]["completed_divergence_agents"] == 0
    assert result["capability_card_draft"] == {}
    assert result["concept_directions"][0]["name"] == "潜伏先机节点"
    assert result["quality_gate"]["publishable"] is False
    assert result["quality_gate"]["direction_ready"] is True


def test_help_command_does_not_start_council() -> None:
    class Host:
        async def _run_core_json(self, *_args, **_kwargs):
            raise AssertionError("/help must not start the research council")

    result = deep_contextual_dialogue(
        Host(),
        {"query": "单装备", "question": "/help", "authoring_requested": True},
    )

    assert result["runtime"]["tools"] == ["help"]
    assert result["orchestration"]["pattern"] == "slash_command"
    assert any("/card" in item for item in result["visible_summary"])
    assert result["capability_card_draft"] == {}


def test_confirmed_card_authors_s6_from_memory_without_redivergence() -> None:
    calls: list[str] = []

    class Host:
        async def _run_core_json(self, agent_id, _prompt, payload, _schema, _budget, *, phase):
            calls.append(phase)
            assert phase.startswith("deep_contextual_dialogue_s6_column_")
            content = (
                _TECHNOLOGY_COLUMN_FIXTURE
                if payload["current_column"]["key"] == "technology_implementation"
                else f"{payload['current_column']['label']}完整正文"
            )
            return {"content": content}

    result = deep_contextual_dialogue(
        Host(),
        {
            "query": "单装备",
            "question": "/card",
            "authoring_requested": True,
            "deep_parent_context": {
                "working_memory": {
                    "current_objective": "形成五栏能力卡",
                    "latest_summary": ["已收敛潜伏先机方向"],
                    "selection_rationale": "机理与直接毁伤闭合",
                    "candidate_directions": [_closed_memory_direction()],
                    "finalization_status": "awaiting_user_confirmation",
                }
            },
        },
    )

    assert calls == [
        "deep_contextual_dialogue_s6_column_1",
        "deep_contextual_dialogue_s6_column_2",
        "deep_contextual_dialogue_s6_column_3",
        "deep_contextual_dialogue_s6_column_4",
        "deep_contextual_dialogue_s6_column_5",
    ]
    assert result["runtime"]["tools"] == ["inspect_memory", "author_s6"]
    assert result["orchestration"]["pattern"] == "memory_restore_s6_authoring"
    assert result["orchestration"]["phases"] == ["inspect_memory", "s6_synthesis"]
    assert result["orchestration"]["completed_divergence_agents"] == 0
    assert result["quality_gate"]["publishable"] is True
    assert result["capability_card_draft"]["overview"]
    assert result["concept_directions"][0]["name"] == "潜伏先机节点"


def test_follow_up_deepens_with_internal_multidim_divergence() -> None:
    calls: list[tuple[str, str]] = []
    progress: list[dict] = []

    class Host:
        def _emit_deep_dialogue_progress(self, row):
            progress.append(dict(row))

        async def _run_core_json(self, agent_id, prompt, payload, _schema, _budget, *, phase):
            calls.append((phase, prompt))
            if phase == "deep_research_conduct":
                return {
                    "intent": "deepen",
                    "tools": ["deepen"],
                    "rationale": "已有方向，内部多维发散后闭合失能判据",
                }
            assert phase == "deep_contextual_dialogue_deepen"
            assert agent_id == "deep_thinking_dialogue"
            assert "多维度" in prompt
            assert "多角度" in prompt
            assert "颠覆传统作战" in prompt
            assert "直接杀伤效应闭合" in prompt
            assert "反适应韧性" in prompt
            assert "禁止原样复述或只补一个字段" in prompt
            assert payload["internal_divergence"]["dimensions"]
            assert len(payload["internal_divergence"]["axes"]) == 3
            return {
                "visible_summary": ["本轮沿毁伤与反制两角把失能判据推进一步"],
                "selection_rationale": "保留潜伏节点，闭合任务舱段失能出口",
                "divergence_steps": [
                    {
                        "title": "颠覆·机理·链反转",
                        "text": "比较了先发毁伤与潜伏择机，淘汰即时攻击。",
                        "stage": "divergence",
                    },
                    {
                        "title": "直接毁伤·末端效应·目标失能",
                        "text": "把失能判据收到关键任务舱段退出当前任务周期。",
                        "stage": "divergence",
                    },
                    {
                        "title": "反适应·制衡·边界",
                        "text": "对手清场后仍可靠局部展开窗口保持非对称收益。",
                        "stage": "divergence",
                    },
                ],
                "concept_directions": [
                    {**_closed_proposal("潜伏先机节点"), "stable": True}
                ],
            }

    result = deep_contextual_dialogue(
        Host(),
        {
            "query": "单装备",
            "question": "继续闭合毁伤与任务失能判据",
            "authoring_requested": False,
            "deep_parent_context": {
                "working_memory": {
                    "current_objective": "闭合直接毁伤判据",
                    "latest_summary": ["保留潜伏先机方向"],
                    "selection_rationale": "机理与直接毁伤尚未完全闭合",
                    "candidate_directions": [_closed_memory_direction()],
                    "finalization_status": "awaiting_user_confirmation",
                }
            },
        },
    )

    assert [item[0] for item in calls] == [
        "deep_research_conduct",
        "deep_contextual_dialogue_deepen",
    ]
    assert result["runtime"]["tools"] == ["deepen"]
    assert result["orchestration"]["pattern"] == "memory_led_internal_multidim_deepen"
    assert result["orchestration"]["completed_divergence_agents"] == 0
    assert "颠覆传统作战" in result["orchestration"]["internal_dimensions"]
    assert len(result["orchestration"]["divergence_axes"]) == 3
    assert result["capability_card_draft"] == {}
    assert result["finalization_status"] == "awaiting_user_confirmation"
    assert any("内部发散" in str(item.get("role") or item.get("delta", {}).get("role", "")) or "内部发散" in str((item.get("delta") or {}).get("role", "")) for item in progress)
    assert any(item.get("round") == "deepen" for item in result["agent_dialogue"])
    assert not any(item[0] == "deep_contextual_dialogue_divergence" for item in calls)
    assert not any(item[0] == "deep_contextual_dialogue_critique" for item in calls)
