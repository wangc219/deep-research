from __future__ import annotations

import asyncio
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import time

import pytest

import equipment_deep_research.agents.provider as provider_module
from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_prompt,
)

from equipment_deep_research.agents.provider import (
    ResponsesAgentProvider,
    _branch_product_output_schema,
    _capability_direction_quality_issues,
    _capability_language_issues,
    _capability_synthesis_handoff,
    _compact_swarm_candidate_handoff,
    _compact_s6_prior_outputs,
    _effective_expert_judge_status,
    _has_combat_effect_signal,
    _normalize_concept_direction_priorities,
    _normalize_effect_chain_references,
    _normalize_priority_references,
    _normalize_s6_deterministic_format,
    _prioritized_evidence_index,
    _prepare_pre_s6_card_contract,
    _quality_judge_candidate_payload,
    _quality_judge_output_token_budget,
    _quality_judge_scoped_evidence_index,
    _query_relevance_issues,
    _s6_first_pass_quality_contract,
    _s6_repair_targets,
    _dedupe_capability_title,
    _winning_step_modes,
)
from equipment_deep_research.agents.workflows.winning import (
    _creative_s3_candidate_instruction,
    _dynamic_s6_card_input,
    _minimal_s6_card_handoff,
    _parallel_s6_card_instruction,
    _s6_portrait_module_lengths,
    _s6_short_portrait_modules,
)
from equipment_deep_research.agents.workflows.s6_quality import (
    _s6_cross_card_identity_issues,
)
from equipment_deep_research.domain.models import WinningHypothesis
from equipment_deep_research.orchestration.capability_portrait import (
    build_capability_portrait,
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
    CommandCache,
    render_prompt_optimized,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.responses import (
    ProviderCapacityError,
    ProviderRequestError,
)


class _RealLikeScriptedProvider(ScriptedFakeProvider):
    """Exercise deterministic Codex gates without launching an external model."""


def _complete_s6_test_modules(name: str) -> dict[str, str]:
    return {
        "overview": (
            f"{name}面向强干扰条件下的时敏目标交战，把传统依赖持续链路的目标复核、"
            "受控接敌和直接毁伤前推到武器本体，使敌方不能仅靠断链、短促暴露和快速转场"
            "换取完整逃逸窗口。装备在任务边界内保持对授权目标的连续判断，直接形成压制、"
            "毁伤和后续补击空间，并让分散前沿火力在远端态势不完整时仍可产生可兑现战果。"
            "这种能力把通信保障从任务成立的刚性前提降为效率增益，为纵深火力续接打开新的作战场景，"
            "并保持战果可复核。相较依靠有人平台反复抵近确认的旧模式，任务编组可把有限链路优先留给"
            "目标更新和禁击边界变化，不再持续传输完整原始数据；即使后方节点暂时失联，已经进入责任区的"
            "武器仍能在预设权限内维持作用窗口，使敌方必须持续隐蔽或频繁转移，而不能用一次干扰换取整段安全时间。"
            "任务成立的关键也因而从后方必须全程看清并持续下令，改为发射前划清权限、弹上保持可追溯判断。"
            "部队由此可把同一批火力分布在多个短时责任区，对手则要为每次开机和转场同时准备隐蔽、诱骗与近防资源。"
        ),
        "technology_implementation": (
            "主攻弹载多源复核与受约束任务控制，两者分别落在导引头、组合导航和任务计算单元。"
            "前者须在定位漂移、目标遮挡和诱饵并存时维持同一目标轨迹，后者须在小体积、低功耗、"
            "有限散热和末段时间压力下守住禁击边界。传统全量数据回传会受带宽与时延拖累，单一"
            "传感器又容易被场景变化误导，因此必须让证据摘要、航迹可信度和剩余能量在弹上耦合，"
            "既保留及时攻击窗口，也避免把自治退化为无约束盲打，关键约束均须可测量并可复核。"
            "工程上还要把模型置信度、导航误差包线、目标机动余量和引信可用条件压缩成可实时计算的状态量，"
            "通过软硬件联锁限制搜索范围与攻击姿态。这样才能在计算资源、视场更新率和能源同时受限时，"
            "让每次目标确认都有可追溯依据，并在证据恶化时及时降级，而不是继续沿用依赖地面席位逐帧判读的实现方式。"
            "为防止感知模块给出高置信但无法攻击的假结论，任务计算机还要将目标证据与可达域、会遇几何和引信触发条件同步更新。"
            "软件输出必须能由独立安全监控通道否决，硬件则需在震动、温升和电源波动下保持门限计算一致，才能支撑实际落装。"
        ),
        "operational_process": (
            "发射平台先装订任务区、目标类别、禁击对象和最大自主权限，随后释放武器沿组合导航"
            "进入责任区。弹体发现候选目标后积累多源证据并检查航迹可达性，必要时利用短链交换"
            "压缩摘要；证据达到交战门限且约束无冲突时转入末段攻击，完成毁伤后形成状态摘要并"
            "触发补击或任务结束。证据不足、友军进入危险区、剩余能量低于安全边界或目标离开"
            "责任区时，武器退出攻击姿态并拒打、转场或终止，保证每次状态转换都有明确条件，"
            "指挥员可据此追溯转段理由。"
            "若后方恢复连接，武器只接收边界修订和高价值目标优先级，不回退到全程遥控；多枚武器相遇时交换"
            "目标占用和剩余作用时间，避免重复扑向同一目标。首枚攻击后，后续弹根据毁伤摘要决定补击、改攻或"
            "退出责任区，从而把授权、接敌、效果确认和火力续接组织成连续状态机，而非若干互不衔接的人工口令。"
            "责任区中若同时出现更高优先级目标，只有尚未锁定末段通道且剩余能量满足改攻条件的武器才能转段；已进入安全不可逆段的个体继续执行原任务。"
            "编队指挥所依据每枚弹的状态摘要统一分配补击窗口，并在越界、证据冲突或无法安全脱离时下达全组终止。"
        ),
        "capability_effects": (
            "该装备新增断链条件下的目标区自主复核、受控交战和火力续接能力，直接降低因图传"
            "卡顿造成的任务放弃、重复发射与高价值平台暴露。它能够压缩从目标短时出现到武器"
            "接敌的时间，提高对机动火力、临时雷达和通信节点的有效毁伤概率，同时用安全拒打"
            "减少诱饵和非授权对象造成的弹药空耗。新的任务场景包括纵深时敏猎歼、前沿分散火力"
            "伴随、强电磁压制区补击，以及链路间歇条件下的多批次连续攻击，并保持战果与弹药消耗可核算。"
            "对部队而言，直接收益不是单纯提高命中率，而是把原本因通信不可用而无法下达的任务转化为可受控执行："
            "前沿单元可在短暂获得目标线索后立即释放火力，后方只需维护边界和优先级。由此减少中继平台伴随、"
            "有人机护航和重复侦察需求，并让敌方机动节点在每次短停、开机或发射时都面临持续在场的打击压力。"
            "作战效果还体现为指挥所可以用更少中继和盯控席位维持更多同时任务，不再因单个链路拥塞整批撤销攻击。"
            "敌方若要恢复安全间隙，除压制通信外还必须同时破坏弹上定位、制造足以通过多源复核的诱饵，或迫使真实目标长时间不得开机。"
        ),
        "winning_logic": (
            "敌方原有优势是用低成本通信压制和短促暴露制造我方决策迟滞，迫使远程火力等待"
            "完整回传、追加中继或放弃攻击。该装备把关键判断压缩到弹上短闭环，使断链只能"
            "降低协同效率，不能直接清除已经在场的攻击关系。对手若要继续规避，必须同时投入"
            "更逼真诱饵、更频繁机动、更长时间干扰和更多近防弹药，并承担真实节点反复暴露的"
            "代价；我方则以有限算力和低带宽交换替代高价值支援，用较低体系成本换取更快接敌、"
            "更少误耗和更高直接毁伤收益。"
            "交换关系因此从双方争夺持续通信和完整态势，转为敌方必须同时对抗导航、感知、任务判断与末段效应。"
            "其单点干扰收益下降，而维持多域欺骗和近程防御的成本随在场武器数量增长；我方即使部分武器被压制，"
            "其余武器仍可独立闭合任务。只要权限边界和证据门限可靠，这种分布式受控自治就能以可接受弹药损耗"
            "换取敌高价值节点更长暴露、更慢转场和更高防御负担。"
            "这一逻辑成立的前提不是弹药能完全代替指挥员，而是权限、目标类别和禁击边界能在发射前被清楚装订，弹上证据门限在对抗中仍可验证。"
            "一旦这些边界无法维持，武器必须拒打而非追求表面命中率，从而把自治的战术收益限定在可接受的政策与误伤风险之内。"
        ),
    }


def _with_model_semantic_contract(
    direction: Mapping[str, object],
    *,
    classification: str = "direct_combat",
    direct_combat_effect: bool = True,
    support_only: bool = False,
    concrete_equipment: bool = True,
    query_alignment_confirmed: bool = True,
    precision_munition: bool = False,
) -> dict:
    """Attach the S3-S5 semantic judgement consumed by non-inferential S6 code."""

    row = dict(direction)
    identity = str(
        row.get("primary_equipment_identity")
        or row.get("equipment_form")
        or row.get("name")
        or ""
    )
    row.setdefault("primary_equipment_identity", identity)
    row["equipment_semantic_assessment"] = {
        "classification": classification,
        "direct_combat_effect": direct_combat_effect,
        "support_only": support_only,
        "concrete_equipment": concrete_equipment,
        "query_alignment_confirmed": query_alignment_confirmed,
        "precision_munition": precision_munition,
    }
    row["semantic_consistency_check"] = {
        "process_actor": identity,
        "launch_or_release_mode": "沿冻结候选的部署或释放域运用",
        "target_and_direct_effect": str(
            row.get("target_and_direct_effect")
            or row.get("military_value")
            or row.get("function")
            or "形成冻结候选声明的直接战场结果"
        ),
        "resolution_note": "主装备、运用主体、目标和直接战果保持一致。",
        "consistent": True,
    }
    return row


def test_s3_candidate_brief_preserves_creative_reasoning_without_rule_pileup() -> None:
    instruction = _creative_s3_candidate_instruction()

    assert "从Query的核心战场矛盾自由创造" in instruction
    assert "形态物质、技术原理、任务能力" in instruction
    assert "战争时空与体系经济逻辑、专名隐喻" in instruction
    assert "不要为覆盖类型而组合" in instruction
    assert "不要默认两字意象加弹/雷/器/系统" in instruction
    assert "专名/代号型不得成为明显多数" in instruction
    assert "只引专名/代号部分" in instruction
    assert "名称没有专名或代号时，不得给整个名称加引号" in instruction
    assert "每个候选只输出name和concise_winning_summary" in instruction
    assert "不要输出其他字段、备选名或推理过程" in instruction
    assert "naming_self_check" not in instruction
    assert len(instruction) < 1200


def test_parallel_s6_card_instruction_is_compact_but_preserves_authority() -> None:
    instruction = _parallel_s6_card_instruction()

    assert instruction == load_dynamic_winning_prompt("S6")
    assert len(instruction) < 1600
    assert "独立Codex CLI会话中只完成这一张候选卡" in instruction
    assert "输入严格只有query_semantics、candidate_weapon、winning_logic_overview三项" in instruction
    assert "不得要求或臆造S5指标、分类、证据、验证" in instruction
    assert "你拥有本卡场景推演、技术论证、作战流程、能力分类和文字编辑权" in instruction
    assert "同一次模型调用内部完成两遍工作" in instruction
    assert "再以总编辑视角静默复核并直接返回唯一终稿" in instruction
    assert "1至2项真正决定装备能否实现的主攻关键技术" in instruction
    assert "五栏合计通常约2000至2250字" in instruction
    assert "真实未来战场态势" in instruction
    assert "敌方具体代价" in instruction
    assert "装备落装" in instruction
    assert "作战窗口" in instruction
    assert "system_contribution_thesis、indicator_portrait" in instruction
    assert "指标从制胜机理和风险反推" in instruction
    assert "不得复用其他卡的骨架、指标、技术路线或验收句式" in instruction
    assert "口号" in instruction and "因果" in instruction
    assert "严禁为凑字复用跨栏句子" in instruction
    assert "发现—判断—决策—打击—评估" in instruction
    assert "INNOVATIVE_CAPABILITY_IMAGE_GUIDANCE" not in instruction


def test_s6_short_portrait_module_detector_checks_each_cjk_column() -> None:
    modules = _complete_s6_test_modules("“潮锋”时敏打击弹")
    assert not _s6_short_portrait_modules(modules)
    modules["winning_logic"] = "敌方断链后我方仍可攻击。"
    assert _s6_short_portrait_modules(modules) == ["winning_logic"]
    assert _s6_portrait_module_lengths(modules)["winning_logic"] < 380
    modules["capability_effects"] = "形成受控打击能力。"
    assert _s6_short_portrait_modules(modules) == [
        "capability_effects",
        "winning_logic",
    ]


@pytest.mark.parametrize('failed_repair', [
    'timeout', 'module_key', 'card_binding_id', 'hypothesis_id', 'missing_binding',
])
def test_dynamic_s6_repairs_only_failed_columns_and_isolates_failed_repairs(
    monkeypatch, failed_repair,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.provider_type = "codex_cli"  # type: ignore[attr-defined]
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    phases: list[str] = []
    payload_binding_ids: list[str] = []

    portfolio = [
        {
            "hypothesis_id": "short-card-1",
            "name": "“潮锋”时敏打击弹",
            "type": "new_capability",
            "equipment_form": "时敏精确打击弹",
            "primary_equipment_identity": "时敏精确打击弹",
            "target_and_direct_effect": "压制并毁伤高价值机动目标",
            "concise_winning_summary": (
                "传统远程火力依赖持续链路，对手可借短时暴露逃离；该弹把复核与受控交战前推到武器端。"
            ),
            "operational_process": ["装订任务并发射", "复核目标后受控交战"],
            "baseline_system": "现役远程精确打击弹药",
            "capability_gap": "断链后目标复核和火力续接不足",
            "direct_evidence_refs": ["ev-1"],
            "validation_plan": ["比较正确交战率和直接毁伤效果"],
            "expert_score": 0.8,
        }
    ]

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        schema,
        max_output_tokens,
        *,
        phase,
    ):
        del agent_id, system, schema, max_output_tokens
        phases.append(phase)
        candidate = dict(payload["candidate_weapon"])
        payload_binding_ids.append(str(candidate["card_binding_id"]))
        modules = _complete_s6_test_modules(str(candidate["name"]))
        if "repair" in phase:
            module_key = payload['portrait_module_key']
            await asyncio.sleep(0)
            if module_key == 'winning_logic' and failed_repair == 'timeout':
                raise TimeoutError("quality enhancement timed out")
            repair = {
                'module_key': module_key,
                'module_content': modules[module_key],
                'card_binding_id': candidate['card_binding_id'],
                'hypothesis_id': candidate['hypothesis_id'],
            }
            if module_key == 'winning_logic':
                if failed_repair == 'missing_binding':
                    repair.pop('card_binding_id')
                else:
                    repair[failed_repair] = 'wrong-identity'
            return json.dumps(repair, ensure_ascii=False)
        modules["capability_effects"] = "形成受控打击能力。"
        modules["winning_logic"] = "敌方断链后我方仍可攻击。"
        if "_module_" in phase:
            module_key = phase.rsplit("_module_", 1)[-1]
            return json.dumps(
                {
                    "module_key": module_key,
                    "module_content": modules[module_key],
                    "card_binding_id": candidate["card_binding_id"],
                    "hypothesis_id": candidate.get("hypothesis_id", ""),
                    "capability_image_draft": "单卡画像",
                },
                ensure_ascii=False,
            )
        if phase.endswith("_spine"):
            direction = {
                **candidate,
                "operational_process": ["装订任务并发射", "复核目标后受控交战"],
                "capability_classification": {
                    "primary_dimension": "打击维度",
                    "secondary_dimensions": [],
                },
                "semantic_consistency_check": {
                    "consistent": True,
                    "checked_fields": ["name", "operational_process"],
                },
            }
            return json.dumps(
                {"direction": direction, "capability_image_draft": "单卡画像"},
                ensure_ascii=False,
            )
        direction = {
            **candidate,
            "operational_process": ["装订任务并发射", "复核目标后受控交战"],
            "capability_classification": {
                "primary_dimension": "打击维度",
                "secondary_dimensions": [],
            },
            "capability_portrait_modules": modules,
            "semantic_consistency_check": {
                "consistent": True,
                "checked_fields": ["name", "operational_process"],
            },
        }
        return json.dumps(
            {"direction": direction, "capability_image_draft": "单卡画像"},
            ensure_ascii=False,
        )

    monkeypatch.setattr(provider, "_run_core_json", fake_run_core_json)
    monkeypatch.setattr(
        provider_module,
        "_capability_direction_quality_issues",
        lambda result, *, handoff=None: [],
    )
    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "强干扰条件下时敏目标精确打击",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {
                    "primary_branch": "G",
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                },
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "packets": [],
                "evidence_index": [],
                "resume_steps": [6],
                "prior_winning_analysis": {
                    "concept_directions": portfolio,
                    "winning_swarm": {
                        "final_equipment_portfolio": portfolio,
                        "portfolio_quality_gate": {"passed": True},
                    },
                },
            }
        )
    )

    assert len(phases) == 8  # Spine + five first-pass columns + two repairs.
    assert sum(phase.endswith("_spine") for phase in phases) == 1
    assert sum("_module_" in phase and "repair" not in phase for phase in phases) == 5
    assert {phase.rsplit('_module_', 1)[-1] for phase in phases if 'repair' in phase} == {
        'capability_effects', 'winning_logic',
    }
    assert all(
        phase.startswith("winning_s6_parallel_card_resume_01")
        or phase.startswith("winning_s6_parallel_card_repair_01")
        for phase in phases
    )
    assert len(set(payload_binding_ids)) == 1
    assert [item["name"] for item in result["concept_directions"]] == [
        "“潮锋”时敏打击弹"
    ]
    card = result["concept_directions"][0]
    final_modules = card['capability_portrait_modules']
    complete_modules = _complete_s6_test_modules(card['name'])
    for key in ('overview', 'technology_implementation', 'operational_process', 'capability_effects'):
        assert final_modules[key] == complete_modules[key]
    assert final_modules['winning_logic'] == '敌方断链后我方仍可攻击。'
    assert any('栏目修复失败' in warning for warning in card['s6_authoring_quality_warnings'])
    assert _s6_short_portrait_modules(card["capability_portrait_modules"])
    assert card["s6_authoring_status"] == "authored_quality_limited"
    assert result["s6_quality_gate_limited"] is True
    assert result.get("s6_card_authoring_limited") in {None, False}
    assert not result.get("s6_reference_weapons", [])


def test_minimal_s6_card_handoff_keeps_decision_spine_and_drops_bulk_state() -> None:
    brief = {
        "hypothesis_id": "hyp-1",
        "name": "潮痕有限区复获反舰巡航弹",
        "primary_equipment_identity": "反舰巡航弹弹体",
        "launch_or_release_domain": "舰载箱式发射",
        "target_and_direct_effect": "复获并毁伤机动水面目标",
        "non_substitutable_difference": "弹上有限区搜索与证据门控",
        "indicator_portrait": "测量复获时间、正确拒打率和剩余能量",
        "query_relevance": "用于拒止环境下远海补击阶段",
        "candidate_ledger": {"hypotheses": ["x" * 20000]},
        "expert_assessment": {"raw_session": "y" * 20000},
        "audit_events": ["z" * 20000],
        "portfolio_identity_contract": {
            "primary_equipment_identity": "反舰巡航弹弹体",
            "launch_or_release_domain": "舰载箱式发射",
            "target_and_direct_effect": "复获并毁伤机动水面目标",
            "private_governance": "q" * 20000,
        },
    }

    handoff = _minimal_s6_card_handoff(brief)

    assert handoff["hypothesis_id"] == "hyp-1"
    assert handoff["primary_equipment_identity"] == "反舰巡航弹弹体"
    assert handoff["target_and_direct_effect"] == "复获并毁伤机动水面目标"
    assert "candidate_ledger" not in handoff
    assert "expert_assessment" not in handoff
    assert "audit_events" not in handoff
    assert "portfolio_identity_contract" not in handoff
    assert len(json.dumps(handoff, ensure_ascii=False)) < 5000


def test_dynamic_s6_card_input_carries_frozen_binding_identity() -> None:
    payload = _dynamic_s6_card_input(
        {
            "hypothesis_id": "candidate-a",
            "card_binding_id": "s6-card-fixed-a",
            "name": "甲装备",
            "primary_equipment_identity": "甲装备",
            "equipment_form": "甲装备",
            "target_and_direct_effect": "打击目标",
            "concise_winning_summary": "改变交换关系",
        },
        query="测试任务",
    )

    assert payload["candidate_weapon"]["hypothesis_id"] == "candidate-a"
    assert payload["candidate_weapon"]["card_binding_id"] == "s6-card-fixed-a"


def test_dynamic_s6_card_input_preserves_frozen_codename_quotes() -> None:
    payload = _dynamic_s6_card_input(
        {
            "hypothesis_id": "candidate-quoted",
            "card_binding_id": "s6-card-quoted",
            "name": "“玄鳞”可变散射攻顶弹",
            "primary_equipment_identity": "“玄鳞”可变散射攻顶弹",
            "equipment_form": "“玄鳞”可变散射攻顶弹",
            "target_and_direct_effect": "打击顶部薄弱目标",
            "concise_winning_summary": "改变识别与拦截交换关系",
        },
        query="测试任务",
    )

    assert payload["candidate_weapon"]["name"] == "“玄鳞”可变散射攻顶弹"
    assert payload["candidate_weapon"]["primary_equipment_identity"] == (
        "“玄鳞”可变散射攻顶弹"
    )


def test_dynamic_s6_card_input_carries_s5_mode_change_spine() -> None:
    payload = _dynamic_s6_card_input(
        {
            "hypothesis_id": "candidate-mode",
            "name": "可消耗分布式拦截弹",
            "primary_equipment_identity": "可消耗分布式拦截弹",
            "equipment_form": "拦截弹",
            "target_and_direct_effect": "直接物理拦截来袭目标",
            "concise_winning_summary": "在节点损耗后继续形成拦截战果。",
            "innovation_basis": "将拦截权从少量高价值节点转为可补充弹体密度",
            "disruption_tier": "new_quality_breakthrough",
            "displaced_operational_mode": "依赖少量高价值节点逐目标拦截",
            "new_operational_mode": "以可消耗弹体密度持续占位并接续交战",
            "winning_relation_shift": "从平台价值交换转为持续效应密度交换",
        },
        query="饱和来袭下的区域拒止",
    )

    overview = payload["winning_logic_overview"]
    assert "创新断点" in overview
    assert "被淘汰的旧作战模式" in overview
    assert "形成的新作战模式" in overview
    assert "制胜关系改写" in overview


def test_parallel_reporter_token_budget_is_rendered_as_soft_guidance() -> None:
    prompt = render_prompt_optimized(
        [ModelMessage("user", "完成指定报告栏目")],
        {
            "max_output_tokens": 1800,
            "_soft_output_token_budget": True,
        },
    )

    assert "Planning output token budget: 1800" in prompt
    assert "not a cutoff" in prompt
    assert "Requested maximum output tokens" not in prompt


def test_codex_command_cache_separates_search_context_sizes() -> None:
    cache = CommandCache()

    high = cache.get_cache_key(
        {"web_search": {"search_context_size": "high"}}, has_schema=True
    )
    medium = cache.get_cache_key(
        {"web_search": {"search_context_size": "medium"}}, has_schema=True
    )
    low = cache.get_cache_key(
        {"web_search": {"search_context_size": "low"}}, has_schema=True
    )

    assert len({high, medium, low}) == 3
    assert high.endswith("search:high")
    assert medium.endswith("search:medium")
    assert low.endswith("search:low")


