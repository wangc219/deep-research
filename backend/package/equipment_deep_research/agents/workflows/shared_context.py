"""Pure context projections shared by winning workflow implementations.

This module deliberately has no dependency on ``coordinator``.  Context
projections are data transformations, so keeping them here prevents the
coordinator, winning flow and helper modules from forming a circular import
graph.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from equipment_deep_research.agents.dynamic_prompt_resources import load_dynamic_winning_json


_INTERNAL_HANDOFF_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:S[1-6]|L[1-4])(?![A-Za-z0-9])|"
    r"Codex|Harness|Packet|Claim|Agent|智能体|循环门控|执行轨迹|物理Cohort|"
    r"候选账本|专家盲评|非支配候选|组合评审|质量门|角色合同|补写|交接状态|"
    r"退回S[1-6]|回到S[1-6]"
)


def query_domain_contract(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the equipment semantic contract from the current Query.

    The contract is deliberately model-owned. It never classifies a Query by
    keyword: the blueprint may explicitly choose ``mission_equipment`` when
    the requested object/effect is non-combat. With no explicit model choice,
    retain the project's direct-combat default so the research does not drift
    toward generic support systems.
    """

    brief = dict(structured_query_brief or {})
    del topic
    requested_mode = str(
        brief.get("query_equipment_mode")
        or brief.get("equipment_domain_mode")
        or brief.get("equipment_mode")
        or "direct_combat"
    ).strip().lower()
    non_combat_mode = requested_mode == "mission_equipment"
    if non_combat_mode:
        return {
            "mode": "mission_equipment",
            "subject_label": "可独立立项、部署和验收的检测/感知/保障装备本体",
            "direct_effect_label": "直接形成可验收的发现、识别、定位、跟踪、测量、诊断或任务恢复效果",
            "allowed_equipment_forms": ["传感器", "检测载荷", "机动检测平台", "多传感器节点", "保障/诊断装备"],
            "forbidden_subjects": ["与Query无关的进攻武器", "远程精确打击弹药", "攻击机器人", "毁伤/杀伤载荷"],
            "requires_direct_combat_weapon": False,
            "signals": {"source": "model_blueprint"},
        }
    return {
        "mode": "direct_combat",
        "subject_label": "可独立立项、研制和试验的直接战斗/打击装备本体",
        "direct_effect_label": "直接形成打击、毁伤、压制、拒止或物理拦截效果",
        "allowed_equipment_forms": ["平台", "弹药", "拦截器", "定向能或电子攻击效应器", "武装无人平台"],
        "forbidden_subjects": ["仅通信、治理、算法或保障节点"],
        "requires_direct_combat_weapon": True,
        "signals": {"source": "model_blueprint_or_default"},
    }


def _truncate_complete_text(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    candidate = text[:limit]
    sentence_end = max(candidate.rfind(mark) for mark in "。！？!?\n")
    if sentence_end >= max(80, limit // 2):
        return candidate[: sentence_end + 1].rstrip()
    return text


def clean_handoff_text(value: Any, *, limit: int | None = 360) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    text = _INTERNAL_HANDOFF_PATTERN.sub("", text)
    text = re.sub(r"(?:packet|claim|reasoning|trace)-[A-Za-z0-9_.:-]+", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip(" ；,，")
    return text if limit is None else _truncate_complete_text(text, limit=limit)


def compact_prompt_value(
    value: Any,
    *,
    max_string_chars: int = 900,
    max_list_items: int = 8,
) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_string_chars else _truncate_complete_text(value, limit=max_string_chars)
    if isinstance(value, Mapping):
        return {
            str(key): compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in value[:max_list_items]
        ]
    return value


def query_combat_equipment_divergence_brief(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project query semantics into a bounded, solution-agnostic handoff."""

    brief = dict(structured_query_brief or {})
    equipment_hypotheses = [
        {key: item for key, item in row.items() if key != "project_name"}
        for row in brief.get("equipment_project_hypotheses", [])
        if isinstance(row, Mapping)
    ]
    frontier_hypotheses = [
        {
            key: item
            for key, item in row.items()
            if key in {
                "enabling_principle", "innovation_mode", "equipment_implication",
                "query_causal_link", "direct_military_effect", "disruptive_delta",
                "conventional_absorption_limit", "technology_horizon",
                "engineering_bottleneck", "disconfirming_condition",
            }
        }
        for row in brief.get("frontier_technology_hypotheses", [])
        if isinstance(row, Mapping)
    ]
    rules = load_dynamic_winning_json(
        "common", section="query_combat_equipment_divergence.generation_rules"
    )
    if not isinstance(rules, list):
        raise ValueError("query-combat equipment generation rules must be a JSON list")
    return {
        "query": clean_handoff_text(topic, limit=600),
        "combat_problem_frame": str(brief.get("combat_problem_frame", ""))[:900]
        or "由前置Codex Agent依据完整query语义建立任务对象、对手、作战阶段和关键矛盾，不做关键词枚举匹配。",
        "enemy_target_profile": compact_prompt_value(brief.get("enemy_target_profile", []), max_string_chars=260, max_list_items=6),
        "battle_phase_and_constraints": compact_prompt_value(brief.get("battle_phase_and_constraints", []), max_string_chars=260, max_list_items=8),
        "required_direct_military_effects": compact_prompt_value(brief.get("required_direct_military_effects", []), max_string_chars=260, max_list_items=6),
        "equipment_semantic_boundary": str(brief.get("equipment_semantic_boundary", ""))[:700],
        "winning_problem_propositions": compact_prompt_value(brief.get("winning_problem_propositions", []), max_string_chars=360, max_list_items=6),
        "weapon_design_variables": compact_prompt_value(brief.get("weapon_design_variables", []), max_string_chars=260, max_list_items=8),
        "query_specific_weapon_architectures": compact_prompt_value(brief.get("query_specific_weapon_architectures", []), max_string_chars=360, max_list_items=6),
        "frontier_technology_hypotheses": compact_prompt_value(frontier_hypotheses, max_string_chars=420, max_list_items=6),
        "equipment_project_hypotheses": compact_prompt_value(equipment_hypotheses, max_string_chars=420, max_list_items=6),
        "rejected_template_anchors": compact_prompt_value(brief.get("rejected_template_anchors", []), max_string_chars=260, max_list_items=6),
        "query_domain_contract": query_domain_contract(
            topic, structured_query_brief=brief
        ),
        "conditional_priority_observation_lenses": [],
        "generation_rules": [str(item).strip() for item in rules if str(item).strip()],
    }


__all__ = [
    "clean_handoff_text",
    "compact_prompt_value",
    "query_domain_contract",
    "query_combat_equipment_divergence_brief",
]
