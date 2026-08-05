from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import json
import os
import subprocess
import sys
import time

import pytest

import equipment_deep_research.agents.provider as provider_module

from equipment_deep_research.agents.provider import (
    ResponsesAgentProvider,
    S6QualityError,
    _branch_product_output_schema,
    _capability_direction_quality_issues,
    _capability_language_issues,
    _capability_synthesis_handoff,
    _capability_text_similarity,
    _compact_swarm_candidate_handoff,
    _compact_s6_prior_outputs,
    _effective_expert_judge_status,
    _has_combat_effect_signal,
    _normalize_concept_direction_priorities,
    _normalize_effect_chain_references,
    _normalize_priority_references,
    _normalize_s6_deterministic_format,
    _prioritized_evidence_index,
    _quality_judge_candidate_payload,
    _quality_judge_output_token_budget,
    _quality_judge_scoped_evidence_index,
    _query_relevance_issues,
    _s6_first_pass_quality_contract,
    _s6_repair_targets,
    _dedupe_capability_title,
    _winning_step_modes,
)
from equipment_deep_research.domain.models import WinningHypothesis
from equipment_deep_research.orchestration.capability_portrait import (
    build_capability_portrait,
)
from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.codex import (
    CodexCliProvider,
    _codex_failure_detail,
    _contract_to_json_schema,
    _is_retryable_failure,
)
from equipment_deep_research.providers.codex_optimizations import (
    render_prompt_optimized,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.responses import ProviderRequestError


class _RealLikeScriptedProvider(ScriptedFakeProvider):
    """Exercise deterministic Codex gates without launching an external model."""


def test_query_led_combat_equipment_theme_contract_is_non_exhaustive() -> None:
    contract = provider_module._query_led_combat_equipment_theme_contract()

    assert contract["examples_are_non_exhaustive"] is True
    assert contract["illustrative_names_are_not_facts"] is True
    assert "query" in contract["query_precedence"]
    assert "不得为了凑齐主题机械生成" in contract["query_precedence"]
    themes = {item["theme"] for item in contract["theme_lanes"]}
    assert themes == {
        "无人远程火力打击装备",
        "体系化、实战化、智能化、颠覆化武器装备",
        "通用化、系列化、规模化武器装备",
        "传统能力红海中的跨代优势武器装备",
        "新质能力蓝海中的高维优速武器装备",
    }
    assert "通信" in contract["support_only_exclusion"]
    assert "不能独立占用最终武器方向" in contract["support_only_exclusion"]
    assert "项目功能" in contract["project_function_requirement"]
    assert "任务链断点" in contract["project_function_requirement"]
    patterns = [
        pattern
        for lane in contract["theme_lanes"]
        for pattern in lane["example_patterns"]
    ]
    assert any("蜂群母舰" in item for item in patterns)
    assert any("高功率微波巡飞弹" in item for item in patterns)


def test_weapon_discovery_and_s6_preflight_receive_query_led_themes() -> None:
    discovery_prompt = provider_module._discovery_system_prompt("weapon_equipment")
    s6_contract = _s6_first_pass_quality_contract(topic="强干扰下蜂群精确打击", handoff={})

    assert "当前query" in discovery_prompt
    assert "非穷尽发散主题" in discovery_prompt
    assert "机械生成" in discovery_prompt
    themes = s6_contract["query_led_combat_equipment_themes"]
    assert themes["examples_are_non_exhaustive"] is True
    assert themes["combat_subject_requirement"].startswith("候选主体必须是")


def test_query_divergence_brief_consumes_codex_semantics_without_keyword_catalog() -> None:
    anti_ship = provider_module._query_combat_equipment_divergence_brief(
        "研究任务",
        structured_query_brief={
            "combat_problem_frame": "远海交战中对高速机动水面编队实施连续火力打击",
            "enemy_target_profile": ["高速机动水面舰艇与编队防空"],
            "battle_phase_and_constraints": ["首轮突防后坐标快速过期"],
            "required_direct_military_effects": ["重创或击沉高价值水面舰艇"],
            "weapon_design_variables": ["多域发射", "末段多模再捕获"],
            "query_specific_weapon_architectures": [
                "潜射低特征多模反舰巡航弹药",
                "空射高速末段机动反舰导弹",
            ],
            "equipment_project_hypotheses": [
                {
                    "project_name": "潜射低特征反舰弹药项目",
                    "equipment_form": "潜射低特征多模反舰巡航弹药",
                    "project_function": "潜艇在远海强对抗阶段隐蔽释放弹药并对高速机动水面编队实施再捕获打击。",
                }
            ],
            "rejected_template_anchors": ["通用反装甲微巡飞弹"],
        },
    )
    underground = provider_module._query_combat_equipment_divergence_brief(
        "研究任务",
        structured_query_brief={
            "combat_problem_frame": "对地下加固设施实施内部关键功能毁伤",
            "query_specific_weapon_architectures": [
                "防区外复合侵彻精确制导弹药",
                "入口封堵与内部级联毁伤弹药族",
            ],
        },
    )
    no_model_brief = provider_module._query_combat_equipment_divergence_brief(
        "包含任意术语的Query"
    )

    assert anti_ship["query_specific_weapon_architectures"] != underground[
        "query_specific_weapon_architectures"
    ]
    assert "潜射低特征" in anti_ship["query_specific_weapon_architectures"][0]
    assert anti_ship["equipment_project_hypotheses"][0]["project_function"]
    assert no_model_brief["query_specific_weapon_architectures"] == []
    assert "提示词表" in no_model_brief["generation_rules"][0]


def test_specialized_seed_recovery_does_not_replace_codex_query_candidates() -> None:
    rows = [
        {
            "title": "顶攻微巡飞反装甲弹药",
            "changed_confrontation_variable": "从正面交战转为顶部薄弱区猎歼",
            "mechanism_chain": ["伴随搜索", "顶部识别", "俯冲毁伤"],
            "direct_military_effects": ["歼灭装甲车辆并阻断集群反击"],
            "equipment_forms": ["单兵顶攻微巡飞反装甲弹药"],
            "novelty_delta": "针对顶部薄弱区形成低成本猎歼闭环",
            "evidence_ids": ["ev-armor-1"],
        },
        {
            "title": "传感器引信反装甲伏击弹药",
            "changed_confrontation_variable": "从追踪单车转为封锁集群展开通道",
            "mechanism_chain": ["预置", "车辆识别", "定向毁伤"],
            "direct_military_effects": ["毁伤先导车辆并迟滞装甲集群展开"],
            "equipment_forms": ["传感器引信反装甲伏击弹药"],
            "novelty_delta": "改变装甲集群机动通道的风险结构",
            "evidence_ids": ["ev-armor-2"],
        },
    ]

    selected, recovered = provider_module._ensure_specialized_winning_seed_lanes(
        rows,
        [],
        archetype="remote_precision_munition_generator",
        topic="装甲集群近距反击装备研究",
    )

    assert recovered == 0
    assert [item["title"] for item in selected] == [item["title"] for item in rows]


def test_winning_projection_preserves_query_specific_equipment_form() -> None:
    hypothesis = WinningHypothesis(
        hypothesis_id="h-query-specific",
        title="地下加固目标内部级联毁伤",
        nearest_public_baseline="公开侵彻弹药基线",
        changed_confrontation_variable="从表面爆破转为内部关键舱室级联毁伤",
        mechanism_chain=["防区外投送", "复合侵彻", "延时起爆"],
        direct_military_effects=["摧毁地下设施内部关键功能"],
        equipment_forms=["防区外复合侵彻延时起爆精确制导弹药"],
        novelty_delta="按目标结构形成受约束内部毁伤",
    )

    assert provider_module._winning_primary_equipment_form(
        hypothesis,
        equipment_family="ground_launched_precision_missile",
    ) == "防区外复合侵彻延时起爆精确制导弹药"


def test_s6_model_call_ignores_expired_run_deadline_without_downshifting() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "wall_clock_deadlines_enabled": True,
            "hard_deadline_seconds": 1,
            "absolute_deadline_seconds": 1,
            "maximum_model_calls": 0,
            "maximum_model_calls_with_residuals": 0,
        }
    )
    provider._run_started_at -= 10  # type: ignore[attr-defined]

    result = asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"query": "test"},
            5200,
            phase="winning_s6_image_deep",
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "xhigh"
    assert options["model_verbosity"] == "medium"
    assert options["max_output_tokens"] == 5200
    assert options["_provider_timeout_seconds"] == 3600
    assert options["_allow_extended_provider_timeout"] is True
    assert options["_provider_retry_attempts"] == 2


def test_s6_card_repair_uses_narrow_low_reasoning_profile() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"query": "test", "repair_targets": [1]},
            2100,
            phase="winning_s6_card_repair",
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "low"
    assert options["model_verbosity"] == "low"
    assert options["_provider_retry_attempts"] == 1
    assert "_allow_extended_provider_timeout" not in options


def test_project_parallel_report_uses_per_section_output_caps() -> None:
    provider = ResponsesAgentProvider(_RealLikeScriptedProvider([]))
    calls: dict[str, int] = {}

    async def fake_run_reporter_text(
        system,
        payload,
        max_output_tokens,
        *,
        phase,
        run_id,
        isolation_id,
    ):
        del system, payload, run_id, isolation_id
        calls[phase] = max_output_tokens
        return ""

    provider._run_reporter_text = fake_run_reporter_text  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="parallel Reporter assembly"):
        provider._draft_parallel_report(  # type: ignore[attr-defined]
            {
                "run_id": "report-token-cap-test",
                "report_template_mode": "project_argument_v1",
            },
            reporter_input={},
            output_token_budget=12000,
            timeout_seconds=5,
        )

    assert calls == {
        "report_generation_chapter_1_demand": 2800,
        "report_generation_chapter_2_portrait": 1800,
        "report_generation_chapter_3_solution": 1800,
        "report_generation_chapter_4_technology_foundation": 2600,
    }


def test_quality_judge_budget_scales_only_for_small_repair_sets() -> None:
    assert _quality_judge_output_token_budget(1) == 2600
    assert _quality_judge_output_token_budget(2) == 3400
    assert _quality_judge_output_token_budget(4) == 4600
    assert _quality_judge_output_token_budget(10) == 4600


def test_expert_judge_keeps_complete_first_round_when_targeted_rejudge_fails() -> None:
    assert _effective_expert_judge_status(
        [{"status": "completed"}, {"status": "failed"}],
        assessed_count=10,
        expected_count=10,
    ) == "completed"
    assert _effective_expert_judge_status(
        [{"status": "limited"}, {"status": "failed"}],
        assessed_count=8,
        expected_count=10,
    ) == "failed"


def test_quality_judge_scopes_evidence_to_reviewed_candidates() -> None:
    rows = [
        {"evidence_id": "ev-1", "claim": "first"},
        {"evidence_id": "ev-2", "claim": "second"},
        {"evidence_id": "ev-3", "claim": "third"},
    ]

    scoped = _quality_judge_scoped_evidence_index(rows, {"ev-2"})

    assert scoped == [{"evidence_id": "ev-2", "claim": "second"}]
    assert _quality_judge_scoped_evidence_index(rows, {"ev-missing"}) == rows


def test_quality_judge_candidate_payload_bounds_repair_expansion() -> None:
    repeated = [f"long finding {index} " + ("detail" * 160) for index in range(20)]
    hypothesis = WinningHypothesis(
        hypothesis_id="hypothesis-review",
        title="bounded quality review candidate",
        nearest_public_baseline="baseline " + ("detail" * 160),
        changed_confrontation_variable="variable " + ("detail" * 160),
        mechanism_chain=repeated,
        direct_military_effects=repeated,
        equipment_forms=repeated,
        system_interfaces=repeated,
        novelty_delta="novelty " + ("detail" * 160),
        evidence_ids=[f"ev-{index}" for index in range(20)],
        counterevidence=repeated,
        adversary_adaptations=repeated,
        failure_boundaries=repeated,
        trl_constraints=repeated,
        cost_constraints=repeated,
        industrial_constraints=repeated,
        cross_scenario_results=repeated,
        validation_plan=repeated,
        evidence_boundary="boundary " + ("detail" * 160),
        implementation_path="new",
        merge_targets=["S5"],
        source_task_ids=["task-1"],
        residuals=[],
        score=0.8,
    )

    payload = _quality_judge_candidate_payload(
        hypothesis,
        blind_label="候选-01",
        deterministic_hard_gate={"passed": True},
    )

    assert len(payload["mechanism_chain"]) == 4
    assert len(payload["evidence_ids"]) == 8
    assert len(payload["validation_plan"]) == 4
    assert payload["mechanism_chain"][0] == repeated[0]
    assert payload["mechanism_chain"][-1] == repeated[-1]
    assert not any("…" in item or "..." in item for item in payload["mechanism_chain"])


def test_swarm_candidate_handoff_deduplicates_and_keeps_latest_repairs() -> None:
    hypothesis = WinningHypothesis(
        hypothesis_id="hypothesis-compact",
        title="远程精确导弹方向",
        nearest_public_baseline="公开基线",
        changed_confrontation_variable="窗口化纵深火力",
        mechanism_chain=[
            "初始机理",
            "重复机理",
            "重复机理",
            "中间机理一",
            "中间机理二",
            "最新修复机理",
        ],
        direct_military_effects=["直接毁伤"],
        equipment_forms=["地面发射远程精确制导导弹"],
        system_interfaces=["任务装订接口"],
        novelty_delta="相对基线改变时间逻辑",
        evidence_ids=["ev-1", "ev-1", "ev-2"],
        counterevidence=["诱饵会降低收益"],
        adversary_adaptations=["强化机动"],
        failure_boundaries=["目标窗口关闭时失效"],
        trl_constraints=["需样机验证"],
        cost_constraints=["按全链成本核算"],
        industrial_constraints=["关键部件需多源供应"],
        cross_scenario_results=["固定目标场景收益较高"],
        validation_plan=["开展半实物对照验证"],
        evidence_boundary="公开资料不证明实战命中率",
        implementation_path="upgrade",
        merge_targets=["S6"],
        source_task_ids=["task-1"],
        residuals=[],
        score=0.8,
    )

    payload = _compact_swarm_candidate_handoff(hypothesis)

    assert payload["mechanism_chain"] == [
        "初始机理",
        "重复机理",
        "中间机理二",
        "最新修复机理",
    ]
    assert payload["evidence_ids"] == ["ev-1", "ev-2"]


def test_portfolio_candidate_handoff_keeps_decision_spine_with_bounded_size() -> None:
    repeated = [f"约束或结论-{index}-" + ("细节" * 80) for index in range(12)]
    hypothesis = WinningHypothesis(
        hypothesis_id="hypothesis-portfolio",
        title="弱网条件下远程精确打击装备族",
        nearest_public_baseline="公开装备基线" + ("说明" * 100),
        changed_confrontation_variable="从持续联网改为任务级降级自治",
        mechanism_chain=repeated,
        direct_military_effects=repeated,
        equipment_forms=repeated,
        system_interfaces=repeated,
        novelty_delta="改变任务续接方式" + ("说明" * 100),
        evidence_ids=[f"ev-{index}" for index in range(12)],
        counterevidence=repeated,
        adversary_adaptations=repeated,
        failure_boundaries=repeated,
        trl_constraints=repeated,
        cost_constraints=repeated,
        industrial_constraints=repeated,
        cross_scenario_results=repeated,
        validation_plan=repeated,
        evidence_boundary="公开资料只支持能力方向" + ("说明" * 100),
        implementation_path="upgrade",
        score=0.82,
    )

    full = _compact_swarm_candidate_handoff(hypothesis)
    portfolio = _compact_swarm_candidate_handoff(
        hypothesis,
        portfolio_summary=True,
    )

    assert set(
        (
            "hypothesis_id",
            "title",
            "nearest_public_baseline",
            "mechanism_chain",
            "direct_military_effects",
            "equipment_forms",
            "evidence_ids",
            "evidence_boundary",
            "failure_boundaries",
            "validation_plan",
            "score",
        )
    ).issubset(portfolio)
    assert "trl_constraints" not in portfolio
    assert len(json.dumps(portfolio, ensure_ascii=False)) < len(
        json.dumps(full, ensure_ascii=False)
    )
    assert portfolio["mechanism_chain"][0] == repeated[0]
    assert portfolio["mechanism_chain"][-1] == repeated[-1]
    assert not any(
        "…" in item or "..." in item
        for key in ("mechanism_chain", "failure_boundaries", "validation_plan")
        for item in portfolio[key]
    )


def test_portfolio_title_replaces_internal_tactic_label_with_equipment_family() -> None:
    hypothesis = WinningHypothesis(
        hypothesis_id="hypothesis-title",
        title="竞争分支：多层反无人走廊迫使低空装备转向窗口突防",
        nearest_public_baseline="公开基线",
        changed_confrontation_variable="防御循环加快",
        mechanism_chain=["形成短时窗口"],
        direct_military_effects=["直接毁伤"],
        equipment_forms=[
            "低成本模块化巡飞弹药族；可消耗电子战压制无人机",
        ],
        system_interfaces=["任务装订接口"],
        novelty_delta="异构窗口突防",
        evidence_ids=["ev-1"],
        counterevidence=[],
        adversary_adaptations=[],
        failure_boundaries=["窗口离散时失效"],
        trl_constraints=[],
        cost_constraints=[],
        industrial_constraints=[],
        cross_scenario_results=[],
        validation_plan=["对照验证"],
        evidence_boundary="仅支持方向",
        implementation_path="upgrade",
        merge_targets=["S6"],
        source_task_ids=["task-1"],
        residuals=[],
        score=0.8,
    )

    assert (
        provider_module._winning_portfolio_title(hypothesis)
        == "低成本模块化巡飞弹药族"
    )


def test_portfolio_title_removes_branch_and_s_node_internal_prefix() -> None:
    hypothesis = WinningHypothesis(
        hypothesis_id="hypothesis-internal-prefix",
        title="G-S2-01：抗辐射巡飞猎歼弹药接替失联精确火力链",
        nearest_public_baseline="公开基线",
        changed_confrontation_variable="任务续接",
        mechanism_chain=["发现并压制辐射源"],
        direct_military_effects=["压制防空节点"],
        equipment_forms=["抗辐射巡飞猎歼弹药"],
        novelty_delta="断链续接",
    )

    assert provider_module._winning_portfolio_title(hypothesis) == (
        "抗辐射巡飞猎歼弹药接替失联精确火力链"
    )


def test_dynamic_portfolio_normalization_cleans_title_and_priority_before_s6_gate() -> None:
    normalized = provider_module._normalize_s6_deterministic_format(
        {
            "confidence": 0.81,
            "concept_directions": [
                {
                    "name": "B1：前出长航时巡飞猎歼平台接替断裂的海上目标确认链",
                    "type": "new_capability",
                    "equipment_form": "舰射长航时反舰巡飞猎歼弹药",
                    "baseline_system": "Harop类长航时巡飞猎歼弹药",
                    "target_scenario": "强电磁压制与GNSS拒止下的远程反舰火力链断裂场景",
                    "capability_gap": "持续链路中断后不能独立复获海上机动目标",
                    "scientific_principle": "以惯性保持和被动复合感知约束搜索区",
                    "enabling_technologies": ["抗扰组合导航", "被动复合感知"],
                    "operational_concept": "由舰艇发射后进入授权目标活动区实施复核和受控交战",
                    "operational_process": ["进入", "搜索复核", "交战", "评估"],
                    "capability_outcome": "形成断链后的目标复获与直接毁伤能力",
                    "military_value": "续接远程反舰火力并直接毁伤授权目标",
                    "winning_mechanism": "把对外部连续更新的依赖转为弹上有限闭环",
                    "development_path": "完成工程样机、接口和对抗试验",
                    "failure_boundary": "目标离开授权搜索区或识别置信不足时中止",
                    "verification": "对照验证复获、拒打和安全中止",
                    "direct_evidence_refs": ["ev-weapon_equipment-1"],
                    "confidence": 0.81,
                }
            ],
        },
        topic="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
    )
    normalized = provider_module._normalize_concept_direction_priorities(normalized)
    direction = normalized["concept_directions"][0]

    assert not direction["name"].startswith(("B1：", "S1：", "候选"))
    assert len(direction["name"]) <= 24
    assert direction["priority"] == "P1"
    assert len(direction["capability_portrait"]) >= 900


def test_remote_precision_portfolio_direction_requires_weapon_and_range_signals() -> None:
    assert provider_module._is_remote_precision_portfolio_direction(
        {
            "name": "JASSM-ER类空射防区外巡航导弹",
            "military_value": "战役纵深精确毁伤",
        }
    )
    assert not provider_module._is_remote_precision_portfolio_direction(
        {
            "name": "低空巡飞猎歼弹药族",
            "military_value": "近程反装甲毁伤",
        }
    )


def _minimal_reasoning_node(step: int) -> dict:
    return {
        "recognition": f"S{step}可审计认识",
        "evidence_refs": ["ev-1"],
        "confidence": 0.7 + step / 100,
        "next_action": {
            "action": "continue" if step < 6 else "stop",
            "target_step": step + 1 if step < 6 else 0,
            "reason": "按六步链路推进",
        },
    }


def _minimal_s4_gate_result() -> dict:
    return {
        "capability_mapping": ["m"],
        "dotmlpf_matrix": [],
        "concept_directions": [],
        "open_questions": [],
        "confidence": 0.8,
        "reasoning_node": _minimal_reasoning_node(4),
    }


def _minimal_s6_gate_result(branch: str = "B") -> dict:
    return {
        "concept_directions": [],
        "capability_image_drafts": [],
        "upstream_coverage": [],
        "branch_products": {
            key: [] for key in _branch_product_output_schema(branch)
        },
        "evidence_validation": {
            "all_ids_valid": True,
            "invalid_ids": [],
            "mismatched_claims": [],
        },
        "assumptions": [],
        "open_questions": [],
        "confidence": 0.8,
        "reasoning_node": _minimal_reasoning_node(6),
    }


def test_s6_schema_contains_only_current_branch_products() -> None:
    assert set(_branch_product_output_schema("A")) == {
        "tactic_concepts",
        "tactic_combinations",
        "capability_domains",
        "capability_indicators",
        "equipment_forms",
    }
    assert set(_branch_product_output_schema("C")) == {
        "case_patterns",
        "future_scenarios",
        "emerging_equipment_categories",
    }
    assert set(_branch_product_output_schema("F")) == {
        "system_vulnerabilities",
        "future_scenarios",
        "capability_domains",
        "equipment_forms",
    }
    assert _branch_product_output_schema("B") == {}


def test_s6_projection_keeps_decision_fields_and_drops_repeated_bulk() -> None:
    projected = _compact_s6_prior_outputs(
        {
            "s4_concept_directions": [
                {
                    "name": "方向一",
                    "function": "f" * 900,
                    "equipment_form": "异构协同网关",
                    "irrelevant_bulk": "x" * 5000,
                }
            ],
            "gap_assessment": [
                {
                    "capability": "跨域互操作",
                    "grade": "关键差距",
                    "basis": "b" * 900,
                    "unneeded": "y" * 5000,
                }
            ],
            "effect_chain": ["e" * 900],
        }
    )

    direction = projected["s4_concept_directions"][0]
    gap = projected["gap_assessment"][0]
    assert "irrelevant_bulk" not in direction
    assert "unneeded" not in gap
    assert direction["function"] == "f" * 900
    assert gap["basis"] == "b" * 900
    assert projected["effect_chain"][0] == "e" * 900


def test_s6_handoff_is_query_led_and_excludes_execution_governance() -> None:
    handoff = _capability_synthesis_handoff(
        topic="西太反介入条件下装备能力缺口",
        branch="B",
        prior_step_outputs={
            "effect_chain": [
                "S3 Agent 判断：远域感知受压后，目标识别到火力分配链路中断"
            ],
            "defense_decomposition": [
                "Codex沿L1门控发现对手将通过分布式节点与诱饵实施反适应"
            ],
            "gap_assessment": [
                {
                    "capability": "远域目标连续跟踪",
                    "grade": "关键差距",
                    "gap_statement": "强干扰与诱饵混入时稳定识别不足",
                    "current_upgrade": "升级现役预警与火控任务系统",
                    "new_development": "发展跨域分布式跟踪节点",
                    "verification": "受扰条件下目标航迹连续率",
                    "evidence_refs": ["ev-1"],
                }
            ],
            "s4_concept_directions": [{"name": "远域火力闭环能力"}],
            "reasoning_nodes": {"4": {"recognition": "不得传入"}},
        },
        evidence_index=[
            {
                "evidence_id": "ev-1",
                "source_title": "公开试验报告",
                "source_url": "https://example.test/report",
                "claim": "强干扰会降低目标航迹连续性",
                "excerpt": "公开试验摘要",
                "created_by": "weapon_equipment",
            }
        ],
    )

    serialized = json.dumps(handoff, ensure_ascii=False)
    assert handoff["query"] == "西太反介入条件下装备能力缺口"
    assert len(handoff["decisive_task_chain_breaks"]) == 1
    assert handoff["high_value_combat_effects"]
    assert any(
        "火力分配" in item for item in handoff["high_value_combat_effects"]
    )
    assert len(handoff["mission_effect_escalation_questions"]) == 3
    assert handoff["public_evidence"][0]["url"] == "https://example.test/report"
    for leaked in ("Agent", "Codex", "S3", "L1", "reasoning_nodes", "Harness"):
        assert leaked not in serialized