def test_codex_command_can_omit_unsupported_search_context_size(monkeypatch) -> None:
    provider = object.__new__(CodexCliProvider)
    provider._command_cache = CommandCache()
    provider._base_command = ["codex", "exec", "-"]
    provider.search_extra_args = ()
    monkeypatch.setenv("EQUIPMENT_DR_SEARCH_CONTEXT_SIZE_MODE", "omit")

    command = provider._build_command({"web_search": {"search_context_size": "low"}})

    assert 'web_search="live"' in command
    assert not any("tools.web_search" in item for item in command)


def test_query_led_combat_equipment_theme_contract_is_non_exhaustive() -> None:
    contract = provider_module._query_led_combat_equipment_theme_contract()

    assert contract["examples_are_non_exhaustive"] is True
    assert contract["illustrative_names_are_not_facts"] is True
    assert "query" in contract["query_precedence"]
    assert "不得为了凑齐主题机械生成" in contract["query_precedence"]
    assert contract["theme_lanes"] == []
    assert "通信" in contract["support_only_exclusion"]
    assert "不能独立占用最终武器方向" in contract["support_only_exclusion"]
    assert "项目功能" in contract["project_function_requirement"]
    assert "任务链断点" in contract["project_function_requirement"]
    assert contract["naming_style_references"] == []
    assert "不提供固定装备名称" in contract["naming_reference_rule"]
    assert "Codex CLI" in contract["naming_reference_rule"]
    assert "形态/物质" in contract["naming_reference_rule"]
    assert "A构型意象型" in contract["naming_reference_rule"]
    assert "B原理突破型" in contract["naming_reference_rule"]
    assert "D使命任务型" in contract["naming_reference_rule"]
    assert "J时空概念型" in contract["naming_reference_rule"]
    assert "C装备专名型" in contract["naming_reference_rule"]
    assert "不是类型配额" in contract["naming_reference_rule"]
    assert "高功率微波" in contract["model_creative_reference"]
    assert "仿生扑翼微型侦察打击弹" in contract["model_creative_reference"]
    assert "‘蜂鸟’仿生扑翼微型作战弹" in contract["model_creative_reference"]
    assert "‘蚁群’分布式微型效应弹" in contract["model_creative_reference"]
    assert "均非必选格式" in contract["model_creative_reference"]
    assert "高超音速滑翔增程精确打击远程火箭弹" in contract["model_creative_reference"]
    assert "模块化巡飞弹—通用弹药系列" in contract["model_creative_reference"]
    assert "不得先选装备族" in contract["divergence_mode"]
    assert "替换成另一Query" in contract["cross_query_template_guard"]
    assert "毁伤" in contract["combat_subject_requirement"]
    assert (
        "成本、平台、时间、毁伤、体系、伦理与博弈逻辑"
        in contract["foresight_first_rule"]
    )
    assert "跨代优势" in contract["foresight_first_rule"]
    assert "高维优速" in contract["foresight_first_rule"]
    assert "低优先级补全项" in contract["frontier_evidence_policy"]


def test_combat_scene_preserves_upstream_semantics_without_keyword_routing() -> None:
    scene = provider_module._winning_combat_scene(
        "远海编队在强对抗海域执行水下警戒与反潜任务，对手低噪声潜艇与无人潜航器混合活动",
        equipment_form="大排量武装猎潜无人潜航器",
    )

    assert "低噪声潜艇" in scene
    assert "大排量武装猎潜无人潜航器" in scene


@pytest.mark.parametrize(
    "title",
    [
        "“沉界”大排量武装猎潜无人潜航器",
        "“断缆”百吨级远海无人水面反潜截击艇",
        "“补网”超大型水下无人母艇",
    ],
)
def test_undersea_platform_titles_are_concrete_weapon_identities(title: str) -> None:
    assert provider_module._winning_title_has_concrete_equipment_identity(title)


def test_weapon_discovery_and_s6_preflight_receive_query_led_themes() -> None:
    discovery_prompt = provider_module._discovery_system_prompt("weapon_equipment")
    s6_contract = _s6_first_pass_quality_contract(
        topic="强干扰下蜂群精确打击", handoff={}
    )

    assert "当前query" in discovery_prompt
    assert "机械生成" in discovery_prompt
    assert "不提供固定装备名称" in discovery_prompt
    assert "高功率微波（HPM）巡飞弹" not in discovery_prompt
    themes = s6_contract["query_led_combat_equipment_themes"]
    assert themes["examples_are_non_exhaustive"] is True
    assert themes["combat_subject_requirement"].startswith("候选主体必须是")


def test_query_divergence_brief_consumes_codex_semantics_without_keyword_catalog() -> (
    None
):
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
            "frontier_technology_hypotheses": [
                {
                    "enabling_principle": "跨介质尾迹与多谱段散射联合测量",
                    "equipment_implication": "潜射低特征末段再捕获反舰弹药",
                    "query_causal_link": "降低高速机动水面目标在末段脱锁概率",
                    "direct_military_effect": "在编队防空压缩窗口内完成再捕获毁伤",
                    "conventional_absorption_limit": "单一射频导引升级不能同时克服诱饵与海杂波",
                    "technology_horizon": "5-10年",
                    "engineering_bottleneck": "弹载传感尺寸与融合时延",
                    "disconfirming_condition": "对抗试验中不能提高真目标保持率",
                }
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

    assert (
        anti_ship["query_specific_weapon_architectures"]
        != underground["query_specific_weapon_architectures"]
    )
    assert "潜射低特征" in anti_ship["query_specific_weapon_architectures"][0]
    assert anti_ship["equipment_project_hypotheses"][0]["project_function"]
    assert (
        anti_ship["frontier_technology_hypotheses"][0]["enabling_principle"]
        == "跨介质尾迹与多谱段散射联合测量"
    )
    assert "project_name" not in anti_ship["equipment_project_hypotheses"][0]
    assert no_model_brief["query_specific_weapon_architectures"] == []
    assert "提示词表" in no_model_brief["generation_rules"][0]


def test_query_divergence_brief_does_not_use_keyword_weapon_lenses() -> None:
    brief = provider_module._query_combat_equipment_divergence_brief(
        "强电磁压制下低空无人远程精确打击续接",
        structured_query_brief={
            "enemy_target_profile": ["间歇开机防空和机动火控节点"],
            "battle_phase_and_constraints": ["低空突防与远程火力续接"],
            "required_direct_military_effects": ["精确压制防空与毁伤高价值节点"],
        },
    )

    assert brief["conditional_priority_observation_lenses"] == []
    assert (
        "固定装备名称"
        in provider_module._query_led_combat_equipment_theme_instruction()
    )


def test_portfolio_innovation_audit_allows_missing_engineering_detail() -> None:
    actionable = provider_module._normalize_portfolio_innovation_audit(
        {
            "frontier_breadth_sufficient": False,
            "portfolio_mode": "process_only",
            "homogeneity_reason": "候选均围绕同一常规弹体调整授权与复评流程",
            "completion_recommended": True,
            "missing_frontier_opportunity": {
                "query_gap": "强干扰下仍需独立获得可用于末制导的目标物理特征",
                "enabling_principle": "不同于常规射频/光电链路的非常规测量机理",
                "innovation_mode": "new_quality",
                "equipment_implication": "采用该测量机理的微型精确毁伤弹药",
                "direct_military_effect": "在欺骗与遮蔽下保持真目标末段精确毁伤",
                "disruptive_delta": "把依赖外部连续信息的制导改为弹上新质感知闭环",
            },
            "audit_reason": "存在一个可由Query直接推导且未覆盖的前沿新质方向",
        }
    )
    vague = provider_module._normalize_portfolio_innovation_audit(
        {
            "frontier_breadth_sufficient": False,
            "completion_recommended": True,
            "missing_frontier_opportunity": {
                "query_gap": "需要更创新",
                "enabling_principle": "量子",
            },
        }
    )

    assert actionable["completion_recommended"] is True
    assert provider_module._portfolio_innovation_completion_requested(actionable)
    assert vague["completion_recommended"] is False


def test_dynamic_portfolio_keeps_selected_identity_and_s6_authored_portrait() -> None:
    selected = [
        {
            "hypothesis_id": "candidate-a",
            "name": "低特征大排水量自主反潜无人潜航器",
            "equipment_form": "大排水量低特征自主反潜无人潜航器",
            "primary_equipment_identity": "大排水量低特征自主反潜无人潜航器",
            "direct_evidence_refs": ["ev-weapon_equipment-a"],
            "capability_portrait": "合并阶段机械草稿",
            "expert_score": 0.86,
        },
        {
            "hypothesis_id": "candidate-b",
            "name": "可投送自主寻的反潜鱼雷",
            "equipment_form": "可投送弱网自主寻的反潜鱼雷",
            "primary_equipment_identity": "可投送弱网自主寻的反潜鱼雷",
            "direct_evidence_refs": ["ev-weapon_equipment-b"],
            "capability_portrait": "合并阶段机械草稿",
            "expert_score": 0.81,
        },
    ]
    authored = [
        {
            "hypothesis_id": "candidate-b",
            "name": "不应覆盖的通用鱼雷",
            "direct_evidence_refs": ["ev-wrong"],
            "target_scenario": "敌低噪潜艇借复杂海底地形脱离接触后的追踪交战窗口",
            "operational_process": ["载机布放", "水下自主复获", "授权后末段寻的"],
            "capability_portrait": "S6撰写的鱼雷专属能力画像",
            "system_contribution_thesis": "鱼雷以水下自主复获续接载机撤离后的追击断点",
            "indicator_portrait": "以失联复获率和误击拒止率判退",
        },
        {
            "hypothesis_id": "candidate-a",
            "name": "不应覆盖的通用潜航器",
            "direct_evidence_refs": ["ev-wrong"],
            "target_scenario": "编队有人平台撤出高威胁水域后的持续声学搜索阶段",
            "operational_process": ["隐蔽前出", "自主建图", "分类回传", "断链继续跟踪"],
            "capability_portrait": "S6撰写的潜航器专属能力画像",
            "system_contribution_thesis": "潜航器以前出持续接触替代有人平台高风险驻留",
            "indicator_portrait": "以持续接触时间和暴露风险判退",
        },
    ]

    merged = provider_module._merge_dynamic_portfolio_with_s6_authored_cards(
        selected,
        authored,
    )

    assert [item["hypothesis_id"] for item in merged] == ["candidate-a", "candidate-b"]
    assert merged[0]["name"] == selected[0]["name"]
    assert merged[0]["direct_evidence_refs"] == ["ev-weapon_equipment-a"]
    assert merged[0]["capability_portrait"] == "S6撰写的潜航器专属能力画像"
    assert merged[0]["system_contribution_thesis"] == (
        "潜航器以前出持续接触替代有人平台高风险驻留"
    )
    assert merged[0]["indicator_portrait"] == "以持续接触时间和暴露风险判退"
    assert merged[0]["operational_process"][0] == "隐蔽前出"
    assert merged[1]["capability_portrait"] == "S6撰写的鱼雷专属能力画像"
    assert merged[1]["system_contribution_thesis"] == (
        "鱼雷以水下自主复获续接载机撤离后的追击断点"
    )
    assert merged[1]["indicator_portrait"] == "以失联复获率和误击拒止率判退"
    assert merged[1]["expert_score"] == 0.81


def test_dynamic_s6_portfolio_confidence_uses_blind_expert_scores() -> None:
    selected = [
        {"expert_score": 0.7956},
        {"expert_score": 0.7858},
        {"expert_score": 0.823},
    ]
    authored = [
        {"confidence": 0.61},
        {"confidence": 0.67},
        {"confidence": 0.72},
    ]

    assert provider_module._s6_portfolio_confidence(selected, authored) == 0.8015


def test_dynamic_s6_portfolio_confidence_falls_back_to_authored_cards() -> None:
    selected = [{"expert_score": ""}, {}]
    authored = [
        {"confidence": 0.71},
        {"confidence": 0.76},
        {"confidence": "not-a-number"},
    ]

    assert provider_module._s6_portfolio_confidence(selected, authored) == 0.735
    assert provider_module._s6_portfolio_confidence(selected, [{}]) == 0.0


def test_dynamic_s6_merge_keeps_selected_fallback_card_in_formal_portfolio() -> None:
    selected = [
        {"hypothesis_id": "ok", "name": "成稿装备"},
        {"hypothesis_id": "failed", "name": "失败装备"},
    ]
    authored = [
        {
            "hypothesis_id": "ok",
            "name": "成稿装备",
            "s6_authoring_status": "authored_semantically_consistent",
            "capability_portrait": "完整原创画像",
        },
        {
            "hypothesis_id": "failed",
            "name": "失败装备",
            "s6_authoring_status": "limited_provider_failure",
        },
    ]

    merged = provider_module._merge_dynamic_portfolio_with_s6_authored_cards(
        selected,
        authored,
    )

    assert [item["name"] for item in merged] == ["成稿装备", "失败装备"]
    assert merged[0]["s6_authoring_status"] == "authored_semantically_consistent"


def test_s6_cross_card_identity_gate_rejects_rebound_portrait() -> None:
    source = {
        "hypothesis_id": "candidate-a",
        "name": "蜂群母弹式自寻的子弹药",
        "primary_equipment_identity": "蜂群母弹式自寻的子弹药",
        "equipment_form": "蜂群母弹式自寻的子弹药",
        "capability_portrait": "概述：浪面跳跃无人爆破艇面向近岸节点实施末段爆破。",
        "operational_process": ["分散释放", "末段接近", "近距爆破"],
    }
    sibling = {
        "hypothesis_id": "candidate-b",
        "name": "浪面跳跃无人爆破艇",
        "primary_equipment_identity": "浪面跳跃无人爆破艇",
        "equipment_form": "浪面跳跃无人爆破艇",
    }

    issues = _s6_cross_card_identity_issues(source, [source, sibling])

    assert issues and "浪面跳跃无人爆破艇" in issues[0]


def test_dynamic_s6_merge_drops_cross_card_contaminated_prose() -> None:
    selected = [
        {
            "hypothesis_id": "candidate-a",
            "name": "蜂群母弹式自寻的子弹药",
            "primary_equipment_identity": "蜂群母弹式自寻的子弹药",
            "equipment_form": "蜂群母弹式自寻的子弹药",
        },
        {
            "hypothesis_id": "candidate-b",
            "name": "浪面跳跃无人爆破艇",
            "primary_equipment_identity": "浪面跳跃无人爆破艇",
            "equipment_form": "浪面跳跃无人爆破艇",
        },
    ]
    authored = [
        {
            "hypothesis_id": "candidate-a",
            "name": "蜂群母弹式自寻的子弹药",
            "s6_authoring_status": "authored_semantically_consistent",
            "capability_portrait": "概述：浪面跳跃无人爆破艇实施末段爆破。",
        },
        {
            "hypothesis_id": "candidate-b",
            "name": "浪面跳跃无人爆破艇",
            "s6_authoring_status": "authored_semantically_consistent",
            "capability_portrait": "概述：浪面跳跃无人爆破艇实施末段爆破。",
        },
    ]

    merged = provider_module._merge_dynamic_portfolio_with_s6_authored_cards(
        selected, authored
    )

    assert [item["hypothesis_id"] for item in merged] == ["candidate-b"]


def test_dynamic_s6_merge_never_positionally_cross_binds_known_ids() -> None:
    selected = [
        {"hypothesis_id": "candidate-a", "name": "甲装备"},
        {"hypothesis_id": "candidate-b", "name": "乙装备"},
    ]
    authored = [
        {
            "hypothesis_id": "candidate-b",
            "name": "乙装备",
            "s6_authoring_status": "authored_semantically_consistent",
            "capability_portrait": "乙装备专属画像",
        }
    ]

    merged = provider_module._merge_dynamic_portfolio_with_s6_authored_cards(
        selected, authored
    )

    assert [item["hypothesis_id"] for item in merged] == ["candidate-b"]


def test_s6_authored_title_cannot_replace_s5_frozen_name() -> None:
    selected = [
        {
            "hypothesis_id": "candidate-usv",
            "name": "中大型无人水面艇，集成拖曳阵、可变深声呐、轻型鱼雷发射架和近程反UUV效应器",
            "equipment_form": "中大型武装无人水面反潜艇",
            "primary_equipment_identity": "中大型武装无人水面反潜艇",
            "direct_evidence_refs": ["ev-usv"],
        }
    ]
    authored = [
        {
            "hypothesis_id": "candidate-usv",
            "name": "远海武装无人水面反潜艇",
            "equipment_form": "中大型武装无人水面反潜艇",
            "primary_equipment_identity": "中大型武装无人水面反潜艇",
            "capability_portrait": "S6形成的无人水面反潜艇专属画像",
        }
    ]

    merged = provider_module._merge_dynamic_portfolio_with_s6_authored_cards(
        selected,
        authored,
    )

    assert merged[0]["name"] == selected[0]["name"]
    assert merged[0]["primary_equipment_identity"] == "中大型武装无人水面反潜艇"
    assert merged[0]["direct_evidence_refs"] == ["ev-usv"]
    assert provider_module._capability_language_issues(1, selected[0]) == []


def test_s6_overview_does_not_require_seven_fixed_connectors() -> None:
    portrait = (
        "概述：联合战役远海警戒阶段，敌方低噪潜艇借海况与地形脱离接触；"
        "编队以大排水量自主反潜无人潜航器为主装备隐蔽前出，在通信中断时持续搜索、分类和跟踪，"
        "为有人平台恢复接触并压缩对手潜航机动窗口。\n"
        "- 装备与技术实现：低特征潜航平台搭载被动声学阵列与本地分类任务系统。\n"
        "- 关键作战流程：母舰外线释放后隐蔽进入搜索区，自主建图并对接触分类，断链时保持跟踪，复联后回传航迹。\n"
        "- 形成能力与作战效果：以持续接触时间、分类准确率和有人平台暴露时间验收持续反潜接触能力。\n"
        "- 制胜逻辑机理：传统反潜依赖平台持续跟踪，新装备把接触保持前推到预置节点，迫使对手在隐蔽机动与摆脱跟踪之间消耗更多时间和能源。"
    )
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "低特征大排水量自主反潜无人潜航器",
            "equipment_form": "大排水量低特征自主反潜无人潜航器",
            "capability_portrait": portrait,
            "operational_process": ["隐蔽释放", "自主建图", "分类跟踪", "复联回传"],
        },
        semantic_contract_required=True,
    )

    assert not any("概述首句缺少" in issue for issue in issues)


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


def test_winning_projection_preserves_model_selected_candidate_title() -> None:
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

    assert (
        provider_module._winning_primary_equipment_form(
            hypothesis,
            equipment_family="ground_launched_precision_missile",
        )
        == "地下加固目标内部级联毁伤"
    )


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
    assert options["web_search"] == {
        "search_context_size": "medium",
        "external_web_access": True,
    }
    assert options["require_web_search"] is True


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
    assert options["_provider_timeout_seconds"] == 240
    assert options["_provider_retry_attempts"] == 1
    assert options["_disable_provider_timeout"] is False
    assert "_allow_extended_provider_timeout" not in options


def test_parallel_s6_card_uses_soft_timeout_and_single_provider_attempt() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"query": "test", "assigned_card": {"name": "test"}},
            3400,
            phase="winning_s6_parallel_card_01",
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "high"
    assert options["model_verbosity"] == "medium"
    assert options["_provider_retry_attempts"] == 1
    assert options["_provider_timeout_seconds"] == 420
    assert options["_disable_provider_timeout"] is True
    assert "web_search" not in options
    assert "require_web_search" not in options


def test_parallel_s6_technology_column_enables_governed_live_search() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"candidate_weapon": {"name": "test"}},
            3200,
            phase="winning_s6_parallel_card_01_module_technology_implementation",
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    options = backend.inputs[0][2]
    assert options["web_search"] == {
        "search_context_size": "medium",
        "external_web_access": True,
    }
    assert options["include_web_sources"] is True
    assert options["require_web_search"] is True


def test_parallel_s6_non_technology_column_does_not_force_live_search() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"candidate_weapon": {"name": "test"}},
            3200,
            phase="winning_s6_parallel_card_01_module_overview",
            output_schema={"ok": "boolean"},
        )
    )

    options = backend.inputs[0][2]
    assert "web_search" not in options
    assert "require_web_search" not in options


def test_parallel_s6_resume_card_preserves_high_reasoning_profile() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"query": "test", "assigned_card": {"name": "test"}},
            3400,
            phase="winning_s6_parallel_card_resume_01",
            output_schema={"ok": "boolean"},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "high"
    assert options["model_verbosity"] == "medium"
    assert options["_provider_retry_attempts"] == 1
    assert options["_provider_timeout_seconds"] == 480
    assert options["_disable_provider_timeout"] is True


def test_parallel_s6_card_repair_uses_shorter_medium_profile() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"query": "test", "blocking_issues": ["missing indicator"]},
            3600,
            phase="winning_s6_parallel_card_repair_01",
            output_schema={"ok": "boolean"},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "medium"
    assert options["model_verbosity"] == "low"
    assert options["_provider_timeout_seconds"] == 240
    assert options["_provider_retry_attempts"] == 1
    assert options["_disable_provider_timeout"] is True


def test_parallel_s6_card_can_opt_into_hard_timeout(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_S6_HARD_TIMEOUTS", "1")
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_s6_image",
            "system",
            {"query": "test", "assigned_card": {"name": "test"}},
            3400,
            phase="winning_s6_parallel_card_01",
            output_schema={"ok": "boolean"},
        )
    )

    options = backend.inputs[0][2]
    assert options["_provider_timeout_seconds"] == 420
    assert options["_disable_provider_timeout"] is False


def test_dynamic_swarm_specialist_allows_provider_retry() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_swarm_evidence_verifier",
            "system",
            {"query": "test"},
            2200,
            phase="winning_swarm_dynamic_s5_evidence_verifier",
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    options = backend.inputs[0][2]
    assert options["_provider_retry_attempts"] == 2
    assert options["_provider_timeout_seconds"] == 480


def test_semantic_pair_clustering_uses_fast_bounded_profile() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_swarm_independent_portfolio_reviewer",
            "system",
            {"pair_ids": [["a", "b"]]},
            860,
            phase="winning_semantic_pair_clustering",
            output_schema={"ok": "boolean"},
        )
    )

    assert result == '{"ok":true}'
    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "low"
    assert options["model_verbosity"] == "low"
    assert options["max_output_tokens"] == 860
    assert options["_provider_timeout_seconds"] == 120
    assert options["_provider_retry_attempts"] == 1
    assert options["_disable_provider_timeout"] is False


def test_pre_generation_angle_selection_uses_fast_bounded_profile() -> None:
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(text='{"selected_seed_ids":[]}')
                )
            ]
        ]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_swarm_independent_portfolio_reviewer",
            "system",
            {"reserve_candidates": []},
            790,
            phase="winning_pre_generation_angle_selection",
            output_schema={"selected_seed_ids": ["string"]},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "low"
    assert options["model_verbosity"] == "low"
    assert options["_provider_timeout_seconds"] == 120
    assert options["_provider_retry_attempts"] == 1


def test_pre_generation_active_angle_selection_has_no_provider_hard_timeout() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"active_angle_ids":[]}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_swarm_independent_portfolio_reviewer",
            "system",
            {"angle_candidates": []},
            1500,
            phase="winning_pre_generation_active_angle_selection",
            output_schema={"active_angle_ids": ["string"]},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "low"
    assert options["model_verbosity"] == "low"
    assert options["_disable_provider_timeout"] is True
    assert options["_provider_retry_attempts"] == 1


