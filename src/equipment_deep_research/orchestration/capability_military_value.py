from __future__ import annotations

from typing import Any, Mapping

from equipment_deep_research.orchestration.capability_portrait import (
    build_capability_portrait,
)


_NEUTRAL_PROFILE: dict[str, Any] = {
    "new_name": "待模型复核的新装备能力方向",
    "upgrade_name": "待模型复核的现役装备升级方向",
    "new_form": "由智能体依据Query、证据和制胜机理确定的主装备对象",
    "upgrade_form": "由智能体依据现役基线、任务断点和证据确定的升级对象",
    "baseline": "现役装备基线待智能体结合证据确认",
    "gap": "具体能力差距待智能体结合Query、基线证据和任务链断点确认",
    "effect": "直接军事效果待智能体结合目标、作战阶段和装备作用机理确认",
    "mechanism": "制胜因果链和装备作用机理待智能体结合证据确认",
    "packages": ["现役基线核验", "任务链断点验证", "装备级方案与试验验证"],
}


def military_capability_profile(topic: str, route: str = "") -> dict[str, Any]:
    """Return an object-neutral fallback without classifying the Query locally.

    The runtime model owns domain, equipment and effect selection.  This profile
    only keeps offline/failure paths schema-complete; neither ``topic`` nor
    ``route`` is inspected for semantic keywords.
    """

    del topic, route
    return {
        **_NEUTRAL_PROFILE,
        "packages": list(_NEUTRAL_PROFILE["packages"]),
    }


def needs_military_capability_rewrite(row: Mapping[str, Any]) -> bool:
    """Report only a structural title omission, not a guessed semantic defect."""

    return not str(row.get("name", "")).strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def rewrite_capability_for_military_value(
    row: Mapping[str, Any],
    *,
    topic: str,
    route: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Complete a capability row without inventing its equipment identity.

    Model-authored rows pass through unchanged.  When a local fallback is
    explicitly required, existing structured fields remain authoritative and
    missing fields receive object-neutral placeholders for later model review.
    """

    result = dict(row)
    missing_name = needs_military_capability_rewrite(result)
    if not missing_name and not force:
        return result

    profile = military_capability_profile(topic, route)
    upgrade = str(result.get("capability_type", "")) == "upgrade"
    name = str(result.get("name", "")).strip() or str(
        profile["upgrade_name" if upgrade else "new_name"]
    )
    equipment_form = str(
        result.get("equipment_form")
        or result.get("equipment_category")
        or profile["upgrade_form" if upgrade else "new_form"]
    ).strip()
    gap = str(result.get("capability_gap", "")).strip() or str(profile["gap"])
    mission_effect = str(
        result.get("mission_effect")
        or result.get("military_utility")
        or result.get("capability_outcome")
        or profile["effect"]
    ).strip()
    mechanism = str(
        result.get("operational_mechanism")
        or result.get("winning_mechanism")
        or result.get("operational_concept")
        or profile["mechanism"]
    ).strip()
    target_scenario = str(result.get("target_scenario", "")).strip() or topic
    problem_statement = str(result.get("problem_statement", "")).strip() or gap
    novelty = str(result.get("novelty", "")).strip()
    scientific_principle = str(result.get("scientific_principle", "")).strip() or (
        novelty or mechanism
    )
    enabling_technologies = _string_list(result.get("enabling_technologies")) or [
        "待智能体依据证据确认"
    ]
    operational_concept = (
        str(result.get("operational_concept", "")).strip() or mechanism
    )
    operational_process = _string_list(result.get("operational_process")) or [
        "待智能体依据任务链确认"
    ]
    capability_outcome = (
        str(result.get("capability_outcome", "")).strip() or mission_effect
    )
    winning_mechanism = (
        str(result.get("winning_mechanism", "")).strip() or novelty or mechanism
    )
    development_path = str(result.get("development_path", "")).strip() or (
        "由智能体依据装备基线、工程约束、成熟度证据和验证结果确定。"
    )

    result.update(
        {
            "name": name,
            "equipment_category": equipment_form,
            "equipment_form": equipment_form,
            "source_winning_logic": str(
                result.get("source_winning_logic", "")
            ).strip()
            or "由智能体依据Query、证据和制胜机理生成",
            "capability_gap": gap,
            "mission_effect": mission_effect,
            "military_utility": mission_effect,
            "strike_countermeasure_value": str(
                result.get("strike_countermeasure_value", "")
            ).strip()
            or mechanism,
            "operational_mechanism": mechanism,
            "target_scenario": target_scenario,
            "problem_statement": problem_statement,
            "scientific_principle": scientific_principle,
            "enabling_technologies": enabling_technologies,
            "operational_concept": operational_concept,
            "operational_process": operational_process,
            "capability_outcome": capability_outcome,
            "winning_mechanism": winning_mechanism,
            "novelty": novelty or "创新性待智能体结合对照基线与证据确认。",
            "foresight": str(result.get("foresight", "")).strip()
            or "前瞻判断待智能体结合技术、对手和任务环境变化确认。",
            "development_path": development_path,
        }
    )
    portrait = build_capability_portrait(
        scenario=target_scenario,
        problem=problem_statement,
        principle=scientific_principle,
        technologies=enabling_technologies,
        operational_concept=operational_concept,
        operational_steps=operational_process,
        capability=capability_outcome,
        effect=mission_effect,
        winning_mechanism=winning_mechanism,
        equipment_form=equipment_form,
        baseline=result.get("baseline_system") or equipment_form,
        development_path=development_path,
        failure_boundary=result.get("risk_boundaries")
        or result.get("operational_constraints"),
        verification_plan=result.get("verification")
        or result.get("verification_plan"),
    )
    result["capability_image"] = portrait
    result["deep_capability_portrait"] = portrait

    if upgrade:
        result["baseline_system"] = (
            str(result.get("baseline_system", "")).strip() or profile["baseline"]
        )
        result["upgrade_package"] = _string_list(result.get("upgrade_package")) or list(
            profile["packages"]
        )
        result["combat_effect_uplift"] = (
            str(result.get("combat_effect_uplift", "")).strip() or mission_effect
        )
        result["strike_chain_contribution"] = (
            str(result.get("strike_chain_contribution", "")).strip() or mechanism
        )
        result["upgrade_boundary"] = (
            str(result.get("upgrade_boundary", "")).strip()
            or "升级边界待智能体依据现役平台余量、接口、任务闭环和试验证据确认。"
        )
    return result
