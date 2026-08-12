"""Codex-facing runtime profiles for every research-agent scene.

The local harness remains the authority that executes and validates tools.
These profiles tell each isolated Codex session which governed tools and
skills are relevant, which method to follow, and what quality gates apply.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Any
from equipment_deep_research.agents.designs.registry import DEFAULT_AGENT_IDS

from equipment_deep_research.agents.performance import role_card_id
from equipment_deep_research.domain.research_focus import (
    baseline_agent_expansion_lenses,
    branch_reference_focus,
)
from equipment_deep_research.orchestration.execution_contracts import (
    is_quality_execution_profile_id,
)


SAFETY_BOUNDARY = (
    "仅使用公开来源开展战略、能力、装备市场与防御性需求研究；不得输出实时目标定位、"
    "具体攻击步骤、可直接执行的伤害行动、规避防护的方法或武器制造参数。"
)


_RUNTIME_AGENT_MODULES = {
    agent_id: import_module(
        f"equipment_deep_research.agents.designs.runtime.{agent_id}"
    )
    for agent_id in DEFAULT_AGENT_IDS
}

QUERY_DOMINANT_BUSINESS_AGENT_IDS = {
    agent_id
    for agent_id, module in _RUNTIME_AGENT_MODULES.items()
    if module.QUERY_DOMINANT
}


SWARM_RUNTIME_SKILL_IDS = [
    "js-equipment-agent-runtime",
    "js-winning-shared-layer",
]


MILITARY_MISSION_LENSES: dict[str, str] = {
    agent_id: module.MISSION_LENS
    for agent_id, module in _RUNTIME_AGENT_MODULES.items()
}


def military_mission_lens(agent_id: str) -> str:
    return MILITARY_MISSION_LENSES.get(
        agent_id,
        "核心判断必须落到可验证的军事任务效果、作用机理和失效边界。",
    )


CODEX_BRANCH_RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    "A": {
        "name": "新战法发现",
        "methodology": [
            "审查现有战法与任务链",
            "构造竞争性新战法",
            "用反事实检验突破口",
            "映射S2-S4与验证路径",
        ],
        "quality_gates": [
            "新战法说明适用条件和失败模式",
            "效果链可追溯到证据或显式假设",
        ],
        "output_focus": [
            "现有战法基线",
            "新战法",
            "效果链",
            "装备能力映射",
            "验证路径",
        ],
    },
    "B": {
        "name": "传统能力缺口发现",
        "methodology": [
            "建立传统任务和装备基线",
            "形成能力-任务矩阵",
            "执行S4-S6五档差距评估",
            "比较升级与新研",
        ],
        "quality_gates": ["差距等级具备比较依据", "升级与新研方向说明边界和优先级"],
        "output_focus": ["装备基线", "能力要求", "五档差距", "升级方向", "优先级"],
    },
    "C": {
        "name": "局部战争案例经验",
        "methodology": [
            "多语言案例检索",
            "事实与时间线还原",
            "构建因果链",
            "跨案例比较",
            "检验未来迁移边界",
        ],
        "quality_gates": ["事实、推断和争议分离", "经验迁移说明背景差异与不可迁移项"],
        "output_focus": [
            "事实时间线",
            "关键决策点",
            "因果链",
            "跨案例模式",
            "未来场景映射",
        ],
    },
    "D": {
        "name": "技术驱动发现",
        "methodology": [
            "扫描技术信号",
            "评估TRL与工程节点",
            "识别限制条件",
            "反向构造颠覆场景",
            "映射S3/S4/S6",
        ],
        "quality_gates": ["成熟度有试验或项目节点依据", "技术潜力不等同于已形成能力"],
        "output_focus": ["技术雷达", "成熟度", "能力潜力", "颠覆场景", "阶段验证"],
    },
    "E": {
        "name": "对手动向牵引发现",
        "methodology": [
            "建立装备/演习/条令变化基线",
            "识别异常动向",
            "估计能力形成节奏",
            "映射S1与S3-S6",
        ],
        "quality_gates": ["变化必须相对基线成立", "意图判断包含替代假设和预警指标"],
        "output_focus": [
            "变化基线",
            "能力形成节奏",
            "威胁效应",
            "体系依赖",
            "对冲能力",
        ],
    },
    "F": {
        "name": "体系对抗博弈发现",
        "methodology": [
            "建立红蓝体系边界",
            "绘制任务与接口依赖",
            "识别单点和级联脆弱性",
            "比较替代链路",
            "映射S3-S6",
        ],
        "quality_gates": ["脆弱性说明前置条件和级联边界", "建议保持任务级和防御性"],
        "output_focus": [
            "体系边界",
            "任务依赖图",
            "脆弱点",
            "替代方案",
            "补链强链需求",
        ],
    },
    "G": {
        "name": "跨域融合发现",
        "methodology": [
            "建立陆海空天电网智认知深海矩阵",
            "识别域间接口",
            "定位协同缝隙",
            "构建跨域效果链",
            "映射S3/S4/S6",
        ],
        "quality_gates": [
            "接口含数据、指挥、时序和保障条件",
            "融合收益与耦合风险同时评估",
        ],
        "output_focus": ["跨域边界", "域间接口", "协同缝隙", "跨域效果链", "融合能力"],
    },
    "H": {
        "name": "非传统安全牵引",
        "methodology": [
            "扫描新型威胁",
            "构造非传统场景",
            "分析跨部门边界",
            "强化S1/S3/S4/S6并弱化不适用步骤",
        ],
        "quality_gates": ["法律伦理与民用影响显式列出", "优先韧性、非致命和跨部门能力"],
        "output_focus": [
            "新型威胁画像",
            "触发条件",
            "跨部门边界",
            "非致命与韧性能力",
            "法律伦理限制",
        ],
    },
}


def _profile(
    scenario: str,
    *,
    skills: Sequence[str],
    tools: Sequence[str],
    methodology: Sequence[str],
    quality_gates: Sequence[str],
    output_focus: Sequence[str],
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "skills": list(skills),
        "tools": list(tools),
        "methodology": list(methodology),
        "quality_gates": list(quality_gates),
        "output_focus": list(output_focus),
        "safety_boundary": SAFETY_BOUNDARY,
    }


CODEX_AGENT_RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    agent_id: dict(module.PROFILE)
    for agent_id, module in _RUNTIME_AGENT_MODULES.items()
    if module.PROFILE
}


def build_codex_runtime_profile(
    agent_id: str,
    *,
    payload: Mapping[str, Any] | None = None,
    agent: Any | None = None,
    harness_profile: Any | None = None,
    phase: str = "analysis",
    compact: bool = False,
) -> dict[str, Any]:
    """Merge the static scene profile with registry and A-H task context."""
    static = CODEX_AGENT_RUNTIME_PROFILES.get(agent_id, {})
    profile: dict[str, Any] = {
        "agent_id": agent_id,
        "phase": phase,
        "scenario": str(
            static.get("scenario") or getattr(agent, "description", "通用结构化研究")
        ),
        "skills": list(static.get("skills", ["深度搜索", "证据治理", "结构化研究"])),
        "tools": list(
            static.get(
                "tools", ["search_sources", "fetch_page", "create_evidence_card"]
            )
        ),
        "methodology": list(
            static.get(
                "methodology", ["界定问题", "收集证据", "分析反证", "结构化输出"]
            )
        ),
        "quality_gates": list(
            static.get("quality_gates", ["事实、推断和假设分离", "结论可追溯"])
        ),
        "output_focus": list(static.get("output_focus", [])),
        "military_mission_lens": military_mission_lens(agent_id),
        "safety_boundary": str(static.get("safety_boundary", SAFETY_BOUNDARY)),
        "tool_execution_rule": "这些是本场景允许或相关的受治理工具；由本地Harness执行和校验。Codex只按其语义规划、分析和输出，不得自行修改工作区或系统状态。",
    }
    expansion_lenses = baseline_agent_expansion_lenses(agent_id)
    if expansion_lenses:
        profile["reference_expansion_lenses"] = expansion_lenses
    if agent is not None:
        registered_skills = getattr(agent, "skills", [])
        shared_skills = getattr(agent, "shared_skills", [])
        registered_tools = getattr(agent, "tools", [])
        research_policy = getattr(agent, "research_policy", {})
        output_contract = getattr(agent, "output_contract", {})
        if registered_skills or shared_skills:
            profile["skills"] = [
                _compact_skill(item)
                for item in [*list(registered_skills), *list(shared_skills)]
            ]
        knowledge_packs = getattr(agent, "knowledge_packs", [])
        if knowledge_packs:
            profile["knowledge_packs"] = [
                _compact_knowledge_pack(item) for item in knowledge_packs
            ]
        if registered_tools:
            profile["tools"] = list(registered_tools)
        if isinstance(research_policy, Mapping):
            profile["research_policy"] = dict(research_policy)
            profile["quality_gates"] = _unique(
                [
                    *profile["quality_gates"],
                    *research_policy.get("stopping_conditions", []),
                ]
            )
            profile["output_focus"] = _unique(
                [*profile["output_focus"], *research_policy.get("required_outputs", [])]
            )
        if isinstance(output_contract, Mapping):
            profile["output_contract"] = dict(output_contract)
    if harness_profile is not None:
        phase_tools = getattr(harness_profile, "phase_tools", {})
        phase_key = (
            "winning"
            if phase.startswith("winning")
            else "baseline"
            if phase in {"web_discovery", "evidence_analysis"}
            else phase
        )
        current_phase_tools = list(phase_tools.get(phase_key, []))
        skill_tools = {
            str(tool)
            for skill in profile.get("skills", [])
            if isinstance(skill, Mapping)
            for tool in skill.get("allowed_tools", [])
        }
        harness_tools = {str(tool) for tool in current_phase_tools}
        active_tools = [
            tool
            for tool in profile["tools"]
            if (not skill_tools or tool in skill_tools)
            and (not harness_tools or tool in harness_tools)
        ]
        profile["tools"] = active_tools or list(profile["tools"])
        profile["harness"] = {
            "profile_id": str(getattr(harness_profile, "profile_id", "")),
            "budget": dict(getattr(harness_profile, "budget", {})),
            "evidence_policy": dict(getattr(harness_profile, "evidence_policy", {})),
            "checkpoint_policy": dict(
                getattr(harness_profile, "checkpoint_policy", {})
            ),
            "stop_conditions": list(getattr(harness_profile, "stop_conditions", [])),
            "recovery_policy": dict(getattr(harness_profile, "recovery_policy", {})),
            "active_phase_tools": current_phase_tools,
        }
        profile["quality_gates"] = _unique(
            [
                *profile["quality_gates"],
                *profile["harness"]["stop_conditions"],
            ]
        )
    branch_codes, blueprint = _find_branch_context(payload or {})
    if branch_codes:
        profile["discovery_branches"] = [
            {
                "code": code,
                **CODEX_BRANCH_RUNTIME_PROFILES[code],
                "reference_focus": branch_reference_focus(code),
            }
            for code in branch_codes
            if code in CODEX_BRANCH_RUNTIME_PROFILES
        ]
        # Fixed disruptive cards are deliberately absent from baseline and
        # first-divergence contexts. They may be injected later by a governed
        # counterfactual reviewer, after Query-led hypotheses already exist.
    if blueprint:
        profile["blueprint_context"] = {
            key: blueprint.get(key)
            for key in (
                "runtime_route",
                "emphasis",
                "required_outputs",
                "loop_policy",
                "reference_focus",
            )
            if blueprint.get(key) not in (None, "", [], {})
        }
    swarm_contract = _find_swarm_specialist_contract(agent_id, payload or {})
    if swarm_contract:
        role = dict(swarm_contract["role_contract"])
        assignment = dict(swarm_contract["assignment"])
        profile["runtime_profile_id"] = str(role["runtime_profile_id"])
        profile["role_contract_version"] = str(role["version"])
        profile["swarm_role_contract"] = role
        profile["swarm_assignment"] = assignment
        profile["scenario"] = str(role["purpose"])
        profile["skills"] = [
            f"{role['display_name']}专用分析",
            "制胜机理共享层",
        ]
        profile["active_dynamic_skill_ids"] = list(SWARM_RUNTIME_SKILL_IDS)
        profile["methodology"] = [
            f"围绕当前声明的候选执行{role['display_name']}任务",
            str(role["purpose"]),
            "只向声明的 hypothesis_id 与 merge_target 提交结构化增量",
            "显式记录证据边界、反证、失败条件和仍未解决的质量残差",
        ]
        profile["quality_gates"] = _unique(
            [
                "不得读取或复述其他 Agent 原始会话",
                "不得招募子 Agent、扩大权限或修改生产角色与 Skill",
                "不得虚构精确指标、效能比例、TRL、成本或产能判断",
                "结果必须保持 hypothesis_id 与 merge_target 的合并边界",
                *role.get("quality_gates", []),
            ]
        )
        profile["output_focus"] = _unique(
            [
                str(role["display_name"]),
                f"对 {role['merge_target']} 的增量贡献",
                "证据与反证边界",
                "失效条件与验证建议",
            ]
        )
        profile["military_mission_lens"] = MILITARY_MISSION_LENSES[
            "winning_dynamic_specialist"
        ]
    dynamic_spec = _find_dynamic_agent_spec(payload or {})
    if dynamic_spec:
        profile["dynamic_agent_contract"] = dynamic_spec
        profile["scenario"] = str(
            dynamic_spec.get("purpose")
            or dynamic_spec.get("display_name")
            or profile["scenario"]
        )
        selected_skill_ids = [
            str(item) for item in dynamic_spec.get("skill_ids", []) if str(item)
        ]
        if selected_skill_ids:
            profile["active_dynamic_skill_ids"] = selected_skill_ids
        selected_pack_ids = [
            str(item)
            for item in dynamic_spec.get("knowledge_pack_ids", [])
            if str(item)
        ]
        if selected_pack_ids:
            profile["active_dynamic_knowledge_pack_ids"] = selected_pack_ids
        profile["methodology"] = _unique(
            [*profile["methodology"], *dynamic_spec.get("methodology", [])]
        )
        profile["quality_gates"] = _unique(
            [*profile["quality_gates"], *dynamic_spec.get("quality_gates", [])]
        )
        profile["output_focus"] = _unique(
            [*profile["output_focus"], *dynamic_spec.get("output_fields", [])]
        )
    # Quality-first profiles keep the complete role card.  Expose the same
    # concise role alias used by the throughput-first profile so callers and
    # traces do not need to understand two incompatible runtime shapes.
    profile["role"] = str(profile.get("scenario", "结构化业务研究"))
    if compact:
        full_profile = dict(profile)
        profile["role_card_id"] = role_card_id(agent_id, phase, full_profile)
        profile["role_card_version"] = "2.0"
        profile.pop("research_policy", None)
        profile.pop("output_contract", None)
        harness = profile.get("harness")
        if isinstance(harness, Mapping):
            profile["harness"] = {
                key: harness.get(key)
                for key in (
                    "profile_id",
                    "budget",
                    "evidence_policy",
                    "stop_conditions",
                    "active_phase_tools",
                )
                if harness.get(key) not in (None, "", [], {})
            }
        if phase == "web_discovery":
            profile["skills"] = [
                {
                    key: item.get(key)
                    for key in ("name", "allowed_tools", "quality_gates")
                    if item.get(key) not in (None, "", [], {})
                }
                if isinstance(item, Mapping)
                else item
                for item in profile.get("skills", [])
            ]
        if is_dynamic_winning_payload(payload or {}):
            profile = _minimal_dynamic_winning_runtime_profile(
                profile,
                agent_id=agent_id,
                phase=phase,
            )
        elif is_aggressive_optimized_v2_payload(payload or {}):
            profile = _minimal_business_runtime_profile(
                profile,
                agent_id=agent_id,
                phase=phase,
                blueprint=blueprint,
            )
    return profile


def is_dynamic_winning_payload(value: Mapping[str, Any]) -> bool:
    """Whether this is the creative dynamic winning-swarm path.

    Dynamic S1-S6 turns must not inherit the generic quality-first role card:
    that card is useful for research/audit agents but repeats evidence,
    validation and quality-gate instructions inside creative sessions.
    """
    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "discovery_blueprint", "visible_context", "context", "input",
        "task_input", "winning_mechanism_input", "assignment",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
    return any(
        str(candidate.get("execution_profile_id", "")).strip()
        == "winning_swarm_dynamic_v2"
        for candidate in candidates
    )


def _minimal_dynamic_winning_runtime_profile(
    profile: Mapping[str, Any],
    *,
    agent_id: str,
    phase: str,
) -> dict[str, Any]:
    """Keep only the context that helps a dynamic S-node think.

    The business task already carries the Query and the node-specific handoff.
    Runtime therefore supplies identity, one skill, and safety only.  In
    particular it does not replay methodology, quality_gates, evidence policy,
    TRL, validation or upstream role contracts.
    """
    node = str(profile.get("swarm_assignment", {}).get("merge_target", ""))
    if not node:
        phase_node = next((f"S{i}" for i in range(1, 7) if f"S{i}" in phase), "")
        node = phase_node
    creative = node in {"S1", "S2", "S3", "S4"}
    role = str(profile.get("scenario") or profile.get("role") or agent_id)[:180]
    if creative:
        skill = {
            "S1": "对手制胜矛盾建模",
            "S2": "任务关系与效应窗口创造",
            "S3": "新质武器概念创造",
            "S4": "跨域/反常规武器概念创造",
        }.get(node, "Query驱动创造")
    elif node == "S5":
        skill = "独立组合语义判断"
    elif node == "S6":
        skill = "单装备能力画像编辑"
    else:
        skill = "动态制胜判断"
    return {
        "agent_id": agent_id,
        "phase": phase,
        "role": role,
        "skill": skill,
        "tools": [],
        "mission_node": node,
        "military_mission_lens": "只围绕当前Query形成可理解的军事任务判断。",
        "safety_boundary": "只做任务级、防御性研究，不输出可直接执行的攻击步骤或制造参数。",
        "handoff_contract": "task_input是唯一业务上下文；只输出当前schema要求的结论。",
    }


def is_optimized_v2_payload(value: Mapping[str, Any]) -> bool:
    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "discovery_blueprint",
        "visible_context",
        "context",
        "input",
        "task_input",
        "winning_mechanism_input",
        "assignment",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("discovery_blueprint")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    return any(
        is_quality_execution_profile_id(candidate.get("execution_profile_id", ""))
        for candidate in candidates
    )


def is_aggressive_optimized_v2_payload(value: Mapping[str, Any]) -> bool:
    """Return whether throughput-first v2 prompt compaction is requested.

    Quality-cluster and dynamic-swarm profiles share the v2 execution model,
    but they must retain the complete role methods and skills.  Only the
    explicit ``optimized_v2`` profile opts into the single-skill/minimal-role
    card used to reduce provider calls and prompt size.
    """

    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "discovery_blueprint",
        "visible_context",
        "context",
        "input",
        "task_input",
        "winning_mechanism_input",
        "assignment",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("discovery_blueprint")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    return any(
        str(candidate.get("execution_profile_id", "")).strip() == "optimized_v2"
        for candidate in candidates
    )


def _minimal_business_runtime_profile(
    profile: Mapping[str, Any],
    *,
    agent_id: str,
    phase: str,
    blueprint: Mapping[str, Any],
) -> dict[str, Any]:
    skills = list(profile.get("skills", []))
    chosen_skill = _choose_single_skill(skills, phase=phase)
    tools = _minimal_phase_tools(
        agent_id=agent_id,
        phase=phase,
        tools=[str(item) for item in profile.get("tools", [])],
    )
    branch = str(
        blueprint.get("primary_branch", "")
        or blueprint.get("discovery_branch", "")
    )
    result = {
        "agent_id": agent_id,
        "phase": phase,
        "role": str(profile.get("scenario", "结构化业务研究"))[:180],
        "skill": chosen_skill,
        "tools": tools,
        "method": [
            str(item)[:120]
            for item in list(profile.get("methodology", []))[:2]
        ],
        "output_focus": [
            str(item)[:80]
            for item in list(profile.get("output_focus", []))[:5]
        ],
        "reference_expansion_lenses": [
            str(item)[:100]
            for item in list(profile.get("reference_expansion_lenses", []))[:3]
        ],
        "disruptive_seed_context": profile.get("disruptive_seed_context", {}),
        "quality_gates": [
            *[
                str(item)[:120]
                for item in list(profile.get("quality_gates", []))[:2]
            ],
            "军事任务效果、作用机理和失效边界不可缺失",
        ],
        "military_mission_lens": military_mission_lens(agent_id),
        "branch_focus": {
            "branch": branch,
            "emphasis": list(blueprint.get("emphasis", []))[:4],
            "required_outputs": list(blueprint.get("required_outputs", []))[:6],
            "reference_focus": blueprint.get("reference_focus", {}),
        }
        if branch
        else {},
        "handoff_contract": "只输出当前schema要求的业务结论、证据引用、置信度、限制和下一步建议；不复述流程。",
        "safety_boundary": "只做公开来源下的任务级能力研究，不输出目标坐标、攻击步骤或可直接执行参数。",
        "role_card_id": str(profile.get("role_card_id", "")),
    }
    if profile.get("runtime_profile_id"):
        result.update(
            {
                "runtime_profile_id": str(profile["runtime_profile_id"]),
                "role_contract_version": str(
                    profile.get("role_contract_version", "1.0")
                ),
                "swarm_role_contract": dict(
                    profile.get("swarm_role_contract", {})
                ),
                "swarm_assignment": dict(profile.get("swarm_assignment", {})),
                "active_dynamic_skill_ids": list(
                    profile.get("active_dynamic_skill_ids", [])
                ),
            }
        )
        result["military_mission_lens"] = str(
            profile.get("military_mission_lens")
            or result["military_mission_lens"]
        )
    if agent_id in QUERY_DOMINANT_BUSINESS_AGENT_IDS:
        result["analysis_anchor"] = "query_dominant_military_divergence"
        result["query_dominance_rule"] = (
            "分析优先级固定为：本Agent专业角色与方法第一，Query核心军事矛盾第二，"
            "打击、歼灭、压制、反制、拒止、威慑等直接军事价值第三；三者共同主导独立发散。"
            "跨Agent精简交接只能用于事实证据、约束和反证校验，不得决定议题、分析结构、"
            "方案命名、优先级或最终结论。"
        )
    if not result.get("reference_expansion_lenses"):
        result.pop("reference_expansion_lenses", None)
    if not result.get("disruptive_seed_context"):
        result.pop("disruptive_seed_context", None)
    return result


def _choose_single_skill(skills: Sequence[Any], *, phase: str) -> str:
    if not skills:
        return "结构化业务判断"
    if phase.startswith("web_discovery"):
        for item in skills:
            if isinstance(item, Mapping) and "search_sources" in item.get(
                "allowed_tools", []
            ):
                return str(item.get("name", "公开来源检索"))
    first = skills[0]
    if isinstance(first, Mapping):
        return str(first.get("name", "结构化业务判断"))
    return str(first)


def _minimal_phase_tools(
    *,
    agent_id: str,
    phase: str,
    tools: Sequence[str],
) -> list[str]:
    if agent_id == "reporter" or phase.startswith("report_generation"):
        return ["write_report"]
    if agent_id == "auditor" or "audit" in phase:
        return ["write_audit"]
    if phase.startswith("web_discovery"):
        return [item for item in ("search_sources",) if item in tools]
    if phase == "evidence_analysis":
        preferred = (
            "create_evidence_card",
            "test_competing_hypothesis",
            "stress_test_scenario",
            "compare_coa",
            "compare_equipment_capability",
        )
        selected = [item for item in preferred if item in tools]
        return selected[:2]
    if phase.startswith("winning"):
        preferred = (
            "write_reasoning_node",
            "write_stage_output",
            "create_capability_image",
            "create_recall_request",
        )
        return [item for item in preferred if item in tools][:2]
    return list(tools)[:2]


def _compact_skill(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return {
        key: value.get(key)
        for key in (
            "name",
            "steps",
            "allowed_tools",
            "quality_gates",
            "stop_conditions",
            "required_artifacts",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _compact_knowledge_pack(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    return {
        key: value.get(key)
        for key in (
            "knowledge_pack_id",
            "description",
            "retrieval_policy",
            "quality_gates",
        )
        if value.get(key) not in (None, "", [], {})
    }


def _find_branch_context(
    value: Mapping[str, Any],
) -> tuple[list[str], Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "discovery_blueprint",
        "visible_context",
        "context",
        "input",
        "winning_mechanism_input",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("discovery_blueprint")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    for candidate in candidates:
        blueprint = candidate.get("discovery_blueprint")
        if isinstance(blueprint, Mapping):
            candidate = blueprint
        primary = str(
            candidate.get("primary_branch") or candidate.get("discovery_branch") or ""
        )
        secondary = candidate.get("secondary_branches", [])
        codes = (
            [primary, *secondary]
            if isinstance(secondary, Sequence)
            and not isinstance(secondary, (str, bytes))
            else [primary]
        )
        resolved = _unique(
            code for code in codes if str(code) in CODEX_BRANCH_RUNTIME_PROFILES
        )
        if resolved:
            return [str(code) for code in resolved], candidate
    return [], {}


def _find_query_text(value: Mapping[str, Any]) -> str:
    """Read a bounded query from known task containers without flattening payloads."""

    candidates: list[Mapping[str, Any]] = [value]
    for key in (
        "task",
        "task_input",
        "input",
        "context",
        "visible_context",
        "winning_mechanism_input",
        "structured_query_brief",
    ):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("structured_query_brief")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    rows: list[str] = []
    for candidate in candidates:
        for key in ("query", "topic", "core_query"):
            text = str(candidate.get(key, "")).strip()
            if text and text not in rows:
                rows.append(text)
    return "\n".join(rows)[:1600]


def _find_dynamic_agent_spec(value: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[Mapping[str, Any]] = [value]
    for key in ("input", "task_input", "winning_mechanism_input"):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
    for candidate in candidates:
        spec = candidate.get("dynamic_agent_spec")
        if isinstance(spec, Mapping):
            return {str(key): item for key, item in spec.items()}
    return {}


def _find_swarm_specialist_contract(
    agent_id: str,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    prefix = "winning_swarm_"
    if not str(agent_id).startswith(prefix):
        return {}
    archetype = str(agent_id)[len(prefix) :]
    # Local import keeps the role catalog authoritative without making the
    # general runtime-profile module initialize the orchestration layer early.
    from equipment_deep_research.orchestration.winning_swarm import (
        MISSION_GRAPH_CORE_ARCHETYPES,
        SWARM_SPECIALIST_ARCHETYPES,
    )

    role_catalog = {
        **SWARM_SPECIALIST_ARCHETYPES,
        **MISSION_GRAPH_CORE_ARCHETYPES,
    }
    if archetype not in role_catalog:
        raise ValueError(f"unknown winning swarm specialist archetype: {archetype}")
    candidates: list[Mapping[str, Any]] = [value]
    for key in ("input", "task_input", "winning_mechanism_input"):
        child = value.get(key)
        if isinstance(child, Mapping):
            candidates.append(child)
            nested = child.get("input")
            if isinstance(nested, Mapping):
                candidates.append(nested)
    task: Mapping[str, Any] = {}
    for candidate in candidates:
        raw_task = candidate.get("specialist_task")
        if isinstance(raw_task, Mapping):
            task = raw_task
            break
    task_archetype = str(task.get("archetype", archetype))
    if task and task_archetype != archetype:
        raise ValueError(
            "winning swarm runtime archetype does not match specialist_task"
        )
    catalog = role_catalog[archetype]
    catalog_target = str(catalog["merge_target"])
    assigned_target = str(task.get("merge_target", catalog_target))
    dynamic_mission_graph = any(
        str(candidate.get("execution_profile_id", ""))
        == "winning_swarm_dynamic_v2"
        for candidate in candidates
    )
    expected_target = (
        assigned_target
        if dynamic_mission_graph
        and assigned_target in {"S1", "S2", "S3", "S4", "S5", "S6"}
        else catalog_target
    )
    if assigned_target != expected_target:
        raise ValueError(
            "winning swarm specialist_task crossed its catalog merge boundary"
        )
    allow_child_spawn = bool(task.get("allow_child_spawn", False))
    if allow_child_spawn:
        raise ValueError("dynamic specialists may not recruit child agents")
    role_contract = {
        "runtime_profile_id": f"winning_swarm_{archetype}",
        "version": "1.0",
        "archetype": archetype,
        "display_name": str(catalog["display_name"]),
        "purpose": str(catalog["purpose"]),
        "merge_target": expected_target,
        "quality_residuals": list(catalog.get("residuals", [])),
        "quality_gates": [
            f"必须实质改善 {residual}"
            for residual in catalog.get("residuals", [])
        ],
        "skill_ids": list(SWARM_RUNTIME_SKILL_IDS),
        "allow_child_spawn": False,
    }
    assignment = {
        "task_id": str(task.get("task_id", "")),
        "agent_instance_id": str(task.get("agent_instance_id", "")),
        "hypothesis_id": str(task.get("hypothesis_id", "")),
        "wave": task.get("wave", 0),
        "merge_target": assigned_target,
        "trigger_residuals": [
            str(item) for item in task.get("trigger_residuals", []) if str(item)
        ][:8],
        "expected_quality_gain": task.get("expected_quality_gain", 0),
        "allow_child_spawn": False,
    }
    return {"role_contract": role_contract, "assignment": assignment}


def _unique(values: Sequence[Any] | Any) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in (None, "", [], {}) and value not in result:
            result.append(value)
    return result


__all__ = [
    "CODEX_AGENT_RUNTIME_PROFILES",
    "CODEX_BRANCH_RUNTIME_PROFILES",
    "SAFETY_BOUNDARY",
    "MILITARY_MISSION_LENSES",
    "build_codex_runtime_profile",
    "is_aggressive_optimized_v2_payload",
    "is_dynamic_winning_payload",
    "is_optimized_v2_payload",
    "military_mission_lens",
]