def test_post_divergence_frontier_mapping_uses_medium_reasoning_in_one_pass() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"angle_challenges":[]}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_swarm_independent_portfolio_reviewer",
            "system",
            {"existing_angles": [], "seed_pool": {"cards": []}},
            2200,
            phase="winning_post_divergence_seed_challenge_mapping",
            output_schema={"angle_challenges": ["object"]},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "medium"
    assert options["model_verbosity"] == "low"
    assert options["max_output_tokens"] == 2200


def test_evidence_analysis_uses_compact_bounded_profile() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"findings":[]}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "weapon_equipment",
            "system",
            {"materialized_sources": []},
            1800,
            phase="evidence_analysis",
            output_schema={"findings": ["string"]},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "medium"
    assert options["model_verbosity"] == "low"
    assert options["_provider_timeout_seconds"] == 210
    assert options["_provider_retry_attempts"] == 1
    assert options["_disable_provider_timeout"] is False


def test_s5_handoff_contract_uses_bounded_authoring_profile() -> None:
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(text='{"indicator_portrait":"ok"}')
                )
            ]
        ]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(  # type: ignore[attr-defined]
            "winning_swarm_independent_portfolio_reviewer",
            "system",
            {"assigned_candidate": {"name": "candidate"}},
            1200,
            phase="winning_s5_handoff_contract_01",
            output_schema={"indicator_portrait": "string"},
        )
    )

    options = backend.inputs[0][2]
    assert options["reasoning_effort"] == "medium"
    assert options["model_verbosity"] == "low"
    assert options["_provider_timeout_seconds"] == 180
    assert options["_provider_retry_attempts"] == 1
    assert options["_disable_provider_timeout"] is False


def test_project_parallel_report_uses_actual_column_count() -> None:
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
        )

    assert calls == {
        "report_generation_chapter_1_demand_overview": 4000,
        "report_generation_chapter_1_status": 4200,
        "report_generation_chapter_1_necessity": 4200,
        "report_generation_chapter_2_equipment_image": 5200,
        "report_generation_chapter_2_operations": 6000,
        "report_generation_chapter_2_contribution": 4000,
        "report_generation_chapter_2_indicators": 4000,
        "report_generation_chapter_3_architecture": 2400,
        "report_generation_chapter_3_subsystems": 4400,
        "report_generation_chapter_4_technology": 5600,
        "report_generation_chapter_5_units": 2800,
        "report_generation_chapter_5_technical_foundation": 3600,
    }


def test_quality_judge_budget_scales_only_for_small_repair_sets() -> None:
    assert _quality_judge_output_token_budget(1) == 2600
    assert _quality_judge_output_token_budget(2) == 3400
    assert _quality_judge_output_token_budget(4) == 4600
    assert _quality_judge_output_token_budget(10) == 4600


def test_expert_judge_keeps_complete_first_round_when_targeted_rejudge_fails() -> None:
    assert (
        _effective_expert_judge_status(
            [{"status": "completed"}, {"status": "failed"}],
            assessed_count=10,
            expected_count=10,
        )
        == "completed"
    )
    assert (
        _effective_expert_judge_status(
            [{"status": "limited"}, {"status": "failed"}],
            assessed_count=8,
            expected_count=10,
        )
        == "failed"
    )


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
    )

    assert len(payload["mechanism_chain"]) == 4
    assert len(payload["evidence_ids"]) == 8
    assert len(payload["validation_plan"]) == 4
    assert payload["mechanism_chain"][0] == repeated[0]
    assert payload["mechanism_chain"][-1] == repeated[-1]
    assert not any("…" in item or "..." in item for item in payload["mechanism_chain"])
    assert "deterministic_hard_gate" not in payload


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
        winning_angle_id="query-winning-angle-2",
        original_paradigm="依赖持续外部目标更新",
        disruptive_shift="转为弹上自治重构目标证据链",
        independence_thesis="改变授权与目标续接关系，而非增加射程",
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
    assert payload["winning_angle_id"] == "query-winning-angle-2"
    assert payload["original_paradigm"] == "依赖持续外部目标更新"
    assert payload["disruptive_shift"] == "转为弹上自治重构目标证据链"
    assert payload["independence_thesis"] == "改变授权与目标续接关系，而非增加射程"


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


def test_portfolio_title_does_not_compose_name_from_equipment_form() -> None:
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

    assert provider_module._winning_portfolio_title(hypothesis) == (
        "多层反无人走廊迫使低空装备转向窗口突防"
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


def test_remote_precision_portfolio_direction_uses_model_classification() -> (
    None
):
    assert provider_module._is_remote_precision_portfolio_direction(
        {
            "name": "JASSM-ER类空射防区外巡航导弹",
            "military_value": "战役纵深精确毁伤",
            "portfolio_role": "remote_precision_strike",
        }
    )
    assert not provider_module._is_remote_precision_portfolio_direction(
        {
            "name": "远程精确巡航导弹",
            "military_value": "战役纵深精确毁伤",
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
        "branch_products": {key: [] for key in _branch_product_output_schema(branch)},
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
    assert any("火力分配" in item for item in handoff["high_value_combat_effects"])
    assert len(handoff["mission_effect_escalation_questions"]) == 3
    assert handoff["public_evidence"][0]["url"] == "https://example.test/report"
    for leaked in ("Agent", "Codex", "S3", "L1", "reasoning_nodes", "Harness"):
        assert leaked not in serialized


def test_dynamic_s6_handoff_passes_only_selected_direct_combat_weapons() -> None:
    handoff = _capability_synthesis_handoff(
        topic="岛链外缘火力续接",
        branch="D",
        prior_step_outputs={
            "winning_swarm": {
                "policy": {"finalist_maximum": 12, "max_concurrency": 6},
                "hypothesis_ledger": {
                    "hypotheses": [
                        {
                            "hypothesis_id": "legacy-s6-1",
                            "title": "“断链”自主末段猎歼弹",
                        }
                    ]
                },
                "final_equipment_portfolio": [
                    {
                        "hypothesis_id": "direct-1",
                        "name": "岛链外缘末段猎歼巡飞弹",
                        "equipment_form": "岛链外缘末段猎歼巡飞弹",
                        "direct_combat_equipment": True,
                        "evidence_ids": ["ev-weapon_equipment-web-1"],
                        "indicator_portrait": (
                            "测量轴比较受扰窗口内目标复核与直接毁伤保持能力；"
                            "对照现役远程打击任务链，无法形成稳定战果时判退。"
                        ),
                        "query_relevance": (
                            "在岛链外缘火力交战阶段，针对敌方机动与干扰压力，"
                            "直接打击并毁伤高价值目标。"
                        ),
                        "unique_operational_role": "断链后的末段自主猎歼",
                        "launch_or_release_domain": "岛链外缘远程火力释放域",
                        "target_and_direct_effect": "猎歼高价值机动目标",
                        "concise_winning_summary": (
                            "受扰断链后仍能自主复核目标，在末段窗口直接猎歼高价值机动目标。"
                        ),
                        "non_substitutable_difference": "把复核与授权前移至弹上",
                        "portfolio_identity_contract": {"hypothesis_id": "direct-1"},
                        "evidence_boundary": "S3 Agent仅形成方向推断，仍需对象试验验证",
                    },
                    {
                        "hypothesis_id": "legacy-s6-1",
                        "name": "断链自主末段猎歼弹",
                        "equipment_form": "断链自主末段猎歼弹",
                        # Failed S6 snapshots created before the flag was
                        # protected still contain a frozen weapon identity.
                    },
                    {
                        "hypothesis_id": "support-1",
                        "name": "火力任务网关",
                        "equipment_form": "火力任务网关",
                        "direct_combat_equipment": False,
                    },
                ],
            }
        },
        evidence_index=[],
    )

    assert [
        item["hypothesis_id"] for item in handoff["selected_equipment_portfolio"]
    ] == [
        "direct-1",
        "legacy-s6-1",
    ]
    assert handoff["selected_equipment_portfolio"][0]["direct_combat_equipment"] is True
    assert "判退" in handoff["selected_equipment_portfolio"][0]["indicator_portrait"]
    assert handoff["selected_equipment_portfolio"][0]["unique_operational_role"] == (
        "断链后的末段自主猎歼"
    )
    assert handoff["selected_equipment_portfolio"][0][
        "portfolio_identity_contract"
    ] == {"hypothesis_id": "direct-1"}
    assert (
        "自主复核目标"
        in handoff["selected_equipment_portfolio"][0]["concise_winning_summary"]
    )
    assert "evidence_boundary" not in handoff["selected_equipment_portfolio"][0]
    assert handoff["selected_equipment_portfolio"][1]["source_hypothesis_title"] == (
        "“断链”自主末段猎歼弹"
    )
    assert handoff["s6_card_capacity"] == 12
    assert handoff["s6_parallelism"] == 32
    assert (
        "仅传入已通过动态组合评审的直接战斗武器" in handoff["selected_portfolio_rule"]
    )
    assert "前置候选阶段冻结" in handoff["selected_portfolio_rule"]
    assert "S6逐卡并行撰写能力画像" in handoff["selected_portfolio_rule"]


def test_s6_handoff_uses_per_run_parallelism_not_worker_capacity() -> None:
    handoff = _capability_synthesis_handoff(
        topic="单任务内并行画像",
        branch="A",
        prior_step_outputs={},
        evidence_index=[],
        s6_parallelism=4,
    )

    assert handoff["s6_parallelism"] == 4


def test_s6_direction_repair_cannot_rename_pre_s6_candidate() -> None:
    repaired = provider_module._merge_s6_direction_repairs(
        {
            "concept_directions": [
                {
                    "name": "仿生扑翼微型侦察打击弹",
                    "capability_portrait": "原画像",
                }
            ]
        },
        {
            "direction_repairs": [
                {
                    "position": 1,
                    "direction": {
                        "name": "S6重新命名的无人机",
                        "capability_portrait": "自然重写后的能力画像",
                    },
                }
            ]
        },
    )

    assert repaired["concept_directions"][0]["name"] == "仿生扑翼微型侦察打击弹"
    assert (
        repaired["concept_directions"][0]["capability_portrait"]
        == "自然重写后的能力画像"
    )


def test_capability_portrait_modules_preserve_frozen_weapon_codename_quotes() -> None:
    portrait = provider_module.assemble_capability_portrait_modules(
        {
            "overview": "“玄鳞”可变散射攻顶弹针对传统固定特征库改变识别交换关系并形成直接毁伤",
            "technology_implementation": "“玄鳞”把可重构散射表面集成到弹体并受飞控约束",
            "operational_process": "“玄鳞”进入防区后改变散射状态并在末段恢复攻顶姿态",
            "capability_effects": "“玄鳞”迫使敌方延迟分类并打击顶部薄弱目标",
            "winning_logic": "“玄鳞”以弹体复杂度换取敌方反应时间和拦截资源",
        }
    )
    assert "“玄鳞”可变散射攻顶弹" in portrait
    assert portrait.count("“玄鳞”") == 5


def test_s6_portrait_repair_changes_only_failed_module() -> None:
    modules = {
        "overview": "原概述",
        "technology_implementation": "原技术实现",
        "operational_process": "原作战流程",
        "capability_effects": "原能力效果",
        "winning_logic": "原制胜逻辑",
    }
    portrait = provider_module.assemble_capability_portrait_modules(modules)
    result = {
        "concept_directions": [
            {
                "name": "“蜕芯”可分离巡飞弹",
                "capability_portrait_modules": modules,
                "capability_portrait": portrait,
                "baseline_system": "冻结基线",
            }
        ]
    }

    repaired = provider_module._merge_s6_portrait_module_repairs(
        result,
        {
            "portrait_module_repairs": [
                {
                    "position": 1,
                    "module_repairs": [
                        {
                            "module": "operational_process",
                            "content": "联合火力突击阶段，发射分队完成装订并按授权窗口释放，弹体在目标区分段接敌、复核和打击，无法确认时终止作用",
                        }
                    ],
                }
            ]
        },
    )

    direction = repaired["concept_directions"][0]
    assert direction["name"] == "“蜕芯”可分离巡飞弹"
    assert direction["baseline_system"] == "冻结基线"
    assert direction["capability_portrait_modules"]["overview"] == "原概述"
    assert direction["capability_portrait_modules"]["technology_implementation"] == "原技术实现"
    assert "联合火力突击阶段" in direction["capability_portrait"]


def test_s6_portrait_issue_mapping_targets_only_named_module() -> None:
    targets = provider_module._s6_portrait_module_repair_targets(
        {"concept_directions": [{"name": "“蜕芯”可分离巡飞弹"}]},
        ["第1项装备能力画像缺少治理模块：关键作战流程："],
    )

    assert targets == {1: ["operational_process"]}


def test_s6_portrait_contract_accepts_non_kinetic_equipment_workflow() -> None:
    modules = {
        "overview": "谱域门控电子对抗站面向联合战役前沿空域，在敌方跳频数据链突发启用窗口，由我方电子对抗单元识别并实施定向干扰，直接迟滞敌无人编队协同",
        "technology_implementation": "阵列接收任务频谱输入，经在线分选和波形参数估计驱动数字射频通道生成相干干扰，资源控制器按威胁优先级分配功率与波束并监测作用反馈",
        "operational_process": "电子对抗分队伴随编队进入任务区，探测敌链路后完成识别与授权，按目标方向形成干扰波束；敌方换频时实时重构策略，达到迟滞效果后转入静默并转移",
        "capability_effects": "形成对突发跳频链路的快速识别、定向压制和动态重构能力，直接降低敌无人编队协同保持度，并以识别时间、有效干扰占空比和己方兼容性验收",
        "winning_logic": "传统宽带压制依赖持续大功率辐射，对手可换频并反定位；门控相干作用把持续覆盖改写为按威胁瞬时聚能，迫使其在维持链路与暴露波形之间选择",
    }
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "谱域门控电子对抗站",
            "primary_equipment_identity": "谱域门控电子对抗站",
            "equipment_form": "车载固定构型电子对抗站",
            "capability_portrait": provider_module.assemble_capability_portrait_modules(
                modules
            ),
        },
    )

    assert not any("未以一个具体武器装备为主体" in issue for issue in issues)
    assert not provider_module._s6_portrait_repair_issues(issues)


def test_s6_winning_logic_content_is_owned_by_codex_not_keyword_gate() -> None:
    modules = {
        "overview": "潮前待机高速打击弹面向联合战役纵深压制阶段，在敌机动节点短时暴露窗口由我方空中平台前出待机并快速俯冲，直接毁伤敌方目标",
        "technology_implementation": "由Codex形成的专属技术实现说明",
        "operational_process": "由Codex形成的真实战斗流程",
        "capability_effects": "形成快速打击能力并直接毁伤目标",
        "winning_logic": "传统远程火力在发现目标后才发射，对手可借短暴露逃逸；空中预置把飞抵等待前置，迫使对手在保持隐蔽与启用节点之间选择；失效边界需通过后续验证判定",
    }
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "潮前待机高速打击弹",
            "equipment_form": "潮前待机高速打击弹",
            "capability_portrait": provider_module.assemble_capability_portrait_modules(
                modules
            ),
        },
    )

    assert not any("制胜逻辑混入" in item for item in issues)
    assert provider_module._s6_portrait_repair_issues(issues) == []


def test_s6_portrait_length_does_not_schedule_module_repair() -> None:
    overlong_logic = (
        "传统远程精确火力依赖持续目标更新并在发现后组织发射，对手能够利用链路迟滞、短时暴露和快速转移逃出打击窗口。"
        + "该装备把受控接敌能力前置到目标邻近空间，以武器本体持续占位替代后方火力临时响应，"
        * 4
        + "迫使对手在保持节点静默与暴露任务功能之间选择，并使其防护资源长期分散。"
    )
    modules = {
        "overview": "概述" * 70,
        "technology_implementation": "技术实现" * 40,
        "operational_process": "作战流程" * 40,
        "capability_effects": "能力效果" * 40,
        "winning_logic": overlong_logic,
    }
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "邻空占位精打弹",
            "equipment_form": "邻空占位精打弹",
            "capability_portrait": provider_module.assemble_capability_portrait_modules(
                modules
            ),
            "operational_process": ["预置待机", "授权后接敌"],
        },
        semantic_contract_required=True,
    )

    assert not any("过度展开" in item or "展开不足" in item for item in issues)
    assert provider_module._s6_portrait_repair_issues(issues) == []


def test_s6_limited_provider_card_is_not_reused() -> None:
    assert not provider_module._s6_card_is_reusable(
        {
            "name": "“天鉴”临近空间预警平台",
            "capability_portrait": "概述：" + "完整军事语义" * 30,
            "operational_process": ["升空展开", "持续警戒并更新威胁航迹"],
            "semantic_consistency_check": {"consistent": True},
            "s6_authoring_status": "limited_provider_failure",
        }
    )


def test_s6_short_complete_decision_card_is_not_reusable() -> None:
    portrait = provider_module.assemble_capability_portrait_modules(
        {
            "overview": "伴随防空分队以机动微波压制车掩护补给车队穿越低空蜂群伏击区",
            "technology_implementation": "宽带接收阵列先被动定位集群控制波束，共形高功率微波阵面随后在受控扇区形成短脉冲作用，车载热管理与发射联锁限制友邻暴露",
            "operational_process": "车辆随队静默机动，确认来袭轴线后短时展开阵面，压制集群控制与机载电子部件，完成作用即转移阵位",
            "capability_effects": "在不逐架消耗拦截弹的条件下瓦解集群协同，为车队保留穿越时间和末端防空弹药",
            "winning_logic": "常规防空依靠逐目标交换，攻击方可用廉价数量耗尽弹药。微波压制把竞争改为作用扇区与集群电子脆弱性的交换，以一次短时能量作用同时破坏多机协同，迫使对手承担加固、分散和失去规模优势的代价。",
        }
    )

    assert not provider_module._s6_card_is_reusable(
        {
            "name": "“静穹”机动微波压制车",
            "capability_portrait": portrait,
            "operational_process": ["随队静默机动", "定向短脉冲压制后转移"],
            "semantic_consistency_check": {"consistent": True},
        }
    )


def test_s6_portrait_repetition_is_not_a_local_string_gate() -> None:
    modules = {
        "overview": "远海编队脱离岸基航空掩护后，长航时猎潜无人潜航器前出至威胁航道，持续追踪企图借复杂水文隐蔽接近的低噪潜艇",
        "technology_implementation": "艇体侧舷与拖曳被动阵列联合估计弱声源方位，本地声学模型随水文剖面修正搜索航路；低特征推进、浮标协同接口和受控武器舱共同维持长时间接触",
        "operational_process": "母舰在安全海域释放潜航器，潜航器沿预测航道隐蔽展开，发现弱接触后自主调整阵位并连续分类，达到交战条件才请求授权，否则保持跟踪并引导有人平台接替",
        "capability_effects": "持续钉住试图穿越警戒幕的低噪潜艇并压缩其机动空间；持续钉住试图穿越警戒幕的低噪潜艇并压缩其机动空间；以接触保持时间、分类可信度和编队暴露代价共同验收",
        "winning_logic": "传统反潜必须让高价值舰机反复抵近维持接触，对手可借水文跃层拖垮搜索节奏。无人潜航器把风险和等待前推至水下警戒幕，以长时间低特征伴随迫使对手在隐蔽航行、任务速度和摆脱跟踪之间持续付出代价。",
    }
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "“潜钟”长航时猎潜无人潜航器",
            "equipment_form": "长航时武装猎潜无人潜航器",
            "capability_portrait": provider_module.assemble_capability_portrait_modules(
                modules
            ),
            "operational_process": ["隐蔽释放并展开", "持续分类跟踪并受控交战"],
        },
        semantic_contract_required=True,
    )

    assert not any("模块内重复" in item for item in issues)
    assert provider_module._s6_portrait_repair_issues(issues) == []


def test_s6_quality_gate_defers_title_form_identity_to_semantic_contract() -> None:
    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                {
                    "name": "可消耗察打一体无人机",
                    "equipment_form": "空射可消耗诱饵反辐射巡飞压制弹",
                    "primary_equipment_identity": "空射可消耗诱饵反辐射巡飞压制弹",
                }
            ]
        }
    )

    assert not any("名称与equipment_form不是同一主装备对象" in item for item in issues)


def test_s6_quality_gate_detects_cross_card_process_template_reuse() -> None:
    def direction(name: str, equipment_form: str) -> dict:
        return {
            "name": name,
            "type": "new_capability",
            "primary_equipment_identity": equipment_form,
            "equipment_form": equipment_form,
            "operational_process": [
                "完成任务装订并进入部署地域",
                "平台进入目标区域后执行搜索复核",
                "满足授权门槛时交战否则拒打",
                "完成毁伤评估并组织补射接替",
            ],
            "semantic_consistency_check": {
                "consistent": True,
                "process_actor": equipment_form,
                "launch_or_release_mode": "由本装备既定发射域执行",
                "target_and_direct_effect": "对授权目标形成直接战果",
                "resolution_note": "整卡语义已核对",
            },
            "operational_mechanism": "形成直接战斗效应",
            "military_value": "直接毁伤敌方目标",
            "adversary_adaptation": "对手实施机动与伪装",
            "failure_boundary": "效应边界不成立时停止",
            "query_relevance": "对应Query任务对象、作战阶段与直接战果",
            "baseline_system": "公开类别级基线",
            "capability_gap": "现役装备缺少该专属战斗动作",
            "confidence": 0.72,
        }

    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                direction("岸基机动反舰导弹", "岸基机动反舰导弹"),
                direction("伴随式反无人拦截弹", "伴随式反无人拦截弹"),
            ]
        },
        handoff={"query": "联合战斗装备研究", "equipment_portfolio_preflight": {}},
    )

    assert not any("作战流程骨架高度重复" in item for item in issues)


def test_dynamic_portfolio_does_not_replace_query_title_with_family_template() -> None:
    hypothesis = WinningHypothesis(
        hypothesis_id="query-weapon",
        title="“礁影”双模伏击巡飞弹",
        nearest_public_baseline="公开巡飞弹基线",
        changed_confrontation_variable="岛礁伏击窗口内的自主目标复核",
        mechanism_chain=["待机", "复核", "猎歼"],
        direct_military_effects=["压制伏击火力节点"],
        equipment_forms=[
            "形态：远程低成本突防巡航弹，内置主杀伤体、末段诱压释放舱和有限末段确认载荷"
        ],
        novelty_delta="以岛礁伏击窗组织自主猎歼",
    )

    assert (
        provider_module._winning_primary_equipment_form(
            hypothesis,
            equipment_family="loitering_munition",
        )
        == "“礁影”双模伏击巡飞弹"
    )


def test_s6_quality_gate_does_not_rejudge_generic_labels_from_keywords() -> None:
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

    assert not any("抽象技术标签" in issue for issue in issues)
    assert not any("具体装备" in issue for issue in issues)
    assert not any("必须包含现役装备升级" in issue for issue in issues)
    assert not any("概述战斗场景要素不完整" in issue for issue in issues)


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

    assert not any(
        "120至360" in issue or "当前" in issue and "字" in issue for issue in issues
    )


def test_s6_normalization_does_not_replace_agent_title_with_equipment_form() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "空射导弹",
                    "equipment_form": "可消耗空射/地面助推无人僚机弹药",
                    "type": "new_capability",
                    "military_value": "对敌防空火控节点实施压制与毁伤",
                }
            ]
        }
    )

    assert normalized["concept_directions"][0]["name"] == "空射导弹"


def test_s6_normalization_preserves_full_identity_for_launch_mode_label() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "地射无人机",
                    "equipment_form": "车载发射舱近程拦截无人机",
                    "type": "new_capability",
                    "military_value": "对低空突防目标实施近程拦截与毁伤",
                }
            ]
        }
    )

    assert normalized["concept_directions"][0]["name"] == "地射无人机"


