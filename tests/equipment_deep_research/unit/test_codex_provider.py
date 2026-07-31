from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess

import pytest

import equipment_deep_research.agents.provider as provider_module

from equipment_deep_research.agents.provider import (
    ResponsesAgentProvider,
    _branch_product_output_schema,
    _capability_direction_quality_issues,
    _capability_language_issues,
    _capability_synthesis_handoff,
    _compact_s6_prior_outputs,
    _has_combat_effect_signal,
    _normalize_concept_direction_priorities,
    _normalize_effect_chain_references,
    _normalize_priority_references,
    _normalize_s6_deterministic_format,
    _prioritized_evidence_index,
    _query_relevance_issues,
    _s6_first_pass_quality_contract,
    _dedupe_capability_title,
    _winning_step_modes,
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


class _RealLikeScriptedProvider(ScriptedFakeProvider):
    """Exercise deterministic Codex gates without launching an external model."""


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
    assert len(direction["function"]) < 500
    assert len(gap["basis"]) < 500
    assert projected["effect_chain"][0].endswith("…")


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
    assert any("现役装备升级" in issue for issue in issues)
    assert any("机制高度重复" in issue for issue in issues)


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

    assert direction["name"] == "现役舰载火控系统目标捕获升级"
    assert 300 <= len(direction["capability_portrait"]) <= 600
    assert "Agent" not in direction["capability_portrait"]
    assert "S6" not in direction["capability_portrait"]


def test_s6_local_normalization_never_cuts_portrait_mid_sentence() -> None:
    complete_sentence = "该方向通过多源探测、目标识别和火力分配形成闭环，并在强干扰条件下保持拦截与再打击能力。"
    partial_sentence = "最后在受扰演练中继续验证目标保持率、火力任务送达率和毁伤闭合率"
    result = {
        "concept_directions": [
            {
                "name": "目标猎获与火力协同能力",
                "type": "new_capability",
                "capability_portrait": complete_sentence * 14 + partial_sentence,
            }
        ]
    }

    normalized = _normalize_s6_deterministic_format(result)
    portrait = normalized["concept_directions"][0]["capability_portrait"]

    assert len(portrait) <= 600
    assert portrait.endswith("。")
    assert partial_sentence not in portrait


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

    assert (
        normalized["concept_directions"][0]["name"]
        == "现役野战防空火力能力升级"
    )


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

    assert normalized["concept_directions"][0]["name"] == "现役有人驾驶装甲工兵破障车突防升级"
    assert normalized["concept_directions"][1]["name"] == "现役野战近程防空分队低空拦截升级"


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
    assert title == "现役弹炮结合防空系统低空拦截升级"
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
    assert direction["name"] == "现役MADIS/L-MADIS低空拦截升级"
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
    assert any("至少4项必须形成直接作战效应" in issue for issue in issues)
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


def test_s6_quality_gate_requires_unmanned_and_lethal_weapon_portfolio() -> None:
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
    assert any("无人作战装备方向" in issue for issue in issues)
    assert any("杀伤/反杀伤武器装备方向" in issue for issue in issues)

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
    assert any("4个相互区分的直接武器" in issue for issue in two_direct_issues)

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
    assert any(
        "独立导弹或精确制导弹药方向" in issue
        for issue in false_positive_issues
    )


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
    assert names[1].endswith("升级")
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
        == "反辐射巡飞弹猎杀"
    )


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


def test_s6_first_pass_contract_frontloads_query_led_missile_preflight() -> None:
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
    assert contract["missile_precision_direction"]["preflight"]["ready"] is True
    assert "回收" in contract["portfolio"]["support_mission_exclusion"]
    assert "首次自检" in contract["portfolio"]["support_mission_exclusion"]
    assert contract["upgrade_direction"]["preflight"]["ready"] is True
    assert "MADIS/L-MADIS" in contract["upgrade_direction"]["preflight"]["candidate_equipment"]
    assert contract["portfolio"]["missile_and_unmanned_must_be_separate_cards"] is True
    assert contract["portfolio"]["minimum_direct_weapon_directions"] == 4
    assert contract["disruptive_dimension_use"]["internal_query_causal_lenses"] == "2..3"
    assert (
        contract["disruptive_dimension_use"][
            "minimum_natural_relationship_groups_in_portfolio"
        ]
        == 3
    )
    assert contract["preflight_acceptance"]["passed"] is True