def test_s6_quality_gate_rejects_generic_technology_labels_and_copying() -> None:
    portrait = (
        "面向预警到火力协同阶段的链路受压，形成可维持目标识别与打击任务续接的能力。"
        "通过冗余链路和任务重组维持指挥决策与反制闭环，并在对手实施诱饵和压制时保持最低火力协同。"
    ) * 3
    result = {
        "concept_directions": [
            {
                "name": f"自治网关{index}",
                "type": "new_capability",
                "equipment_form": "通用模块",
                "operational_mechanism": "维持指挥与打击链路",
                "military_value": "提升反制与持续作战能力",
                "development_path": "近期验证、中期集成",
                "verification": "任务闭环恢复时间",
                "future_trigger": "未来强干扰常态化",
                "adversary_adaptation": "对手转用诱饵与多点压制",
                "failure_boundary": "平台能源不足时失效",
                "capability_portrait": portrait[:500],
            }
            for index in range(1, 4)
        ]
    }

    issues = _capability_direction_quality_issues(result)

    assert any("抽象技术标签" in issue for issue in issues)
    assert any("具体装备" in issue for issue in issues)
    assert not any("必须包含现役装备升级" in issue for issue in issues)
    assert any("概述首句" in issue for issue in issues)


def test_s6_length_is_advisory_not_a_hard_quality_issue() -> None:
    overview = (
        "概述：面向强电磁压制下纵深精确打击续接阶段，针对敌方机动防空、诱饵、雷达静默与"
        "电子欺骗反制，利用受扰导航完整性评估和多模目标证据互证原理，采用抗扰组合导航、"
        "被动感知与安全拒打技术，以远程精确制导导弹为主装备，通过任务装订、受扰飞行、"
        "搜索复核、交战或拒打、毁伤评估和补射接替组织战斗，形成强压制条件下稳定续接火力的"
        "能力，实现对授权纵深目标的直接压制与毁伤。"
    )
    direction = {
        "name": "抗扰远程精确制导导弹",
        "type": "new_capability",
        "equipment_form": "远程精确制导导弹",
        "capability_portrait": overview + ("详细机理按装备事实完整展开。" * 20),
    }

    handoff = {"equipment_portfolio_preflight": []}
    issues = _capability_direction_quality_issues(
        {"concept_directions": [direction]},
        handoff=handoff,
    )

    assert not any("120至360" in issue or "当前" in issue and "字" in issue for issue in issues)


def test_s6_delivery_blocking_classifier_rejects_cardinality_and_duplicates() -> None:
    issues = [
        "S6必须形成5至7项具体、互异且高军事价值的最终武器装备方向",
        "S6各能力画像confidence不得机械同值，必须反映证据差异",
        "S6第1项与第2项机制高度重复（三元字符相似度0.910）",
        "S6第3项未说明具体作战阶段、任务对象及打击/反制效果",
        "S6具名装备方向必须引用与自身型号或装备族直接匹配的对象证据；涉及位置4",
    ]

    blocking = provider_module._s6_delivery_blocking_issues(issues)

    assert blocking == [issues[0], issues[2], issues[3], issues[4]]


def test_s6_repair_targets_extracts_global_evidence_mismatch_positions() -> None:
    result = {"concept_directions": [{} for _ in range(5)]}

    targets = _s6_repair_targets(
        result,
        ["S6具名装备方向必须引用匹配对象证据；涉及位置4"],
    )

    assert targets == [4]


def test_s6_repair_targets_selects_later_duplicate_title_card() -> None:
    result = {
        "concept_directions": [
            {"name": "岛礁无人远火舱"},
            {"name": "多模复核反辐射巡飞猎歼弹"},
            {"name": "低成本巡航弹"},
            {"name": "多模复核反辐射巡飞猎歼弹"},
            {"name": "近岸无人远火发射艇"},
            {"name": "滞空反无人巡航拦截弹"},
        ]
    }

    targets = _s6_repair_targets(
        result,
        ["S6最终方向名称必须互异，禁止多个不同装备被压缩为同一标题：多模复核反辐射巡飞猎歼弹"],
    )

    assert targets == [4]


def test_parallel_s6_cards_receive_isolated_codex_sessions() -> None:
    assert (
        provider_module._swarm_provider_isolation_id(
            "winning_s6_image",
            {"parallel_card_id": "s6-card-3"},
        )
        == "s6-card-3"
    )
    assert (
        provider_module._swarm_provider_isolation_id(
            "winning_s6_image",
            {"query": "ordinary monolithic S6"},
        )
        == ""
    )


def test_s6_quality_gate_rejects_dynamic_missile_cards_with_shared_recapture_template() -> None:
    shared = (
        "面向强电磁压制与GNSS拒止，针对目标坐标过期、导航受扰和末端不可确认，"
        "利用目标信息时效约束与多模证据门控原理，采用组合导航可信评估、受约束搜索、"
        "末段再捕获和安全拒打技术，通过分散接令、目标时效复核、发射、再捕获或拒打、"
        "毁伤评估与补射接替组织战斗。对手以诱饵、机动、强干扰和近程拦截反制；"
        "以再捕获率、错误接受率、正确拒打率和单位有效毁伤成本验收。"
    )
    result = {
        "concept_directions": [
            {
                "name": "多模再捕获反舰导弹毁伤",
                "capability_portrait": shared * 5 + "由空射平台攻击海上编队。",
            },
            {
                "name": "地射远程导弹机动目标再捕获",
                "capability_portrait": shared * 5 + "由地面发射车攻击纵深机动节点。",
            },
        ]
    }

    issues = _capability_direction_quality_issues(result)

    assert any(
        "第1项与第2项机制高度重复" in issue
        and "发射域/平台" in issue
        and "专属验证指标" in issue
        for issue in issues
    )


def test_s6_similarity_threshold_keeps_six_distinct_deadline_weapon_cards() -> None:
    directions = build_deadline_weapon_directions(
        topic="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
        evidence_ids=["ev-1", "ev-2"],
    )
    portraits = [str(item.get("capability_portrait", "")) for item in directions]
    maximum = max(
        _capability_text_similarity(left, right)
        for index, left in enumerate(portraits)
        for right in portraits[index + 1 :]
    )

    assert len(directions) == 6
    assert maximum < 0.75


def test_s6_local_normalization_expands_portrait_and_repairs_upgrade_title() -> None:
    result = {
        "concept_directions": [
            {
                "name": "抗毁通信升级包",
                "type": "upgrade",
                "function": "在强干扰条件下保持目标识别并向火力单元分配目标",
                "equipment_form": "现役舰载火控系统与电子战系统",
                "operational_mechanism": "通过受扰目标航迹融合和电子压制协同，缩短发现到交战的链路",
                "military_value": "提高反制、拦截和再打击能力",
                "development_path": "近期完成任务软件与传感器改装，中期开展跨平台对抗试验",
                "future_trigger": "对手分布式干扰与诱饵目标规模持续扩大",
                "adversary_adaptation": "实施多点佯动、频谱压制和火力节点猎杀",
                "failure_boundary": "目标质量不足且火控节点连续损失时",
                "baseline_system": "现役舰载火控系统",
                "upgrade_package": ["目标航迹融合改进", "电子战任务软件改进"],
                "combat_effect_uplift": "提升目标捕获、火力分配和拦截效果",
                "strike_chain_contribution": "维持侦察—决策—火力—打击—评估闭环",
                "upgrade_boundary": "现役算力和传感器孔径不足时转入新研",
                "verification": "强干扰和节点损耗条件下的有效交战闭环完成率",
                "capability_portrait": "S6 Agent认为该方向可提升火力反制。",
            }
        ]
    }

    normalized = _normalize_s6_deterministic_format(
        result,
        topic="舰队强干扰条件下火力反制研究",
    )
    direction = normalized["concept_directions"][0]

    assert direction["name"] == "现役舰载火控系统目标捕获"
    assert len(direction["capability_portrait"]) >= 900
    assert 0.0 <= direction["confidence"] <= 1.0
    assert "- 关键作战流程：" in direction["capability_portrait"]
    assert "- 发展与验证路径：" not in direction["capability_portrait"]
    assert "Agent" not in direction["capability_portrait"]
    assert "S6" not in direction["capability_portrait"]


def test_s6_local_normalization_preserves_long_portrait_and_completes_sentence() -> None:
    complete_sentence = "该方向通过多源探测、目标识别和火力分配形成闭环，并在强干扰条件下保持拦截与再打击能力。"
    partial_sentence = "最后在受扰演练中继续验证目标保持率、火力任务送达率和毁伤闭合率"
    result = {
        "concept_directions": [
            {
                "name": "目标猎获与火力协同能力",
                "type": "new_capability",
                "capability_portrait": complete_sentence * 20 + partial_sentence,
            }
        ]
    }

    normalized = _normalize_s6_deterministic_format(result)
    portrait = normalized["concept_directions"][0]["capability_portrait"]

    assert len(portrait) > 800
    assert portrait.endswith("。")
    overview = portrait.split("\n", 1)[0]
    assert all(
        marker in overview
        for marker in ("面向", "针对", "利用", "采用", "通过", "形成", "实现")
    )
    assert "- 关键作战流程：" in portrait


def test_s6_local_normalization_removes_repeated_title_terms() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "现役野战防空火力火力能力升级。",
                    "type": "upgrade",
                }
            ]
        }
    )

    assert normalized["concept_directions"][0]["name"] == "现役野战防空火力拦截"


def test_s6_title_preflight_preserves_ascii_abbreviation_spacing() -> None:
    title = "FS-LIDS类公开基线已集成FAAD C2打击能力升级"

    assert _dedupe_capability_title(title) == title
    issues = _capability_language_issues(3, {"name": title})
    assert any("超过24字" in item for item in issues)
    assert any("描述句" in item for item in issues)


def test_s6_title_preflight_repairs_layout_whitespace_and_repetition() -> None:
    assert _dedupe_capability_title(" 能力  方向\n升级。 ") == "能力方向升级"
    assert _dedupe_capability_title("火力火力能力升级") == "火力能力升级"
    assert _dedupe_capability_title("FAAD   C2") == "FAAD C2"


def test_s6_title_gate_rejects_upgrade_suffix_on_visible_weapon_name() -> None:
    issues = _capability_language_issues(
        2,
        {"name": "空射隐身防区外巡航导弹抗扰补打升级"},
    )

    assert any("非装备命名" in issue for issue in issues)


def test_s6_overview_gate_rejects_research_framing_and_missing_combat_grounding() -> None:
    issues = _capability_language_issues(
        1,
        {
            "name": "空射隐身防区外抗扰巡航导弹",
            "capability_portrait": (
                "概述：面向强电磁压制下精确打击装备研究中的导航受扰任务阶段，"
                "针对公开基线不能证明目标包过期条件下的闭合质量，利用状态估计原理，"
                "采用多源导航技术，通过任务装订和末端确认流程，形成抗扰打击能力，"
                "实现任务闭环效果。"
            ),
        },
    )

    assert any("研究管理或证据管理" in issue for issue in issues)
    assert any("战斗场景要素不完整" in issue for issue in issues)


def test_s6_overview_gate_accepts_weapon_specific_combat_sequence() -> None:
    issues = _capability_language_issues(
        1,
        {
            "name": "空射隐身防区外抗扰巡航导弹",
            "capability_portrait": (
                "概述：面向联合战役首轮纵深突击后敌防空体系恢复、导航欺骗持续生效的战区，"
                "针对敌方防空指挥所和远程火力节点短时转移造成目标包迅速过期的难点，"
                "利用多源约束导航与末端身份复核原理，采用抗欺骗组合导航、被动射频和光电确认技术，"
                "通过轰炸机编队在防区外发射、导弹分散进入目标区、搜索复核、受控交战或拒打、"
                "毁伤评估与补射接替的作战流程，形成强干扰条件下纵深目标持续补打能力，"
                "实现摧毁敌方指挥与火力节点、压缩防空重组时间并保持后续突击走廊的作战效果。"
            ),
        },
    )

    assert not any("研究管理或证据管理" in issue for issue in issues)
    assert not any("战斗场景要素不完整" in issue for issue in issues)


def test_s6_local_normalization_uses_concise_upgrade_equipment_anchor() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "复杂障碍突破升级",
                    "type": "upgrade",
                    "baseline_system": (
                        "该卡独有基线为现役有人驾驶装甲工兵破障车、扫雷车、"
                        "架桥与通路标识车辆，主要依赖战前侦察和人工确认。"
                    ),
                    "equipment_form": "现役装甲工兵破障车与扫雷车",
                    "military_value": "提高突破口开设和装甲分队突防能力",
                },
                {
                    "name": "低空节点防护升级",
                    "type": "upgrade",
                    "baseline_system": "被升级对象为现役野战近程防空分队、便携防空火力和警戒雷达",
                    "equipment_form": "升级现役野战防空车与光电探测器",
                    "combat_effect_uplift": "提升低空目标拦截和阵地拒止效果",
                },
            ]
        }
    )

    assert normalized["concept_directions"][0]["name"] == "现役有人驾驶装甲工兵破障车突防"
    assert normalized["concept_directions"][1]["name"] == "现役野战近程防空分队低空拦截"


def test_s6_local_normalization_compresses_long_baseline_sentence_to_equipment_title() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "现役近程防空火炮和弹炮结合防空系统具备机动底盘拦截能力升级",
                    "type": "upgrade",
                    "baseline_system": "现役近程防空火炮和弹炮结合防空系统具备机动底盘拦截能力",
                    "equipment_form": "现役弹炮结合防空系统",
                    "combat_effect_uplift": "提升低空小目标连续拦截和阵地拒止效果",
                }
            ]
        }
    )

    title = normalized["concept_directions"][0]["name"]
    assert title == "现役弹炮结合防空系统低空拦截"
    assert len(title) <= 24
    assert "具备" not in title


def test_s6_local_normalization_repairs_model_family_upgrade_title_without_narrative_debris() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "现役其中MADIS/L-MADIS可低空拦截升级",
                    "type": "upgrade",
                    "baseline_system": (
                        "公开证据显示，其中MADIS/L-MADIS/O-CSUAS/MRIC等被列为"
                        "前沿车载近程防空反无人任务系统的现役升级基线。"
                    ),
                    "equipment_form": (
                        "现役MADIS/L-MADIS车载近程防空反无人任务系统，"
                        "配套低成本拦截弹。"
                    ),
                    "combat_effect_uplift": "提升低空无人机和巡飞目标连续拦截能力",
                }
            ]
        }
    )

    direction = normalized["concept_directions"][0]
    assert direction["name"] == "现役MADIS/L-MADIS低空拦截"
    assert not any(
        "名称未直接点明具体装备对象" in issue
        for issue in _capability_direction_quality_issues(
            {"concept_directions": [direction]}
        )
    )


def test_s6_local_normalization_replaces_abstract_capability_name_with_equipment_object() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "高消耗战场边缘自主目标猎获与火力重组能力",
                    "type": "new_capability",
                    "equipment_form": "可消耗无人侦察平台、边缘目标识别节点、低成本效应器和战损后火力重组终端",
                    "operational_mechanism": "完成目标猎获和火力重组",
                }
            ]
        }
    )

    title = normalized["concept_directions"][0]["name"]
    assert title == "可消耗无人侦察平台目标猎获"
    assert "能力" not in title


def test_s6_local_normalization_replaces_multidomain_capability_slogan_with_effector() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "岛链远程目标猎获与多域饱和打击协同能力",
                    "type": "new_capability",
                    "equipment_form": (
                        "海空天电多源传感节点、远程反舰/对陆效应器、"
                        "电子压制载荷和分布式火力任务系统"
                    ),
                    "operational_mechanism": "远程目标猎获与多域饱和打击",
                }
            ]
        }
    )

    title = normalized["concept_directions"][0]["name"]
    assert "效应器" in title
    assert "饱和打击" in title
    assert not title.endswith("能力")
    assert provider_module._is_lethal_weapon_equipment_direction(
        normalized["concept_directions"][0]
    ) is True


@pytest.mark.parametrize(
    "title,equipment_form",
    [
        (
            "可消耗低空无人侦打诱骗机",
            "小型固定翼/垂直起降低空无人机，搭载光电、被动射频、诱饵和轻型毁伤载荷",
        ),
        (
            "远域反辐射压制无人僚机",
            "中型喷气无人僚机，配电子攻击吊舱、诱饵和反辐射小弹药",
        ),
        (
            "关岛抗饱和定向能拦截阵",
            "固定定向能拦截阵，含高能激光、高功率微波效应器和火控单元",
        ),
    ],
)
def test_s6_local_normalization_preserves_concrete_compound_equipment_titles(
    title: str,
    equipment_form: str,
) -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": title,
                    "type": "new_capability",
                    "equipment_form": equipment_form,
                    "operational_mechanism": "完成目标发现、压制、拦截或毁伤任务",
                }
            ]
        }
    )

    assert normalized["concept_directions"][0]["name"] == title


def test_s6_title_gate_rejects_abstract_capability_suffix_even_with_combat_terms() -> None:
    issues = _capability_language_issues(
        1,
        {
            "name": "岛链远程目标猎获与多域饱和打击协同能力",
            "equipment_form": "远程反舰导弹、电子压制效应器和火力任务系统",
        },
    )

    assert any("抽象能力口号" in issue for issue in issues)


@pytest.mark.parametrize(
    "raw_name,equipment_form,extra,expected",
    [
        (
            "小型固定翼/垂直起降低空无人机目标发现",
            "小型固定翼/垂直起降低空无人机，搭载EO/IR、被动射频、可控诱饵和轻型毁伤载荷",
            {
                "function": "承担侦察、诱骗、毁伤确认和有限突击",
                "military_value": "改善目标发现、BDA和再打击闭环",
            },
            "可消耗低空无人侦打诱骗机",
        ),
        (
            "中型喷气无人僚机或长航时无人平台打击",
            "中型喷气无人僚机，配电子攻击吊舱、诱饵和反辐射小弹药",
            {"function": "实施远域电子压制和反辐射突击"},
            "远域反辐射压制无人僚机",
        ),
        (
            "含高能激光或高功率微波效应器火力",
            "关岛固定定向能拦截阵，含高能激光或高功率微波效应器",
            {"function": "承担固定枢纽抗饱和拦截"},
            "关岛抗饱和定向能拦截阵",
        ),
    ],
)
def test_s6_local_normalization_recovers_equipment_title_from_enumerative_fragment(
    raw_name: str,
    equipment_form: str,
    extra: dict[str, str],
    expected: str,
) -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": raw_name,
                    "type": "new_capability",
                    "equipment_form": equipment_form,
                    **extra,
                }
            ]
        }
    )

    assert normalized["concept_directions"][0]["name"] == expected


@pytest.mark.parametrize(
    "row,expected",
    [
        (
            {
                "name": "岛链远程目标猎获与多域饱和打击协同能力",
                "type": "new_capability",
                "equipment_form": "远程反舰/对陆效应器和分布式火力任务系统",
                "novelty": "转向可消耗、可补充的远程精确火力对象",
                "foresight": "导弹/弹药独立化避免发射平台成为瓶颈",
            },
            "岛链远程精确制导弹药",
        ),
        (
            {
                "name": "含高能激光或高功率微波效应器火力",
                "type": "new_capability",
                "equipment_form": "关岛固定定向能拦截阵地，含高能激光和高功率微波效应器",
                "deep_capability_portrait": "该装备承担固定枢纽抗饱和拦截并降低边际拦截成本。",
            },
            "关岛抗饱和定向能拦截阵",
        ),
    ],
)
def test_s6_local_normalization_recovers_titles_from_persisted_card_fields(
    row: dict[str, str], expected: str
) -> None:
    normalized = _normalize_s6_deterministic_format(
        {"concept_directions": [row]},
        topic="挖掘在西太反介入体系下的装备能力缺口",
    )

    assert normalized["concept_directions"][0]["name"] == expected


def test_evidence_projection_prioritizes_upstream_references() -> None:
    rows = [
        {"evidence_id": "ev-a", "created_by": "other"},
        {"evidence_id": "ev-b", "created_by": "weapon_equipment"},
        {"evidence_id": "ev-c", "created_by": "other"},
    ]

    projected = _prioritized_evidence_index(
        rows,
        preferred_ids={"ev-c"},
        allowed_agents={"weapon_equipment"},
        limit=2,
    )

    assert [item["evidence_id"] for item in projected] == ["ev-c", "ev-b"]


def test_s6_combat_value_can_be_proven_across_the_complete_direction() -> None:
    assert _has_combat_effect_signal(
        {
            "combat_effect_uplift": "关键消息送达率提升并缩短重同步时间",
            "strike_countermeasure_value": "保持通信受压条件下的反制任务闭环",
            "operational_mechanism": "",
            "capability_portrait": "",
        }
    )


def test_s6_quality_gate_rejects_support_only_upgrade_as_final_direction() -> None:
    portrait = (
        "该方向面向强干扰环境下的任务连续性，通过多链路切换、接口治理和恢复机制维持信息流转。"
        "近期重点改造终端、网关和网络管理组件，中期完成跨平台集成，并以消息送达率、恢复时间和"
        "系统可用率作为验证指标。对手可能通过持续干扰、节点损耗和伪装接入扩大压力；当平台能源、"
        "接口余量或网络资源不足时，该能力将进入失效边界。建设中需要区分公开事实、综合推断和工程"
        "假设，避免对未经校准的性能增益作精确承诺，并通过多场景演训复核适用条件与不确定性。"
    )
    portrait = (portrait * 2)[:420]

    def support_direction(name: str, capability_type: str) -> dict:
        row = {
            "name": name,
            "type": capability_type,
            "function": "保持通信与保障连续性",
            "equipment_form": "现役指挥车船通信终端与多链路任务系统",
            "operational_mechanism": "在链路受压时切换通道并恢复消息同步",
            "military_value": "提升持续作战与任务保障能力",
            "strike_countermeasure_value": "降低通信中断风险",
            "development_path": "近期改装—中期集成—演训验证",
            "verification": "关键消息送达率与恢复时间",
            "future_trigger": "未来强电磁干扰常态化",
            "adversary_adaptation": "对手转向多点压制和节点损耗",
            "failure_boundary": "平台能源与接口余量不足时失效",
            "capability_portrait": portrait,
        }
        if capability_type == "upgrade":
            row.update(
                {
                    "baseline_system": "现役海空前沿指挥车船通信任务系统",
                    "upgrade_package": ["多模通信终端", "链路管理模块"],
                    "combat_effect_uplift": "提高关键消息送达率和任务连续性",
                    "strike_chain_contribution": "保持信息流转与任务保底",
                    "upgrade_boundary": "平台余量不足时转入新研",
                }
            )
        return row

    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                support_direction(
                    "现役海空前沿指挥车船多链路任务保底通信升级",
                    "upgrade",
                ),
                support_direction("分布式通信网关恢复系统", "new_capability"),
                support_direction("任务数据审计与接口治理系统", "new_capability"),
            ]
        }
    )

    assert any("高阶作战效果" in issue for issue in issues)
    assert any("现役升级名称未体现" in issue for issue in issues)
    assert any("直接作战效应装备未构成组合主体" in issue for issue in issues)
    assert any("不得把普通通信" in issue for issue in issues)


def test_s6_support_subcomponent_does_not_reclassify_direct_weapon_direction() -> None:
    direction = {
        "name": "可消耗空海无人目标托管集群形成远火命中窗口",
        "function": "持续生成火力可用目标包并引导再打击",
        "equipment_form": "无人机、无人艇、模块化载荷和前沿快速补给箱组",
        "military_value": "提升目标发现、火力分配和远程毁伤效率",
        "operational_mechanism": "无人节点受损后重构角色并保持目标跟踪",
    }

    assert provider_module._is_ordinary_support_direction(direction) is False


def test_s6_camouflage_submodule_does_not_reclassify_fire_control_vehicle() -> None:
    direction = {
        "name": "机动被动探测火控车",
        "function": "静默发现目标并输出火控摘要",
        "equipment_form": (
            "高机动被动射频/光电探测车、边缘火控计算单元和"
            "伪装机动发射协同模块"
        ),
        "military_value": "提升目标发现、火力分配和再打击质量",
    }

    assert provider_module._is_ancillary_support_equipment_direction(direction) is False


