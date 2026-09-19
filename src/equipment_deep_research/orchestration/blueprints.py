"""Executable A-H discovery blueprints from the target architecture."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Mapping, Sequence

from equipment_deep_research.agents.orchestrator_prompt import (
    ORCHESTRATOR_PROMPT_VERSION,
)
from equipment_deep_research.contracts.agents import AgentSpec
from equipment_deep_research.domain.models import ResearchProblem
from equipment_deep_research.orchestration.winning_swarm import (
    normalize_winning_swarm_policy,
)
from equipment_deep_research.domain.research_focus import branch_reference_focus


@dataclass(frozen=True)
class BranchBlueprint:
    code: str
    name: str
    route: str
    emphasis: tuple[str, ...]
    specialist_agent_ids: tuple[str, ...]
    required_capability_tags: tuple[str, ...]
    required_outputs: tuple[str, ...]
    waves: tuple[tuple[str, ...], ...]


BRANCH_BLUEPRINTS: dict[str, BranchBlueprint] = {
    "A": BranchBlueprint(
        "A",
        "新战法发现",
        "new_winning_mechanism",
        ("S2", "S3", "S4"),
        (),
        ("equipment", "operation"),
        (
            "现有战法基线",
            "战法概念集（3种新战法+5种战法组合）",
            "装备能力需求图像（8大能力域+30项能力指标）",
            "关联装备形态建议",
            "效果链与验证路径",
        ),
        (
            ("international_situation",),
            ("combat_scenario", "weapon_equipment"),
            ("operational_employment",),
        ),
    ),
    "B": BranchBlueprint(
        "B",
        "传统能力缺口发现",
        "traditional_gap",
        ("S4", "S5", "S6"),
        (),
        ("equipment", "capability_gap"),
        (
            "装备基线与五档差距",
            "需求卡片（具体待发展武器装备/装备构型/关键指标/优先级/支撑场景/证据链）",
            "能力全景图",
            "深度研究报告（含推理链可回溯）",
        ),
        (("international_situation",), ("combat_scenario", "weapon_equipment")),
    ),
    "C": BranchBlueprint(
        "C",
        "局部战争案例经验",
        "war_case_learning",
        ("案例链", "S3", "S4", "S5", "S6"),
        ("case_research",),
        ("case_reconstruction", "lessons", "equipment"),
        (
            "事实时间线与关键决策点",
            "因果链与跨案例对比",
            "案例规律报告（6条核心规律）",
            "未来场景预测（3类高置信场景）",
            "装备需求图像（4大新兴装备类别）",
            "迁移边界",
        ),
        (
            ("case_research",),
            ("combat_scenario", "weapon_equipment"),
            ("operational_employment",),
        ),
    ),
    "D": BranchBlueprint(
        "D",
        "技术驱动发现",
        "new_winning_mechanism",
        ("技术雷达", "S3", "S4", "S6"),
        ("technology_radar",),
        ("technology_radar", "technology_readiness", "equipment"),
        (
            "技术扫描",
            "成熟度",
            "能力潜力",
            "颠覆场景",
            "阶段验证",
            "装备能力需求图像（需求卡片）",
        ),
        (
            ("technology_radar",),
            ("combat_scenario", "weapon_equipment"),
            ("operational_employment",),
        ),
    ),
    "E": BranchBlueprint(
        "E",
        "对手动向牵引发现",
        "new_winning_mechanism",
        ("对手监测", "S1", "S3", "S4", "S5"),
        ("opponent_monitoring",),
        ("opponent_monitoring", "threat", "equipment"),
        (
            "变化基线",
            "能力形成节奏",
            "威胁效应",
            "体系依赖",
            "对冲能力",
            "装备能力需求图像（需求卡片）",
        ),
        (
            ("opponent_monitoring", "international_situation"),
            ("combat_scenario", "weapon_equipment"),
            ("operational_employment",),
        ),
    ),
    "F": BranchBlueprint(
        "F",
        "体系对抗博弈发现",
        "traditional_gap",
        ("体系仿真", "S3", "S4", "S5", "S6"),
        ("system_confrontation",),
        ("system_modeling", "equipment", "coordination"),
        (
            "体系边界",
            "任务依赖图",
            "脆弱点",
            "替代方案",
            "补链强链",
            "装备能力需求图像（需求卡片）",
        ),
        (
            ("combat_scenario", "weapon_equipment"),
            ("system_confrontation",),
            ("operational_employment",),
        ),
    ),
    "G": BranchBlueprint(
        "G",
        "跨域融合发现",
        "new_winning_mechanism",
        ("跨域矩阵", "S3", "S4", "S6"),
        ("cross_domain_fusion",),
        ("cross_domain", "equipment", "coordination"),
        (
            "跨域边界",
            "域间接口",
            "协同缝隙",
            "跨域效果链",
            "融合能力",
            "装备能力需求图像（需求卡片）",
        ),
        (
            ("cross_domain_fusion",),
            ("combat_scenario", "weapon_equipment"),
            ("operational_employment",),
        ),
    ),
    "H": BranchBlueprint(
        "H",
        "非传统安全牵引",
        "new_winning_mechanism",
        ("新场景", "S1", "S3", "S4", "S6"),
        ("nontraditional_security",),
        ("nontraditional_security", "scenario", "equipment"),
        (
            "新型威胁画像",
            "触发条件",
            "跨部门边界",
            "非致命与韧性能力",
            "法律伦理限制",
            "装备能力需求图像（需求卡片）",
        ),
        (
            ("nontraditional_security", "international_situation"),
            ("combat_scenario", "weapon_equipment"),
            ("operational_employment",),
        ),
    ),
}


COMMON_FINAL_DELIVERABLES = (
    "深度研究主报告（深度性、创新性、前瞻性、军事价值性）",
    "分支专用收敛产物",
)


BRANCH_BASELINE_AGENT_PLANS: dict[str, tuple[tuple[str, str], ...]] = {
    "A": (
        ("operational_employment", "required"),
        ("combat_scenario", "reference"),
        ("weapon_equipment", "reference"),
        ("international_situation", "callback"),
    ),
    "B": (
        ("combat_scenario", "required"),
        ("weapon_equipment", "reference"),
        ("operational_employment", "reference"),
        ("international_situation", "callback"),
        # S2承担作战运用审查，S5承担体系差距综合。以下角色默认只在
        # 对应残差出现时回调，避免在主链前重复生成同类结论。
        ("system_confrontation", "callback"),
    ),
    "C": (
        ("case_research", "required"),
        ("weapon_equipment", "reference"),
        ("operational_employment", "reference"),
        ("combat_scenario", "callback"),
    ),
    "D": (
        ("technology_radar", "required"),
        ("weapon_equipment", "reference"),
        ("combat_scenario", "reference"),
        ("operational_employment", "callback"),
    ),
    "E": (
        ("opponent_monitoring", "required"),
        ("international_situation", "reference"),
        ("weapon_equipment", "reference"),
        ("combat_scenario", "callback"),
        ("operational_employment", "callback"),
    ),
    "F": (
        ("system_confrontation", "required"),
        ("combat_scenario", "reference"),
        ("weapon_equipment", "reference"),
        ("operational_employment", "callback"),
    ),
    "G": (
        ("cross_domain_fusion", "required"),
        ("weapon_equipment", "reference"),
        ("operational_employment", "reference"),
        ("combat_scenario", "callback"),
    ),
    "H": (
        ("nontraditional_security", "required"),
        ("international_situation", "reference"),
        ("combat_scenario", "reference"),
        ("weapon_equipment", "callback"),
    ),
}


TOPIC_AGENT_SIGNALS: dict[str, dict[str, Any]] = {
    "international_situation": {
        "priority": 140,
        "mode": "required",
        "signals": (
            "国际",
            "国外",
            "外军",
            "境外",
            "全球",
            "地区安全",
            "区域安全",
            "西太",
            "亚太",
            "印太",
            "台海",
            "南海",
            "东海",
            "中东",
            "欧洲",
            "印度洋",
            "东北亚",
            "东南亚",
            "南亚",
            "朝鲜半岛",
            "日本",
            "西南岛链",
            "第一岛链",
            "第二岛链",
            "边境涉外",
            "海外基地",
            "海外通道",
            "一带一路",
            "美西方",
            "印度",
            "朝鲜",
            "北约",
            "联盟",
            "盟友",
            "美军",
            "俄军",
            "日军",
            "对外",
            "地缘",
        ),
        "reason": "任务涉及外部地区、国外力量或国际安全环境，需要建立战略态势与对手能力建设基线。",
    },
    "system_confrontation": {
        "priority": 98,
        "mode": "required",
        "signals": (
            "体系对抗",
            "体系博弈",
            "反介入",
            "区域拒止",
            "a2/ad",
            "a2ad",
            "杀伤链",
            "杀伤网",
            "ooda",
            "体系脆弱",
            "体系韧性",
            "体系依赖",
            "穿透性制空",
            "马赛克战",
            "决策中心战",
            "分布式杀伤",
        ),
        "reason": "任务明确涉及体系级对抗、依赖链或反介入/区域拒止，需要体系建模与补链强链分析。",
    },
    "weapon_equipment": {
        "priority": 92,
        # The public equipment baseline constrains and verifies concrete
        # candidates, but it must not become the prerequisite that anchors or
        # blocks first-round S1-S3 innovation.  It still runs in the bounded
        # first wave when the Query asks for equipment evidence, as a reference
        # boundary snapshot; S4/S5 own candidate-level verification.
        "mode": "reference",
        "signals": (
            "装备",
            "武器",
            "平台",
            "型号",
            "载荷",
            "参数",
            "现役",
            "在研",
            "升级",
            "改进",
            "能力缺口",
            "能力差距",
            "技术成熟度",
            "研发需求",
            "无人系统",
            "远程火力",
            "远程精打",
            "新质毁伤",
            "装备能力图像",
        ),
        "reason": "任务要求装备现状、能力差距、升级或新研判断，需要装备证据与成熟度分析。",
    },
    "operational_employment": {
        "priority": 88,
        "mode": "required",
        "signals": (
            "作战",
            "战法",
            "运用",
            "任务链",
            "行动方案",
            "力量协同",
            "联合作战",
            "部署原则",
            "打击",
            "反制",
            "防御",
            "保障",
            "持续作战",
        ),
        "reason": "任务涉及作战运用、任务链或力量协同，需要把场景和装备结论转化为可评估的运用约束。",
    },
    "combat_scenario": {
        "priority": 82,
        "mode": "reference",
        "signals": (
            "作战场景",
            "战场环境",
            "任务场景",
            "阶段演化",
            "时间窗口",
            "危机阶段",
            "战区",
            "海域",
            "空域",
            "电磁环境",
            "复杂环境",
            "场景推演",
            "远海前出",
            "远程快打",
            "全球到达",
            "全球达到",
            "岛链",
        ),
        "reason": "任务包含具体战场环境、阶段或时间窗口，需要构造可验证的场景压力与边界条件。",
    },
    "opponent_monitoring": {
        "priority": 84,
        "mode": "required",
        "signals": (
            "对手动向",
            "兵力部署",
            "部署变化",
            "采购变化",
            "演训变化",
            "力量建设",
            "对手装备",
            "列装节奏",
            "扩军",
            "军费变化",
            "全球部署",
            "金穹",
            "多层防御",
            "预警拦截",
            "下一代拦截器",
        ),
        "reason": "任务关注对手力量建设、部署、采购或演训变化，需要持续动向监测。",
    },
}


def topic_agent_recommendations(topic: str) -> list[dict[str, Any]]:
    normalized = str(topic).lower()
    recommendations: list[dict[str, Any]] = []
    for agent_id, rule in TOPIC_AGENT_SIGNALS.items():
        matched = [
            signal for signal in rule["signals"] if str(signal).lower() in normalized
        ]
        if not matched:
            continue
        recommendations.append(
            {
                "agent_id": agent_id,
                "mode": rule["mode"],
                "priority": rule["priority"],
                "matched_signals": matched[:5],
                "reason": rule["reason"],
            }
        )
    return sorted(
        recommendations,
        key=lambda item: (-int(item["priority"]), str(item["agent_id"])),
    )


WINNING_STEP_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "step": 1,
        "agent_id": "winning_s1_opponent",
        "label": "S1 对手分析",
    },
    {
        "step": 2,
        "agent_id": "winning_s2_operations",
        "label": "S2 作战运用审查",
    },
    {
        "step": 3,
        "agent_id": "winning_s3_breakthrough",
        "label": "S3 突破口思考",
    },
    {
        "step": 4,
        "agent_id": "winning_s4_capability",
        "label": "S4 装备能力映射",
    },
    {
        "step": 5,
        "agent_id": "winning_s5_gap",
        "label": "S5 装备现状与差距",
    },
    {
        "step": 6,
        "agent_id": "winning_s6_image",
        "label": "S6 能力图像综合",
    },
)

BRANCH_WINNING_STEP_MODES: dict[str, tuple[str, ...]] = {
    "A": ("light", "deep", "deep", "standard", "light", "deep"),
    "B": ("standard", "standard", "standard", "deep", "deep", "deep"),
    "C": ("skip", "skip", "deep", "deep", "standard", "deep"),
    "D": ("skip", "skip", "deep", "deep", "light", "deep"),
    "E": ("deep", "skip", "deep", "deep", "standard", "deep"),
    "F": ("skip", "skip", "deep", "deep", "deep", "deep"),
    "G": ("skip", "skip", "deep", "deep", "skip", "deep"),
    "H": ("deep", "skip", "deep", "deep", "skip", "deep"),
}


def winning_step_modes(
    primary_branch: str,
    *,
    research_route: str = "",
    adaptive_modes: Mapping[Any, Any] | None = None,
    l4_overrides: Sequence[Mapping[str, Any]] | Mapping[Any, Any] | None = None,
) -> dict[int, str]:
    """Resolve the executable S1-S6 plan shared by runtime and API projections."""
    branch = str(primary_branch)
    if branch not in BRANCH_WINNING_STEP_MODES:
        branch = {
            "new_winning_mechanism": "A",
            "traditional_gap": "B",
            "war_case_learning": "C",
        }.get(str(research_route), "B")
    result = {
        step: mode
        for step, mode in enumerate(
            BRANCH_WINNING_STEP_MODES[branch],
            start=1,
        )
    }

    def apply(raw_step: Any, raw_mode: Any) -> None:
        try:
            step = int(raw_step)
        except (TypeError, ValueError):
            return
        mode = str(raw_mode)
        if step in result and mode in {"skip", "light", "standard", "deep"}:
            result[step] = mode

    if isinstance(adaptive_modes, Mapping):
        for raw_step, raw_mode in adaptive_modes.items():
            apply(raw_step, raw_mode)
    if isinstance(l4_overrides, Mapping):
        for raw_step, raw_mode in l4_overrides.items():
            apply(raw_step, raw_mode)
    elif isinstance(l4_overrides, Sequence) and not isinstance(
        l4_overrides,
        (str, bytes),
    ):
        for item in l4_overrides:
            if isinstance(item, Mapping):
                apply(item.get("step"), item.get("mode"))
    return result


def build_discovery_blueprint(
    problem: ResearchProblem,
    *,
    model_blueprint: Mapping[str, Any] | None = None,
    available_agent_capabilities: Mapping[str, Sequence[str]] | None = None,
    available_skills: Mapping[str, Mapping[str, Any]] | None = None,
    available_knowledge_pack_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    model_blueprint = dict(model_blueprint or {})
    resolved = problem.resolved_discovery_branch()
    requested_code = (
        str(problem.discovery_branch)
        if problem.discovery_branch != "auto"
        else str(model_blueprint.get("primary_branch") or resolved["primary"])
    )
    code = (
        requested_code
        if requested_code in BRANCH_BLUEPRINTS
        else str(resolved["primary"])
    )
    spec = BRANCH_BLUEPRINTS[code]
    secondary_source = (
        []
        if problem.interaction_mode == "expert" and problem.discovery_branch != "auto"
        else model_blueprint.get("secondary_branches", resolved.get("secondary", []))
    )
    secondary = [
        str(item)
        for item in secondary_source
        if str(item) in BRANCH_BLUEPRINTS and str(item) != code
    ][:2]
    unmatched_driver = str(model_blueprint.get("unmatched_driver", "")).strip()[:1000]
    available_capabilities = {
        str(agent_id): tuple(str(tag) for tag in tags)
        for agent_id, tags in (available_agent_capabilities or {}).items()
    }
    custom_blueprint = _normalize_custom_blueprint(
        model_blueprint.get("custom_blueprint", {}) if unmatched_driver else {},
        available_capabilities=available_capabilities,
    )
    dynamic_subagents = _normalize_dynamic_subagents(
        model_blueprint.get("dynamic_subagents", []),
        unmatched_driver=unmatched_driver,
        available_skills=available_skills or {},
        available_knowledge_pack_ids=available_knowledge_pack_ids or (),
    )
    specialists = list(spec.specialist_agent_ids)
    extra_tags: list[str] = []
    # Secondary branches guide L4 review and S-step emphasis. They are not hard
    # requirements that automatically expand every baseline run; the selector
    # may still choose their agents when the task actually needs them.
    # ``preferred_agent_ids`` are already represented by the model-authored
    # baseline plan.  Treating them as architecture specialists as well used
    # to append the same capability a second time after the plan had been
    # bounded, so a nominal four-Agent blueprint started five real Codex
    # sessions.  Only the selected A-H branch owns mandatory specialists.
    extra_tags.extend(custom_blueprint["required_capability_tags"])
    specialists = list(dict.fromkeys(specialists))
    waves = (
        [list(wave) for wave in custom_blueprint["waves"]]
        if custom_blueprint["waves"]
        else [list(wave) for wave in spec.waves]
    )
    if problem.interaction_mode == "autonomous":
        waves.insert(0, ["scenario_divergence"])
        specialists.insert(0, "scenario_divergence")
        extra_tags.append("autonomous_discovery")
    for specialist in specialists:
        if not any(specialist in wave for wave in waves):
            waves.insert(max(0, len(waves) - 1), [specialist])
    driver_scores = _normalize_driver_scores(model_blueprint.get("driver_scores", []))
    structured_query_brief = _normalize_structured_query_brief(
        model_blueprint.get("structured_query_brief", {}),
        fallback=problem.structured_query_brief(),
    )
    baseline_agent_plan = _normalize_baseline_agent_plan(
        model_blueprint.get("baseline_agent_plan", []),
        branch=code,
        available_agent_ids=set(available_capabilities),
        specialist_agent_ids=specialists,
    )
    if model_blueprint.get("baseline_agent_plan"):
        # The Codex orchestrator has already reasoned over the complete Query.
        # Do not let a deterministic keyword table silently promote callbacks
        # or replace that decision.  Local routing is only a bounded fallback
        # for offline/fake runs where no model blueprint exists.
        baseline_agent_plan = _bound_model_agent_plan(
            baseline_agent_plan,
            maximum_active=3,
        )
        semantic_agent_signals: list[dict[str, Any]] = []
    else:
        baseline_agent_plan, semantic_agent_signals = _apply_topic_agent_policy(
            baseline_agent_plan,
            branch=code,
            topic=problem.analysis_text(),
            available_agent_ids=set(available_capabilities),
            specialist_agent_ids=specialists,
            minimum_active=3,
            maximum_active=4,
        )
    confidence = _bounded_confidence(
        model_blueprint.get("confidence"),
        fallback=float(resolved.get("confidence", 0.55)),
    )
    return {
        "blueprint_id": f"blueprint-{code.lower()}-{problem.problem_id[-8:]}",
        "interaction_mode": problem.interaction_mode,
        "primary_branch": code,
        "branch_name": spec.name,
        "secondary_branches": secondary,
        "runtime_route": (
            spec.route if problem.research_route == "auto" else problem.research_route
        ),
        "emphasis": list(spec.emphasis),
        "specialist_agent_ids": specialists,
        "baseline_agent_plan": baseline_agent_plan,
        "semantic_agent_signals": semantic_agent_signals,
        "initial_baseline_agent_ids": [
            item["agent_id"]
            for item in baseline_agent_plan
            if item["mode"] in {"required", "reference"}
        ],
        "callback_agent_ids": [
            item["agent_id"]
            for item in baseline_agent_plan
            if item["mode"] == "callback"
        ],
        "required_capability_tags": list(
            dict.fromkeys([*spec.required_capability_tags, *extra_tags])
        ),
        "required_outputs": list(
            dict.fromkeys(
                [
                    *spec.required_outputs,
                    *COMMON_FINAL_DELIVERABLES,
                    *custom_blueprint["required_outputs"],
                ]
            )
        ),
        "waves": waves,
        "custom_blueprint": custom_blueprint,
        "dynamic_subagents": dynamic_subagents,
        "winning_swarm_policy": normalize_winning_swarm_policy(
            model_blueprint.get("winning_swarm_policy", {}),
            enabled=False,
        ),
        "loop_policy": {
            "inner_max_iterations": 1,
            "middle_max_cycles": 1,
            "outer_max_rounds": min(problem.max_rounds_hint, 2),
            "meta_max_cycles": 1,
        },
        "meta_triggers": list(
            dict.fromkeys(
                [
                    "出现跨分支高价值线索",
                    "当前分支无法覆盖关键能力标签",
                    "案例/技术/对手变化反向触发其他发现路径",
                    *(
                        ["A-H运行基座无法解释OTHER驱动源，需动态组合蓝图"]
                        if unmatched_driver
                        else []
                    ),
                    *_bounded_text_list(
                        model_blueprint.get("meta_triggers", []), limit=8
                    ),
                ]
            )
        ),
        "generated_by": "codex_orchestrator"
        if model_blueprint
        else "deterministic_architecture_policy",
        "prompt_version": ORCHESTRATOR_PROMPT_VERSION,
        "blueprint_mode": (
            "meta_composed"
            if unmatched_driver and custom_blueprint["preferred_agent_ids"]
            else "dynamic_extension"
            if unmatched_driver
            else "catalog"
        ),
        "driver_scores": driver_scores,
        "unmatched_driver": unmatched_driver,
        "structured_query_brief": structured_query_brief,
        "reference_focus": branch_reference_focus(code),
        "focus_questions": _bounded_text_list(
            model_blueprint.get("focus_questions", []), limit=8
        ),
        "assumptions": _bounded_text_list(
            model_blueprint.get("assumptions", []), limit=8
        ),
        "hard_constraints": _bounded_text_list(
            model_blueprint.get("hard_constraints", []), limit=8
        ),
        "adaptive_winning_step_modes": custom_blueprint["s1_s6_modes"],
        "confidence": confidence,
        "rationale": str(
            model_blueprint.get("rationale") or resolved.get("rationale", "")
        )[:1500],
    }


def _normalize_structured_query_brief(
    value: Any,
    *,
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    base = dict(fallback)
    core_query = str(raw.get("core_query") or base.get("core_query", ""))[:500]
    supplement_summary = str(
        raw.get("supplement_summary") or base.get("supplement_summary", "")
    )[:1200]
    focus_questions = _bounded_text_list(
        raw.get("focus_questions") or base.get("focus_questions", []),
        limit=6,
    )
    expansion_dimensions = _bounded_text_list(
        raw.get("expansion_dimensions") or base.get("expansion_dimensions", []),
        limit=8,
    )
    constraints_and_assumptions = _bounded_text_list(
        raw.get("constraints_and_assumptions")
        or base.get("constraints_and_assumptions", []),
        limit=6,
    )
    combat_problem_frame = str(
        raw.get("combat_problem_frame") or base.get("combat_problem_frame", "")
    )[:900]
    enemy_target_profile = _bounded_text_list(
        raw.get("enemy_target_profile") or base.get("enemy_target_profile", []),
        limit=6,
    )
    battle_phase_and_constraints = _bounded_text_list(
        raw.get("battle_phase_and_constraints")
        or base.get("battle_phase_and_constraints", []),
        limit=8,
    )
    required_direct_military_effects = _bounded_text_list(
        raw.get("required_direct_military_effects")
        or base.get("required_direct_military_effects", []),
        limit=6,
    )
    equipment_semantic_boundary = str(
        raw.get("equipment_semantic_boundary")
        or base.get("equipment_semantic_boundary", "")
    ).strip()[:700]
    query_equipment_mode = str(
        raw.get("query_equipment_mode")
        or base.get("query_equipment_mode", "direct_combat")
    ).strip().lower()
    if query_equipment_mode not in {"direct_combat", "mission_equipment"}:
        query_equipment_mode = "direct_combat"
    winning_problem_propositions = _normalize_winning_problem_propositions(
        raw.get("winning_problem_propositions")
        or base.get("winning_problem_propositions", []),
        limit=6,
    )
    weapon_design_variables = _bounded_text_list(
        raw.get("weapon_design_variables") or base.get("weapon_design_variables", []),
        limit=8,
    )
    query_specific_weapon_architectures = _bounded_text_list(
        raw.get("query_specific_weapon_architectures")
        or base.get("query_specific_weapon_architectures", []),
        limit=6,
    )
    frontier_technology_hypotheses = _normalize_frontier_technology_hypotheses(
        raw.get("frontier_technology_hypotheses")
        or base.get("frontier_technology_hypotheses", []),
        limit=6,
    )
    equipment_project_hypotheses = _normalize_equipment_project_hypotheses(
        raw.get("equipment_project_hypotheses")
        or base.get("equipment_project_hypotheses", []),
        limit=6,
    )
    rejected_template_anchors = _bounded_text_list(
        raw.get("rejected_template_anchors")
        or base.get("rejected_template_anchors", []),
        limit=6,
    )
    return {
        "core_query": core_query,
        "supplement_present": bool(
            raw.get("supplement_present", base.get("supplement_present", False))
        ),
        "supplement_summary": supplement_summary,
        "focus_questions": focus_questions,
        "expansion_dimensions": expansion_dimensions,
        "constraints_and_assumptions": constraints_and_assumptions,
        "combat_problem_frame": combat_problem_frame,
        "enemy_target_profile": enemy_target_profile,
        "battle_phase_and_constraints": battle_phase_and_constraints,
        "required_direct_military_effects": required_direct_military_effects,
        "equipment_semantic_boundary": equipment_semantic_boundary,
        "query_equipment_mode": query_equipment_mode,
        "winning_problem_propositions": winning_problem_propositions,
        "weapon_design_variables": weapon_design_variables,
        "query_specific_weapon_architectures": query_specific_weapon_architectures,
        "frontier_technology_hypotheses": frontier_technology_hypotheses,
        "equipment_project_hypotheses": equipment_project_hypotheses,
        "rejected_template_anchors": rejected_template_anchors,
        "handoff_rule": str(
            raw.get("handoff_rule")
            or base.get(
                "handoff_rule",
                "补充信息用于拓展分析方向；其中假设需验证，不视为既成事实。",
            )
        )[:300],
    }


def _normalize_winning_problem_propositions(
    value: Any,
    *,
    limit: int,
) -> list[dict[str, str]]:
    """Keep the blueprint as an open problem map, not an equipment catalogue."""

    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value[:limit]:
        if not isinstance(item, Mapping):
            continue
        row = {
            key: str(item.get(key, "")).strip()[:360]
            for key in (
                "target_and_phase",
                "task_breakpoint",
                "conventional_assumption",
                "changeable_variable",
                "mechanism_search_question",
                "direct_military_result",
                "exclusion_and_falsification_boundary",
            )
        }
        if (
            row["task_breakpoint"]
            and row["changeable_variable"]
            and row["direct_military_result"]
        ):
            rows.append(row)
    return rows


def _normalize_frontier_technology_hypotheses(
    value: Any,
    *,
    limit: int,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value[:limit]:
        if not isinstance(item, Mapping):
            continue
        row = {
            "enabling_principle": str(item.get("enabling_principle", "")).strip()[:320],
            "innovation_mode": str(item.get("innovation_mode", "")).strip()[:120],
            "equipment_implication": str(item.get("equipment_implication", "")).strip()[
                :360
            ],
            "query_causal_link": str(item.get("query_causal_link", "")).strip()[:420],
            "direct_military_effect": str(
                item.get("direct_military_effect", "")
            ).strip()[:360],
            "disruptive_delta": str(item.get("disruptive_delta", "")).strip()[:420],
            "conventional_absorption_limit": str(
                item.get("conventional_absorption_limit", "")
            ).strip()[:420],
            "technology_horizon": str(item.get("technology_horizon", "")).strip()[:120],
            "engineering_bottleneck": str(
                item.get("engineering_bottleneck", "")
            ).strip()[:360],
            "disconfirming_condition": str(
                item.get("disconfirming_condition", "")
            ).strip()[:360],
        }
        if (
            row["enabling_principle"]
            and row["equipment_implication"]
            and row["query_causal_link"]
            and row["direct_military_effect"]
        ):
            rows.append(row)
    return rows


def _normalize_equipment_project_hypotheses(
    value: Any,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, Mapping):
            continue
        row = {
            "project_name": str(item.get("project_name", "")).strip()[:180],
            "equipment_form": str(item.get("equipment_form", "")).strip()[:260],
            "project_function": str(item.get("project_function", "")).strip()[:420],
            "query_causal_link": str(item.get("query_causal_link", "")).strip()[:420],
            "target_and_phase": str(item.get("target_and_phase", "")).strip()[:360],
            "direct_military_effect": str(
                item.get("direct_military_effect", "")
            ).strip()[:360],
            "design_variables": _bounded_text_list(
                item.get("design_variables", []), limit=8
            ),
            "innovation_logic": _bounded_text_list(
                item.get("innovation_logic", []), limit=6
            ),
            "evidence_questions": _bounded_text_list(
                item.get("evidence_questions", []), limit=6
            ),
            "rejection_condition": str(item.get("rejection_condition", "")).strip()[
                :360
            ],
        }
        if row["project_name"] and row["equipment_form"] and row["project_function"]:
            rows.append(row)
    return rows


def _normalize_baseline_agent_plan(
    value: Any,
    *,
    branch: str,
    available_agent_ids: set[str],
    specialist_agent_ids: Sequence[str],
) -> list[dict[str, str]]:
    known_ids = available_agent_ids or {
        agent_id
        for rows in BRANCH_BASELINE_AGENT_PLANS.values()
        for agent_id, _ in rows
    }
    raw_rows = (
        list(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_rows:
        if not isinstance(item, Mapping):
            continue
        agent_id = str(item.get("agent_id", ""))
        mode = str(item.get("mode", ""))
        if agent_id not in known_ids or agent_id in seen:
            continue
        if mode not in {"required", "reference", "callback"}:
            continue
        seen.add(agent_id)
        result.append(
            {
                "agent_id": agent_id,
                "mode": mode,
                "reason": str(item.get("reason", ""))[:500],
            }
        )
    if not any(item["mode"] in {"required", "reference"} for item in result):
        result = [
            {
                "agent_id": agent_id,
                "mode": mode,
                "reason": f"{branch}分支确定性基线建议",
            }
            for agent_id, mode in BRANCH_BASELINE_AGENT_PLANS[branch]
            if agent_id in known_ids
        ]
        seen = {item["agent_id"] for item in result}
    for agent_id in specialist_agent_ids:
        if agent_id not in known_ids or agent_id in seen:
            continue
        result.insert(
            0,
            {
                "agent_id": agent_id,
                "mode": "required",
                "reason": f"{branch}分支专用发现Agent",
            },
        )
        seen.add(agent_id)
    return result[:6]


def _bound_model_agent_plan(
    plan: list[dict[str, str]],
    *,
    maximum_active: int,
) -> list[dict[str, str]]:
    """Keep a model-authored plan small without reinterpreting its semantics."""

    active_count = 0
    result: list[dict[str, str]] = []
    for item in plan:
        row = dict(item)
        if row["mode"] in {"required", "reference"}:
            active_count += 1
            if active_count > maximum_active:
                row["mode"] = "callback"
                row["reason"] = (
                    f"{row.get('reason', '')}；超过首轮{maximum_active}个Agent上限，"
                    "转为缺口触发回调。"
                ).strip("；")
        result.append(row)
    return result


def _apply_topic_agent_policy(
    plan: list[dict[str, str]],
    *,
    branch: str,
    topic: str,
    available_agent_ids: set[str],
    specialist_agent_ids: Sequence[str],
    minimum_active: int = 3,
    maximum_active: int = 4,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Promote task-explicit roles, then keep the first wave bounded and auditable."""
    rows = {item["agent_id"]: dict(item) for item in plan}
    scores: dict[str, int] = {
        item["agent_id"]: (72 if item["mode"] == "required" else 52)
        for item in plan
        if item["mode"] in {"required", "reference"}
    }
    if branch == "B":
        # Preserve the architectural barrier even when the topic does not
        # literally contain region/scenario trigger words.
        scores["combat_scenario"] = 125
    for specialist in specialist_agent_ids:
        if available_agent_ids and specialist not in available_agent_ids:
            continue
        rows.setdefault(
            specialist,
            {
                "agent_id": specialist,
                "mode": "required",
                "reason": "分支专用发现 Agent",
            },
        )
        rows[specialist]["mode"] = "required"
        scores[specialist] = 120

    semantic = [
        item
        for item in topic_agent_recommendations(topic)
        if not available_agent_ids or item["agent_id"] in available_agent_ids
    ]
    callback_locks = {"system_confrontation"} if branch == "B" else set()
    for item in semantic:
        agent_id = str(item["agent_id"])
        existing = rows.get(agent_id, {})
        prior_reason = str(existing.get("reason", "")).strip()
        reason = str(item["reason"])
        if agent_id in callback_locks:
            rows[agent_id] = {
                "agent_id": agent_id,
                "mode": "callback",
                "reason": "；".join(
                    part
                    for part in (
                        prior_reason,
                        reason,
                        "B分支由S2/S5先承担该分析，仅在残差门触发时回调",
                    )
                    if part
                ),
            }
            scores.pop(agent_id, None)
            continue
        rows[agent_id] = {
            "agent_id": agent_id,
            "mode": str(item["mode"]),
            "reason": "；".join(part for part in (reason, prior_reason) if part),
        }
        scores[agent_id] = max(scores.get(agent_id, 0), int(item["priority"]))
        if branch == "B" and agent_id == "international_situation":
            # External-region B tasks must establish the strategic background
            # before the scenario Agent consumes it.
            scores[agent_id] = 130

    active_ids = [
        agent_id
        for agent_id, row in rows.items()
        if row.get("mode") in {"required", "reference"}
    ]
    ranked_active = sorted(
        active_ids,
        key=lambda agent_id: (-scores.get(agent_id, 0), agent_id),
    )
    # Topic-mandatory roles are locked into the bounded first wave.  In
    # particular, an external-region query must not silently demote the
    # international-situation baseline merely because four other roles score
    # highly.  The remaining slots still follow the existing ranking policy.
    mandatory_ids = [
        str(item["agent_id"])
        for item in semantic
        if str(item.get("mode", "")) == "required"
        and str(item["agent_id"]) in ranked_active
    ]
    keep = set(mandatory_ids[:maximum_active])
    for agent_id in ranked_active:
        if len(keep) >= maximum_active:
            break
        keep.add(agent_id)
    if len(keep) < minimum_active:
        callback_ids = [
            agent_id for agent_id, row in rows.items() if row.get("mode") == "callback"
        ]
        for agent_id in callback_ids:
            keep.add(agent_id)
            if len(keep) >= minimum_active:
                break

    ordered: list[dict[str, str]] = []
    for agent_id in ranked_active:
        row = rows[agent_id]
        if agent_id not in keep:
            row["mode"] = "callback"
            row["reason"] = (
                f"{row.get('reason', '')}；首轮 Agent 范围为 {minimum_active}–{maximum_active}，"
                "该角色转为缺口触发回调。"
            ).strip("；")
        ordered.append(row)
    for agent_id, row in rows.items():
        if agent_id not in {item["agent_id"] for item in ordered}:
            if agent_id in keep:
                row["mode"] = "reference"
            ordered.append(row)
    ordered.sort(
        key=lambda row: (
            0 if row["mode"] == "required" else 1 if row["mode"] == "reference" else 2,
            -scores.get(row["agent_id"], 0),
            row["agent_id"],
        )
    )
    return ordered[:6], semantic