def test_s6_quality_gate_requires_three_natural_disruptive_relationship_groups() -> None:
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
    assert any("至少需要3类与query因果相关" in issue for issue in shallow_issues)

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
    assert any("无人作战平台前置装备桶尚未ready" in issue for issue in issues)
    assert any("导弹/精确制导弹药前置装备桶尚未ready" in issue for issue in issues)


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

    def direction(name: str, portrait: str) -> dict:
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
            "operational_mechanism": "维持侦察、指挥与火力打击协同",
            "development_path": "近期升级—中期集成—验证闸门",
            "future_trigger": "未来强电磁压制与低成本饱和手段常态化",
            "adversary_adaptation": "对手转向诱饵、多点压制和节点毁伤",
            "failure_boundary": "平台能源、接口或时延无法维持任务闭环时失效",
            "query_relevance": "对应当前query中的强干扰任务阶段、目标识别压力和火力打击续接需求",
            "baseline_system": f"现役或类比{name}装备基线",
            "capability_gap": f"{name}在强干扰条件下缺少独立的目标猎获、火力协同与毁伤闭合能力",
            "capability_portrait": portrait,
            "confidence": 0.8,
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
        return (
            f"{subject}面向强干扰条件下侦察预警到火力打击阶段的任务链断点，形成具体装备对象与任务系统能力。"
            f"核心通过{mechanism}改变单点失效传播，在对手实施诱饵、电子压制和节点毁伤时维持目标识别、"
            "指挥决策、火力分配与毁伤评估闭环，从而提升防御性打击、反制、拒止和持续作战效果。"
            "相对现役基线，新增机制不是堆叠通用算力，而是把传感、决策、效应和保障重构为可替换功能；"
            "近期以模块化改装或原理样机验证，中期进入跨平台体系集成。未来触发条件是强电磁与低成本饱和"
            "手段常态化；若平台能源、接口余量或时延无法支撑最低任务闭环则失效，并以任务闭环恢复时间、"
            "受扰目标航迹连续率和火力任务续接率进行证伪。该方向还必须面对对手转用多点压制、伪目标和"
            "分布式机动的反适应，通过任务级演训决定继续升级现役系统还是转入新型装备研制。"
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
                ),
                direction(
                    "分布式远域目标猎歼无人机系统",
                    valid_portrait("远域无人机系统", "多源跟踪与分布式效应协同"),
                ),
                direction(
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
                ),
                direction(
                    "低空反无人分层拦截弹猎歼系统",
                    valid_portrait(
                        "反无人拦截系统",
                        "多源低空探测、成本感知火力分配与连续拦截",
                    ),
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
                    *[
                        direction(f"方向{index}", "过短")
                        for index in range(1, 4)
                    ],
                    direction(
                        "长航时巡飞弹蜂群搜索压制毁伤系统",
                        valid_portrait(
                            "巡飞弹蜂群系统",
                            "长航时待机、多目标分配与搜索压制毁伤协同",
                        ),
                    ),
                    direction(
                        "低空反无人分层拦截弹猎歼系统",
                        valid_portrait(
                            "反无人拦截系统",
                            "多源低空探测、成本感知火力分配与连续拦截",
                        ),
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


def test_s6_low_combat_value_repairs_only_target_cards_without_rerunning_upstream(
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
                "S6最终方向中至少2项必须是直接作战效应方向，不能全部收敛为通信、保障、恢复或治理升级"
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
    repair_payload = next(
        payload
        for _, phase, payload in calls
        if phase == "winning_s6_card_repair"
    )
    assert "current_result" not in repair_payload
    assert repair_payload["repair_targets"]
    assert set(repair_payload) == {
        "query",
        "branch",
            "analysis_priority",
            "capability_synthesis_handoff",
            "first_pass_quality_contract",
            "repair_targets",
        "protected_cards",
        "repair_issues",
        "valid_evidence_ids",
    }


def test_s6_never_spends_a_second_model_repair_in_later_middle_cycle(
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
            "S6第1项仍缺少与query契合的独立导弹方向"
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
    result = asyncio.run(
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
    assert result["s6_quality_gate_failed"] is True


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
    batches = [
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
    scoped_merge_inputs: list[tuple[str, list[str], list[str]]] = []

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        nonlocal seed_index
        del system, output_schema, max_output_tokens
        task = payload["specialist_task"]
        mission_node = task["merge_target"]
        if phase == "winning_swarm_dynamic_seed":
            seed_index += 1
            if agent_id.endswith("disruptive_mechanism_generator"):
                await asyncio.sleep(0.01)
            elif agent_id.endswith("adversary_counter_adaptation_red_team"):
                await asyncio.sleep(0.08)
            marker = f"branch_token_{seed_index}_{agent_id}"
            return json.dumps(
                {
                    "hypotheses": [
                        {
                            "title": f"title_{marker}",
                            "nearest_public_baseline": f"baseline-{marker}",
                            "changed_confrontation_variable": f"variable_{marker}",
                            "mechanism_chain": [f"mechanism_{marker}"],
                            "direct_military_effects": [f"effect_{marker}"],
                            "equipment_forms": [f"自主无人战斗平台-{marker}"],
                            "novelty_delta": f"delta-{marker}",
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
                    "mission_graph_target_instances": 12,
                    "max_concurrency": 6,
                },
            },
            "coverage": {},
            "packets": [{"packet_id": "packet-1", "agent_id": "weapon_equipment"}],
            "evidence_index": [{"evidence_id": "ev-1"}],
        }
    )

    swarm = result["winning_swarm"]
    assert 12 <= len(swarm["task_graph"]) <= 16
    assert any(
        row.get("event_type") == "winning_agent_instance_recruited"
        for row in progress_rows
    )
    assert swarm["budget"]["maximum_observed_concurrency"] <= 6
    assert 5 <= len(swarm["final_equipment_portfolio"]) <= 7
    assert swarm["portfolio_quality_gate"]["passed"] is True
    assert swarm["portfolio_quality_gate"]["direct_combat_equipment_count"] >= 4
    assert all(
        row[1] == row[2]
        for row in scoped_merge_inputs
        if row[0] in {"S4", "S5"}
    )
    assert all(
        len(row[1]) == 1
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
    first_s4 = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_started"
        and row.get("mission_node") == "S4"
    )
    slow_s3 = next(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_completed"
        and row.get("agent_id") == slow_s3_id
    )
    assert fast_s3 < first_s4 < slow_s3


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