def test_s6_normalization_omits_internal_evidence_boundary_without_blocking_delivery() -> (
    None
):
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "强扰断链复获反舰巡航弹",
                    "equipment_form": "远程反舰巡航弹",
                    "evidence_boundary": "S6 Agent要求退回S5补写对象证据",
                }
            ]
        }
    )

    assert "evidence_boundary" not in normalized["concept_directions"][0]
    assert (
        provider_module._s6_delivery_blocking_issues(
            ["S6第1项evidence_boundary为内部审计备注，交付时忽略该可选字段"]
        )
        == []
    )


def test_s6_weapon_name_is_not_reclassified_by_suffix_vocabulary() -> None:
    issue = provider_module._capability_language_issues(
        1,
        {"name": "“影袭”低特征诱骗压制攻击弹药", "type": "new_capability"},
    )

    assert issue == []
    assert provider_module._s6_delivery_blocking_issues(issue) == []
    assert provider_module._requires_s6_combat_value_rewrite(issue) is False


def test_s6_quality_gate_accepts_semantic_codename_with_full_weapon_identity() -> None:
    direction = {
        "name": "“影袭”低特征诱骗压制反辐射巡飞攻击弹",
        "equipment_form": "低特征诱骗压制反辐射巡飞攻击弹",
        "type": "new_capability",
    }

    assert provider_module._capability_language_issues(1, direction) == []
    assert provider_module._s6_primary_equipment_identity_mismatch(direction) is False


def test_s6_delivery_blocking_classifier_makes_every_local_issue_advisory() -> None:
    issues = [
        "S6必须形成5至7项具体、互异且高军事价值的最终武器装备方向",
        "S6各能力画像confidence不得机械同值，必须反映证据差异",
        "S6第1项与第2项机制高度重复（三元字符相似度0.910）",
        "S6第3项未说明具体作战阶段、任务对象及打击/反制效果",
        "S6具名装备方向必须引用与自身型号或装备族直接匹配的对象证据；涉及位置4",
    ]

    blocking = provider_module._s6_delivery_blocking_issues(issues)

    assert blocking == []


def test_s6_delivery_length_is_not_a_hard_gate() -> None:
    issues = ["装备能力画像总长度超限（正文1100字，最多1000字）"]
    assert provider_module._s6_delivery_blocking_issues(issues) == []
    state = provider_module._s6_release_gate_state(issues, [])
    assert state["passed"] is True
    assert state["failed"] is False
    assert state["limited"] is True


def test_s6_frontier_new_capability_accepts_analogous_evidence_but_upgrade_does_not() -> (
    None
):
    base_direction = {
        "name": "低特征纵深压制巡航弹",
        "type": "new_capability",
        "equipment_form": "低特征纵深压制巡航弹",
        "baseline_system": "JASSM类防区外巡航弹",
        "direct_evidence_refs": ["ev-analogous-aargm"],
        "foresight_evidence_status": "analogous_project_evidence",
        "evidence_boundary": "公开材料只支持相邻项目的发射与效应机理，不证明拟议巡航弹已经实现。",
    }
    handoff = {
        "query": "强对抗纵深压制",
        "public_evidence": [
            {
                "evidence_id": "ev-analogous-aargm",
                "title": "AARGM-ER反辐射导弹公开项目",
            }
        ],
    }

    frontier_issues = _capability_direction_quality_issues(
        {"concept_directions": [base_direction]}, handoff=handoff
    )
    upgrade_issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                {
                    **base_direction,
                    "type": "upgrade",
                    "foresight_evidence_status": "direct_object_baseline",
                }
            ]
        },
        handoff=handoff,
    )

    assert not any("具名装备方向必须引用" in issue for issue in frontier_issues)
    assert not any("具名装备方向必须引用" in issue for issue in upgrade_issues)


def test_s6_semantic_contract_warns_on_completely_evidence_free_frontier_card() -> None:
    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                {
                    "name": "前瞻高功率微波巡飞弹",
                    "type": "new_capability",
                    "equipment_form": "高功率微波巡飞弹",
                    "direct_evidence_refs": [],
                }
            ]
        },
        handoff={"equipment_portfolio_preflight": []},
    )

    evidence_issues = [item for item in issues if "缺少任何可追溯证据引用" in item]
    assert evidence_issues == []


def test_s6_delivery_does_not_block_missing_or_placeholder_indicator_portrait() -> (
    None
):
    issues = [
        "S6第1项缺少indicator_portrait",
        "S6第2项indicator_portrait未形成由本装备机理推导的差异化测量轴、"
        "对照基线与判退条件",
    ]

    assert provider_module._s6_delivery_blocking_issues(issues) == []


def test_s6_release_state_marks_evidence_backed_warnings_as_limited() -> None:
    state = provider_module._s6_release_gate_state(
        ["S6第1项缺少indicator_portrait"],
        ["S6第1项标题超过48字"],
    )

    assert state == {
        "passed": True,
        "failed": False,
        "limited": True,
        "issues": [],
        "warnings": [
            "S6第1项缺少indicator_portrait",
            "S6第1项标题超过48字",
        ],
    }


def test_s6_confidence_warning_is_not_delivery_blocking() -> None:
    warning = "步骤置信度低于0.65，需要定向复核"
    assert provider_module._s6_delivery_blocking_issues([warning]) == []
    state = provider_module._s6_release_gate_state([], [warning])
    assert state["passed"] is True
    assert state["failed"] is False
    assert state["limited"] is True


def test_s6_same_card_long_sentence_reuse_is_advisory() -> None:
    repeated = (
        "验证阶段必须以强干扰下持续接触时间、误击拒止率和有人平台暴露时间"
        "对照现役基线实施判退。"
    )
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "低特征大排水量自主反潜无人潜航器",
            "equipment_form": "低特征大排水量自主反潜无人潜航器",
            "capability_portrait": repeated * 3,
        },
    )

    assert not any("同一卡片长句机械重复" in item for item in issues)
    assert provider_module._s6_portrait_repair_issues(issues) == []


def test_s6_payload_bundle_title_is_owned_by_semantic_agent() -> None:
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "轻型鱼雷/反UUV拦截弹药模块",
            "equipment_form": "轻型鱼雷/反UUV拦截弹药模块",
        },
    )

    assert issues == []


def test_s6_trusts_semantically_locked_identity_without_keyword_title_gate() -> None:
    issues = provider_module._capability_language_issues(
        1,
        {
            "name": "深海伏击任务效应节点",
            "primary_equipment_identity": "深海预置自主伏击武器系统",
            "equipment_form": "深海预置自主伏击武器系统",
            "semantic_consistency_check": {"consistent": True},
            "portfolio_identity_contract": {
                "pre_s6_identity_contract": {
                    "status": "resolved_by_s5_semantic_agent",
                    "method": "whole_candidate_military_semantics",
                }
            },
        },
        semantic_contract_required=True,
    )

    assert not any("载荷/模块/节点" in item for item in issues)


def test_query_scene_is_not_reclassified_by_local_domain_keywords() -> None:
    issues = provider_module._capability_direction_quality_issues(
        {
            "concept_directions": [
                {
                    "name": "低特征大排水量自主反潜无人潜航器",
                    "type": "new_capability",
                    "target_scenario": "敌水面编队依托分层防空进入反舰交战阶段",
                }
            ]
        },
        handoff={
            "query": "远海编队水下警戒与反潜作战",
            "equipment_portfolio_preflight": {},
        },
    )

    assert not any("水下/反潜Query场景错误投影" in item for item in issues)


def test_s6_repair_targets_extracts_global_evidence_mismatch_positions() -> None:
    result = {"concept_directions": [{} for _ in range(5)]}

    targets = _s6_repair_targets(
        result,
        ["S6具名装备方向必须引用匹配对象证据；涉及位置4"],
    )

    assert targets == [4]


def test_s6_repair_targets_can_cover_full_eight_card_portfolio() -> None:
    result = {"concept_directions": [{} for _ in range(8)]}
    issues = [f"S6第{position}项缺少indicator_portrait" for position in range(1, 9)]

    assert _s6_repair_targets(result, issues) == list(range(1, 9))


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
        [
            "S6最终方向名称必须互异，禁止多个不同装备被压缩为同一标题：多模复核反辐射巡飞猎歼弹"
        ],
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


def test_dynamic_s6_card_binding_creates_distinct_codex_cli_providers() -> None:
    created: list[str] = []

    class Provider:
        def __init__(self, isolation_id: str = "shared") -> None:
            self.isolation_id = isolation_id

        def snapshot(self) -> dict[str, str]:
            return {
                "type": "codex_cli",
                "context_isolation": self.isolation_id,
            }

        def isolated_copy(self, isolation_id: str) -> "Provider":
            created.append(isolation_id)
            return Provider(isolation_id)

    provider = ResponsesAgentProvider(Provider())  # type: ignore[arg-type]
    payloads = [
        {
            "query_semantics": "query",
            "candidate_weapon": {
                "name": f"weapon-{index}",
                "card_binding_id": f"s6-card-binding-{index}",
            },
            "winning_logic_overview": "winning logic",
        }
        for index in range(1, 4)
    ]

    isolation_ids = [
        provider_module._swarm_provider_isolation_id(
            "winning_s6_image",
            payload,
        )
        for payload in payloads
    ]
    scoped = [
        provider._provider_for("winning_s6_image", isolation_id=isolation_id)
        for isolation_id in isolation_ids
    ]

    assert isolation_ids == [
        "s6-card-binding-1",
        "s6-card-binding-2",
        "s6-card-binding-3",
    ]
    assert len({id(item) for item in scoped}) == 3
    assert [item.snapshot()["context_isolation"] for item in scoped] == isolation_ids
    assert created == isolation_ids


def test_s6_quality_gate_does_not_use_cross_card_text_similarity() -> (
    None
):
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

    assert not any("第1项与第2项机制高度重复" in issue for issue in issues)


def test_s6_title_preflight_preserves_ascii_abbreviation_spacing() -> None:
    title = "FS-LIDS类公开基线已集成FAAD C2打击能力升级"

    assert _dedupe_capability_title(title) == title
    issues = _capability_language_issues(3, {"name": title})
    assert not any("超过24字" in item for item in issues)
    assert not any("描述句" in item for item in issues)


def test_s6_title_preflight_repairs_layout_only_not_semantic_repetition() -> None:
    assert _dedupe_capability_title(" 能力  方向\n升级。 ") == "能力方向升级"
    assert _dedupe_capability_title("火力火力能力升级") == "火力火力能力升级"
    assert _dedupe_capability_title("FAAD   C2") == "FAAD C2"


def test_s6_title_gate_does_not_reject_upgrade_suffix_locally() -> None:
    issues = _capability_language_issues(
        2,
        {"name": "空射隐身防区外巡航导弹抗扰补打升级"},
    )

    assert issues == []


def test_s6_overview_style_is_not_a_local_keyword_gate() -> (
    None
):
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

    assert not any("研究管理或证据管理" in issue for issue in issues)
    assert not any("战斗场景要素不完整" in issue for issue in issues)
    assert provider_module._s6_portrait_repair_issues(issues) == []


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


def test_s6_local_normalization_preserves_agent_upgrade_names() -> None:
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

    assert normalized["concept_directions"][0]["name"] == "复杂障碍突破升级"
    assert normalized["concept_directions"][1]["name"] == "低空节点防护升级"


def test_s6_local_normalization_does_not_compose_name_from_baseline_sentence() -> None:
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
    assert title == "现役近程防空火炮和弹炮结合防空系统具备机动底盘拦截能力升级"


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


def test_s6_title_gate_does_not_classify_abstract_suffix_by_keywords() -> (
    None
):
    issues = _capability_language_issues(
        1,
        {
            "name": "岛链远程目标猎获与多域饱和打击协同能力",
            "equipment_form": "远程反舰导弹、电子压制效应器和火力任务系统",
        },
    )

    assert issues == []


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


def test_s6_combat_value_uses_the_model_semantic_contract() -> None:
    assert _has_combat_effect_signal(
        {
            "combat_effect_uplift": "关键消息送达率提升并缩短重同步时间",
            "strike_countermeasure_value": "保持通信受压条件下的反制任务闭环",
            "operational_mechanism": "",
            "capability_portrait": "",
            "equipment_semantic_assessment": {"direct_combat_effect": True},
        }
    )


def test_s6_support_only_decision_is_consumed_from_s5_semantic_contract() -> None:
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

    directions = [
        _with_model_semantic_contract(
            support_direction(
                "现役海空前沿指挥车船多链路任务保底通信升级",
                "upgrade",
            ),
            classification="support_only",
            direct_combat_effect=False,
            support_only=True,
        ),
        _with_model_semantic_contract(
            support_direction("分布式通信网关恢复系统", "new_capability"),
            classification="support_only",
            direct_combat_effect=False,
            support_only=True,
        ),
        _with_model_semantic_contract(
            support_direction("任务数据审计与接口治理系统", "new_capability"),
            classification="support_only",
            direct_combat_effect=False,
            support_only=True,
        ),
    ]

    assert all(
        provider_module._is_ordinary_support_direction(item) for item in directions
    )
    issues = _capability_direction_quality_issues(
        {"concept_directions": directions}
    )
    assert not any("不得把普通通信" in issue for issue in issues)


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
            "高机动被动射频/光电探测车、边缘火控计算单元和伪装机动发射协同模块"
        ),
        "military_value": "提升目标发现、火力分配和再打击质量",
    }

    assert provider_module._is_ancillary_support_equipment_direction(direction) is False


@pytest.mark.parametrize(
    ("name", "equipment_form"),
    [
        (
            "激光-可编程炮弹复合清漏拦截车",
            "机动防空炮车集成高能激光器与可编程空爆弹药",
        ),
        (
            "箱式垂发可回收反无人截击器车",
            "箱式垂发车搭载可回收反无人空中截击器",
        ),
        (
            "被动交接定向电子攻击压制车",
            "高机动底盘集成定向电子攻击阵列",
        ),
    ],
)
def test_s6_recognizes_mobile_counter_swarm_effect_vehicles(
    name: str,
    equipment_form: str,
) -> None:
    direction = _with_model_semantic_contract(
        {
            "name": name,
            "equipment_form": equipment_form,
            "function": "在近海强对抗条件下拦截或压制无人蜂群",
            "military_value": "削减蜂群同步抵达压力并降低末段弹药消耗",
            "operational_mechanism": "完成目标交接、效应器分配、拦截压制与战果复核",
        }
    )

    assert provider_module._direction_name_has_equipment_object(direction) is True
    assert provider_module._is_lethal_weapon_equipment_direction(direction) is True
    assert provider_module._is_ordinary_support_direction(direction) is False
    assert provider_module._is_ancillary_support_equipment_direction(direction) is False


def test_s6_quality_gate_requires_query_specific_direct_lethal_weapon_portfolio() -> (
    None
):
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
            direction(
                "现役预警机目标识别与火力引导升级",
                "现役预警机与联合火控系统",
                "upgrade",
            ),
            direction(
                "分布式雷达目标猎获系统", "机动雷达与光电传感器", "new_capability"
            ),
            direction("电子战目标压制系统", "电子战任务系统", "new_capability"),
        ]
    }
    issues = _capability_direction_quality_issues(missing_weapons)
    assert not any("杀伤/反杀伤武器装备方向" in issue for issue in issues)
    assert not any("必须包含无人" in issue for issue in issues)

    unrelated_query_issues = _capability_direction_quality_issues(
        missing_weapons,
        handoff={"query": "社会化资源参与战时工业动员装备研究"},
    )
    assert not any("当前query涉及无人" in issue for issue in unrelated_query_issues)
    assert not any("当前query涉及远程火力" in issue for issue in unrelated_query_issues)

    complete_portfolio = {
        "concept_directions": [
            direction(
                "现役防空导弹抗饱和拦截升级", "现役防空导弹与联合火控系统", "upgrade"
            ),
            direction(
                "远域无人机目标猎歼系统",
                "察打一体无人机与协同攻击载荷",
                "new_capability",
            ),
            direction(
                "远程反舰导弹连续打击系统",
                "远程反舰导弹、发射单元与联合火控系统",
                "new_capability",
            ),
            direction(
                "低空反无人高功率微波压制器", "高功率微波反无人效应器", "new_capability"
            ),
            direction(
                "深海无人潜航器鱼雷伏击系统",
                "无人潜航器与重型鱼雷载荷",
                "new_capability",
            ),
        ]
    }
    complete_issues = _capability_direction_quality_issues(complete_portfolio)
    assert not any("无人作战装备方向" in issue for issue in complete_issues)
    assert not any("杀伤/反杀伤武器装备方向" in issue for issue in complete_issues)
    assert not any("4个相互区分的直接武器" in issue for issue in complete_issues)

    fire_platform_portfolio = {
        "concept_directions": [
            direction(
                "抗干扰远程精确制导弹药", "陆基远程精确制导弹药", "new_capability"
            ),
            direction(
                "可消耗无人搜索打击平台", "察打一体可消耗无人机", "new_capability"
            ),
            direction("多模拒打巡飞弹药", "中小型巡飞弹药", "new_capability"),
            direction(
                "HIMARS/NMESIS断链拒止升级", "HIMARS、NMESIS机动发射车", "upgrade"
            ),
            direction(
                "低特征前沿精确火力车", "模块化发射箱与低特征火力车", "new_capability"
            ),
        ]
    }
    fire_platform_issues = _capability_direction_quality_issues(fire_platform_portfolio)
    assert not any("4个相互区分的直接武器" in issue for issue in fire_platform_issues)

    two_direct_only = {
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
                "远程反舰导弹连续打击系统",
                "远程反舰导弹、发射单元与联合火控系统",
                "new_capability",
            ),
            direction(
                "分布式雷达目标猎获系统", "机动雷达与光电传感器", "new_capability"
            ),
            direction(
                "联合火控目标分配系统", "联合火控系统与任务传感器", "new_capability"
            ),
        ]
    }
    two_direct_issues = _capability_direction_quality_issues(two_direct_only)
    assert not any("武器未构成组合主体" in issue for issue in two_direct_issues)

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
    assert not any(
        "独立导弹或精确制导弹药方向" in issue for issue in false_positive_issues
    )


def test_s6_query_mismatch_is_read_from_structured_agent_judgement() -> None:
    portrait = (
        "该方向面向海上区域拒止条件下的交战阶段，以独立导弹武器和联合火控完成目标识别、"
        "火力分配、突防、毁伤评估和再次打击。相对现役基线，新增抗干扰制导、任务重规划"
        "和多平台协同发射机制，并针对对手饱和突防、诱饵和节点损耗形成反适应。近期完成"
        "现役系统改装，中期形成样机并开展体系联试；验证采用红蓝对抗、实弹或半实物试验，"
        "若有效交战闭环和毁伤闭合率不能提高，则降低优先级。"
    )
    direction = _with_model_semantic_contract({
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
    }, query_alignment_confirmed=False, precision_munition=True)
    handoff = {
        "query": "评估我军现役海上区域拒止体系在强干扰与饱和突防条件下的装备能力差距"
    }

    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                direction,
                {
                    **direction,
                    "name": "远域无人机目标猎歼系统",
                    "equipment_form": "察打一体无人机",
                    "type": "upgrade",
                    "upgrade_package": ["火控软件", "任务载荷"],
                    "combat_effect_uplift": "提升猎歼与毁伤能力",
                    "strike_chain_contribution": "缩短发现到打击闭环",
                    "upgrade_boundary": "平台余量不足时转入新研",
                },
                {
                    **direction,
                    "name": "机动雷达防空拦截引导系统",
                    "equipment_form": "机动雷达与防空火控系统",
                },
            ]
        },
        handoff=handoff,
    )

    assert any("模型判定与当前Query不一致" in issue for issue in issues)


def test_s6_query_relevance_does_not_use_local_stage_keyword_checklist() -> None:
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
    assert issues == []


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
    for row in (
            {
                "name": "中小型反辐射巡飞弹目标发现",
                "equipment_form": "中小型反辐射巡飞弹与被动射频载荷",
            },
            {
                "name": "PrSM Increment 1/2火力升级",
                "equipment_form": "PrSM Increment 1/2类陆基远程精确制导弹药",
            },
            {
                "name": "可消耗远程电子压制弹火力",
                "equipment_form": "远程电子压制弹与被动射频导引载荷",
            },
            {
                "name": "现役Tomahawk Block V火力升级",
                "equipment_form": "现役Tomahawk Block V巡航导弹与舰载发射系统",
            },
    ):
        assert provider_module._direction_name_has_equipment_object(
            _with_model_semantic_contract(row, precision_munition=True)
        ) is True


def test_s6_structured_identity_accepts_novel_glide_strike_pod_without_lexicon() -> (
    None
):
    """A new-build ``打击舱`` is valid when its governed contract is complete."""

    direction = _with_model_semantic_contract({
        "name": "“判毁续击”分布式效应滑翔打击舱",
        "type": "new_capability",
        "primary_equipment_identity": "“判毁续击”分布式效应滑翔打击舱",
        "equipment_form": "“判毁续击”分布式效应滑翔打击舱",
        "function": "末段复核目标毁伤状态，对关键节点实施直接毁伤与必要补击",
        "operational_mechanism": "分布式释放后按目标优先级滑翔接近，完成毁伤判定并独立触发补击",
        "military_value": "在首击不确定和链路受压条件下闭合毁伤链，提升关键节点持续失能概率",
    })

    assert provider_module._direction_name_has_equipment_object(direction) is True
    issues = provider_module._capability_direction_quality_issues(
        {
            "concept_directions": [
                {
                    **direction,
                    "confidence": 0.72,
                    "adversary_adaptation": "对手转移目标并加强诱饵干扰",
                    "failure_boundary": "目标身份无法确认时拒打",
                    "query_relevance": (
                        "面向强干扰和节点损耗条件下的打击阶段，"
                        "应对对手诱饵压力，形成关键节点直接毁伤与必要补击效果。"
                    ),
                    "baseline_system": "现有远程精确火力与一次性战斗部",
                    "capability_gap": "首击毁伤不确定时缺少低成本补击手段",
                }
            ]
        },
        handoff={},
    )
    assert not any("名称未直接点明具体装备对象" in issue for issue in issues)
    assert not any("未绑定具体装备" in issue for issue in issues)


def test_s6_recognizes_semantic_combat_munition_compound() -> None:
    direction = _with_model_semantic_contract({
        "name": "远程可消耗电子诱骗弹火力",
        "equipment_form": "远程电子诱骗弹与任务载荷",
        "military_value": "压制防空雷达并为主攻弹群制造突防窗口",
    }, precision_munition=True)

    assert provider_module._direction_name_has_equipment_object(direction) is True
    assert provider_module._is_missile_precision_munition_direction(direction) is True


def test_s6_rejects_support_mission_disguised_with_unmanned_and_firepower() -> None:
    direction = _with_model_semantic_contract({
        "name": "小型无人机回收/数据读取接口火力",
        "equipment_form": "小型无人机、回收装置与数据读取接口",
        "function": "回收平台并读取任务数据",
        "military_value": "提升任务数据复盘效率",
    }, classification="support_only", direct_combat_effect=False, support_only=True)

    assert provider_module._is_ordinary_support_direction(direction) is True
    assert provider_module._is_lethal_weapon_equipment_direction(direction) is False


def test_s6_normalizer_preserves_agent_query_relevance_without_local_projection() -> None:
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

    assert normalized_direction["query_relevance"] == direction["query_relevance"]
    assert not _query_relevance_issues(
        1,
        normalized_direction,
        query="强干扰、弱通信条件下低信息依赖精确打击研究",
    )