def test_s6_quality_gate_requires_query_specific_direct_lethal_weapon_portfolio() -> None:
    portrait = (
        "该方向面向强干扰条件下目标发现到火力打击阶段，通过具体装备完成目标识别、火力分配、"
        "拦截、毁伤评估和再次打击。相对现役基线，新增机制把传感器、火控和效应器组合为可验证"
        "任务链，并针对对手诱饵、压制和节点损耗形成反适应。近期完成现役系统改装，中期形成样机"
        "并开展体系联试；若目标航迹连续率、火力任务续接率和毁伤闭合率不能提高，则降低优先级。"
        "验证采用红蓝对抗、实弹或半实物试验，不对未经校准的性能增益作精确承诺。"
    )
    portrait = (portrait * 2)[:420]

    def direction(name: str, equipment_form: str, capability_type: str) -> dict:
        row = {
            "name": name,
            "type": capability_type,
            "function": "发现并打击高价值目标",
            "equipment_form": equipment_form,
            "operational_mechanism": "通过目标识别、火力分配和效应器协同完成拦截毁伤",
            "military_value": "提升目标猎歼、拦截和再打击能力",
            "strike_countermeasure_value": "形成直接打击与反制效果",
            "development_path": "近期改装，中期样机研制与对抗验证",
            "future_trigger": "低成本饱和威胁持续增加",
            "adversary_adaptation": "对手采用诱饵、干扰和分布式机动",
            "failure_boundary": "目标质量和火控精度不足时失效",
            "verification": "目标发现至毁伤闭合率",
            "capability_portrait": portrait,
        }
        if capability_type == "upgrade":
            row.update(
                {
                    "baseline_system": equipment_form,
                    "upgrade_package": ["目标识别模块", "火控任务软件"],
                    "combat_effect_uplift": "提高目标拦截与毁伤效率",
                    "strike_chain_contribution": "缩短发现到打击闭环",
                    "upgrade_boundary": "平台余量不足时转入新研",
                }
            )
        return row

    missing_weapons = {
        "concept_directions": [
            direction("现役预警机目标识别与火力引导升级", "现役预警机与联合火控系统", "upgrade"),
            direction("分布式雷达目标猎获系统", "机动雷达与光电传感器", "new_capability"),
            direction("电子战目标压制系统", "电子战任务系统", "new_capability"),
        ]
    }
    issues = _capability_direction_quality_issues(missing_weapons)
    assert any("杀伤/反杀伤武器装备方向" in issue for issue in issues)
    assert not any("必须包含无人" in issue for issue in issues)

    unrelated_query_issues = _capability_direction_quality_issues(
        missing_weapons,
        handoff={"query": "社会化资源参与战时工业动员装备研究"},
    )
    assert not any("当前query涉及无人" in issue for issue in unrelated_query_issues)
    assert not any(
        "当前query涉及远程火力" in issue for issue in unrelated_query_issues
    )

    complete_portfolio = {
        "concept_directions": [
            direction("现役防空导弹抗饱和拦截升级", "现役防空导弹与联合火控系统", "upgrade"),
            direction("远域无人机目标猎歼系统", "察打一体无人机与协同攻击载荷", "new_capability"),
            direction("远程反舰导弹连续打击系统", "远程反舰导弹、发射单元与联合火控系统", "new_capability"),
            direction("低空反无人高功率微波压制器", "高功率微波反无人效应器", "new_capability"),
            direction("深海无人潜航器鱼雷伏击系统", "无人潜航器与重型鱼雷载荷", "new_capability"),
        ]
    }
    complete_issues = _capability_direction_quality_issues(complete_portfolio)
    assert not any("无人作战装备方向" in issue for issue in complete_issues)
    assert not any("杀伤/反杀伤武器装备方向" in issue for issue in complete_issues)
    assert not any("4个相互区分的直接武器" in issue for issue in complete_issues)

    fire_platform_portfolio = {
        "concept_directions": [
            direction("抗干扰远程精确制导弹药", "陆基远程精确制导弹药", "new_capability"),
            direction("可消耗无人搜索打击平台", "察打一体可消耗无人机", "new_capability"),
            direction("多模拒打巡飞弹药", "中小型巡飞弹药", "new_capability"),
            direction("HIMARS/NMESIS断链拒止升级", "HIMARS、NMESIS机动发射车", "upgrade"),
            direction("低特征前沿精确火力车", "模块化发射箱与低特征火力车", "new_capability"),
        ]
    }
    fire_platform_issues = _capability_direction_quality_issues(
        fire_platform_portfolio
    )
    assert not any(
        "4个相互区分的直接武器" in issue
        for issue in fire_platform_issues
    )

    two_direct_only = {
        "concept_directions": [
            direction("现役预警机目标识别与火力引导升级", "现役预警机与联合火控系统", "upgrade"),
            direction("远域无人机目标猎歼系统", "察打一体无人机与协同攻击载荷", "new_capability"),
            direction("远程反舰导弹连续打击系统", "远程反舰导弹、发射单元与联合火控系统", "new_capability"),
            direction("分布式雷达目标猎获系统", "机动雷达与光电传感器", "new_capability"),
            direction("联合火控目标分配系统", "联合火控系统与任务传感器", "new_capability"),
        ]
    }
    two_direct_issues = _capability_direction_quality_issues(two_direct_only)
    portfolio_warning = next(
        issue for issue in two_direct_issues if "武器未构成组合主体" in issue
    )
    assert provider_module._s6_delivery_blocking_issues([portfolio_warning]) == []

    ammunition_support_false_positive = {
        "concept_directions": [
            direction(
                "现役预警机目标识别与火力引导升级",
                "现役预警机与联合火控系统",
                "upgrade",
            ),
            direction(
                "远域无人机目标猎歼系统",
                "察打一体无人机与协同攻击载荷",
                "new_capability",
            ),
            direction(
                "现役自行火炮与弹药补给车辆火力续行升级",
                "现役自行火炮、炮兵指挥车和弹药补给车辆",
                "upgrade",
            ),
        ]
    }
    false_positive_issues = _capability_direction_quality_issues(
        ammunition_support_false_positive
    )
    assert not any("独立导弹或精确制导弹药方向" in issue for issue in false_positive_issues)


def test_s6_missile_direction_must_be_semantically_relevant_to_query() -> None:
    portrait = (
        "该方向面向海上区域拒止条件下的交战阶段，以独立导弹武器和联合火控完成目标识别、"
        "火力分配、突防、毁伤评估和再次打击。相对现役基线，新增抗干扰制导、任务重规划"
        "和多平台协同发射机制，并针对对手饱和突防、诱饵和节点损耗形成反适应。近期完成"
        "现役系统改装，中期形成样机并开展体系联试；验证采用红蓝对抗、实弹或半实物试验，"
        "若有效交战闭环和毁伤闭合率不能提高，则降低优先级。"
    )
    direction = {
        "name": "远程反舰导弹连续打击系统",
        "type": "new_capability",
        "function": "发现并打击海上高价值目标",
        "equipment_form": "远程反舰导弹、发射单元与联合火控系统",
        "operational_mechanism": "通过目标识别、火力分配和协同突防完成连续毁伤",
        "military_value": "提升海上区域拒止、反舰毁伤和再打击能力",
        "strike_countermeasure_value": "形成远程反舰打击与抗饱和反制效果",
        "development_path": "近期分系统改进，中期样机研制与对抗验证",
        "future_trigger": "强干扰与饱和突防威胁持续增加",
        "adversary_adaptation": "对手采用诱饵、干扰和分布式机动",
        "failure_boundary": "目标质量和制导火控精度不足时失效",
        "baseline_system": "现役岸舰导弹和海上目标指示体系",
        "capability_gap": "强干扰下连续目标保持和多波次毁伤能力不足",
        "capability_portrait": (portrait * 2)[:500],
        "query_relevance": (
            "面向陆上边境巡逻任务，在日常警戒阶段应对普通车辆目标，"
            "通过导弹打击提升火力效果"
        ),
    }
    handoff = {
        "query": "评估我军现役海上区域拒止体系在强干扰与饱和突防条件下的装备能力差距"
    }

    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                direction,
                {**direction, "name": "远域无人机目标猎歼系统", "equipment_form": "察打一体无人机", "type": "upgrade", "upgrade_package": ["火控软件", "任务载荷"], "combat_effect_uplift": "提升猎歼与毁伤能力", "strike_chain_contribution": "缩短发现到打击闭环", "upgrade_boundary": "平台余量不足时转入新研"},
                {**direction, "name": "机动雷达防空拦截引导系统", "equipment_form": "机动雷达与防空火控系统"},
            ]
        },
        handoff=handoff,
    )

    assert any("未保留当前query的主题锚点" in issue for issue in issues)


def test_s6_missile_query_relevance_requires_stage_pressure_and_effect() -> None:
    direction = {
        "name": "低成本防空拦截弹药系统",
        "query_relevance": "该方向与局部战争中的装备需求相关，需要发展新型弹药。",
    }

    issues = _query_relevance_issues(
        2,
        direction,
        query="从近年局部战争中挖掘我军装备发展需求",
    )

    assert not any("主题锚点" in issue for issue in issues)
    assert any("作战阶段" in issue for issue in issues)
    assert any("威胁压力" in issue for issue in issues)
    assert any("直接作战效果" in issue for issue in issues)


def test_s6_query_relevance_accepts_degraded_communications_topic_anchors() -> None:
    direction = {
        "name": "远程精确制导弹药",
        "query_relevance": (
            "面向弱通信条件下的首轮打击阶段，应对导航压制和目标更新稀疏压力，"
            "保持对高价值节点的精确毁伤与区域拒止。"
        ),
    }

    issues = _query_relevance_issues(
        1,
        direction,
        query="强干扰、弱通信条件下低信息依赖精确打击研究",
    )

    assert not any("主题锚点" in issue for issue in issues)


def test_s6_direction_name_recognizes_loitering_munition_as_equipment_object() -> None:
    assert provider_module._direction_name_has_equipment_object(
        {
            "name": "中小型反辐射巡飞弹目标发现",
            "equipment_form": "中小型反辐射巡飞弹与被动射频载荷",
        }
    ) is True
    assert provider_module._direction_name_has_equipment_object(
        {
            "name": "PrSM Increment 1/2火力升级",
            "equipment_form": "PrSM Increment 1/2类陆基远程精确制导弹药",
        }
    ) is True

    assert provider_module._direction_name_has_equipment_object(
        {
            "name": "可消耗远程电子压制弹火力",
            "equipment_form": "远程电子压制弹与被动射频导引载荷",
        }
    ) is True

    assert provider_module._direction_name_has_equipment_object(
        {
            "name": "现役Tomahawk Block V火力升级",
            "equipment_form": "现役Tomahawk Block V巡航导弹与舰载发射系统",
        }
    ) is True


def test_s6_recognizes_semantic_combat_munition_compound() -> None:
    direction = {
        "name": "远程可消耗电子诱骗弹火力",
        "equipment_form": "远程电子诱骗弹与任务载荷",
        "military_value": "压制防空雷达并为主攻弹群制造突防窗口",
    }

    assert provider_module._direction_name_has_equipment_object(direction) is True
    assert provider_module._is_missile_precision_munition_direction(direction) is True


def test_s6_rejects_support_mission_disguised_with_unmanned_and_firepower() -> None:
    direction = {
        "name": "小型无人机回收/数据读取接口火力",
        "equipment_form": "小型无人机、回收装置与数据读取接口",
        "function": "回收平台并读取任务数据",
        "military_value": "提升任务数据复盘效率",
    }

    assert provider_module._is_ordinary_support_direction(direction) is True
    assert provider_module._is_lethal_weapon_equipment_direction(direction) is False


def test_s6_title_normalizer_collapses_enumerative_loitering_munition_title() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "舰载或前沿箱式发射的巡飞弹目标发现",
                    "type": "new_capability",
                    "equipment_form": "车载、舰载或前沿箱式发射的巡飞弹",
                    "function": "在弱通信和目标更新稀疏条件下搜索确认目标",
                    "query_relevance": "低信息依赖条件下承担目标发现和有限毁伤",
                }
            ]
        },
        topic="强干扰、弱通信条件下低信息依赖精确打击研究",
    )

    assert normalized["concept_directions"][0]["name"] == "低信息侦打巡飞弹"


def test_s6_title_normalizer_differentiates_generic_new_weapon_class() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "反辐射巡飞弹",
                    "type": "new_capability",
                    "equipment_form": "反辐射巡飞弹、被动射频寻的与末端光电确认传感器",
                    "function": "搜索间歇开机雷达并实施压制毁伤",
                    "novelty": "以末端光电复核降低假辐射源诱骗风险",
                }
            ]
        },
        topic="强电磁压制下精确打击装备研究",
    )

    assert normalized["concept_directions"][0]["name"] == "多模复核反辐射巡飞猎歼弹"


def test_s6_title_normalizer_repairs_name_only_equipment_defects_without_model() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "远域压制开窗",
                    "type": "new_capability",
                    "equipment_form": "可消耗远程电子压制弹与被动射频导引载荷",
                    "function": "压制敌防空雷达并制造主攻火力突防窗口",
                    "military_value": "提升突防、压制和毁伤效果",
                },
                {
                    "name": "现役低信息火力升级",
                    "type": "upgrade",
                    "baseline_system": "现役Tomahawk Block V巡航导弹",
                    "equipment_form": "Tomahawk Block V巡航导弹与舰载发射系统",
                    "combat_effect_uplift": "提升弱通信条件下的远程毁伤能力",
                    "strike_chain_contribution": "保持打击和再打击闭环",
                },
            ]
        },
        topic="强干扰、弱通信条件下低信息依赖精确打击研究",
    )

    names = [item["name"] for item in normalized["concept_directions"]]
    assert "电子压制弹" in names[0]
    assert names[1] == "舰载抗扰巡航导弹精确毁伤"
    assert "升级" not in names[1]
    assert provider_module._direction_name_has_equipment_object(
        normalized["concept_directions"][0]
    )
    assert provider_module._direction_name_has_equipment_object(
        normalized["concept_directions"][1]
    )


def test_s6_normalizer_projects_query_anchor_without_model_repair() -> None:
    direction = {
        "name": "低空诱饵压制巡飞弹开窗",
        "type": "new_capability",
        "equipment_form": "低空诱饵压制巡飞弹",
        "query_relevance": (
            "在突防与交战阶段应对敌防空压制和诱饵压力，形成压制开窗并提升主弹毁伤效果。"
        ),
    }

    normalized = _normalize_s6_deterministic_format(
        {"concept_directions": [direction]},
        topic="强干扰、弱通信条件下低信息依赖精确打击研究",
    )
    normalized_direction = normalized["concept_directions"][0]

    assert "强干扰" in normalized_direction["query_relevance"]
    assert "弱通信" in normalized_direction["query_relevance"]
    assert not _query_relevance_issues(
        1,
        normalized_direction,
        query="强干扰、弱通信条件下低信息依赖精确打击研究",
    )


def test_s6_normalizer_projects_electromagnetic_and_gnss_pressure() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "远程反舰导弹",
                    "type": "new_capability",
                    "equipment_form": "远程反舰导弹",
                    "query_relevance": (
                        "在补击与交战阶段应对目标机动压力，形成末段再捕获和直接毁伤。"
                    ),
                }
            ]
        },
        topic="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
    )

    relevance = normalized["concept_directions"][0]["query_relevance"]
    assert "强电磁压制" in relevance
    assert "GNSS拒止" in relevance
    assert not _query_relevance_issues(
        1,
        normalized["concept_directions"][0],
        query="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
    )


def test_s6_dynamic_full_cards_rebuild_distinct_weapon_portraits() -> None:
    common = {
        "type": "upgrade",
        "priority": "P1",
        "confidence": 0.82,
        "feasibility": "4",
        "feasibility_basis": "依据公开基线、工程约束和对抗试验校准",
        "horizon": "mid",
        "direct_evidence_refs": ["ev-1"],
        "derived_from": ["公开证据与候选制胜机理综合"],
        "development_path": "完成工程样机、接口联试与实装对抗试验",
        "future_trigger": "强干扰与短时目标暴露成为常态",
        "adversary_adaptation": "对手增加诱饵、机动与局部拦截",
        "verification": "开展受扰条件下的红蓝对抗验证",
        "upgrade_boundary": "平台余量不足时转入新研",
    }
    anti_radiation = {
        **common,
        "hypothesis_id": "anti-radiation",
        "name": "前出反辐射巡飞侦打一体平台",
        "equipment_form": "长航时反辐射巡飞弹药",
        "baseline_system": "Harop类长航时巡飞弹药",
        "mission_effects": ["迫使敌雷达静默并摧毁真实辐射节点"],
        "function": "压制敌防空雷达",
        "military_value": "迫使敌雷达静默并摧毁真实辐射节点",
        "combat_effect_uplift": "扩大远程反舰火力突防窗口",
        "strike_chain_contribution": "前出搜索→关机等待→复核目标→授权毁伤",
        "target_scenario": "反舰突击进入敌岸基防空区前的雷达间歇开机阶段",
        "capability_gap": "现役反辐射弹药难以跨越关机窗口并排除诱饵",
        "problem_statement": "真实雷达关机转移与诱饵辐射造成目标丢失",
        "scientific_principle": "关机前辐射记忆与末端独立复核",
        "enabling_technologies": ["宽带被动射频", "弹载目标记忆", "光电末端复核"],
        "operational_concept": "前出巡飞、辐射源搜索、关机等待、末端复核与受控毁伤",
        "operational_process": ["前出部署", "辐射搜索", "关机等待", "光电复核", "授权毁伤"],
        "capability_outcome": "跨越关机窗口猎杀真实防空雷达",
        "winning_mechanism": "迫使雷达在持续开机暴露与关机失去火控之间两难",
        "novelty": "关机等待与多模复核",
        "query_relevance": "在突防阶段应对敌雷达诱饵压力并形成毁伤",
        "upgrade_package": ["射频任务载荷", "光电复核组件"],
        "failure_boundary": "目标无法形成任何辐射与光学证据时拒打",
        "failure_boundaries": ["目标完全转入地下"],
        "validation_plan": ["测试关机再捕获率与诱饵误接受率"],
        "mechanism_chain": ["前出搜索", "关机等待", "末端复核", "授权毁伤"],
        "equipment_forms": ["长航时反辐射巡飞弹药"],
        "system_interfaces": ["射频任务载荷接口", "火控授权接口"],
        "evidence_ids": ["ev-1"],
    }
    precision_missile = {
        **common,
        "hypothesis_id": "prsm",
        "name": "PrSM类地射远程多模末制导导弹",
        "equipment_form": "PrSM类地射远程多模末制导导弹",
        "baseline_system": "PrSM公开开放架构基线",
        "mission_effects": ["远程毁伤短时暴露的岸基反舰与防空节点"],
        "function": "远程精确毁伤",
        "military_value": "远程毁伤短时暴露的岸基反舰与防空节点",
        "combat_effect_uplift": "提高坐标过期后的再捕获与有效毁伤率",
        "strike_chain_contribution": "分散接令→机动发射→抗扰飞行→末段再捕获→毁伤评估",
        "target_scenario": "远海反舰交战后敌岸基机动发射车短时再暴露阶段",
        "capability_gap": "现役地射导弹在GNSS拒止与坐标过期后末段再捕获不足",
        "problem_statement": "机动目标在飞行时间内转移且导航受扰",
        "scientific_principle": "目标有效期控制与多模末段再捕获",
        "enabling_technologies": ["抗扰组合导航", "多模末制导", "目标包有效期管理"],
        "operational_concept": "分散接令、机动发射、受扰飞行、末段再捕获与安全拒打",
        "operational_process": ["分散接令", "机动发射", "抗扰飞行", "末段搜索", "再捕获或拒打"],
        "capability_outcome": "对坐标过期的机动目标实施远程精确毁伤",
        "winning_mechanism": "以末段独立证据压缩目标依靠转移和坐标过期获得的逃逸收益",
        "novelty": "开放接口集成固定多模末制导段",
        "query_relevance": "在补击阶段应对导航拒止与目标机动压力并形成直接毁伤",
        "upgrade_package": ["抗扰组合导航组件", "多模末制导段"],
        "failure_boundary": "末段无法形成可靠识别证据时拒打",
        "failure_boundaries": ["目标有效期耗尽"],
        "validation_plan": ["测试再捕获率、命中率和正确拒打率"],
        "mechanism_chain": ["分散接令", "机动发射", "抗扰飞行", "末段再捕获"],
        "equipment_forms": ["PrSM类地射远程多模末制导导弹"],
        "system_interfaces": ["开放任务总线", "目标包装订接口"],
        "evidence_ids": ["ev-2"],
    }

    normalized = _normalize_s6_deterministic_format(
        {"concept_directions": [anti_radiation, precision_missile]},
        topic="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
    )
    portraits = [item["capability_portrait"] for item in normalized["concept_directions"]]

    assert all(len(item) >= 900 for item in portraits)
    assert all(
        120 <= len(item.split("\n", 1)[0].removeprefix("概述：")) <= 360
        for item in portraits
    )
    assert SequenceMatcher(None, portraits[0], portraits[1]).ratio() < 0.9


def test_s6_title_compactor_keeps_weapon_identity_short_and_classifiable() -> None:
    directions = [
        {
            "name": "长航时可消耗反舰巡飞猎歼弹药自主续接方向",
            "equipment_form": "长航时可消耗多模反舰巡飞猎歼弹药",
            "military_value": "在强干扰下再捕获并毁伤海上目标",
        },
        {
            "name": "射后自主再捕获多模反舰任务弹药升级方向",
            "equipment_form": "射后自主再捕获多模反舰任务弹药",
            "military_value": "在GNSS拒止下实施末段再捕获与毁伤",
        },
        {
            "name": "批量可消耗低空无人携弹平台首击后补打",
            "equipment_form": "批量可消耗低空察打一体无人携弹平台",
            "military_value": "对首击漏毁目标实施本机复核与直接补射",
        },
    ]

    titles = [provider_module._compact_capability_direction_title(item) for item in directions]

    assert titles == [
        "长航时可消耗多模反舰巡飞猎歼弹药",
        "多模再捕获反舰导弹",
        "低空可消耗察打一体无人机",
    ]
    assert all(len(item) <= 24 for item in titles)
    assert provider_module._is_missile_precision_munition_direction(
        {**directions[0], "name": titles[0]}
    )
    assert provider_module._is_missile_precision_munition_direction(
        {**directions[1], "name": titles[1]}
    )
    assert provider_module._direction_name_has_equipment_object(
        {**directions[2], "name": titles[2]}
    )


def test_dynamic_portfolio_prioritizes_weapon_object_evidence_refs() -> None:
    refs = provider_module._prioritize_equipment_evidence_refs(
        [
            "ev-combat_scenario-web-1",
            "ev-operational_employment-web-1",
            "ev-weapon_equipment-web-harop",
            "ev-weapon_equipment-web-prsm",
            "ev-combat_scenario-web-1",
        ]
    )

    assert refs == [
        "ev-weapon_equipment-web-harop",
        "ev-weapon_equipment-web-prsm",
        "ev-combat_scenario-web-1",
        "ev-operational_employment-web-1",
    ]


def test_s6_title_compactor_uses_primary_equipment_identity_only() -> None:
    fire_rocket = {
        "name": "分布式机动火箭炮再打击",
        "type": "new_capability",
        "equipment_form": "轮式机动火箭炮与远程制导火箭弹",
        "military_value": "在弱通信条件下完成二次齐射和补打毁伤",
        "capability_portrait": "与巡飞弹协同搜索后实施再打击。",
    }
    unmanned_vehicle = {
        "name": "被动测向反辐射无人车猎杀",
        "type": "new_capability",
        "equipment_form": "履带式被动测向反辐射无人车与短程毁伤载荷",
        "military_value": "猎杀敌电子战干扰源并恢复打击窗口",
        "capability_portrait": "可与巡飞弹共享搜索结果，在弱通信下协同。",
    }

    assert provider_module._compact_capability_direction_title(fire_rocket) != "低信息侦打巡飞弹"
    assert provider_module._compact_capability_direction_title(unmanned_vehicle) != "低信息侦打巡飞弹"

    anti_radiation_loitering = {
        "name": "低信息反辐射节点猎杀",
        "type": "new_capability",
        "equipment_form": "中远程反辐射巡飞弹与宽带被动射频载荷",
        "military_value": "在弱通信下搜索并猎杀敌电子战干扰源",
    }
    assert (
        provider_module._compact_capability_direction_title(anti_radiation_loitering)
        == "自主猎杀反辐射巡飞弹"
    )


def test_s6_title_compactor_preserves_upgrade_combat_gain() -> None:
    direction = {
        "name": "长航时反辐射巡飞弹药再捕获",
        "type": "upgrade",
        "equipment_form": "长航时反辐射巡飞弹药",
        "baseline_system": "AARGM-ER反辐射导弹",
        "military_value": "在辐射源关机后维持目标记忆并实施再捕获",
        "operational_mechanism": "目标记忆→末段再捕获→压制防空节点",
    }

    assert provider_module._compact_capability_direction_title(direction) == (
        "长航时反辐射巡飞弹药再捕获"
    )