def _normalize_dynamic_subagents(
    value: Any,
    *,
    unmatched_driver: str,
    available_skills: Mapping[str, Mapping[str, Any]],
    available_knowledge_pack_ids: Sequence[str],
) -> list[dict[str, Any]]:
    raw_rows = (
        list(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )
    known_skills = set(str(item) for item in available_skills)
    known_packs = set(str(item) for item in available_knowledge_pack_ids)
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw_rows[:12], start=1):
        if not isinstance(item, Mapping):
            continue
        purpose = str(item.get("purpose", "")).strip()[:800]
        trigger_gap = str(item.get("trigger_gap", "")).strip()[:500]
        merge_target = str(item.get("merge_target", ""))
        if (
            not purpose
            or not trigger_gap
            or merge_target not in {"S1", "S2", "S3", "S4", "S5", "S6", "convergence"}
        ):
            continue
        skill_ids = list(
            dict.fromkeys(
                str(skill_id)
                for skill_id in item.get("skill_ids", [])
                if str(skill_id) in known_skills
            )
        )
        pack_ids = list(
            dict.fromkeys(
                [
                    *(
                        str(pack_id)
                        for skill_id in skill_ids
                        for pack_id in available_skills[skill_id].get(
                            "knowledge_pack_ids", []
                        )
                        if str(pack_id) in known_packs
                    ),
                    *(
                        str(pack_id)
                        for pack_id in item.get("knowledge_pack_ids", [])
                        if str(pack_id) in known_packs
                    ),
                ]
            )
        )
        allowed_tools = list(
            dict.fromkeys(
                str(tool)
                for skill_id in skill_ids
                for tool in available_skills[skill_id].get("allowed_tools", [])
            )
        )
        display_name = str(item.get("display_name", "动态专用Agent")).strip()[:120]
        slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
        digest = sha256(
            f"{display_name}:{purpose}:{merge_target}:{index}".encode("utf-8")
        ).hexdigest()[:8]
        result.append(
            {
                "agent_instance_id": f"dynamic-{slug or 'specialist'}-{digest}",
                "hypothesis_id": str(
                    item.get("hypothesis_id") or f"hypothesis-dynamic-{digest}"
                )[:160],
                "display_name": display_name,
                "purpose": purpose,
                "trigger_gap": trigger_gap,
                "required_capability_tags": _bounded_text_list(
                    item.get("required_capability_tags", []), limit=8
                ),
                "skill_ids": skill_ids,
                "knowledge_pack_ids": pack_ids,
                "allowed_tools": allowed_tools,
                "methodology": _bounded_text_list(item.get("methodology", []), limit=8),
                "quality_gates": _bounded_text_list(
                    item.get("quality_gates", []), limit=8
                ),
                "output_fields": _bounded_text_list(
                    item.get("output_fields", []), limit=12
                ),
                "merge_target": merge_target,
                "contribution_to_steps": [
                    int(step)
                    for step in item.get("contribution_to_steps", [])
                    if str(step).isdigit() and 1 <= int(step) <= 6
                ][:6],
                "allow_child_spawn": False,
                "stop_conditions": _bounded_text_list(
                    item.get("stop_conditions", []), limit=8
                ),
                "max_output_tokens": _bounded_int(
                    item.get("max_output_tokens"),
                    minimum=800,
                    maximum=3200,
                    fallback=1800,
                ),
                "generated_by": "codex_orchestrator",
            }
        )
    # unmatched_driver 只是编排层对“现有分支解释不充分”的记录，不能单独
    # 证明需要新增运行时角色。只有模型明确提交了合法、边界清晰且可合并的
    # dynamic_subagents 合同时才创建动态 Agent，避免无依据的额外模型调用和
    # 后续 S1-S6 对未声明角色的引用。
    del unmatched_driver
    return result