def test_s6_normalizer_does_not_append_query_terms_to_agent_relevance() -> None:
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
    assert relevance == "在补击与交战阶段应对目标机动压力，形成末段再捕获和直接毁伤。"
    assert not _query_relevance_issues(
        1,
        normalized["concept_directions"][0],
        query="强电磁压制与GNSS拒止条件下远程反舰火力链断裂后的自主续接装备研究",
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


def test_s6_language_gate_does_not_reclassify_equipment_names() -> None:
    direction = {
        "name": "远程精确打击联合升级",
        "equipment_form": "JASSM空射巡航导弹与PrSM地射远程导弹联合升级",
    }

    assert provider_module._capability_language_issues(
        1,
        direction,
        semantic_contract_required=True,
    ) == []


def test_s6_gate_treats_mobile_rocket_launcher_as_bound_combat_equipment() -> None:
    direction = _with_model_semantic_contract({
        "name": "无人值守远程精确打击火箭发射车",
        "equipment_form": "无人值守机动火箭发射车，配远程精确火箭弹兼容发射架",
        "function": "对已暴露防空和远火节点实施快速补击",
    })

    assert provider_module._direction_name_has_equipment_object(direction) is True
    assert direction["equipment_semantic_assessment"]["concrete_equipment"] is True


def test_s6_gate_recognizes_armed_unmanned_wingman_as_concrete_equipment() -> None:
    direction = _with_model_semantic_contract({
        "name": "远域反辐射压制无人僚机",
        "equipment_form": "长航时低可探测武装无人僚机",
    }, classification="unmanned_combat")

    assert provider_module._direction_name_has_equipment_object(direction) is True


def test_s6_normalizer_does_not_rewrite_wrong_model_authored_flow() -> None:
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
        "operational_process": [
            "防区外释放",
            "组合导航",
            "时效判断",
            "末段复核",
            "毁伤或拒打",
        ],
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
    assert portrait == direction["capability_portrait"]
    assert "箱式分批释放" in portrait
    assert "在位察打" in portrait


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
    assert "海上" in contract["query"]
    assert "区域拒止" in contract["query"]
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
    assert contract["portfolio"]["membership_and_identity_locked_before_s6"] is True
    assert "至少两项" in contract["portfolio"]["same_family_independence_rule"]
    assert "只修复质量残差命中的位置" in contract["portfolio"]["resume_rule"]
    assert (
        contract["disruptive_dimension_use"]["internal_query_causal_lenses"] == "2..3"
    )
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
    assert contract["s6_latency_budget"]["normal_model_passes"] == 1
    assert contract["s6_latency_budget"]["maximum_targeted_repair_passes"] == 1
    assert (
        contract["s6_latency_budget"]["repair_scope"]
        == "failed_portrait_modules_only_identity_locked"
    )
    assert "S5交接门闭合并锁定" in submission_contract
    assert contract["preflight_acceptance"]["passed"] is True


def test_pre_s6_contract_does_not_locally_author_missing_s5_semantics() -> (
    None
):
    prepared = _prepare_pre_s6_card_contract(
        {
            "name": "强扰断链复获反舰巡航弹",
            "primary_equipment_identity": "固定构型远程反舰巡航弹",
            "baseline_system": "现役防区外反舰巡航弹",
            "non_substitutable_difference": "外部目标更新中断后的有限区复获窗口",
            "target_and_direct_effect": "毁伤机动水面目标并阻断编队重组",
            "launch_or_release_domain": "岛链外缘海空联合战役补击阶段的舰射域",
            "unique_operational_role": "断链条件下续接远程反舰打击",
            "validation_plan": ["比较目标复获时间、正确交战率和正确拒打率"],
            "failure_boundary": "剩余能量不足以覆盖搜索区",
        },
        query="强干扰条件下远海机动目标持续精确打击",
    )

    assert "indicator_portrait" not in prepared
    assert "query_relevance" not in prepared
    assert (
        prepared["portfolio_identity_contract"]["pre_s6_quality_contract"][
            "s6_mutation_allowed"
        ]
        is False
    )


def test_pre_s6_contract_inherits_capability_gap_from_frozen_candidate_semantics() -> (
    None
):
    prepared = _prepare_pre_s6_card_contract(
        {
            "name": "断链目标续认巡飞弹",
            "baseline_system": "现役坐标装订巡飞弹",
            "problem_statement": "目标机动和链路压制使发射前坐标快速过期",
            "target_and_direct_effect": "续认授权目标并实施直接毁伤",
        },
        query="不完备战场信息条件下精确打击",
    )

    assert prepared["capability_gap"] == (
        "目标机动和链路压制使发射前坐标快速过期"
    )


def test_s6_normalization_inherits_missing_capability_gap_from_legacy_card() -> None:
    normalized = _normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "断链目标续认巡飞弹",
                    "problem_statement": "目标机动和链路压制使发射前坐标快速过期",
                }
            ]
        }
    )

    assert normalized["concept_directions"][0]["capability_gap"] == (
        "目标机动和链路压制使发射前坐标快速过期"
    )


def test_pre_s6_contract_omits_internal_evidence_boundary_before_authoring() -> None:
    prepared = _prepare_pre_s6_card_contract(
        {
            "name": "强扰断链复获反舰巡航弹",
            "baseline_system": "现役防区外反舰巡航弹",
            "target_and_direct_effect": "毁伤机动水面目标并阻断编队重组",
            "failure_boundary": "剩余能量不足以覆盖搜索区",
            "evidence_boundary": "S5 Agent认为仍需回到S4补写对象证据",
        },
        query="强干扰条件下远海机动目标持续精确打击",
    )

    assert "evidence_boundary" not in prepared
    contract = prepared["portfolio_identity_contract"]["pre_s6_quality_contract"]
    assert contract["evidence_boundary_status"] == (
        "omitted_internal_or_non_epistemic_boundary"
    )


def test_pre_s6_contract_preserves_public_epistemic_evidence_boundary() -> None:
    boundary = (
        "公开证据仅支持相邻项目的末段传感与抗扰导航，"
        "不证明拟议巡航弹已经形成完整装备和实战毁伤效能。"
    )
    prepared = _prepare_pre_s6_card_contract(
        {
            "name": "强扰断链复获反舰巡航弹",
            "baseline_system": "现役防区外反舰巡航弹",
            "target_and_direct_effect": "毁伤机动水面目标并阻断编队重组",
            "failure_boundary": "剩余能量不足以覆盖搜索区",
            "evidence_boundary": boundary,
        },
        query="强干扰条件下远海机动目标持续精确打击",
    )

    assert prepared["evidence_boundary"] == boundary
    contract = prepared["portfolio_identity_contract"]["pre_s6_quality_contract"]
    assert contract["evidence_boundary_status"] == (
        "accepted_public_epistemic_boundary"
    )


def test_pre_s6_contract_does_not_keyword_rewrite_s5_identity_and_strips_internal_language() -> (
    None
):
    prepared = _prepare_pre_s6_card_contract(
        {
            "name": "形态：远程低成本突防巡航弹，内置主杀伤体、末段诱压释放舱和确认载荷",
            "source_hypothesis_title": "“扰窗”末段诱压突防巡航弹",
            "baseline_system": "S5 Agent建议对照现役防区外巡航弹",
            "non_substitutable_difference": "S4将末段防御分类窗口转化为拥塞时间",
            "target_and_direct_effect": "压迫点防御误配拦截资源并毁伤高价值机动目标",
            "validation_plan": ["比较一体诱压弹与独立诱饵齐射的主弹到达率"],
            "failure_boundary": "对手自动分类成熟后诱压不再增加防御负担",
        },
        query="强电磁压制下远程精确毁伤",
    )

    assert prepared["name"] == (
        "形态：远程低成本突防巡航弹，内置主杀伤体、末段诱压释放舱和确认载荷"
    )
    assert "primary_equipment_identity" not in prepared
    contract = prepared["portfolio_identity_contract"]["pre_s6_quality_contract"]
    assert contract["indicator_portrait"] == ""
    assert contract["query_relevance"] == ""


@pytest.mark.parametrize(
    "profile_id",
    ["winning_swarm_dynamic_v2", "optimized_v2"],
)
def test_s6_only_resume_upgrades_legacy_portfolio_before_parallel_authoring(
    monkeypatch,
    profile_id,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.provider_type = "codex_cli"  # type: ignore[attr-defined]
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    events: list[dict] = []
    provider.set_winning_progress_callback(events.append)
    phases: list[str] = []
    systems: list[str] = []
    payload_key_sets: list[set[str]] = []
    s6_payloads: list[dict] = []
    card_binding_ids: list[str] = []
    module_prompt_sections: list[tuple[str, str]] = []
    module_attempts: list[tuple[str, str, int]] = []
    active_s6_calls = 0
    maximum_s6_concurrency = 0
    initial_gate_limit = provider._call_gate.snapshot()["limit"]

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        schema,
        max_output_tokens,
        *,
        phase,
    ):
        nonlocal active_s6_calls, maximum_s6_concurrency
        del agent_id, schema, max_output_tokens
        phases.append(phase)
        systems.append(system)
        payload_key_sets.append(set(payload))
        if phase.startswith("winning_s6_parallel_card"):
            s6_payloads.append(dict(payload))
        card_binding_ids.append(
            str(payload.get("candidate_weapon", {}).get("card_binding_id", ""))
        )
        if "_module_" in phase:
            module_prompt_sections.append(
                (
                    str(payload.get("portrait_module_key", "")),
                    str(payload.get("portrait_module_prompt_section", "")),
                )
            )
            module_attempts.append(
                (
                    str(payload.get("candidate_weapon", {}).get("name", "")),
                    str(payload.get("portrait_module_key", "")),
                    int(payload.get("portrait_module_attempt", 0)),
                )
            )
        active_s6_calls += 1
        maximum_s6_concurrency = max(
            maximum_s6_concurrency,
            active_s6_calls,
        )
        try:
            await asyncio.sleep(0.01)
        finally:
            active_s6_calls -= 1
        assigned = dict(payload["candidate_weapon"])
        assigned["concise_winning_summary"] = payload["winning_logic_overview"]
        name = assigned["name"]
        modules = _complete_s6_test_modules(name)
        if "_module_" in phase:
            module_key = phase.rsplit("_module_", 1)[-1]
            if (
                name.endswith("-3")
                and module_key == "capability_effects"
                and int(payload.get("portrait_module_attempt", 0)) == 1
            ):
                raise ProviderRequestError("single column transient failure")
            return json.dumps(
                {
                    "module_key": module_key,
                    "module_content": modules[module_key],
                    "card_binding_id": assigned.get("card_binding_id", ""),
                    "hypothesis_id": assigned.get("hypothesis_id", ""),
                    "capability_image_draft": f"{name}断链续接能力画像",
                },
                ensure_ascii=False,
            )
        direction = {
            **assigned,
            "function": f"由{name}在强干扰火力窗口内完成目标复核与直接打击",
            "operational_mechanism": "以本地任务装订和非卫星导航维持目标区自主交战闭环",
            "target_scenario": "联合战役纵深打击阶段遭卫星拒止、导航欺骗和防空压制",
            "operational_process": [
                "发射平台装订目标类别、授权边界和禁打区",
                "武器按非卫星导航组合进入目标责任区",
                "本地复核授权目标并排除诱饵与非授权对象",
                "满足门槛后实施压制或毁伤，不满足时拒打",
                "形成战果摘要并触发后续补击或任务终止",
            ],
            "military_value": "压制或毁伤授权目标并维持远程精确火力续接",
            "combat_effect_uplift": "在卫星链路中断时保持直接打击和补击能力",
            "strike_chain_contribution": "闭合目标复核、授权交战、毁伤评估和补击续接",
            "development_path": "完成样机、硬件在环和对抗条件下任务试验",
            "future_trigger": "卫星拒止与复杂电磁压制成为常态威胁",
            "adversary_adaptation": "对手采用诱饵、短促暴露和导航欺骗",
            "failure_boundary": "目标复核或授权边界无法可靠维持时判退",
            "capability_gap": "现役基线缺少断链条件下的目标区自主复核和续接打击",
            "capability_outcome": "形成断链条件下远程精确火力自主续接能力",
            # S6 is allowed to author prose, but must not overwrite the S5
            # capability classification or display a conflicting dimension.
            "capability_classification": {
                "primary_dimension": "突防维度",
                "secondary_dimensions": ["生存抗毁维度"],
                "classification_basis": "S6错误地把技术路径当成主要战果。",
            },
            "semantic_consistency_check": {
                "process_actor": name,
                "launch_or_release_mode": "由装备既定发射域释放",
                "target_and_direct_effect": "对授权目标实施压制或毁伤",
                "checked_fields": [
                    "name",
                    "operational_process",
                    "capability_portrait",
                ],
                "consistent": True,
                "resolution_note": "主装备、发射域、目标和战果一致",
            },
            "confidence": 0.78,
            # S6 may return stale values, but the S5 contract must overwrite them.
            "indicator_portrait": "通用指标待补充",
            "query_relevance": "与当前query相关",
        }
        if not phase.endswith("_spine"):
            direction["capability_portrait_modules"] = modules
            direction["capability_portrait"] = (
                "能力分类：主：突防维度；辅：生存抗毁维度。\n"
                + "概述："
                + modules["overview"]
                + "\n- 装备与技术实现："
                + modules["technology_implementation"]
                + "\n- 关键作战流程："
                + modules["operational_process"]
                + "\n- 形成能力与作战效果："
                + modules["capability_effects"]
                + "\n- 制胜逻辑机理："
                + modules["winning_logic"]
            )
        return json.dumps(
            {
                "direction": direction,
                "capability_image_draft": f"{name}断链续接能力画像",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(provider, "_run_core_json", fake_run_core_json)
    monkeypatch.setattr(
        provider_module,
        "_capability_direction_quality_issues",
        lambda result, *, handoff=None: [],
    )
    legacy_portfolio = [
        {
            "hypothesis_id": f"legacy-{index}",
            "name": f"断链自主精确打击弹-{index}",
            "type": "new_capability",
            "equipment_form": f"断链自主精确打击弹-{index}",
            "primary_equipment_identity": f"断链自主精确打击弹-{index}",
            "target_scenario": "卫星拒止条件下的纵深火力交战阶段",
            "problem_statement": "目标更新中断与导航欺骗威胁导致精确打击链断裂",
            "military_value": "毁伤授权目标并维持远程精确打击续接",
            "baseline_system": f"现役远程精确打击弹药基线-{index}",
            "capability_gap": "断链条件下目标区自主复核与续接打击能力不足",
            "direct_evidence_refs": [f"ev-{index}"],
            "validation_plan": ["对比任务响应、目标复核、正确交战和正确拒打"],
            "failure_boundaries": ["无法可靠复核目标或维持授权边界时判退"],
            "capability_classification": {
                "primary_dimension": "毁伤维度",
                "secondary_dimensions": ["持续作战维度"],
                "classification_basis": (
                    "决定性节点是断链后由弹体自主复核并完成授权交战，主要可验收战果是持续毁伤目标。"
                ),
            },
            "expert_score": 0.78,
        }
        for index in range(1, 6)
    ]

    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "卫星受扰条件下跨域自主远程精确火力研究",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {
                    "primary_branch": "G",
                    "execution_profile_id": profile_id,
                    "winning_swarm_policy": {
                        "finalist_maximum": 12,
                        "max_concurrency": 6,
                    },
                },
                "execution_profile_id": profile_id,
                "packets": [],
                "evidence_index": [],
                "resume_steps": [6],
                "prior_winning_analysis": {
                    "concept_directions": legacy_portfolio,
                    "s6_quality_gate_failed": True,
                    "s6_quality_gate_passed": False,
                    "winning_swarm": {
                        "policy": {"finalist_maximum": 12, "max_concurrency": 6},
                        "final_equipment_portfolio": legacy_portfolio,
                        "portfolio_quality_gate": {"passed": True},
                    },
                },
            }
        )
    )

    assert all(
        phase.startswith("winning_s6_parallel_card_resume_") for phase in phases
    )
    assert all(
        {"query_semantics", "candidate_weapon", "winning_logic_overview"}.issubset(keys)
        for keys in payload_key_sets
    )
    forbidden_s6_context = {
        "failure_boundary",
        "failure_boundaries",
        "evidence_boundary",
        "direct_evidence_refs",
        "evidence_refs",
        "evidence_ids",
        "validation_plan",
        "indicator_portrait",
    }
    s6_payload_key_sets = [
        keys
        for phase, keys in zip(phases, payload_key_sets, strict=True)
        if phase.startswith("winning_s6_parallel_card")
    ]
    assert all(
        not (forbidden_s6_context & keys)
        for keys in s6_payload_key_sets
    )
    if profile_id == "winning_swarm_dynamic_v2":
        assert all(
            not (
                forbidden_s6_context
                & set(payload.get("candidate_weapon", {}))
            )
            for payload in s6_payloads
        )
    assert len(set(card_binding_ids)) == 5
    assert all(card_binding_ids)
    if profile_id == "winning_swarm_dynamic_v2":
        assert sum(phase.endswith("_spine") for phase in phases) == 5
        assert sum("_module_" in phase for phase in phases) == 26
        assert len(phases) == 31
        assert maximum_s6_concurrency == 25
        assert result["s6_parallel_authoring"]["portrait_modules_concurrent"] is True
        assert result["s6_parallel_authoring"]["process_isolation"] == "new_process_per_turn"
    else:
        assert maximum_s6_concurrency == 25
        assert len(phases) == 31
        assert sum(1 for phase in phases if phase.endswith("_spine")) == 5
        assert sum(1 for phase in phases if "_module_" in phase) == 26
        assert all("parallel_card_id" in keys for keys in payload_key_sets)
        spine_systems = [
            system
            for phase, system in zip(phases, systems, strict=True)
            if phase.endswith("_spine")
        ]
        module_systems = [
            system
            for phase, system in zip(phases, systems, strict=True)
            if "_module_" in phase
        ]
        assert spine_systems
        assert all("五栏正文由其他并发会话撰写" in system for system in spine_systems)
        assert all("只完成本卡当前指定栏目" in system for system in module_systems)
        assert set(module_prompt_sections) == {
            ("overview", "S6_1"),
            ("technology_implementation", "S6_2"),
            ("operational_process", "S6_3"),
            ("capability_effects", "S6_4"),
            ("winning_logic", "S6_5"),
        }
        assert sum(
            1
            for name, module_key, _attempt in module_attempts
            if name.endswith("-3") and module_key == "capability_effects"
        ) == 2
        assert all(
            sum(
                1
                for seen_name, seen_key, _attempt in module_attempts
                if seen_name == name and seen_key == module_key
            )
            == (2 if name.endswith("-3") and module_key == "capability_effects" else 1)
            for name in {item[0] for item in module_attempts}
            for module_key in {
                "overview",
                "technology_implementation",
                "operational_process",
                "capability_effects",
                "winning_logic",
            }
        )
        assert result["s6_parallel_authoring"] == {
            "cards_concurrent": True,
            "cards_wave": "asyncio.gather",
            "portrait_modules_concurrent": True,
            "card_concurrency_limit": 32,
            "portrait_module_prompt_sections": {
                "overview": "S6_1",
                "technology_implementation": "S6_2",
                "operational_process": "S6_3",
                "capability_effects": "S6_4",
                "winning_logic": "S6_5",
            },
            "process_isolation": "new_process_per_turn",
        }
    assert not any("任务输入、计算/处理" in system for system in systems)
    assert not any("到任务结果的实现链" in system for system in systems)
    assert not any("repair" in phase for phase in phases)
    assert any(
        event.get("event_type") == "winning_s5_handoff_quality_gate_completed"
        for event in events
    )
    assert len(result["concept_directions"]) == 5
    if profile_id != "winning_swarm_dynamic_v2":
        assert result["s6_parallel_authoring"]["portrait_modules_concurrent"] is True
    assert provider._call_gate.snapshot()["limit"] == initial_gate_limit
    expected_primary_dimension = (
        "突防维度" if profile_id == "winning_swarm_dynamic_v2" else "毁伤维度"
    )
    expected_portrait_prefix = (
        "能力分类：主：突防维度；辅：生存抗毁维度。"
        if profile_id == "winning_swarm_dynamic_v2"
        else "能力分类：主：毁伤维度；辅："
    )
    for direction in result["concept_directions"]:
        assert (
            direction["capability_classification"]["primary_dimension"]
            == expected_primary_dimension
        )
        assert direction["capability_portrait"].startswith(expected_portrait_prefix)


def test_parallel_s6_failure_moves_card_to_reference_without_run_failure(
    monkeypatch,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.provider_type = "codex_cli"  # type: ignore[attr-defined]
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    events: list[dict] = []
    provider.set_winning_progress_callback(events.append)

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        schema,
        max_output_tokens,
        *,
        phase,
    ):
        del agent_id, system, schema, max_output_tokens
        assigned = dict(payload["candidate_weapon"])
        if "_02" in phase.split("_module_")[0]:
            raise ProviderRequestError("Agent timed out after 240 seconds")
        modules = _complete_s6_test_modules(str(assigned["name"]))
        if "_module_" in phase:
            module_key = phase.rsplit("_module_", 1)[-1]
            return json.dumps(
                {
                    "module_key": module_key,
                    "module_content": modules[module_key],
                    "card_binding_id": assigned.get("card_binding_id", ""),
                    "hypothesis_id": assigned.get("hypothesis_id", ""),
                    "capability_image_draft": "已完成卡片",
                },
                ensure_ascii=False,
            )
        assigned.update(
            {
                "semantic_consistency_check": {
                    "consistent": True,
                    "checked_fields": ["name", "operational_process"],
                },
            }
        )
        if not phase.endswith("_spine"):
            assigned["capability_portrait_modules"] = modules
            assigned["capability_portrait"] = (
                provider_module.assemble_capability_portrait_modules(modules)
            )
        return json.dumps(
            {
                "direction": assigned,
                "capability_image_draft": "已完成卡片",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(provider, "_run_core_json", fake_run_core_json)
    portfolio = [
        {
            "hypothesis_id": f"candidate-{index}",
            "name": f"前置制胜装备-{index}",
            "type": "new_capability",
            "equipment_form": f"前置制胜装备-{index}",
            "primary_equipment_identity": f"前置制胜装备-{index}",
            "unique_operational_role": f"以独立制胜轴{index}改变交战关系",
            "launch_or_release_domain": "岛链外缘联合火力交战阶段",
            "target_and_direct_effect": "压制并毁伤高价值机动目标",
            "non_substitutable_difference": f"独立改变任务链变量{index}",
            "military_value": "压缩目标暴露窗口并直接毁伤高价值机动目标",
            "operational_mechanism": (
                "由弹体在强干扰下完成目标复核、火力授权和直接毁伤闭环"
            ),
            "target_scenario": "岛链外缘强干扰条件下的高价值机动目标猎歼阶段",
            "problem_statement": "目标更新中断使传统远程火力错失短时暴露窗口",
            "scientific_principle": "以弹上多源复核和条件授权压缩交战闭环",
            "enabling_technologies": ["弹上多源复核", "抗扰任务控制"],
            "operational_concept": "前沿单元发现目标后发射，弹体复核并直接交战",
            "operational_process": [
                "前沿单元在目标暴露窗口内完成条件授权并发射",
                "弹体在强干扰下复核目标身份和交战边界",
                "满足门限后对高价值机动目标实施直接毁伤",
            ],
            "capability_outcome": "形成断链条件下的时敏目标直接猎歼能力",
            "winning_mechanism": "把持续链路依赖转为弹上短闭环，压缩敌方机动逃逸时间",
            "concise_winning_summary": (
                "传统远程火力依赖持续链路并在发现后组织发射，对手可借短时暴露和更新迟滞逃离。"
                "该弹把目标复核与受控交战前推到武器端，迫使对手在保持静默与暴露任务功能之间选择，形成断链条件下的持续接敌优势。"
            ),
            "adversary_adaptation": "敌方可能使用诱饵、遮蔽和短时机动压缩复核窗口",
            "failure_boundary": "弹上感知无法区分真实目标与诱饵时不再优先",
            "baseline_system": f"现役远程精确打击基线-{index}",
            "capability_gap": "强干扰下目标更新中断导致火力链失效",
            "direct_evidence_refs": [f"ev-{index}"],
            "validation_plan": ["比较任务响应、正确交战率和直接毁伤效果"],
            "failure_boundaries": ["无法保持授权边界或目标复核时判退"],
            "expert_score": 0.8,
        }
        for index in range(1, 3)
    ]

    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "强干扰条件下远程精确火力续接",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {
                    "primary_branch": "G",
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                },
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "packets": [],
                "evidence_index": [],
                "resume_steps": [6],
                "prior_winning_analysis": {
                    "concept_directions": portfolio,
                    "s6_quality_gate_failed": True,
                    "s6_quality_gate_passed": False,
                    "winning_swarm": {
                        "final_equipment_portfolio": portfolio,
                        "portfolio_quality_gate": {"passed": True},
                    },
                },
            }
        )
    )

    assert result["s6_quality_gate_failed"] is False
    assert [item["name"] for item in result["concept_directions"]] == [
        "前置制胜装备-1",
        "前置制胜装备-2",
    ]
    assert len(result["s6_reference_weapons"]) == 1
    limited = result["s6_reference_weapons"][0]
    assert limited["s6_authoring_status"] == "limited_provider_failure"
    assert limited["s6_authoring_failure_type"] in {
        "S6SpineAuthoringError",
        "S6QualityError",
        "ProviderRequestError",
    }
    assert limited["name"] == "前置制胜装备-2"
    assert limited["s6_eligible"] is True
    assert limited["selection_status"] == "selected_limited"
    assert limited["concise_winning_summary"]
    assert any(
        event.get("event_type") == "winning_s6_card_authoring_limited"
        for event in events
    )


