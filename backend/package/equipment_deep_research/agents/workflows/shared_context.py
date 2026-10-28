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

_MISSION_EQUIPMENT_QUERY_PATTERN = re.compile(
    r"(?:灾害|救援|搜救|应急|消防|医疗|抢险|公网中断|通信恢复|通信保障|"
    r"检测|监测|测绘|巡检|诊断|维修保障)"
)
_DIRECT_COMBAT_QUERY_PATTERN = re.compile(r"(?:作战|战场|敌方|对手|打击|毁伤|杀伤|压制|拦截|拒止|突防|弹药|导弹|武器)")
_NEGATION_MARKERS = (
    "不使用",
    "禁止使用",
    "避免使用",
    "不得使用",
    "不要使用",
    "不采用",
    "不涉及",
    "排除",
)
_CANDIDATE_COUNT_PATTERN = re.compile(
    r"(?:收敛为|形成|输出|给出|保留|筛选出)\s*"
    r"(?:正好|恰好|严格)?\s*"
    r"(?P<minimum>[一二三四五六七八九十两\d]+)\s*"
    r"(?:[-—~至到]\s*(?P<maximum>[一二三四五六七八九十两\d]+)\s*)?"
    r"(?:个|项|类|组|套)?\s*"
    # Users often place bounded project qualifiers between the number and
    # “候选”, for example “正好3个可独立立项、部署和试验验收的实体装备候选”.
    # Stop at sentence punctuation so the count cannot leak into a later,
    # unrelated candidate request.
    r"[^，。；！？\n]{0,48}?(?:实体装备|武器装备|装备)?\s*候选"
)
_CHINESE_NUMBER_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _bounded_chinese_integer(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
    elif text in _CHINESE_NUMBER_DIGITS:
        number = _CHINESE_NUMBER_DIGITS[text]
    elif text.startswith("十") and len(text) == 2 and text[1] in _CHINESE_NUMBER_DIGITS:
        number = 10 + _CHINESE_NUMBER_DIGITS[text[1]]
    elif text.endswith("十") and len(text) == 2 and text[0] in _CHINESE_NUMBER_DIGITS:
        number = _CHINESE_NUMBER_DIGITS[text[0]] * 10
    elif len(text) == 3 and text[1] == "十":
        left = _CHINESE_NUMBER_DIGITS.get(text[0])
        right = _CHINESE_NUMBER_DIGITS.get(text[2])
        number = left * 10 + right if left is not None and right is not None else 0
    else:
        return None
    return number if 1 <= number <= 12 else None


def requested_candidate_count_contract(topic: str) -> dict[str, Any]:
    """Preserve an explicit user-requested portfolio size across S4-S6.

    This is not a default quota.  It activates only for an unambiguous count
    next to the word ``候选`` and keeps the evidence boundary explicit so a
    model cannot satisfy the number by duplicating or fabricating directions.
    """

    match = _CANDIDATE_COUNT_PATTERN.search(str(topic or ""))
    if match is None:
        return {
            "explicit": False,
            "minimum": 0,
            "target": 0,
            "maximum": 0,
            "source": "none",
        }
    minimum = _bounded_chinese_integer(match.group("minimum"))
    maximum = _bounded_chinese_integer(match.group("maximum")) or minimum
    if minimum is None or maximum is None:
        return {
            "explicit": False,
            "minimum": 0,
            "target": 0,
            "maximum": 0,
            "source": "none",
        }
    lower, upper = sorted((minimum, maximum))
    return {
        "explicit": True,
        "minimum": lower,
        "target": lower if lower == upper else upper,
        "maximum": upper,
        "source": "user_query",
    }


def _has_positive_direct_combat_signal(topic: str) -> bool:
    """Return true only for combat terms asserted by the user.

    Acceptance Queries often name words such as ``敌方`` or ``毁伤`` only to
    prohibit them.  Treating those exclusions as positive combat intent
    silently forced disaster-response research back into the historical
    direct-combat template.
    """

    text = str(topic or "")
    for match in _DIRECT_COMBAT_QUERY_PATTERN.finditer(text):
        prefix = text[: match.start()]
        clause_start = max(prefix.rfind(mark) for mark in "。；;！？!?\n") + 1
        clause = prefix[clause_start:]
        negation_position = max(clause.rfind(marker) for marker in _NEGATION_MARKERS)
        contrast_position = max(
            clause.rfind(marker) for marker in ("但", "但是", "然而", "同时", "转而", "改为", "仍需", "仍要")
        )
        if negation_position >= 0 and contrast_position < negation_position:
            continue
        return True
    return False


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
    requested_mode = (
        str(
            brief.get("query_equipment_mode")
            or brief.get("equipment_domain_mode")
            or brief.get("equipment_mode")
            or "direct_combat"
        )
        .strip()
        .lower()
    )
    # Blueprint generation can fail open with its historical direct-combat
    # default.  That default (and any combat template text derived from it)
    # must not override an explicitly non-combat Query such as disaster rescue
    # communications. Mixed/combat Queries retain the safe combat default.
    explicit_mission_query = bool(_MISSION_EQUIPMENT_QUERY_PATTERN.search(str(topic or "")))
    explicit_combat_query = _has_positive_direct_combat_signal(str(topic or ""))
    if requested_mode == "direct_combat" and brief and explicit_mission_query and not explicit_combat_query:
        requested_mode = "mission_equipment"
    non_combat_mode = requested_mode == "mission_equipment"
    if non_combat_mode:
        return {
            "mode": "mission_equipment",
            "subject_label": "可独立立项、部署和验收的检测/感知/通信/保障装备本体",
            "direct_effect_label": "直接形成可验收的发现、识别、定位、跟踪、测量、通信恢复、诊断或任务恢复效果",
            "allowed_equipment_forms": [
                "传感器",
                "检测载荷",
                "机动检测平台",
                "多传感器节点",
                "空中/地面通信中继平台",
                "便携式任务终端",
                "卫星通信终端",
                "保障/诊断装备",
            ],
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


def query_domain_narrative_instruction(
    topic: str,
    *,
    structured_query_brief: Mapping[str, Any] | None = None,
) -> str:
    """Return generation guidance for a non-combat mission-equipment Query.

    This is deliberately an authoring preference rather than a release gate.
    Historical combat-template wording can be corrected at the public
    materialization boundary without suppressing otherwise useful model
    divergence or failing an evidence-backed research run.
    """

    domain = query_domain_contract(
        topic,
        structured_query_brief=structured_query_brief,
    )
    if domain["mode"] != "mission_equipment":
        return ""
    return (
        "【非战斗任务叙事引导】本Query研究救援、检测、通信或保障任务，不存在敌我对抗。"
        "优先避免敌方、我方、对手、击落、摧毁、毁伤、杀伤、弹药、战果、交战、作战反制等历史模板措辞；"
        "不要把自然环境、地形、天气、故障、拥塞或灾害拟人化为敌方/对手，也不要虚构人为干扰。"
        "兼容JSON字段名可以保留，但字段内容必须按以下语义填写：operational_process写关键任务流程，"
        "capability_outcome写可观察任务效果，winning_mechanism写任务价值与关键关系变化，"
        "adversary_adaptation写环境压力、失效模式、缓解措施及其新增工程代价。"
        "所有军事价值类字段按当前Query改写为工程价值、救援价值或任务价值；事实、推断和待验证假设必须分开。"
        "该引导用于提升公开表达一致性，不得据此删除有价值候选、缩减发散空间或把整项研究判为失败。"
    )


def reconcile_discovery_blueprint_domain(
    topic: str,
    blueprint: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the Query-owned semantic boundary to a generated blueprint.

    The model blueprint remains authoritative for routing, but a legacy
    direct-combat default must not leak combat deliverables into an explicit
    rescue/inspection/communications Query.
    """

    resolved = dict(blueprint)
    raw_brief = resolved.get("structured_query_brief", {})
    brief = dict(raw_brief) if isinstance(raw_brief, Mapping) else {}
    contract = query_domain_contract(topic, structured_query_brief=brief)
    if contract["mode"] != "mission_equipment":
        return resolved

    brief["query_equipment_mode"] = "mission_equipment"
    brief["combat_problem_frame"] = ""
    brief["enemy_target_profile"] = []
    brief["required_direct_military_effects"] = []
    brief["battle_phase_and_constraints"] = []
    brief["weapon_design_variables"] = []
    brief["query_specific_weapon_architectures"] = []
    brief["equipment_semantic_boundary"] = contract["subject_label"]
    resolved["structured_query_brief"] = brief

    output_replacements = {
        "现有战法基线": "现有任务流程与系统基线",
        "战法概念集（3种新战法+5种战法组合）": "任务方案概念集",
        "装备能力需求图像（8大能力域+30项能力指标）": "装备能力需求画像",
        "效果链与验证路径": "任务效果链与验证路径",
        "深度研究主报告（深度性、创新性、前瞻性、军事价值性）": (
            "深度研究主报告（深度性、创新性、前瞻性、工程与任务价值）"
        ),
    }
    outputs = resolved.get("required_outputs", [])
    if isinstance(outputs, list):
        resolved["required_outputs"] = list(
            dict.fromkeys(output_replacements.get(str(item), str(item)) for item in outputs)
        )
    resolved["query_domain_contract"] = contract
    return resolved


_MISSION_NARRATIVE_REPLACEMENTS = (
    ("作战反制", "工程缓解"),
    ("敌方（如有）", "环境压力或失效因素"),
    ("敌方", "任务环境"),
    ("我方", "救援参与方"),
    ("对手", "环境压力或失效因素"),
    ("击落", "使其失效"),
    ("摧毁", "破坏"),
    ("毁伤", "任务效果"),
    ("杀伤", "任务影响"),
    ("弹药", "任务资源"),
    ("战果", "任务效果"),
    ("交战", "任务协同"),
    ("突防", "通联恢复"),
    ("射程", "覆盖范围"),
    ("火力", "任务资源"),
    ("战场", "任务现场"),
    ("侦察", "现场感知"),
    ("压制", "环境压力"),
    ("抗毁", "抗损恢复"),
    ("敌人", "环境压力或失效因素"),
    ("攻击", "任务影响"),
    ("对抗", "工程压力"),
    ("打击", "任务作用"),
    ("战斗", "任务"),
    ("武器", "装备"),
    ("反制", "缓解"),
    ("战术", "任务方案"),
    ("战法", "任务方案"),
    ("战争", "任务"),
    ("作战", "任务"),
    ("军事", "任务"),
)

_MISSION_GOVERNED_S6_LABELS = (
    "概述：",
    "装备与技术实现：",
    "关键作战流程：",
    "形成能力与作战效果：",
    "制胜逻辑机理：",
)


def sanitize_mission_narrative_text(value: Any) -> str:
    """在最终物化边界移除非战斗任务中的历史作战模板措辞。"""

    normalized = str(value or "").replace("非战斗", "灾害救援")
    protected_labels: dict[str, str] = {}
    for index, label in enumerate(_MISSION_GOVERNED_S6_LABELS):
        token = f"\ue000S6_LABEL_{index}\ue001"
        if label in normalized:
            normalized = normalized.replace(label, token)
            protected_labels[token] = label
    text = re.sub(
        r"不使用[^。；;\n]{0,220}?等叙事",
        "坚持灾害救援任务叙事",
        normalized,
    )
    for source, replacement in _MISSION_NARRATIVE_REPLACEMENTS:
        text = text.replace(source, replacement)
    for token, label in protected_labels.items():
        text = text.replace(token, label)
    return text


def sanitize_mission_artifact(value: Any) -> Any:
    """递归正规化 mission 装备的公开交付物，不改写领域存储中的用户原文。"""

    if isinstance(value, dict):
        return {key: sanitize_mission_artifact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_mission_artifact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_mission_artifact(item) for item in value)
    if isinstance(value, str):
        return sanitize_mission_narrative_text(value)
    return value


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
            if key
            in {
                "enabling_principle",
                "innovation_mode",
                "equipment_implication",
                "query_causal_link",
                "direct_military_effect",
                "disruptive_delta",
                "conventional_absorption_limit",
                "technology_horizon",
                "engineering_bottleneck",
                "disconfirming_condition",
            }
        }
        for row in brief.get("frontier_technology_hypotheses", [])
        if isinstance(row, Mapping)
    ]
    rules = load_dynamic_winning_json("common", section="query_combat_equipment_divergence.generation_rules")
    if not isinstance(rules, list):
        raise ValueError("query-combat equipment generation rules must be a JSON list")
    return {
        "query": clean_handoff_text(topic, limit=600),
        "combat_problem_frame": str(brief.get("combat_problem_frame", ""))[:900]
        or "由前置Codex Agent依据完整query语义建立任务对象、对手、作战阶段和关键矛盾，不做关键词枚举匹配。",
        "enemy_target_profile": compact_prompt_value(
            brief.get("enemy_target_profile", []), max_string_chars=260, max_list_items=6
        ),
        "battle_phase_and_constraints": compact_prompt_value(
            brief.get("battle_phase_and_constraints", []), max_string_chars=260, max_list_items=8
        ),
        "required_direct_military_effects": compact_prompt_value(
            brief.get("required_direct_military_effects", []), max_string_chars=260, max_list_items=6
        ),
        "equipment_semantic_boundary": str(brief.get("equipment_semantic_boundary", ""))[:700],
        "winning_problem_propositions": compact_prompt_value(
            brief.get("winning_problem_propositions", []), max_string_chars=360, max_list_items=6
        ),
        "weapon_design_variables": compact_prompt_value(
            brief.get("weapon_design_variables", []), max_string_chars=260, max_list_items=8
        ),
        "query_specific_weapon_architectures": compact_prompt_value(
            brief.get("query_specific_weapon_architectures", []), max_string_chars=360, max_list_items=6
        ),
        "frontier_technology_hypotheses": compact_prompt_value(
            frontier_hypotheses, max_string_chars=420, max_list_items=6
        ),
        "equipment_project_hypotheses": compact_prompt_value(
            equipment_hypotheses, max_string_chars=420, max_list_items=6
        ),
        "rejected_template_anchors": compact_prompt_value(
            brief.get("rejected_template_anchors", []), max_string_chars=260, max_list_items=6
        ),
        "query_domain_contract": query_domain_contract(topic, structured_query_brief=brief),
        "conditional_priority_observation_lenses": [],
        "generation_rules": [str(item).strip() for item in rules if str(item).strip()],
    }


__all__ = [
    "clean_handoff_text",
    "compact_prompt_value",
    "query_domain_contract",
    "query_domain_narrative_instruction",
    "reconcile_discovery_blueprint_domain",
    "requested_candidate_count_contract",
    "sanitize_mission_artifact",
    "sanitize_mission_narrative_text",
    "query_combat_equipment_divergence_brief",
]