def test_s6_title_compactor_keeps_public_jassm_baseline_out_of_project_name() -> None:
    direction = {
        "name": "JASSM/JASSM-ER火力",
        "type": "upgrade",
        "equipment_form": (
            "远程低可探测巡航弹，配多源抗扰导航组件、被动/成像复核末制导、"
            "目标包时效管理、失联等待/拒打任务软件和低带宽毁伤摘要回传模块。"
        ),
        "baseline_system": "JASSM/JASSM-ER类空射防区外精确打击弹药",
        "function": (
            "在连续数据链中断和目标包可能过期条件下，对敌纵深节点进行末段复核、"
            "受控毁伤、拒打等待和补击接替。"
        ),
        "military_value": "在弱网失联条件下复核、拒打并续接补击。",
        "combat_effect_uplift": "降低误击和弹药空耗，续接纵深补击。",
    }

    title = provider_module._compact_capability_direction_title(direction)
    normalized = provider_module._normalize_s6_deterministic_format(
        {"concept_directions": [direction], "confidence": 0.71},
        topic="西太前沿机场受毁与强电磁压制下跨岛链无人远程火力持续释能",
    )["concept_directions"][0]

    assert title == "失联复核远程巡航弹"
    assert normalized["name"] == "失联复核远程巡航弹"
    assert provider_module._direction_name_has_equipment_object(normalized)
    assert provider_module._is_missile_precision_munition_direction(normalized)


def test_s6_normalizer_disambiguates_semantically_distinct_title_collisions() -> None:
    shared = {
        "name": "长航时可消耗多模反舰巡飞猎歼弹药再捕获",
        "type": "upgrade",
        "equipment_form": "长航时可消耗多模反舰巡飞猎歼弹药",
        "baseline_system": "LRASM/JASSM与Harop公开装备基线",
        "function": "对机动水面目标实施再捕获和直接毁伤",
        "military_value": "形成断链后的目标再发现与毁伤效果",
        "capability_gap": "外部目标更新中断后需要弹上续接",
    }
    normalized = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    **shared,
                    "hypothesis_id": "responsibility-zone",
                    "source_hypothesis_title": "时空责任区自治型远程反舰巡飞弹药群",
                    "operational_mechanism": (
                        "多枚弹药按预置责任区分区搜索，以空间分工扩大目标可能区覆盖"
                    ),
                },
                {
                    **shared,
                    "hypothesis_id": "collaborative-dedup",
                    "source_hypothesis_title": "协同去重型远程反舰巡飞弹药群",
                    "operational_mechanism": (
                        "弹间交换目标摘要并协同去重，避免重复追逐同一疑似目标"
                    ),
                },
            ],
            "confidence": 0.8,
        },
        topic="强电磁压制与GNSS拒止下远程反舰火力链续接",
    )

    titles = [item["name"] for item in normalized["concept_directions"]]
    assert titles == [
        "分区搜索反舰巡飞猎歼弹药",
        "协同去重反舰巡飞猎歼弹药",
    ]
    assert len(set(titles)) == 2
    assert all(len(title) <= 24 for title in titles)
    assert all(
        provider_module._direction_name_has_equipment_object(item)
        for item in normalized["concept_directions"]
    )


def test_s6_normalizer_preserves_subtype_flows_and_does_not_fake_semantic_distinction() -> None:
    shared = {
        "name": "多模再捕获远程反舰巡航弹药",
        "type": "upgrade",
        "equipment_form": "多模导引自主再捕获远程反舰巡航弹药",
        "baseline_system": "LRASM/JASSM远程反舰巡航弹药公开基线",
        "function": "断链后再捕获并直接毁伤机动水面舰艇",
        "military_value": "在外部更新中断后形成直接反舰毁伤",
        "capability_gap": "目标航迹陈旧后远程反舰火力难以完成安全再捕获",
        "mission_effects": ["直接反舰毁伤"],
        "target_scenario": "强电磁压制与GNSS拒止下远海反舰齐射后的目标复获阶段",
        "scientific_principle": "把断链容错前移至弹上自主搜索与身份复核",
        "enabling_technologies": ["抗扰组合导航", "多模身份复核", "安全弃攻"],
        "operational_concept": "目标装订、抗扰进入、搜索复核与受控毁伤",
        "capability_outcome": "断链后再捕获并直接毁伤经授权水面舰艇",
        "winning_mechanism": "压缩对手利用航迹过期脱离接触的时间窗口",
        "development_path": "完成数字靶场、半实物联试和实装对抗验证",
        "failure_boundary": "搜索区超出剩余能量或身份置信度不足时拒打",
        "verification": "以再捕获、重复攻击、拒打和直接毁伤结果决定转段",
        "confidence": 0.8,
        "direct_evidence_refs": ["ev-weapon_equipment-1"],
        "query_relevance": (
            "面向远海反舰目标复获阶段的强电磁压制和GNSS拒止压力，"
            "续接断裂火力链并直接毁伤机动水面舰艇"
        ),
        "future_trigger": "目标活动海域受限且保有最后可信航迹时优先",
        "adversary_adaptation": "对手使用诱饵、编队分散和航向突变扩大搜索负荷",
        "upgrade_package": ["抗扰组合导航", "多模身份复核"],
        "combat_effect_uplift": "提高断链后再捕获与直接毁伤概率",
        "strike_chain_contribution": "发射—进入—搜索—身份复核—毁伤或拒打",
        "upgrade_boundary": "基础弹体能源、算力和导引头视场必须闭合",
    }
    normalized = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    **shared,
                    "hypothesis_id": "finite-search",
                    "source_hypothesis_title": "有限扇区单弹再捕获",
                    "operational_mechanism": (
                        "单弹按有限扇区、航迹陈旧度和剩余能量搜索，"
                        "身份复核后直接毁伤或拒打"
                    ),
                    "operational_process": [
                        "目标有效期装订",
                        "搜索区与能量校核",
                        "单弹抗扰进入",
                        "有限区搜索",
                        "身份复核",
                        "直接毁伤或拒打",
                    ],
                },
                {
                    **shared,
                    "hypothesis_id": "coordinated-dedup",
                    "source_hypothesis_title": "多弹目标摘要协同",
                    "operational_mechanism": (
                        "多弹按扇区分工并交换目标摘要，避免重复攻击同一疑似舰艇，"
                        "失联后独立搜索"
                    ),
                    "operational_process": [
                        "齐射扇区分配",
                        "抗扰进入",
                        "局部目标发现",
                        "摘要交换",
                        "重复判定",
                        "独立毁伤或改搜",
                    ],
                },
            ],
            "confidence": 0.8,
        },
        topic="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
    )

    finite, coordinated = normalized["concept_directions"]
    assert finite["name"] == "有限区搜索远程反舰巡航弹药"
    assert coordinated["name"] == "协同去重远程反舰巡航弹药"
    assert finite["operational_process"] == [
        "目标有效期装订",
        "搜索区与能量校核",
        "单弹抗扰进入",
        "有限区搜索",
        "身份复核",
        "直接毁伤或拒打",
    ]
    assert coordinated["operational_process"] == [
        "齐射扇区分配",
        "抗扰进入",
        "局部目标发现",
        "摘要交换",
        "重复判定",
        "独立毁伤或改搜",
    ]
    assert _capability_text_similarity(
        finite["capability_portrait"],
        coordinated["capability_portrait"],
    ) >= 0.90
    pairwise_issues = [
        issue
        for issue in _capability_direction_quality_issues(normalized)
        if "机制高度重复" in issue
    ]
    assert pairwise_issues


def test_s6_normalizer_preserves_loitering_subtype_flows_without_keyword_rewrite() -> None:
    shared = {
        "name": "长航时多模反舰巡飞猎歼弹药",
        "type": "upgrade",
        "equipment_form": "长航时可消耗多模反舰巡飞猎歼弹药",
        "baseline_system": "Harop与公开空射巡飞弹药基线",
        "function": "断链后持续搜索、复核并直接攻击机动水面舰艇",
        "military_value": "延长目标保管并形成断链后的直接反舰毁伤",
        "capability_gap": "外部目标更新中断后缺少可在位搜索并自主复核的直接攻击弹药",
        "mission_effects": ["直接反舰毁伤"],
        "target_scenario": "强电磁压制与GNSS拒止下远海反舰火力链断裂后的目标复获阶段",
        "scientific_principle": "把目标保管、身份复核与受控攻击闭环前移到巡飞猎歼弹上",
        "enabling_technologies": ["抗扰组合导航", "多模身份复核", "安全弃攻"],
        "operational_concept": "任务装订、分散进入、在位搜索、身份复核与受控攻击",
        "capability_outcome": "断链后保持目标接触并直接毁伤经授权水面舰艇",
        "winning_mechanism": "压缩对手利用航迹过期和编队机动脱离接触的窗口",
        "development_path": "完成载机投放、半实物联试、海上靶场和红队对抗验证",
        "failure_boundary": "剩余能量不足或跨模态身份置信度不足时拒打",
        "verification": "以目标保管、身份复核、直接攻击、拒打和受扰生存结果决定转段",
        "confidence": 0.8,
        "direct_evidence_refs": ["ev-weapon_equipment-1"],
        "query_relevance": "续接强电磁压制与GNSS拒止下断裂的远程反舰火力链",
        "future_trigger": "外部航迹失效但保有目标可能区时优先",
        "adversary_adaptation": "对手采用关机静默、诱饵、编队分散和外围拦截扩大搜索与识别负荷",
        "upgrade_package": ["抗扰组合导航", "多模身份复核"],
        "combat_effect_uplift": "提高断链后目标保管、再捕获和直接毁伤概率",
        "strike_chain_contribution": "投放—进入—搜索—复核—直接攻击或拒打",
        "upgrade_boundary": "弹体能源、传感器暴露管理、载机投放包线和授权逻辑必须闭合",
    }
    normalized = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    **shared,
                    "hypothesis_id": "air-launched-batch-custody",
                    "source_hypothesis_title": "空射多轴错时投放与目标保管批次接替",
                    "operational_mechanism": (
                        "载机在防区外完成安全分离，多轴错时分批投放，后续批次接替前批目标保管并直接攻击"
                    ),
                    "operational_process": [
                        "载机释放窗口规划",
                        "安全分离",
                        "多轴错时投放",
                        "前批目标保管",
                        "后批保管接替",
                        "直接攻击或拒打",
                    ],
                },
                {
                    **shared,
                    "hypothesis_id": "rf-imaging-cross-check",
                    "source_hypothesis_title": "被动射频候选发现与成像交叉复核",
                    "operational_mechanism": (
                        "控制传感器暴露，以被动射频发现候选舰艇，再由成像传感器交叉确认并在外围拦截压力下直接攻击"
                    ),
                    "operational_process": [
                        "低特征进入",
                        "被动射频候选发现",
                        "成像传感器短时开启",
                        "跨模态交叉确认",
                        "外围拦截规避",
                        "直接攻击或拒打",
                    ],
                },
            ],
            "confidence": 0.8,
        },
        topic="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
    )

    air_launched, rf_verified = normalized["concept_directions"]
    assert air_launched["name"] == "空射反舰巡飞猎歼弹药"
    assert rf_verified["name"] == "射频复核反舰巡飞猎歼弹药"
    assert air_launched["operational_process"] == [
        "载机释放窗口规划",
        "安全分离",
        "多轴错时投放",
        "前批目标保管",
        "后批保管接替",
        "直接攻击或拒打",
    ]
    assert rf_verified["operational_process"] == [
        "低特征进入",
        "被动射频候选发现",
        "成像传感器短时开启",
        "跨模态交叉确认",
        "外围拦截规避",
        "直接攻击或拒打",
    ]
    assert _capability_text_similarity(
        air_launched["capability_portrait"],
        rf_verified["capability_portrait"],
    ) >= 0.90
    pairwise_issues = [
        issue
        for issue in _capability_direction_quality_issues(normalized)
        if "机制高度重复" in issue
    ]
    assert pairwise_issues


def test_s6_normalizer_keeps_substantive_duplicates_visible_to_hard_gate() -> None:
    duplicate = {
        "name": "低信息侦打巡飞弹",
        "type": "new_capability",
        "equipment_form": "车载低信息侦打巡飞弹",
        "baseline_system": "同一公开巡飞弹基线",
        "function": "搜索并打击同一目标",
        "military_value": "形成同一毁伤效果",
        "operational_mechanism": "按同一流程进入目标区并实施打击",
        "capability_gap": "同一能力差距",
    }
    normalized = provider_module._normalize_s6_deterministic_format(
        {"concept_directions": [duplicate, dict(duplicate)]}
    )

    assert [item["name"] for item in normalized["concept_directions"]] == [
        "低信息侦打巡飞弹",
        "低信息侦打巡飞弹",
    ]


def test_s6_normalizer_preserves_query_specific_prsm_weapon_identity() -> None:
    result = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "PrSM Increment 1已交火力",
                    "type": "upgrade",
                    "equipment_form": (
                        "一枚工厂固定构型的PrSM Increment 2类陆基远程反舰试验验证弹："
                        "保留HIMARS/M270兼容发射边界"
                    ),
                    "baseline_system": "PrSM Increment 1与HIMARS兼容发射基线",
                    "military_value": "对机动海上目标实施末段再捕获与毁伤",
                }
            ],
            "confidence": 0.8,
        },
        topic="强电磁压制与GNSS拒止下远程反舰火力链续接",
    )

    direction = result["concept_directions"][0]
    assert direction["equipment_form"] == "工厂固定构型的PrSM Increment 2类陆基远程反舰试验验证弹"
    assert direction["name"] == "地射远程机动目标精确毁伤导弹"
    assert provider_module._direction_mixes_distinct_weapon_families(direction) == {"prsm"}
    assert provider_module._capability_upgrade_effect_anchor(
        direction["equipment_form"],
        direction["name"],
    ) == "毁伤"


def test_s6_normalizer_preserves_query_specific_anti_ship_weapon_identity() -> None:
    result = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "LRASM/JASSM目标再捕获",
                    "type": "upgrade",
                    "equipment_form": "多模末制导远程反舰巡航弹药",
                    "baseline_system": (
                        "公开LRASM/JASSM低可探测防区外弹药作为对照基线"
                    ),
                    "source_hypothesis_title": "空射反舰弹药内生再捕获",
                    "military_value": "对机动水面目标实施再捕获和直接毁伤",
                }
            ]
        }
    )

    direction = result["concept_directions"][0]
    assert direction["equipment_form"] == "多模末制导远程反舰巡航弹药"
    assert direction["name"] == "多模再捕获反舰导弹"
    assert provider_module._direction_mixes_distinct_weapon_families(direction) == set()


def test_s6_normalizer_treats_public_baseline_caveat_as_evidence_not_primary_family() -> None:
    result = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "防区外巡航导弹补打",
                    "type": "new_capability",
                    "equipment_form": (
                        "远程巡航母弹，内置诱饵、被动侦察、短时电子压制和小型毁伤子弹药舱；"
                        "公开证据仅支撑JASSM/JASSM-ER与MALD/MALD-J等分立基线，"
                        "不证明成熟复合母弹已列装"
                    ),
                    "baseline_system": (
                        "公开基线为JASSM/JASSM-ER防区外巡航导弹和"
                        "MALD/MALD-J可消耗诱饵"
                    ),
                    "function": "后方机动射手一次起射并分时释放异构子效应器",
                    "military_value": "为后续精打火力制造突防窗口",
                }
            ]
        },
        topic="前沿机场受毁与强电磁压制下跨岛链无人远程火力持续释能",
    )

    direction = result["concept_directions"][0]
    assert direction["equipment_form"] == (
        "远程巡航母弹，内置诱饵、被动侦察、短时电子压制和小型毁伤子弹药舱"
    )
    assert direction["name"] == "异构子效应器巡航母弹"
    assert provider_module._direction_mixes_distinct_weapon_families(direction) == set()


def test_s6_family_gate_still_rejects_two_primary_families_without_evidence_caveat() -> None:
    direction = {
        "name": "远程精确打击联合升级",
        "equipment_form": "JASSM空射巡航导弹与PrSM地射远程导弹联合升级",
    }

    assert provider_module._direction_mixes_distinct_weapon_families(direction) == {
        "jassm",
        "prsm",
    }


def test_s6_title_compactor_recovers_unmanned_boat_and_common_airframe_objects() -> None:
    unmanned_boat = {
        "name": "可预置或远程投送火力",
        "equipment_form": "低特征自主无人艇",
        "operational_mechanism": "预置在关键航路实施伏击和直接撞击毁伤",
    }
    common_airframe = {
        "name": "采用共同推进火力",
        "equipment_form": "采用共同推进与发射接口的可消耗飞行弹体",
        "operational_mechanism": "任务前换装任务模块并形成混合齐射",
    }

    assert provider_module._compact_capability_direction_title(unmanned_boat) == (
        "航路伏击自主突击无人艇"
    )
    assert provider_module._compact_capability_direction_title(common_airframe) == (
        "共架可消耗多任务弹药"
    )


def test_s6_title_compactor_recovers_fresh_quality_platform_and_munition_objects() -> None:
    semi_submersible = {
        "name": "低特征无人半潜储射艇",
        "equipment_form": "具备远程弹药舱和安全终止功能的无人半潜储射平台",
        "function": "海上分散待机并按授权分批释放远程弹药",
    }
    common_cruise = {
        "name": "HIMARS/M270火力",
        "equipment_form": "陆海通用小型巡航打击弹及兼容箱式发射筒",
        "military_value": "以低成本可消耗弹药扩大批量库存和连续波次",
    }

    assert provider_module._compact_capability_direction_title(semi_submersible) == (
        "半潜预置巡航弹无人艇"
    )
    assert provider_module._compact_capability_direction_title(common_cruise) == (
        "陆海通用低成本巡航打击弹"
    )


def test_s6_title_compactor_reconciles_r8_proposed_equipment_with_public_baselines() -> None:
    land_decoy = {
        "name": "空射可消耗电子攻击压制效应器",
        "equipment_form": "陆基或近岸弹射的可消耗诱扰靶弹，配有限伴随干扰载荷",
        "function": "陆基弹射后模拟突防航迹，诱开雷达并消耗拦截弹",
        "baseline_system": "MALD/MALD-J空射诱饵与电子攻击基线",
    }
    unmanned_rocket_launcher = {
        "name": "HIMARS/M270火力",
        "equipment_form": "无人值守机动火箭发射车，配远程精确火箭弹兼容发射架",
        "function": "分散部署并对已暴露防空、远火和指挥节点实施快速补击",
        "baseline_system": "HIMARS/M270发射PrSM类远程精确弹药",
    }
    semi_submersible_magazine = {
        "name": "反舰巡飞猎歼弹药",
        "equipment_form": "无人半潜待机弹舱，内置容器化远程巡飞弹",
        "function": "近岸隐蔽驻留并发射巡飞弹拒止海上机动编队",
    }
    counter_swarm_vehicle = {
        "name": "电子战系统配合承担无人机拦截目标发现",
        "equipment_form": "车载反蜂群拦截系统，集成本地雷达和小型拦截弹",
        "function": "伴随分散火力点拦截无人侦察与巡飞弹，保护补射窗口",
    }

    assert provider_module._compact_capability_direction_title(land_decoy) == (
        "陆基远程防空压制诱饵弹"
    )
    assert provider_module._compact_capability_direction_title(
        unmanned_rocket_launcher
    ) == "无人值守远程精确打击火箭发射车"
    assert provider_module._compact_capability_direction_title(
        semi_submersible_magazine
    ) == "半潜预置反舰导弹火力舱"
    assert provider_module._compact_capability_direction_title(counter_swarm_vehicle) == (
        "节点护卫反无人机拦截车"
    )


def test_s6_gate_treats_mobile_rocket_launcher_as_bound_combat_equipment() -> None:
    direction = {
        "name": "无人值守远程精确打击火箭发射车",
        "equipment_form": "无人值守机动火箭发射车，配远程精确火箭弹兼容发射架",
        "function": "对已暴露防空和远火节点实施快速补击",
    }

    identity = f"{direction['name']} {direction['equipment_form']}"

    assert provider_module._direction_name_has_equipment_object(direction) is True
    assert any(
        term in identity
        for term in (
            *provider_module._DIRECT_COMBAT_EQUIPMENT_NAME_TERMS,
            *provider_module._CAPABILITY_EQUIPMENT_OBJECT_TERMS,
        )
    )


def test_s6_title_compactor_reconciles_r9_launcher_and_common_ea_munition() -> None:
    offline_rocket_launcher = {
        "name": "HIMARS/M270发射PrSM可火力",
        "equipment_form": (
            "箱式机动远程火箭发射车，配本地任务库、离线授权校验、"
            "PNT置信度判定和短报文更新接口，兼容PrSM类弹药作为公开对照"
        ),
        "function": "在断链环境中对防空和支援节点实施快速精确补击并组织邻车补射",
        "baseline_system": "HIMARS/M270发射PrSM的公开基线",
    }
    common_ea_munition = {
        "name": "航路伏击自主突击无人艇",
        "equipment_form": (
            "地面发射车和无人艇发射箱共用的可耗电子攻击弹，"
            "搭载诱饵航迹和电子攻击载荷"
        ),
        "function": "由岸海节点发射，诱启防空并扰乱防空资源分配",
        "military_value": "在主打击波次前实施电子压制",
    }

    assert provider_module._compact_capability_direction_title(
        offline_rocket_launcher
    ) == "断链复核远程精确打击火箭发射车"
    assert provider_module._compact_capability_direction_title(common_ea_munition) == (
        "陆海共架防空诱扰电子攻击弹"
    )

    normalized_launcher = {
        **offline_rocket_launcher,
        "name": provider_module._compact_capability_direction_title(
            offline_rocket_launcher
        ),
    }
    assert provider_module._direction_mixes_distinct_weapon_families(
        normalized_launcher
    ) == {"prsm"}


def test_s6_title_compactor_reconciles_r10_semisub_magazine_and_node_defense() -> None:
    semi_submersible_magazine = {
        "name": "低特征自主突击无人艇",
        "equipment_form": (
            "低活动半潜无人艇，内置密封远程弹药舱、简化火控终端和被动告警，"
            "按人工授权任务包执行发射或保持静默"
        ),
        "function": "分散海上待机并对固定保障节点和海空集结区实施小波次续射",
        "operational_mechanism": "接收低带宽摘要后短时发射，射后转移或沉默",
    }
    node_defense_interceptor = {
        "name": "低空可消耗察打一体无人机",
        "equipment_form": (
            "节点内置微型拦截弹发射单元，配套被动告警、小型近程火控"
            "和有限数量可消耗拦截弹"
        ),
        "function": "远火节点遭无人机和巡飞弹搜索时，以节点自卫火力实施近程拦截",
        "operational_mechanism": "发射节点告警后拦截低空威胁并转移",
    }

    assert provider_module._compact_capability_direction_title(
        semi_submersible_magazine
    ) == "半潜预置远程导弹火力舱"
    assert provider_module._compact_capability_direction_title(
        node_defense_interceptor
    ) == "节点自卫反无人机微型拦截弹"


def test_s6_normalizer_keeps_short_takeoff_fire_carrier_as_primary_platform() -> None:
    direction = {
        "name": "断链复核低成本巡航弹补击",
        "type": "new_capability",
        "equipment_form": (
            "短距起降低特征无人机体、模块化内外载架、诱饵与小型巡航/巡飞弹挂载、"
            "被动导航和人在回路任务监管组成"
        ),
        "function": "短距起降无人火力母机从简易跑道释放诱饵、小型巡航弹或巡飞弹",
        "target_scenario": "主跑道受毁但滑行道、道路或小型起降场仍可使用",
        "capability_gap": "有人载机和完整机场不可持续出动时空射诱骗与轻型打击同步中断",
        "scientific_principle": "利用短距起降、低特征航迹和模块化混载降低机场依赖",
        "enabling_technologies": ["短距起降", "模块化载架", "抗扰导航", "人在回路释放"],
        "operational_concept": "从简易场地出动并在授权释放区先投诱饵再释放小型打击弹药",
        "operational_process": ["简易场地起飞", "进入释放区", "释放诱饵和打击弹", "转场退出"],
        "capability_outcome": "形成跑道受损后的无人空中诱骗与轻型打击能力",
        "military_value": "维持空中释能并迟滞敌防空重组",
        "winning_mechanism": "把完整跑道和有人载机从必要条件降为可替代条件",
        "failure_boundary": "载荷过小、生存性不足或弱网授权失效时不能承担持续释能",
    }

    normalized = provider_module._normalize_s6_deterministic_format(
        {"concept_directions": [direction], "confidence": 0.75},
        topic="西太机场受毁与强电磁压制下跨岛链无人远程火力持续释能",
    )["concept_directions"][0]

    assert normalized["name"] == "短距起降低特征无人火力母机"
    assert "无人火力母机" in normalized["capability_portrait"]
    assert all(
        marker in normalized["capability_portrait"]
        for marker in ("简易场地", "释放区", "诱饵", "小型巡航", "人在回路", "转场")
    )
    assert "批次合格率" not in normalized["capability_portrait"]
    assert provider_module._capability_portrait_alignment_issues(1, normalized) == []