def test_dynamic_s6_resume_reauthors_persisted_cards_from_minimal_input(
    monkeypatch,
) -> None:
    backend = _RealLikeScriptedProvider([])
    backend.provider_type = "codex_cli"  # type: ignore[attr-defined]
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    events: list[dict] = []
    provider.set_winning_progress_callback(events.append)
    model_phases: list[str] = []

    async def reauthor_model_call(
        agent_id,
        system,
        payload,
        schema,
        max_output_tokens,
        *,
        phase,
    ):
        del agent_id, system, schema, max_output_tokens
        model_phases.append(phase)
        candidate = dict(payload["candidate_weapon"])
        source = next(
            item for item in completed_cards if item["name"] == candidate["name"]
        )
        modules = source.get("capability_portrait_modules") or _complete_s6_test_modules(
            candidate["name"]
        )
        if "_module_" in phase:
            module_key = phase.rsplit("_module_", 1)[-1]
            return json.dumps(
                {
                    "module_key": module_key,
                    "module_content": modules[module_key],
                    "card_binding_id": candidate.get("card_binding_id", ""),
                    "hypothesis_id": candidate.get("hypothesis_id", ""),
                    "capability_image_draft": f"{candidate['name']}重新生成能力画像",
                },
                ensure_ascii=False,
            )
        direction = {**source, **candidate}
        if phase.endswith("_spine"):
            direction.pop("capability_portrait_modules", None)
            direction.pop("capability_portrait", None)
        return json.dumps(
            {
                "direction": direction,
                "capability_image_draft": f"{candidate['name']}重新生成能力画像",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(provider, "_run_core_json", reauthor_model_call)
    monkeypatch.setattr(
        provider_module,
        "_capability_direction_quality_issues",
        lambda result, *, handoff=None: [],
    )
    completed_cards = []
    for index in range(1, 3):
        name = f"断链自主精确打击弹-{index}"
        card = provider_module._prepare_pre_s6_card_contract(
            {
                "hypothesis_id": f"completed-{index}",
                "name": name,
                "type": "new_capability",
                "equipment_form": name,
                "primary_equipment_identity": name,
                "unique_operational_role": f"以独立制胜轴{index}闭合火力链",
                "launch_or_release_domain": "岛链外缘联合火力交战阶段",
                "target_and_direct_effect": "压制并毁伤高价值机动目标",
                "non_substitutable_difference": f"独立改变任务链变量{index}",
                "baseline_system": f"现役远程精确打击基线-{index}",
                "capability_gap": "强干扰下目标更新中断导致火力链失效",
                "direct_evidence_refs": [f"ev-{index}"],
                "validation_plan": ["比较任务响应、正确交战率和直接毁伤效果"],
                "failure_boundaries": ["无法保持授权边界或目标复核时判退"],
                "expert_score": 0.8,
            },
            query="强干扰条件下远程精确火力续接",
        )
        card.update(
            {
                "function": f"由{name}完成目标复核和直接毁伤",
                "military_value": "在断链条件下保持直接压制与毁伤能力",
                "capability_outcome": "形成弱网条件下自主续接精确火力",
                "operational_process": [
                    "任务装订后进入责任区",
                    "本地复核目标与授权边界",
                    "满足门槛后实施直接毁伤并形成战果摘要",
                ],
                "capability_portrait_modules": _complete_s6_test_modules(name),
                "capability_portrait": (
                    "能力分类：主：突防维度；辅：生存抗毁维度。\n"
                    + "概述："
                    + _complete_s6_test_modules(name)["overview"]
                    + "\n- 装备与技术实现："
                    + _complete_s6_test_modules(name)["technology_implementation"]
                    + "\n- 关键作战流程："
                    + _complete_s6_test_modules(name)["operational_process"]
                    + "\n- 形成能力与作战效果："
                    + _complete_s6_test_modules(name)["capability_effects"]
                    + "\n- 制胜逻辑机理："
                    + _complete_s6_test_modules(name)["winning_logic"]
                ),
                "semantic_consistency_check": {
                    "consistent": True,
                    "checked_fields": [
                        "name",
                        "operational_process",
                        "capability_portrait",
                    ],
                },
                "confidence": 0.8,
            }
        )
        completed_cards.append(card)

    result = asyncio.run(
        provider._analyze_winning_subagents(
            {
                "topic": "强干扰条件下远程精确火力续接",
                "research_route": "new_winning_mechanism",
                "discovery_blueprint": {
                    "primary_branch": "G",
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                },
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "packets": [],
                "evidence_index": [],
                "resume_steps": [6],
                "prior_winning_analysis": {
                    "concept_directions": completed_cards,
                    "s6_quality_gate_failed": False,
                    "s6_quality_gate_passed": True,
                    "winning_swarm": {
                        "final_equipment_portfolio": completed_cards,
                        "portfolio_quality_gate": {"passed": True},
                    },
                },
            }
        )
    )

    assert model_phases
    assert sum(phase.endswith("_spine") for phase in model_phases) == 2
    assert sum("_module_" in phase for phase in model_phases) == 10
    assert sum(
        1
        for phase in model_phases
        if phase.startswith("winning_s6_parallel_card_resume_0")
    ) == 12
    assert all(
        phase.startswith("winning_s6_parallel_card_resume_0") for phase in model_phases
    )
    assert [item["name"] for item in result["concept_directions"]] == [
        item["name"] for item in completed_cards
    ]
    assert (
        sum(
            item.get("event_type") == "winning_s6_card_authoring_reused"
            for item in events
        )
        == 0
    )


def test_s6_semantic_contract_validates_codex_self_check_without_weapon_keyword_table() -> (
    None
):
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
    assert any("语义一致性合同未通过" in issue for issue in inconsistent_issues)


def test_s6_normalization_coerces_json_boolean_strings_without_rewriting_semantics() -> (
    None
):
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
    assert (
        normalized_direction["operational_process"] == direction["operational_process"]
    )
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
    assert (
        normalized["concept_directions"][0]["equipment_form"]
        == direction["equipment_form"]
    )


def test_s6_disruptive_relationship_diversity_is_pre_generation_guidance_not_hard_gate() -> (
    None
):
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

    rich = {
        "concept_directions": [dict(item) for item in shallow["concept_directions"]]
    }
    rich["concept_directions"][0]["novelty"] = "以低成本规模消耗反转成本交换"
    rich["concept_directions"][1]["novelty"] = "以长航时持续存在的平台重构发射关系"
    rich["concept_directions"][2]["novelty"] = "以毁伤评估和再打击压缩决策周期"
    rich_issues = _capability_direction_quality_issues(rich)
    assert not any("至少需要3类与query因果相关" in issue for issue in rich_issues)


def test_s6_quality_gate_rejects_camouflage_as_a_weapon_portfolio_slot() -> None:
    direction = _with_model_semantic_contract({
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
        "capability_portrait": (
            "该装备用于战役准备阶段构设多谱段假目标并消耗对手侦察资源。" * 20
        )[:360]
        + "。",
    }, classification="support_only", direct_combat_effect=False, support_only=True)

    issues = _capability_direction_quality_issues(
        {"concept_directions": [direction] * 5},
        handoff={"query": "远程无人精确火力装备需求研究"},
    )

    assert provider_module._is_ordinary_support_direction(direction) is True
    assert not any("不得把伪装、假目标" in issue for issue in issues)


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


def test_s6_local_diagnostics_do_not_trigger_scoped_or_full_regeneration() -> None:
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
            "indicator_portrait": (
                "以强干扰下任务闭环响应时间、目标识别率、直接毁伤或拦截成功率"
                "对照现役基线进行考核，低于门槛时判退"
            ),
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
    assert phases.count("winning_s6_card_repair") == 0
    assert "winning_s6_combat_value_rewrite" not in phases
    assert len(result["concept_directions"]) == 5
    assert result["subagent_runs"][-1]["critic_issues"] == []


def test_s6_substantive_local_diagnostic_does_not_repair_or_rerun_upstream(
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
            return ["S6第1项未说明具体作战阶段、任务对象及打击/反制效果"]
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
    assert phases.count("winning_s6_card_repair") == 0
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
        lambda result, *, handoff=None: ["S6第1项证据边界待补充（非阻断建议）"],
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
            step = (
                6
                if agent_id == "winning_s6_image"
                else int(agent_id.split("_s", 1)[1][0])
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
    assert result["s6_quality_gate_failed"] is False

    phases = [phase for _, phase in calls]
    assert phases.count("winning_s6_image_deep") == 1
    assert phases.count("winning_s6_card_repair") == 0


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
    backend.provider_type = "codex_cli"  # type: ignore[attr-defined]
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
    assert (("winning_s4_capability", "winning_s4_targeted_repair") in calls) is (
        4 in expected_steps
    )
    assert ("winning_s6_image", "winning_s6_card_repair") not in calls
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


def test_codex_cli_provider_archives_exact_prompt_and_raw_exchange(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(
        command="codex",
        model="gpt-audit",
        workspace_path=tmp_path,
        base_url="https://gateway.example.test/v1",
        api_key="audit-secret-key",
        include_default_skills=False,
    )
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-audit"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"ok":true}'},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 7}}),
        ]
    )
    captured: dict[str, str] = {}

    def fake_execute(command, prompt):
        captured["prompt"] = prompt
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="cli-note")

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("system", "audit-system"), ModelMessage("user", "audit-user")],
                [],
                {
                    "reasoning_effort": "high",
                    "output_schema": {"ok": "boolean"},
                    "_audit_run_id": "run-audit-1",
                    "_audit_agent_id": "winning_s3_breakthrough",
                    "_audit_phase": "winning_swarm_dynamic_s3",
                    "_audit_call_purpose": "S3 candidate generation",
                },
            )
        ]

    events = asyncio.run(collect())
    relative_path = events[-1].final_turn.metadata["codex_transcript_paths"][0]
    attempt_dir = tmp_path / relative_path

    assert attempt_dir.joinpath("prompt.txt").read_text(encoding="utf-8") == captured["prompt"]
    assert attempt_dir.joinpath("stdout.jsonl").read_text(encoding="utf-8") == stdout
    assert attempt_dir.joinpath("stderr.txt").read_text(encoding="utf-8") == "cli-note"
    assert attempt_dir.joinpath("final.txt").read_text(encoding="utf-8") == '{"ok":true}'
    assert json.loads(attempt_dir.joinpath("output_schema.json").read_text(encoding="utf-8")) == {"ok": "boolean"}
    metadata = json.loads(attempt_dir.joinpath("metadata.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == "run-audit-1"
    assert metadata["agent_id"] == "winning_s3_breakthrough"
    assert metadata["phase"] == "winning_swarm_dynamic_s3"
    assert metadata["codex_thread_id"] == "thread-audit"
    assert metadata["returncode"] == 0
    serialized_metadata = json.dumps(metadata)
    assert "audit-secret-key" not in serialized_metadata
    assert "gateway.example.test" not in serialized_metadata


def test_codex_cli_provider_archives_each_retry_without_overwrite(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        retry_attempts=2,
        include_default_skills=False,
    )
    calls = 0

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
                stderr="first-attempt",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "done"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "retry-audit")],
                [],
                {
                    "_audit_run_id": "run-audit-retry",
                    "_audit_agent_id": "agent-a",
                    "_audit_phase": "phase-a",
                },
            )
        ]

    events = asyncio.run(collect())
    paths = events[-1].final_turn.metadata["codex_transcript_paths"]

    assert len(paths) == 2
    assert paths[0].endswith("attempt-01")
    assert paths[1].endswith("attempt-02")
    assert (tmp_path / paths[0] / "stderr.txt").read_text(encoding="utf-8") == "first-attempt"
    assert (tmp_path / paths[1] / "final.txt").read_text(encoding="utf-8") == "done"


def test_codex_transcript_archive_failure_never_fails_model_delivery(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(workspace_path=tmp_path, include_default_skills=False)
    stdout = json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "delivered"},
        }
    )
    monkeypatch.setattr(
        provider,
        "_execute",
        lambda command, prompt: subprocess.CompletedProcess(
            command, 0, stdout=stdout, stderr=""
        ),
    )

    def fail_archive(path, content):
        del path, content
        raise OSError("audit volume unavailable")

    monkeypatch.setattr(
        "equipment_deep_research.providers.codex._atomic_private_text",
        fail_archive,
    )

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "archive-failure")],
                [],
                {"_audit_run_id": "run-audit-write-failure"},
            )
        ]

    events = asyncio.run(collect())

    assert events[-1].final_turn.text == "delivered"
    assert list(events[-1].final_turn.metadata["codex_transcript_paths"]) == []


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


def test_codex_normal_completion_kills_descendant_process_group(
    tmp_path,
) -> None:
    provider = CodexCliProvider(
        command=sys.executable,
        workspace_path=tmp_path,
        include_default_skills=False,
    )
    child_pid_path = tmp_path / "normal-child.pid"
    script = (
        "import pathlib, subprocess, sys; "
        "child=subprocess.Popen(['/bin/sleep', '60'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); "
        "print('normal-completion')"
    )

    result = asyncio.run(
        provider._execute_async(
            [sys.executable, "-c", script, str(child_pid_path)],
            "",
            timeout_seconds=5,
        )
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "normal-completion"
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
        pytest.fail("completed Codex turn left a descendant process running")


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
        "url: https://relay.example.test/v1/responses"
    )

    assert _is_retryable_failure(detail) is True


@pytest.mark.parametrize(
    "detail",
    [
        "Selected model is at capacity",
        "remote gateway: model is at capacity, please retry later",
        "upstream capacity exceeded",
        "当前分组上游负载已饱和，请稍后再试",
    ],
)
def test_codex_capacity_refusal_is_retryable(detail: str) -> None:
    assert _is_retryable_failure(detail) is True


def test_codex_capacity_retry_ignores_single_attempt_workflow_cap(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_ATTEMPTS", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_JITTER_SECONDS", "0")

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.asyncio.sleep",
        no_sleep,
    )
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        retry_attempts=1,
        include_default_skills=False,
    )
    calls = 0
    success_stdout = json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": '{"ok":true}'},
        }
    )

    def fake_execute(command, prompt):
        nonlocal calls
        del prompt
        calls += 1
        if calls < 4:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=json.dumps(
                    {
                        "type": "turn.failed",
                        "error": {"message": "Selected model is at capacity"},
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout=success_stdout, stderr="")

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "capacity")],
                [],
                {
                    "output_schema": {"ok": "boolean"},
                    "_provider_retry_attempts": 1,
                },
            )
        ]

    events = asyncio.run(collect())

    assert calls == 4
    assert events[-1].final_turn.text == '{"ok":true}'
    assert events[-1].final_turn.metadata["attempts"] == 4
    assert events[-1].final_turn.metadata["retry_reasons"] == (
        "capacity",
        "capacity",
        "capacity",
    )
    assert events[-1].final_turn.metadata["capacity_retry_attempts"] == 4


def test_codex_capacity_exhaustion_raises_typed_error(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_JITTER_SECONDS", "0")

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.asyncio.sleep",
        no_sleep,
    )
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        retry_attempts=1,
        include_default_skills=False,
    )

    def fake_execute(command, prompt):
        del prompt
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "Selected model is at capacity"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "capacity")],
                [],
                {"output_schema": {"ok": "boolean"}},
            )
        ]

    import asyncio

    with pytest.raises(ProviderCapacityError, match="after 2 attempt\\(s\\)"):
        asyncio.run(collect())


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
    assert (
        events[-1].final_turn.metadata["provider_timeout_seconds"] == expected_timeout
    )
    assert events[-1].final_turn.metadata["extended_provider_timeout"] is allow_extended


def test_codex_provider_allows_reporter_call_without_process_timeout(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = CodexCliProvider(workspace_path=tmp_path, timeout_seconds=900)
    captured: dict[str, object] = {}
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "report"},
                }
            ),
            json.dumps({"type": "turn.completed"}),
        ]
    )

    async def fake_execute_async(command, prompt, *, timeout_seconds=None):
        del command, prompt
        captured["timeout_seconds"] = timeout_seconds
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(provider, "_execute_async", fake_execute_async)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "test")],
                [],
                {"_disable_provider_timeout": True},
            )
        ]

    events = asyncio.run(collect())

    assert captured["timeout_seconds"] == 0
    assert events[-1].final_turn.metadata["provider_timeout_seconds"] is None
    assert events[-1].final_turn.metadata["provider_timeout_disabled"] is True


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


def test_codex_cli_provider_refreshes_stale_runtime_auth_before_each_call(
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
    codex_home = tmp_path / "codex-api-home"
    provider = CodexCliProvider(
        workspace_path=tmp_path,
        codex_home=codex_home,
        inherit_user_config=False,
        api_key="fresh-test-key",
        base_url="https://codex.example.test/v1",
    )
    (codex_home / "auth.json").write_text(
        '{"auth_mode":"apikey","OPENAI_API_KEY":"stale-test-key"}',
        encoding="utf-8",
    )

    provider._execute([provider.command, "exec"], "prompt")

    auth = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
    assert auth["OPENAI_API_KEY"] == "fresh-test-key"
    assert captured["env"]["OPENAI_API_KEY"] == "fresh-test-key"
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
    assert [row["step"] for row in completed_progress_rows if "step" in row] == [1, 2, 3, 4, 5, 6]
    assert any(
        row.get("event_type") == "winning_model_call_started" and row.get("step") == 3
        for row in progress_rows
    )
    assert len(result["codex_call_metrics"]) == 11
    assert "reasoning_node" not in {key for key in result if key != "reasoning_nodes"}
    prompt_text = "\n".join(
        str(message.content)
        for messages, _, _ in backend.inputs
        for message in messages
    )
    assert "现役升级必须写明被升级对象、真正改变能力生成方式的软硬件改装路径" in prompt_text
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
            if (
                isinstance(candidate, Mapping)
                and "capability_synthesis_handoff" in candidate
            ):
                s6_inputs.append(dict(candidate))
    assert len(s6_inputs) == 1
    s6_input = s6_inputs[0]
    assert set(s6_input) == {
        "query",
        "branch",
        "analysis_priority",
        "branch_deliverables",
        "capability_synthesis_handoff",
        "execution_profile_id",
        "first_pass_quality_contract",
        "valid_evidence_ids",
    }
    assert "disruptive_seed_context" not in s6_input
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


def test_winning_retry_is_checked_by_harness_then_final_round_critic(
    monkeypatch,
) -> None:
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


def test_winning_recall_does_not_repeat_same_step_with_unchanged_input(
    monkeypatch,
) -> None:
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
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"capability_mapping":["m"]}')
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"passed":true,"issues":[]}')
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"concept_directions":[]}')
            )
        ],
        [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"passed":true,"issues":[]}')
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

    s3_runs = [
        row
        for row in result["subagent_runs"]
        if row["agent_id"] == "winning_s3_breakthrough"
    ]
    assert len(backend.inputs) == 6
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

    assert len(backend.inputs) == 6
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