def normalize_dynamic_subagents(
    value: Any,
    *,
    available_skills: Mapping[str, Mapping[str, Any]],
    available_knowledge_pack_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Validate bounded runtime specialists without inventing a fallback role."""
    shared_skills = {
        skill_id: skill
        for skill_id, skill in available_skills.items()
        if bool(skill.get("shared"))
    }
    return _normalize_dynamic_subagents(
        value,
        unmatched_driver="",
        available_skills=shared_skills,
        available_knowledge_pack_ids=available_knowledge_pack_ids,
    )


def _bounded_int(
    value: Any,
    *,
    minimum: int,
    maximum: int,
    fallback: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _normalize_driver_scores(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        branch = str(item.get("branch", ""))
        if branch not in BRANCH_BLUEPRINTS or branch in seen:
            continue
        seen.add(branch)
        result.append(
            {
                "branch": branch,
                "score": _bounded_confidence(item.get("score"), fallback=0.0),
                "signals": _bounded_text_list(item.get("signals", []), limit=6),
                "exclusion_reason": str(item.get("exclusion_reason", ""))[:500],
            }
        )
    return sorted(result, key=lambda item: (-item["score"], item["branch"]))[:3]


def _normalize_custom_blueprint(
    value: Any,
    *,
    available_capabilities: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    available_ids = set(available_capabilities)
    preferred = [
        str(item)
        for item in raw.get("preferred_agent_ids", [])
        if str(item) in available_ids
    ]
    preferred = list(dict.fromkeys(preferred))
    valid_tags = {str(tag) for tags in available_capabilities.values() for tag in tags}
    required_tags = [
        str(item)
        for item in raw.get("required_capability_tags", [])
        if str(item) in valid_tags
    ]
    required_tags = list(dict.fromkeys(required_tags))
    raw_waves = raw.get("waves", [])
    dependencies: list[dict[str, str]] = []
    raw_dependencies = raw.get("dependencies", [])
    if isinstance(raw_dependencies, Sequence) and not isinstance(
        raw_dependencies, (str, bytes)
    ):
        for item in raw_dependencies:
            if not isinstance(item, Mapping):
                continue
            upstream = str(item.get("upstream", ""))
            downstream = str(item.get("downstream", ""))
            if (
                upstream in preferred
                and downstream in preferred
                and upstream != downstream
            ):
                dependencies.append(
                    {
                        "upstream": upstream,
                        "downstream": downstream,
                        "handoff": str(item.get("handoff", ""))[:500],
                    }
                )
    waves, dependency_cycle_rejected = _schedule_custom_waves(
        preferred,
        raw_waves,
        dependencies,
    )
    if dependency_cycle_rejected:
        preferred = []
        waves = []
        dependencies = []
    modes: dict[str, str] = {}
    raw_modes = raw.get("s1_s6_modes", {})
    if isinstance(raw_modes, Mapping):
        for step in range(1, 7):
            mode = str(raw_modes.get(str(step), raw_modes.get(step, "")))
            if mode in {"skip", "light", "standard", "deep"}:
                modes[str(step)] = mode
    return {
        "driver_type": str(raw.get("driver_type", ""))[:500],
        "required_capability_tags": required_tags,
        "preferred_agent_ids": preferred,
        "waves": waves,
        "dependencies": dependencies,
        "dependency_cycle_rejected": dependency_cycle_rejected,
        "s1_s6_modes": modes,
        "required_outputs": _bounded_text_list(
            raw.get("required_outputs", []), limit=12
        ),
        "stop_conditions": _bounded_text_list(raw.get("stop_conditions", []), limit=8),
        "rationale": str(raw.get("rationale", ""))[:1000],
    }


def _schedule_custom_waves(
    preferred: Sequence[str],
    raw_waves: Any,
    dependencies: Sequence[Mapping[str, str]],
) -> tuple[list[list[str]], bool]:
    preferred_ids = list(dict.fromkeys(str(item) for item in preferred))
    proposed_rank = {agent_id: len(preferred_ids) for agent_id in preferred_ids}
    if isinstance(raw_waves, Sequence) and not isinstance(raw_waves, (str, bytes)):
        for rank, raw_wave in enumerate(raw_waves):
            if not isinstance(raw_wave, Sequence) or isinstance(raw_wave, (str, bytes)):
                continue
            for agent_id in raw_wave:
                if str(agent_id) in proposed_rank:
                    proposed_rank[str(agent_id)] = min(
                        proposed_rank[str(agent_id)],
                        rank,
                    )
    incoming = {agent_id: set() for agent_id in preferred_ids}
    for item in dependencies:
        incoming[str(item["downstream"])].add(str(item["upstream"]))
    pending = set(preferred_ids)
    completed: set[str] = set()
    waves: list[list[str]] = []
    while pending:
        ready = [
            agent_id
            for agent_id in preferred_ids
            if agent_id in pending and incoming[agent_id] <= completed
        ]
        if not ready:
            return [], True
        next_rank = min(proposed_rank[agent_id] for agent_id in ready)
        wave = [agent_id for agent_id in ready if proposed_rank[agent_id] == next_rank]
        waves.append(wave)
        completed.update(wave)
        pending.difference_update(wave)
    return waves, False


def _bounded_confidence(value: Any, *, fallback: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = fallback
    return max(0.0, min(1.0, score))


def _bounded_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item).strip()[:500] for item in value if str(item).strip()][:limit]


def execution_waves_from_blueprint(
    selected: Sequence[AgentSpec],
    blueprint: Mapping[str, Any],
    *,
    maximize_parallelism: bool = False,
) -> list[list[AgentSpec]]:
    if (
        maximize_parallelism
        and blueprint.get("baseline_execution_mode")
        == "query_dominant_isolated_parallel"
    ):
        # optimized_v2 baseline Agents independently consume the Query and
        # public evidence.  Cross-Agent synthesis happens after this wave, so
        # business-role handoff declarations must not serialize isolated CLI
        # calls or leak one role's narrative into another role's context.
        return [list(selected)] if selected else []
    by_id = {agent.agent_id: agent for agent in selected}
    preferred_rank: dict[str, int] = {}
    raw_waves = list(blueprint.get("waves", []))
    for rank, raw_wave in enumerate(raw_waves):
        if not isinstance(raw_wave, Sequence) or isinstance(raw_wave, (str, bytes)):
            continue
        for agent_id in raw_wave:
            if str(agent_id) in by_id:
                preferred_rank[str(agent_id)] = rank
    fallback_rank = len(raw_waves)
    selected_ids = set(by_id)
    hard_dependencies = {
        str(agent_id): {
            str(dependency)
            for dependency in dependencies
            if str(dependency) in selected_ids
        }
        for agent_id, dependencies in dict(
            blueprint.get("hard_dependencies", {}) or {}
        ).items()
        if str(agent_id) in selected_ids
        and isinstance(dependencies, Sequence)
        and not isinstance(dependencies, (str, bytes))
    }
    pending = dict(by_id)
    completed: set[str] = set()
    result: list[list[AgentSpec]] = []
    while pending:
        ready = [
            agent
            for agent in pending.values()
            if not (
                (
                    set(
                        agent.handoff_policy.get(
                            "wait_for",
                            agent.handoff_policy.get("accept_from", []),
                        )
                    )
                    | hard_dependencies.get(agent.agent_id, set())
                )
                & selected_ids - completed
            )
        ]
        if not ready:
            raise ValueError(
                "selected discovery agents contain a handoff dependency cycle"
            )
        if maximize_parallelism:
            wave = ready
        else:
            next_rank = min(
                preferred_rank.get(agent.agent_id, fallback_rank) for agent in ready
            )
            wave = [
                agent
                for agent in ready
                if preferred_rank.get(agent.agent_id, fallback_rank) == next_rank
            ]
        wave.sort(key=lambda agent: list(by_id).index(agent.agent_id))
        result.append(wave)
        for agent in wave:
            pending.pop(agent.agent_id)
            completed.add(agent.agent_id)
    return result


__all__ = [
    "BRANCH_BLUEPRINTS",
    "BRANCH_WINNING_STEP_MODES",
    "WINNING_STEP_DEFINITIONS",
    "BranchBlueprint",
    "build_discovery_blueprint",
    "execution_waves_from_blueprint",
    "normalize_dynamic_subagents",
    "winning_step_modes",
]