def test_s6_normalizer_keeps_island_loitering_launcher_distinct_from_its_payload() -> None:
    island_launcher = {
        "name": "多模复核反辐射巡飞猎歼弹",
        "type": "new_capability",
        "equipment_form": (
            "可伪装转运的栖岛弹舱，集成助推发射架、巡飞攻击弹、"
            "被动/光电复核载荷和任务边界装订终端"
        ),
        "function": "岛岸分散小队以短轨助推方式释放巡飞弹并完成局部搜索和补击",
        "target_scenario": "前沿机场受毁后的小岛分散火力接续",
        "capability_gap": "完整跑道不可用时缺少可转运的非跑道巡飞弹发射节点",
        "scientific_principle": "以栖岛预置和助推发射替代机场出动链",
        "enabling_technologies": ["助推短轨发射", "巡飞攻击弹", "任务边界装订"],
        "operational_concept": "弹舱进入小岛阵位后按人工授权分批释放巡飞弹",
        "operational_process": ["栖岛部署", "授权复核", "助推发射", "转移接替"],
        "capability_outcome": "形成非跑道岛岸巡飞火力接续能力",
        "military_value": "在机场失能后继续搜索和补击敌机动防空节点",
        "winning_mechanism": "迫使敌方持续搜索多个可转运岛岸弹舱",
        "failure_boundary": "弹舱暴露、授权失效或补给中断时停止释能",
    }
    anti_radiation_munition = {
        **island_launcher,
        "equipment_form": (
            "远程巡飞弹体，集成被动射频寻的、光电/红外复核、"
            "抗干扰导航和人在回路授权边界"
        ),
        "function": "搜索间歇开机雷达并实施受控压制毁伤",
        "operational_concept": "巡飞弹在目标区等待辐射源暴露并完成末端复核",
        "operational_process": ["进入待机区", "被动搜索", "光电复核", "攻击或拒打"],
    }

    normalized = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [island_launcher, anti_radiation_munition],
            "confidence": 0.74,
        },
        topic="西太机场受毁与强电磁压制下跨岛链无人远程火力持续释能",
    )["concept_directions"]

    assert [item["name"] for item in normalized] == [
        "栖岛助推巡飞弹发射舱",
        "多模复核反辐射巡飞猎歼弹",
    ]
    launcher_portrait = normalized[0]["capability_portrait"]
    assert "栖岛弹舱" in launcher_portrait
    assert all(
        marker in launcher_portrait
        for marker in ("栖岛", "弹舱", "巡飞弹", "授权", "接替")
    )
    assert "以长航时多模复核反辐射巡飞猎歼弹为主装备" not in launcher_portrait
    assert provider_module._capability_portrait_alignment_issues(1, normalized[0]) == []


def test_r10_expendable_mission_bridge_portrait_stays_a_target_update_node() -> None:
    direction = {
        "name": "可消耗空中任务桥巡航弹",
        "equipment_form": (
            "可消耗巡航弹式空中任务桥，搭载被动射频、简化成像或电子支援载荷、"
            "短窗低概率截获转发设备和安全终止模块"
        ),
        "function": "为岸海分散射手提供短时目标更新和火力转交",
        "target_scenario": "机场受毁、主数据链间歇且有人侦察平台不宜前出",
        "capability_gap": "分散射手缺少一次可用的低带宽目标摘要窗口",
        "scientific_principle": "以可消耗短时在位节点替代连续宽带目标更新",
        "enabling_technologies": ["被动射频", "简化成像", "低带宽摘要转发"],
        "operational_concept": "岸海节点释放后短时获取目标证据并转发授权射手",
        "capability_outcome": "恢复一次目标确认、火力转交和补射决策窗口",
        "military_value": "使远火射手在链路间歇时仍可合法补射",
        "winning_mechanism": "把高价值侦察平台持续在位需求转为可消耗短窗更新",
        "failure_boundary": "证据过期、身份冲突或转发失败时安全终止",
    }

    portrait = provider_module._build_direction_capability_portrait(
        direction,
        topic="西太机场受毁与强电磁压制下跨岛链远火持续释能",
    )

    overview = portrait.splitlines()[0]
    assert "可消耗巡航弹式空中任务桥" in overview
    assert "目标摘要" in overview
    assert "火力转交" in overview
    assert "不得自行攻击" in portrait
    assert "受控突防毁伤" not in overview


def test_s6_gate_recognizes_armed_unmanned_wingman_as_concrete_equipment() -> None:
    direction = {
        "name": "远域反辐射压制无人僚机",
        "equipment_form": "长航时低可探测武装无人僚机",
    }

    assert provider_module._direction_name_has_equipment_object(direction) is True


def test_s6_normalizer_keeps_missile_launch_usv_out_of_ramming_portrait() -> None:
    direction = {
        "name": "航路伏击自主突击无人艇",
        "type": "new_capability",
        "equipment_form": "半潜无人艇平台与模块化巡航弹舱",
        "function": "海上无人火力节点按授权释放巡航弹，补上机场受毁后的远火中断点。",
        "target_scenario": "西太岛链首轮后海上远火续接阶段",
        "capability_gap": "机场和固定阵地受毁后缺少隐蔽海上发射节点",
        "scientific_principle": "分布式海上预置与异步释能降低单点失效风险",
        "enabling_technologies": ["半潜艇体", "模块化巡航弹舱", "低截获授权"],
        "operational_concept": "危机期分散预置，冲突中按授权发射后转移或沉默",
        "operational_process": ["分散布放", "海上待机", "授权复核", "释放巡航弹", "转移补射"],
        "capability_outcome": "形成不依赖机场的海上远程火力释放能力",
        "military_value": "续接对敌纵深节点和海空编队的远程打击",
        "winning_mechanism": "迫使敌方扩大海上小目标搜剿范围",
        "operational_mechanism": "低特征待机，接令后释放巡航弹并转移",
        "failure_boundary": "弹舱状态或授权不可验证时拒绝发射",
        "capability_portrait": (
            "概述：面向海峡伏击，针对目标通过，以无人艇为主装备，利用航路约束，采用近距识别，"
            "通过直接撞击，形成近距拦截能力，实现清剿伏击区作战效果。"
        ),
    }

    normalized = provider_module._normalize_s6_deterministic_format(
        {"concept_directions": [direction], "confidence": 0.7},
        topic="西太机场受毁后跨岛链无人远程火力持续释能",
    )["concept_directions"][0]

    assert normalized["name"] == "半潜预置远程导弹火力舱"
    assert "释放巡航弹" in normalized["capability_portrait"]
    assert "直接撞击" not in normalized["capability_portrait"]


def test_s6_normalizer_keeps_lost_link_cruise_missile_out_of_loitering_flow() -> None:
    direction = {
        "name": "失联复核远程巡航弹",
        "type": "upgrade",
        "equipment_form": "远程低可探测巡航弹与失联等待/拒打任务软件",
        "baseline_system": "JASSM/JASSM-ER类防区外巡航弹",
        "function": "载机或远程无人发射平台释放后，在链路中断时复核纵深节点并受控毁伤。",
        "target_scenario": "西太机场受毁和强电磁压制后的纵深补击阶段",
        "capability_gap": "GNSS受扰和目标包过期时可能误击或空耗",
        "scientific_principle": "导航可信评估与末段独立身份证据约束毁伤释放",
        "enabling_technologies": ["组合导航", "目标包时效管理", "末段成像复核"],
        "operational_concept": "防区外释放后按任务包飞行，末段复核、毁伤或拒打",
        "operational_process": ["防区外释放", "组合导航", "时效判断", "末段复核", "毁伤或拒打"],
        "capability_outcome": "形成失联条件下的受控纵深毁伤和补击能力",
        "military_value": "摧毁敌纵深指挥、保障和远程火力节点",
        "winning_mechanism": "压缩目标依靠链路压制与快速修复获得的生存窗口",
        "operational_mechanism": "链路中断后判断目标包时效，末段复核后毁伤或拒打",
        "failure_boundary": "目标身份无法确认时拒打",
        "capability_portrait": (
            "概述：面向目标邻近空域持续作战，针对首击漏毁，以巡航弹为主装备，利用在位察打，"
            "采用箱式分批释放，通过巡飞待机补射，形成连续察打能力，实现补击作战效果。"
        ),
    }

    normalized = provider_module._normalize_s6_deterministic_format(
        {"concept_directions": [direction], "confidence": 0.72},
        topic="西太机场受毁和强电磁压制下跨岛链远程火力",
    )["concept_directions"][0]

    portrait = normalized["capability_portrait"]
    assert "防区外释放" in portrait
    assert "目标包" in portrait
    assert "时效" in portrait or "过期" in portrait
    assert "箱式分批释放" not in portrait
    assert "在位察打" not in portrait


def test_report_portrait_prefers_structured_problem_over_legacy_gap_bundle() -> None:
    item = {
        "direction": "诱扰开窗可消耗无人弹",
        "target_scenario": "主攻弹药进入敌一体化防空区前的突防开窗阶段",
        "problem_statement": "敌防空雷达与拦截资源压缩主攻弹药突防窗口",
        "capability_gap": (
            "概述：面向旧场景，针对旧问题，以可消耗喷气无人弹为主装备，"
            "利用旧机理，采用旧技术，通过旧流程形成旧能力"
        ),
        "scientific_principle": "以可消耗特征模拟和伴随干扰诱导敌火控资源错配",
        "enabling_technologies": ["可编程特征模拟", "伴随干扰载荷"],
        "operational_concept": "多轴释放、诱导雷达响应、受控干扰和窗口通报",
        "operational_process": ["威胁库装订", "多轴释放", "诱导雷达响应", "窗口通报"],
        "capability_outcome": "可消耗诱骗和压制开窗",
        "mission_effect": "为主攻巡航弹创造突防窗口",
        "winning_mechanism": "以低成本无人弹换取敌高价值拦截与辐射暴露",
        "equipment_hint": "可消耗喷气无人弹，配可编程特征模拟和伴随干扰载荷",
        "public_equipment_baseline": "MALD类公开可消耗诱饵基线",
        "boundary": "失效边界：敌方不响应诱扰时只能作为消耗诱饵",
    }

    portrait = provider_module._report_capability_portrait_markdown(item)

    overview = portrait.split("\n", 1)[0]
    assert "针对敌防空雷达与拦截资源压缩主攻弹药突防窗口" in overview
    assert "以可消耗喷气无人弹，以可消耗喷气无人弹" not in overview
    assert "针对旧问题" not in overview


def test_s6_quality_gate_rejects_duplicate_visible_equipment_titles() -> None:
    base = {
        "name": "低信息侦打巡飞弹",
        "type": "new_capability",
        "equipment_form": "车载巡飞弹",
        "function": "前沿目标发现与打击",
        "military_value": "形成目标发现、打击与毁伤效果",
        "operational_mechanism": "侦察后进入交战并实施打击",
        "combat_effect_uplift": "提升毁伤效果",
        "strike_chain_contribution": "强化目标发现与再打击",
        "development_path": "样机验证后集成",
        "future_trigger": "强干扰成为常态",
        "adversary_adaptation": "对手增加诱饵",
        "failure_boundary": "识别失败时中止",
        "query_relevance": "强干扰、弱通信条件下在交战阶段应对压制并实施打击毁伤",
        "baseline_system": "现役巡飞弹",
        "capability_gap": "弱通信目标确认不足",
        "capability_portrait": "作战画像。" * 80,
    }
    directions = [dict(base) for _ in range(5)]
    directions[0]["type"] = "upgrade"
    directions[0]["upgrade_package"] = ["任务计算", "制导组件"]
    directions[0]["upgrade_boundary"] = "弹体余量不足时转新研"

    issues = _capability_direction_quality_issues(
        {"concept_directions": directions},
        handoff={"query": "强干扰、弱通信条件下低信息依赖精确打击研究"},
    )

    assert any("名称必须互异" in issue for issue in issues)


def test_s6_first_pass_contract_frontloads_query_specific_weapon_preflight() -> None:
    contract = _s6_first_pass_quality_contract(
        topic="评估海上区域拒止体系在强干扰与饱和突防条件下的装备能力差距",
        handoff={
            "equipment_portfolio_preflight": [
                {
                    "category": "combat_equipment_upgrade",
                    "ready": True,
                    "candidate_equipment": "现役MADIS/L-MADIS低空拦截升级",
                    "baseline_system": "现役MADIS/L-MADIS反无人任务系统",
                    "capability_gap": "多批次低空目标持续拦截能力不足",
                    "query_relevance": "前沿节点防护阶段应对低成本无人饱和压力",
                    "evidence_refs": ["ev-0"],
                },
                {
                    "category": "missile_precision_munition",
                    "ready": True,
                    "candidate_equipment": "远程反舰导弹",
                    "baseline_system": "现役岸舰导弹",
                    "capability_gap": "强干扰下连续突防和毁伤能力不足",
                    "query_relevance": "海上区域拒止交战阶段面临强干扰和饱和突防压力，需要连续反舰毁伤",
                    "evidence_refs": ["ev-1"],
                },
                {
                    "category": "unmanned_combat_platform",
                    "ready": True,
                    "candidate_equipment": "远域察打一体无人机",
                    "baseline_system": "现役侦察无人机",
                    "capability_gap": "弱网下持续目标猎获能力不足",
                    "query_relevance": "强干扰条件下侦察阶段需要无人平台持续发现并引导火力",
                    "evidence_refs": ["ev-2"],
                },
            ]
        },
    )

    assert contract["goal"] == "first_pass_acceptance_without_gate_retry"
    assert "海上" in contract["query_anchors"]
    assert "区域拒止" in contract["query_anchors"]
    preflight = contract["query_specific_preflight_directions"]
    assert len(preflight) == 3
    assert all(item["ready"] is True for item in preflight)
    assert "回收" in contract["portfolio"]["support_mission_exclusion"]
    assert "首次自检" in contract["portfolio"]["support_mission_exclusion"]
    assert any("MADIS/L-MADIS" in item["candidate_equipment"] for item in preflight)
    assert (
        contract["portfolio"]["missile_and_unmanned_must_be_separate_cards"]
        == "only_when_both_are_query_aligned_and_selected"
    )
    assert "固定数量" in contract["portfolio"]["direct_weapon_portfolio_rule"]
    assert contract["disruptive_dimension_use"]["internal_query_causal_lenses"] == "2..3"
    assert (
        "不作为固定数量后置阻断门"
        in contract["disruptive_dimension_use"]["relationship_diversity_policy"]
    )
    submission_contract = " ".join(contract["per_card_submission_check"])
    assert "primary_equipment_identity" in submission_contract
    assert "semantic_consistency_check" in submission_contract
    assert "不得由本地关键词模板代写流程" in submission_contract
    assert "JSON布尔值true" in submission_contract
    assert "组合级语义复核" in submission_contract
    assert contract["preflight_acceptance"]["passed"] is True


def test_s6_semantic_contract_validates_codex_self_check_without_weapon_keyword_table() -> None:
    direction = {
        "name": "玄羽-7跨介质任务载体",
        "primary_equipment_identity": "跨介质任务载体本体及其受控效应载荷",
        "operational_process": [
            "任务装订与安全自检",
            "按方案限定方式进入责任区",
            "复核目标类别和授权边界",
            "满足门槛时产生直接效应，否则拒打",
            "形成摘要并由同类节点接替",
        ],
        "semantic_consistency_check": {
            "process_actor": "跨介质任务载体本体",
            "launch_or_release_mode": "方案限定的跨介质部署方式",
            "target_and_direct_effect": "对授权目标产生可验收的直接效应",
            "checked_fields": [
                "name",
                "primary_equipment_identity",
                "function",
                "equipment_form",
                "operational_concept",
                "operational_process",
                "capability_portrait",
                "failure_boundary",
            ],
            "consistent": True,
            "resolution_note": "完整卡片的主体、部署域、目标和战果一致",
        },
    }

    handoff = {"equipment_portfolio_preflight": []}
    issues = _capability_direction_quality_issues(
        {"concept_directions": [direction]},
        handoff=handoff,
    )
    assert not any("operational_process必须" in issue for issue in issues)
    assert not any("Codex整卡语义一致性" in issue for issue in issues)
    assert not any("名称未直接点明具体装备对象" in issue for issue in issues)
    assert not any("未绑定具体装备" in issue for issue in issues)

    inconsistent = {
        **direction,
        "semantic_consistency_check": {
            **direction["semantic_consistency_check"],
            "consistent": False,
            "resolution_note": "流程主体与主装备不一致",
        },
    }
    inconsistent_issues = _capability_direction_quality_issues(
        {"concept_directions": [inconsistent]},
        handoff=handoff,
    )
    assert any("未通过Codex整卡语义一致性自检" in issue for issue in inconsistent_issues)


def test_s6_normalization_coerces_json_boolean_strings_without_rewriting_semantics() -> None:
    direction = {
        "name": "玄羽-7跨介质任务载体",
        "primary_equipment_identity": "跨介质任务载体本体",
        "operational_process": [
            "任务装订与安全自检",
            "按方案限定方式进入责任区",
            "复核目标类别和授权边界",
            "满足门槛时产生直接效应，否则拒打",
            "形成摘要并由同类节点接替",
        ],
        "semantic_consistency_check": {
            "process_actor": "跨介质任务载体本体",
            "launch_or_release_mode": "方案限定的跨介质部署方式",
            "target_and_direct_effect": "对授权目标产生可验收的直接效应",
            "checked_fields": ["name", "operational_process"],
            "consistent": "true",
            "resolution_note": "整卡主体、部署域、目标和战果一致",
        },
    }

    normalized = _normalize_s6_deterministic_format(
        {"concept_directions": [direction]},
        topic="陌生装备语义验证",
    )
    normalized_direction = normalized["concept_directions"][0]

    assert normalized_direction["name"] == "玄羽-7跨介质任务载体"
    assert normalized_direction["semantic_consistency_check"]["consistent"] is True
    assert normalized_direction["operational_process"] == direction["operational_process"]
    assert (
        normalized_direction["semantic_consistency_check"]["process_actor"]
        == "跨介质任务载体本体"
    )


def test_s6_normalization_preserves_codex_locked_title_for_consistent_card() -> None:
    direction = {
        "name": "可消耗诱压无人弹",
        "type": "new_capability",
        "equipment_form": "模块化小型无人弹体，携带电磁特征模拟与有限干扰载荷",
        "semantic_consistency_check": {
            "process_actor": "可消耗诱压无人弹",
            "launch_or_release_mode": "岛岸发射架或无人水面平台释放",
            "target_and_direct_effect": "诱导敌防空传感与火控节点暴露",
            "checked_fields": ["name", "equipment_form", "operational_process"],
            "consistent": True,
            "resolution_note": "主装备、释放域、目标和直接战果一致",
        },
    }

    normalized = _normalize_s6_deterministic_format(
        {"concept_directions": [direction]},
        topic="强电磁压制下无人远火持续释能",
    )

    assert normalized["concept_directions"][0]["name"] == "可消耗诱压无人弹"
    assert normalized["concept_directions"][0]["equipment_form"] == direction["equipment_form"]


def test_s6_disruptive_relationship_diversity_is_pre_generation_guidance_not_hard_gate() -> None:
    names = [
        ("现役防空导弹抗饱和拦截升级", "upgrade"),
        ("远域无人机目标猎歼系统", "new_capability"),
        ("远程反舰导弹连续打击系统", "new_capability"),
        ("低空微波反无人拦截器", "new_capability"),
        ("无人潜航器鱼雷伏击系统", "new_capability"),
    ]
    portrait = (
        "该装备面向海上区域拒止交战阶段，针对高强度对抗中的目标发现、火力分配、突防、"
        "拦截和毁伤任务形成可独立立项的武器装备。相对现役基线，装备通过任务载荷、火控软件、"
        "抗干扰制导和机动发射完成目标闭环，并用红蓝对抗、半实物和实装试验考核任务完成率、"
        "有效交战率和失效边界。对手采用诱饵、干扰和机动规避时，装备需要保持任务对象识别和"
        "直接作战效果；若目标质量、制导精度或平台余量不足，则降低优先级并转入新研。"
    )

    def direction(index: int, name: str, capability_type: str) -> dict:
        row = {
            "name": name,
            "type": capability_type,
            "function": "在交战阶段完成目标打击、拦截或毁伤",
            "equipment_form": name,
            "operational_mechanism": "在交战阶段闭合目标发现、火力分配、突防和毁伤链",
            "military_value": "提高区域拒止和直接毁伤任务完成率",
            "combat_effect_uplift": "提升有效交战和毁伤闭合能力",
            "strike_chain_contribution": "缩短发现到火力打击闭环",
            "development_path": "近期改装验证，中期形成样机并开展对抗试验",
            "future_trigger": "对手饱和突防和机动规避压力增加",
            "adversary_adaptation": "对手采用诱饵、干扰和机动规避",
            "failure_boundary": "目标质量或制导精度不足时降级",
            "query_relevance": "面向西太区域拒止交战阶段的饱和突防压力，直接提高打击、拦截和毁伤效果",
            "baseline_system": f"现役同类装备基线{index}",
            "capability_gap": f"现役装备在高强度交战中的任务闭合差距{index}",
            "capability_portrait": (portrait * 2)[:500],
            "novelty": "相对现役基线形成装备任务机制增量",
        }
        if capability_type == "upgrade":
            row.update(
                {
                    "upgrade_package": ["火控软件", "任务载荷"],
                    "upgrade_boundary": "平台余量不足时转入新研",
                }
            )
        return row

    shallow = {
        "concept_directions": [
            direction(index, name, capability_type)
            for index, (name, capability_type) in enumerate(names, start=1)
        ]
    }
    shallow_issues = _capability_direction_quality_issues(shallow)
    assert not any("至少需要3类与query因果相关" in issue for issue in shallow_issues)

    rich = {"concept_directions": [dict(item) for item in shallow["concept_directions"]]}
    rich["concept_directions"][0]["novelty"] = "以低成本规模消耗反转成本交换"
    rich["concept_directions"][1]["novelty"] = "以长航时持续存在的平台重构发射关系"
    rich["concept_directions"][2]["novelty"] = "以毁伤评估和再打击压缩决策周期"
    rich_issues = _capability_direction_quality_issues(rich)
    assert not any("至少需要3类与query因果相关" in issue for issue in rich_issues)


def test_s6_quality_gate_rejects_camouflage_as_a_weapon_portfolio_slot() -> None:
    direction = {
        "name": "机动伪装诱饵阵地系统",
        "type": "new_capability",
        "function": "构设多谱段假目标并评估诱饵效果",
        "equipment_form": "机动伪装车、热源假目标和效果评估终端",
        "operational_mechanism": "在战役准备阶段压低对手目标识别和火力分配效率",
        "military_value": "诱导对手消耗侦察与打击资源",
        "strike_countermeasure_value": "形成诱骗与反侦察效果",
        "development_path": "近期样机研制与对抗验证",
        "future_trigger": "多谱段侦察威胁增加",
        "adversary_adaptation": "对手采用多源交叉识别",
        "failure_boundary": "假目标特征不一致时失效",
        "query_relevance": "面向远程精确火力对抗准备阶段的多谱段侦察压力，降低对手打击效率",
        "baseline_system": "现役伪装器材",
        "capability_gap": "快速构设和效果评估不足",
        "capability_portrait": ("该装备用于战役准备阶段构设多谱段假目标并消耗对手侦察资源。" * 20)[:360] + "。",
    }

    issues = _capability_direction_quality_issues(
        {"concept_directions": [direction] * 5},
        handoff={"query": "远程无人精确火力装备需求研究"},
    )

    assert any("不得把伪装、假目标" in issue for issue in issues)


def test_s6_first_pass_contract_exposes_missing_preflight_before_generation() -> None:
    contract = _s6_first_pass_quality_contract(
        topic="从近年局部战争中挖掘装备发展需求",
        handoff={"equipment_portfolio_preflight": []},
    )

    assert contract["preflight_acceptance"]["passed"] is False
    issues = contract["preflight_acceptance"]["issues_to_resolve_before_submission"]
    assert any("尚未形成任何与query直接对应" in issue for issue in issues)


def test_s4_normalizes_one_based_terminal_effect_chain_reference() -> None:
    repaired = _normalize_effect_chain_references(
        {
            "derived_from": ["effect_chain[6]", "effect_chain[2]"],
            "nested": {"reference": "由effect_chain[6]推导"},
        },
        6,
    )

    assert repaired["derived_from"] == ["effect_chain[5]", "effect_chain[2]"]
    assert repaired["nested"]["reference"] == "由effect_chain[5]推导"


def test_s6_normalizes_lettered_effect_chain_references() -> None:
    repaired = _normalize_effect_chain_references(
        {"derived_from": ["effect_chain:B", "effect_chain:链条F"]},
        6,
    )

    assert repaired["derived_from"] == ["effect_chain[1]", "effect_chain[5]"]


def test_s6_normalizes_final_priorities_and_stale_advisory_references() -> None:
    result = _normalize_concept_direction_priorities(
        {
            "concept_directions": [
                {"name": "a", "priority": "P1"},
                {"name": "b", "priority": "P3"},
                {"name": "c", "priority": "P3"},
            ]
        }
    )
    nodes = _normalize_priority_references(
        {"5": {"next_action": {"reason": "优先P1、P3、P6"}}},
        3,
    )

    assert [row["priority"] for row in result["concept_directions"]] == [
        "P1",
        "P2",
        "P3",
    ]
    assert nodes["5"]["next_action"]["reason"] == "优先P1、P3、P3"
    assert not _has_combat_effect_signal(
        {
            "combat_effect_uplift": "提高接口兼容性",
            "strike_countermeasure_value": "",
            "operational_mechanism": "",
            "capability_portrait": "",
        }
    )