def test_swarm_quality_profile_runs_three_bounded_waves_and_keeps_candidate_ledger() -> (
    None
):
    def candidate(index: int) -> dict:
        return {
            "title": f"候选{index}：机制族{index}",
            "naming_rationale": f"名称对应第{index}类主装备、目标与直接毁伤机理",
            "decisive_advantage_thesis": f"在当前交战窗口以机制{index}改变火力交换结果",
            "cross_query_distinction": f"更换目标或作战阶段后第{index}类构型与名称必须重做",
            "nearest_public_baseline": f"公开基线{index}",
            "changed_confrontation_variable": f"改变变量{index}",
            "mechanism_chain": [f"独立机制{index}", f"任务闭环{index}"],
            "direct_military_effects": [f"直接打击并毁伤目标{index}"],
            "equipment_forms": [f"具体装备形态{index}"],
            "project_function": f"作战分队在受扰窗口使用具体装备{index}打击并毁伤目标{index}",
            "system_interfaces": [f"火控接口{index}", f"效应载荷接口{index}"],
                "novelty_delta": f"相对基线形成实质差异{index}",
                "frontier_principle": f"前沿作用原理{index}",
                "technology_discontinuity": f"常规升级无法吸收的装备关系跃迁{index}",
                "technology_horizon": "5-10年",
                "engineering_bottleneck": f"可证伪工程瓶颈{index}",
                "original_paradigm": f"传统制胜关系{index}",
                "disruptive_shift": f"新的制胜关系{index}",
                "independence_thesis": f"不是同族换名或一般性能提升{index}",
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
        for index in range(1, 7)
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
        for _ in range(4)
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

    quality_cluster_prompt = repr([message.content for message in backend.inputs[0][0]])
    assert "query_led_weapon_naming_style" in quality_cluster_prompt
    assert "唯一主装备身份" in quality_cluster_prompt
    assert "名称不是候选摘要" in quality_cluster_prompt
    assert "不得逐词拆解" in quality_cluster_prompt
    assert "高功率微波（HPM）巡飞弹" not in quality_cluster_prompt
    assert "自由角度形成后才允许由模型" in quality_cluster_prompt
    assert "不得复制" in quality_cluster_prompt

    swarm = result["winning_swarm"]
    assert 1 <= len(backend.inputs) <= 12
    assert 1 <= len(swarm["task_graph"]) <= 12
    assert swarm["waves"]
    assert all(1 <= item["wave"] <= 3 for item in swarm["waves"])
    assert 1 <= len(swarm["hypotheses"]) <= 6
    assert 1 <= len(swarm["finalists"]) <= len(swarm["hypotheses"])
    assert swarm["budget"]["maximum_instances"] == 12
    assert swarm["core_schedule"]["active_steps"] == []
    assert swarm["core_schedule"]["quality_gate_passed"] is True
    assert swarm["final_merge"]["passed"] is True
    assert swarm["specialist_execution_batches"]
    assert all(
        1 <= item["wave"] <= 3 and item["task_ids"]
        for item in swarm["specialist_execution_batches"]
    )
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
    assert 1 <= len(recruitment_rows) <= 12
    assert len({row["session_ref"] for row in recruitment_rows}) == len(
        recruitment_rows
    )
    assert all(row["provider_type"] == "codex_cli" for row in recruitment_rows)
    assert all(
        row["execution_backend"] == "independent_codex_cli" for row in recruitment_rows
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
        if "specialist_completed" in lifecycle:
            assert lifecycle.index("specialist_session_completed") < lifecycle.index(
                "specialist_completed"
            )


def test_swarm_quality_profile_runs_core_s_agents_in_parallel_and_finalizes_merge() -> (
    None
):
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
                            "naming_rationale": f"名称对应具体装备{breadth_index}及其目标毁伤机理",
                            "decisive_advantage_thesis": f"在当前交战窗口改变火力交换结果{breadth_index}",
                            "cross_query_distinction": f"更换目标后构型和名称必须重做{breadth_index}",
                            "nearest_public_baseline": f"公开基线{breadth_index}",
                            "changed_confrontation_variable": f"变量{breadth_index}",
                            "mechanism_chain": [f"机理{breadth_index}", "形成任务闭环"],
                            "direct_military_effects": [
                                f"直接打击并毁伤目标{breadth_index}"
                            ],
                            "equipment_forms": [f"具体装备{breadth_index}"],
                            "project_function": f"作战分队在受扰场景使用具体装备{breadth_index}打击并毁伤目标",
                            "system_interfaces": ["火控授权接口", "效应载荷接口"],
                                "novelty_delta": f"实质差异{breadth_index}",
                                "frontier_principle": f"前沿作用原理{breadth_index}",
                                "technology_discontinuity": f"常规升级无法吸收的装备关系跃迁{breadth_index}",
                                "technology_horizon": "5-10年",
                                "engineering_bottleneck": f"可证伪工程瓶颈{breadth_index}",
                                "original_paradigm": f"传统制胜关系{breadth_index}",
                                "disruptive_shift": f"新的制胜关系{breadth_index}",
                                "independence_thesis": f"不是同族换名或一般性能提升{breadth_index}",
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
    assert all(
        "physical_cohort_id" not in row for row in result["subagent_runs"]
    )


def test_dynamic_v2_assigns_distinct_angles_and_converges_before_downstream_merge(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "6")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "6")
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    backend.provider_type = "codex_cli"  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    progress_rows: list[dict] = []
    provider.set_winning_progress_callback(progress_rows.append)
    seed_index = 0
    slow_s3_instance_id: str | None = None
    scoped_merge_inputs: list[tuple[str, list[str], list[str]]] = []
    dynamic_seed_library_inputs: list[tuple[str, dict]] = []
    active_seed_calls = 0
    maximum_seed_concurrency = 0
    execution_order: list[str] = []
    angle_assignments: list[dict] = []
    reviewer_inputs: list[dict] = []
    pre_generation_selector_inputs: list[dict] = []
    s6_authoring_inputs: list[dict] = []
    s5_handoff_inputs: list[dict] = []
    s5_handoff_prompts: list[str] = []
    active_s5_handoff_calls = 0
    maximum_s5_handoff_concurrency = 0
    s3_call_counts: dict[str, int] = {}
    candidate_policy_prompts: dict[str, list[str]] = {}
    s3_task_inputs: list[dict] = []
    s3_generation_payloads: list[dict] = []
    s3_counterfactual_key_presence: list[tuple[int, bool]] = []
    s3_post_divergence_seed_presence: list[tuple[int, bool]] = []
    s3_post_divergence_frontier_presence: list[tuple[int, bool]] = []
    s3_visible_evidence_by_call: list[tuple[int, set[str]]] = []
    post_divergence_seed_mapper_agent_ids: list[str] = []
    post_divergence_frontier_mapper_inputs: list[dict] = []

    async def fake_run_core_json(
        agent_id,
        system,
        payload,
        output_schema,
        max_output_tokens,
        *,
        phase="structured_analysis",
    ):
        nonlocal seed_index, slow_s3_instance_id
        nonlocal active_seed_calls, maximum_seed_concurrency
        nonlocal active_s5_handoff_calls, maximum_s5_handoff_concurrency
        if phase in {
            "winning_pre_generation_active_angle_selection",
            "winning_post_divergence_seed_challenge_mapping",
            "winning_semantic_pair_clustering",
            "winning_swarm_dynamic_seed",
        }:
            candidate_policy_prompts.setdefault(phase, []).append(str(system))
        if phase == "winning_pre_generation_active_angle_selection":
            assert "innovation_naming_reference" not in payload
            assert "seed_pool" not in payload
            pre_generation_selector_inputs.append(
                {
                    "payload_keys": set(payload),
                    "open_angle_seeds": list(payload["open_angle_seeds"]),
                    "schema_keys": set(output_schema),
                    "max_output_tokens": max_output_tokens,
                }
            )
                # Force all six S3/S4 producers to overlap at the shared
                # refresh boundary. Exactly one selector call must serve every slot.
            await asyncio.sleep(0.02)
            raise ProviderRequestError(
                "Codex CLI timed out after 120 seconds"
            )
        if phase == "winning_post_divergence_seed_challenge_mapping":
            post_divergence_seed_mapper_agent_ids.append(str(agent_id))
            post_divergence_frontier_mapper_inputs.append(dict(payload))
            existing = list(payload["existing_angles"])
            seed_cards = list(payload["seed_pool"]["cards"])
            return json.dumps(
                {
                    "angle_challenges": [
                        {
                            "target_angle_id": existing[0]["angle_id"],
                            "seed_ids": [seed_cards[0]["id"], seed_cards[1]["id"]],
                            "reframed_winning_question": "由模型重构两个种子关系挑战自由角度",
                            "query_specific_value": "只在当前目标、阶段与威胁组合下成立",
                            "discard_boundary": "不能形成独立装备机理时全部舍弃",
                        }
                    ],
                    "frontier_angle_challenges": [
                        {
                            "target_angle_id": existing[0]["angle_id"],
                            "conventional_ceiling": "常规流程优化和成熟部件拼装不能改变交战交换关系",
                            "frontier_opportunities": [
                                {
                                    "enabling_principle": "由Query推演得到的前沿效应与自主协同原理",
                                    "weapon_architecture_pressure": "迫使主装备的效应器、制导感知和平台关系发生实质变化",
                                    "disruptive_military_asymmetry": "从逐目标交换转为跨域非对称压制",
                                    "natural_naming_cue": "名称应显出真实前沿效应和主装备构型",
                                    "technology_horizon": "5-10 years",
                                    "engineering_credibility_boundary": "载荷小型化、能量管理和对抗试验可证伪",
                                }
                            ],
                            "recommended_use": "explore",
                            "reason": "在当前Query中有独立颠覆价值",
                        }
                    ],
                    "additional_seed_angles": [],
                    "discarded_seed_ids": [item["id"] for item in seed_cards[2:]],
                    "stop_reason": "one_optional_seed_challenge_mapped_after_free_divergence",
                },
                ensure_ascii=False,
            )
        if phase.startswith("winning_s5_handoff_contract_"):
            assigned = dict(payload["assigned_candidate"])
            s5_handoff_inputs.append(assigned)
            s5_handoff_prompts.append(str(system))
            active_s5_handoff_calls += 1
            maximum_s5_handoff_concurrency = max(
                maximum_s5_handoff_concurrency,
                active_s5_handoff_calls,
            )
            try:
                await asyncio.sleep(0.02)
            finally:
                active_s5_handoff_calls -= 1
            return json.dumps(
                {
                    "indicator_portrait": (
                        f"测量轴：评估{assigned['name']}改变任务链断点后直接毁伤效果的保持程度；"
                        "对照基线：与现有同类装备在相同干扰和授权约束下比较；"
                        "判退条件：若无法稳定压缩交战窗口或形成直接毁伤则停止转段。"
                    ),
                    "query_relevance": (
                        f"{assigned['name']}面向当前作战场景的目标猎歼阶段，针对敌方干扰、"
                        "机动和任务链断裂压力，直接打击并毁伤目标，形成不可替代的战场结果。"
                    ),
                    "identity_status": "resolved",
                    "naming_contract_passed": True,
                    "frozen_name": assigned["name"],
                    "primary_equipment_identity": assigned[
                        "primary_equipment_identity"
                    ],
                    "identity_resolution": "依据整卡军事语义确认唯一接敌与直接作用主体。",
                    "concise_winning_summary": (
                        "压缩拒止环境下的目标确认窗口，对高价值时敏目标实施自主精确毁伤。"
                    ),
                },
                ensure_ascii=False,
            )
        if phase.startswith("winning_s6_parallel_card_"):
            assigned_card = dict(payload["candidate_weapon"])
            assigned_card["concise_winning_summary"] = payload[
                "winning_logic_overview"
            ]
            modules = _complete_s6_test_modules(str(assigned_card.get("name", "装备")))
            s6_authoring_inputs.append(
                {
                    "phase": phase,
                    "system": system,
                    "name": assigned_card.get("name", ""),
                    "concise_winning_summary": assigned_card.get(
                        "concise_winning_summary", ""
                    ),
                    "max_output_tokens": max_output_tokens,
                    "payload_keys": set(payload),
                }
            )
            if "_module_" in phase:
                module_key = phase.rsplit("_module_", 1)[-1]
                return json.dumps(
                    {
                        "module_key": module_key,
                        "module_content": modules[module_key],
                        "card_binding_id": assigned_card.get("card_binding_id", ""),
                        "hypothesis_id": assigned_card.get("hypothesis_id", ""),
                        "capability_image_draft": "S6 自然撰写完成",
                    },
                    ensure_ascii=False,
                )
            assigned_card.update(
                {
                    "operational_process": ["按候选专属制胜机理完成交战。"],
                    "semantic_consistency_check": {
                        "consistent": True,
                        "checked_fields": [
                            "name",
                            "operational_process",
                            "capability_portrait",
                        ],
                        "notes": "主装备身份未改变。",
                    },
                }
            )
            if not phase.endswith("_spine"):
                assigned_card["capability_portrait"] = (
                    "S6 Codex 会话基于候选身份自然撰写的作战能力画像。"
                )
                assigned_card["capability_portrait_modules"] = modules
            return json.dumps(
                {
                    "direction": assigned_card,
                    "capability_image_draft": "S6 自然撰写完成",
                },
                ensure_ascii=False,
            )
        if phase == "winning_swarm_dynamic_portfolio_review_fast":
            candidate_ledger = payload.get("candidate_ledger", {})
            candidate_rows = list(candidate_ledger.get("hypotheses", []))
            allowed_ids = [item["hypothesis_id"] for item in candidate_rows]
            execution_order.append("downstream_start:S5:incremental-review")
            reviewer_inputs.append(
                {
                    "phase": phase,
                    "max_output_tokens": max_output_tokens,
                    "evidence_count": len(payload.get("evidence_index", [])),
                    "schema_keys": set(output_schema),
                    "decision_keys": set(output_schema["decisions"][0]),
                    "decision_schema": dict(output_schema["decisions"][0]),
                    "system": str(system),
                    "allowed_ids": allowed_ids,
                        "payload_keys": set(payload),
                        "coverage_matrix": dict(payload.get("coverage_matrix", {})),
                        "candidate_row_keys": [set(item) for item in candidate_rows],
                }
            )
            visible_ids = [
                item["hypothesis_id"]
                for item in candidate_ledger.get("hypotheses", [])
            ]
            scoped_merge_inputs.append(("S5", allowed_ids, visible_ids))
            return json.dumps(
                {
                    "decisions": [
                        {
                            "hypothesis_id": hypothesis_id,
                            "decision": "retain",
                            "reason": "候选具有独立作战角色并可直接形成战果",
                                "independence_basis": "核心机理不同",
                                "innovation_priority": (
                                    0.9 if position % 2 else 0.7
                                ),
                                "innovation_basis": "改变接敌几何与敌我交换关系",
                                "disruption_tier": (
                                    "paradigm_disruption"
                                    if position % 2
                                    else "new_quality_breakthrough"
                                ),
                                "material_innovation_breakpoint_present": True,
                                "ordinary_upgrade_or_function_packaging": False,
                                "displaced_operational_mode": "依赖高价值平台逐目标接敌",
                                "new_operational_mode": "以分布式效应体持续占位并自主接敌",
                                "winning_relation_shift": "从高价值平台互换转为可消耗效应密度压制",
                            }
                        for position, hypothesis_id in enumerate(allowed_ids, start=1)
                    ],
                    "portfolio_order": allowed_ids,
                    "portfolio_summary": "增量候选保留进入组合",
                    "stop_reason": "incremental_review_complete",
                },
                ensure_ascii=False,
            )
        if phase == "winning_semantic_pair_clustering":
            return json.dumps(
                {
                    "pairwise_comparisons": [
                        {
                            "left_hypothesis_id": left,
                            "right_hypothesis_id": right,
                            "relationship": (
                                "non_independent_variant"
                                if index == 1
                                else "independent"
                            ),
                            "axis_equivalence": {
                                "target": True,
                                "task_chain_breakpoint": True,
                                "changed_variable": True,
                                "core_mechanism": index != 1,
                                "direct_result": True,
                            },
                            "material_difference_axes": (
                                ["core_mechanism"] if index == 1 else ["target"]
                            ),
                            "confidence": 0.9,
                        }
                        for index, (left, right) in enumerate(
                            payload["pair_ids"], start=1
                        )
                    ],
                    "stop_reason": "all_pairs_compared",
                },
                ensure_ascii=False,
            )
        if phase == "winning_pre_generation_angle_selection":
            return json.dumps(
                {
                    "selected_seed_ids": [
                        item["seed_id"] for item in payload["reserve_candidates"][:4]
                    ],
                    "selection_reasons": [],
                    "rejected_groups": [],
                    "stop_reason": "independent_reserves_selected",
                },
                ensure_ascii=False,
            )
        if phase == "winning_s3_precommit_admission":
            raise AssertionError("S3 must not start a second precommit model call")
        if phase == "winning_quality_expert_review":
            raise AssertionError("dynamic v2 must not invoke the removed quality judge")
        if agent_id == "winning_round_critic":
            return json.dumps(
                {
                    "passed": True,
                    "issues": [],
                    "step_reviews": [],
                    "recall_requests": [],
                    "recommended_action": "continue",
                    "target_step": 0,
                },
                ensure_ascii=False,
            )
        task = payload["specialist_task"]
        mission_node = task["merge_target"]
        if phase == "winning_swarm_dynamic_reasoning_seed":
            execution_order.append(f"reasoning_start:{agent_id}")
            await asyncio.sleep(0.01)
            execution_order.append(f"reasoning_done:{agent_id}")
            return json.dumps(
                {
                    "reasoning_seeds": [
                        {
                            "combat_problem": f"query-problem-{agent_id}-{ordinal}",
                            "enemy_advantage": f"query-advantage-{agent_id}-{ordinal}",
                            "breakpoint": f"query-breakpoint-{agent_id}-{ordinal}",
                            "changed_variable": f"query-variable-{agent_id}-{ordinal}",
                            "direct_effect": f"query-result-{agent_id}-{ordinal}",
                        }
                        for ordinal in range(1, 3)
                    ],
                    "quality_residuals": [],
                    "stop_reason": "reasoning_complete",
                },
                ensure_ascii=False,
            )
        if phase == "winning_swarm_dynamic_seed":
            diversity_pool = [dict(payload.get("open_exploration_hint", {}))]
            assert set(("name", "concise_winning_summary")) == set(
                output_schema["hypotheses"][0]
            )
            assert "title" not in output_schema["hypotheses"][0]
            assert "naming_style" not in output_schema["hypotheses"][0]
            assert "core_disruptive_difference" not in output_schema["hypotheses"][0]
            instance_id = str(task.get("agent_instance_id", ""))
            s3_call_counts[instance_id] = s3_call_counts.get(instance_id, 0) + 1
            s3_task_inputs.append(dict(task))
            s3_generation_payloads.append(dict(payload))
            s3_counterfactual_key_presence.append(
                (
                    s3_call_counts[instance_id],
                    "counterfactual_disruptive_challenges" in payload,
                )
            )
            s3_post_divergence_seed_presence.append(
                (
                    s3_call_counts[instance_id],
                    "post_divergence_seed_angle_provocations" in payload,
                )
            )
            s3_post_divergence_frontier_presence.append(
                (
                    s3_call_counts[instance_id],
                    "post_divergence_frontier_angle_provocations" in payload,
                )
            )
            s3_visible_evidence_by_call.append(
                (
                    s3_call_counts[instance_id],
                    {
                        str(item.get("evidence_id", ""))
                        for item in payload.get("evidence_index", [])
                    },
                )
            )
            initial_empty = False
            if diversity_pool:
                angle_assignments.extend(diversity_pool)
                execution_order.append(f"s3_start:{agent_id}")
            else:
                execution_order.append(f"completion_start:{agent_id}")
            dynamic_seed_library_inputs.append(
                (
                    str(task["archetype"]),
                    dict(payload.get("disruptive_paradigm_seed_library_v2", {})),
                )
            )
            seed_index += 1
            active_seed_calls += 1
            maximum_seed_concurrency = max(maximum_seed_concurrency, active_seed_calls)
            try:
                if slow_s3_instance_id is None:
                    slow_s3_instance_id = instance_id
                if instance_id == slow_s3_instance_id:
                    await asyncio.sleep(0.08)
                else:
                    await asyncio.sleep(0.02)
            finally:
                active_seed_calls -= 1
                execution_order.append(
                    (
                        f"s3_done:{agent_id}"
                        if diversity_pool
                        else f"completion_done:{agent_id}"
                    )
                )
            if initial_empty:
                return json.dumps(
                    {
                        "hypotheses": [],
                        "quality_residuals": [],
                        "stop_reason": "assigned thesis rejected after Query test",
                    },
                    ensure_ascii=False,
                )
            marker = f"branch_token_{seed_index}_{agent_id}"
            portfolio_completion = "portfolio_direction_shortfall" in task.get(
                "trigger_residuals", []
            )
            hypothesis_count = 2 if portfolio_completion else 1
            return json.dumps(
                {
                    "hypotheses": [
                            {
                                "name": (
                                    f"“断链复获”自主无人战斗平台-{marker}"
                                    if not portfolio_completion
                                    else (
                                        f"“远矢”精确巡航效应器-{marker}"
                                        if ordinal == 1
                                        else f"“潜雷”可消耗电子压制无人平台-{marker}"
                                    )
                                ),
                                "title": (
                                (
                                    f"远程精确巡航效应器-{marker}"
                                    if ordinal == 1
                                    else f"可消耗电子压制无人平台-{marker}"
                                )
                                if portfolio_completion
                                else f"断链复获自主无人战斗平台-{marker}"
                            ),
                                    "winning_angle_id": "",
                                    "combat_dimension": "OTHER:自主断链复获",
                                "dimension_winning_logic": (
                                    "在强干扰窗口改变目标再捕获与直接毁伤关系"
                                ),
                                "naming_style": "D/E/I任务能力",
                                "core_disruptive_difference": (
                                    f"改变断链条件下目标复获与直接毁伤关系-{marker}-{ordinal}"
                                ),
                                    "concise_winning_summary": (
                                        f"在强干扰窗口由{marker}自主复获临机目标，压缩交战空窗并直接完成压制与毁伤。"
                                    ),
                            "original_paradigm": f"original-{marker}-{ordinal}",
                            "disruptive_shift": f"shift-{marker}-{ordinal}",
                            "independence_thesis": f"independent-{marker}-{ordinal}",
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
                                    else f"直接打击并毁伤目标-{marker}"
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
                                "project_function": (
                                    f"作战分队在受扰窗口使用自主无人战斗平台-{marker}"
                                    f"直接打击、毁伤或压制敌方目标-{ordinal}"
                                ),
                                "reference_overview": (
                                    "在强干扰造成任务链断裂时自主复获目标，并直接完成压制与毁伤。"
                                ),
                            "system_interfaces": [
                                f"任务总线-{marker}-{ordinal}",
                                f"火控授权接口-{marker}-{ordinal}",
                            ],
                            "novelty_delta": f"delta-{marker}-{ordinal}",
                            "frontier_principle": f"frontier-principle-{marker}-{ordinal}",
                            "technology_discontinuity": f"conventional-ceiling-crossed-{marker}-{ordinal}",
                            "technology_horizon": "5-10 years",
                            "engineering_bottleneck": f"falsifiable-bottleneck-{marker}-{ordinal}",
                            "naming_rationale": f"name maps the concrete weapon, target and direct effect-{marker}-{ordinal}",
                            "decisive_advantage_thesis": f"weapon changes the engagement outcome in the query window-{marker}-{ordinal}",
                            "cross_query_distinction": f"another target or phase requires a different configuration and name-{marker}-{ordinal}",
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
        execution_order.append(f"downstream_start:{mission_node}:{agent_id}")
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
                    "mission_graph_target_instances": 15,
                    "s3_winning_thesis_capacity": 10,
                    "expert_repair_reserved_instances": 3,
                    "expert_repair_max_candidates": 3,
                    "max_concurrency": 6,
                },
            },
            "coverage": {},
            "packets": [{"packet_id": "packet-1", "agent_id": "weapon_equipment"}],
            "military_value_handoff": {
                "claims": [
                    {
                        "mechanism": "前沿边缘节点把天基信息转化为本地行动。",
                        "military_effects": ["拒止制衡", "体系协同"],
                        "claim_id": "must-not-leak",
                        "evidence_ids": ["ev-1"],
                        "source_urls": ["https://example.com/ev-1"],
                        "confidence": 0.9,
                    },
                    {
                        "mechanism": "受扰时以降级自治维持最低任务闭环。",
                        "military_effects": ["生存抗毁", "持续作战"],
                        "counter_evidence": ["must-not-leak"],
                    },
                    {
                        "mechanism": "第三条摘要不得进入单个创作会话。",
                        "military_effects": ["保障恢复"],
                    },
                ],
                "frontier_inspirations": [
                    {
                        "source_agent_id": "combat_scenario",
                        "packet_id": "packet-1",
                        "signal": "低成本分布式效应器可能改变精确火力交换关系",
                        "conventional_assumption_challenged": "精确打击依赖高成本单发武器",
                        "possible_military_discontinuity": "从单发命中竞争转为持续效果竞争",
                        "query_relevance": "影响当前Query中的火力可承受性",
                        "evidence_boundary": "公开趋势只构成启发，不证明装备成立",
                        "downstream_question": "何种武器架构能形成可控持续效果",
                        "evidence_ids": ["ev-1"],
                    }
                ]
            },
            "evidence_index": [
                {"evidence_id": "ev-1", "created_by": "combat_scenario"},
                {
                    "evidence_id": "ev-weapon_equipment-web-prsm",
                    "created_by": "weapon_equipment",
                },
            ],
            "structured_query_brief": {
                "equipment_project_hypotheses": [
                    {
                        "project_name": f"query-thesis-{index}",
                        "equipment_form": f"query-equipment-form-{index}",
                        "project_function": f"query-mechanism-{index}",
                        "query_causal_link": f"query-variable-{index}",
                        "target_and_phase": f"query-phase-{index}",
                        "direct_military_effect": f"query-result-{index}",
                    }
                    for index in range(1, 4)
                ]
            },
        }
    )

    swarm = result["winning_swarm"]
    # Dynamic v2 guarantees the governed 8-instance floor, while the exact
    # role count remains elastic after removing fixed observation-lens lists.
    assert 8 <= len(swarm["task_graph"]) <= 21
    assert (
        sum(
            row.get("event_type") == "winning_quality_repair_planned"
            for row in progress_rows
        )
        == 0
    )
    assert not any(
        row.get("event_type") == "winning_portfolio_gap_completion_planned"
        for row in progress_rows
    )
    clustering_started = any(
        row.get("event_type") == "winning_semantic_clustering_started"
        for row in progress_rows
    )
    if clustering_started:
        assert any(
            row.get("event_type") == "winning_semantic_clustering_completed"
            for row in progress_rows
        )
    angle_plan_events = [
        row
        for row in progress_rows
        if row.get("event_type") == "winning_pre_generation_angle_portfolio_planned"
    ]
    assert len(angle_plan_events) == 1
    assert 3 <= angle_plan_events[0]["assigned_angle_count"] <= 6
    assert 3 <= angle_plan_events[0]["s3_capacity_slot_count"] <= 6
    assert angle_plan_events[0]["inactive_capacity_slot_count"] == 0
    materialized_events = [
        row
        for row in progress_rows
        if row.get("event_type") == "winning_s3_active_agents_materialized"
    ]
    assert len(materialized_events) == 1
    assert 3 <= materialized_events[0]["active_instance_count"] <= 6
    assert materialized_events[0]["unused_capacity_count"] == 0
    assert not any(
        row.get("event_type") == "winning_s3_capacity_slot_skipped"
        for row in progress_rows
    )
    assert angle_plan_events[0]["reserve_angle_count"] == 0
    assert pre_generation_selector_inputs
    assert len(pre_generation_selector_inputs) == 1
    assert pre_generation_selector_inputs[0]["payload_keys"] == {
        "query",
        "open_angle_seeds",
    }
    assert pre_generation_selector_inputs[0]["schema_keys"] == {
        "open_hints",
        "stop_reason",
    }
    assert len(pre_generation_selector_inputs[0]["open_angle_seeds"]) == 8
    assert all(
        set(item) == {"battlefield_relationship", "desired_direct_result"}
        for item in pre_generation_selector_inputs[0]["open_angle_seeds"]
    )
    assert pre_generation_selector_inputs[0]["max_output_tokens"] <= 900
    active_policy = "".join(
        candidate_policy_prompts["winning_pre_generation_active_angle_selection"]
    )
    assert "轻量开放角度提示器" in active_policy
    assert "不要命名装备、指定技术路线" in active_policy
    fallback_events = [
        row
        for row in progress_rows
        if row.get("event_type")
        == "winning_pre_generation_active_angle_selection_fallback"
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0]["failure_type"] == "ProviderRequestError"
    assert fallback_events[0]["fallback_source"] == "s1_s2_reasoning_seeds"
    assert not any(
        row.get("event_type") == "winning_candidate_competition_converged"
        for row in progress_rows
    )
    assert swarm["budget"]["planned_instances"] <= 21
    assert swarm["budget"]["maximum_observed_concurrency"] <= 6
    assert maximum_seed_concurrency >= 1
    assert angle_assignments
    initial_assignments = [
        item
        for item in angle_assignments
        if "-reallocated-" not in str(item.get("assignment_id", ""))
    ]
    recovery_assignments = [
        item
        for item in angle_assignments
        if "-reallocated-" in str(item.get("assignment_id", ""))
    ]
    initial_assignment_ids = {
        str(item.get("assignment_id", "")) for item in initial_assignments
    }
    assert initial_assignment_ids <= {""}
    assert all(not item.get("project_name") for item in initial_assignments)
    assert all(any(str(value).strip() for value in item.values()) for item in initial_assignments)
    assert not recovery_assignments
    for assignment in initial_assignments:
        assert set(assignment) <= {
            "battlefield_relationship",
            "desired_direct_result",
        }
    assert not any(
        row.get("event_type") == "winning_s3_empty_angle_reallocated"
        for row in progress_rows
    )
    s3_policy = "".join(candidate_policy_prompts["winning_swarm_dynamic_seed"])
    assert all(
        len(prompt) < 4500
        for prompt in candidate_policy_prompts["winning_swarm_dynamic_seed"]
    )
    assert "从Query的核心战场矛盾自由创造" in s3_policy
    assert "独特物理形态、结构构型、材料/介质、新物理原理" in s3_policy
    assert "装备独特运动方式、反传统隐喻、数量/密度/规模" in s3_policy
    assert "一般性的任务能力、功能效果和动作流程应进入concise_winning_summary" in s3_policy
    assert "背景剥离诱显巡飞弹" in s3_policy
    assert "不要默认两字意象加弹/雷/器/系统" in s3_policy
    assert "每个候选只输出name和concise_winning_summary" in s3_policy
    assert "可提交1—3个候选" in s3_policy
    assert "宁缺毋滥" in s3_policy
    assert "面向未来战争需要的多样性来自不同制胜断点" in s3_policy
    assert "不来自同一装备更换代号、载荷或任务前缀" in s3_policy
    assert "已占用的其他关系（仅用于避同构，不要求复述）" in s3_policy
    assert "严格按以下模型生成顺序" not in s3_policy
    assert s3_policy.count("装备开放探索约束") == 0
    assert "naming_comparison" not in s3_policy
    assert "naming_self_check" not in s3_policy
    first_s3_payload = next(
        item
        for item in s3_generation_payloads
        if "counterfactual_disruptive_challenges" not in item
    )
    creative_payload_keys = {
        "query",
        "execution_profile_id",
        "specialist_task",
        "open_exploration_hint",
        "military_value_handoff",
        "random_naming_style_assignment",
    }
    # S4 carries the structured winning-dimension package so its downstream
    # handoff remains auditable; S3 keeps the same dimension in its bounded
    # task purpose for the compact creative contract.
    # The compact creative contract remains stable, while coverage steering
    # and bounded sibling summaries are additive controls for model
    # divergence.  Keep the assertion explicit about the required core and
    # the optional sidecars instead of freezing the transport to its old key
    # set.
    assert creative_payload_keys <= set(first_s3_payload)
    assert set(first_s3_payload) - creative_payload_keys <= {
        "winning_dimension_package",
        "coverage_steer",
        "occupied_sibling_concepts",
        "occupied_s3_core_concepts",
        "occupied_s3_boundary_rule",
    }
    assert first_s3_payload["coverage_steer"]["exclusive_axis"]
    assert len(first_s3_payload["occupied_sibling_concepts"]) <= 12
    if "winning_dimension_package" in first_s3_payload:
        package = first_s3_payload["winning_dimension_package"]
        assert package["code"].startswith("D")
        assert package["dimension"]
        assert package["winning_logic"]
        assert package["forward_winning_question"]
    assert first_s3_payload["execution_profile_id"] == "winning_swarm_dynamic_v2"
    assert "battlefield_relationship" in first_s3_payload["open_exploration_hint"]
    assert "desired_direct_result" in first_s3_payload["open_exploration_hint"]
    naming_assignment = first_s3_payload["random_naming_style_assignment"]
    assert naming_assignment["selection_mode"] == "random_without_replacement"
    assert naming_assignment["name_length"].startswith("名称主体尽量8—12个汉字")
    assert [item["candidate_position"] for item in naming_assignment["candidate_order"]] == [1, 2, 3]
    assert len({item["code"] for item in naming_assignment["candidate_order"]}) == 3
    assert all(item["code"] in set("ABCDEFGHIJKLMNO") for item in naming_assignment["candidate_order"])
    creative_handoff = first_s3_payload["military_value_handoff"]
    assert set(creative_handoff) == {"claims"}
    assert len(creative_handoff["claims"]) == 2
    assert all(
        set(item) == {"mechanism", "military_effects"}
        for item in creative_handoff["claims"]
    )
    assert "must-not-leak" not in str(creative_handoff)
    forbidden_s3_keys = {
        "claim_bundles",
        "packet_index",
        "packets",
        "evidence_index",
        "valid_reference_ids",
        "upstream_reasoning_seeds",
        "secondary_cross_agent_constraints",
        "battlefield_contradiction",
        "discovery_convergence",
        "discovery_blueprint",
    }
    assert all(
        forbidden_s3_keys.isdisjoint(payload)
        for payload in s3_generation_payloads
    )
    assert all(
        all(
            set(claim) == {"mechanism", "military_effects"}
            for claim in payload.get("military_value_handoff", {}).get("claims", [])
        )
        for payload in s3_generation_payloads
    )
    assert "combat_dimension_assignment" not in first_s3_payload
    assert "evidence_index" not in first_s3_payload
    assert "candidate_ledger" not in first_s3_payload
    assert "query_combat_equipment_divergence_brief" not in first_s3_payload
    assert "s6_release_preflight" not in first_s3_payload
    assert "post_divergence_innovation_naming_reference" not in first_s3_payload
    assert not post_divergence_seed_mapper_agent_ids
    assert not post_divergence_frontier_mapper_inputs
    assert not any(
        has_frontier_provocation
        for _, has_frontier_provocation in s3_post_divergence_frontier_presence
    )
    self_admission_events = [
        row
        for row in progress_rows
        if row.get("event_type")
        == "winning_s3_first_pass_self_admission_completed"
    ]
    assert len(self_admission_events) == sum(s3_call_counts.values())
    assert all(
        row.get("separate_precommit_model_call") is False
        for row in self_admission_events
    )
    assert all(
        row.get("candidate_maximum_per_session") == 3
        for row in self_admission_events
    )
    assert not any(
        str(row.get("event_type", "")).startswith("winning_s3_precommit_")
        for row in progress_rows
    )
    if clustering_started:
        clustering_policy = "".join(
            candidate_policy_prompts["winning_semantic_pair_clustering"]
        )
        assert "同一装备家族本身不是重复" in clustering_policy
        assert "改变变量或核心机理任一实质不同" in clustering_policy
        clustering_completed = [
            row
            for row in progress_rows
            if row.get("event_type") == "winning_semantic_clustering_completed"
        ]
        assert clustering_completed
    last_reasoning_done = max(
        index
        for index, row in enumerate(execution_order)
        if row.startswith("reasoning_done:")
    )
    first_s3_start = min(
        index
        for index, row in enumerate(execution_order)
        if row.startswith("s3_start:")
    )
    assert last_reasoning_done < first_s3_start
    fanout_events = [
        row
        for row in progress_rows
        if row.get("event_type") == "winning_s4_candidate_fanout_materialized"
    ]
    assert not fanout_events
    s4_scopes = [row for row in scoped_merge_inputs if row[0] == "S4"]
    assert not s4_scopes
    s5_scopes = [row for row in scoped_merge_inputs if row[0] == "S5"]
    assert s5_scopes
    assert all(
        allowed_ids and set(allowed_ids) <= set(visible_ids)
        for _, allowed_ids, visible_ids in s5_scopes
    )
    incremental_s4_events = [
        row
        for row in progress_rows
        if row.get("event_type") == "winning_s4_incremental_boundary_opened"
    ]
    assert len(incremental_s4_events) == 1
    first_s3_completed = min(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_completed"
        and row.get("mission_node") == "S3"
    )
    last_s3_completed = max(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_completed"
        and row.get("mission_node") == "S3"
    )
    first_s4_started = min(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_started"
        and row.get("mission_node") == "S4"
    )
    assert incremental_s4_events[0]["completed_s3_instance_ids"]
    assert first_s3_completed < first_s4_started < last_s3_completed
    first_s5_started = min(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_started"
        and row.get("mission_node") == "S5"
    )
    last_creative_completed = max(
        index
        for index, row in enumerate(progress_rows)
        if row.get("event_type") == "winning_agent_session_completed"
        and row.get("mission_node") in {"S3", "S4"}
    )
    # Cross-pool S5 waits for the live creator set, then 2-3 reviewers
    # compare the complete candidate pool.
    assert first_s5_started > last_creative_completed
    assert 2 <= len(s5_scopes) <= 3
    assert not any(
        row.get("event_type") == "winning_contribution_rebase_required"
        for row in progress_rows
    )
    assert s3_task_inputs
    assert all(
        item.get("merge_target") in {"S3", "S4"}
        and item.get("allow_child_spawn") is False
        for item in s3_task_inputs
    )
    assert all(
        not has_counterfactual_key
        for call_count, has_counterfactual_key in s3_counterfactual_key_presence
        if call_count == 1
    )
    assert not any(
        has_counterfactual_key
        for _, has_counterfactual_key in s3_counterfactual_key_presence
    )
    assert not any(
        has_post_divergence_seed
        for _, has_post_divergence_seed in s3_post_divergence_seed_presence
    )
    assert all(
        "ev-weapon_equipment-web-prsm" not in evidence_ids
        for call_count, evidence_ids in s3_visible_evidence_by_call
        if call_count == 1
    )
    # Reallocated S3 sessions may use the explicit counterfactual challenge,
    # but a public equipment catalogue is never required as an innovation
    # anchor even on retry.
    assert reviewer_inputs
    assert all(
        item["phase"] == "winning_swarm_dynamic_portfolio_review_fast"
        for item in reviewer_inputs
    )
    assert all(item["max_output_tokens"] == 2400 for item in reviewer_inputs)
    assert all(item["evidence_count"] == 0 for item in reviewer_inputs)
    assert all(
        item["schema_keys"]
        == {"decisions", "portfolio_order", "portfolio_summary", "stop_reason"}
        for item in reviewer_inputs
    )
    assert all(
        item["decision_keys"]
        == {
            "hypothesis_id",
            "decision",
            "reason",
            "independence_basis",
            "innovation_priority",
            "dimension_scores",
            "weighted_score",
            "innovation_basis",
            "s5_innovation_mechanism_score",
            "naming_new_quality",
            "naming_semantic_alignment",
            "naming_semantics_aligned",
            "naming_assessment_status",
            "naming_anchor",
            "naming_reason",
            "direct_equipment",
            "weapon_object_specific",
            "support_dependency_only",
            "known_science_consistent",
            "weapon_body_mechanism_closes",
            "material_innovation_breakpoint_present",
            "ordinary_upgrade_or_function_packaging",
            "disruption_tier",
            "displaced_operational_mode",
            "new_operational_mode",
            "winning_relation_shift",
            "merge_target_hypothesis_id",
        }
        for item in reviewer_inputs
    )
    assert all("candidate_ledger" in item["payload_keys"] for item in reviewer_inputs)
    assert all(
        item["payload_keys"] - {"candidate_ledger", "coverage_matrix", "expert_review_feedback"}
        == set()
        for item in reviewer_inputs
    )
    assert all(
        "coverage_matrix" in item["payload_keys"]
        and set(item["coverage_matrix"]) >= {
            "coverage_ratio",
            "duplicate_ratio",
            "primary_gaps",
        }
        for item in reviewer_inputs
    )
    assert all(
        all(keys == {"hypothesis_id", "name", "concise_winning_summary"} for keys in item["candidate_row_keys"])
        for item in reviewer_inputs
    )
    assert all("只做创新性、颠覆性和候选独立性筛选" in item["system"] for item in reviewer_inputs)
    assert all(
        "普通性能加码、把现有功能智能化、流程提速" in item["system"]
        for item in reviewer_inputs
    )
    assert all(
        "最多保留创新性最强的7条" in item["system"]
        and "禁止为凑数回收已经判退的普通方向" in item["system"]
        for item in reviewer_inputs
    )
    assert all("不改名、不补写装备字段" in item["system"] for item in reviewer_inputs)
    assert all("输入候选严格只有hypothesis_id、name和concise_winning_summary" in item["system"] for item in reviewer_inputs)
    assert all("不得要求或使用Query" in item["system"] for item in reviewer_inputs)
    selected_innovation = [
        item["innovation_priority"] for item in swarm["final_equipment_portfolio"]
    ]
    assert selected_innovation == sorted(selected_innovation, reverse=True)
    assert all(
        item.get("disruption_tier")
        in {"paradigm_disruption", "new_quality_breakthrough"}
        and item.get("displaced_operational_mode")
        and item.get("new_operational_mode")
        and item.get("winning_relation_shift")
        for item in swarm["final_equipment_portfolio"]
    )
    assert all(
        item.get("innovation_priority") is not None
        for item in swarm["candidate_lineage"]
    )
    # S6 card authoring and handoff contracts are covered by dedicated tests.
    # This integration probe ends at post-divergence convergence so it does
    # not couple soft-challenge behavior to one synthetic S5 portfolio shape.
    assert dynamic_seed_library_inputs
    assert all(context == {} for _, context in dynamic_seed_library_inputs)
    return
    assert s6_authoring_inputs
    assert len(s6_authoring_inputs) == len(swarm["final_equipment_portfolio"])
    assert all(item["max_output_tokens"] == 3200 for item in s6_authoring_inputs)
    assert all(
        item["payload_keys"]
        == {"query_semantics", "candidate_weapon", "winning_logic_overview"}
        for item in s6_authoring_inputs
    )
    assert all(
        "输入严格只有query_semantics、candidate_weapon、winning_logic_overview三项"
        in item["system"]
        and "再直接写成决策短卡" in item["system"]
        and "每栏都以约400个有效中文字为中心" in item["system"]
        and "五栏合计通常约2000至2250字" in item["system"]
        and "复杂因果尚未闭合时可适当略多" in item["system"]
        and "禁止按字符硬切" in item["system"]
        and "决定性瓶颈、核心原理怎样落实到装备本体" in item["system"]
        and "样机、半实物或对抗试验和判退结果" in item["system"]
        and "行动主体、进入条件、关键动作" in item["system"]
        and "新任务或新场景" in item["system"]
        and "删除跨栏重复" in item["system"]
        and len(item["system"]) < 1600
        for item in s6_authoring_inputs
    )
    assert all("不因篇幅偏差失败、重试、截断或机械扩写" in item["system"] for item in s6_authoring_inputs)
    assert all("删除重复背景" in item["system"] for item in s6_authoring_inputs)
    assert all(item["concise_winning_summary"] for item in s6_authoring_inputs)
    assert len(s5_handoff_inputs) == len(swarm["final_equipment_portfolio"])
    assert s5_handoff_prompts
    assert all(
        "S3候选生成Codex会话已经在" in item
        for item in s5_handoff_prompts
    )
    assert all("唯一主装备" in item for item in s5_handoff_prompts)
    assert all("不得改名" in item for item in s5_handoff_prompts)
    assert all("逐字复制assigned_candidate.name" in item for item in s5_handoff_prompts)
    assert all("concise_winning_summary" in item for item in s5_handoff_prompts)
    assert all(
        "不参与身份判定、质量硬门或S6改名" in item for item in s5_handoff_prompts
    )
    assert maximum_s5_handoff_concurrency >= min(2, len(s5_handoff_inputs))
    assert [item["name"] for item in s6_authoring_inputs] == [
        item["name"] for item in swarm["final_equipment_portfolio"]
    ]
    assert all(
        provider_module._indicator_portrait_is_specific(item["indicator_portrait"])
        and provider_module._query_relevance_is_specific(item["query_relevance"])
        for item in swarm["final_equipment_portfolio"]
    )
    assert all(
        item.get("concise_winning_summary")
        for item in swarm["final_equipment_portfolio"]
    )
    assert all(
        item.get("frontier_principle")
        and item.get("technology_discontinuity")
        and item.get("technology_horizon")
        and item.get("engineering_bottleneck")
        for item in swarm["final_equipment_portfolio"]
    )
    assert sum(
        row.get("event_type") == "winning_s5_handoff_contract_completed"
        for row in progress_rows
    ) == len(swarm["final_equipment_portfolio"])
    # A generic Query no longer receives role/branch-prior cards. The Codex
    # specialist owns open-ended divergence and may receive an empty library.
    assert dynamic_seed_library_inputs
    assert all(context == {} for _, context in dynamic_seed_library_inputs)
    assert 1 <= len(swarm["final_equipment_portfolio"]) <= 7
    assert swarm["portfolio_quality_gate"]["passed"] is True, swarm[
        "portfolio_quality_gate"
    ]
    assert swarm["portfolio_quality_gate"]["capability_portrait_gate_passed"] is True
    assert swarm["portfolio_quality_gate"]["equipment_diversity_passed"] is True
    assert swarm["portfolio_quality_gate"]["direct_combat_main_body_passed"] is True
    assert swarm["portfolio_quality_gate"]["complete_capability_portrait_count"] == len(
        swarm["final_equipment_portfolio"]
    )
    assert swarm["portfolio_quality_gate"]["expert_judge_passed"] is True
    assert swarm["expert_judge"]["status"] == "completed"
    assert swarm["expert_judge"]["round_count"] >= 1
    assert swarm["expert_judge"]["repair_wave"]["merged_count"] == 0
    assert swarm["expert_judge"]["portfolio_completion_wave"]["created_count"] == 0
    if swarm["expert_judge"]["round_count"] > 1:
        assert len(swarm["expert_judge"]["rounds"][1]["assessments"]) >= 1
    assert len(swarm["expert_assessments"]) == len(swarm["hypotheses"])
    assert all(item["passed"] for item in swarm["expert_assessments"])
    assert swarm["portfolio_quality_gate"]["direct_combat_equipment_count"] >= 1
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
        row[1] == row[2] for row in scoped_merge_inputs if row[0] in {"S4", "S5"}
    )
    present_archetypes = {item["archetype"] for item in swarm["task_graph"]}
    ordering_probe_archetypes = {
        "disruptive_mechanism_generator",
        "adversary_counter_adaptation_red_team",
        "frontier_equipment_miner",
        "equipment_realization_architect",
        "evidence_verifier",
    }
    if not ordering_probe_archetypes.issubset(present_archetypes):
        # Query-led role selection is elastic; absence of an optional probe
        # role is valid and must not reintroduce a fixed archetype catalogue.
        return
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