def test_s6_retry_uses_scoped_weapon_repair_instead_of_full_regeneration() -> None:
    backend = _RealLikeScriptedProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    phases: list[str] = []

    def direction(
        name: str,
        portrait: str,
        *,
        confidence: float = 0.8,
    ) -> dict:
        capability_type = "upgrade" if "现役" in name else "new_capability"
        row = {
            "name": name,
            "priority": "P1",
            "type": capability_type,
            "function": "保持任务链",
            "feasibility": "3",
            "horizon": "mid",
            "direct_evidence_refs": [],
            "derived_from": ["packet-1"],
            "verification": "验证任务闭环时间",
            "military_value": "维持作战任务闭环",
            "depth_mechanism": "通过冗余改变失效传播",
            "foresight": "面向未来链路受压场景",
            "novelty": "从链路增强转向任务级韧性",
            "strike_countermeasure_value": "支撑防御性反制",
                "equipment_form": (
                    "现役预警机任务系统与抗扰数据链改装包"
                    if capability_type == "upgrade"
                    else f"{name}任务平台系统"
                ),
                "primary_equipment_identity": f"{name}及其任务载荷边界",
                "operational_mechanism": "维持侦察、指挥与火力打击协同",
                "operational_process": [
                    "任务装订与安全自检",
                    "按方案限定方式部署或进入责任区",
                    "搜索告警并复核目标与授权条件",
                    "满足门槛时交战，否则拒打或退出",
                    "形成效果摘要并组织补射或接替",
                ],
                "semantic_consistency_check": {
                    "process_actor": name,
                    "launch_or_release_mode": "由方案装备形态限定，未限定时保持平台中性",
                    "target_and_direct_effect": "对指定目标形成直接打击、毁伤、压制或拦截效果",
                    "checked_fields": [
                        "name",
                        "primary_equipment_identity",
                        "function",
                        "equipment_form",
                        "operational_concept",
                        "operational_process",
                        "capability_portrait",
                        "failure_boundary",
                    ],
                    "consistent": True,
                    "resolution_note": "整卡主装备、流程主体、发射域和直接战果一致",
                },
            "development_path": "近期升级—中期集成—验证闸门",
            "future_trigger": "未来强电磁压制与低成本饱和手段常态化",
            "adversary_adaptation": "对手转向诱饵、多点压制和节点毁伤",
            "failure_boundary": "平台能源、接口或时延无法维持任务闭环时失效",
            "query_relevance": "对应当前query中的强干扰任务阶段、目标识别压力和火力打击续接需求",
            "baseline_system": f"现役或类比{name}装备基线",
            "capability_gap": f"{name}在强干扰条件下缺少独立的目标猎获、火力协同与毁伤闭合能力",
            "capability_portrait": portrait,
            "confidence": confidence,
        }
        if capability_type == "upgrade":
            row.update(
                {
                    "baseline_system": "现役预警机任务计算机、雷达和数据链系统",
                    "upgrade_package": ["抗扰多链路终端", "火力协同任务计算模块"],
                    "combat_effect_uplift": "主链路受压后维持目标识别和火力打击续接",
                    "strike_chain_contribution": "缩短侦察识别到火力分配与打击评估闭环",
                    "upgrade_boundary": "平台余量不足时转入分布式预警节点新研",
                }
            )
        return row

    def valid_portrait(subject: str, mechanism: str) -> str:
        equipment, problem, concept, capability, effect = next(
            values
            for marker, values in (
                (
                    "预警机",
                    (
                        "现役空中预警机雷达与火控任务系统",
                        "敌方远程防空雷达和干扰机压制空情链，预警机被迫在岛链外缘后撤",
                        "预警机编队完成目标航迹复核和远程反舰火力引导",
                        "维持目标识别、火力分配与毁伤评估",
                        "续接反舰导弹补击并阻断敌舰编队重组",
                    ),
                ),
                (
                    "无人机",
                    (
                        "远域察打一体无人机",
                        "敌方舰艇编队施放诱饵并压制前沿链路，海上目标短时机动暴露",
                        "无人机分队前出搜索、复核目标并授权受控交战",
                        "分布式目标猎获与近距补击",
                        "摧毁漏毁舰艇并续接后续火力",
                    ),
                ),
                (
                    "反舰导弹",
                    (
                        "远程反舰导弹",
                        "敌方航母编队机动规避并实施GNSS欺骗和末段电子对抗",
                        "舰艇火力单元齐射后由导弹自主进入目标区搜索复核",
                        "断链条件下海上机动目标再捕获",
                        "毁伤敌舰并阻断编队重组",
                    ),
                ),
                (
                    "巡飞弹",
                    (
                        "长航时反舰巡飞弹药",
                        "敌方两栖编队在岛链海域分散机动并以防空火力压缩补击窗口",
                        "岸基发射单元投放巡飞弹群进入目标区待机复核并受控交战",
                        "持续搜索压制与多波次补射",
                        "压制护航舰并摧毁漏毁目标",
                    ),
                ),
                (
                    "反无人",
                    (
                        "低成本反无人拦截弹",
                        "敌方无人集群低空突入我方前沿阵地并以诱饵消耗防空库存",
                        "防空分队发射拦截弹分层搜索复核并连续交战",
                        "低空饱和目标分层拦截",
                        "歼灭无人集群并保护远程火力阵地",
                    ),
                ),
            )
            if marker in subject
        )
        return build_capability_portrait(
            scenario=f"岛链外缘联合海空战役首轮火力受压阶段，{problem}",
            problem=problem,
            principle=mechanism,
            technologies=[mechanism, "目标识别与抗扰导航", "火控任务管理"],
            operational_concept=concept,
            operational_steps=[
                "由我方发射平台完成任务装订并发射/部署",
                "进入目标海域后搜索并复核敌方目标",
                "满足授权门槛则交战，证据不足则拒打",
                "完成毁伤评估并组织补射或接替",
            ],
            capability=capability,
            effect=effect,
            winning_mechanism=mechanism,
            equipment_form=equipment,
            baseline=f"现役或类比{subject}装备基线",
            development_path="近期样机—中期体系集成—远期实战化列装",
            failure_boundary=[
                "敌方诱饵和多点压制使身份复核低于门槛时拒打",
                "能源、库存或载荷余量不足时退出交战",
            ],
            verification_plan=(
                "在强电磁压制、GNSS拒止、诱饵注入和节点毁伤条件下对照验证任务闭环时间、"
                "正确交战率、正确拒打率、毁伤率和补射接替成功率。"
            ),
        )

    def maritime_denial_portrait() -> str:
        return (
            "海上无人艇电子压制与目标拒止系统面向岛链外缘封控和分布式海上目标拒止阶段，"
            "以低可探测无人艇搭载电子侦察、定向压制和诱饵载荷，在有人舰艇进入高风险区域前"
            "完成辐射源定位、通信压制和目标暴露塑形。其军事价值不在维持一般链路，而在迫使"
            "对手雷达、数据链和火控节点改变工作方式，为反舰导弹和远程火力创造目标指示、突防"
            "与再打击窗口，并通过多艇分散部署提高拒止持续性。未来对手可能采用静默、跳频、诱饵"
            "和无人反制平台实施猎杀，因此系统需具备任务自治重组、载荷快速切换和失联条件下的"
            "安全撤离逻辑。若海况限制、能源余量、频谱识别精度或远程火力协同无法达到任务门槛，"
            "该方向不应优先部署。验证应采用强干扰海况试验，观察辐射源定位连续率、压制后目标"
            "暴露时间、火力任务接续率和无人艇战损后的任务保持度，并据此决定平台规模与载荷组合。"
        )

    def repair_target_direction(name: str, portrait: str) -> dict:
        row = direction(name, portrait)
        row.pop("query_relevance")
        return row

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, output_schema, max_output_tokens
        phases.append(phase)
        if agent_id == "winning_step_critic":
            issues = payload.get("deterministic_quality_issues", [])
            return json.dumps(
                {
                    "passed": not issues,
                    "issues": issues,
                    "retry_guidance": issues,
                    "recommended_action": "retry" if issues else "pass",
                },
                ensure_ascii=False,
            )
        if agent_id == "winning_round_critic":
            return '{"passed":true,"rerun_from_step":0,"issues":[]}'
        if agent_id == "winning_s3_breakthrough":
            result = {"effect_chain": ["e"], "confidence": 0.8}
        elif agent_id == "winning_s4_capability":
            result = {"capability_mapping": ["m"], "confidence": 0.8}
        elif phase == "winning_s6_card_repair":
            repaired = [
                direction(
                    "现役预警机受扰火力打击续接升级",
                    valid_portrait("现役预警机升级", "抗扰多链路与火力协同重构"),
                    confidence=0.82,
                ),
                direction(
                    "分布式远域目标猎歼无人机系统",
                    valid_portrait("远域无人机系统", "多源跟踪与分布式效应协同"),
                    confidence=0.79,
                ),
                direction(
                    "远程反舰导弹抗扰目标指示与连续打击系统",
                    valid_portrait(
                        "远程反舰导弹系统",
                        "抗欺骗目标指示、分布式发射与毁伤评估回灌",
                    ),
                    confidence=0.77,
                ),
                direction(
                    "长航时巡飞弹蜂群搜索压制毁伤系统",
                    valid_portrait(
                        "巡飞弹蜂群系统",
                        "长航时待机、多目标分配与搜索压制毁伤协同",
                    ),
                    confidence=0.75,
                ),
                direction(
                    "低空反无人分层拦截弹猎歼系统",
                    valid_portrait(
                        "反无人拦截系统",
                        "多源低空探测、成本感知火力分配与连续拦截",
                    ),
                    confidence=0.73,
                ),
            ]
            return json.dumps(
                {
                    "direction_repairs": [
                        {
                            "position": item["position"],
                            "direction": repaired[item["position"] - 1],
                        }
                        for item in payload["repair_targets"]
                    ],
                },
                ensure_ascii=False,
            )
        else:
            result = {
                "concept_directions": [
                    repair_target_direction(
                        "现役预警机受扰火力打击续接升级",
                        valid_portrait(
                            "现役预警机升级",
                            "抗扰多链路与火力协同重构",
                        ),
                    ),
                    repair_target_direction(
                        "分布式远域目标猎歼无人机系统",
                        valid_portrait(
                            "远域无人机系统",
                            "多源跟踪与分布式效应协同",
                        ),
                    ),
                    repair_target_direction(
                        "远程反舰导弹抗扰目标指示与连续打击系统",
                        valid_portrait(
                            "远程反舰导弹系统",
                            "抗欺骗目标指示、分布式发射与毁伤评估回灌",
                        ),
                    ),
                    direction(
                        "长航时巡飞弹蜂群搜索压制毁伤系统",
                        valid_portrait(
                            "巡飞弹蜂群系统",
                            "长航时待机、多目标分配与搜索压制毁伤协同",
                        ),
                        confidence=0.75,
                    ),
                    direction(
                        "低空反无人分层拦截弹猎歼系统",
                        valid_portrait(
                            "反无人拦截系统",
                            "多源低空探测、成本感知火力分配与连续拦截",
                        ),
                        confidence=0.73,
                    ),
                ],
                "capability_image_drafts": ["d1", "d2", "d3", "d4", "d5"],
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
            }
        result["reasoning_node"] = {
            "recognition": agent_id,
            "evidence_refs": ["packet-1"],
            "confidence": 0.8,
            "next_action": {"action": "continue", "target_step": 0, "reason": "done"},
        }
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "test",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {"primary_branch": "G"},
                "packets": [{"packet_id": "packet-1"}],
                "evidence_index": [],
            }
        )
    )

    assert phases.count("winning_s6_image_deep") == 1
    assert phases.count("winning_s6_card_repair") == 1
    assert "winning_s6_combat_value_rewrite" not in phases
    assert len(result["concept_directions"]) == 5
    assert result["subagent_runs"][-1]["critic_issues"] == []


def test_s6_substantive_card_defect_uses_low_repair_without_rerunning_upstream(
    monkeypatch,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    calls: list[tuple[str, str, dict]] = []
    quality_checks = 0

    def fake_quality_gate(result, *, handoff=None):
        del result, handoff
        nonlocal quality_checks
        quality_checks += 1
        if quality_checks == 1:
            return [
                "S6第1项未说明具体作战阶段、任务对象及打击/反制效果"
            ]
        return []

    monkeypatch.setattr(
        provider_module,
        "_capability_direction_quality_issues",
        fake_quality_gate,
    )

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, max_output_tokens
        calls.append((agent_id, phase, dict(payload)))
        if agent_id == "winning_round_critic":
            return '{"passed":true,"rerun_from_step":0,"issues":[]}'
        result = {key: [] for key in output_schema}
        if "confidence" in output_schema:
            result["confidence"] = 0.8
        if agent_id == "winning_s6_image":
            result["confidence"] = 0.8
        if "concept_directions" in output_schema:
            result["concept_directions"] = [
                {"name": f"方向{index}", "type": "new_capability"}
                for index in range(1, 4)
            ]
        if "evidence_validation" in output_schema:
            result["evidence_validation"] = {
                "all_ids_valid": True,
                "invalid_ids": [],
                "mismatched_claims": [],
            }
        result["reasoning_node"] = _minimal_reasoning_node(
            6 if agent_id == "winning_s6_image" else int(agent_id.split("_s", 1)[1][0])
        )
        result["reasoning_node"]["evidence_refs"] = ["packet-1"]
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "台海岛链低轨韧性条件下适应研究",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {"primary_branch": "G"},
                "packets": [{"packet_id": "packet-1"}],
                "evidence_index": [],
            }
        )
    )

    phases = [phase for _, phase, _ in calls]
    assert phases.count("winning_s6_image_deep") == 1
    assert phases.count("winning_s6_card_repair") == 1
    assert "winning_s6_combat_value_rewrite" not in phases
    assert phases.count("winning_s4_capability_deep") == 1


def test_s6_transient_transport_failure_raises_without_fallback_portrait(
    monkeypatch,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        provider_module,
        "_capability_direction_quality_issues",
        lambda result, *, handoff=None: [],
    )

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, payload, max_output_tokens
        calls.append((agent_id, phase))
        if agent_id == "winning_s6_image" and phase == "winning_s6_image_deep":
            raise ProviderRequestError(
                "stream disconnected before completion: error decoding response body"
            )
        if phase == "winning_s6_card_repair":
            return '{"direction_repairs":[]}'
        if agent_id == "winning_round_critic":
            return '{"passed":true,"rerun_from_step":0,"issues":[]}'
        result = {key: [] for key in output_schema}
        if "confidence" in output_schema:
            result["confidence"] = 0.8
        if "evidence_validation" in output_schema:
            result["evidence_validation"] = {
                "all_ids_valid": True,
                "invalid_ids": [],
                "mismatched_claims": [],
            }
        result["reasoning_node"] = _minimal_reasoning_node(
            int(agent_id.split("_s", 1)[1][0])
        )
        result["reasoning_node"]["evidence_refs"] = ["packet-1"]
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    with pytest.raises(ProviderRequestError):
        asyncio.run(
            provider._analyze_winning_subagents(
                {
                    "topic": "强电磁压制下精确打击任务续接装备研究",
                    "research_route": "new_winning_mechanism",
                    "discovery_blueprint": {"primary_branch": "G"},
                    "packets": [{"packet_id": "packet-1"}],
                    "evidence_index": [
                        {
                            "evidence_id": "ev-1",
                            "claim": "公开资料支持强干扰条件下的装备差距研判",
                        }
                    ],
                }
            )
        )

    assert calls.count(("winning_s6_image", "winning_s6_image_deep")) == 1


def test_s6_persistent_quality_failure_stops_without_fallback(
    monkeypatch,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    calls: list[tuple[str, str]] = []
    round_reviews = 0

    monkeypatch.setattr(
        provider_module,
        "_capability_direction_quality_issues",
        lambda result, *, handoff=None: [
            "S6具名装备方向必须引用与自身型号或装备族直接匹配的对象证据，"
            "禁止用通用场景材料或其他型号来源代替；涉及位置1"
        ],
    )

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, max_output_tokens
        nonlocal round_reviews
        calls.append((agent_id, phase))
        if agent_id == "winning_round_critic":
            round_reviews += 1
            if round_reviews == 1:
                return json.dumps(
                    {
                        "passed": False,
                        "rerun_from_step": 6,
                        "rerun_steps": [6],
                        "affected_fields": ["capability_images"],
                        "issues": ["S6导弹方向仍不合格"],
                        "rerun_guidance": ["仅复核S6问题卡"],
                    },
                    ensure_ascii=False,
                )
            return '{"passed":true,"issues":[]}'
        if phase == "winning_s6_card_repair":
            return json.dumps(
                {
                    "direction_repairs": [
                        {
                            "position": item["position"],
                            "direction": item["direction"],
                        }
                        for item in payload["repair_targets"]
                    ]
                },
                ensure_ascii=False,
            )

        result = {key: [] for key in output_schema}
        if "confidence" in output_schema:
            result["confidence"] = 0.8
        if "concept_directions" in output_schema:
            result["concept_directions"] = [
                {"name": f"方向{index}", "type": "new_capability"}
                for index in range(1, 4)
            ]
        if "evidence_validation" in output_schema:
            result["evidence_validation"] = {
                "all_ids_valid": True,
                "invalid_ids": [],
                "mismatched_claims": [],
            }
        if "reasoning_node" in output_schema:
            step = 6 if agent_id == "winning_s6_image" else int(
                agent_id.split("_s", 1)[1][0]
            )
            result["reasoning_node"] = _minimal_reasoning_node(step)
            result["reasoning_node"]["evidence_refs"] = ["packet-1"]
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    with pytest.raises(S6QualityError, match="未生成限时保底画像"):
        asyncio.run(
            provider._analyze_winning_subagents(
                {
                    "topic": "局部战争装备需求",
                    "research_route": "traditional_gap",
                    "discovery_blueprint": {"primary_branch": "B"},
                    "packets": [{"packet_id": "packet-1"}],
                    "evidence_index": [],
                }
            )
        )

    phases = [phase for _, phase in calls]
    assert phases.count("winning_s6_image_deep") == 1
    assert phases.count("winning_s6_card_repair") == 1


@pytest.mark.parametrize(
    ("rerun_from", "expected_steps"),
    [(4, [4, 6]), (6, [6])],
)
def test_traceability_middle_loop_uses_minimal_targeted_repairs(
    rerun_from: int,
    expected_steps: list[int],
) -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    calls: list[tuple[str, str]] = []
    round_reviews = 0

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, payload, max_output_tokens
        nonlocal round_reviews
        calls.append((agent_id, phase))
        if agent_id == "winning_step_critic":
            return '{"passed":true,"issues":[],"retry_guidance":[]}'
        if agent_id == "winning_round_critic":
            round_reviews += 1
            if round_reviews == 1:
                return json.dumps(
                    {
                        "passed": False,
                        "rerun_from_step": rerun_from,
                        "issues": [
                            "S4 derived_from 索引越界，且对 effect_chain 的承接说明不足"
                        ],
                        "affected_fields": ["capability_mapping"],
                        "rerun_guidance": ["修正索引并补齐显式承接"],
                        "rerun_steps": [4, 5, 6],
                    },
                    ensure_ascii=False,
                )
            return '{"passed":true,"rerun_from_step":0,"issues":[]}'

        result = {key: [] for key in output_schema}
        if "confidence" in output_schema:
            result["confidence"] = 0.8
        if "evidence_validation" in output_schema:
            result["evidence_validation"] = {
                "all_ids_valid": True,
                "invalid_ids": [],
                "mismatched_claims": [],
            }
        if "reasoning_node" in output_schema:
            step = int(agent_id.split("_s", 1)[1].split("_", 1)[0])
            result["reasoning_node"] = _minimal_reasoning_node(step)
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "traceability repair",
                "research_route": "traditional_gap",
                "discovery_blueprint": {"primary_branch": "B"},
                "packets": [{"packet_id": "packet-1"}],
                "evidence_index": [],
            }
        )
    )

    executed_agents = [agent_id for agent_id, _ in calls]
    assert executed_agents.count("winning_s4_capability") == (
        2 if 4 in expected_steps else 1
    )
    assert executed_agents.count("winning_s5_gap") == 1
    assert executed_agents.count("winning_s6_image") == 2
    assert (
        ("winning_s4_capability", "winning_s4_targeted_repair") in calls
    ) is (4 in expected_steps)
    assert ("winning_s6_image", "winning_s6_card_repair") in calls
    backtrack = next(
        row
        for row in result["loop_trace"]
        if row.get("event") == "intelligent_backtrack"
    )
    assert backtrack["rerun_steps"] == expected_steps


def test_codex_cli_provider_builds_isolated_ephemeral_invocation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(
        command="codex",
        model="gpt-test",
        workspace_path=tmp_path,
        sandbox_mode="read-only",
    )
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"ok":true}'},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12}}),
        ]
    )
    captured: dict[str, object] = {}

    def fake_execute(command, prompt):
        captured["command"] = list(command)
        captured["prompt"] = prompt
        schema_path = command[command.index("--output-schema") + 1]
        captured["output_schema"] = json.loads(
            open(schema_path, encoding="utf-8").read()
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("system", "system"), ModelMessage("user", {"task": "x"})],
                [],
                {
                    "reasoning_effort": "high",
                    "model_verbosity": "low",
                    "web_search": {},
                    "output_schema": {"ok": "boolean"},
                },
            )
        ]

    events = asyncio.run(collect())
    command = captured["command"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-test"
    assert command[-1] == "-"
    assert 'web_search="live"' in command
    assert 'tools.web_search={context_size="high"}' in command
    assert 'model_reasoning_effort="high"' in command
    assert 'model_verbosity="low"' in command
    assert "--output-schema" in command
    assert captured["output_schema"] == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    assert "Do not edit workspace files" in str(captured["prompt"])
    assert events[-1].final_turn.text == '{"ok":true}'
    assert events[-1].final_turn.metadata["codex_thread_id"] == "thread-1"
    assert events[-1].final_turn.metadata["attempts"] == 1
    assert provider.snapshot()["execution_backend"] == "independent_codex_cli"
    assert provider.snapshot()["session_mode"] == "ephemeral"
    assert provider.snapshot()["process_isolation"] == "new_process_per_turn"


def test_codex_cli_provider_creates_task_scoped_isolated_copy(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: str(command),
    )
    provider = CodexCliProvider(
        command="/usr/local/bin/codex",
        model="gpt-test",
        workspace_path=tmp_path,
        codex_home=tmp_path / "codex-home" / "orchestrator-default",
        sandbox_mode="read-only",
        include_default_skills=False,
    )

    scoped = provider.isolated_copy("specialist-instance-1")

    assert scoped is not provider
    assert scoped.snapshot()["context_isolation"] == "specialist-instance-1"
    assert scoped.snapshot()["session_mode"] == "ephemeral"
    assert scoped.codex_home == (
        provider.codex_home / "isolated" / "specialist-instance-1"
    )
    assert scoped.sandbox_mode == "read-only"
    assert "--ephemeral" in scoped._build_base_command()


def test_codex_async_process_returns_normally_without_forced_termination(
    tmp_path,
) -> None:
    provider = CodexCliProvider(
        command=sys.executable,
        workspace_path=tmp_path,
        include_default_skills=False,
    )

    result = asyncio.run(
        provider._execute_async(
            [sys.executable, "-c", "print('normal-completion')"],
            "",
            timeout_seconds=5,
        )
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "normal-completion"


def test_codex_timeout_kills_descendant_after_process_leader_exits(
    tmp_path,
) -> None:
    provider = CodexCliProvider(
        command=sys.executable,
        workspace_path=tmp_path,
        include_default_skills=False,
    )
    child_pid_path = tmp_path / "child.pid"
    script = (
        "import os, pathlib, subprocess, sys; "
        "child=subprocess.Popen(['/bin/sleep', '60']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); "
        "os._exit(0)"
    )

    with pytest.raises(ProviderRequestError, match="timed out after 1 seconds"):
        asyncio.run(
            provider._execute_async(
                [sys.executable, "-c", script, str(child_pid_path)],
                "",
                timeout_seconds=1,
            )
        )

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, 9)
        pytest.fail("timed-out Codex descendant process was left running")


def test_codex_failure_detail_prefers_structured_stdout_error_over_warnings() -> None:
    stdout = json.dumps(
        {
            "type": "turn.failed",
            "error": {"message": "upstream stream disconnected"},
        }
    )
    stderr = "2026-01-01 WARN remote plugin catalog requires login"

    detail = _codex_failure_detail(stdout, stderr)

    assert detail == "upstream stream disconnected"
    assert _is_retryable_failure(detail) is True


def test_codex_failure_detail_filters_plugin_warnings_for_nonretryable_error() -> None:
    stderr = "\n".join(
        [
            "2026-01-01 WARN remote plugin catalog requires login",
            "output schema is invalid",
        ]
    )

    detail = _codex_failure_detail("", stderr)

    assert detail == "output schema is invalid"
    assert _is_retryable_failure(detail) is False


def test_transient_relay_invalid_key_response_gets_one_provider_retry() -> None:
    detail = (
        'unexpected status 401 Unauthorized: {"error":"Invalid API key"}, '
        'url: https://relay.example.test/v1/responses'
    )

    assert _is_retryable_failure(detail) is True


def test_codex_cli_provider_retries_retryable_process_failure(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(workspace_path=tmp_path, retry_attempts=2)
    calls = 0
    success_stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"ok":true}'},
                }
            ),
            json.dumps({"type": "turn.completed"}),
        ]
    )

    def fake_execute(command, prompt):
        nonlocal calls
        del prompt
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=json.dumps(
                    {
                        "type": "turn.failed",
                        "error": {"message": "upstream stream disconnected"},
                    }
                ),
                stderr="WARN plugin login unavailable",
            )
        return subprocess.CompletedProcess(command, 0, stdout=success_stdout, stderr="")

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "test")],
                [],
                {"output_schema": {"ok": "boolean"}},
            )
        ]

    events = asyncio.run(collect())

    assert calls == 2
    assert events[-1].final_turn.text == '{"ok":true}'
    assert events[-1].final_turn.metadata["attempts"] == 2


def test_codex_cli_provider_allows_swarm_to_disable_provider_replay(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(workspace_path=tmp_path, retry_attempts=2)
    calls = 0

    def fake_execute(command, prompt):
        nonlocal calls
        del prompt
        calls += 1
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "upstream stream disconnected"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "test")],
                [],
                {
                    "output_schema": {"ok": "boolean"},
                    "_provider_timeout_seconds": 480,
                    "_provider_retry_attempts": 1,
                },
            )
        ]

    with pytest.raises(ProviderRequestError, match="after 1 attempt"):
        asyncio.run(collect())
    assert calls == 1


@pytest.mark.parametrize(
    ("allow_extended", "expected_timeout"),
    [(False, 900), (True, 3600)],
)
def test_codex_provider_extends_timeout_only_for_explicit_quality_calls(
    monkeypatch,
    tmp_path,
    allow_extended: bool,
    expected_timeout: int,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MAX_TIMEOUT_SECONDS", "3600")
    provider = CodexCliProvider(workspace_path=tmp_path, timeout_seconds=900)
    captured: dict[str, int] = {}
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"ok":true}'},
                }
            ),
            json.dumps({"type": "turn.completed"}),
        ]
    )

    async def fake_execute_async(command, prompt, *, timeout_seconds=None):
        del command, prompt
        captured["timeout_seconds"] = int(timeout_seconds or 0)
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(provider, "_execute_async", fake_execute_async)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "test")],
                [],
                {
                    "output_schema": {"ok": "boolean"},
                    "_provider_timeout_seconds": 3600,
                    "_allow_extended_provider_timeout": allow_extended,
                },
            )
        ]

    events = asyncio.run(collect())

    assert captured["timeout_seconds"] == expected_timeout
    assert events[-1].final_turn.metadata["provider_timeout_seconds"] == expected_timeout
    assert events[-1].final_turn.metadata["extended_provider_timeout"] is allow_extended


def test_compact_contract_is_converted_to_native_codex_json_schema() -> None:
    assert _contract_to_json_schema(
        {
            "confidence": "0..1",
            "action": "continue|backtrack|stop",
            "steps": [{"step": "1..6", "passed": "boolean"}],
        }
    ) == {
        "type": "object",
        "properties": {
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "action": {
                "type": "string",
                "enum": ["continue", "backtrack", "stop"],
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "integer", "minimum": 1, "maximum": 6},
                        "passed": {"type": "boolean"},
                    },
                    "required": ["step", "passed"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["confidence", "action", "steps"],
        "additionalProperties": False,
    }


def test_flexible_analysis_section_schema_remains_strict_json_schema_compatible() -> (
    None
):
    assert _contract_to_json_schema("string | object | array") == {
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ]
    }


def test_codex_failure_detail_reads_top_level_responses_error() -> None:
    stdout = json.dumps(
        {
            "error": {
                "message": "Invalid schema for response_format",
                "code": "invalid_json_schema",
            }
        }
    )

    assert _codex_failure_detail(stdout, "WARN plugin unavailable") == (
        "Invalid schema for response_format"
    )


def test_codex_cli_provider_loads_project_agent_runtime_skill(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    skill = tmp_path / "skills" / "runtime" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: runtime\ndescription: test\n---\n\nFollow the runtime.\n",
        encoding="utf-8",
    )
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        skill_paths=[skill],
    )

    command = provider._build_command({})
    config_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--config"
    ]
    assert any(value.startswith("skills.config=[") for value in config_values)
    assert any(str(skill) in value for value in config_values)


def test_codex_cli_provider_can_disable_all_default_skills(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        include_default_skills=False,
    )

    command = provider._build_command({})

    assert not any("skills.config=" in value for value in command)


def test_codex_cli_provider_auth_home_initialization_is_concurrency_safe(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    codex_home = tmp_path / "shared-codex-home"

    def build_provider(_: int) -> CodexCliProvider:
        return CodexCliProvider(
            workspace_path=tmp_path,
            codex_home=codex_home,
            api_key="shared-test-key",
            base_url="https://codex.example.test/v1",
            inherit_user_config=False,
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        providers = list(pool.map(build_provider, range(12)))

    payload = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    assert payload == {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": "shared-test-key",
    }
    assert all(provider.codex_home == codex_home for provider in providers)


def test_standalone_codex_prompt_omits_multi_agent_boilerplate() -> None:
    prompt = render_prompt_optimized(
        [
            ModelMessage("system", "独立报告指令"),
            ModelMessage("user", {"query": "体系韧性"}),
        ],
        {
            "prompt_mode": "standalone",
            "reasoning_effort": "xhigh",
            "max_output_tokens": 7600,
        },
    )

    assert prompt.startswith("独立报告指令")
    assert "任务输入" in prompt
    assert "体系韧性" in prompt
    assert "multi-agent orchestration" not in prompt
    assert "bounded research agent" not in prompt
    assert "Requested reasoning effort" not in prompt
    assert "Conversation:" not in prompt


def test_codex_cli_provider_uses_writable_isolated_home_and_drops_parent_runtime_env(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-thread")
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "parent")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.subprocess.run",
        fake_run,
    )
    provider = CodexCliProvider(workspace_path=tmp_path)
    provider._execute([provider.command, "exec"], "prompt")

    env = captured["env"]
    assert env["CODEX_HOME"] == str(tmp_path / "outputs/runtime/codex-home")
    assert "CODEX_THREAD_ID" not in env
    assert "CODEX_INTERNAL_ORIGINATOR_OVERRIDE" not in env
    assert (tmp_path / "outputs/runtime/codex-home").is_dir()


def test_codex_cli_provider_can_inherit_auth_without_global_provider_config(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    user_home = tmp_path / "user-home"
    user_codex = user_home / ".codex"
    user_codex.mkdir(parents=True)
    (user_codex / "auth.json").write_text('{"token":"test"}', encoding="utf-8")
    (user_codex / "config.toml").write_text(
        'model_provider = "custom"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(user_home))
    isolated_home = tmp_path / "isolated-codex"

    CodexCliProvider(
        workspace_path=tmp_path,
        codex_home=isolated_home,
        source_codex_home=user_codex,
        inherit_user_config=False,
    )

    assert (isolated_home / "auth.json").is_file()
    assert not (isolated_home / "config.toml").exists()


def test_codex_cli_provider_configures_api_key_and_base_url_without_exposing_secret(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    isolated_home = tmp_path / "codex-api-home"
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        codex_home=isolated_home,
        inherit_user_config=False,
        api_key="test-codex-key",
        base_url="https://codex.example.test/v1",
    )

    auth_path = isolated_home / "auth.json"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["auth_mode"] == "apikey"
    assert "OPENAI_API_KEY" in auth
    assert len(auth["OPENAI_API_KEY"]) > 0
    assert auth_path.stat().st_mode & 0o777 == 0o600
    command = provider._build_command({})
    config_values = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--config"
    ]
    assert 'model_provider="equipment_research_gateway"' in config_values
    gateway_config = next(
        value
        for value in config_values
        if value.startswith("model_providers.equipment_research_gateway=")
    )
    assert 'base_url="https://codex.example.test/v1"' in gateway_config
    assert 'wire_api="responses"' in gateway_config
    assert "supports_websockets=false" in gateway_config
    assert "test-codex-key" not in gateway_config
    assert provider.snapshot()["base_url_host"] == "codex.example.test"
    assert "test-codex-key" not in repr(provider)
    assert "test-codex-key" not in json.dumps(provider.snapshot())


def test_codex_custom_gateway_passes_api_key_only_through_child_environment(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.subprocess.run",
        fake_run,
    )
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        api_key="runtime-secret",
        base_url="https://codex.example.test/v1",
    )
    command = provider._build_command({})
    provider._execute(command, "prompt")

    env = captured["env"]
    assert env["EQUIPMENT_DR_CODEX_RUNTIME_API_KEY"] == "runtime-secret"
    assert "runtime-secret" not in " ".join(command)


def test_codex_api_url_mode_does_not_inherit_conflicting_user_provider_config(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    source_home = tmp_path / "source-codex"
    source_home.mkdir()
    (source_home / "config.toml").write_text(
        'model_provider = "unrelated-user-provider"\n',
        encoding="utf-8",
    )
    isolated_home = tmp_path / "isolated-codex"

    provider = CodexCliProvider(
        workspace_path=tmp_path,
        codex_home=isolated_home,
        source_codex_home=source_home,
        inherit_user_config=True,
        api_key="project-key",
        base_url="https://codex.example.test/v1",
    )

    assert provider.inherit_user_config is False
    assert not (isolated_home / "config.toml").exists()


@pytest.mark.parametrize(
    "base_url",
    [
        "http://codex.example.test/v1",
        "https://user:secret@codex.example.test/v1",
        "https://codex.example.test/v1?key=secret",
        "https://codex.example.test/v1#fragment",
    ],
)
def test_codex_cli_provider_rejects_unsafe_base_url(
    monkeypatch,
    tmp_path,
    base_url,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )

    with pytest.raises(ValueError, match="Codex base URL must be HTTPS"):
        CodexCliProvider(workspace_path=tmp_path, base_url=base_url)


def test_codex_mode_runs_six_subagents_with_inner_and_middle_loops(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS", "1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "1")
    step_results = [
        {"defense_decomposition": ["d"], "confidence": 0.8},
        {"winning_paths": ["p"], "confidence": 0.8},
        {"effect_chain": ["e"], "confidence": 0.8},
        _minimal_s4_gate_result(),
        {
            "gap_assessment": [{"capability": "c", "grade": "部分差距", "basis": "b"}],
            "confidence": 0.8,
        },
        _minimal_s6_gate_result(),
    ]
    for step, result in enumerate(step_results, start=1):
        result["reasoning_node"] = _minimal_reasoning_node(step)
    batches: list[list[ProviderStreamEvent]] = []
    for step, result in enumerate(step_results, start=1):
        batches.append(
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(text=json.dumps(result, ensure_ascii=False))
                )
            ]
        )
        if step not in {4, 6}:
            batches.append(
                [
                    ProviderStreamEvent.final(
                        ProviderFinalTurn(
                            text='{"passed":true,"issues":[],"retry_guidance":[]}'
                        )
                    )
                ]
            )
    batches.append(
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"rerun_from_step":0,"issues":[],"rerun_guidance":[]}'
                )
            )
        ]
    )
    backend = ScriptedFakeProvider(batches)
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]

    provider = ResponsesAgentProvider(backend)
    progress_rows: list[dict] = []
    provider.set_winning_progress_callback(progress_rows.append)
    result = provider.analyze_winning_mechanism(
        {
            "topic": "test",
            "research_route": "traditional_gap",
            "coverage": {},
            "packets": [{"packet_id": "packet-1"}],
            "evidence_index": [{"evidence_id": "ev-1"}],
        }
    )

    assert len(result["subagent_runs"]) == 6
    assert [row["agent_id"] for row in result["subagent_runs"]] == [
        "winning_s1_opponent",
        "winning_s2_operations",
        "winning_s3_breakthrough",
        "winning_s4_capability",
        "winning_s5_gap",
        "winning_s6_image",
    ]
    assert sum(row["loop"] == "inner" for row in result["loop_trace"]) == 6
    assert result["loop_trace"][-1]["loop"] == "middle"
    assert result["loop_trace"][-1]["passed"] is True
    assert list(result["reasoning_nodes"]) == [str(step) for step in range(1, 7)]
    assert result["reasoning_nodes"]["1"]["recognition"] == "S1可审计认识"
    assert result["subagent_runs"][0]["next_action"]["target_step"] == 2
    completed_progress_rows = [
        row
        for row in progress_rows
        if not str(row.get("event_type", "")).startswith("winning_model_")
    ]
    assert [row["step"] for row in completed_progress_rows] == [1, 2, 3, 4, 5, 6]
    assert any(
        row.get("event_type") == "winning_model_call_started"
        and row.get("step") == 3
        for row in progress_rows
    )
    assert len(result["codex_call_metrics"]) == 11
    assert "reasoning_node" not in {key for key in result if key != "reasoning_nodes"}
    prompt_text = "\n".join(
        str(message.content)
        for messages, _, _ in backend.inputs
        for message in messages
    )
    assert "现役升级必须写明被升级对象、至少两项软硬件改装" in prompt_text
    assert "禁止把自治、网关、算法、中间件、审计等通用技术" in prompt_text
    assert "公开证据不足，保留类别级" in prompt_text
    assert "公开型号、装备族谱或现役" in prompt_text
    assert "当前S步骤专用角色与方法、query军事任务与对抗问题" in prompt_text
    assert "跨Agent精简交接和公开证据只作为次级事实素材" in prompt_text
    assert any(
        "baseline_system" in options.get("output_schema", {})["concept_directions"][0]
        for _, _, options in backend.inputs
        if "concept_directions" in options.get("output_schema", {})
    )
    s6_inputs = []
    for messages, _, _ in backend.inputs:
        for message in messages:
            if not isinstance(message.content, Mapping):
                continue
            candidate = message.content.get("task_input", {})
            while (
                isinstance(candidate, Mapping)
                and set(candidate) == {"input"}
                and isinstance(candidate.get("input"), Mapping)
            ):
                candidate = candidate["input"]
            if isinstance(candidate, Mapping) and "capability_synthesis_handoff" in candidate:
                s6_inputs.append(dict(candidate))
    assert len(s6_inputs) == 1
    s6_input = s6_inputs[0]
    assert set(s6_input) == {
        "query",
        "branch",
        "analysis_priority",
        "branch_deliverables",
        "capability_synthesis_handoff",
        "disruptive_seed_context",
        "first_pass_quality_contract",
        "valid_evidence_ids",
    }
    assert "prior_step_outputs" not in s6_input
    assert "packet_index" not in str(s6_input)
    s1_s5_inputs: dict[int, dict] = {}
    for messages, _, _ in backend.inputs:
        for message in messages:
            if not isinstance(message.content, Mapping):
                continue
            candidate = message.content.get("task_input", {})
            while (
                isinstance(candidate, Mapping)
                and set(candidate) == {"input"}
                and isinstance(candidate.get("input"), Mapping)
            ):
                candidate = candidate["input"]
            contract = (
                candidate.get("military_divergence_contract", {})
                if isinstance(candidate, Mapping)
                else {}
            )
            if isinstance(contract, Mapping) and contract.get("step") in range(1, 6):
                s1_s5_inputs[int(contract["step"])] = dict(candidate)
    assert set(s1_s5_inputs) == {1, 2, 3, 4, 5}
    for step, step_input in s1_s5_inputs.items():
        contract = step_input["military_divergence_contract"]
        assert step_input["query"] == "test"
        assert contract["primary_anchor"] == "query_military_problem"
        assert contract["upstream_role"] == "evidence_constraints_counterevidence_only"
        assert contract["minimum_competing_mechanisms"] == 3
        assert contract["step"] == step


def test_lean_winning_loop_skips_model_critics_when_local_gates_pass(
    monkeypatch,
) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS", raising=False)
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    called_agents: list[str] = []

    def materialize(contract):
        if isinstance(contract, dict):
            return {key: materialize(value) for key, value in contract.items()}
        if isinstance(contract, list):
            return [materialize(contract[0])] if contract else []
        text = str(contract)
        if text == "boolean":
            return True
        if text == "0..1":
            return 0.8
        if "|" in text:
            return text.split("|", 1)[0]
        if "evidence_id" in text or "packet_id" in text:
            return "packet-1"
        return "value"

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, payload, max_output_tokens, phase
        called_agents.append(agent_id)
        result = materialize(output_schema)
        result["reasoning_node"] = {
            "recognition": f"{agent_id} result",
            "evidence_refs": ["packet-1"],
            "confidence": 0.8,
            "next_action": {
                "action": "continue",
                "target_step": 0,
                "reason": "local gate passed",
            },
        }
        result["confidence"] = 0.8
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = provider.analyze_winning_mechanism(
        {
            "topic": "lean-loop",
            "research_route": "traditional_gap",
            "packets": [{"packet_id": "packet-1"}],
            "evidence_index": [],
        }
    )

    assert len(result["subagent_runs"]) == 6
    assert set(called_agents) == {
        "winning_s1_opponent",
        "winning_s2_operations",
        "winning_s3_breakthrough",
        "winning_s4_capability",
        "winning_s5_gap",
        "winning_s6_image",
    }
    assert all("critic" not in agent_id for agent_id in called_agents)
    assert result["loop_trace"][-1]["loop"] == "middle"
    assert result["loop_trace"][-1]["passed"] is True


def test_codex_winning_graph_runs_s5_after_s4_capability_mapping() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    execution_order: list[str] = []

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        del system, payload, max_output_tokens, phase
        if agent_id in {"winning_s4_capability", "winning_s5_gap"}:
            execution_order.append(agent_id)
        if agent_id in {"winning_step_critic", "winning_round_critic"}:
            return '{"passed":true,"issues":[],"retry_guidance":[],"rerun_from_step":0}'
        result = {key: [] for key in output_schema}
        result.update(
            {
                "confidence": 0.8,
                "reasoning_node": {
                    "recognition": agent_id,
                    "evidence_refs": [],
                    "confidence": 0.8,
                    "next_action": {
                        "action": "continue",
                        "target_step": 0,
                        "reason": "complete",
                    },
                },
            }
        )
        return json.dumps(result)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]

    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "test",
                "research_route": "traditional_gap",
                "discovery_blueprint": {"primary_branch": "B"},
                "packets": [],
                "evidence_index": [],
            }
        )
    )

    assert execution_order == ["winning_s4_capability", "winning_s5_gap"]
    assert [row["step"] for row in result["subagent_runs"]] == [1, 2, 3, 4, 5, 6]


def test_codex_winning_graph_skips_steps_for_cross_domain_branch() -> None:
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
        del system, payload, max_output_tokens, phase
        if agent_id == "winning_round_critic":
            return '{"passed":true,"rerun_from_step":0,"issues":[]}'
        result = {key: [] for key in output_schema}
        if "confidence" in output_schema:
            result["confidence"] = 0.8
        if "evidence_validation" in output_schema:
            result["evidence_validation"] = {
                "all_ids_valid": True,
                "invalid_ids": [],
                "mismatched_claims": [],
            }
        result["reasoning_node"] = _minimal_reasoning_node(
            6 if agent_id == "winning_s6_image" else int(agent_id.split("_s", 1)[1][0])
        )
        return json.dumps(result, ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]

    result = provider.analyze_winning_mechanism(
        {
            "topic": "cross-domain",
            "research_route": "new_winning_mechanism",
            "discovery_blueprint": {"primary_branch": "G"},
            "coverage": {},
            "packets": [],
            "evidence_index": [],
        }
    )

    assert [
        row["step"] for row in result["subagent_runs"] if row["status"] == "completed"
    ] == [3, 4, 6]
    assert [
        row["step"]
        for row in result["subagent_runs"]
        if row["status"] == "skipped_by_branch_blueprint"
    ] == [1, 2, 5]
    assert [row["execution_mode"] for row in result["winning_step_plan"]] == [
        "skip",
        "skip",
        "deep",
        "deep",
        "skip",
        "deep",
    ]


def test_winning_retry_is_checked_by_harness_then_final_round_critic(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS", "1")
    batches = [
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"effect_chain":["e1"]}'))],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                        text=(
                            '{"passed":false,"issues":["缺少边界"],'
                            '"retry_guidance":["补充边界"],'
                            '"recommended_action":"retry"}'
                        )
                )
            )
        ],
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"effect_chain":["e2"]}'))],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=json.dumps(_minimal_s4_gate_result(), ensure_ascii=False)
                )
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=json.dumps(_minimal_s6_gate_result("G"), ensure_ascii=False)
                )
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"rerun_from_step":0,"issues":[]}'
                )
            )
        ],
    ]
    backend = ScriptedFakeProvider(batches)
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]

    result = ResponsesAgentProvider(backend).analyze_winning_mechanism(
        {
            "topic": "cross-domain",
            "research_route": "new_winning_mechanism",
            "discovery_blueprint": {"primary_branch": "G"},
            "coverage": {},
            "packets": [],
            "evidence_index": [],
        }
    )

    critic_calls = [
        item
        for item in result["codex_call_metrics"]
        if item["agent_id"] == "winning_step_critic"
    ]
    assert len(critic_calls) == 1
    assert len(backend.inputs) == 6
    assert sum(row["loop"] == "inner" for row in result["loop_trace"]) == 4


def test_winning_recall_does_not_repeat_same_step_with_unchanged_input(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS", "1")
    batches = [
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"effect_chain":["e1"]}'))],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=(
                        '{"passed":false,"issues":["需要补证"],'
                        '"recommended_action":"recall",'
                        '"recall_target":"technology_readiness"}'
                    )
                )
            )
        ],
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"capability_mapping":["m"]}'))],
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"passed":true,"issues":[]}'))],
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"concept_directions":[]}'))],
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"passed":true,"issues":[]}'))],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"rerun_from_step":0,"issues":[]}'
                )
            )
        ],
    ]
    backend = ScriptedFakeProvider(batches)
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]

    result = ResponsesAgentProvider(backend).analyze_winning_mechanism(
        {
            "topic": "cross-domain",
            "research_route": "new_winning_mechanism",
            "discovery_blueprint": {"primary_branch": "G"},
            "coverage": {},
            "packets": [],
            "evidence_index": [],
        }
    )

    s3_runs = [
        row
        for row in result["subagent_runs"]
        if row["agent_id"] == "winning_s3_breakthrough"
    ]
    assert len(backend.inputs) == 7
    assert len(s3_runs) == 1
    assert s3_runs[0]["critic_action"] == "recall"
    assert s3_runs[0]["critic_recall_target"] == "technology_readiness"


def test_targeted_resume_reuses_prior_steps_and_dynamic_outputs(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS", "1")
    batches = []
    for payload in (
        '{"capability_mapping":["m2"]}',
        '{"gap_assessment":[]}',
        '{"concept_directions":[]}',
    ):
        batches.extend(
            [
                [ProviderStreamEvent.final(ProviderFinalTurn(text=payload))],
                [
                    ProviderStreamEvent.final(
                        ProviderFinalTurn(text='{"passed":true,"issues":[]}')
                    )
                ],
            ]
        )
    batches.append(
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"rerun_from_step":0,"issues":[]}'
                )
            )
        ]
    )
    backend = ScriptedFakeProvider(batches)
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]

    result = ResponsesAgentProvider(backend).analyze_winning_mechanism(
        {
            "topic": "resume",
            "research_route": "traditional_gap",
            "discovery_blueprint": {
                "primary_branch": "B",
                "dynamic_subagents": [
                    {"agent_instance_id": "dynamic-existing", "merge_target": "S3"}
                ],
            },
            "packets": [],
            "evidence_index": [],
            "resume_steps": [4, 5, 6],
            "prior_winning_analysis": {
                "defense_decomposition": ["d1"],
                "winning_paths": ["p1"],
                "effect_chain": ["e1"],
                "dynamic_subagent_outputs": [
                    {
                        "agent_instance_id": "dynamic-existing",
                        "merge_target": "S3",
                        "result": {"findings": ["existing"]},
                    }
                ],
            },
        }
    )

    assert len(backend.inputs) == 7
    assert result["defense_decomposition"] == ["d1"]
    assert result["effect_chain"] == ["e1"]
    assert [
        row["step"]
        for row in result["subagent_runs"]
        if row["status"] == "reused_from_prior_analysis"
    ] == [1, 2, 3]