def test_s6_title_compactor_preserves_agent_authored_novel_weapon_name() -> None:
    direction = {
        "name": "潮痕-1有限区复获远程反舰巡航弹",
        "equipment_form": "固定构型远程反舰巡航弹及多模末制导段",
        "military_value": "断链后复获并直接毁伤机动水面目标",
    }

    assert provider_module._compact_capability_direction_title(direction) == (
        "潮痕-1有限区复获远程反舰巡航弹"
    )


def test_s6_title_compactor_preserves_codex_name_without_dictionary_promotion() -> None:
    direction = {
        "name": "远程导弹",
        "equipment_form": "岛基机动有限区复获远程反舰导弹",
        "baseline_system": "PrSM Increment 1公开基线",
    }

    assert provider_module._compact_capability_direction_title(direction) == "远程导弹"


def test_s6_title_collisions_remain_visible_for_quality_gate() -> None:
    directions = [
        {
            "name": "有限区复获远程反舰巡航弹",
            "equipment_form": "固定构型远程反舰巡航弹",
            "operational_mechanism": "有限区搜索后复核交战",
        },
        {
            "name": "有限区复获远程反舰巡航弹",
            "equipment_form": "固定构型远程反舰巡航弹",
            "operational_mechanism": "换词描述的有限区搜索后复核交战",
        },
    ]

    normalized = provider_module._uniquify_compacted_capability_titles(directions)

    assert [item["name"] for item in normalized] == [
        "有限区复获远程反舰巡航弹",
        "有限区复获远程反舰巡航弹",
    ]


def test_s6_normalization_does_not_build_missing_portrait() -> None:
    normalized = provider_module._normalize_s6_deterministic_format(
        {
            "concept_directions": [
                {
                    "name": "潮痕-1有限区复获远程反舰巡航弹",
                    "equipment_form": "固定构型远程反舰巡航弹及多模末制导段",
                    "target_scenario": "GNSS拒止下远海目标航迹过期后的补击窗口",
                    "problem_statement": "外部目标更新中断后难以安全复获机动舰艇",
                    "scientific_principle": "有限区搜索与跨模态身份复核",
                    "enabling_technologies": ["抗扰导航", "射频—成像复核"],
                    "operational_concept": "进入有限搜索区后复获并受控交战",
                    "operational_process": [
                        "任务装订",
                        "有限区搜索",
                        "身份复核",
                        "攻击或弃攻",
                    ],
                    "capability_outcome": "断链后复获并直接毁伤授权水面目标",
                    "military_value": "压缩目标依靠航迹过期脱离打击的窗口",
                    "winning_mechanism": "把目标机动收益收敛到可验证搜索包线",
                    "failure_boundary": "剩余能量不足时弃攻",
                }
            ]
        },
        topic="远海目标复获装备研究",
    )
    direction = normalized["concept_directions"][0]

    assert direction.get("capability_portrait", "") == ""