def test_codex_winning_graph_runs_dynamic_specialists_before_merge() -> None:
    batches = [
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=json.dumps(
                        {
                            "findings": ["关键部件替代路线不足"],
                            "evidence_refs": ["packet-1"],
                            "contribution_to_steps": [
                                {"step": 5, "contribution": "补充供应链差距"}
                            ],
                            "assumptions": [],
                            "open_questions": [],
                            "merge_target": "S5",
                            "stop_reason": "bounded_complete",
                            "confidence": 0.76,
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"effect_chain":["e"],"confidence":0.8}')
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"issues":[],"retry_guidance":[]}'
                )
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"capability_mapping":["m"],"confidence":0.8}')
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"issues":[],"retry_guidance":[]}'
                )
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"concept_directions":[],"confidence":0.8}')
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"issues":[],"retry_guidance":[]}'
                )
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text='{"passed":true,"rerun_from_step":0,"issues":[],"rerun_guidance":[]}'
                )
            )
        ],
    ]
    backend = ScriptedFakeProvider(batches)
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]

    result = ResponsesAgentProvider(backend).analyze_winning_mechanism(
        {
            "topic": "cross-domain",
            "research_route": "new_winning_mechanism",
            "discovery_blueprint": {
                "primary_branch": "G",
                "dynamic_subagents": [
                    {
                        "agent_instance_id": "dynamic-supply-chain-1",
                        "display_name": "供应链韧性研究Agent",
                        "purpose": "补充供应链约束",
                        "skill_ids": ["codex_deep_search_shared"],
                        "knowledge_pack_ids": ["equipment_ontology"],
                        "merge_target": "S5",
                        "max_output_tokens": 1200,
                    }
                ],
            },
            "coverage": {},
            "packets": [{"packet_id": "packet-1"}],
            "evidence_index": [],
        }
    )

    assert result["dynamic_subagent_outputs"][0]["agent_instance_id"] == (
        "dynamic-supply-chain-1"
    )
    assert result["dynamic_subagent_runs"][0]["merge_target"] == "S5"
    assert result["subagent_runs"][0]["execution_mode"] == "dynamic"
    projected_dynamic_inputs = []
    for messages, _, _ in backend.inputs[1:]:
        for message in messages:
            if not isinstance(message.content, Mapping):
                continue
            candidate = message.content.get("task_input", {})
            while (
                isinstance(candidate, Mapping)
                and set(candidate) == {"input"}
                and isinstance(candidate.get("input"), Mapping)
            ):
                candidate = candidate["input"]
            prior = (
                candidate.get("prior_step_outputs", {})
                if isinstance(candidate, Mapping)
                else {}
            )
            if isinstance(prior, Mapping):
                projected_dynamic_inputs.extend(prior.get("dynamic_inputs", []))
    assert projected_dynamic_inputs == []


def test_swarm_quality_profile_runs_three_bounded_waves_and_keeps_candidate_ledger() -> None:
    def candidate(index: int) -> dict:
        return {
            "title": f"候选{index}：机制族{index}",
            "nearest_public_baseline": f"公开基线{index}",
            "changed_confrontation_variable": f"改变变量{index}",
            "mechanism_chain": [f"独立机制{index}", f"任务闭环{index}"],
            "direct_military_effects": [f"直接军事效果{index}"],
            "equipment_forms": [f"具体装备形态{index}"],
            "novelty_delta": f"相对基线形成实质差异{index}",
            "evidence_ids": ["ev-1"],
            "evidence_boundary": "公开证据只支持组成技术，不证明完整效能",
            "counterevidence": [f"反证{index}"],
            "adversary_adaptations": [f"对手适应{index}"],
            "failure_boundaries": [f"失效边界{index}"],
            "trl_constraints": [f"成熟度约束{index}"],
            "cost_constraints": [f"成本约束{index}"],
            "industrial_constraints": [f"产能约束{index}"],
            "cross_scenario_results": [f"跨场景结果{index}"],
            "validation_plan": [f"可证伪试验{index}"],
            "implementation_path": "new",
        }

    batches = [
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=json.dumps(
                        {"hypotheses": [candidate(index)]},
                        ensure_ascii=False,
                    )
                )
            )
        ]
        for index in range(1, 5)
    ]
    batches.extend(
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=json.dumps(
                        {
                            "findings": ["独立评审确认保留并补充不确定性边界"],
                            "evidence_ids": ["ev-1", "invented-id"],
                            "evidence_boundary": "不把组成技术证据外推为作战效能",
                            "incremental_quality": 0.05,
                            "recommendation": "retain",
                        },
                        ensure_ascii=False,
                    )
                )
            )
        ]
        for _ in range(2)
    )
    backend = ScriptedFakeProvider(batches)
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    progress_rows: list[dict] = []
    provider.set_winning_progress_callback(progress_rows.append)

    result = provider.analyze_winning_mechanism(
        {
            "topic": "bounded swarm",
            "research_route": "new_winning_mechanism",
            "execution_profile_id": "swarm_quality_v1",
            "discovery_blueprint": {
                "primary_branch": "D",
                "execution_profile_id": "swarm_quality_v1",
                "adaptive_winning_step_modes": {
                    str(step): "skip" for step in range(1, 7)
                },
                "winning_swarm_policy": {
                    "enabled": True,
                    "max_dynamic_instances": 12,
                    "max_concurrency": 6,
                    "max_waves": 3,
                    "minimum_expected_gain": 0.03,
                },
            },
            "coverage": {},
            "packets": [{"packet_id": "packet-1", "agent_id": "weapon_equipment"}],
            "evidence_index": [{"evidence_id": "ev-1"}],
        }
    )

    swarm = result["winning_swarm"]
    assert len(backend.inputs) == 6
    assert len(swarm["task_graph"]) == 6
    assert [item["wave"] for item in swarm["waves"]] == [1, 3]
    assert len(swarm["hypotheses"]) == 4
    assert 2 <= len(swarm["finalists"]) <= 4
    assert swarm["budget"]["maximum_instances"] == 12
    assert swarm["core_schedule"]["active_steps"] == []
    assert swarm["core_schedule"]["quality_gate_passed"] is True
    assert swarm["final_merge"]["passed"] is True
    assert [
        (item["wave"], item["batch"], len(item["task_ids"]))
        for item in swarm["specialist_execution_batches"]
    ] == [(1, 1, 4), (3, 1, 2)]
    assert all(
        evidence_id == "ev-1"
        for item in swarm["hypotheses"]
        for evidence_id in item["evidence_ids"]
    )
    event_types = {row.get("event_type") for row in progress_rows}
    assert {
        "swarm_planned",
        "specialist_recruitment_planned",
        "specialist_spawned",
        "specialist_session_started",
        "specialist_session_completed",
        "specialist_completed",
        "hypothesis_created",
        "swarm_gate_evaluated",
    } <= event_types
    recruitment_rows = [
        row
        for row in progress_rows
        if row.get("event_type") == "specialist_recruitment_planned"
    ]
    assert len(recruitment_rows) == 6
    assert len({row["session_ref"] for row in recruitment_rows}) == 6
    assert all(row["provider_type"] == "codex_cli" for row in recruitment_rows)
    assert all(
        row["execution_backend"] == "independent_codex_cli"
        for row in recruitment_rows
    )
    assert all(row["context_isolation"] == "ephemeral" for row in recruitment_rows)
    assert all(row["allow_child_spawn"] is False for row in recruitment_rows)
    assert all(row["role_purpose"] for row in recruitment_rows)
    for recruitment in recruitment_rows:
        lifecycle = [
            row["event_type"]
            for row in progress_rows
            if row.get("agent_id") == recruitment["agent_instance_id"]
        ]
        assert lifecycle.index("specialist_recruitment_planned") < lifecycle.index(
            "specialist_session_started"
        )
        assert lifecycle.index("specialist_session_started") < lifecycle.index(
            "specialist_session_completed"
        )
        assert lifecycle.index("specialist_session_completed") < lifecycle.index(
            "specialist_completed"
        )


def test_swarm_quality_profile_runs_core_s_agents_in_parallel_and_finalizes_merge() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    breadth_index = 0
    running_core = 0
    maximum_running_core = 0

    def sample_schema(value, key: str = ""):
        if key == "reasoning_node":
            return {
                "recognition": "形成可审计认识",
                "evidence_refs": ["ev-1"],
                "confidence": 0.82,
                "next_action": {
                    "action": "continue",
                    "target_step": 3,
                    "reason": "依赖满足后继续",
                },
            }
        if isinstance(value, Mapping):
            return {name: sample_schema(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [sample_schema(value[0], key)] if value else []
        if key == "confidence":
            return 0.82
        if key in {"evidence_refs", "direct_evidence_refs", "evidence_ids"}:
            return ["ev-1"]
        if "boolean" in str(value):
            return True
        return f"{key or 'field'}-value"

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        nonlocal breadth_index, running_core, maximum_running_core
        del system, max_output_tokens
        if phase == "winning_swarm_breadth":
            breadth_index += 1
            return json.dumps(
                {
                    "hypotheses": [
                        {
                            "title": f"候选{breadth_index}",
                            "nearest_public_baseline": f"公开基线{breadth_index}",
                            "changed_confrontation_variable": f"变量{breadth_index}",
                            "mechanism_chain": [f"机理{breadth_index}", "形成任务闭环"],
                            "direct_military_effects": [f"直接效果{breadth_index}"],
                            "equipment_forms": [f"具体装备{breadth_index}"],
                            "novelty_delta": f"实质差异{breadth_index}",
                            "evidence_ids": ["ev-1"],
                            "evidence_boundary": "证据不外推完整作战效能",
                            "counterevidence": ["存在反证"],
                            "adversary_adaptations": ["对手可能适应"],
                            "failure_boundaries": ["边界条件"],
                            "trl_constraints": ["成熟度待验证"],
                            "cost_constraints": ["成本待比较"],
                            "industrial_constraints": ["产能待核验"],
                            "cross_scenario_results": ["跨场景保持方向有效"],
                            "validation_plan": ["设置可证伪对照试验"],
                            "implementation_path": "new",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        if phase == "winning_swarm_convergence":
            task = payload["specialist_task"]
            return json.dumps(
                {
                    "hypothesis_id": task["hypothesis_id"],
                    "merge_target": task["merge_target"],
                    "findings": ["独立评审确认保留"],
                    "evidence_ids": ["ev-1"],
                    "evidence_boundary": "只确认方向，不虚构精确效能",
                    "incremental_quality": 0.05,
                    "recommendation": "retain",
                },
                ensure_ascii=False,
            )
        if agent_id in {"winning_s1_opponent", "winning_s2_operations"}:
            running_core += 1
            maximum_running_core = max(maximum_running_core, running_core)
            await asyncio.sleep(0.02)
            running_core -= 1
        return json.dumps(sample_schema(output_schema), ensure_ascii=False)

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = provider.analyze_winning_mechanism(
        {
            "topic": "core swarm parallel merge",
            "research_route": "new_winning_mechanism",
            "execution_profile_id": "swarm_quality_v1",
            "discovery_blueprint": {
                "primary_branch": "B",
                "execution_profile_id": "swarm_quality_v1",
                "adaptive_winning_step_modes": {
                    "1": "standard",
                    "2": "standard",
                    "3": "skip",
                    "4": "skip",
                    "5": "skip",
                    "6": "skip",
                },
                "winning_swarm_policy": {"enabled": True},
            },
            "coverage": {},
            "packets": [{"packet_id": "packet-1", "agent_id": "combat_scenario"}],
            "evidence_index": [{"evidence_id": "ev-1"}],
        }
    )

    swarm = result["winning_swarm"]
    assert maximum_running_core == 2
    assert swarm["core_schedule"]["logical_waves"][0]["core_agents"] == [
        "S1",
        "S2",
    ]
    assert swarm["core_schedule"]["completed_steps"] == ["S1", "S2"]
    assert swarm["core_schedule"]["quality_gate_passed"] is True
    assert swarm["final_merge"]["passed"] is True


def test_dynamic_v2_releases_fast_candidate_branch_before_slow_s3_and_scopes_merge() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    progress_rows: list[dict] = []
    provider.set_winning_progress_callback(progress_rows.append)
    seed_index = 0
    judge_round = 0
    scoped_merge_inputs: list[tuple[str, list[str], list[str]]] = []
    dynamic_seed_library_inputs: list[tuple[str, dict]] = []
    active_seed_calls = 0
    maximum_seed_concurrency = 0

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        nonlocal seed_index, judge_round, active_seed_calls, maximum_seed_concurrency
        del system, output_schema, max_output_tokens
        if phase == "winning_quality_expert_review":
            judge_round += 1
            initial_failure_count = max(
                0, len(payload["blind_candidates"]) - 3
            )
            return json.dumps(
                {
                    "assessments": [
                        {
                            "blind_label": item["blind_label"],
                            "verdict": (
                                "revise"
                                if (
                                    judge_round == 1
                                    and index <= initial_failure_count
                                )
                                else "pass"
                            ),
                            "dimension_scores": {
                                "domain_relevance": 0.86,
                                "equipment_capability_fit": (
                                    0.70
                                    if (
                                        judge_round == 1
                                        and index <= initial_failure_count
                                    )
                                    else 0.84
                                ),
                                "innovation": 0.78,
                                "military_value": (
                                    0.68
                                    if (
                                        judge_round == 1
                                        and index <= initial_failure_count
                                    )
                                    else 0.88
                                ),
                                "causal_coherence": 0.82,
                                "credibility": 0.80,
                                "engineering_feasibility": 0.76,
                                "robustness": 0.74,
                            },
                            "strengths": ["形成具体无人战斗装备落点"],
                            "weaknesses": ["工程参数仍需试验校准"],
                            "rejection_reasons": (
                                ["装备构型需要进一步具体化"]
                                if (
                                    judge_round == 1
                                    and index <= initial_failure_count
                                )
                                else []
                            ),
                            "residuals": (
                                ["equipment_not_concrete"]
                                if (
                                    judge_round == 1
                                    and index <= initial_failure_count
                                )
                                else []
                            ),
                            "equipment_classification": "unmanned_combat",
                            "innovation_type": "mechanism",
                            "confidence": 0.82,
                            "evidence_ids": ["ev-1"],
                        }
                        for index, item in enumerate(
                            payload["blind_candidates"], start=1
                        )
                    ],
                    "portfolio_findings": ["候选之间形成机制差异"],
                    "stop_reason": "review_complete",
                },
                ensure_ascii=False,
            )
        task = payload["specialist_task"]
        mission_node = task["merge_target"]
        if phase == "winning_swarm_dynamic_seed":
            dynamic_seed_library_inputs.append(
                (
                    str(task["archetype"]),
                    dict(payload.get("disruptive_paradigm_seed_library_v2", {})),
                )
            )
            seed_index += 1
            active_seed_calls += 1
            maximum_seed_concurrency = max(
                maximum_seed_concurrency, active_seed_calls
            )
            try:
                if agent_id.endswith("adversary_counter_adaptation_red_team"):
                    await asyncio.sleep(0.08)
                else:
                    await asyncio.sleep(0.02)
            finally:
                active_seed_calls -= 1
            marker = f"branch_token_{seed_index}_{agent_id}"
            portfolio_completion = (
                "portfolio_direction_shortfall"
                in task.get("trigger_residuals", [])
            )
            hypothesis_count = 2 if portfolio_completion else 1
            return json.dumps(
                {
                    "hypotheses": [
                        {
                            "title": (
                                (
                                    f"远程精确巡航效应器-{marker}"
                                    if ordinal == 1
                                    else f"可消耗电子压制无人平台-{marker}"
                                )
                                if portfolio_completion
                                else f"title_{marker}"
                            ),
                            "nearest_public_baseline": f"baseline-{marker}-{ordinal}",
                            "changed_confrontation_variable": f"variable_{marker}_{ordinal}",
                            "mechanism_chain": [
                                (
                                    (
                                        f"远域突防精确毁伤-{marker}"
                                        if ordinal == 1
                                        else f"低空诱导电子压制-{marker}"
                                    )
                                    if portfolio_completion
                                    else f"mechanism_{marker}"
                                )
                            ],
                            "direct_military_effects": [
                                (
                                    (
                                        f"纵深精确毁伤-{marker}"
                                        if ordinal == 1
                                        else f"压制防空火控窗口-{marker}"
                                    )
                                    if portfolio_completion
                                    else f"effect_{marker}"
                                )
                            ],
                            "equipment_forms": [
                                (
                                    (
                                        f"远程精确巡航弹药-{marker}"
                                        if ordinal == 1
                                        else f"可消耗电子攻击无人机-{marker}"
                                    )
                                    if portfolio_completion
                                    else f"自主无人战斗平台-{marker}"
                                )
                            ],
                            "system_interfaces": [
                                f"任务总线-{marker}-{ordinal}",
                                f"火控授权接口-{marker}-{ordinal}",
                            ],
                            "novelty_delta": f"delta-{marker}-{ordinal}",
                            "evidence_ids": ["ev-1"],
                            "evidence_boundary": "只支持方向，不外推精确效能",
                            "counterevidence": ["复杂干扰可能削弱效果"],
                            "adversary_adaptations": ["对手采用诱饵和压制"],
                            "failure_boundaries": ["感知完全失效时不成立"],
                            "trl_constraints": ["关键载荷成熟度待验证"],
                            "cost_constraints": ["需比较全寿命成本"],
                            "industrial_constraints": ["需验证模块化产能"],
                            "cross_scenario_results": ["强干扰场景需压力测试"],
                            "validation_plan": ["设置对照场景进行可证伪试验"],
                            "implementation_path": "new",
                        }
                        for ordinal in range(1, hypothesis_count + 1)
                    ],
                    "quality_residuals": (
                        ["evidence_insufficient"]
                        if "mechanism_generator" in agent_id
                        or "counter_adaptation_red_team" in agent_id
                        else []
                    ),
                    "stop_reason": "seed_complete",
                },
                ensure_ascii=False,
            )
        allowed_ids = list(
            payload["candidate_ledger"].get("allowed_hypothesis_ids", [])
        )
        visible_ids = [
            item["hypothesis_id"]
            for item in payload["candidate_ledger"].get("hypotheses", [])
        ]
        scoped_merge_inputs.append((mission_node, allowed_ids, visible_ids))
        contributions = [
            {
                "hypothesis_id": hypothesis_id,
                "merge_target": mission_node,
                "findings": [f"{mission_node}结构化增量"],
                "equipment_forms": ["模块化自主无人战斗平台"],
                "system_interfaces": ["开放任务总线", "火控授权接口"],
                "evidence_ids": ["ev-1"],
                "evidence_boundary": "保持公开证据边界",
                "failure_boundaries": ["失效边界已记录"],
                "validation_plan": ["对照试验验证任务链闭合"],
                "residuals_resolved": ["equipment_not_concrete"],
                "incremental_quality": 0.06,
                "recommendation": "retain",
            }
            for hypothesis_id in allowed_ids
        ]
        return json.dumps(
            {
                "contributions": contributions,
                "portfolio_review": ["保留非支配候选"],
                "stop_reason": "merge_complete",
            },
            ensure_ascii=False,
        )

    provider._run_core_json = fake_run_core_json  # type: ignore[method-assign]
    result = provider.analyze_winning_mechanism(
        {
            "topic": "动态制胜机理装备集群",
            "research_route": "new_winning_mechanism",
            "execution_profile_id": "winning_swarm_dynamic_v2",
            "discovery_blueprint": {
                "primary_branch": "D",
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "adaptive_winning_step_modes": {
                    str(step): "skip" for step in range(1, 7)
                },
                "winning_swarm_policy": {
                    "enabled": True,
                    "policy_id": "winning_swarm_dynamic_v2",
                    "mission_graph_target_instances": 13,
                    "expert_repair_reserved_instances": 3,
                    "expert_repair_max_candidates": 3,
                    "max_concurrency": 6,
                },
            },
            "coverage": {},
            "packets": [{"packet_id": "packet-1", "agent_id": "weapon_equipment"}],
            "evidence_index": [{"evidence_id": "ev-1"}],
        }
    )

    swarm = result["winning_swarm"]
    assert 12 <= len(swarm["task_graph"]) <= 18
    assert sum(
        row.get("event_type") == "winning_quality_repair_planned"
        for row in progress_rows
    ) == 2
    assert any(
        row.get("event_type")
        == "winning_portfolio_gap_completion_planned"
        for row in progress_rows
    )
    assert swarm["budget"]["planned_instances"] <= 18
    assert swarm["budget"]["maximum_observed_concurrency"] <= 6
    assert maximum_seed_concurrency >= 5
    direct_generator_seeds = next(
        context
        for archetype, context in dynamic_seed_library_inputs
        if archetype == "direct_combat_equipment_generator"
    )
    # A generic Query no longer receives role/branch-prior cards. The Codex
    # specialist owns open-ended divergence and may receive an empty library.
    assert direct_generator_seeds == {}
    assert 5 <= len(swarm["final_equipment_portfolio"]) <= 7
    assert swarm["portfolio_quality_gate"]["passed"] is True, swarm[
        "portfolio_quality_gate"
    ]
    assert swarm["portfolio_quality_gate"]["capability_portrait_gate_passed"] is True
    assert (
        swarm["portfolio_quality_gate"]["complete_capability_portrait_count"]
        == len(swarm["final_equipment_portfolio"])
    )
    assert swarm["portfolio_quality_gate"]["expert_judge_passed"] is True
    assert swarm["expert_judge"]["status"] == "completed"
    assert swarm["expert_judge"]["round_count"] == 2
    assert swarm["expert_judge"]["repair_wave"]["merged_count"] == 2
    assert (
        swarm["expert_judge"]["portfolio_completion_wave"]["created_count"]
        == 2
    )
    assert len(swarm["expert_judge"]["rounds"][1]["assessments"]) == 4
    assert len(swarm["expert_assessments"]) == len(swarm["hypotheses"])
    rejected_by_expert = {
        item["hypothesis_id"]
        for item in swarm["expert_assessments"]
        if item["passed"] is False
    }
    assert len(rejected_by_expert) >= 1
    assert rejected_by_expert.isdisjoint(
        swarm["portfolio_decision"]["selected_hypothesis_ids"]
    )
    assert swarm["portfolio_quality_gate"]["direct_combat_equipment_count"] >= 4
    assert [item["name"] for item in result["concept_directions"]] == [
        item["name"] for item in swarm["final_equipment_portfolio"]
    ]
    assert all(
        item["equipment_form"]
        and item["military_value"]
        and item["operational_mechanism"]
        and item["baseline_system"]
        and item["capability_gap"]
        and item["system_interfaces"]
        and item["direct_evidence_refs"]
        and item["failure_boundaries"]
        and item["validation_plan"]
        for item in result["concept_directions"]
    )
    assert all(
        row[1] == row[2]
        for row in scoped_merge_inputs
        if row[0] in {"S4", "S5"}
    )
    fast_s3_id = next(
        item["instance_id"]
        for item in swarm["task_graph"]
        if item["archetype"] == "disruptive_mechanism_generator"
    )
    slow_s3_id = next(
        item["instance_id"]
        for item in swarm["task_graph"]
        if item["archetype"] == "adversary_counter_adaptation_red_team"
    )
    fast_s3 = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_completed"
        and row.get("agent_id") == fast_s3_id
    )
    frontier_s4_id = next(
        item["instance_id"]
        for item in swarm["task_graph"]
        if item["archetype"] == "frontier_equipment_miner"
    )
    architect_s4_id = next(
        item["instance_id"]
        for item in swarm["task_graph"]
        if item["archetype"] == "equipment_realization_architect"
    )
    evidence_s5_id = next(
        item["instance_id"]
        for item in swarm["task_graph"]
        if item["archetype"] == "evidence_verifier"
    )
    frontier_s4_started = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_started"
        and row.get("agent_id") == frontier_s4_id
    )
    architect_s4_started = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_started"
        and row.get("agent_id") == architect_s4_id
    )
    evidence_s5_started = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_started"
        and row.get("agent_id") == evidence_s5_id
    )
    slow_s3 = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_completed"
        and row.get("agent_id") == slow_s3_id
    )
    assert frontier_s4_started < slow_s3
    assert fast_s3 < evidence_s5_started < slow_s3
    assert fast_s3 < architect_s4_started


def test_codex_l4_meta_review_uses_orchestrator_runtime() -> None:
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=json.dumps(
                            {
                                "replan_required": True,
                                "added_secondary_branches": ["E"],
                                "step_mode_overrides": [
                                    {
                                        "step": 1,
                                        "mode": "deep",
                                        "reason": "出现对手动向线索",
                                    },
                                ],
                                "focus_questions": ["对手能力形成节奏是否改变优先序"],
                                "rationale": "跨分支线索需要加强S1。",
                                "stop_reason": "bounded_replan_complete",
                            },
                            ensure_ascii=False,
                        )
                    )
                )
            ]
        ]
    )
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]

    result = ResponsesAgentProvider(backend).review_discovery_meta_loop(
        {
            "topic": "test",
            "discovery_blueprint": {"primary_branch": "G"},
            "convergence": {"cross_branch_links": ["G-E"]},
        }
    )

    assert result["replan_required"] is True
    assert result["added_secondary_branches"] == ["E"]
    assert result["step_mode_overrides"][0]["step"] == 1


def test_adaptive_l4_plan_overrides_branch_default_step_modes() -> None:
    assert _winning_step_modes(
        {
            "discovery_blueprint": {
                "primary_branch": "G",
                "adaptive_winning_step_modes": {"1": "deep", "5": "light"},
            }
        }
    ) == {
        1: "deep",
        2: "skip",
        3: "deep",
        4: "deep",
        5: "light",
        6: "deep",
    }
