"""S1-S6 winning-mechanism workflow.

The provider host supplies model I/O, budgets, callbacks and metrics through
the same runtime port used before this extraction.
"""
# ruff: noqa: F821, F841

from __future__ import annotations

from typing import Any

from equipment_deep_research.agents.designs.winning_s6_image import (
    CAPABILITY_OVERVIEW_GUIDANCE,
    CAPABILITY_CLASSIFICATION_GUIDANCE,
    CAPABILITY_PORTRAIT_CONCISION_GUIDANCE,
    FRONTLINE_LANGUAGE_GUIDANCE,
    INNOVATIVE_CAPABILITY_IMAGE_GUIDANCE,
    OPERATIONAL_FEASIBILITY_GUIDANCE,
    TECHNOLOGY_IMPLEMENTATION_GUIDANCE,
)
from equipment_deep_research.orchestration.capability_portrait import (
    assemble_capability_portrait_modules,
    parse_capability_portrait_modules,
)
from equipment_deep_research.orchestration.winning_swarm import (
    COMBAT_EQUIPMENT_DIVERGENCE_DIMENSIONS,
    QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION,
)

# Loaded lazily after the coordinator has completed initialization. The
# workflow reuses stable helper functions during the compatibility migration.
from equipment_deep_research.agents.workflows import coordinator as _legacy
from equipment_deep_research.agents.workflows.winning_stages import stage_for

globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)


def _open_s3_exploration_brief(
    topic: str,
    structured_query_brief: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Give early winning Agents the problem boundary, not blueprint answers.

    The discovery blueprint may contain useful downstream planning hypotheses,
    but fields that already resemble weapon architectures, enabling solutions
    or project theses strongly anchor an otherwise isolated Codex session.  The
    creative S3/S4 producers therefore receive the Query-derived combat problem
    and controller blueprint, while S5 may inspect the full brief for review.
    """

    full = _query_combat_equipment_divergence_brief(
        topic,
        structured_query_brief=structured_query_brief or {},
    )
    boundary_keys = (
        "query",
        "combat_problem_frame",
        "enemy_target_profile",
        "battle_phase_and_constraints",
        "required_direct_military_effects",
        "equipment_semantic_boundary",
        "winning_problem_propositions",
    )
    return {
        **{key: full.get(key, [] if key.endswith("s") else "") for key in boundary_keys},
        "generation_rules": [
            "先独立理解战场矛盾，再自由提出技术—效应—武器构型；不得把蓝图字段当候选答案",
            "先比较多个真正不同的实现原理与制胜关系，选定后才闭合装备身份和名称",
            "公开基线用于反事实比较，不作为装备目录、型号谱系或命名来源",
            "颠覆角度仅作开放启发，不构成固定技术路线、装备类别或数量配额",
        ],
        "solution_hypotheses_withheld": True,
    }


def _open_s3_theme_contract() -> dict[str, Any]:
    """Keep shared examples and fixed lenses out of creative generation."""

    return {
        "authority": "完整Query语义和本会话军事判断",
        "candidate_boundary": (
            "候选主体是直接接敌并形成可验证战果的具体武器；网络、算法和保障只能作为内部约束"
        ),
        "creative_freedom": (
            "不预设装备族、技术路线、创新维度、候选数量或命名格式"
        ),
        "template_guard": "换成另一Query仍基本成立时重新发散",
        "examples_withheld": True,
    }


def _open_s3_theme_instruction() -> str:
    contract = _open_s3_theme_contract()
    return "装备开放探索约束：" + "".join(str(value) for value in contract.values())


def _creative_s3_candidate_instruction() -> str:
    """Give S3/S4 a genuinely light creative contract."""

    return (
        "从Query战场矛盾出发，自主创造少量能直接接敌并形成战果的单一武器装备。"
        "输入中的可选多样性挑战只用于打开不同思路，制胜维度和开放挑战都只是可接受、重构或舍弃的启发；不得按字段、目录、"
        "热门技术或固定句式拼装答案。先在内部比较不同物理原理、战场存在方式和交换关系，"
        "并主动检查侦察感知、打击、毁伤、突防、拦截、压制、拒止、生存抗毁及Query特有维度之间"
        "是否存在值得交叉的新关系；这些维度可全部舍弃，也可混合或自创，不是一会话一维度。"
        "再一次性闭合装备身份、自然名称、关键机理和直接战果。通信、算法、数据链与保障只能作为"
        "装备内部条件，不能成为候选主体。不要讨论证据、成熟度、成本产能、验证计划或敌方反适应；"
        "这些不属于轻型创造会话。"
        + QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
        + "构型意象型、原理突破型、装备专名型仅是开放参考，可混合、舍弃或自创第四种命名方式。"
        "名称应来自整装语义，只抓最有辨识度的创新主线，不用维度词机械拼名。"
        "只输出schema规定的严格JSON，不输出推理过程。"
    )


def _minimal_s6_card_handoff(brief: Mapping[str, Any]) -> dict[str, Any]:
    """Project one frozen S5 decision spine into a small, per-card S6 handoff."""

    def compact(value: Any, limit: int = 360) -> Any:
        if isinstance(value, str):
            text = " ".join(value.split()).strip()
            if len(text) <= limit:
                return text
            candidate = text[:limit]
            boundary = max(candidate.rfind(mark) for mark in "。！？；")
            return candidate[: boundary + 1] if boundary >= limit // 2 else candidate
        if isinstance(value, Mapping):
            return {str(k): compact(v, 180) for k, v in list(value.items())[:8] if v not in (None, "", [], {})}
        if isinstance(value, (list, tuple)):
            return [compact(v, 180) for v in list(value)[:4] if v not in (None, "", [], {})]
        return value

    fields = (
        "hypothesis_id", "name", "primary_equipment_identity", "equipment_form",
        "unique_operational_role", "target_and_direct_effect",
        "non_substitutable_difference", "query_relevance", "indicator_portrait",
        "failure_boundary", "concise_winning_summary",
    )
    result = {key: compact(brief[key]) for key in fields if brief.get(key) not in (None, "", [], {})}
    result["handoff_contract"] = "S5冻结决策脊柱；S6只写本卡画像，不改身份、分类、指标或Query关联。"
    return result


def _dynamic_s6_card_input(
    brief: Mapping[str, Any],
    *,
    query: str,
) -> dict[str, Any]:
    """Build the only context a dynamic S6 writer is allowed to see.

    S6 is a semantic author, not an S5 form filler.  In dynamic-v2 the model
    receives the Query boundary, one candidate weapon identity and its winning
    logic summary.  Indicators, classifications, evidence, validation and
    portfolio metadata stay outside the model call and are never allowed to
    anchor the portrait.
    """

    candidate = {
        key: str(brief.get(key, "")).strip()
        for key in (
            "name",
            "primary_equipment_identity",
            "equipment_form",
            "target_and_direct_effect",
        )
        if str(brief.get(key, "")).strip()
    }
    winning_logic = str(
        brief.get("concise_winning_summary")
        or brief.get("winning_mechanism")
        or brief.get("non_substitutable_difference")
        or brief.get("decisive_advantage_thesis")
        or brief.get("disruptive_shift")
        or ""
    ).strip()
    return {
        "query_semantics": str(query or brief.get("query_relevance", "")).strip(),
        "candidate_weapon": candidate,
        "winning_logic_overview": winning_logic,
    }


def _minimal_portfolio_candidate_handoff(item: Any) -> dict[str, Any]:
    """Expose only the military identity axes needed by incremental S5."""

    return {
        "hypothesis_id": str(item.hypothesis_id),
        "title": str(item.title),
        "equipment_form": list(item.equipment_forms[:2]),
        "target_and_direct_effect": (
            str(item.project_function)
            or "；".join(str(value) for value in item.direct_military_effects[:2])
        ),
        "changed_confrontation_variable": str(
            item.changed_confrontation_variable
        ),
        "core_mechanism": list(item.mechanism_chain[:4]),
        "direct_military_results": list(item.direct_military_effects[:3]),
        "unique_operational_role": str(item.independence_thesis),
        "disruptive_shift": str(item.disruptive_shift),
    }


def _compact_s6_authored_card_event(direction: Mapping[str, Any]) -> dict[str, Any]:
    """Publish one bounded but complete S6 card for live API projection."""

    keep = (
        "hypothesis_id", "name", "source_hypothesis_title", "type",
        "primary_equipment_identity", "equipment_form", "equipment_family",
        "unique_operational_role", "launch_or_release_domain",
        "target_and_direct_effect", "non_substitutable_difference",
        "baseline_system", "capability_gap", "target_scenario", "function",
        "operational_mechanism", "operational_process", "capability_outcome",
        "military_value", "winning_mechanism", "capability_portrait",
        "capability_portrait_modules", "semantic_consistency_check",
        "s6_authoring_status", "indicator_portrait", "query_relevance",
        "direct_evidence_refs", "evidence_boundary", "validation_plan",
        "failure_boundary", "adversary_adaptation", "priority", "confidence",
        "expert_score", "verification_status", "confidence_limited",
        "selection_quality_status", "capability_classification",
        "direct_combat_equipment",
    )
    return {
        key: _compact_prompt_value(
            direction.get(key),
            max_string_chars=1800 if key == "capability_portrait" else 520,
            max_list_items=12,
        )
        for key in keep
        if direction.get(key) not in (None, "", [], {})
    }


def _quality_cluster_candidate_instruction() -> str:
    """Keep quality-cluster breadth creative while preserving evidence discipline."""

    return (
        "质量集群广度会话负责创造真正值得继续论证的具体武器，不按角色名称、装备目录、"
        "热门技术或固定数量生产答案。先理解Query中的目标、阶段、敌方优势和我方关键限制，"
        "在内部比较最强常规升级、非装备方案与多种前沿物理/工程路线；只保留能够改变武器本体、"
        "接敌方式、效应关系或战争交换关系，且可由试验判退的方向。"
        "每个候选只允许一个唯一主装备身份，说明使用主体、作用条件、关键动作、直接战果、前沿原理、"
        "常规方案不能吸收的技术断点、决定性工程瓶颈、体系接口、对手反适应和失败边界。"
        "公开资料证明已有底座，拟议创新明确为待验证假设；缺少同名公开型号不机械淘汰，"
        "也不得虚构列装、成熟度、性能或产能。reference_overview只用通俗中文概括独特战场条件、"
        "制胜关系和直接战果，不复述字段或套统一句式；naming_rationale说明整装命名理由，不得逐词拆解。"
        + QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
        + "只输出schema规定的严格JSON，不输出比较过程。"
    )


def _parallel_s6_card_instruction() -> str:
    """Return the compact role contract for one isolated S6 card session."""

    return (
        "你是S6单装备能力画像作者，在独立Codex CLI会话中只完成这一张候选卡。"
        "输入严格只有query_semantics、candidate_weapon、winning_logic_overview三项；不得要求或臆造"
        "S5指标、分类、证据、验证、失败边界、组合位置或其他卡信息。候选武器身份是写作锚点，"
        "不得换成另一装备，但你拥有本卡场景推演、技术论证、作战流程、能力分类和文字编辑权。先独立理解它为何能改变Query中的战场关系，"
        "再推演其专属作战链与可实现的装备本体，再直接写成决策短卡：概述、技术实现、作战流程、"
        "能力效果、制胜逻辑。每栏约120至150个中文字作为软编辑目标，不因篇幅偏差失败、重试或截断；"
        "五栏各自回答不同问题，正文合计约450至1400字，删除重复背景和空泛"
        "智能化标签；技术栏讲清决定性瓶颈、核心原理怎样落实到装备本体及接口/能源/材料/控制/制造约束；"
        "必要时说明样机、半实物或对抗试验和判退结果，不用成熟度标签、热门技术或组件清单代替判断；"
        "流程栏只写该装备独有的交战节点，交代行动主体、进入条件、关键动作、任务状态变化和转入下一节点的条件；"
        "不要套用发现—决策—打击—评估的通用骨架；效果栏写"
        "新增战果及由此形成的新任务或新场景，能力分类必须显示在画像开头；制胜栏写被改写的敌我交换关系。使用一线设计人员能直接理解的通俗准确中文。成稿前静默删除跨栏重复、生僻造词、无解释缩写，"
        "核对主装备、行动主体、目标和战果一致，并令semantic_consistency_check.consistent为JSON"
        "布尔true。只输出schema规定的严格JSON。"
    )


def _dynamic_role_contract_handoff(contract: Any, task: Any) -> dict[str, Any]:
    """Expose authority and handoff boundaries without replaying rule lists."""

    node = str(contract.mission_node)
    authority = {
        "S1": "自主重构对手成功逻辑、体系依赖、反适应与失效窗口；不预定装备答案。",
        "S2": "自主比较任务组织、力量运用和非装备对照；不预定装备答案。",
        "S3": "与S4同权自主定义问题并创造具体武器候选；多维交叉判断优先于任何分配建议。",
        "S4": "与S3同权自主定义问题并创造具体武器候选；不承担后置物化、映射或机械补全。",
        "S5": "只拥有组合语义准入、合并和判退权，不补写或审查候选内容。",
        "S6": "只接收Query语义、候选武器身份和对应制胜逻辑概述；自主完成分类、技术、流程和画像。",
    }.get(node, "在声明节点内自主完成军事判断。")
    handoff = {
        "S1": "只交接对手优势、战场矛盾、可改变关系和期望战果。",
        "S2": "只交接任务关系、效应窗口、可改变关系和期望战果。",
        "S3": "只交接最小装备身份、制胜机理和直接战果。",
        "S4": "只交接最小装备身份、制胜机理和直接战果。",
        "S5": "冻结入选装备的军事决策脊柱供S6逐项继承。",
        "S6": "交付单卡画像和语义一致性结论。",
    }.get(node, "只交接声明节点的结构化结论。")
    return {
        "contract_id": str(contract.role_contract_id),
        "role": str(task.display_name),
        "mission_node": node,
        "mandate": str(task.purpose),
        "decision_authority": authority,
        "handoff_contract": handoff,
        "prohibitions": [
            "不得读取或复述其他Agent原始会话",
            "不得招募子Agent或扩大节点权限",
            "不得把内部流程、评审措辞或交接状态写入候选内容",
        ],
    }


async def analyze_winning_subagents(
    host,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run S1-S6 as independent Codex sessions with explicit handoffs."""
    metric_offset = host._call_metric_count()
    shared = {
        "run_id": payload.get("run_id", ""),
        "topic": payload.get("topic", ""),
        "structured_query_brief": payload.get("structured_query_brief", {}),
        "research_route": payload.get("research_route", ""),
        "discovery_blueprint": payload.get("discovery_blueprint", {}),
        "discovery_branch": payload.get("discovery_branch", ""),
        "coverage": payload.get("coverage", {}),
        "packets": payload.get("packets", []),
        "military_value_handoff": payload.get("military_value_handoff", {}),
        "evidence_index": payload.get("evidence_index", []),
        "discovery_convergence": payload.get("discovery_convergence", {}),
        "new_evidence_ids": payload.get("new_evidence_ids", []),
        "new_packet_ids": payload.get("new_packet_ids", []),
        "shared_skill_catalog": payload.get("shared_skill_catalog", []),
        "knowledge_pack_catalog": payload.get("knowledge_pack_catalog", []),
        "resume_from": payload.get("resume_from", "L1"),
        "attempt": payload.get("attempt", 1),
        "selected_business_agent_ids": payload.get(
            "selected_business_agent_ids", []
        ),
        "prior_winning_analysis": payload.get("prior_winning_analysis", {}),
        "resume_steps": payload.get("resume_steps", []),
        "execution_profile_id": payload.get("execution_profile_id", "legacy_v1"),
        "execution_contract": payload.get("execution_contract", {}),
        "ablation_scope": payload.get("ablation_scope", ""),
        "evidence_closed": bool(payload.get("evidence_closed", False)),
    }
    optimized_v2 = is_quality_execution_profile_id(shared["execution_profile_id"])
    aggressive_compaction = shared["execution_profile_id"] == "optimized_v2"
    analysis_priority_contract = {
        "primary": [
            "current_agent_specialist_role_and_method",
            "query_military_problem",
            "direct_combat_value",
        ],
        "secondary_only": "cross_agent_handoff_for_evidence_constraints_counterevidence",
        "handoff_must_not_control": [
            "agenda",
            "structure",
            "naming",
            "priority",
            "final_conclusion",
        ],
    }

    raw_military_handoff = shared.get("military_value_handoff", {})
    military_value_claims = [
        {
            "claim_id": str(item.get("claim_id", "")),
            "claim_type": str(item.get("claim_type", "inference")),
            "source_agent_id": str(item.get("source_agent_id", "")),
            "packet_id": str(item.get("packet_id", "")),
            "military_effects": list(item.get("military_effects", []))[:5],
            "mechanism": str(item.get("mechanism", ""))[:460],
            "mission_condition": str(item.get("mission_condition", ""))[:180],
            "failure_boundary": str(item.get("failure_boundary", ""))[:220],
            "evidence_ids": list(item.get("evidence_ids", []))[:3],
            "source_urls": list(item.get("source_urls", []))[:2],
            "confidence": item.get("confidence"),
            "downstream_steps": list(item.get("downstream_steps", []))[:5],
        }
        for item in (
            raw_military_handoff.get("claims", [])
            if isinstance(raw_military_handoff, Mapping)
            else []
        )
        if isinstance(item, Mapping) and str(item.get("mechanism", "")).strip()
    ]
    military_branch_products = (
        raw_military_handoff.get("branch_products", {})
        if isinstance(raw_military_handoff, Mapping)
        else {}
    )
    baseline_boundaries = [
        {
            "packet_id": str(item.get("packet_id", "")),
            "agent_id": str(item.get("agent_id", "")),
            "availability": "unavailable",
            "limitations": [
                str(value)[:260] for value in item.get("limitations", [])[:2]
            ],
            "open_questions": [
                str(value)[:260] for value in item.get("open_questions", [])[:2]
            ],
            "downstream_obligations": [
                str(value)[:300] for value in item.get("downstream_obligations", [])[:3]
            ],
        }
        for item in (
            raw_military_handoff.get("baseline_boundaries", [])
            if isinstance(raw_military_handoff, Mapping)
            else []
        )
        if isinstance(item, Mapping)
        and str(item.get("availability", "")) == "unavailable"
    ]
    baseline_frontier_inspirations = [
        {
            "source_agent_id": str(item.get("source_agent_id", "")),
            "packet_id": str(item.get("packet_id", "")),
            "signal": str(item.get("signal", ""))[:220],
            "conventional_assumption_challenged": str(
                item.get("conventional_assumption_challenged", "")
            )[:180],
            "possible_military_discontinuity": str(
                item.get("possible_military_discontinuity", "")
            )[:220],
            "query_relevance": str(item.get("query_relevance", ""))[:180],
            "evidence_boundary": str(item.get("evidence_boundary", ""))[:220],
            "downstream_question": str(item.get("downstream_question", ""))[:220],
            "evidence_ids": list(item.get("evidence_ids", []))[:3],
            "source_urls": list(item.get("source_urls", []))[:2],
        }
        for item in (
            raw_military_handoff.get("frontier_inspirations", [])
            if isinstance(raw_military_handoff, Mapping)
            else []
        )
        if isinstance(item, Mapping) and str(item.get("signal", "")).strip()
    ][:6]

    def military_claims_for_steps(indices: Sequence[int]) -> list[dict[str, Any]]:
        targets = {f"S{index}" for index in indices if 1 <= index <= 5}
        rows = [
            item
            for item in military_value_claims
            if targets.intersection(map(str, item.get("downstream_steps", [])))
        ]
        return rows[: min(8, max(4, len(indices) * 3))]

    def military_packet_refs_for_claims(
        claims: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        packet_ids = {
            str(item.get("packet_id", ""))
            for item in claims
            if str(item.get("packet_id", ""))
        }
        return [
            {
                "packet_id": item["packet_id"],
                "agent_id": item["agent_id"],
                "evidence_ids": item["evidence_ids"][:3],
                "confidence": item["confidence"],
            }
            for item in packet_index
            if item["packet_id"] in packet_ids
        ]

    def evidence_for_claims(
        claims: Sequence[Mapping[str, Any]],
        *,
        prior_step_outputs: Mapping[str, Any] | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        relevant_ids = {
            str(evidence_id)
            for item in claims
            for evidence_id in item.get("evidence_ids", [])
            if str(evidence_id)
        }
        relevant_ids.update(_collect_reference_ids(prior_step_outputs or {}))
        return [
            dict(item)
            for item in shared.get("evidence_index", [])
            if isinstance(item, Mapping)
            and str(item.get("evidence_id", "")) in relevant_ids
        ][:limit]

    packet_index = [
        {
            "packet_id": str(item.get("packet_id", "")),
            "agent_id": str(item.get("agent_id", "")),
            "capability_tags": list(item.get("capability_tags", [])),
            "handoff_summary": str(item.get("handoff_summary", "")),
            "evidence_ids": list(item.get("evidence_ids", [])),
            "confidence": item.get("confidence"),
            "open_questions": list(item.get("open_questions", []))[:3],
        }
        for item in shared["packets"]
        if isinstance(item, Mapping)
    ]

    def packet_projection(item: Mapping[str, Any], *, step: int) -> dict[str, Any]:
        """Keep only decision-bearing handoff fields for the current S-step."""
        agent_id = str(item.get("agent_id", ""))
        case_packet = agent_id == "case_research" and step in {3, 4, 5, 6}
        payload_value = item.get("business_payload", item.get("payload", {}))
        projected = {
            "packet_id": str(item.get("packet_id", "")),
            "agent_id": agent_id,
            "summary": str(item.get("summary", "") or item.get("handoff_summary", "")),
            "findings": list(item.get("findings", []))[: (6 if case_packet else 3)],
            "business_payload": payload_value,
            "evidence_ids": list(item.get("evidence_ids", []))[
                : (12 if case_packet else 6)
            ],
            "confidence": item.get("confidence"),
            "limits": list(item.get("limits", item.get("limitations", [])))[:1],
            "next_questions": list(
                item.get("next_questions", item.get("open_questions", []))
            )[:1],
        }
        return _compact_prompt_value(
            {
                key: value
                for key, value in projected.items()
                if value not in (None, "", [], {})
            },
            max_string_chars=900 if case_packet else 220,
            max_list_items=10 if case_packet else 3,
        )

    valid_evidence_ids = {
        str(item.get("evidence_id", ""))
        for item in shared.get("evidence_index", [])
        if isinstance(item, Mapping) and str(item.get("evidence_id", "")).strip()
    }
    valid_packet_ids = {
        str(item.get("packet_id", ""))
        for item in packet_index
        if str(item.get("packet_id", "")).strip()
    }
    valid_reference_ids = valid_evidence_ids | valid_packet_ids
    packet_agents_by_step = {
        1: {
            "international_situation",
            "opponent_monitoring",
            "system_confrontation",
            "weapon_equipment",
        },
        2: {
            "combat_scenario",
            "operational_employment",
            "international_situation",
        },
        3: set(),
        4: {
            "combat_scenario",
            "operational_employment",
            "system_confrontation",
            "weapon_equipment",
        },
        5: {
            "weapon_equipment",
            "system_confrontation",
            "combat_scenario",
        },
        6: set(),
    }
    primary_branch_for_packets = str(
        shared.get("discovery_blueprint", {}).get("primary_branch", "")
        if isinstance(shared.get("discovery_blueprint", {}), Mapping)
        else ""
    )
    if primary_branch_for_packets == "C":
        for step in (3, 4, 5, 6):
            packet_agents_by_step[step].add("case_research")

    def step_shared_context(
        index: int,
        prior_step_outputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        blueprint = shared.get("discovery_blueprint", {})
        compact_blueprint = (
            {
                key: blueprint.get(key)
                for key in (
                    "execution_profile_id",
                    "primary_branch",
                    "runtime_route",
                    "emphasis",
                    "required_outputs",
                    "reference_focus",
                    "focus_questions",
                    "hard_constraints",
                    "structured_query_brief",
                    "adaptive_winning_step_modes",
                )
                if blueprint.get(key) not in (None, "", [], {})
            }
            if isinstance(blueprint, Mapping)
            else {}
        )
        if optimized_v2:
            compact_blueprint["execution_profile_id"] = shared["execution_profile_id"]
        allowed_agents = packet_agents_by_step[index]
        case_projection = primary_branch_for_packets == "C" and index in {3, 4, 5, 6}
        step_claims = (
            military_claims_for_steps([index]) if optimized_v2 and index <= 5 else []
        )
        if optimized_v2:
            evidence_rows = evidence_for_claims(
                step_claims,
                prior_step_outputs=prior_step_outputs,
                limit=12 if case_projection else (10 if index in {1, 2} else 8),
            )
            selected_packets: list[Mapping[str, Any]] = []
            step_packet_index = military_packet_refs_for_claims(step_claims)
        else:
            evidence_rows = _prioritized_evidence_index(
                shared["evidence_index"],
                preferred_ids=_collect_reference_ids(prior_step_outputs or {}),
                allowed_agents=allowed_agents,
                limit=16 if index in {1, 2} else 12,
            )
            selected_packets = [
                item
                for item in shared["packets"]
                if isinstance(item, Mapping)
                and str(item.get("agent_id", "")) in allowed_agents
            ]
            step_packet_index = packet_index
        context = {
            "topic": shared["topic"],
            "query": shared["topic"],
            "structured_query_brief": _compact_prompt_value(
                shared.get("structured_query_brief", {}),
                max_string_chars=360,
                max_list_items=8,
            ),
            "query_combat_equipment_divergence_brief": (
                _query_combat_equipment_divergence_brief(
                    str(shared.get("topic", "")),
                    structured_query_brief=shared.get("structured_query_brief", {}),
                )
            ),
            "research_route": shared["research_route"],
            "discovery_branch": shared["discovery_branch"],
            "execution_profile_id": shared["execution_profile_id"],
            "analysis_priority": analysis_priority_contract,
            "discovery_blueprint": compact_blueprint,
            "packet_index": _compact_prompt_value(
                step_packet_index,
                max_string_chars=220 if aggressive_compaction else 280,
                max_list_items=6 if aggressive_compaction else 8,
            ),
            "packets": (
                [packet_projection(item, step=index) for item in selected_packets]
                if optimized_v2
                else _compact_prompt_value(
                    selected_packets,
                    max_string_chars=1200
                    if case_projection
                    else (420 if index in {1, 2} else 280),
                    max_list_items=14
                    if case_projection
                    else (6 if index in {1, 2} else 4),
                )
            ),
            "secondary_cross_agent_constraints": (
                _compact_prompt_value(
                    step_claims,
                    max_string_chars=460,
                    max_list_items=6,
                )
                if optimized_v2 and index <= 5
                else []
            ),
            "branch_products": (
                _compact_prompt_value(
                    military_branch_products,
                    max_string_chars=360,
                    max_list_items=8,
                )
                if optimized_v2
                and primary_branch_for_packets == "C"
                and index in {3, 4, 5}
                else {}
            ),
            "evidence_index": _compact_prompt_value(
                evidence_rows,
                max_string_chars=240 if aggressive_compaction else 300,
                max_list_items=len(evidence_rows),
            ),
            "discovery_convergence": _compact_prompt_value(
                (
                    shared.get("discovery_convergence", {})
                    if not aggressive_compaction and index in {1, 2}
                    else {}
                ),
                max_string_chars=260 if aggressive_compaction else 420,
                max_list_items=3 if aggressive_compaction else 6,
            ),
        }
        step_agent_id = stage_for(index).agent_id
        if index == 5:
            selected_seed_context = disruptive_seed_context(
                str(shared.get("topic", "")),
                branch=primary_branch_for_packets,
                agent_id=step_agent_id,
            )
            if selected_seed_context:
                context["disruptive_seed_context"] = selected_seed_context
        if index <= 5:
            context["military_divergence_contract"] = (
                _winning_military_divergence_contract(index)
            )
        if not optimized_v2:
            context.update(
                {
                    "coverage": shared["coverage"],
                    "resume_from": shared["resume_from"],
                    "attempt": shared["attempt"],
                }
            )
        elif index in {1, 2} and shared.get("coverage"):
            context["coverage"] = _compact_prompt_value(
                shared["coverage"], max_string_chars=180, max_list_items=3
            )
        recall_increment = {
            "new_evidence_ids": list(shared.get("new_evidence_ids", []))[:12],
            "new_packet_ids": list(shared.get("new_packet_ids", []))[:6],
        }
        if any(recall_increment.values()):
            context["recall_increment"] = recall_increment
        return {
            key: value
            for key, value in context.items()
            if value not in (None, "", [], {})
        }

    def compact_for_prompt(
        value: Any,
        *,
        max_string_chars: int = 900,
        max_list_items: int = 8,
    ) -> Any:
        """Bound repeated model context without changing the stored result."""
        return _compact_prompt_value(
            value,
            max_string_chars=max_string_chars,
            max_list_items=max_list_items,
        )

    def round_review_projection(value: Mapping[str, Any]) -> dict[str, Any]:
        keys = (
            "defense_decomposition",
            "operational_review",
            "winning_paths",
            "breakthrough_directions",
            "effect_chain",
            "capability_mapping",
            "dotmlpf_matrix",
            "s4_concept_directions",
            "gap_assessment",
            "concept_directions",
            "capability_image_drafts",
            "upstream_coverage",
            "evidence_validation",
            "reasoning_nodes",
            "open_questions",
        )
        return compact_for_prompt(
            {key: value[key] for key in keys if key in value},
            max_string_chars=700,
            max_list_items=6,
        )

    def prior_projection(
        index: int,
        prior_step_outputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        field_map = {
            1: (),
            2: ("defense_decomposition",),
            3: (
                "defense_decomposition",
                "operational_review",
                "winning_paths",
                "existing_tactic_baseline",
                "tactic_concepts",
                "tactic_validation_results",
            ),
            4: ("breakthrough_directions", "effect_chain"),
            5: (
                "capability_mapping",
                "dotmlpf_matrix",
                "s4_concept_directions",
            ),
            6: (
                "capability_mapping",
                "gap_assessment",
                "s4_concept_directions",
            ),
        }
        if index == 6:
            projected = _compact_s6_prior_outputs(prior_step_outputs)
            if aggressive_compaction:
                projected = compact_for_prompt(
                    projected,
                    max_string_chars=420,
                    max_list_items=6,
                )
        else:
            projected = {
                key: compact_for_prompt(
                    prior_step_outputs[key],
                    max_string_chars=520 if aggressive_compaction else 900,
                    max_list_items=6 if aggressive_compaction else 8,
                )
                for key in field_map[index]
                if key in prior_step_outputs
            }
        raw_nodes = prior_step_outputs.get("reasoning_nodes", {})
        if not aggressive_compaction and isinstance(raw_nodes, Mapping):
            projected["reasoning_nodes"] = {
                str(step): compact_for_prompt(
                    value,
                    max_string_chars=500,
                    max_list_items=6,
                )
                for step, value in raw_nodes.items()
                if str(step).isdigit() and int(str(step)) <= index
            }
        dynamic_rows = prior_step_outputs.get("dynamic_subagent_outputs", [])
        if isinstance(dynamic_rows, list):
            allowed_merge_targets = {f"S{index}"}
            if index == 6:
                allowed_merge_targets.add("convergence")
            eligible_dynamic_rows = [
                item
                for item in dynamic_rows
                if isinstance(item, Mapping)
                and item.get("accepted", True) is True
                and str(item.get("merge_target", "")) in allowed_merge_targets
                and isinstance(item.get("result", {}), Mapping)
            ]
            projected["dynamic_inputs"] = [
                {
                    "agent_instance_id": str(item.get("agent_instance_id", "")),
                    "hypothesis_id": str(item.get("hypothesis_id", "")),
                    "merge_target": str(item.get("merge_target", "")),
                    "findings": list(result.get("findings", []))[
                        : (2 if aggressive_compaction else 4)
                    ],
                    "contribution_to_steps": list(
                        result.get("contribution_to_steps", [])
                    )[: (2 if aggressive_compaction else 4)],
                    "evidence_refs": list(result.get("evidence_refs", []))[
                        : (4 if aggressive_compaction else 8)
                    ],
                    "open_questions": list(result.get("open_questions", []))[:1],
                    "confidence": result.get("confidence"),
                }
                for item in eligible_dynamic_rows[: (4 if optimized_v2 else 3)]
                if isinstance((result := item.get("result", {})), Mapping)
            ]
        winning_swarm = prior_step_outputs.get("winning_swarm", {})
        if index in {4, 5, 6} and isinstance(winning_swarm, Mapping):
            finalists = winning_swarm.get("finalists", [])
            if isinstance(finalists, list):
                projected["winning_hypotheses"] = [
                    compact_for_prompt(
                        item,
                        max_string_chars=420 if aggressive_compaction else 700,
                        max_list_items=6,
                    )
                    for item in finalists[:4]
                    if isinstance(item, Mapping)
                ]
        return projected

    def sanitize_references(value: Any) -> Any:
        if isinstance(value, list):
            return [sanitize_references(item) for item in value]
        if not isinstance(value, Mapping):
            return value
        cleaned: dict[str, Any] = {}
        removed_refs: list[str] = []
        for key, item in value.items():
            if key in {"evidence_refs", "direct_evidence_refs"} and isinstance(
                item, list
            ):
                accepted = [str(ref) for ref in item if str(ref) in valid_reference_ids]
                removed_refs.extend(
                    str(ref) for ref in item if str(ref) not in valid_reference_ids
                )
                cleaned[key] = list(dict.fromkeys(accepted))
            else:
                cleaned[str(key)] = sanitize_references(item)
        if removed_refs and "derived_from" in cleaned:
            existing = cleaned.get("derived_from", [])
            existing_rows = list(existing) if isinstance(existing, list) else []
            cleaned["derived_from"] = list(
                dict.fromkeys([*map(str, existing_rows), *removed_refs])
            )
        return cleaned

    primary_branch = str(
        shared.get("discovery_blueprint", {}).get("primary_branch", "")
        if isinstance(shared.get("discovery_blueprint", {}), Mapping)
        else ""
    ) or {
        "new_winning_mechanism": "A",
        "traditional_gap": "B",
        "war_case_learning": "C",
    }.get(str(shared.get("research_route", "")), "B")
    branch_product_schema = _branch_product_output_schema(primary_branch)

    if shared["evidence_closed"]:
        query_led_combat_rule = (
            "消融共同规则（证据闭合）：query只定义研究边界和需回答的问题，不是事实、装备现状、"
            "成熟度、性能或作战机理的独立证据。所有事实、比较、能力判断、装备对象、成熟度判断和"
            "因果结论必须逐项来自输入generic packet或evidence_index，并保留对应证据ID/packet_id。"
            "禁止使用模型常识、训练记忆或常识性军事知识补齐被移除的专业多源基线；没有输入依据时"
            "必须写‘未形成’或‘待验证’，不得为了满足数量、结构或门禁而虚构候选。仍按当前S步骤"
            "专用方法完成分析，但结论强度和覆盖范围必须随证据表面真实收缩。"
        )
    else:
        query_led_combat_rule = (
            "共同规则：分析优先级固定为当前S步骤专用角色与方法、query军事任务与对抗问题、"
            "打击/歼灭/反制/拒止/威慑等直接军事价值；三者共同主导主动发散多个机制真正不同的"
            "作战假设或候选方案，再比较收敛。跨Agent精简交接和公开证据只作为次级事实素材、"
            "约束与反证，不得决定议题、结构、术语、命名、优先级或结论。每个候选必须说明任务对象、"
            "作战阶段、打击/歼灭/反制/拒止/威慑/抗毁效果、对手反适应和失败边界。"
        )
    equipment_theme_rule = _query_led_combat_equipment_theme_instruction()
    steps = [
        (
            "winning_s1_opponent",
            query_led_combat_rule
            + "S1 对手分析子Agent：从query直接形成必要数量的竞争性对手体系与反适应假设；数量由"
            "关键不确定性和解释差异决定，不以配额补齐。再从敌方"
            "感知、决策、火力、保障与恢复链中识别薄弱环节；不得只复述上游威胁清单。"
            "defense_decomposition每项按‘竞争假设—体系依赖—任务级薄弱环节—我方军事窗口—"
            "对手反适应—失败边界—事实/推断/假设’压缩表达。"
            "说明哪些任务级环节可被削弱、延迟、欺骗、拒止或制衡，以及由此形成的军事效果和失效边界。"
            "必须区分证据、推断和假设，不得生成可直接执行的攻击指令。只输出严格JSON。",
            {
                "defense_decomposition": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s2_operations",
            query_led_combat_rule
            + "S2 作战运用审查子Agent：回到query审查现有任务链、作战概念、协同关系、保障条件"
            "和失败模式，形成少量但机制真正不同的制胜路径；路径数量由可解释的竞争方案决定，"
            "不得为满足数字而拆分同一思路。S1只提供"
            "对手约束，不能限定本步骤的方案空间。说明各路径对打击/歼灭闭环、反制效率、拒止强度、抗毁恢复或"
            "持续作战能力的实际贡献。winning_paths每项按‘现有基线—新机制—直接军事效果—权衡—"
            "对手反适应—失败边界—证据状态’压缩表达。只输出严格JSON。",
            {
                "operational_review": ["string"],
                "winning_paths": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s3_breakthrough",
            query_led_combat_rule
            + equipment_theme_rule
            + "S3 突破口思考子Agent：以query核心矛盾为主，结合而非照抄S1/S2，形成证据与因果"
            "能够支撑的竞争性任务级突破方向并构建效果链；不按数量或效果类别配额拆分，"
            "输入中的disruptive_seed_context若存在，也只是Query直接召回的可选反事实参考，不是事实、"
            "指标、目录或配额；先基于完整Query自行发散，再决定是否使用任一种子。不得为覆盖成本、平台、"
            "时间、效应、体系或博弈维度而补齐，不得机械罗列方法论。种子标题不能直接变成突破方向或"
            "装备名称；允许忽略全部种子并提出改变新体系关系的OTHER方向。"
            "必须进行反事实和替代假设检验。每项解释如何改变对抗机制并产生打击、反制、拒止、"
            "威慑或体系生存效果。只保留能够独立论证的方向，每项必须包含核心矛盾、适用条件、"
            "改变的关键前提、直接—间接—最终军事效果、对手反适应和可证伪失败条件；"
            "失败模式、证据或上游Packet依据，不得把推断写成直接证据。依据只允许使用逐字存在于"
            "valid_evidence_ids的证据ID或packet_index中的packet_id；分析框架、变量和优先序若无直接"
            "证据必须标为待验证假设，不得引用convergence、内部节点简称或未定义编号。只输出严格JSON。",
            {
                "breakthrough_directions": ["string"],
                "effect_chain": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s4_capability",
            query_led_combat_rule
            + equipment_theme_rule
            + "S4 装备能力映射子Agent：从query所要求的作战效果出发，把S3效果链转换为"
            "效果-功能-性能/约束-体系接口；仅保留能够直接改变目标发现、火力、突防、拦截、"
            "毁伤、拒止或威慑效果的能力映射，通信、接口、治理和保障只能作为支撑层，不能主导组合。"
            "只吸收与query直接因果相关、确有解释增益的发散镜头；不得为覆盖成本、平台、时间、效应、体系和"
            "可控性而机械增项。对种子触发的方向必须说明改变了哪项传统关系，"
            "同时给出现役做优接口与未来拓新装备族；不得把种子标题直接当作装备名称。"
            "每个方向增加capability_classification：主维度由该方向最主要的可验收战场结果决定，"
            "可使用毁伤维度、突防维度或Query驱动的其他自然维度；辅维度只在确有独立价值时保留，"
            "分类用于解释方向，不构成数量配额、固定目录或准入关键词。"
            "输出装备能力需求而非具体作战行动。每个方向必须区分装备措施与条令、组织、训练、"
            "领导教育、人员、设施、政策等非装备DOTMLPF措施，说明体系接口、适用边界、"
            "直接证据与推导判断，最多6项。每项显式给出gap_type、direct_evidence_refs、"
            "derived_from、validation_needed、priority、feasibility_basis、verification和"
            "uncertainty_boundary，并从军事价值、深度机制、前瞻触发条件和新颖性四个维度"
            "说明该方向为何值得进入装备论证。S4的priority/type/feasibility均为带量规的暂定判断，"
            "由S5进行证据审计和最终调整：可行性5=成熟现役底座且以增量集成为主，4=关键技术成熟但"
            "体系集成待验证，3=工程可行但关键接口或场景待验证，2=关键技术或成熟度不确定，1=概念级；"
            "priority综合军事价值、前置依赖、成熟度、证据强度和时效。禁止用后续S5/S6作为S4推导来源。"
            "若动态专用Agent或S3已经给出优先序，必须保持该顺序；确需调整时逐项说明权重和证据理由。"
            "feasibility_basis只能使用上述1至5级量表，不得另造L1/L2等未定义分级。新增具体装备型号"
            "有direct_evidence_refs时应优先引用；没有公开对象证据时仍可基于Query因果和装备构型保留具体方向，"
            "但必须把公开事实、类比推导和待验证假设分开，不得因字段缺失而失败。每个方向只保留一个主装备对象，近期接口/"
            "软件升级与中期新平台或中继建设必须在边界中拆开。"
            "为降低结构化冗余，capability_mapping每项不超过180字；dotmlpf_matrix各列表最多2项；"
            "concept_directions中的function、feasibility_basis、verification、uncertainty_boundary及"
            "military_value/depth_mechanism/foresight/novelty等辅助字段各控制在80至160字，字段之间不得"
            "复述同一事实，深度留给因果机制和可证伪边界。S3每条effect_chain必须在capability_mapping"
            "或dotmlpf_matrix中显式承接；derived_from中的effect_chain索引统一使用零基编号0至N-1，"
            "不得引用N或不存在的编号。"
            "只输出严格JSON。",
            {
                "capability_mapping": ["string"],
                "dotmlpf_matrix": [
                    {
                        "mission": "string",
                        "gap_type": "platform|interface|redundancy|governance|mixed",
                        "materiel": ["string"],
                        "non_materiel": ["string"],
                        "interfaces": ["string"],
                        "boundaries": ["string"],
                        "evidence_refs": ["exact evidence_id or packet_id"],
                        "derived_from": ["packet_id, dynamic input, or prior step"],
                        "validation_needed": ["string"],
                    }
                ],
                "concept_directions": [
                    {
                        "name": "string",
                        "priority": "P1..P8",
                        "type": "new_capability|upgrade",
                        "function": "string",
                        "feasibility": "1..5",
                        "feasibility_basis": "string",
                        "direct_evidence_refs": ["exact evidence_id"],
                        "derived_from": ["packet_id, dynamic input, or prior step"],
                        "verification": "string",
                        "uncertainty_boundary": "string",
                        "military_value": "string",
                        "depth_mechanism": "string",
                        "foresight": "string",
                        "novelty": "string",
                        "strike_countermeasure_value": "string",
                        "equipment_form": "string",
                        "operational_mechanism": "string",
                        "capability_classification": {
                            "primary_dimension": "Query驱动的主要能力维度，如毁伤维度、突防维度或其他自然维度",
                            "secondary_dimensions": ["最多两个确有独立价值的辅助能力维度"],
                            "classification_basis": "主要战场结果、关键流程节点与制胜关系为何支持该分类",
                        },
                    }
                ],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s5_gap",
            query_led_combat_rule
            + equipment_theme_rule
            + "S5 装备现状与差距子Agent：以query的实际作战后果为尺度，将目标能力与现有/在研"
            "装备、成熟度和体系约束对齐；对每项能力比较现役升级、中长期新研和非装备缓解三种路径，"
            "对颠覆性候选额外检查成本、工业补充、对手反制、降级可用和试验淘汰条件，"
            "按其恢复打击、拦截、反制、拒止、威慑或抗毁效果的增量排序，不得把接口、通信或治理"
            "不足本身当作最高等级差距。"
            "按五档差距给出依据并保留冲突数据。每项必须同时给出缺口本体、证据强度、"
            "gap_statement必须按‘现役基线—受压时削弱的军事效果—补齐后恢复的军事效果—仍存边界’表达；"
            "近期现役升级、中长期新研、验证指标和精确证据引用，并说明该缺口削弱何种打击、反制、"
            "抗毁或持续作战效果、补齐后恢复哪段任务链；成熟度不足不得误写为能力空白，"
            "存在关键战时边界时不得简单评为满足。只能评估S4 concept_directions明确映射的能力，"
            "不得新增独立能力项；‘公开资料未证明能力存在’最多标为low不确定性，不能直接判定关键差距，"
            "high证据强度必须来自直接测试失败、正式审计或明确现状证据，最多8项。只输出严格JSON。"
            "S5尚不能预知S6最终合并后的方向编号，因此reasoning_node.next_action和正文必须使用"
            "能力名称，不得使用P1、P2等最终优先级编号；最终连续编号由S6统一生成。"
            "同时形成s6_preflight前置质量合同：从当前query_combat_equipment_divergence_brief与S4候选中"
            "选择证据闭环能够支持的Query专属具体武器装备族，逐项检查其能否从任务语义、能力映射和对象证据建立因果关系；"
            "方向数量由独立性和证据决定，不设固定上下限。"
            "S5必须把每个ready候选的candidate_equipment写成最终冻结的完整装备名称：该名称继承S3/S4"
            "创新生成结果并完成必要语义收敛，须体现Query专属主装备、颠覆制胜机理或差异化作战作用；"
            "进入S6后名称、主装备身份和候选成员关系均不可修改。若名称仍空泛、重复、串卡或无法对应"
            "单一装备对象，必须在S5内合并、判退或修正，禁止把命名工作留给S6。"
            "无人、低空、远程精打和精确打击仅是可选重点镜头，不是固定装备桶或覆盖配额。每类写明与query契合的"
            "任务对象、作战阶段、现役/类比基线、独立差距和候选装备对象；若证据不足必须显式标记"
            "ready=false和原因，不得用弹药补给、导弹保障、运输、维修等支援装备冒充武器方向。"
            "每个ready装备桶还必须先形成整卡语义蓝图：明确唯一主装备对象、实际执行作战流程的主体、"
            "发射/释放/部署域、目标对象与直接战果，并给出由真实交战因果链决定长度、平台一致的operational_flow_contract。"
            "不得用标题或基线中的关键词套预设流程族；必须从Query、项目功能和完整装备形态理解主语。"
            "若主装备是母平台、发射舱、发射车或载机，所携弹药不得在流程中无说明地取代主平台；"
            "若发射域未被方案限定，必须保持平台中性，公开基线不能擅自把方案改为空射、陆射或海射。"
            "cross_family_confusion_risks要提前指出最容易导致主体、发射域、目标或毁伤方式串卡的语义风险。"
            "同时闭合capability_classification；以该装备在当前场景中的主要战果确定主维度，辅维度只保留"
            "真正改变需求或设计判断的项。分类可以是毁伤、突防或其他Query驱动维度，不得按示例凑类。"
            "技术可实现性不能只报成熟度等级，必须指出可复用底座、决定性工程瓶颈、装备本体实现链、"
            "关键集成约束和可判退的验证路径。"
            "该前置合同只提供组合质量约束，不替代S6独立综合。",
            {
                "gap_assessment": [
                    {
                        "capability": "string",
                        "grade": "空白|关键差距|部分差距|满足|超出",
                        "gap_statement": "string",
                        "evidence_strength": "high|medium|low",
                        "current_upgrade": "string",
                        "new_development": "string",
                        "verification": "string",
                        "evidence_refs": ["exact evidence_id or packet_id"],
                        "basis": "string",
                    }
                ],
                "s6_preflight": {
                    "equipment_buckets": [
                        {
                            "category": "Codex依据Query语义形成的具体武器装备族标识",
                            "ready": "boolean",
                            "query_relevance": "与当前query契合的任务对象、作战阶段和直接作战效果",
                            "baseline_system": "该类方向的现役或类比装备基线",
                            "capability_gap": "该类方向独立且具体的能力差距",
                            "candidate_equipment": "与Query目标、阶段和直接战果对应的具体打击杀伤武器对象",
                            "primary_equipment_identity": "唯一主装备对象及其平台/弹体/载荷边界",
                            "process_actor": "实际执行部署、进入、搜索/告警、交战和再组织的主体",
                            "launch_or_release_domain": "明确空/陆/海/水下或平台中性，以及发射/释放方式",
                            "target_and_direct_effect": "主要目标对象与可直接验收的打击、毁伤、压制或拦截战果",
                            "operational_flow_contract": [
                                "Codex按完整语义形成、步骤数由真实交战因果链决定的装备专属作战流程"
                            ],
                            "cross_family_confusion_risks": [
                                "可能被基线、载荷或相邻卡片误导的主体/发射域/目标/毁伤语义"
                            ],
                            "capability_classification": {
                                "primary_dimension": "主要能力维度",
                                "secondary_dimensions": ["辅助能力维度"],
                                "classification_basis": "按主要战果和制胜关系说明归类依据",
                            },
                            "evidence_refs": ["exact evidence_id or packet_id"],
                            "blocking_reason": "ready=false时说明缺少的证据或因果条件",
                        }
                    ],
                    "title_risks": ["重复词、抽象技术名、支援装备冒充武器等风险"],
                },
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
        (
            "winning_s6_image",
            equipment_theme_rule
            + "你是独立的装备能力画像综合Agent。分析主导顺序固定为：S6装备论证角色与方法、Query主题、"
            "打击/歼灭/压制/反制/拒止/威慑等强军事运用价值。S3与S4并行发散、命名Query相关的新质颠覆"
            "武器候选，S5负责语义准入、合并、证据审查、判退和冻结最终候选。S6不得独立发散、"
            "新增、删除、合并、替换或重命名装备方向；capability_synthesis_handoff中的候选成员、名称和"
            "主装备身份是不可变输入。S6只围绕每张冻结候选撰写自然、深入的能力画像。不得复述或拼接"
            "上游措辞和执行过程，但必须保持上游冻结的装备事实与身份。每一项画像都必须"
            "直接改变目标发现、火力分配、突防、拦截、压制、毁伤、再打击、区域拒止或威慑效果。"
            "所有入选项必须是可独立立项、研制、改装并试验考核的具体装备系统，不得用能力口号、技术标签、"
            "战法名称或支撑清单占位。内部仅比较与query直接因果相关且能够改变结论的成本、平台、时间、效应、体系或"
            "自主可控镜头，不展示六维方法论清单；每个最终方向都必须说明其相对公开基线改变了何种传统对抗关系，"
            "disruptive_seed_context只用于防止陷入渐进补齐，不得作为证据，也不得强制生成与query无关的概念。"
            "最终组合必须直接映射到武器装备发展，并以直接承担侦察打击、突防、歼灭、压制、拦截、"
            "毁伤或区域拒止的武器/无人作战装备为主体；"
            "主体方向必须与Query任务对象和制胜矛盾直接匹配，由Codex CLI从完整军事语义开放推演，"
            "不得使用预置装备类别、技术关键词、命名示例或固定创新维度反向拼接候选。"
            "每个方向要自然论证其解决的传统能力痛点与缺口、带来的能力提升，是否形成新的作战运用或"
            "制胜战法，以及是否依靠新的技术或原理改变传统能力实现样式；没有成立的颠覆性价值时如实降级，"
            "不得用新颖词汇包装。query_relevance只需自然说明任务对象、阶段、威胁压力和直接战果。"
            "direction.name必须逐字复制S5冻结名称，不得清理标点、去编号、压缩、扩写、同义替换或"
            "依据公开型号重新命名。若冻结名称空泛、重复、串卡或不对应单一装备，必须终止S6并退回"
            "S3–S5处理，不能在画像阶段修复名称。现役改进关系和公开型号只写入baseline_system及画像论证。"
            "通信、链路、网关、治理、审计、恢复与保障只能作为武器、传感器、火控、电子战或效应平台"
            "内部的支撑性改进措施，不得单列为最终能力方向。伪装、假目标、工程构设、效果评估和后勤保障"
            "原则上也只能作为横向支撑层；仅当query明确以该任务为主题、且能够形成直接战斗效应时才可竞争成为具体装备方向。"
            "禁止把自治、网关、算法、中间件、审计等通用技术或‘保底通信’单独包装成最终方向。"
            "每项必须回答：面向何种对象、场景与作战阶段；切断、恢复或强化哪段任务链；应形成何种"
            "平台、武器、任务系统、载荷或保障能力；其机理如何提升侦察预警、指挥决策、火力协同、"
            "打击、歼灭、拦截、反制、拒止、威慑、抗毁恢复或持续作战；相对现役基线新增什么机制。"
            "流程族识别必须由你基于整张装备卡的语义完成，禁止按标题、载荷或公开型号关键词套模板。"
            "在同一次调用内部，先为每卡锁定primary_equipment_identity，再生成function、equipment_form、"
            "operational_concept、operational_process和capability_portrait；提交前重新通读整卡，核对这些字段"
            "是否始终由同一个主装备对象执行、是否保持同一发射/释放域、是否面向同一目标并产生同一类直接战果。"
            "特别检查三类通用关系错误：母平台/发射装置被所携弹药替换为流程主语；防御拦截装备串入目标区"
            "察打补射；平台中性方案被公开基线擅自限定为空射、陆射或海射。以上是关系检查，不是装备关键词清单。"
            "只有semantic_consistency_check.consistent=true的卡片才允许提交；若不一致，必须在本次成稿内重写"
            "冲突字段后再提交唯一最终JSON，不得把问题留给后置质量门或卡片修复。"
            'consistent必须输出为JSON布尔值true，不得输出字符串"true"。逐卡复核完成后还必须进行一次'
            "组合级复核：比较全部卡片的主装备、发射域、目标、作用机理和验证指标；发现实质重复或"
            "身份冲突时只报告前置候选问题并停止交付，不得在S6合并、替换或改标题。"
            "能力画像必须保持‘概述+装备与技术实现+关键作战流程+形成能力与作战效果+"
            "制胜逻辑机理’五段格式。"
            + CAPABILITY_CLASSIFICATION_GUIDANCE
            + INNOVATIVE_CAPABILITY_IMAGE_GUIDANCE
            + OPERATIONAL_FEASIBILITY_GUIDANCE
            + CAPABILITY_PORTRAIT_CONCISION_GUIDANCE
            + CAPABILITY_OVERVIEW_GUIDANCE
            + FRONTLINE_LANGUAGE_GUIDANCE
            + "概述和四段正文均应精炼，"
            "只保留高价值的军事作战信息：敌我对抗、主装备、关键技术、交战动作、直接战果、公开基线及失效边界。"
            "每项内容都必须由该装备独有的语义产生，禁止保留占位符或套用通用句。场景必须落到真实战役/战斗阶段与"
            "作战地域；Query只是主题与约束来源，禁止把‘深度研究、理解、现代战争、全链条、全流程、制胜机理’"
            "等原始Query措辞机械粘贴到‘面向’。应先依据Query的任务对象和制胜矛盾推演具体战场，再写入"
            "敌我对抗态势、时间窗口和交战压力。"
            "概述只保留理解核心制胜判断不可缺少的敌我对象或任务窗口，不要求逐项覆盖主体、地域、"
            "反制、授权、流程和指标；这些内容分别留在结构化字段与下方专属栏目。关键作战流程应依据该武器自身的"
            "部署或值班方式、发射/释放域、感知与授权来源、效应方式、战果判定和再组织逻辑形成装备专属"
            "短动作链；不得把‘部署—进入—搜索复核—交战/拒打—评估—补射接替’或其他共享阶段骨架"
            "机械复制到所有卡片。流程可因装备不同体现拦截值班、伏击布设、伴随突防、定向能作用、"
            "水下潜伏、轨道机动、火力齐射或其他由Query和装备机理自然推导的战斗行动。直接结果应体现压制、摧毁、拦截、开辟走廊、续接后续火力或"
            "阻断敌方重组等直接战场结果。面向或针对节点禁止从‘装备研究中的’‘研究任务阶段’‘针对公开"
            "资料/公开基线不能证明’等研究管理、证据管理措辞起笔；公开证据边界、失效条件、发展与验证信息仅保留在独立结构化字段；"
            "最后单独点明制胜逻辑机理。不得只写装备组成、功能清单或抽象愿景。"
            "baseline_system和equipment_form应优先使用输入证据明确支持的公开型号、装备族谱或现役"
            "任务系统作为锚点，并说明该锚点承担的打击、猎歼、毁伤、拦截或压制作用；若证据只支持"
            "装备类别，必须明确写‘公开证据不足，保留类别级’，严禁凭常识虚构型号。"
            "现役升级必须写明被升级对象、真正改变能力生成方式的软硬件改装路径、作战效能增益、"
            "打击链贡献及转入新研的边界；不得为满足数量而罗列组件。"
            "每项同时给出3至10年触发条件、对手反适应、失效边界和可证伪指标；无校准数据不得虚构精确增益。"
            "capability_portrait按‘精炼概述+四个互斥分点’撰写，是区别于完整研究报告的决策短卡。"
            "必须在本次调用内直接取舍成稿，不得先写报告段落再压缩；概述只给关键断点、装备改变和直接结果，"
            "不得预演下方技术、流程或制胜逻辑，也不得出现省略号。"
            "下方四个分点分别展开装备与技术实现、关键作战流程、形成能力与作战效果、制胜逻辑机理，"
            + TECHNOLOGY_IMPLEMENTATION_GUIDANCE
            + "各栏没有最低字数、固定句数或统一句式，写到本栏独有结论完整即停止。"
            "优先删除重复背景、同义解释、公开资料复述、"
            "通用技术清单和不改变军事判断的修饰语；"
            "内容只能来自本卡主装备、关键技术、部署编组、交战动作、授权/效应闭环、"
            "直接军事结果、对手反适应和失效条件。四栏必须各自承担不同信息职责，不得用同一背景或流程反复填充。"
            "不得为满足字数重复场景、同义改写或堆砌通用术语，每句话至少承载一个可用于军事判断的信息。"
            "公开基线、文献罗列、验证程序和发展计划不进入画像正文，统一留在追溯字段。"
            "发展和验证信息只保留在development_path与verification字段，不进入装备能力画像正文。"
            "避免重复同一背景、效果或流程；宁可删去低价值枝节，也不堆砌公开资料、技术名词或泛化判断。其余字段"
            "每项40至100字，只保留一个独立决策信息，禁止重复背景或复述画像。direct_evidence_refs"
            "最多3项、derived_from最多2项、upgrade_package保留2至4项，assumptions和open_questions"
            "各最多3项。branch_products每类最多3条短句。"
            "用户可见内容不得出现Agent、Codex、S1-S6、L1-L4、Harness、Packet、Claim或内部编号。"
            "direct_evidence_refs只能选valid_evidence_ids；证据支撑事实，能力需求属于明确标注的综合推断。"
            "upstream_coverage只说明少量上游能力名称如何被吸收，不得复制上游正文。"
            "branch_products按当前branch_deliverables的字段格式交付；内容数量由Query、证据和独立性决定，"
            "不得为凑满历史示例中的战法、组合、指标、规律、场景或装备数量而拆分或补写。只输出严格JSON。",
            {
                "concept_directions": [
                    {
                        "name": "S3/S5冻结的自然整装名称：清楚识别唯一主装备，只承载一条最值得记住的创新主线；复杂任务、机理与战果写入下方说明，不把字段短语拼成标题",
                        "priority": "P1..P8",
                        "type": "new_capability|upgrade",
                        "function": "string",
                        "feasibility": "1..5",
                        "horizon": "near|mid|long",
                        "direct_evidence_refs": ["exact evidence_id"],
                        "foresight_evidence_status": "direct_object_baseline|analogous_project_evidence|component_mechanism_evidence",
                        "evidence_boundary": "公开证据支持与不支持的内容；未来增量属于何种待验证假设",
                        "derived_from": ["packet_id or prior step"],
                        "military_value": "string",
                        "depth_mechanism": "string",
                        "foresight": "string",
                        "novelty": "string",
                        "strike_countermeasure_value": "string",
                        "equipment_form": "具体武器装备形态；优先无人作战平台、导弹/弹药/拦截器、火控与效应器，写清载荷和作战对象",
                        "primary_equipment_identity": "唯一主装备对象，明确平台/弹体/载荷边界以及是否平台中性",
                        "operational_mechanism": "该装备能力如何作用于任务链并改变对抗效果",
                        "capability_classification": {
                            "primary_dimension": "主要能力维度，如毁伤维度、突防维度或Query驱动的其他自然维度",
                            "secondary_dimensions": ["最多两个确有独立价值的辅助维度"],
                            "classification_basis": "用通俗军语说明主要战果、关键流程节点和制胜关系为何支持该分类",
                        },
                        "equipment_semantic_assessment": {
                            "classification": "direct_combat|unmanned_combat|upgrade|system_link|support_only|non_equipment",
                            "direct_combat_effect": "boolean",
                            "support_only": "boolean",
                            "unmanned_combat": "boolean",
                            "precision_munition": "boolean",
                            "concrete_equipment": "boolean",
                            "query_alignment_confirmed": "boolean",
                            "rationale": "S5模型基于完整候选语义形成的判断理由",
                        },
                        "target_scenario": "面向的具体对象、环境、作战阶段和约束场景",
                        "problem_statement": "当前要解决的问题、难点、需求或任务链断点",
                        "scientific_principle": "支撑方案成立的作战、控制、信息、效应或体系原理",
                        "enabling_technologies": ["形成能力所采用的具体软硬件技术"],
                        "operational_concept": "装备如何编组、部署、协同、交战、评估和再组织的作战概念",
                        "operational_process": ["按时间顺序给出的关键作战流程步骤"],
                        "semantic_consistency_check": {
                            "process_actor": "流程各阶段实际行动主体",
                            "launch_or_release_mode": "发射、释放、部署域及其是否由方案明确限定",
                            "target_and_direct_effect": "主要目标对象与直接战果",
                            "checked_fields": [
                                "name|primary_equipment_identity|function|equipment_form|operational_concept|operational_process|capability_portrait|failure_boundary"
                            ],
                            "consistent": True,
                            "resolution_note": "发现冲突时在本次成稿内如何重写；无冲突时说明为何一致",
                        },
                        "capability_outcome": "最终形成的可考核装备能力",
                        "winning_mechanism": "为何能改变时间、精度、成本、平台、毁伤或体系关系并制胜",
                        "development_path": "近期现役武器改装—中期无人/导弹/弹药样机或型号研制—体系集成与实弹/对抗验证闸门",
                        "future_trigger": "3至10年内使该方向变得必要或可行的威胁/技术/体系触发条件",
                        "adversary_adaptation": "对手可能采取的反适应及本方向的再对抗要求",
                        "failure_boundary": "在哪些环境、体系依赖或工程条件下失效或不再优先",
                        "validation_plan": [
                            "前瞻方向的可证伪验证、判退或淘汰条件；暂缺可显式标为后续补全"
                        ],
                        "query_relevance": "必填：该装备方向为何与当前query的任务对象、作战阶段、威胁压力和直接作战效果契合",
                        "baseline_system": "所有方向必填：优先写证据支持的公开型号/装备族谱及当前能力基线；证据不足时明确保留类别级，不得虚构型号",
                        "capability_gap": "所有方向必填：该装备对象在当前query下独立、具体且不可复用的能力差距",
                        "upgrade_package": [
                            "upgrade必填：服务直接作战效果的具体传感、火控、制导、电子战、任务软件或载荷改进措施"
                        ],
                        "combat_effect_uplift": "upgrade必填：升级后对实际作战、打击/反制和持续任务能力的提升",
                        "strike_chain_contribution": "upgrade必填：对侦察—决策—火力—打击—评估—再组织链路的贡献",
                        "upgrade_boundary": "upgrade必填：现役改装可达边界及必须转入新研的条件",
                        "capability_portrait": "由五个独立模块确定性组装的装备战斗画像；突出真实交战流程、直接战果和创新制胜机理，不写失效、发展与验证信息",
                        "capability_portrait_modules": {
                            "overview": "只保留一个传统能力瓶颈、一个创新断点和一个直接战果",
                            "technology_implementation": "只保留一条技术痛点—突破原理—工程实现—能力跃迁的决定性突破链",
                            "operational_process": "只保留使任务状态发生变化的装备专属战斗动作链",
                            "capability_effects": "只保留相对基线新增能力和可验证战场结果",
                            "winning_logic": "只保留主要战争交换关系、新制胜机制和对手新增成本",
                        },
                        "indicator_portrait": "由本装备任务机理直接推导的差异化指标画像；写明覆盖/射程、响应、毁伤或压制、授权自主边界、生存/成本/规模中真正决定胜负的测量轴、对照基线和判退条件，不套固定指标清单",
                        "confidence": "0..1；按该对象证据强度和推导跨度单独给出；前瞻新质方向允许0.45..0.65，低置信度表示推导跨度而非失败",
                    }
                ],
                "capability_image_drafts": ["每项入选具体武器装备能力画像的单句结论"],
                "upstream_coverage": [
                    {
                        "upstream_item": "精简交接中的能力差距或作战效果名称",
                        "disposition": "standalone|merged|horizontal_layer",
                        "target_directions": ["最终能力方向名称"],
                        "rationale": "为何单列、合并或作为横向层",
                    }
                ],
                "branch_products": branch_product_schema,
                "evidence_validation": {
                    "all_ids_valid": "boolean",
                    "invalid_ids": ["string"],
                    "mismatched_claims": ["string"],
                },
                "assumptions": ["string"],
                "open_questions": ["string"],
                "confidence": "0..1",
            },
        ),
    ]
    if primary_branch == "A":
        agent_id, system, schema = steps[1]
        steps[1] = (
            agent_id,
            system + " A分支必须在现有战法基线之上形成必要数量、机制真正不同的新战法；"
            "差异必须落在决策权分配、任务组织、效应递进或对抗机理，而不是同义改名。",
            {
                **schema,
                "existing_tactic_baseline": ["string"],
                "tactic_concepts": [
                    {
                        "tactic_id": "稳定且唯一的战法ID",
                        "name": "string",
                        "mechanism": "string",
                        "difference_from_baseline": "string",
                        "applicable_scenarios": ["scenario_id"],
                        "failure_conditions": ["string"],
                        "evidence_refs": ["exact evidence_id or packet_id"],
                    }
                ],
            },
        )
        agent_id, system, schema = steps[2]
        steps[2] = (
            agent_id,
            system
            + " A分支必须消费已形成的tactic_validation_results，对与Query相关的代表性场景执行任务链、"
            "强电磁、弱网、节点损耗和对手适应压力测试。无校准数据时只给定性等级、"
            "比较排序、适用条件和置信度，禁止给出虚构的精确提升百分比。",
            {
                **schema,
                "pressure_test_matrix": [
                    {
                        "tactic_id": "已形成的稳定战法ID",
                        "scenario_id": "string",
                        "mission_chain": "high|medium|low",
                        "strong_electromagnetic": "high|medium|low",
                        "degraded_network": "high|medium|low",
                        "attrition_resilience": "high|medium|low",
                        "opponent_adaptation": "high|medium|low",
                        "conditions": ["string"],
                        "confidence": "0..1",
                    }
                ],
                "tactic_effect_ranking": ["按任务适配与证据排序的战法ID"],
            },
        )

    def cohort_role_contract(index: int) -> dict[str, Any]:
        base = {
            1: {
                "objective": "解构对手感知、决策、火力、保障与恢复体系，识别依赖、替代链和任务级薄弱环节。",
                "must_consume": ["背景与场景约束", "对手/装备公开证据"],
                "military_test": "说明可被削弱、延迟、欺骗、拒止或制衡的环节及失效边界。",
            },
            2: {
                "objective": "审查现有任务链、战法、协同与保障基线，形成机制不同且可比较的制胜运用路径。",
                "must_consume": ["场景任务链", "S1对手体系认识"],
                "military_test": "比较打击/歼灭闭环、反制效率、拒止强度、抗毁恢复和持续作战效果。",
            },
            3: {
                "objective": "围绕核心矛盾执行反事实与压力测试，形成突破方向和直接—间接—最终效果链。",
                "must_consume": ["S1/S2结论或分支专用Packet", "反证与适用条件"],
                "military_test": "验证强电磁、弱网、节点损耗和对手适应下的任务效果与失败模式。",
            },
            4: {
                "objective": "把效果链映射为任务—能力—功能—性能约束—体系接口，并区分装备与非装备措施。",
                "must_consume": ["S3效果链", "相关业务Packet与直接证据"],
                "military_test": "每项能力必须解释对打击、反制、拒止、抗毁或持续作战链路的可验证贡献。",
            },
            5: {
                "objective": "对齐目标能力与现役/在研装备、成熟度和体系约束，完成五档差距及升级/新研边界。",
                "must_consume": ["S4能力映射", "装备现状与成熟度证据"],
                "military_test": "说明缺口切断何种任务效果，补齐后恢复哪段打击、反制、抗毁或保障链。",
            },
            6: {
                "objective": "融合前五步形成少而精的能力画像、优先级、装备形态、演化路径和验证闸门。",
                "must_consume": ["S4能力映射", "S5差距评估", "分支规定产物"],
                "military_test": "只保留具备显著军事价值、前瞻机制和可证伪建设路径的方向。",
            },
        }[index]
        branch_focus = {
            "A": {
                2: "形成由证据支持、机制真正不同的新战法；不是同义改名，数量不设配额。",
                3: "消费已形成的战法，对有区分度的代表性场景执行任务链与对抗压力测试。",
                4: "围绕Query相关能力域、指标和装备形态建立可追溯映射基础，不按目录补齐。",
                5: "轻量盘点现役底座与关键差距，不重复完整装备研究。",
            },
            "B": {
                1: "围绕西太/反介入等给定体系识别对手关键节点和反适应方式。",
                2: "审查我方现有运用与保障基线，不另造脱离场景的新战法。",
                3: "形成能够牵引S4/S5的突破方向，不提前跳到装备型号。",
                4: "重点完成能力映射、需求卡片字段和体系接口。",
                5: "重点完成五档差距、现役升级、新研边界和验证依据。",
            },
            "C": {
                3: "完整消费案例Packet，形成3类未来场景迁移及不可迁移边界。",
                4: "把6条案例规律映射为能力需求，并支撑4类新兴装备类别。",
                5: "对迁移后的能力需求执行现役基础、差距与工程边界审查。",
            },
            "D": {3: "以技术改变任务机制为主线，区分成熟度与能力潜力。"},
            "E": {3: "把对手能力形成信号转换为可削弱、延迟、拒止或制衡的窗口。"},
            "F": {
                3: "构造级联失效、替代链和降级运行场景。",
                4: "形成补链强链能力映射。",
                5: "审查替代链的现役基础和关键差距。",
            },
            "G": {
                3: "聚焦数据、权限、时序和接口缝隙。",
                4: "映射跨域闭环与最低可用能力。",
            },
            "H": {
                3: "兼顾威胁扩散、任务保护和可控反制。",
                4: "保留法律伦理与军地协同边界。",
            },
        }.get(primary_branch, {}).get(
            index, "按当前分支合同完成本步骤，不扩展无关分析。"
        )
        return {
            **base,
            "branch_focus": branch_focus,
            "military_divergence_contract": _winning_military_divergence_contract(
                index
            ),
            "quality_gate": "事实/推断/假设分离；结论绑定证据或上游引用；保留反证、置信度和失效边界。",
        }

    step_modes = _winning_step_modes(shared)
    if shared["execution_profile_id"] == "winning_swarm_dynamic_v2":
        # The Mission Graph stops at the governed equipment portfolio;
        # its S6 node is intentionally supplied by the parallel portrait
        # author below.  An adaptive blueprint may skip analytical S6 in
        # other profiles, but dynamic v2 must still author the deliverable
        # cards before the final gate can judge them.
        step_modes[6] = "deep"
    active_steps = [
        index for index in range(1, len(steps) + 1) if step_modes[index] != "skip"
    ]
    requested_resume_steps: list[int] = []
    for item in shared.get("resume_steps", []):
        try:
            step = int(item)
        except (TypeError, ValueError):
            continue
        if step in active_steps and step not in requested_resume_steps:
            requested_resume_steps.append(step)
    if requested_resume_steps:
        active_steps = requested_resume_steps

    fast_profile = (
        os.environ.get(
            "EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE",
            "quality",
        )
        .strip()
        .lower()
        == "fast"
    )
    model_loop_critics = os.environ.get(
        "EQUIPMENT_DR_ENABLE_MODEL_LOOP_CRITICS",
        "0",
    ).strip().lower() in {"1", "true", "yes"}
    shared["winning_step_plan"] = [
        {
            "step": index,
            "agent_id": steps[index - 1][0],
            "execution_mode": step_modes[index],
        }
        for index in range(1, len(steps) + 1)
    ]
    prior_winning_analysis = shared.get("prior_winning_analysis", {})
    accumulated: dict[str, Any] = (
        {
            key: value
            for key, value in prior_winning_analysis.items()
            if key
            not in {
                "assumptions",
                "open_questions",
                "subagent_runs",
                "dynamic_subagent_runs",
                "loop_trace",
                "codex_call_metrics",
                "middle_loop_limited",
                "evidence_supplement_pending",
                "targeted_evidence_requests",
            }
        }
        if isinstance(prior_winning_analysis, Mapping)
        else {}
    )
    all_assumptions: list[str] = []
    all_open_questions: list[str] = []
    runs: list[dict[str, Any]] = []
    loop_trace: list[dict[str, Any]] = []
    dynamic_outputs: list[dict[str, Any]] = []
    reasoning_nodes: dict[str, dict[str, Any]] = {}
    s6_model_repair_used = False
    s6_parallel_authoring_only = bool(
        (
            shared.get("execution_profile_id") == "winning_swarm_dynamic_v2"
            or optimized_v2
        )
        and host.provider_kind == "codex_cli"
        and getattr(host.provider, "provider_type", "") == "codex_cli"
    )
    dynamic_s6_authoring = shared.get("execution_profile_id") == "winning_swarm_dynamic_v2"

    blueprint = shared.get("discovery_blueprint", {})
    swarm_policy = (
        blueprint.get("winning_swarm_policy", {})
        if isinstance(blueprint, Mapping)
        and isinstance(blueprint.get("winning_swarm_policy", {}), Mapping)
        else {}
    )
    if shared["execution_profile_id"] == "winning_swarm_dynamic_v2":
        swarm_policy = {
            "policy_id": "winning_swarm_dynamic_v2",
            "enabled": True,
            **dict(swarm_policy),
        }
    swarm_controller = WinningSwarmController(swarm_policy)
    dynamic_swarm_enabled = (
        shared["execution_profile_id"] == "winning_swarm_dynamic_v2"
        and swarm_controller.enabled
        and not requested_resume_steps
    )
    swarm_enabled = (
        shared["execution_profile_id"] == "swarm_quality_v1"
        and swarm_controller.enabled
        and not requested_resume_steps
    )
    dynamic_specs = (
        list(blueprint.get("dynamic_subagents", []))
        if isinstance(blueprint, Mapping)
        and isinstance(blueprint.get("dynamic_subagents", []), list)
        else []
    )[: (12 if (swarm_enabled or dynamic_swarm_enabled) else 3)]

    async def run_dynamic_specialist(spec: Mapping[str, Any]) -> dict[str, Any]:
        instance_id = str(spec.get("agent_instance_id", "dynamic-specialist"))
        hypothesis_id = str(spec.get("hypothesis_id", "")).strip() or (
            "hypothesis-dynamic-"
            + sha256(
                f"{instance_id}:{spec.get('merge_target', 'S3')}".encode("utf-8")
            ).hexdigest()[:12]
        )
        dynamic_steps = [
            int(item)
            for item in spec.get("contribution_to_steps", [])
            if str(item).isdigit() and 1 <= int(item) <= 5
        ]
        dynamic_claims = (
            military_claims_for_steps(dynamic_steps or [3, 4, 5])
            if optimized_v2
            else []
        )
        dynamic_evidence = (
            evidence_for_claims(dynamic_claims, limit=10)
            if optimized_v2
            else list(shared.get("evidence_index", []))
        )
        result = _parse_json_object(
            await host._run_core_json(
                "winning_dynamic_specialist",
                "你是由制胜主控按需生成的辅助专用Agent。严格执行dynamic_agent_spec，"
                "只处理其中定义的可分离专业缺口，不得扩大权限、改写其他Agent结论或绕过证据门控。"
                "输出必须说明如何合并到指定S节点及其对军事任务判断的增量；证据引用只能来自"
                "valid_evidence_ids或packet_id。",
                {
                    "topic": shared["topic"],
                    "research_route": shared["research_route"],
                    "analysis_priority": analysis_priority_contract,
                    "discovery_blueprint": _compact_prompt_value(
                        shared.get("discovery_blueprint", {}),
                        max_string_chars=700,
                        max_list_items=8,
                    ),
                    "coverage": _compact_prompt_value(
                        {} if optimized_v2 else shared.get("coverage", {}),
                        max_string_chars=500,
                        max_list_items=10,
                    ),
                    "packet_index": _compact_prompt_value(
                        military_packet_refs_for_claims(dynamic_claims)
                        if optimized_v2
                        else packet_index,
                        max_string_chars=320,
                        max_list_items=8,
                    ),
                    "packets": _compact_prompt_value(
                        [] if optimized_v2 else shared.get("packets", []),
                        max_string_chars=360,
                        max_list_items=6,
                    ),
                    "secondary_cross_agent_constraints": _compact_prompt_value(
                        dynamic_claims,
                        max_string_chars=460,
                        max_list_items=6,
                    ),
                    "evidence_index": _compact_prompt_value(
                        dynamic_evidence,
                        max_string_chars=280,
                        max_list_items=20,
                    ),
                    "dynamic_agent_spec": dict(spec),
                    "valid_evidence_ids": [
                        str(item.get("evidence_id", ""))
                        for item in dynamic_evidence
                        if isinstance(item, Mapping)
                        and str(item.get("evidence_id", "")).strip()
                    ],
                },
                {
                    "findings": ["string"],
                    "evidence_refs": ["exact evidence_id or packet_id"],
                    "contribution_to_steps": [
                        {
                            "step": "1..6",
                            "contribution": "string",
                        }
                    ],
                    "assumptions": ["string"],
                    "open_questions": ["string"],
                    "merge_target": "S1|S2|S3|S4|S5|S6|convergence",
                    "stop_reason": "string",
                    "confidence": "0..1",
                },
                int(spec.get("max_output_tokens", 1800)),
                phase="winning_dynamic_specialist",
            )
        )
        if not result:
            raise ValueError(f"{instance_id} returned invalid structured JSON")
        reported_target = str(result.get("merge_target", ""))
        declared_target = str(spec.get("merge_target", "S3"))
        if reported_target and reported_target != declared_target:
            raise ValueError(
                f"{instance_id} crossed merge target {declared_target} -> {reported_target}"
            )
        result = sanitize_references(result)
        result["merge_target"] = declared_target
        return {
            "agent_instance_id": instance_id,
            "hypothesis_id": hypothesis_id,
            "display_name": str(spec.get("display_name", "动态专用Agent")),
            "merge_target": declared_target,
            "skill_ids": list(spec.get("skill_ids", [])),
            "knowledge_pack_ids": list(spec.get("knowledge_pack_ids", [])),
            "accepted": True,
            "result": result,
        }

    if (
        dynamic_specs
        and not (swarm_enabled or dynamic_swarm_enabled)
        and not requested_resume_steps
        and host._optional_work_allowed(
            priority="critical",
            minimum_remaining_seconds=240.0,
        )
    ):
        try:
            dynamic_outputs = list(
                await asyncio.gather(
                    *(run_dynamic_specialist(spec) for spec in dynamic_specs)
                )
            )
        except (RuntimeError, TimeoutError) as exc:
            if not _is_harness_budget_error(exc):
                raise
            accumulated["dynamic_specialists_budget_skipped"] = True
            dynamic_outputs = []
        accumulated["dynamic_subagent_outputs"] = dynamic_outputs
        for item in dynamic_outputs:
            result = item["result"]
            runs.append(
                {
                    "step": 0,
                    "agent_id": item["agent_instance_id"],
                    "template_agent_id": "winning_dynamic_specialist",
                    "middle_cycle": 0,
                    "execution_mode": "dynamic",
                    "merge_target": item["merge_target"],
                    "skill_ids": item["skill_ids"],
                    "knowledge_pack_ids": item["knowledge_pack_ids"],
                    "confidence": result.get("confidence"),
                    "open_question_count": len(result.get("open_questions", [])),
                    "status": "completed",
                }
            )
    elif (
        dynamic_specs
        and not (swarm_enabled or dynamic_swarm_enabled)
        and not requested_resume_steps
    ):
        accumulated["dynamic_specialists_budget_skipped"] = True
        loop_trace.append(
            {
                "loop": "dynamic",
                "event": "deadline_skip",
                "passed": True,
                "issues": [
                    "运行已进入截止收敛区间，跳过可选动态专用分析，保留主链证据。"
                ],
            }
        )

    swarm_plan = None
    swarm_tasks: list[SpecialistTask] = []
    swarm_hypotheses: dict[str, WinningHypothesis] = {}
    swarm_contributions: list[SpecialistContribution] = []
    swarm_gates: list[dict[str, Any]] = []
    swarm_merges: list[dict[str, str]] = []
    swarm_rejections: list[dict[str, Any]] = []
    swarm_completed_task_ids: set[str] = set()
    swarm_failed_task_ids: set[str] = set()
    core_swarm_schedule: dict[str, Any] = {}
    swarm_semaphore = asyncio.Semaphore(
        int(swarm_controller.policy.get("max_concurrency", 6))
    )

    def emit_swarm_event(
        event_type: str,
        *,
        actor: str = "winning_swarm_controller",
        **details: Any,
    ) -> None:
        host._emit_winning_progress(
            {
                "event_type": event_type,
                "agent_id": actor,
                **details,
            }
        )

    async def cluster_hypotheses_with_independent_codex(
        candidates: Sequence[WinningHypothesis],
        *,
        scope_id: str,
        changed_hypothesis_ids: set[str] | None = None,
    ) -> tuple[list[WinningHypothesis], list[dict[str, str]]]:
        """Use an isolated Codex session for five-axis semantic clustering."""

        exact_unique, exact_merges = swarm_controller.deduplicate_hypotheses(candidates)
        if len(exact_unique) < 2 or host.provider_kind != "codex_cli":
            return exact_unique, exact_merges
        instance_id = (
            "winning-semantic-clusterer-"
            + sha256(f"{shared.get('run_id', '')}:{scope_id}".encode()).hexdigest()[:16]
        )
        task = SpecialistTask(
            task_id=instance_id,
            agent_instance_id=instance_id,
            archetype="independent_portfolio_reviewer",
            display_name="候选五轴语义聚类",
            wave=0,
            purpose=(
                "独立成对比较候选的目标、任务链断点、改变变量、核心机理和直接战果，"
                "只识别同一制胜命题及其非独立变体，不生成或改写候选。"
            ),
            merge_target="S5",
            max_output_tokens=min(
                1800,
                700 + (len(exact_unique) * (len(exact_unique) - 1) // 2) * 160,
            ),
            allow_child_spawn=False,
        )
        candidate_rows = [
            {
                "hypothesis_id": item.hypothesis_id,
                "title": item.title,
                "target": item.project_function,
                "task_chain_breakpoint": item.problem_statement
                if hasattr(item, "problem_statement")
                else item.project_function,
                "winning_angle_id": item.winning_angle_id,
                "original_paradigm": item.original_paradigm,
                "disruptive_shift": item.disruptive_shift,
                "independence_thesis": item.independence_thesis,
                "changed_confrontation_variable": item.changed_confrontation_variable,
                "core_mechanism": list(item.mechanism_chain),
                "direct_military_results": list(item.direct_military_effects),
            }
            for item in exact_unique
        ]
        pair_ids = [
            [left.hypothesis_id, right.hypothesis_id]
            for index, left in enumerate(exact_unique)
            for right in exact_unique[index + 1 :]
            if not changed_hypothesis_ids
            or left.hypothesis_id in changed_hypothesis_ids
            or right.hypothesis_id in changed_hypothesis_ids
        ]
        if not pair_ids:
            return exact_unique, exact_merges
        output_schema = {
            "pairwise_comparisons": [
                {
                    "left_hypothesis_id": "exact id",
                    "right_hypothesis_id": "exact id",
                    "relationship": "same_thesis|non_independent_variant|independent",
                    "shared_target": "string",
                    "shared_task_chain_breakpoint": "string",
                    "shared_changed_variable": "string",
                    "shared_core_mechanism": "string",
                    "shared_direct_result": "string",
                    "axis_equivalence": {
                        "target": "boolean",
                        "task_chain_breakpoint": "boolean",
                        "changed_variable": "boolean",
                        "core_mechanism": "boolean",
                        "direct_result": "boolean",
                    },
                    "material_difference_axes": [
                        "target|task_chain_breakpoint|changed_variable|core_mechanism|direct_result"
                    ],
                    "independent_acceptance_basis": [
                        "material difference, empty for duplicates"
                    ],
                    "confidence": "0..1",
                }
            ],
            "stop_reason": "string",
        }
        emit_swarm_event(
            "winning_semantic_clustering_started",
            actor=instance_id,
            candidate_count=len(candidate_rows),
            pair_count=len(pair_ids),
            scope_id=scope_id,
        )
        try:
            text = await host._run_core_json(
                "winning_swarm_independent_portfolio_reviewer",
                "你是与候选生成会话完全隔离的军事装备语义聚类专家。逐对比较所有指定候选，只依据五个轴："
                "目标对象、任务链断点、改变的对抗变量、核心制胜机理、直接军事战果。名称、代号、平台小改、"
                "发射域改写、接口扩写和验证措辞不同，不足以构成独立命题。只有至少一个五轴要素发生会改变"
                "立项判断和独立验收的实质变化，才判为independent；同一装备家族本身不是重复，只要接敌链、"
                "授权时机、效应触发、迫使对手采取的反应、直接战果或判退试验中至少一项发生足以改变立项/验收"
                "结论的实质变化，就应保留为独立候选。尤其是改变变量或核心机理任一实质不同，"
                "必须判independent；共同指向同一种最终毁伤/瘫痪战果不能抵消这种差异。同一命题换说法判same_thesis；属于同一"
                "命题、不能独立验收的构型变体判non_independent_variant。不得使用字符重合率、关键词数量、"
                "装备类型配额或候选顺序判断。只有五轴全部实质等价、material_difference_axes为空时"
                "才允许same_thesis或non_independent_variant。必须覆盖input.pair_ids中的每一对，只输出JSON。",
                {
                    "run_id": shared.get("run_id", ""),
                    "agent_instance_id": instance_id,
                    "execution_profile_id": shared.get("execution_profile_id", ""),
                    "specialist_task": to_plain(task),
                    "query": shared.get("topic", ""),
                    "structured_query_brief": shared.get("structured_query_brief", {}),
                    "candidates": candidate_rows,
                    "pair_ids": pair_ids,
                },
                output_schema,
                task.max_output_tokens,
                phase="winning_semantic_pair_clustering",
            )
            result = _parse_json_object(text)
            comparisons = result.get("pairwise_comparisons", [])
            if not isinstance(comparisons, list):
                raise ValueError("semantic clusterer returned invalid comparisons")
            valid_pairs = {tuple(item) for item in pair_ids}
            duplicate_pairs: set[frozenset[str]] = set()
            for row in comparisons:
                if not isinstance(row, Mapping):
                    continue
                left = str(row.get("left_hypothesis_id", ""))
                right = str(row.get("right_hypothesis_id", ""))
                pair = (left, right)
                reverse_pair = (right, left)
                if pair not in valid_pairs and reverse_pair not in valid_pairs:
                    continue
                relationship = str(row.get("relationship", "")).lower()
                try:
                    confidence = float(row.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                axis_equivalence = row.get("axis_equivalence", {})
                all_axes_equivalent = bool(
                    isinstance(axis_equivalence, Mapping)
                    and all(
                        axis_equivalence.get(axis) is True
                        for axis in (
                            "target",
                            "task_chain_breakpoint",
                            "changed_variable",
                            "core_mechanism",
                            "direct_result",
                        )
                    )
                )
                raw_difference_axes = row.get("material_difference_axes", [])
                no_material_differences = isinstance(
                    raw_difference_axes, list
                ) and not any(str(item).strip() for item in raw_difference_axes)
                if (
                    relationship in {"same_thesis", "non_independent_variant"}
                    and confidence >= 0.70
                    and all_axes_equivalent
                    and no_material_differences
                ):
                    duplicate_pairs.add(frozenset((left, right)))
            # Complete-link grouping prevents transitive over-merging:
            # A≈B and B≈C never collapses A with C unless the independent
            # Codex also explicitly judged A≈C.
            groups: list[list[WinningHypothesis]] = []
            for item in sorted(
                exact_unique,
                key=lambda candidate: (
                    -candidate.score,
                    -len(candidate.evidence_ids),
                    candidate.hypothesis_id,
                ),
            ):
                compatible_group = next(
                    (
                        group
                        for group in groups
                        if all(
                            frozenset((item.hypothesis_id, member.hypothesis_id))
                            in duplicate_pairs
                            for member in group
                        )
                    ),
                    None,
                )
                if compatible_group is None:
                    groups.append([item])
                else:
                    compatible_group.append(item)
            kept: list[WinningHypothesis] = []
            merges = list(exact_merges)
            for group in groups:
                ordered = sorted(
                    group,
                    key=lambda item: (
                        -item.score,
                        -len(item.evidence_ids),
                        item.hypothesis_id,
                    ),
                )
                representative = ordered[0]
                kept.append(representative)
                for duplicate in ordered[1:]:
                    merges.append(
                        {
                            "source_hypothesis_id": duplicate.hypothesis_id,
                            "target_hypothesis_id": representative.hypothesis_id,
                            "reason": "independent_codex_five_axis_semantic_cluster",
                        }
                    )
            emit_swarm_event(
                "winning_semantic_clustering_completed",
                actor=instance_id,
                candidate_count=len(exact_unique),
                retained_count=len(kept),
                merged_count=len(merges),
                scope_id=scope_id,
            )
            return kept, merges
        except BaseException as exc:
            emit_swarm_event(
                "winning_semantic_clustering_failed",
                actor=instance_id,
                failure_type=type(exc).__name__,
                error_message=str(exc)[:500],
                fallback="exact_five_axis_identity_only",
                scope_id=scope_id,
            )
            return exact_unique, exact_merges

    async def call_swarm_specialist(
        task: SpecialistTask,
        hypothesis: WinningHypothesis | None = None,
        *,
        batch: int = 0,
    ) -> dict[str, Any]:
        if task.allow_child_spawn:
            raise ValueError("dynamic specialists may not recruit child agents")
        runtime_agent_id = f"winning_swarm_{task.archetype}"
        scoped_provider = host._provider_for(
            runtime_agent_id,
            isolation_id=task.agent_instance_id,
        )
        provider_snapshot = getattr(scoped_provider, "snapshot", lambda: {})()
        session_ref = _swarm_session_ref(task)
        runtime_contract = _swarm_runtime_audit_contract(
            task,
            provider_snapshot,
            runtime_agent_id=runtime_agent_id,
            session_ref=session_ref,
        )
        emit_swarm_event(
            "specialist_spawned",
            actor=task.agent_instance_id,
            **runtime_contract,
            batch=batch,
            status="recruiting",
        )
        async with swarm_semaphore:
            emit_swarm_event(
                "specialist_session_started",
                actor=task.agent_instance_id,
                **runtime_contract,
                batch=batch,
                status="running",
            )
            started_at = monotonic()
            common_input = {
                "run_id": shared.get("run_id", ""),
                "agent_instance_id": task.agent_instance_id,
                "mission_node": task.merge_target,
                "batch": batch,
                "topic": shared["topic"],
                "research_route": shared["research_route"],
                "execution_profile_id": shared["execution_profile_id"],
                "discovery_branch": primary_branch,
                "query_combat_equipment_divergence_brief": (
                    _open_s3_exploration_brief(
                        str(shared.get("topic", "")),
                        shared.get("structured_query_brief", {}),
                    )
                    if task.merge_target in {"S1", "S2", "S3"}
                    else _query_combat_equipment_divergence_brief(
                        str(shared.get("topic", "")),
                        structured_query_brief=shared.get(
                            "structured_query_brief", {}
                        ),
                    )
                ),
                "query_led_weapon_naming_style": {
                    "references": _query_led_combat_equipment_theme_contract()[
                        "naming_style_references"
                    ],
                    "rule": _query_led_combat_equipment_theme_contract()[
                        "naming_reference_rule"
                    ],
                    "format": (
                        "由当前装备语义动态选择自然描述名、专名或可解释代号；"
                        "不预设统一代号、缩写、后缀或句式"
                    ),
                },
                "specialist_task": to_plain(task),
                "role_contract": {
                    "mandate": task.purpose,
                    "decision_authority": (
                        "自主比较常规、非装备与前沿路线并创造候选"
                        if task.wave == 1
                        else "只对声明候选和残差作独立挑战或收敛判断"
                    ),
                    "handoff_contract": (
                        "只交接装备身份、制胜机理、直接战果、证据边界和可证伪条件"
                    ),
                    "prohibitions": [
                        "不得读取其他Agent原始会话",
                        "不得招募子Agent或改写其他候选",
                        "不得把内部评审流程写入候选",
                    ],
                },
                "hypothesis": to_plain(hypothesis) if hypothesis else {},
                "packet_index": _compact_prompt_value(
                    packet_index,
                    max_string_chars=360,
                    max_list_items=10,
                ),
                "evidence_index": _compact_prompt_value(
                    _prioritize_winning_evidence_index(
                        shared.get("evidence_index", []),
                        archetype=task.archetype,
                    ),
                    max_string_chars=300,
                    max_list_items=24,
                ),
                "valid_reference_ids": sorted(valid_reference_ids),
                "isolation_contract": {
                    "raw_other_agent_sessions_visible": False,
                    "may_recruit_child_agent": False,
                    "declared_hypothesis_id": task.hypothesis_id,
                    "declared_merge_target": task.merge_target,
                },
            }
            if task.wave == 1:
                schema: dict[str, Any] = {
                    "hypotheses": [
                        {
                            "title": "string",
                            "naming_rationale": "holistic editorial reason this is a natural and memorable name for the complete weapon; do not justify it word by word or map it to every field",
                            "decisive_advantage_thesis": "why this equipment can create a battle-winning advantage rather than merely improve a metric",
                            "cross_query_distinction": "what must change if the query's target, phase or threat changes; proves this is not a reusable template",
                            "nearest_public_baseline": "string",
                            "changed_confrontation_variable": "string",
                            "mechanism_chain": ["string"],
                            "direct_military_effects": ["string"],
                            "equipment_forms": ["specific equipment category/form"],
                            "project_function": "who uses this equipment under what constraints to do what and achieve what mission result",
                            "reference_overview": "显示在装备名下方的一句精简制胜说明；通常35-80个中文字符但不是硬门，聚焦独特战场条件、颠覆关系与直接战果，不复述标题、不套固定句式",
                            "system_interfaces": [
                                "concrete platform, payload, C2, fire-control or support interface"
                            ],
                            "novelty_delta": "substantive difference from baseline",
                            "frontier_principle": "concrete enabling principle embodied by this weapon",
                            "technology_discontinuity": "why conventional upgrade or process change cannot absorb the decisive increment",
                            "technology_horizon": "bounded research horizon without unsupported readiness claims",
                            "engineering_bottleneck": "primary falsifiable physics, integration, cost, safety or test question",
                            "evidence_ids": ["exact evidence_id or packet_id"],
                            "evidence_boundary": "what evidence does and does not prove",
                            "counterevidence": ["string"],
                            "adversary_adaptations": ["string"],
                            "failure_boundaries": ["string"],
                            "trl_constraints": ["string"],
                            "cost_constraints": ["string"],
                            "industrial_constraints": ["string"],
                            "cross_scenario_results": ["string"],
                            "validation_plan": ["falsifiable test"],
                            "implementation_path": "new|upgrade|system_link|non_materiel",
                        }
                    ],
                    "stop_reason": "string",
                }
                phase = "winning_swarm_breadth"
                wave_instruction = _quality_cluster_candidate_instruction()
            else:
                schema = {
                    "hypothesis_id": "exact declared hypothesis_id",
                    "merge_target": "exact declared merge_target",
                    "findings": ["incremental finding"],
                    "mechanism_chain_updates": ["string"],
                    "direct_military_effects": ["string"],
                    "equipment_forms": ["specific equipment category/form"],
                    "project_function": "complete or repaired project function",
                    "system_interfaces": [
                        "concrete platform, payload, C2, fire-control or support interface"
                    ],
                    "novelty_delta": "string",
                    "naming_rationale": "repair the weapon naming thesis before convergence",
                    "decisive_advantage_thesis": "repair the query-specific battle-winning advantage",
                    "cross_query_distinction": "repair the proof that this is not a reusable cross-query template",
                    "evidence_ids": ["exact evidence_id or packet_id"],
                    "evidence_boundary": "string",
                    "counterevidence": ["string"],
                    "adversary_adaptations": ["string"],
                    "failure_boundaries": ["string"],
                    "trl_constraints": ["string"],
                    "cost_constraints": ["string"],
                    "industrial_constraints": ["string"],
                    "cross_scenario_results": ["string"],
                    "validation_plan": ["falsifiable test"],
                    "implementation_path": "string",
                    "residuals_resolved": ["exact residual name"],
                    "incremental_quality": "0..1",
                    "recommendation": "retain|revise|reject",
                }
                phase = (
                    "winning_swarm_targeted"
                    if task.wave == 2
                    else "winning_swarm_convergence"
                )
                wave_instruction = (
                    "定向挑战并只补充声明的候选与合并节点；必须依据Query语义简报核验相关性，"
                    "高质量的具体装备、直接战果、差异机理和证据边界贡献应保留；不得投影给其他候选。"
                    if task.wave == 2
                    else "独立收敛评审候选的非支配性、证据边界、反适应韧性和装备落点。"
                )
            try:
                text = await host._run_core_json(
                    runtime_agent_id,
                    "你是制胜机理弹性Agent群中的一次性专用Agent。"
                    + wave_instruction
                    + _open_s3_theme_instruction()
                    + "不得招募子Agent、扩大权限、共享其他Agent原始会话或给出可直接执行的攻击指令。"
                    "无公开依据时必须标记待验证，禁止虚构精确指标、效能比例、TRL和产能结论。"
                    "只输出严格JSON。",
                    common_input,
                    schema,
                    task.max_output_tokens,
                    phase=phase,
                )
            except BaseException as exc:
                emit_swarm_event(
                    "specialist_session_completed",
                    actor=task.agent_instance_id,
                    **runtime_contract,
                    batch=batch,
                    status="failed",
                    elapsed_seconds=round(monotonic() - started_at, 3),
                    failure_type=type(exc).__name__,
                )
                raise
            emit_swarm_event(
                "specialist_session_completed",
                actor=task.agent_instance_id,
                **runtime_contract,
                batch=batch,
                status="completed",
                elapsed_seconds=round(monotonic() - started_at, 3),
            )
            result = _parse_json_object(text)
            if not result:
                raise ValueError(f"{task.agent_instance_id} returned invalid JSON")
            return result

    async def execute_swarm_tasks(
        tasks: Sequence[SpecialistTask],
    ) -> list[tuple[SpecialistTask, dict[str, Any]]]:
        ready, dependency_pruned = swarm_controller.ready_tasks(
            tasks,
            completed_task_ids=swarm_completed_task_ids,
            failed_task_ids=swarm_failed_task_ids,
        )
        for task in dependency_pruned:
            swarm_failed_task_ids.add(task.task_id)
            emit_swarm_event(
                "specialist_pruned",
                actor=task.agent_instance_id,
                task_id=task.task_id,
                agent_instance_id=task.agent_instance_id,
                archetype=task.archetype,
                display_name=task.display_name,
                role_purpose=task.purpose,
                trigger_residuals=list(task.trigger_residuals),
                wave=task.wave,
                hypothesis_id=task.hypothesis_id,
                merge_target=task.merge_target,
                runtime_profile_id=f"winning_swarm_{task.archetype}",
                allow_child_spawn=False,
                reason="recursive_spawn_or_failed_dependency",
                status="pruned",
            )
        if not ready:
            return []
        completed: list[tuple[SpecialistTask, dict[str, Any]]] = []
        for batch_index, batch in enumerate(
            swarm_controller.conflict_free_batches(ready),
            start=1,
        ):
            for task in batch:
                runtime_agent_id = f"winning_swarm_{task.archetype}"
                scoped_provider = host._provider_for(
                    runtime_agent_id,
                    isolation_id=task.agent_instance_id,
                )
                emit_swarm_event(
                    "specialist_recruitment_planned",
                    actor=task.agent_instance_id,
                    **_swarm_runtime_audit_contract(
                        task,
                        getattr(scoped_provider, "snapshot", lambda: {})(),
                        runtime_agent_id=runtime_agent_id,
                        session_ref=_swarm_session_ref(task),
                    ),
                    batch=batch_index,
                    status="planned",
                )
            outcomes = await asyncio.gather(
                *(
                    call_swarm_specialist(
                        task,
                        swarm_hypotheses.get(task.hypothesis_id),
                        batch=batch_index,
                    )
                    for task in batch
                ),
                return_exceptions=True,
            )
            for task, outcome in zip(batch, outcomes):
                if isinstance(outcome, BaseException):
                    swarm_failed_task_ids.add(task.task_id)
                    emit_swarm_event(
                        "specialist_pruned",
                        actor=task.agent_instance_id,
                        task_id=task.task_id,
                        wave=task.wave,
                        batch=batch_index,
                        hypothesis_id=task.hypothesis_id,
                        merge_target=task.merge_target,
                        reason=type(outcome).__name__,
                    )
                    continue
                swarm_completed_task_ids.add(task.task_id)
                completed.append((task, outcome))
                emit_swarm_event(
                    "specialist_completed",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    agent_instance_id=task.agent_instance_id,
                    archetype=task.archetype,
                    display_name=task.display_name,
                    role_purpose=task.purpose,
                    wave=task.wave,
                    batch=batch_index,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    runtime_profile_id=f"winning_swarm_{task.archetype}",
                    status="completed",
                )
                runs.append(
                    {
                        "step": 0,
                        "agent_id": task.agent_instance_id,
                        "template_agent_id": "winning_dynamic_specialist",
                        "middle_cycle": 0,
                        "execution_mode": "dynamic",
                        "wave": task.wave,
                        "batch": batch_index,
                        "hypothesis_id": task.hypothesis_id,
                        "merge_target": task.merge_target,
                        "status": "completed",
                    }
                )
        return completed

    async def execute_swarm_breadth() -> None:
        nonlocal swarm_plan, dynamic_outputs
        swarm_plan = swarm_controller.plan_initial(
            topic=str(shared["topic"]),
            execution_profile_id=str(shared["execution_profile_id"]),
        )
        swarm_tasks.extend(swarm_plan.tasks)
        emit_swarm_event(
            "swarm_planned",
            plan=to_plain(swarm_plan),
            wave_count=len(swarm_plan.waves),
            task_count=len(swarm_plan.tasks),
            max_dynamic_instances=swarm_controller.policy["max_dynamic_instances"],
            max_concurrency=swarm_controller.policy["max_concurrency"],
            minimum_expected_gain=swarm_controller.policy["minimum_expected_gain"],
            core_schedule=core_swarm_schedule,
        )
        outcomes = await execute_swarm_tasks(swarm_plan.tasks)
        breadth_candidates: list[WinningHypothesis] = []
        breadth_outputs: list[dict[str, Any]] = []
        for task, result in outcomes:
            raw_hypotheses = result.get("hypotheses", [])
            rows = raw_hypotheses if isinstance(raw_hypotheses, list) else []
            remaining_candidate_capacity = max(
                0,
                int(swarm_controller.policy.get("breadth_hypothesis_maximum", 12))
                - len(breadth_candidates),
            )
            rows = rows[:remaining_candidate_capacity]
            for ordinal, raw in enumerate(rows, start=1):
                if not isinstance(raw, Mapping):
                    continue
                hypothesis = swarm_controller.hypothesis_from_mapping(
                    raw,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                    ordinal=ordinal,
                )
                gate = swarm_controller.evaluate_gate(
                    hypothesis,
                    stage="breadth",
                )
                swarm_gates.append(to_plain(gate))
                emit_swarm_event(
                    "swarm_gate_evaluated",
                    hypothesis_id=hypothesis.hypothesis_id,
                    stage="breadth",
                    passed=gate.passed,
                    score=gate.score,
                    residuals=gate.residuals,
                )
                if not gate.passed:
                    rejected = {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "stage": "breadth",
                        "reasons": gate.rejection_reasons or gate.residuals,
                    }
                    swarm_rejections.append(rejected)
                    emit_swarm_event("hypothesis_rejected", **rejected)
                    continue
                breadth_candidates.append(hypothesis)
                breadth_outputs.append(
                    {
                        "agent_instance_id": task.agent_instance_id,
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "display_name": task.display_name,
                        "merge_target": task.merge_target,
                        "accepted": True,
                        "result": {
                            "findings": [
                                hypothesis.title,
                                *hypothesis.mechanism_chain[:2],
                            ],
                            "evidence_refs": hypothesis.evidence_ids,
                            "contribution_to_steps": [
                                {
                                    "step": int(task.merge_target[1:])
                                    if task.merge_target.startswith("S")
                                    else 6,
                                    "contribution": hypothesis.novelty_delta,
                                }
                            ],
                            "open_questions": hypothesis.residuals[:2],
                            "confidence": hypothesis.score,
                            "merge_target": task.merge_target,
                        },
                    }
                )
                emit_swarm_event(
                    "hypothesis_created",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    hypothesis_id=hypothesis.hypothesis_id,
                    title=hypothesis.title,
                    merge_target=task.merge_target,
                    score=hypothesis.score,
                )
        unique, merges = await cluster_hypotheses_with_independent_codex(
            breadth_candidates,
            scope_id="swarm-breadth",
        )
        kept_ids = {item.hypothesis_id for item in unique}
        swarm_merges.extend(merges)
        for row in merges:
            emit_swarm_event("hypothesis_merged", **row)
        swarm_hypotheses.update({item.hypothesis_id: item for item in unique})
        dynamic_outputs.extend(
            item for item in breadth_outputs if item["hypothesis_id"] in kept_ids
        )
        accumulated["dynamic_subagent_outputs"] = list(dynamic_outputs)

    async def execute_swarm_challenges() -> None:
        nonlocal dynamic_outputs
        breadth_gates = [
            swarm_controller.evaluate_gate(item, stage="breadth")
            for item in swarm_hypotheses.values()
        ]
        tasks = swarm_controller.plan_targeted(
            list(swarm_hypotheses.values()),
            breadth_gates,
            topic=str(shared["topic"]),
            used_instances=len(swarm_tasks),
        )
        swarm_tasks.extend(tasks)
        outcomes = await execute_swarm_tasks(tasks)
        for task, result in outcomes:
            try:
                contribution = swarm_controller.contribution_from_mapping(
                    result,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                )
            except ValueError as exc:
                swarm_failed_task_ids.add(task.task_id)
                emit_swarm_event(
                    "specialist_pruned",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    wave=task.wave,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    reason=str(exc)[:300],
                )
                continue
            swarm_contributions.append(contribution)
            if not contribution.accepted:
                emit_swarm_event(
                    "specialist_pruned",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    wave=task.wave,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    reason="incremental_quality_below_threshold",
                    incremental_quality=contribution.incremental_quality,
                )
                continue
            updated = swarm_controller.apply_contribution(
                swarm_hypotheses[task.hypothesis_id],
                contribution,
            )
            swarm_hypotheses[updated.hypothesis_id] = updated
            dynamic_outputs.append(
                {
                    "agent_instance_id": task.agent_instance_id,
                    "hypothesis_id": task.hypothesis_id,
                    "display_name": task.display_name,
                    "merge_target": task.merge_target,
                    "accepted": True,
                    "result": {
                        "findings": contribution.findings,
                        "evidence_refs": contribution.evidence_ids,
                        "contribution_to_steps": [
                            {
                                "step": int(task.merge_target[1:])
                                if task.merge_target.startswith("S")
                                else 6,
                                "contribution": finding,
                            }
                            for finding in contribution.findings[:3]
                        ],
                        "open_questions": updated.residuals[:2],
                        "confidence": updated.score,
                        "merge_target": task.merge_target,
                    },
                }
            )
            emit_swarm_event(
                "hypothesis_merged",
                actor=task.agent_instance_id,
                hypothesis_id=task.hypothesis_id,
                contribution_id=contribution.contribution_id,
                merge_target=task.merge_target,
                incremental_quality=contribution.incremental_quality,
            )
        accumulated["dynamic_subagent_outputs"] = list(dynamic_outputs)

    async def execute_swarm_convergence() -> None:
        nonlocal dynamic_outputs
        preliminary, _, preliminary_gates = swarm_controller.select_finalists(
            list(swarm_hypotheses.values())
        )
        if not preliminary:
            preliminary = sorted(
                swarm_hypotheses.values(),
                key=lambda item: (-item.score, item.hypothesis_id),
            )[: int(swarm_controller.policy.get("finalist_maximum", 12))]
        swarm_gates.extend(to_plain(item) for item in preliminary_gates)
        tasks = swarm_controller.plan_convergence(
            preliminary,
            topic=str(shared["topic"]),
            used_instances=len(swarm_tasks),
        )
        swarm_tasks.extend(tasks)
        outcomes = await execute_swarm_tasks(tasks)
        for task, result in outcomes:
            try:
                contribution = swarm_controller.contribution_from_mapping(
                    result,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                )
            except ValueError as exc:
                emit_swarm_event(
                    "specialist_pruned",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    wave=task.wave,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    reason=str(exc)[:300],
                )
                continue
            swarm_contributions.append(contribution)
            if contribution.accepted:
                swarm_hypotheses[task.hypothesis_id] = (
                    swarm_controller.apply_contribution(
                        swarm_hypotheses[task.hypothesis_id],
                        contribution,
                    )
                )
                dynamic_outputs.append(
                    {
                        "agent_instance_id": task.agent_instance_id,
                        "hypothesis_id": task.hypothesis_id,
                        "display_name": task.display_name,
                        "merge_target": task.merge_target,
                        "accepted": True,
                        "result": {
                            "findings": contribution.findings,
                            "evidence_refs": contribution.evidence_ids,
                            "contribution_to_steps": [
                                {"step": 6, "contribution": finding}
                                for finding in contribution.findings[:3]
                            ],
                            "open_questions": swarm_hypotheses[
                                task.hypothesis_id
                            ].residuals[:2],
                            "confidence": swarm_hypotheses[task.hypothesis_id].score,
                            "merge_target": task.merge_target,
                        },
                    }
                )
                emit_swarm_event(
                    "hypothesis_merged",
                    actor=task.agent_instance_id,
                    hypothesis_id=task.hypothesis_id,
                    contribution_id=contribution.contribution_id,
                    merge_target=task.merge_target,
                    incremental_quality=contribution.incremental_quality,
                )
        finalists, rejected, final_gates = swarm_controller.select_finalists(
            list(swarm_hypotheses.values())
        )
        swarm_gates.extend(to_plain(item) for item in final_gates)
        for gate in final_gates:
            emit_swarm_event(
                "swarm_gate_evaluated",
                hypothesis_id=gate.hypothesis_id,
                stage=gate.stage,
                passed=gate.passed,
                score=gate.score,
                residuals=gate.residuals,
                rejection_reasons=gate.rejection_reasons,
            )
        for hypothesis in rejected:
            gate = next(
                (
                    item
                    for item in final_gates
                    if item.hypothesis_id == hypothesis.hypothesis_id
                ),
                None,
            )
            rejection = {
                "hypothesis_id": hypothesis.hypothesis_id,
                "stage": "final",
                "reasons": (
                    list(gate.rejection_reasons)
                    if gate is not None and gate.rejection_reasons
                    else list(hypothesis.residuals)
                    or ["最终候选组合未选中，具体排序原因缺失"]
                ),
            }
            swarm_rejections.append(rejection)
            emit_swarm_event("hypothesis_rejected", **rejection)
        finalist_ids = {item.hypothesis_id for item in finalists}
        for hypothesis_id, hypothesis in list(swarm_hypotheses.items()):
            swarm_hypotheses[hypothesis_id] = replace(
                hypothesis,
                status=("finalist" if hypothesis_id in finalist_ids else "rejected"),
            )
        accumulated["dynamic_subagent_outputs"] = list(dynamic_outputs)
        accumulated["winning_swarm"] = {
            "policy": dict(swarm_controller.policy),
            "plan": to_plain(swarm_plan) if swarm_plan else {},
            "task_graph": [to_plain(item) for item in swarm_tasks],
            "waves": [
                {
                    "wave": wave,
                    "task_ids": [
                        item.task_id for item in swarm_tasks if item.wave == wave
                    ],
                }
                for wave in range(1, 4)
                if any(item.wave == wave for item in swarm_tasks)
            ],
            "hypotheses": [
                to_plain(item)
                for item in sorted(
                    swarm_hypotheses.values(),
                    key=lambda row: (-row.score, row.hypothesis_id),
                )
            ],
            "finalists": [to_plain(item) for item in finalists],
            "contributions": [to_plain(item) for item in swarm_contributions],
            "gates": list(swarm_gates),
            "merges": list(swarm_merges),
            "rejections": list(swarm_rejections),
            "promotion_candidates": [],
            "core_schedule": dict(core_swarm_schedule),
            "budget": {
                "planned_instances": len(swarm_tasks),
                "completed_instances": len(swarm_completed_task_ids),
                "failed_or_pruned_instances": len(swarm_failed_task_ids),
                "maximum_instances": swarm_controller.policy["max_dynamic_instances"],
                "maximum_concurrency": swarm_controller.policy["max_concurrency"],
                "maximum_waves": swarm_controller.policy["max_waves"],
            },
            "stop_reason": (
                "quality_gain_below_threshold"
                if any(not item.accepted for item in swarm_contributions)
                else "bounded_three_wave_complete"
            ),
        }
        emit_swarm_event(
            "swarm_gate_evaluated",
            stage="portfolio",
            passed=bool(finalists),
            finalist_count=len(finalists),
            rejected_count=len(rejected),
            swarm_summary=accumulated["winning_swarm"],
        )

    async def execute_dynamic_mission_graph() -> None:
        """Execute the v2 S1-S6 role graph as isolated, dependency-ready turns.

        Unlike ``swarm_quality_v1`` this path does not run one fixed Codex
        turn for each S node.  Every graph instance is a governed role and
        every model turn receives only the immutable candidate-ledger
        snapshot available when it starts.  Commits are serialized locally;
        stale contributions are explicitly rebased before they can merge.
        """

        nonlocal dynamic_outputs
        # Dynamic-v2 has no reserved legacy repair or quality-judge capacity.
        repair_reserve = 0
        maximum_instances = int(
            swarm_controller.policy.get("max_dynamic_instances", 18)
        )
        producer_instance_limit = max(
            int(swarm_controller.policy.get("mission_graph_min_instances", 8)),
            min(
                maximum_instances - max(0, repair_reserve),
                int(swarm_controller.policy.get("mission_graph_target_instances", 15)),
            ),
        )
        target_instances = min(
            int(swarm_controller.policy.get("mission_graph_target_instances", 12)),
            producer_instance_limit,
        )
        graph = swarm_controller.build_mission_graph(
            topic=str(shared["topic"]),
            execution_profile_id=str(shared["execution_profile_id"]),
            target_instances=target_instances,
            query_theses=(
                shared.get("structured_query_brief", {}).get(
                    "equipment_project_hypotheses", []
                )
                if isinstance(shared.get("structured_query_brief", {}), Mapping)
                else []
            ),
        )
        contracts = {item.role_contract_id: item for item in graph.role_contracts}
        completed_instances: set[str] = set()
        failed_instances: set[str] = set()
        pending = {item.instance_id: item for item in graph.agent_instances}
        hypotheses: list[WinningHypothesis] = []
        ledger: HypothesisLedgerVersion | None = None
        merge_receipts: list[MergeReceipt] = []
        contribution_rows: list[WinningContribution] = []
        execution_batches: list[dict[str, Any]] = []
        maximum_observed_concurrency = 0
        instance_hypothesis_ids: dict[str, set[str]] = {}
        reasoning_seeds_by_instance: dict[str, list[dict[str, Any]]] = {}
        winning_angle_assignments: dict[str, dict[str, Any]] = {}
        query_equipment_blueprint: dict[str, Any] = {}
        winning_angle_refresh_task: asyncio.Task[None] | None = None
        candidate_id_aliases: dict[str, str] = {}
        portfolio_rejected_ids: set[str] = set()
        reviewed_candidate_ids: set[str] = set()
        pending_incremental_review_ids: set[str] = set()
        review_targets_by_instance: dict[str, set[str]] = {}
        incremental_review_sequence = 0
        semantic_clustered_ledger_version = -1
        candidate_competition_converged = False
        s3_active_instances_materialized = False
        initial_expert_review_scope: set[str] | None = None
        dynamic_instance_retry_counts: dict[str, int] = {}
        running_instances: dict[
            asyncio.Task[tuple[WinningAgentInstance, dict[str, Any], int]],
            tuple[WinningAgentInstance, set[str], int],
        ] = {}
        running_started_at: dict[asyncio.Task[Any], float] = {}

        def creative_producer_instances() -> list[WinningAgentInstance]:
            """Interleave S3/S4 so either group can receive active dimensions."""

            by_node = {
                node: [
                    item
                    for item in graph.agent_instances
                    if item.mission_node == node and not item.hypothesis_id
                ]
                for node in ("S3", "S4")
            }
            rows: list[WinningAgentInstance] = []
            for index in range(max((len(value) for value in by_node.values()), default=0)):
                for node in ("S3", "S4"):
                    if index < len(by_node[node]):
                        rows.append(by_node[node][index])
            return rows

        async def _refresh_winning_angle_assignments_once() -> None:
            """Build non-authoritative diversity provocations for S3/S4 creators.

            The scout may suppress obviously duplicate capacity, but it does
            not own the equipment answer.  Every isolated creator first forms
            its own Query interpretation and may accept, reframe or replace
            the suggested lens.  Semantic clustering and S5 remain the first
            authoritative cross-candidate decisions.
            """

            nonlocal winning_angle_assignments
            nonlocal query_equipment_blueprint
            if winning_angle_assignments:
                return
            producers = creative_producer_instances()
            structured_brief = shared.get("structured_query_brief", {})
            blueprint_theses = [
                dict(item)
                for item in (
                    structured_brief.get("equipment_project_hypotheses", [])
                    if isinstance(structured_brief, Mapping)
                    else []
                )
                if isinstance(item, Mapping)
            ][: len(producers)]
            frontier_theses = [
                dict(item)
                for item in (
                    structured_brief.get("frontier_technology_hypotheses", [])
                    if isinstance(structured_brief, Mapping)
                    else []
                )
                if isinstance(item, Mapping)
            ][: len(producers)]
            raw_seeds = [
                dict(seed)
                for instance_id in sorted(reasoning_seeds_by_instance)
                for seed in reasoning_seeds_by_instance[instance_id]
                if isinstance(seed, Mapping)
            ]
            distinct_seeds: list[dict[str, Any]] = []
            seen_spines: set[tuple[str, str, str]] = set()
            for seed in raw_seeds:
                spine = tuple(
                    str(seed.get(key, "")).strip().casefold()
                    for key in (
                        "changed_confrontation_variable",
                        "mechanism_thesis",
                        "direct_military_result",
                    )
                )
                if not any(spine) or spine in seen_spines:
                    continue
                seen_spines.add(spine)
                distinct_seeds.append(seed)

            def angle_semantic_text(value: Mapping[str, Any]) -> str:
                """Project one thesis/seed onto its pre-generation win logic.

                This is used only to allocate isolated S3 sessions.  It
                does not generate prose or infer an equipment family.  By
                comparing the changed confrontation variable, mechanism
                and direct result before candidate authoring, a fourth
                S1/S2-derived seed cannot be selected merely because it
                occupies the fourth list position while duplicating a
                blueprint thesis already assigned to another session.
                """

                return "；".join(
                    str(value.get(key, "")).strip()
                    for key in (
                        "query_causal_link",
                        "changed_confrontation_variable",
                        "project_function",
                        "mechanism_thesis",
                        "frontier_principle",
                        "technology_discontinuity",
                        "novelty_search_question",
                        "exclusion_boundary",
                        "direct_military_effect",
                        "direct_military_result",
                        "target_and_phase",
                    )
                    if str(value.get(key, "")).strip()
                )

            # Select the complete active + reserve thesis portfolio before
            # any S3 candidate is authored.  Earlier code trusted the
            # first blueprint theses and only reviewed leftovers, which
            # allowed an incremental mechanism to consume an S3 slot and
            # be rejected much later by the expert judge.  This isolated
            # review can also formulate a replacement thesis when S1/S2
            # supplied fewer than four genuinely disruptive relationships.
            angle_candidates: list[dict[str, Any]] = []
            for index, thesis in enumerate(blueprint_theses, start=1):
                angle_candidates.append(
                    {
                        "angle_id": f"blueprint-angle-{index}",
                        "source": "query_blueprint_thesis",
                        # A blueprint title is only an internal planning label;
                        # it must not become an S3 naming seed.
                        "project_name": "",
                        "equipment_form_hypothesis": str(
                            thesis.get("equipment_form", "")
                        ).strip(),
                        "target_and_phase": str(
                            thesis.get("target_and_phase", "")
                        ).strip(),
                        "mechanism_thesis": str(
                            thesis.get("project_function")
                            or thesis.get("query_causal_link", "")
                        ).strip(),
                        "changed_confrontation_variable": str(
                            thesis.get("query_causal_link", "")
                        ).strip(),
                        "direct_military_result": str(
                            thesis.get("direct_military_effect", "")
                        ).strip(),
                        "competing_explanation": str(
                            thesis.get("competing_explanation", "")
                        ).strip(),
                        "adversary_adaptation": str(
                            thesis.get("adversary_adaptation", "")
                        ).strip(),
                        "failure_boundary": str(
                            thesis.get("failure_boundary", "")
                        ).strip(),
                    }
                )
            for index, thesis in enumerate(frontier_theses, start=1):
                angle_candidates.append(
                    {
                        "angle_id": f"frontier-angle-{index}",
                        "source": "query_frontier_technology_hypothesis",
                        "project_name": "",
                        "equipment_form_hypothesis": str(
                            thesis.get("equipment_implication", "")
                        ).strip(),
                        "target_and_phase": "",
                        "mechanism_thesis": str(
                            thesis.get("query_causal_link", "")
                        ).strip(),
                        "changed_confrontation_variable": str(
                            thesis.get("disruptive_delta")
                            or thesis.get("conventional_absorption_limit", "")
                        ).strip(),
                        "direct_military_result": str(
                            thesis.get("direct_military_effect", "")
                        ).strip(),
                        "frontier_principle": str(
                            thesis.get("enabling_principle", "")
                        ).strip(),
                        "technology_discontinuity": str(
                            thesis.get("disruptive_delta")
                            or thesis.get("conventional_absorption_limit", "")
                        ).strip(),
                        "technology_horizon": str(
                            thesis.get("technology_horizon", "")
                        ).strip(),
                        "engineering_bottleneck": str(
                            thesis.get("engineering_bottleneck", "")
                        ).strip(),
                        "competing_explanation": "",
                        "adversary_adaptation": "",
                        "failure_boundary": str(
                            thesis.get("disconfirming_condition", "")
                        ).strip(),
                    }
                )
            for index, seed in enumerate(distinct_seeds, start=1):
                angle_candidates.append(
                    {
                        "angle_id": f"reasoning-angle-{index}",
                        "source": "s1_s2_query_reasoning",
                        "project_name": "",
                        "equipment_form_hypothesis": "",
                        "target_and_phase": str(
                            seed.get("target_and_phase", "")
                        ).strip(),
                        "mechanism_thesis": str(
                            seed.get("mechanism_thesis", "")
                        ).strip(),
                        "changed_confrontation_variable": str(
                            seed.get("changed_confrontation_variable", "")
                        ).strip(),
                        "direct_military_result": str(
                            seed.get("direct_military_result", "")
                        ).strip(),
                        "competing_explanation": str(
                            seed.get("competing_explanation", "")
                        ).strip(),
                        "adversary_adaptation": str(
                            seed.get("adversary_adaptation", "")
                        ).strip(),
                        "failure_boundary": str(
                            seed.get("failure_boundary", "")
                        ).strip(),
                    }
                )
            angle_candidates = [
                item for item in angle_candidates if angle_semantic_text(item)
            ]
            reviewer_observations = [
                dict(item)
                for item in angle_candidates
                if item.get("source") == "s1_s2_query_reasoning"
            ]
            active_angle_ids: list[str] = []
            reserve_angle_ids: list[str] = []
            replacement_angles: list[dict[str, Any]] = []
            replacement_reserve_angles: list[dict[str, Any]] = []
            angle_selection_audit: dict[str, Any] = {}
            angle_capacity = min(
                len(producers),
                graph.maximum_concurrency,
                int(
                    swarm_controller.policy.get(
                        "s3_winning_thesis_capacity", len(producers)
                    )
                ),
            )
            reserve_target = 0
            active_selection_succeeded = False
            if (
                angle_candidates or isinstance(structured_brief, Mapping)
            ) and host.provider_kind == "codex_cli":
                try:
                    selection_text = await host._run_core_json(
                        "winning_swarm_independent_portfolio_reviewer",
                        "你是候选生成前的Query多样性侦察员，不是装备语义主控，也不裁决最终答案。"
                        "此时尚未产生任何装备候选。只从完整Query提取不可违反的目标、威胁、阶段、地域、"
                        "升级边界和反模板边界，并列出若干尚待S3/S4独立探索的开放断点；不要指定唯一物理创新、"
                        "唯一战场存在方式或唯一制胜逻辑。"
                        "combat_dimensions只是可选作战效应视角，不是固定分类、十二条生产线、数量配额或质量门。"
                        "根据Query只激活真正相关且能导向不同装备思考空间的维度；可以不使用多数维度，也可提出"
                        "Query特有的OTHER维度。replacement_angles只是一组可选多样性提示，不与Agent一一绑定；"
                        "后续每个Agent都可跨多个提示比较、组合、重构、全部舍弃或提出自己的方向。不得预先给出装备名称、装备家族、技术套餐、"
                        "成品构型或必须继承的答案。"
                        "S3和S4职责相同，都是创新装备生成者。只决定开放探索提示池和合理Agent容量，不给每个会话"
                        "指定唯一维度、答案方向或排他责任。maximum_active只是并发容量上限，不要求填满；同一维度只有在Query"
                        "存在两个不可互相吸收的制胜问题时才可重复。angle_candidates只用于理解战场问题，不能"
                        "继承其装备形态、技术路线、工作名或抽象短语。只输出JSON。",
                        {
                            "query": shared.get("topic", ""),
                            "problem_boundary": _open_s3_exploration_brief(
                                str(shared.get("topic", "")),
                                structured_brief,
                            ),
                            "angle_candidates": reviewer_observations,
                            "combat_dimensions": list(
                                COMBAT_EQUIPMENT_DIVERGENCE_DIMENSIONS
                            ),
                            "source_observation_rule": (
                                "仅用于发现遗漏和相邻重复；不得原样选为S3命题，"
                                "不得继承其中的装备形态、技术路线或命名语法"
                            ),
                            "maximum_active": angle_capacity,
                            "maximum_reserve": 0,
                        },
                        {
                            "query_equipment_blueprint": {
                                "query_semantic_constraints": [
                                    "target, threat, phase, geography or escalation constraints that all creators must respect"
                                ],
                                "unresolved_battlefield_conflicts": [
                                    "open Query-specific conflict to be independently interpreted by creators"
                                ],
                                "plausible_breakpoints": [
                                    "non-authoritative breakpoint worth challenging, without a weapon answer"
                                ],
                                "anti_template_boundary": "what would make a candidate generic or transferable to another Query",
                                "authority": "soft_challenge_only",
                            },
                            "active_angle_ids": ["exact angle_id"],
                            "reserve_angle_ids": ["exact angle_id"],
                            "replacement_angles": [
                                {
                                    "activation": "active",
                                    "combat_dimension": "one Query-relevant dimension or OTHER:<natural label>",
                                    "dimension_winning_logic": "how this dimension can overturn the opponent relationship under the Query blueprint without choosing a weapon answer",
                                    "target_and_phase": "Query-specific object and stage",
                                    "mechanism_thesis": "open exploration question about an independent winning relationship, not its answer",
                                    "changed_confrontation_variable": "what relationship the S3 session may overturn",
                                    "direct_military_result": "direct battlefield result sought",
                                    "novelty_search_question": "what non-incremental opportunity should be explored without preselecting a technology",
                                    "exclusion_boundary": "which adjacent exploration problems this Agent must not duplicate",
                                    "competing_explanation": "credible alternative explanation",
                                    "adversary_adaptation": "likely counter-adaptation",
                                    "failure_boundary": "falsifiable boundary",
                                }
                            ],
                            "selection_reasons": [
                                {
                                    "angle_id": "exact angle_id or replacement index",
                                    "independent_axis": "materially different winning relationship",
                                    "disruptive_leverage": "why this changes the contest",
                                    "weapon_identity_implication": "why the thesis forces a distinct direct-combat weapon architecture",
                                    "nearest_conventional_implementation": "the strongest ordinary implementation that could absorb this thesis",
                                    "irreducible_delta": "the single mechanism that conventional implementation cannot absorb",
                                }
                            ],
                            "rejected_angle_groups": [
                                {
                                    "angle_ids": ["exact angle_id"],
                                    "reason": "duplicate, incremental, generic, or weak Query causality",
                                }
                            ],
                            "technology_discontinuity_audit": {
                                "frontier_angles_considered": [
                                    "exact frontier-angle id"
                                ],
                                "selected_frontier_angles": ["exact frontier-angle id"],
                                "rejected_frontier_reasons": [
                                    "query causality, equipment implication or feasibility reason"
                                ],
                                "process_only_portfolio_avoided": "boolean",
                            },
                            "stop_reason": "string",
                        },
                        min(1800, 760 + len(reviewer_observations) * 55),
                        phase="winning_pre_generation_active_angle_selection",
                    )
                    selection = _parse_json_object(selection_text)
                    active_selection_succeeded = True
                    raw_blueprint = selection.get("query_equipment_blueprint", {})
                    if isinstance(raw_blueprint, Mapping):
                        query_equipment_blueprint = {
                            "query_semantic_constraints": [
                                str(value).strip()
                                for value in raw_blueprint.get(
                                    "query_semantic_constraints", []
                                )
                                if str(value).strip()
                            ][:8],
                            "unresolved_battlefield_conflicts": [
                                str(value).strip()
                                for value in raw_blueprint.get(
                                    "unresolved_battlefield_conflicts", []
                                )
                                if str(value).strip()
                            ][:8],
                            "plausible_breakpoints": [
                                str(value).strip()
                                for value in raw_blueprint.get(
                                    "plausible_breakpoints", []
                                )
                                if str(value).strip()
                            ][:8],
                            "anti_template_boundary": str(
                                raw_blueprint.get("anti_template_boundary", "")
                            ).strip(),
                            "authority": "soft_challenge_only",
                        }
                    valid_ids = {str(item["angle_id"]) for item in angle_candidates}
                    active_angle_ids = list(
                        dict.fromkeys(
                            str(item)
                            for item in selection.get("active_angle_ids", [])
                            if str(item) in valid_ids
                        )
                    )[:angle_capacity]
                    reserve_angle_ids = list(
                        dict.fromkeys(
                            str(item)
                            for item in selection.get("reserve_angle_ids", [])
                            if str(item) in valid_ids
                            and str(item) not in active_angle_ids
                        )
                    )[:reserve_target]
                    normalized_replacements = [
                        {
                            "angle_id": f"reviewer-replacement-{index}",
                            "source": "pre_generation_reviewer_exploration_problem",
                            "project_name": "",
                            "equipment_form_hypothesis": "",
                            "activation": str(
                                item.get("activation", "active")
                            ).strip().lower(),
                            **{
                                key: str(item.get(key, "")).strip()
                                for key in (
                                    "combat_dimension",
                                    "dimension_winning_logic",
                                    "target_and_phase",
                                    "mechanism_thesis",
                                    "changed_confrontation_variable",
                                    "direct_military_result",
                                    "novelty_search_question",
                                    "exclusion_boundary",
                                    "competing_explanation",
                                    "adversary_adaptation",
                                    "failure_boundary",
                                )
                            },
                        }
                        for index, item in enumerate(
                            selection.get("replacement_angles", []),
                            start=1,
                        )
                        if isinstance(item, Mapping)
                        and str(item.get("mechanism_thesis", "")).strip()
                        and str(item.get("changed_confrontation_variable", "")).strip()
                        and str(item.get("direct_military_result", "")).strip()
                    ]
                    replacement_angles = [
                        item
                        for item in normalized_replacements
                        if item.get("activation") != "reserve"
                    ][:angle_capacity]
                    replacement_reserve_angles = [
                        item
                        for item in normalized_replacements
                        if item.get("activation") == "reserve"
                    ][:reserve_target]
                    angle_selection_audit = {
                        "query_equipment_blueprint": query_equipment_blueprint,
                        "selection_reasons": selection.get("selection_reasons", []),
                        "rejected_angle_groups": selection.get(
                            "rejected_angle_groups", []
                        ),
                        "technology_discontinuity_audit": selection.get(
                            "technology_discontinuity_audit", {}
                        ),
                        "stop_reason": selection.get("stop_reason", ""),
                    }
                    emit_swarm_event(
                        "winning_query_equipment_blueprint_planned",
                        actor="winning_swarm_controller",
                        graph_id=graph.graph_id,
                        query_equipment_blueprint=query_equipment_blueprint,
                        activated_dimensions=[
                            str(item.get("combat_dimension", ""))
                            for item in replacement_angles
                            if str(item.get("combat_dimension", "")).strip()
                        ],
                        rule=(
                            "Query选择相关维度；维度不是固定生产线、装备家族或命名模板"
                        ),
                    )
                except Exception as exc:
                    emit_swarm_event(
                        "winning_pre_generation_active_angle_selection_fallback",
                        actor="winning_swarm_controller",
                        graph_id=graph.graph_id,
                        failure_type=type(exc).__name__,
                        error_message=str(exc)[:300],
                    )

            angle_by_id = {str(item["angle_id"]): item for item in angle_candidates}
            selected_active = [
                dict(angle_by_id[angle_id])
                for angle_id in active_angle_ids
                if angle_id in angle_by_id
            ]
            if replacement_angles:
                selected_active = []
            for replacement in replacement_angles:
                if len(selected_active) >= angle_capacity:
                    break
                selected_active.append(dict(replacement))
            # Only transport/non-Codex fallback may fill the bounded capacity.
            # A successful semantic reviewer is allowed to activate fewer
            # theses; that decision must not be overwritten by local text
            # similarity or a desire to keep every S3 slot busy.
            remaining_angles = [
                dict(item)
                for item in angle_candidates
                if str(item["angle_id"])
                not in {str(selected["angle_id"]) for selected in selected_active}
            ]
            while (
                not active_selection_succeeded
                and remaining_angles
                and len(selected_active) < angle_capacity
            ):
                occupied_texts = [angle_semantic_text(item) for item in selected_active]
                selected = min(
                    remaining_angles,
                    key=lambda item: max(
                        (
                            _capability_text_similarity(
                                angle_semantic_text(item), occupied
                            )
                            for occupied in occupied_texts
                            if occupied
                        ),
                        default=0.0,
                    ),
                )
                remaining_angles.remove(selected)
                selected_active.append(selected)
            selected_active_ids = {str(item["angle_id"]) for item in selected_active}
            selected_reserves = [
                dict(angle_by_id[angle_id])
                for angle_id in reserve_angle_ids
                if angle_id in angle_by_id and angle_id not in selected_active_ids
            ]
            if replacement_angles:
                selected_reserves = [
                    dict(item) for item in replacement_reserve_angles
                ]
            # If the semantic reviewer was unavailable, retain a bounded
            # least-similar reserve set for intentional empty returns.
            if not selected_reserves and not active_selection_succeeded:
                reserve_remaining = [
                    item
                    for item in remaining_angles
                    if str(item["angle_id"]) not in selected_active_ids
                ]
                while reserve_remaining and len(selected_reserves) < reserve_target:
                    occupied = [
                        angle_semantic_text(item)
                        for item in [*selected_active, *selected_reserves]
                    ]
                    selected = min(
                        reserve_remaining,
                        key=lambda item: max(
                            (
                                _capability_text_similarity(
                                    angle_semantic_text(item), text
                                )
                                for text in occupied
                                if text
                            ),
                            default=0.0,
                        ),
                    )
                    reserve_remaining.remove(selected)
                    selected_reserves.append(dict(selected))

            # The Query controller is the only pre-generation semantic pass.
            # Legacy disruptive seed mapping is intentionally absent: it added
            # another model-authored solution frame before S3/S4 and correlated
            # otherwise independent creators.
            angle_selection_audit["legacy_seed_challenge_disabled"] = True

            # Reuse the established assignment transport below: active
            # angles behave as blueprint theses and pair with their own
            # semantic seed; only the preselected reserves remain unused.
            blueprint_theses = [dict(item) for item in selected_active]
            distinct_seeds = [
                *[dict(item) for item in selected_active],
                *[dict(item) for item in selected_reserves],
            ]

            unused_seed_indices = set(range(len(distinct_seeds)))

            def select_seed(
                thesis: Mapping[str, Any],
                occupied: Sequence[Mapping[str, Any]],
            ) -> dict[str, Any]:
                if not unused_seed_indices:
                    return {}
                thesis_text = angle_semantic_text(thesis)
                occupied_texts = [
                    angle_semantic_text(item)
                    for item in occupied
                    if angle_semantic_text(item)
                ]

                def rank(index: int) -> tuple[float, float, int]:
                    seed_text = angle_semantic_text(distinct_seeds[index])
                    similarity_to_thesis = (
                        _capability_text_similarity(seed_text, thesis_text)
                        if seed_text and thesis_text
                        else 0.0
                    )
                    maximum_occupied_similarity = max(
                        (
                            _capability_text_similarity(seed_text, item)
                            for item in occupied_texts
                        ),
                        default=0.0,
                    )
                    # A blueprint-backed session prefers the S1/S2 seed
                    # that explains its thesis. An open session prefers the
                    # least occupied winning relationship. Stable reverse
                    # index ordering preserves deterministic selection.
                    if thesis_text:
                        return (
                            similarity_to_thesis,
                            -maximum_occupied_similarity,
                            -index,
                        )
                    return (
                        1.0 - maximum_occupied_similarity,
                        0.0,
                        -index,
                    )

                selected_index = max(unused_seed_indices, key=rank)
                unused_seed_indices.remove(selected_index)
                return distinct_seeds[selected_index]

            reserved: list[dict[str, str]] = []
            for index, instance in enumerate(producers):
                if index >= len(blueprint_theses):
                    winning_angle_assignments[instance.instance_id] = {
                        "assignment_id": f"query-winning-capacity-{index + 1}",
                        "source": "semantic_no_distinct_angle",
                        "active": False,
                        "project_name": "",
                        "equipment_form_hypothesis": "",
                        "target_and_phase": "",
                        "mechanism_thesis": "",
                        "changed_confrontation_variable": "",
                        "direct_military_result": "",
                        "competing_explanation": "",
                        "adversary_adaptation": "",
                        "failure_boundary": "",
                        "reserved_other_angles": [],
                        "rule": (
                            "独立Query语义评审未发现可占用本容量槽的额外制胜命题；"
                            "本槽不启动模型，也不得自行补造装备。"
                        ),
                    }
                    continue
                thesis = (
                    blueprint_theses[index] if index < len(blueprint_theses) else {}
                )
                seed = select_seed(thesis, reserved)
                assignment = {
                    "assignment_id": f"query-winning-angle-{index + 1}",
                    "active": True,
                    "authority": "advisory_diversity_pool_only",
                    "allowed_response_modes": ["accept", "reframe", "replace"],
                    "self_proposed_id_pattern": "self-proposed:<short-id>",
                    "source": "query_blueprint_thesis"
                    if thesis.get("source") == "query_blueprint_thesis"
                    else "query_frontier_technology_hypothesis"
                    if thesis.get("source") == "query_frontier_technology_hypothesis"
                    else "s1_s2_query_reasoning"
                    if thesis.get("source") == "s1_s2_query_reasoning"
                    else "pre_generation_reviewer_exploration_problem"
                    if thesis.get("source")
                    == "pre_generation_reviewer_exploration_problem"
                    else "post_divergence_model_reframed_seed_angle"
                    if thesis.get("source")
                    == "post_divergence_model_reframed_seed_angle"
                    else "s1_s2_query_reasoning"
                    if seed or thesis
                    else "open_other_angle",
                    "project_name": "",
                    "combat_dimension": str(
                        thesis.get("combat_dimension", "")
                    ).strip(),
                    "dimension_winning_logic": str(
                        thesis.get("dimension_winning_logic", "")
                    ).strip(),
                    "query_equipment_blueprint": dict(query_equipment_blueprint),
                    "equipment_form_hypothesis": str(
                        thesis.get("equipment_form_hypothesis")
                        or thesis.get("equipment_form", "")
                    ).strip(),
                    "target_and_phase": str(thesis.get("target_and_phase", "")).strip(),
                    "mechanism_thesis": str(
                        thesis.get("project_function")
                        or thesis.get("query_causal_link")
                        or thesis.get("mechanism_thesis")
                        or seed.get("mechanism_thesis", "")
                    ).strip(),
                    "changed_confrontation_variable": str(
                        thesis.get("query_causal_link")
                        or thesis.get("changed_confrontation_variable")
                        or seed.get("changed_confrontation_variable", "")
                    ).strip(),
                    "direct_military_result": str(
                        thesis.get("direct_military_effect")
                        or thesis.get("direct_military_result")
                        or seed.get("direct_military_result", "")
                    ).strip(),
                    "novelty_search_question": str(
                        thesis.get("novelty_search_question")
                        or seed.get("novelty_search_question", "")
                    ).strip(),
                    "exclusion_boundary": str(
                        thesis.get("exclusion_boundary")
                        or seed.get("exclusion_boundary", "")
                    ).strip(),
                    "post_divergence_seed_provocations": list(
                        thesis.get("post_divergence_seed_provocations", [])
                    ),
                    "post_divergence_frontier_provocations": list(
                        thesis.get("post_divergence_frontier_provocations", [])
                    ),
                    "frontier_principle": str(
                        thesis.get("frontier_principle")
                        or seed.get("frontier_principle", "")
                    ).strip(),
                    "technology_discontinuity": str(
                        thesis.get("technology_discontinuity")
                        or seed.get("technology_discontinuity", "")
                    ).strip(),
                    "technology_horizon": str(
                        thesis.get("technology_horizon")
                        or seed.get("technology_horizon", "")
                    ).strip(),
                    "engineering_bottleneck": str(
                        thesis.get("engineering_bottleneck")
                        or seed.get("engineering_bottleneck", "")
                    ).strip(),
                    "competing_explanation": str(
                        thesis.get("competing_explanation")
                        or seed.get("competing_explanation", "")
                    ).strip(),
                    "adversary_adaptation": str(
                        thesis.get("adversary_adaptation")
                        or seed.get("adversary_adaptation", "")
                    ).strip(),
                    "failure_boundary": str(
                        thesis.get("failure_boundary")
                        or seed.get("failure_boundary", "")
                    ).strip(),
                    "reserved_other_angles": list(reserved),
                    "rule": (
                        "这是共享的可选多样性提示池，不是本Agent的题目、角色身份或排他分工，也不限定"
                        "技术、构型、装备家族或名称。Agent必须先独立理解完整Query，在多个维度间比较交叉关系，"
                        "然后可接受、组合、重构、全部舍弃或提出自己的OTHER方向；"
                        "语义蓝图只含共同约束和开放问题，不构成中心答案。"
                        "名称必须来自最终装备最核心的物理创新和战场存在方式，不得把维度、任务动作、"
                        "性能指标或输入字段直接压缩成装备名。"
                    ),
                }
                winning_angle_assignments[instance.instance_id] = assignment
                reserved.append(
                    {
                        "assignment_id": assignment["assignment_id"],
                        "changed_confrontation_variable": assignment[
                            "changed_confrontation_variable"
                        ],
                        "mechanism_thesis": assignment["mechanism_thesis"],
                        "direct_military_result": assignment["direct_military_result"],
                        "frontier_principle": assignment["frontier_principle"],
                        "technology_discontinuity": assignment[
                            "technology_discontinuity"
                        ],
                        "novelty_search_question": assignment[
                            "novelty_search_question"
                        ],
                        "exclusion_boundary": assignment["exclusion_boundary"],
                    }
                )
            for instance_id, assignment in winning_angle_assignments.items():
                own_id = str(assignment.get("assignment_id", ""))
                assignment["reserved_other_angles"] = [
                    dict(item)
                    for item in reserved
                    if str(item.get("assignment_id", "")) != own_id
                ]
            emit_swarm_event(
                "winning_pre_generation_angle_portfolio_planned",
                actor="winning_swarm_controller",
                graph_id=graph.graph_id,
                assigned_angle_count=sum(
                    bool(item.get("active", True))
                    for item in winning_angle_assignments.values()
                ),
                s3_capacity_slot_count=len(winning_angle_assignments),
                inactive_capacity_slot_count=sum(
                    not bool(item.get("active", True))
                    for item in winning_angle_assignments.values()
                ),
                reserve_angle_count=0,
                assigned_angles=[
                    {
                        "assignment_id": item.get("assignment_id", ""),
                        "changed_confrontation_variable": item.get(
                            "changed_confrontation_variable", ""
                        ),
                        "mechanism_thesis": item.get("mechanism_thesis", ""),
                        "direct_military_result": item.get(
                            "direct_military_result", ""
                        ),
                    }
                    for item in winning_angle_assignments.values()
                    if bool(item.get("active", True))
                ],
                reserve_angles=[],
                rule=("生成前只分发可挑战的多样性提示；S3/S4可接受、重构或提出独立OTHER方向，跨候选约束后置到语义聚类与S5"),
                selection_audit=angle_selection_audit,
            )

        async def refresh_winning_angle_assignments() -> None:
            """Share one pre-generation portfolio review across all S3 slots."""

            nonlocal winning_angle_refresh_task
            if winning_angle_assignments:
                return
            if winning_angle_refresh_task is None:
                # No await occurs between the guard and task assignment,
                # so all concurrently awakened S3 producers observe the
                # same task on the single asyncio event loop.
                winning_angle_refresh_task = asyncio.create_task(
                    _refresh_winning_angle_assignments_once()
                )
            await asyncio.shield(winning_angle_refresh_task)

        async def materialize_active_s3_instances() -> None:
            """Remove unused S3/S4 dimension capacity before execution.

            The mission graph keeps bounded S3 capacity while S1/S2 are still
            diverging.  Once the isolated Query-level selector has chosen the
            genuinely independent winning theses, only those instances should
            reach the scheduler.  Earlier code scheduled every capacity slot
            and let ``call_instance`` return a synthetic skipped result; those
            zero-work tasks polluted batches and could briefly occupy scarce
            model slots ahead of real S3 authors.
            """

            nonlocal graph, s3_active_instances_materialized
            if s3_active_instances_materialized:
                return
            await refresh_winning_angle_assignments()
            inactive_ids = {
                item.instance_id
                for item in graph.agent_instances
                if item.mission_node in {"S3", "S4"}
                and not item.hypothesis_id
                and not bool(
                    winning_angle_assignments.get(item.instance_id, {}).get(
                        "active", True
                    )
                )
            }
            s3_active_instances_materialized = True
            if not inactive_ids:
                return

            for instance_id in inactive_ids:
                pending.pop(instance_id, None)
                completed_instances.add(instance_id)
                instance_hypothesis_ids[instance_id] = set()

            retained_instances: list[WinningAgentInstance] = []
            for item in graph.agent_instances:
                if item.instance_id in inactive_ids:
                    continue
                retained_instances.append(
                    replace(
                        item,
                        depends_on=[
                            dependency
                            for dependency in item.depends_on
                            if dependency not in inactive_ids
                        ],
                    )
                )
            retained_by_id = {item.instance_id: item for item in retained_instances}
            for instance_id, item in list(pending.items()):
                if instance_id in retained_by_id:
                    pending[instance_id] = retained_by_id[instance_id]
            dependencies = {
                item.instance_id: list(item.depends_on) for item in retained_instances
            }
            maximum_wave = max((item.wave for item in retained_instances), default=0)
            waves = [
                [
                    item.instance_id
                    for item in retained_instances
                    if item.wave == wave_index
                ]
                for wave_index in range(1, maximum_wave + 1)
            ]
            seeds = {key: list(value) for key, value in graph.s_node_seeds.items()}
            seeds["S3"] = [
                instance_id
                for instance_id in seeds.get("S3", [])
                if instance_id not in inactive_ids
            ]
            seeds["S4"] = [
                instance_id
                for instance_id in seeds.get("S4", [])
                if instance_id not in inactive_ids
            ]
            graph = replace(
                graph,
                agent_instances=retained_instances,
                dependencies=dependencies,
                waves=waves,
                s_node_seeds=seeds,
            )
            emit_swarm_event(
                "winning_s3_active_agents_materialized",
                actor="winning_swarm_controller",
                graph_id=graph.graph_id,
                active_instance_ids=[
                    *seeds.get("S3", []),
                    *seeds.get("S4", []),
                ],
                active_instance_count=(
                    len(seeds.get("S3", [])) + len(seeds.get("S4", []))
                ),
                unused_capacity_count=len(inactive_ids),
                rule=(
                    "Query语义选择后仅物化有效制胜命题；未使用容量不进入调度或模型调用"
                ),
            )

        def task_for_instance(instance: WinningAgentInstance) -> SpecialistTask:
            contract = contracts[instance.role_contract_id]
            display_name = instance.display_name
            purpose = contract.purpose
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                producers = creative_producer_instances()
                try:
                    position = producers.index(instance)
                except ValueError:
                    position = 0
                label = chr(ord("A") + min(position, 25))
                assignment = dict(
                    winning_angle_assignments.get(instance.instance_id, {})
                )
                dimension = str(assignment.get("combat_dimension", "")).strip()
                display_name = f"开放创新武器 Agent {label}"
                semantic_parts = [
                    str(assignment.get("target_and_phase", "")).strip(),
                    str(assignment.get("changed_confrontation_variable", "")).strip(),
                    str(assignment.get("mechanism_thesis", "")).strip(),
                    str(assignment.get("direct_military_result", "")).strip(),
                    str(assignment.get("failure_boundary", "")).strip(),
                ]
                if any(semantic_parts):
                    target, changed_variable, mechanism, result, boundary = (
                        semantic_parts
                    )
                    purpose = (
                        f"先独立分析完整Query及{target or '关键作战阶段'}，自主发散创新武器装备。"
                        "以下只是从共享多样性池抽取的一条非权威启发，可与其他维度交叉、重构或全部舍弃："
                        f"{dimension or '开放创新'}视角下的{mechanism or changed_variable or '新制胜关系'}，"
                        f"观察{result or '直接军事效果'}。不要围绕该维度填题；先比较多种物理创新、"
                        "战场存在方式和装备身份，再独立完成自然名称与一句制胜说明。"
                        "本会话只创造候选，不承担物化、接口收敛、证据核验或工程验证。"
                    )
            output_budget = (
                1000
                if instance.archetype == "independent_portfolio_reviewer"
                else 3200
                if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id
                else 2200
            )
            return SpecialistTask(
                task_id=instance.instance_id,
                agent_instance_id=instance.instance_id,
                archetype=instance.archetype,
                display_name=display_name,
                wave=instance.wave,
                purpose=purpose,
                merge_target=instance.merge_target,
                hypothesis_id=instance.hypothesis_id,
                trigger_residuals=list(instance.trigger_residuals),
                depends_on=list(instance.depends_on),
                expected_quality_gain=instance.expected_quality_gain,
                max_output_tokens=output_budget,
                allow_child_spawn=False,
            )

        def canonical_candidate_id(hypothesis_id: str) -> str:
            current = str(hypothesis_id)
            seen: set[str] = set()
            while current in candidate_id_aliases and current not in seen:
                seen.add(current)
                current = candidate_id_aliases[current]
            return current

        async def call_instance(
            instance: WinningAgentInstance,
            *,
            ledger_snapshot: HypothesisLedgerVersion | None,
            batch_index: int,
            candidate_scope: set[str],
        ) -> tuple[WinningAgentInstance, dict[str, Any], int]:
            if instance.allow_child_spawn:
                raise ValueError("mission graph instances may not recruit child agents")
            contract = contracts[instance.role_contract_id]
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                await refresh_winning_angle_assignments()
                assignment = winning_angle_assignments.get(instance.instance_id, {})
                if not bool(assignment.get("active", True)):
                    emit_swarm_event(
                        "winning_s3_capacity_slot_skipped",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        batch=batch_index,
                        assignment_id=str(assignment.get("assignment_id", "")),
                        reason="semantic_no_distinct_angle",
                    )
                    return (
                        instance,
                        {
                            "hypotheses": [],
                            "quality_residuals": [],
                            "stop_reason": ("Query语义评审未激活该容量槽"),
                            "semantic_capacity_inactive": True,
                        },
                        (ledger_snapshot.version if ledger_snapshot is not None else 0),
                    )
            # S3 task identity is bound only after semantic selection.  A
            # reallocated reserve therefore receives a freshly derived
            # purpose instead of retaining its prior static role or a
            # blueprint equipment working name.
            task = task_for_instance(instance)
            runtime_agent_id = f"winning_swarm_{instance.archetype}"
            scoped_provider = host._provider_for(
                runtime_agent_id,
                isolation_id=instance.instance_id,
            )
            runtime_contract = _swarm_runtime_audit_contract(
                task,
                getattr(scoped_provider, "snapshot", lambda: {})(),
                runtime_agent_id=runtime_agent_id,
                session_ref=_swarm_session_ref(task),
            )
            emit_swarm_event(
                "winning_agent_instance_ready",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                role_contract_id=instance.role_contract_id,
                mission_node=instance.mission_node,
                depends_on=list(instance.depends_on),
                batch=batch_index,
                **runtime_contract,
            )
            ledger_candidates = (
                list(ledger_snapshot.hypotheses)
                if ledger_snapshot is not None
                else list(hypotheses)
            )
            # Validation designers only need the candidate branches
            # produced by their declared dependencies.  The old S6
            # exception sent the complete ledger to every validation
            # designer and made a two-candidate task reread 30-40k chars.
            # Only the independent portfolio reviewer is intentionally
            # global.
            if candidate_scope:
                ledger_candidates = [
                    item
                    for item in ledger_candidates
                    if item.hypothesis_id in candidate_scope
                ]
            candidate_snapshot = [
                _compact_swarm_candidate_handoff(
                    item,
                    portfolio_summary=(
                        instance.archetype == "independent_portfolio_reviewer"
                    ),
                )
                for item in ledger_candidates
            ]
            compact_evidence_index: list[Any] = []
            if instance.mission_node in {"S1", "S2", "S3", "S4"}:
                # Creative turns are intentionally evidence-free. Evidence,
                # maturity and validation fields anchor independent creators
                # to familiar solutions and belong outside this session.
                candidate_snapshot = []
            elif instance.archetype == "independent_portfolio_reviewer":
                candidate_snapshot = [
                    _minimal_portfolio_candidate_handoff(item)
                    for item in ledger_candidates
                ]
            candidate_handoff_chars = len(
                json.dumps(candidate_snapshot, ensure_ascii=False)
            )
            evidence_handoff_chars = len(
                json.dumps(compact_evidence_index, ensure_ascii=False)
            )
            common_input = {
                # Carry durable identity into every isolated dynamic turn
                # so model progress is attributable to one S-node and
                # refreshes the Worker lease while the CLI is running.
                "run_id": shared.get("run_id", ""),
                "agent_instance_id": instance.instance_id,
                "batch": batch_index,
                "mission_node": instance.mission_node,
                "topic": shared["topic"],
                "research_route": shared["research_route"],
                "execution_profile_id": shared["execution_profile_id"],
                "discovery_branch": primary_branch,
                "query_led_combat_equipment_themes": (
                    _open_s3_theme_contract()
                    if instance.mission_node in {"S1", "S2", "S3", "S4"}
                    else _query_led_combat_equipment_theme_contract()
                ),
                "query_combat_equipment_divergence_brief": (
                    _open_s3_exploration_brief(
                        str(shared.get("topic", "")),
                        shared.get("structured_query_brief", {}),
                    )
                    if instance.mission_node in {"S1", "S2", "S3", "S4"}
                    else _query_combat_equipment_divergence_brief(
                        str(shared.get("topic", "")),
                        structured_query_brief=shared.get(
                            "structured_query_brief", {}
                        ),
                    )
                ),
                "mission_graph": {
                    "graph_id": graph.graph_id,
                    "mission_objective": graph.mission_objective,
                },
                "equipment_portfolio_contract": {
                    "selection_rule": (
                        "所有通过Query因果、直接军事效果和独立性评审的直接战斗武器均可进入S6；"
                        "对象证据与证据边界有则优先保留，没有不得因此淘汰；数量不是质量门或淘汰理由。"
                    ),
                    "minimum_direct_combat_equipment": 1,
                    "direct_equipment_definition": (
                        "主体装备直接承担低空进入、侦察打击、突防、压制、猎歼、"
                        "拦截、精确毁伤或区域拒止；C2、通信、算法、网关和保障"
                        "只能作为内嵌接口或约束。"
                    ),
                    "priority_lanes": [
                        "从query敌方目标和任务阶段反推的直接打击/毁伤武器",
                        "从query对抗压力反推的突防、导引、拦截或效应构型",
                        "探索未复述共享Prompt示例名称的OTHER新质装备架构，并与已激活方向竞争",
                        "仅在query存在明确因果关系时采用低成本、无人、高超声速或定向能镜头",
                    ],
                    "priority_lane_rule": (
                        "以上是生成顺序而非装备目录；不得为覆盖主题生成与query无关的方向。"
                    ),
                    "disruptive_lenses": [
                        {
                            "logic": "成本逻辑",
                            "shift": "性能竞争转向经济竞争",
                            "essential_change": "用规模改变交换关系",
                        },
                        {
                            "logic": "制造逻辑",
                            "shift": "工厂生产转向战区制造",
                            "essential_change": "制造能力成为战斗力",
                        },
                        {
                            "logic": "平台逻辑",
                            "shift": "平台中心转向火力生态",
                            "essential_change": "火力成为网络资源",
                        },
                        {
                            "logic": "时间逻辑",
                            "shift": "快速响应转向时间占位",
                            "essential_change": "控制战争节奏",
                        },
                        {
                            "logic": "毁伤逻辑",
                            "shift": "摧毁实体转向剥夺能力",
                            "essential_change": "从杀伤到瘫痪",
                        },
                        {
                            "logic": "智能逻辑",
                            "shift": "人控武器转向自进化生态",
                            "essential_change": "从装备竞争到智能竞争",
                        },
                    ],
                    "disruptive_lens_rule": (
                        "这些只是非穷尽启发镜头，不是六条生产线、装备类别、数量配额或质量门。"
                        "先由Query的目标、任务断点和对抗变量确定制胜命题；仅在存在直接因果关系时"
                        "采用其中任意方向，也可全部舍弃并形成表外的新颠覆逻辑。"
                    ),
                },
                "role_contract": _dynamic_role_contract_handoff(contract, task),
                "specialist_task": to_plain(task),
                "candidate_ledger": {
                    "ledger_id": ledger_snapshot.ledger_id if ledger_snapshot else "",
                    "version": ledger_snapshot.version if ledger_snapshot else 0,
                    "hypotheses": candidate_snapshot,
                    "allowed_hypothesis_ids": sorted(candidate_scope),
                    "handoff_schema": (
                        "portfolio_decision_spine_v2"
                        if instance.archetype == "independent_portfolio_reviewer"
                        else "compact_decision_spine_v1"
                    ),
                },
                "evidence_index": compact_evidence_index,
                "valid_reference_ids": sorted(valid_reference_ids),
                "isolation_contract": {
                    "raw_other_agent_sessions_visible": False,
                    "may_recruit_child_agent": False,
                    "declared_merge_target": instance.merge_target,
                },
                "upstream_reasoning_seeds": [
                    seed
                    for dependency in instance.depends_on
                    for seed in reasoning_seeds_by_instance.get(dependency, [])
                ][
                    :6
                    if instance.mission_node in {"S3", "S4"}
                    else 12
                ],
            }
            if instance.mission_node in {"S1", "S2", "S3", "S4"}:
                open_brief = _open_s3_exploration_brief(
                    str(shared.get("topic", "")),
                    shared.get("structured_query_brief", {}),
                )
                upstream_seeds = [
                    {
                        key: seed.get(key, "")
                        for key in (
                            "combat_problem",
                            "enemy_advantage",
                            "breakpoint",
                            "changed_variable",
                            "direct_effect",
                        )
                        if seed.get(key) not in (None, "", [], {})
                    }
                    for dependency in instance.depends_on
                    for seed in reasoning_seeds_by_instance.get(dependency, [])
                    if isinstance(seed, Mapping)
                ][:4]
                common_input = {
                    "run_id": shared.get("run_id", ""),
                    "agent_instance_id": instance.instance_id,
                    "mission_node": instance.mission_node,
                    "specialist_task": to_plain(task),
                    "role_contract": _dynamic_role_contract_handoff(contract, task),
                    "query": str(shared.get("topic", "")),
                    "battlefield_contradiction": {
                        key: open_brief.get(key, "")
                        for key in (
                            "combat_problem_frame",
                            "enemy_target_profile",
                            "battle_phase_and_constraints",
                            "required_direct_military_effects",
                        )
                    },
                    "upstream_reasoning_seeds": upstream_seeds,
                    "open_challenge": (
                        "提出一种会改变交战关系、且不能被普通流程优化替代的直接作战装备；"
                        "若建议维度不成立，请自行换一个更强方向。"
                    ),
                    "isolation_contract": {
                        "raw_other_agent_sessions_visible": False,
                        "may_recruit_child_agent": False,
                    },
                }
            elif instance.archetype == "independent_portfolio_reviewer":
                common_input = {
                    "run_id": shared.get("run_id", ""),
                    "agent_instance_id": instance.instance_id,
                    "mission_node": "S5",
                    "specialist_task": to_plain(task),
                    "query": str(shared.get("topic", "")),
                    "candidate_ledger": {
                        "ledger_id": ledger_snapshot.ledger_id if ledger_snapshot else "",
                        "version": ledger_snapshot.version if ledger_snapshot else 0,
                        "hypotheses": candidate_snapshot,
                        "allowed_hypothesis_ids": sorted(candidate_scope),
                        "handoff_schema": "incremental_portfolio_identity_v1",
                    },
                    "review_contract": (
                        "只判定组合成员的独立性、互补性和直接装备属性；不生成、改写、"
                        "补证、验证、估算成熟度或重新命名候选。"
                    ),
                    "existing_portfolio": [
                        _minimal_portfolio_candidate_handoff(item)
                        for item in (ledger_snapshot.hypotheses if ledger_snapshot else [])
                        if item.hypothesis_id not in candidate_scope
                        and item.hypothesis_id in reviewed_candidate_ids
                    ][:8],
                    "isolation_contract": {
                        "raw_other_agent_sessions_visible": False,
                        "may_recruit_child_agent": False,
                    },
                }
            if instance.mission_node in {"S1", "S2", "S3", "S4"}:
                common_input["equipment_portfolio_contract"] = {
                    "selection_rule": (
                        "候选由本次Codex语义推演产生；数量、装备族、技术方向、创新类别和名称格式均不预设"
                    ),
                    "direct_equipment_definition": (
                        "最终候选必须是能直接接敌并形成打击、毁伤、压制、拦截或拒止战果的具体武器；"
                        "算法、网络和保障只能成为其内部机理、接口或约束"
                    ),
                    "free_divergence_first": True,
                    "counterfactual_examples_available_after_divergence_only": True,
                }
            if instance.mission_node == "S6":
                common_input["s6_release_preflight"] = {
                    "identity_and_scene": (
                        "保持主装备、目标、作用域、直接战果和装备专属流程一致"
                    ),
                    "evidence_boundary": (
                        "已知基线与拟议增量分开；缺少同名公开型号不机械淘汰，也不得虚构成熟度"
                    ),
                    "quality_basis": "军事因果、技术可实现性、证据边界和可证伪性",
                }
            if instance.mission_node == "S6" and baseline_boundaries:
                common_input["baseline_availability_boundaries"] = list(
                    baseline_boundaries
                )
                common_input["baseline_boundary_rule"] = (
                    "缺失基线不是候选失败条件，也不得用通用型号目录事后补齐。"
                    "S5合并完整候选账本后记录仍未闭合的成熟度、成本产能和现役差距；"
                    "无法公开确认的内容标为待验证，不得伪造证据或机械淘汰候选。"
                )
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                await refresh_winning_angle_assignments()
                dimension_assignment = dict(
                    winning_angle_assignments.get(instance.instance_id, {})
                )
                diversity_pool: list[dict[str, str]] = []
                own_id = str(dimension_assignment.get("assignment_id", ""))
                for item in [
                    dimension_assignment,
                    *[
                        candidate
                        for candidate in winning_angle_assignments.values()
                        if str(candidate.get("assignment_id", "")) != own_id
                    ],
                ]:
                    compact_item = {
                        "optional_lens": str(item.get("combat_dimension", "")).strip(),
                        "open_relationship": str(
                            item.get("changed_confrontation_variable", "")
                        ).strip(),
                        "possible_result": str(
                            item.get("direct_military_result", "")
                        ).strip(),
                    }
                    if any(compact_item.values()):
                        diversity_pool.append(compact_item)
                common_input["optional_diversity_pool"] = diversity_pool[:6]
                common_input["diversity_pool_authority"] = (
                    "advisory_only；先独立理解Query，可跨项组合、重构、全部舍弃或自创方向；"
                    "不得将任一项视为本Agent的固定维度、答案或排他分工"
                )
            if instance.mission_node in {"S1", "S2"} and not instance.hypothesis_id:
                output_schema = {
                    "reasoning_seeds": [
                        {
                            "combat_problem": "the decisive battlefield contradiction",
                            "enemy_advantage": "why the opponent currently controls it",
                            "breakpoint": "the exploitable task-chain breakpoint",
                            "changed_variable": "the relationship worth changing",
                            "direct_effect": "the desired direct battlefield result",
                        }
                    ],
                    "stop_reason": "string",
                }
                instruction = (
                    "这是轻型创造前置会话，只从Query提炼2至4个彼此不同、能打开新武器思路的"
                    "战场矛盾。每条只写战场问题、对手或现行范式为何占优、可改变的关系、期望直接"
                    "战果和一句开放挑战；不要命名装备，不要写证据、TRL、成本、验证、反适应、失败"
                    "边界或审计字段。"
                    + (
                        "S1重点从对手体系的依赖、感知/决策/火力闭环和其最难被剥夺的优势反推破局关系，"
                        "避免把解决方案写成装备。"
                        if instance.mission_node == "S1"
                        else "S2重点从我方任务组织、时序、效应窗口和资源交换关系中找出传统流程无法解决的矛盾，"
                        "避免复述S1的对手底图。"
                    )
                )
                phase = "winning_swarm_dynamic_reasoning_seed"
            elif instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                output_schema: dict[str, Any] = {
                    "hypotheses": [
                        {
                            "title": "string",
                            "equipment_form": "具体主装备形态",
                            "primary_equipment_identity": "唯一主装备及平台/弹体边界",
                            "target_and_direct_effect": "目标、阶段与直接战果",
                            "unique_operational_role": "不可被其他候选替代的作战角色",
                            "changed_confrontation_variable": "改变的战场关系",
                            "frontier_principle": "装备本体采用的关键新原理",
                            "disruptive_shift": "由此形成的新制胜关系",
                            "mechanism_chain": ["string"],
                            "direct_military_effects": ["string"],
                        }
                    ],
                    "stop_reason": "string",
                }
                # The schema and governed inputs retain all audit constraints.
                # Use a compact creative brief for the actual Codex call so the
                # model reasons about the weapon instead of imitating a rule list.
                instruction = _creative_s3_candidate_instruction()
                instruction += (
                    "只输出1至2张最小候选卡。先从Query矛盾自由推演，并把optional_diversity_pool"
                    "仅作为可全部舍弃的反事实启发，不按其中任一维度填题。"
                    "再一次性完成自然命名与完整装备身份；S3与S4权限相同。每卡只写装备形态、"
                    "目标与直接战果、独特作战角色、改变变量、前沿原理、颠覆关系和短机理链。"
                    "禁止输出证据ID、证据边界、TRL、成本、产能、验证计划、反适应、失败边界、"
                    "工程瓶颈、技术期限、系统接口或任何审计/交接字段；不得生成组合装备或事后改名。"
                )
                instruction += (
                    "S3和S4没有偏向差别、先后关系或物化分工；二者都是完整Query驱动的开放创新武器作者。"
                )
                phase = "winning_swarm_dynamic_seed"
            else:
                output_schema = {
                    "decisions": [
                        {
                            "hypothesis_id": "exact candidate id",
                            "decision": "retain|merge|reject",
                            "merge_target_hypothesis_id": "exact id when merge, otherwise empty",
                            "reason": "one concise semantic reason",
                            "independent_axis": "target|breakpoint|changed_variable|core_mechanism|direct_result",
                            "direct_equipment": "boolean",
                        }
                    ],
                    "portfolio_order": ["exact candidate ids"],
                    "portfolio_summary": "one short combination summary",
                    "stop_reason": "string",
                }
                instruction = (
                    "你是S5独立组合装备评审。只比较候选的目标、任务链断点、改变变量、核心机理和"
                    "直接战果，判断retain、merge或reject；确认它是否是具体直接作战装备、是否与组合中"
                    "其他候选独立或互补。不得生成新候选，不得改写候选正文，不得重新命名；名称不一致只能"
                    "判reject并说明语义冲突。不要输出或补写证据、TRL、成本、产能、验证、反适应、失败"
                    "边界、接口或画像字段。候选一旦完成即可审查，输入可能只是新增/受影响的小批候选。"
                )
                if instance.archetype != "independent_portfolio_reviewer":
                    raise RuntimeError(
                        "dynamic-v2 S5 only permits the independent portfolio reviewer"
                    )
                phase = "winning_swarm_dynamic_portfolio_review_fast"
            emit_swarm_event(
                "winning_agent_session_started",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                mission_node=instance.mission_node,
                batch=batch_index,
                candidate_handoff_count=len(candidate_snapshot),
                candidate_handoff_chars=candidate_handoff_chars,
                evidence_handoff_count=len(compact_evidence_index),
                evidence_handoff_chars=evidence_handoff_chars,
                handoff_total_chars=(candidate_handoff_chars + evidence_handoff_chars),
                handoff_schema=(
                    "portfolio_decision_spine_v2"
                    if instance.archetype == "independent_portfolio_reviewer"
                    else "compact_decision_spine_v1"
                ),
                **runtime_contract,
            )
            started_at = monotonic()
            text = await host._run_core_json(
                runtime_agent_id,
                "你是动态孵化制胜机理集群中的一次性受治理Agent。"
                + task.purpose
                + instruction
                + "输入中的role_contract只界定本节点权限、禁止事项和交接责任，不是逐条写作模板。"
                "请在权限内自主推演、比较并取舍；输出遵循JSON schema。不得招募子Agent、扩大权限、"
                "读取其他Agent原始会话或虚构精确指标。只输出严格JSON。",
                common_input,
                output_schema,
                task.max_output_tokens,
                phase=phase,
            )
            result = _parse_json_object(text)
            if not result:
                raise ValueError(f"{instance.instance_id} returned invalid JSON")
            if instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                raw_hypotheses = result.get("hypotheses", [])
                emit_swarm_event(
                    "winning_s3_first_pass_self_admission_completed",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    winning_angle_id=str(
                        winning_angle_assignments.get(instance.instance_id, {}).get(
                            "assignment_id", ""
                        )
                    ),
                    candidate_count=(
                        len(raw_hypotheses)
                        if isinstance(raw_hypotheses, list)
                        else 0
                    ),
                    separate_precommit_model_call=False,
                    rule=(
                        "候选生成、单一主装备闭合与自然命名在同一次S3/S4会话完成；语义准入交给S5"
                    ),
                )
            emit_swarm_event(
                "winning_agent_session_completed",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                mission_node=instance.mission_node,
                batch=batch_index,
                elapsed_seconds=round(monotonic() - started_at, 3),
                **runtime_contract,
            )
            return (
                instance,
                result,
                (ledger_snapshot.version if ledger_snapshot is not None else 0),
            )

        def refresh_candidate_ledger() -> dict[str, str]:
            """Publish newly completed seed branches without a global barrier."""

            nonlocal ledger
            candidates_by_id = {
                item.hypothesis_id: item
                for item in hypotheses
                if item.hypothesis_id not in portfolio_rejected_ids
                and canonical_candidate_id(item.hypothesis_id) == item.hypothesis_id
            }
            if ledger is not None:
                # Preserve already merged S4-S6 fields when a slower S3
                # branch publishes an additional candidate.
                candidates_by_id.update(
                    {item.hypothesis_id: item for item in ledger.hypotheses}
                )
            # Do not perform local lexical or score-based admission before S5.
            # Producer IDs are already unique; S5 owns semantic merge/reject
            # decisions against the complete portfolio.
            unique = list(candidates_by_id.values())
            semantic_merges: list[dict[str, Any]] = []
            # Keep all bounded seed branches while downstream work is in
            # flight.  Early score/id truncation invalidated already-issued
            # candidate scopes and produced unknown_hypothesis_id rejects.
            unique = list(unique)
            id_remap = {
                str(item["source_hypothesis_id"]): str(item["target_hypothesis_id"])
                for item in semantic_merges
            }
            for source_id, target_id in id_remap.items():
                candidate_id_aliases[source_id] = canonical_candidate_id(target_id)
            for source_id in list(candidate_id_aliases):
                candidate_id_aliases[source_id] = canonical_candidate_id(
                    candidate_id_aliases[source_id]
                )
            for instance_id, scoped_ids in list(instance_hypothesis_ids.items()):
                instance_hypothesis_ids[instance_id] = {
                    canonical_candidate_id(item) for item in scoped_ids
                }
            swarm_merges.extend(semantic_merges)
            swarm_hypotheses.update({item.hypothesis_id: item for item in unique})
            if ledger is None:
                ledger = swarm_controller.create_ledger(unique)
            elif {item.hypothesis_id for item in ledger.hypotheses} != {
                item.hypothesis_id for item in unique
            }:
                ledger = HypothesisLedgerVersion(
                    ledger_id=ledger.ledger_id,
                    version=ledger.version + 1,
                    parent_version=ledger.version,
                    hypotheses=unique,
                    merge_receipts=list(ledger.merge_receipts),
                    change_summary="candidate_branch_published",
                    created_by="winning_swarm_controller",
                )
            emit_swarm_event(
                "winning_candidate_ledger_frozen",
                graph_id=graph.graph_id,
                ledger_id=ledger.ledger_id,
                ledger_version=ledger.version,
                candidate_count=len(unique),
                incremental=True,
            )
            return id_remap

        def compact_candidate_ledger_for_review() -> None:
            """Plan a bounded legacy review scope without deleting candidates.

            Dynamic-v2 bypasses this compatibility helper because incremental
            S5 scope is driven by newly completed candidate ids.
            """

            nonlocal initial_expert_review_scope
            if str(swarm_controller.policy.get("policy_id")) == "winning_swarm_dynamic_v2":
                # Dynamic S5 reviews only the candidate ids delivered in each
                # completion-driven batch; never pre-trim the ledger with an
                # expert-pool quota.
                initial_expert_review_scope = None
                return
            pool_maximum = int(
                swarm_controller.policy.get("expert_candidate_pool_maximum", 8)
            )
            if ledger is None:
                return
            if len(ledger.hypotheses) <= pool_maximum:
                initial_expert_review_scope = None
                return
            retained = swarm_controller.retain_diverse_candidates(
                ledger.hypotheses,
                maximum=pool_maximum,
            )
            initial_expert_review_scope = {item.hypothesis_id for item in retained}
            emit_swarm_event(
                "winning_candidate_review_scope_planned",
                graph_id=graph.graph_id,
                ledger_id=ledger.ledger_id,
                ledger_version=ledger.version,
                complete_candidate_count=len(ledger.hypotheses),
                review_candidate_count=len(retained),
                review_candidate_ids=sorted(initial_expert_review_scope),
                rule=("评审容量只限制本轮Codex输入，不删除完整候选账本"),
            )

        async def semantic_cluster_candidate_ledger(
            *,
            scope_id: str,
            changed_hypothesis_ids: set[str] | None = None,
        ) -> dict[str, str]:
            """Publish the isolated Codex five-axis clustering decision."""

            nonlocal ledger, semantic_clustered_ledger_version
            if ledger is None or ledger.version == semantic_clustered_ledger_version:
                return {}
            (
                clustered,
                semantic_merges,
            ) = await cluster_hypotheses_with_independent_codex(
                ledger.hypotheses,
                scope_id=scope_id,
                changed_hypothesis_ids=changed_hypothesis_ids,
            )
            id_remap = {
                str(item["source_hypothesis_id"]): str(item["target_hypothesis_id"])
                for item in semantic_merges
            }
            for source_id, target_id in id_remap.items():
                candidate_id_aliases[source_id] = canonical_candidate_id(target_id)
            for source_id in list(candidate_id_aliases):
                candidate_id_aliases[source_id] = canonical_candidate_id(
                    candidate_id_aliases[source_id]
                )
            for instance_id, scoped_ids in list(instance_hypothesis_ids.items()):
                instance_hypothesis_ids[instance_id] = {
                    canonical_candidate_id(item) for item in scoped_ids
                }
            known_merge_keys = {
                (
                    item.get("source_hypothesis_id", ""),
                    item.get("target_hypothesis_id", ""),
                    item.get("reason", ""),
                )
                for item in swarm_merges
            }
            for item in semantic_merges:
                merge_key = (
                    item.get("source_hypothesis_id", ""),
                    item.get("target_hypothesis_id", ""),
                    item.get("reason", ""),
                )
                if merge_key not in known_merge_keys:
                    swarm_merges.append(item)
                    known_merge_keys.add(merge_key)
                    emit_swarm_event("hypothesis_merged", **item)
            if {item.hypothesis_id for item in clustered} != {
                item.hypothesis_id for item in ledger.hypotheses
            }:
                ledger = HypothesisLedgerVersion(
                    ledger_id=ledger.ledger_id,
                    version=ledger.version + 1,
                    parent_version=ledger.version,
                    hypotheses=clustered,
                    merge_receipts=list(ledger.merge_receipts),
                    change_summary="independent_codex_five_axis_clustering",
                    created_by="winning_semantic_clusterer",
                )
                emit_swarm_event(
                    "winning_candidate_ledger_frozen",
                    graph_id=graph.graph_id,
                    ledger_id=ledger.ledger_id,
                    ledger_version=ledger.version,
                    candidate_count=len(clustered),
                    incremental=False,
                    compaction_reason="independent_codex_five_axis_clustering",
                )
            semantic_clustered_ledger_version = ledger.version
            return id_remap


        def scope_for_instance(
            item: WinningAgentInstance,
            ledger_snapshot: HypothesisLedgerVersion | None,
        ) -> set[str]:
            if item.instance_id in review_targets_by_instance:
                return {
                    canonical_candidate_id(value)
                    for value in review_targets_by_instance[item.instance_id]
                }
            if item.hypothesis_id:
                return {canonical_candidate_id(item.hypothesis_id)}
            if (
                item.archetype == "independent_portfolio_reviewer"
                and ledger_snapshot is not None
            ):
                return {
                    hypothesis.hypothesis_id
                    for hypothesis in ledger_snapshot.hypotheses
                }
            return {
                canonical_candidate_id(hypothesis_id)
                for dependency in item.depends_on
                for hypothesis_id in instance_hypothesis_ids.get(dependency, set())
            }

        def ensure_incremental_reviewer_pending() -> None:
            """Schedule one isolated S5 batch without waiting for slow producers."""

            nonlocal graph, incremental_review_sequence
            if not pending_incremental_review_ids:
                return
            reviewer_pending = next(
                (
                    item
                    for item in pending.values()
                    if item.archetype == "independent_portfolio_reviewer"
                ),
                None,
            )
            if reviewer_pending is not None:
                review_targets_by_instance.setdefault(
                    reviewer_pending.instance_id, set()
                ).update(pending_incremental_review_ids)
                pending_incremental_review_ids.clear()
                return
            if any(
                item.archetype == "independent_portfolio_reviewer"
                for item, _, _ in running_instances.values()
            ):
                return
            template = next(
                (
                    item
                    for item in graph.agent_instances
                    if item.archetype == "independent_portfolio_reviewer"
                ),
                None,
            )
            if template is None:
                return
            incremental_review_sequence += 1
            reviewer = replace(
                template,
                instance_id=(
                    f"{template.instance_id}-incremental-{incremental_review_sequence:02d}"
                ),
                depends_on=[],
                wave=max(1, template.wave),
                trigger_residuals=["incremental_candidate_available"],
            )
            pending[reviewer.instance_id] = reviewer
            review_targets_by_instance[reviewer.instance_id] = set(
                pending_incremental_review_ids
            )
            pending_incremental_review_ids.clear()
            graph = replace(
                graph,
                agent_instances=[*graph.agent_instances, reviewer],
                dependencies={**graph.dependencies, reviewer.instance_id: []},
                s_node_seeds={
                    **graph.s_node_seeds,
                    "S5": [
                        *graph.s_node_seeds.get("S5", []),
                        reviewer.instance_id,
                    ],
                },
                maximum_instances=max(
                    graph.maximum_instances, len(graph.agent_instances) + 1
                ),
            )
            emit_swarm_event(
                "winning_incremental_portfolio_review_scheduled",
                actor=reviewer.instance_id,
                graph_id=graph.graph_id,
                candidate_ids=sorted(review_targets_by_instance[reviewer.instance_id]),
                rule="candidate_completion_driven_without_wave_barrier",
            )

        def merge_lock_keys(
            item: WinningAgentInstance,
            candidate_scope: set[str],
        ) -> set[tuple[str, str]]:
            # S1-S3 seed roles read inherited branches for context but
            # publish new hypotheses. Locking their read scope serialized
            # the quality-critical S3 equipment generators even though
            # they never write the same candidate ids.
            if item.mission_node in {"S1", "S2", "S3", "S4"} and not item.hypothesis_id:
                return set()
            return {
                (hypothesis_id, item.merge_target) for hypothesis_id in candidate_scope
            }


        emit_swarm_event(
            "winning_mission_graph_planned",
            graph=to_plain(graph),
            graph_id=graph.graph_id,
            task_count=len(graph.agent_instances),
            maximum_concurrency=graph.maximum_concurrency,
            minimum_instances=graph.minimum_instances,
            maximum_instances=graph.maximum_instances,
        )
        batch_index = 0
        while pending or running_instances:
            s1_s2_finished = all(
                item.instance_id in completed_instances | failed_instances
                for item in graph.agent_instances
                if item.mission_node in {"S1", "S2"} and not item.hypothesis_id
            )
            if (
                s1_s2_finished
                and not s3_active_instances_materialized
                and any(
                    item.mission_node in {"S3", "S4"} and not item.hypothesis_id
                    for item in pending.values()
                )
            ):
                await materialize_active_s3_instances()
            # No same-wave convergence barrier: each completed S3/S4 branch
            # is published and reviewed incrementally below. Final convergence
            # remains a bounded close-out action after producers drain.
            if (
                ledger is not None
                and not running_instances
                and pending
                and not candidate_competition_converged
                and all(
                    item.archetype == "independent_portfolio_reviewer"
                    for item in pending.values()
                )
            ):
                await semantic_cluster_candidate_ledger(
                    scope_id=f"{graph.graph_id}:pre-portfolio-reviewer"
                )
                compact_candidate_ledger_for_review()
            ready = sorted(
                (
                    item
                    for item in pending.values()
                    if all(dep in completed_instances for dep in item.depends_on)
                    and (
                        item.mission_node not in {"S3", "S4"}
                        or all(
                            seed_instance.instance_id
                            in completed_instances | failed_instances
                            for seed_instance in graph.agent_instances
                            if seed_instance.mission_node in {"S1", "S2"}
                            and not seed_instance.hypothesis_id
                        )
                    )
                    and (
                        item.mission_node not in {"S5", "S6"}
                        or ledger is not None
                        and bool(ledger.hypotheses)
                    )
                    and (
                        item.archetype != "independent_portfolio_reviewer"
                        or ledger is not None and bool(ledger.hypotheses)
                    )
                ),
                key=lambda item: (
                    item.wave,
                    -item.expected_quality_gain,
                    item.instance_id,
                ),
            )
            available_slots = max(0, graph.maximum_concurrency - len(running_instances))
            if not ready and not running_instances:
                for item in pending.values():
                    failed_instances.add(item.instance_id)
                    emit_swarm_event(
                        "winning_agent_instance_cancelled",
                        actor=item.instance_id,
                        graph_id=graph.graph_id,
                        reason="unsatisfied_dependency",
                    )
                break
            running_merge_keys = {
                merge_key
                for running_item, running_scope, _ in running_instances.values()
                for merge_key in merge_lock_keys(running_item, running_scope)
            }
            selected: list[WinningAgentInstance] = []
            selected_merge_keys: set[tuple[str, str]] = set()
            for item in ready:
                item_scope = scope_for_instance(item, ledger)
                item_keys = merge_lock_keys(item, item_scope)
                if item_keys & (running_merge_keys | selected_merge_keys):
                    continue
                selected.append(item)
                selected_merge_keys.update(item_keys)
                if len(selected) >= available_slots:
                    break
            if selected:
                batch_index += 1
                snapshot = ledger
                execution_batches.append(
                    {
                        "batch": batch_index,
                        "instance_ids": [item.instance_id for item in selected],
                        "mission_nodes": [item.mission_node for item in selected],
                        "base_ledger_version": snapshot.version if snapshot else 0,
                    }
                )
                for item in selected:
                    pending.pop(item.instance_id, None)
                    inherited_scope = scope_for_instance(item, snapshot)
                    call = asyncio.create_task(
                        call_instance(
                            item,
                            ledger_snapshot=snapshot,
                            batch_index=batch_index,
                            candidate_scope=inherited_scope,
                        )
                    )
                    running_instances[call] = (item, inherited_scope, batch_index)
                    running_started_at[call] = monotonic()
                maximum_observed_concurrency = max(
                    maximum_observed_concurrency, len(running_instances)
                )
            if not running_instances:
                continue
            # Do not wait forever without a durable event.  This is an
            # observability interval, not a timeout: the task remains
            # alive and is never cancelled or failed because it exceeded
            # the interval.  Its model-progress callback continues to
            # refresh the Worker lease while Codex is thinking.
            done, _ = await asyncio.wait(
                set(running_instances),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=max(
                    10.0,
                    float(
                        os.environ.get(
                            "EQUIPMENT_DR_SWARM_WAIT_HEARTBEAT_SECONDS",
                            "30",
                        )
                    ),
                ),
            )
            if not done:
                now = monotonic()
                emit_swarm_event(
                    "winning_agent_waiting",
                    actor="winning_swarm_controller",
                    graph_id=graph.graph_id,
                    running_instances=[
                        {
                            "agent_instance_id": item.instance_id,
                            "mission_node": item.mission_node,
                            "archetype": item.archetype,
                            "batch": batch,
                            "elapsed_seconds": round(
                                now - running_started_at.get(task, now), 1
                            ),
                        }
                        for task, (item, _scope, batch) in running_instances.items()
                    ],
                    note="模型会话仍在执行；仅写入进度，不触发超时失败或取消",
                )
                continue
            for completed_call in done:
                instance, candidate_scope, instance_batch = running_instances.pop(
                    completed_call
                )
                running_started_at.pop(completed_call, None)
                try:
                    outcome: object = completed_call.result()
                except BaseException as exc:  # soft-isolate one role instance
                    outcome = exc
                # A failed competing instance is a soft failure: downstream
                # roles may still use the surviving branches.
                completed_instances.add(instance.instance_id)
                instance_hypothesis_ids[instance.instance_id] = set(candidate_scope)
                if isinstance(outcome, BaseException):
                    retry_count = dynamic_instance_retry_counts.get(
                        instance.instance_id, 0
                    )
                    if retry_count < 1:
                        dynamic_instance_retry_counts[instance.instance_id] = (
                            retry_count + 1
                        )
                        completed_instances.discard(instance.instance_id)
                        pending[instance.instance_id] = instance
                        emit_swarm_event(
                            "winning_agent_instance_retry_scheduled",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            mission_node=instance.mission_node,
                            retry_number=retry_count + 1,
                            failure_type=type(outcome).__name__,
                            error_message=str(outcome)[:500],
                        )
                        continue
                    failed_instances.add(instance.instance_id)
                    completed_instances.add(instance.instance_id)
                    emit_swarm_event(
                        "winning_agent_instance_failed",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        failure_type=type(outcome).__name__,
                        error_message=str(outcome)[:500],
                        retry_count=retry_count,
                    )
                    continue
                _, result, base_version = outcome
                runs.append(
                    {
                        "step": int(instance.mission_node[1:]),
                        "agent_id": instance.instance_id,
                        "template_agent_id": f"winning_swarm_{instance.archetype}",
                        "middle_cycle": 1,
                        "execution_mode": "dynamic_mission_graph",
                        "wave": instance.wave,
                        "batch": instance_batch,
                        "merge_target": instance.merge_target,
                        "status": "completed",
                    }
                )
                if instance.mission_node in {"S1", "S2"} and not instance.hypothesis_id:
                    raw_reasoning_seeds = result.get("reasoning_seeds", [])
                    if not isinstance(raw_reasoning_seeds, list):
                        raw_reasoning_seeds = []
                    reasoning_seeds_by_instance[instance.instance_id] = [
                        dict(item)
                        for item in raw_reasoning_seeds
                        if isinstance(item, Mapping)
                    ][:8]
                    instance_hypothesis_ids[instance.instance_id] = set()
                    emit_swarm_event(
                        "winning_reasoning_seed_published",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        mission_node=instance.mission_node,
                        seed_count=len(
                            reasoning_seeds_by_instance[instance.instance_id]
                        ),
                    )
                elif instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                    task = task_for_instance(instance)
                    raw_rows = result.get("hypotheses", [])
                    if not isinstance(raw_rows, list):
                        raw_rows = []
                    if instance.archetype in {
                        "direct_combat_equipment_generator",
                        "remote_precision_munition_generator",
                        "mass_scalable_combat_family_generator",
                    }:
                        # A weak/empty Codex result must remain visible and
                        # trigger another governed reasoning pass.  Do not
                        # synthesize familiar weapon cards locally from the
                        # evidence index: that was the main source of the
                        # repeated, mechanically assembled candidate board.
                        added_count = 0
                        emit_swarm_event(
                            "winning_specialized_seed_authored"
                            if raw_rows
                            else "winning_specialized_seed_empty",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            archetype=instance.archetype,
                            recovered_count=added_count,
                            candidate_count=len(raw_rows),
                            stop_reason=str(result.get("stop_reason", ""))[:300],
                            quality_residuals=[
                                str(item)[:240]
                                for item in result.get("quality_residuals", [])
                                if str(item).strip()
                            ][:4],
                        )
                    produced_ids: set[str] = set()
                    for ordinal, raw in enumerate(raw_rows[:6], start=1):
                        if not isinstance(raw, Mapping):
                            continue
                        candidate = swarm_controller.hypothesis_from_mapping(
                            raw,
                            task=task,
                            valid_evidence_ids=set(valid_reference_ids),
                            ordinal=ordinal,
                        )
                        admission = swarm_controller.evaluate_gate(
                            candidate, stage="targeted"
                        )
                        # Local gates are diagnostic only for creative S3/S4
                        # output. S5 owns semantic admission, merge and reject
                        # decisions using the complete Query and portfolio.
                        if admission.residuals:
                            emit_swarm_event(
                                "winning_candidate_pre_s5_residual_recorded",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                hypothesis_id=candidate.hypothesis_id,
                                mission_node=instance.mission_node,
                                residuals=admission.residuals,
                                blocking=False,
                            )
                        hypotheses.append(candidate)
                        produced_ids.add(candidate.hypothesis_id)
                        emit_swarm_event(
                            "winning_candidate_branch_created",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            hypothesis_id=candidate.hypothesis_id,
                            mission_node=instance.mission_node,
                            score=candidate.score,
                            title=candidate.title,
                            equipment_form=list(candidate.equipment_forms[:2]),
                            primary_equipment_identity=(
                                str(raw.get("primary_equipment_identity", "")).strip()
                                or str(raw.get("equipment_form", "")).strip()
                                or "；".join(candidate.equipment_forms[:2])
                            ),
                            naming_rationale=str(
                                raw.get("naming_rationale", "")
                            ).strip(),
                            naming_owner="s3_s4_codex",
                        )
                    id_remap = refresh_candidate_ledger()
                    resolved_ids = {
                        id_remap.get(hypothesis_id, hypothesis_id)
                        for hypothesis_id in produced_ids
                    }
                    known_ledger_ids = {
                        item.hypothesis_id for item in ledger.hypotheses
                    }
                    instance_hypothesis_ids[instance.instance_id] = {
                        hypothesis_id
                        for hypothesis_id in resolved_ids
                        if hypothesis_id in known_ledger_ids
                    } or set(candidate_scope)
                    incremental_ids = set(
                        instance_hypothesis_ids[instance.instance_id]
                    )
                    if incremental_ids:
                        semantic_remap = await semantic_cluster_candidate_ledger(
                            scope_id=(
                                f"{graph.graph_id}:incremental:"
                                f"{instance.instance_id}:{instance_batch}"
                            ),
                            changed_hypothesis_ids=incremental_ids,
                        )
                        incremental_ids = {
                            canonical_candidate_id(
                                semantic_remap.get(hypothesis_id, hypothesis_id)
                            )
                            for hypothesis_id in incremental_ids
                        }
                        known_incremental_ids = {
                            item.hypothesis_id for item in ledger.hypotheses
                        }
                        incremental_ids &= known_incremental_ids
                        instance_hypothesis_ids[instance.instance_id] = set(
                            incremental_ids
                        )
                        pending_incremental_review_ids.update(
                            incremental_ids - reviewed_candidate_ids
                        )
                        ensure_incremental_reviewer_pending()
                else:
                    if ledger is None:
                        continue
                    if instance.archetype == "independent_portfolio_reviewer":
                        raw_decisions = result.get("decisions", [])
                        if not isinstance(raw_decisions, list):
                            raw_decisions = []
                        known_ids = {
                            item.hypothesis_id for item in ledger.hypotheses
                        }
                        retained_ids = set(known_ids)
                        reviewed_now: set[str] = set()
                        for raw in raw_decisions:
                            if not isinstance(raw, Mapping):
                                continue
                            source_id = canonical_candidate_id(
                                str(raw.get("hypothesis_id", ""))
                            )
                            if source_id not in known_ids or (
                                candidate_scope and source_id not in candidate_scope
                            ):
                                continue
                            decision = str(raw.get("decision", "")).strip().lower()
                            target_id = canonical_candidate_id(
                                str(raw.get("merge_target_hypothesis_id", ""))
                            )
                            reviewed_now.add(source_id)
                            if decision == "merge" and (
                                target_id in known_ids and target_id != source_id
                            ):
                                candidate_id_aliases[source_id] = target_id
                                retained_ids.discard(source_id)
                                merge_row = {
                                    "source_hypothesis_id": source_id,
                                    "target_hypothesis_id": target_id,
                                    "reason": "incremental_s5_portfolio_merge",
                                }
                                swarm_merges.append(merge_row)
                                emit_swarm_event("hypothesis_merged", **merge_row)
                            elif decision == "reject":
                                retained_ids.discard(source_id)
                                portfolio_rejected_ids.add(source_id)
                                swarm_rejections.append(
                                    {
                                        "hypothesis_id": source_id,
                                        "reason": str(raw.get("reason", ""))[:500],
                                        "stage": "incremental_s5_portfolio_review",
                                    }
                                )
                            elif decision != "retain":
                                continue
                            emit_swarm_event(
                                "winning_incremental_portfolio_decision",
                                actor=instance.instance_id,
                                graph_id=graph.graph_id,
                                hypothesis_id=source_id,
                                decision=decision,
                                merge_target_hypothesis_id=(
                                    target_id if decision == "merge" else ""
                                ),
                                reason=str(raw.get("reason", ""))[:500],
                                independent_axis=str(
                                    raw.get("independent_axis", "")
                                )[:120],
                                direct_equipment=bool(
                                    raw.get("direct_equipment", False)
                                ),
                            )
                        if retained_ids != known_ids:
                            ledger = HypothesisLedgerVersion(
                                ledger_id=ledger.ledger_id,
                                version=ledger.version + 1,
                                parent_version=ledger.version,
                                hypotheses=[
                                    item
                                    for item in ledger.hypotheses
                                    if item.hypothesis_id in retained_ids
                                ],
                                merge_receipts=list(ledger.merge_receipts),
                                change_summary="incremental_s5_portfolio_decision",
                                created_by=instance.instance_id,
                            )
                        # S5 changed only portfolio disposition, not candidate
                        # semantics. Mark this version clustered so close-out
                        # does not perform a redundant second clustering call.
                        semantic_clustered_ledger_version = ledger.version
                        reviewed_candidate_ids.update(reviewed_now)
                        pending_incremental_review_ids.difference_update(reviewed_now)
                        review_targets_by_instance.pop(instance.instance_id, None)
                        emit_swarm_event(
                            "winning_incremental_portfolio_review_completed",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            reviewed_candidate_ids=sorted(reviewed_now),
                            remaining_candidate_ids=sorted(
                                pending_incremental_review_ids
                            ),
                            portfolio_order=[
                                str(value)
                                for value in result.get("portfolio_order", [])
                                if str(value).strip()
                            ],
                            portfolio_summary=str(
                                result.get("portfolio_summary", "")
                            )[:500],
                        )
                        ensure_incremental_reviewer_pending()
                        continue
                    raw_contributions = result.get("contributions", [])
                    if isinstance(raw_contributions, Mapping):
                        raw_contributions = [raw_contributions]
                    if not isinstance(raw_contributions, list):
                        raw_contributions = []
                    known_ids = {item.hypothesis_id for item in ledger.hypotheses}
                    for ordinal, raw in enumerate(raw_contributions[:8], start=1):
                        if not isinstance(raw, Mapping):
                            continue
                        reported_hypothesis_id = str(raw.get("hypothesis_id", ""))
                        hypothesis_id = canonical_candidate_id(reported_hypothesis_id)
                        if hypothesis_id not in known_ids:
                            obsolete_candidate = next(
                                (
                                    item
                                    for item in hypotheses
                                    if item.hypothesis_id == reported_hypothesis_id
                                ),
                                None,
                            )
                            if obsolete_candidate is not None:
                                semantic_target = (
                                    swarm_controller.semantic_hypothesis_match(
                                        obsolete_candidate,
                                        ledger.hypotheses,
                                    )
                                )
                                if semantic_target:
                                    candidate_id_aliases[reported_hypothesis_id] = (
                                        semantic_target
                                    )
                                    hypothesis_id = semantic_target
                        if hypothesis_id != reported_hypothesis_id:
                            emit_swarm_event(
                                "winning_contribution_hypothesis_remapped",
                                actor=instance.instance_id,
                                reported_hypothesis_id=reported_hypothesis_id,
                                hypothesis_id=hypothesis_id,
                            )
                        if hypothesis_id not in known_ids:
                            emit_swarm_event(
                                "winning_contribution_rejected",
                                actor=instance.instance_id,
                                reason="unknown_hypothesis_id",
                                hypothesis_id=hypothesis_id,
                            )
                            continue
                        if (
                            instance.mission_node != "S6"
                            and candidate_scope
                            and hypothesis_id not in candidate_scope
                        ):
                            emit_swarm_event(
                                "winning_contribution_rejected",
                                actor=instance.instance_id,
                                reason="crossed_candidate_scope",
                                hypothesis_id=hypothesis_id,
                                allowed_hypothesis_ids=sorted(candidate_scope),
                            )
                            continue
                        reported_target = str(
                            raw.get("merge_target") or instance.merge_target
                        )
                        if reported_target != instance.merge_target:
                            emit_swarm_event(
                                "winning_contribution_rejected",
                                actor=instance.instance_id,
                                reason="crossed_merge_target",
                                hypothesis_id=hypothesis_id,
                            )
                            continue
                        try:
                            quality = max(
                                0.0,
                                min(1.0, float(raw.get("incremental_quality", 0.0))),
                            )
                        except (TypeError, ValueError):
                            quality = 0.0
                        recommendation = str(raw.get("recommendation", "retain"))[:80]
                        findings = [
                            str(item)
                            for item in raw.get("findings", [])
                            if str(item).strip()
                        ][:8]
                        evidence_ids = swarm_controller.sanitize_evidence_ids(
                            raw.get("evidence_ids", raw.get("evidence_refs", [])),
                            set(valid_reference_ids),
                        )
                        patch_fields = {
                            key: raw.get(key)
                            for key in (
                                "findings",
                                "mechanism_chain_updates",
                                "direct_military_effects",
                                "equipment_forms",
                                "project_function",
                                "system_interfaces",
                                "novelty_delta",
                                "evidence_boundary",
                                "counterevidence",
                                "adversary_adaptations",
                                "failure_boundaries",
                                "trl_constraints",
                                "cost_constraints",
                                "industrial_constraints",
                                "cross_scenario_results",
                                "validation_plan",
                                "implementation_path",
                            )
                            if raw.get(key) not in (None, "", [], {})
                        }
                        retention = swarm_controller.contribution_retention_assessment(
                            raw,
                            evidence_ids=evidence_ids,
                            reported_quality=quality,
                            mission_node=instance.mission_node,
                        )
                        effective_quality = float(retention["effective_quality"])
                        accepted = bool(retention["accepted"])
                        # S4 fan-out and integrated S5 patches are scheduled
                        # only after their full dependency barrier, and merge
                        # locks guarantee disjoint candidate/target writes.
                        # Sibling completions therefore commute; advance the
                        # local ledger base without replaying a Codex session.
                        merge_base_version = (
                            ledger.version
                            if instance.mission_node in {"S4", "S5"}
                            else base_version
                        )
                        contribution = WinningContribution(
                            contribution_id=(
                                "winning-contribution-"
                                + sha256(
                                    f"{instance.instance_id}:{hypothesis_id}:{ordinal}".encode()
                                ).hexdigest()[:16]
                            ),
                            agent_instance_id=instance.instance_id,
                            role_contract_id=instance.role_contract_id,
                            hypothesis_id=hypothesis_id,
                            merge_target=instance.merge_target,
                            base_ledger_version=merge_base_version,
                            hypothesis_patch=patch_fields,
                            quality_dimensions={
                                "incremental_quality": effective_quality,
                                "reported_incremental_quality": quality,
                                "structured_weapon_delta": (
                                    1.0 if retention["structured_weapon_delta"] else 0.0
                                ),
                            },
                            evidence_ids=evidence_ids,
                            residuals_resolved=[
                                str(item)
                                for item in raw.get("residuals_resolved", [])
                                if str(item).strip()
                            ][:8],
                            incremental_quality=effective_quality,
                            recommendation=recommendation,
                            accepted=accepted,
                        )
                        contribution_rows.append(contribution)
                        emit_swarm_event(
                            "winning_contribution_queued",
                            actor=instance.instance_id,
                            contribution_id=contribution.contribution_id,
                            hypothesis_id=hypothesis_id,
                            merge_target=instance.merge_target,
                            base_ledger_version=base_version,
                        )
                        ledger_after, receipt = swarm_controller.merge_contribution(
                            ledger, contribution
                        )
                        merge_receipts.append(receipt)
                        if receipt.rebase_required:
                            emit_swarm_event(
                                "winning_contribution_rebase_required",
                                actor=instance.instance_id,
                                contribution_id=contribution.contribution_id,
                                from_version=contribution.base_ledger_version,
                                to_version=ledger.version,
                            )
                            contribution = swarm_controller.rebase_contribution(
                                contribution, ledger
                            )
                            ledger_after, receipt = swarm_controller.merge_contribution(
                                ledger, contribution
                            )
                            merge_receipts.append(receipt)
                        ledger = ledger_after
                        emit_swarm_event(
                            "winning_contribution_merged",
                            actor=instance.instance_id,
                            contribution_id=contribution.contribution_id,
                            hypothesis_id=hypothesis_id,
                            merge_target=instance.merge_target,
                            status=receipt.status,
                            resulting_ledger_version=receipt.resulting_ledger_version,
                        )

        if ledger is None:
            ledger = swarm_controller.create_ledger([])
        else:
            if not candidate_competition_converged:
                await semantic_cluster_candidate_ledger(
                    scope_id=f"{graph.graph_id}:pre-portfolio-finalization"
                )
            compact_candidate_ledger_for_review()
        # The dynamic portfolio is the direct result of incremental semantic
        # clustering plus S5 retain/merge/reject decisions. There is no second
        # expert score, evidence/TRL audit, repair wave, or completeness ranker.
        maximum = int(swarm_controller.policy.get("finalist_maximum", 12))
        selected_ids_ordered = [
            item.hypothesis_id for item in ledger.hypotheses
        ][:maximum]
        selected_ids = set(selected_ids_ordered)
        decision = PortfolioDecision(
            decision_id=(
                "portfolio-decision-"
                + sha256(
                    f"{ledger.ledger_id}:{ledger.version}:{'|'.join(selected_ids_ordered)}".encode()
                ).hexdigest()[:16]
            ),
            ledger_id=ledger.ledger_id,
            ledger_version=ledger.version,
            pareto_front=list(selected_ids_ordered),
            selected_hypothesis_ids=list(selected_ids_ordered),
            rejected_hypothesis_ids=[],
            objective_scores={},
            dominance_reasons={},
            expert_assessment_ids=[],
            # Compatibility field on the shared decision model. In dynamic-v2
            # this means only "S5 produced a non-empty portfolio"; no quality
            # judge exists or is invoked.
            quality_judge_passed=bool(selected_ids_ordered),
            status="accepted_by_incremental_s5",
            requires_human_review=False,
        )
        emit_swarm_event(
            "winning_inner_loop_evaluated",
            actor="winning_swarm_independent_portfolio_reviewer",
            graph_id=graph.graph_id,
            loop="inner",
            cycle=1,
            passed=decision.quality_judge_passed,
            candidate_count=len(ledger.hypotheses),
            repaired_count=0,
            issues=[],
        )
        final_hypotheses = [
            item for item in ledger.hypotheses if item.hypothesis_id in selected_ids
        ]
        def capability_direction(
            item: WinningHypothesis,
            position: int,
        ) -> dict[str, Any]:
            equipment_form = _winning_primary_equipment_form(item)
            military_value = "；".join(item.direct_military_effects[:3])
            mechanism = "→".join(item.mechanism_chain[:5])
            project_function = (
                item.project_function or military_value or item.novelty_delta
            )
            card = {
                "hypothesis_id": item.hypothesis_id,
                "name": _winning_portfolio_title(item),
                "source_hypothesis_title": _winning_portfolio_title(item),
                "priority": f"P{position}",
                "type": "new_capability",
                "equipment_form": equipment_form,
                "primary_equipment_identity": equipment_form,
                "unique_operational_role": project_function,
                "target_and_direct_effect": military_value,
                "non_substitutable_difference": item.changed_confrontation_variable,
                "query_relevance": (
                    f"通过改变“{item.changed_confrontation_variable}”，"
                    f"在当前任务链中形成{military_value}。"
                ),
                "concise_winning_summary": (
                    item.reference_overview or item.disruptive_shift or mechanism
                ),
                "mechanism_chain": list(item.mechanism_chain[:5]),
                "frontier_principle": item.frontier_principle,
                "disruptive_shift": item.disruptive_shift,
                "selection_quality_status": "accepted_by_incremental_s5",
                "direct_combat_equipment": True,
            }
            failure_boundary = "；".join(item.failure_boundaries[:2]).strip()
            if failure_boundary:
                card["failure_boundary"] = failure_boundary
            return card

        raw_equipment_portfolio = [
            capability_direction(item, position)
            for position, item in enumerate(final_hypotheses, start=1)
        ]


        # S5 is a portfolio decision only. The previous per-card handoff
        # contract was a second heavy authoring pass that recreated evidence,
        # TRL, indicators and semantic classification. S6 receives the
        # already-frozen candidate spine directly.
        equipment_portfolio: list[dict[str, Any]] = [
            dict(card) for card in raw_equipment_portfolio
        ]
        emit_swarm_event(
            "winning_s5_portfolio_frozen",
            actor="winning_swarm_independent_portfolio_reviewer",
            graph_id=graph.graph_id,
            selected_count=len(equipment_portfolio),
            rejected_count=0,
            status="completed",
            contract_owner="s5_incremental_portfolio_reviewer",
            naming_mutation_allowed=False,
        )
        direct_combat_count = sum(
            bool(item.get("direct_combat_equipment")) for item in equipment_portfolio
        )
        direct_hypotheses = list(final_hypotheses)
        direct_equipment_family_counts = swarm_controller.equipment_family_counts(
            direct_hypotheses
        )
        distinct_direct_equipment_family_count = len(direct_equipment_family_counts)
        complete_handoff_count = sum(
            all(
                (
                    str(item.get("name", "")).strip(),
                    str(item.get("equipment_form", "")).strip(),
                    str(item.get("target_and_direct_effect", "")).strip(),
                    str(item.get("unique_operational_role", "")).strip(),
                    item.get("mechanism_chain"),
                )
            )
            for item in equipment_portfolio
        )
        s6_handoff_gate_passed = complete_handoff_count == len(
            equipment_portfolio
        ) and bool(equipment_portfolio)
        equipment_family_counts = swarm_controller.equipment_family_counts(
            final_hypotheses
        )
        equipment_family_count = len(equipment_family_counts)
        maximum_same_family_count = max(
            equipment_family_counts.values(),
            default=0,
        )
        minimum_family_count = min(3, len(equipment_portfolio))
        maximum_allowed_same_family = max(
            2,
            len(equipment_portfolio) // 2,
        )
        # Five-axis independent Codex clustering has already merged
        # same-thesis and non-independent variants before expert selection.
        # Do not re-open that semantic decision with a local family-name
        # classifier or Chinese token-overlap threshold at the final gate.
        same_family_independence_conflicts: list[dict[str, Any]] = []
        equipment_diversity_passed = True
        preferred_distinct_direct_equipment = int(
            swarm_controller.policy.get(
                "preferred_distinct_direct_equipment",
                5,
            )
        )
        direct_equipment_diversity_passed = True
        direct_combat_main_body_passed = direct_combat_count >= max(
            1, (len(equipment_portfolio) + 1) // 2
        )
        remote_precision_present = any(
            _is_remote_precision_portfolio_direction(item)
            for item in equipment_portfolio
        )
        # Ratios and completeness counters below are diagnostics. They must
        # not turn a model-selected, independently authored portfolio into a
        # failed run. Semantic admission belongs to the Codex review; this
        # layer only records whether there is something concrete to deliver.
        portfolio_quality_gate_passed = bool(equipment_portfolio)
        direct_equipment_diversity_limited = bool(
            not direct_equipment_diversity_passed
            and distinct_direct_equipment_family_count > 0
        )
        diversity_only_warning = bool(
            direct_equipment_diversity_limited
            and direct_combat_main_body_passed
            and s6_handoff_gate_passed
            and equipment_diversity_passed
            and bool(equipment_portfolio)
        )
        dynamic_outputs = [
            {
                "agent_instance_id": item.source_task_ids[-1]
                if item.source_task_ids
                else "winning_mission_graph",
                "hypothesis_id": item.hypothesis_id,
                "display_name": item.title,
                "merge_target": "convergence",
                "accepted": item.hypothesis_id in selected_ids,
                "result": {
                    "findings": [item.title, *item.mechanism_chain[:2]],
                    "evidence_refs": list(item.evidence_ids),
                    "open_questions": list(item.residuals[:2]),
                    "confidence": item.score,
                },
            }
            for item in ledger.hypotheses
        ]
        accumulated["dynamic_subagent_outputs"] = list(dynamic_outputs)

        # Make every S5 disposition explainable to the UI without inventing a
        # second expert judgement or evidence status.
        selected_by_id = {item.hypothesis_id: item for item in final_hypotheses}
        candidate_lineage: list[dict[str, Any]] = []
        for item in ledger.hypotheses:
            row = to_plain(item)
            if item.hypothesis_id in selected_by_id:
                row.update(
                    selection_status="selected",
                    selection_reason_code="retained_by_incremental_s5",
                    selection_reason="经增量语义聚类与S5独立组合评审保留，进入S6并行画像撰写。",
                    s6_eligible=True,
                )
            else:
                row.update(
                    # This lineage board is a research catalogue, not the
                    # delivery gate itself. Non-selected candidates remain
                    # inspectable without a fabricated expert assessment.
                    selection_status="reference",
                    selection_reason_code="not_retained_by_incremental_s5",
                    selection_reason="本轮未由S5保留为独立组合成员，不进入S6画像撰写。",
                    s6_eligible=False,
                )
            candidate_lineage.append(row)
        accumulated["winning_swarm"] = {
            "policy": dict(swarm_controller.policy),
            "mission_graph": to_plain(graph),
            "task_graph": [to_plain(item) for item in graph.agent_instances],
            "role_contracts": [to_plain(item) for item in graph.role_contracts],
            "candidate_lineage": candidate_lineage,
            "hypothesis_ledger": to_plain(ledger),
            "hypotheses": [to_plain(item) for item in ledger.hypotheses],
            "contributions": [to_plain(item) for item in contribution_rows],
            "merge_receipts": [to_plain(item) for item in merge_receipts],
            "portfolio_decision": to_plain(decision),
            "finalists": [to_plain(item) for item in final_hypotheses],
            "final_equipment_portfolio": equipment_portfolio,
            "portfolio_quality_gate": {
                "passed": portfolio_quality_gate_passed,
                "direction_count": len(equipment_portfolio),
                "direct_combat_equipment_count": direct_combat_count,
                "complete_s6_handoff_count": complete_handoff_count,
                "s6_handoff_gate_passed": s6_handoff_gate_passed,
                "equipment_diversity_passed": equipment_diversity_passed,
                "equipment_family_count": equipment_family_count,
                "equipment_family_counts": equipment_family_counts,
                "direct_equipment_family_counts": (direct_equipment_family_counts),
                "distinct_direct_equipment_family_count": (
                    distinct_direct_equipment_family_count
                ),
                "preferred_distinct_direct_equipment": (
                    preferred_distinct_direct_equipment
                ),
                "available_distinct_direct_equipment_family_count": (
                    distinct_direct_equipment_family_count
                ),
                "direct_equipment_diversity_passed": (
                    direct_equipment_diversity_passed
                ),
                "direct_equipment_diversity_limited": (
                    direct_equipment_diversity_limited
                ),
                "direct_equipment_diversity_warning": (
                    "当前保留"
                    f"{distinct_direct_equipment_family_count}个互异直接装备族；"
                    f"未达到优先目标{preferred_distinct_direct_equipment}个，"
                    "仅作为待补强项，不因数量不足淘汰已通过候选"
                    if direct_equipment_diversity_limited
                    else ""
                ),
                "diversity_only_warning": diversity_only_warning,
                "direct_combat_main_body_passed": (direct_combat_main_body_passed),
                "minimum_equipment_family_count": minimum_family_count,
                "maximum_same_family_count": maximum_same_family_count,
                "maximum_allowed_same_family": maximum_allowed_same_family,
                "same_family_minimum_independent_axes": int(
                    swarm_controller.policy.get(
                        "same_family_minimum_independent_axes",
                        2,
                    )
                ),
                "same_family_independence_conflicts": (
                    same_family_independence_conflicts
                ),
                "remote_precision_required": False,
                "remote_precision_present": remote_precision_present,
                "selection_rule": "增量五轴语义聚类与S5独立组合评审决定保留、合并和判退；动态路径不运行旧重型质量评估",
                "s6_card_capacity": int(
                    swarm_controller.policy.get("finalist_maximum", 12)
                ),
                "direct_combat_equipment_must_be_main_body": True,
            },
            "execution_batches": execution_batches,
            "events_version": "winning_swarm_dynamic_v2",
            "budget": {
                "planned_instances": len(graph.agent_instances),
                "completed_instances": len(completed_instances - failed_instances),
                "failed_instances": len(failed_instances),
                "minimum_instances": graph.minimum_instances,
                "maximum_instances": graph.maximum_instances,
                "maximum_concurrency": graph.maximum_concurrency,
                "maximum_observed_concurrency": maximum_observed_concurrency,
            },
            "stop_reason": (
                "mission_graph_complete_with_diversity_warning"
                if portfolio_quality_gate_passed and direct_equipment_diversity_limited
                else (
                    "mission_graph_complete"
                    if portfolio_quality_gate_passed
                    else "mission_graph_limited_no_deliverable_portfolio"
                )
            ),
        }
        emit_swarm_event(
            "winning_portfolio_merge_completed",
            graph_id=graph.graph_id,
            ledger_id=ledger.ledger_id,
            ledger_version=ledger.version,
            selected_hypothesis_ids=decision.selected_hypothesis_ids,
            rejected_hypothesis_ids=decision.rejected_hypothesis_ids,
            final_equipment_portfolio=_compact_equipment_portfolio_event(
                equipment_portfolio
            ),
            portfolio_quality_gate=accumulated["winning_swarm"][
                "portfolio_quality_gate"
            ],
            swarm_summary=_compact_swarm_event_summary(accumulated["winning_swarm"]),
        )

    async def generate_parallel_s6_cards(
        *,
        agent_id: str,
        system: str,
        schema: Mapping[str, Any],
        step_input: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Plan one portfolio, then author its equipment cards in parallel."""

        direction_schema = schema["concept_directions"][0]
        portrait_modules_schema = {
            "overview": (
                "约120至150个中文字的决策概述：传统能力为何在本场景失效、本装备改变的核心关系、"
                "直接战果；完整性优先，不复述技术或流程栏"
            ),
            "technology_implementation": (
                "约120至150个中文字：可复用底座、决定性瓶颈、核心原理如何落实到装备本体、"
                "关键工程约束、样机/半实物/对抗试验和判退结果；不得写成组件清单"
            ),
            "operational_process": (
                "约120至150个中文字的装备专属关键节点链：每个节点自然包含行动主体、进入条件、"
                "关键动作、状态变化和转段条件；突出授权/效应窗口、战果确认和再组织"
            ),
            "capability_effects": (
                "约120至150个中文字：相对基线新增能力、可验证战场结果、由此开发的新任务或新场景；"
                "不复述流程"
            ),
            "winning_logic": (
                "约120至150个中文字：敌方原有优势、传统方案为何失效、改变的成本/时间/暴露/毁伤/"
                "攻防消耗关系，以及迫使对手承担的新防御或组织成本"
            ),
        }
        card_direction_schema = {
            key: direction_schema[key]
            for key in (
                "name",
                "function",
                "military_value",
                "equipment_form",
                "primary_equipment_identity",
                "operational_mechanism",
                "capability_classification",
                "equipment_semantic_assessment",
                "target_scenario",
                "problem_statement",
                "scientific_principle",
                "enabling_technologies",
                "operational_concept",
                "operational_process",
                "semantic_consistency_check",
                "capability_outcome",
                "winning_mechanism",
                "adversary_adaptation",
                "failure_boundary",
                "capability_portrait",
            )
            if key in direction_schema
        }
        card_direction_schema.pop("capability_portrait", None)
        card_direction_schema["capability_portrait_modules"] = portrait_modules_schema
        handoff = step_input.get("capability_synthesis_handoff", {})
        handoff = handoff if isinstance(handoff, Mapping) else {}
        selected_portfolio = handoff.get("selected_equipment_portfolio", [])
        selected_portfolio = (
            [dict(item) for item in selected_portfolio if isinstance(item, Mapping)]
            if isinstance(selected_portfolio, list)
            else []
        )
        # The compact handoff may omit fields that already exist in the
        # authoritative S5 portfolio. Reattach those exact upstream semantics
        # before authoring so a provider failure can preserve the complete
        # candidate rather than degrade into a sparse title-only row.
        authoritative_portfolio_rows: list[dict[str, Any]] = []
        for source in (
            accumulated.get("winning_swarm", {}).get("final_equipment_portfolio", [])
            if isinstance(accumulated.get("winning_swarm", {}), Mapping)
            else [],
            shared.get("prior_winning_analysis", {})
            .get("winning_swarm", {})
            .get("final_equipment_portfolio", [])
            if isinstance(shared.get("prior_winning_analysis", {}), Mapping)
            and isinstance(
                shared.get("prior_winning_analysis", {}).get("winning_swarm", {}),
                Mapping,
            )
            else [],
            shared.get("prior_winning_analysis", {}).get("concept_directions", [])
            if isinstance(shared.get("prior_winning_analysis", {}), Mapping)
            else [],
        ):
            if not isinstance(source, list):
                continue
            authoritative_portfolio_rows.extend(
                dict(item) for item in source if isinstance(item, Mapping)
            )
        authoritative_by_id = {
            str(item.get("hypothesis_id", "")).strip(): item
            for item in authoritative_portfolio_rows
            if str(item.get("hypothesis_id", "")).strip()
        }
        authoritative_by_name = {
            str(item.get("name", "")).strip(): item
            for item in authoritative_portfolio_rows
            if str(item.get("name", "")).strip()
        }
        selected_portfolio = [
            {
                **dict(
                    authoritative_by_id.get(
                        str(item.get("hypothesis_id", "")).strip(),
                        authoritative_by_name.get(
                            str(item.get("name", "")).strip(),
                            {},
                        ),
                    )
                ),
                **item,
            }
            for item in selected_portfolio
        ]
        card_capacity = max(
            1,
            min(12, int(handoff.get("s6_card_capacity", 12) or 12)),
        )
        planner_schema = {
            key: value
            for key, value in schema.items()
            if key not in {"concept_directions", "capability_image_drafts"}
        }
        planner_schema["card_briefs"] = [
            {
                "position": 1,
                "name": "逐字复制S3–S5已冻结的候选装备名称",
                "type": "new_capability|upgrade",
                "primary_equipment_identity": "唯一主装备及平台/弹体/载荷边界",
                "equipment_form": "可独立立项的具体装备形态",
                "unique_operational_role": "该卡在组合中不可由其他卡替代的任务作用",
                "launch_or_release_domain": "方案自身限定的部署、发射或释放域",
                "target_and_direct_effect": "主要敌方目标及直接战果",
                "non_substitutable_difference": (
                    "相对其他卡不可替代的核心物理、接敌或制胜差异；不设数量门槛"
                ),
                "baseline_system": "公开基线或证据不足时的类别级边界",
                "capability_gap": "query下该主装备独有的能力差距",
                "direct_evidence_refs": ["exact evidence_id"],
                "foresight_evidence_status": "direct_object_baseline|analogous_project_evidence|component_mechanism_evidence",
                "evidence_boundary": "公开证据支持与不支持的内容",
                "validation_plan": ["可证伪判退路径，可暂列后续补全"],
                "indicator_portrait": "S5交接锁定的差异化测量轴、对照基线与判退条件",
                "query_relevance": "S5交接锁定的任务对象、作战阶段、威胁压力和直接战果关联",
                "concise_winning_summary": "S5形成的名称下方精简制胜说明；仅作S6补充语境，不参与身份或质量硬门",
            }
        ]
        # The dynamic swarm has already selected these candidates through
        # its independent evidence and portfolio review.  Do not make S6
        # discard them merely to satisfy a fixed card count: turn every
        # selected, independently evidenced weapon into one card brief.
        pre_s6_candidate_names = [
            str(item.get("candidate_equipment", "")).strip()
            for item in handoff.get("equipment_portfolio_preflight", [])
            if isinstance(item, Mapping)
            and item.get("ready") is True
            and str(item.get("candidate_equipment", "")).strip()
        ]
        if selected_portfolio:
            plan = {"portfolio_source": "winning_swarm_selected_candidates"}
            briefs = selected_portfolio[:card_capacity]
        else:
            if not pre_s6_candidate_names:
                plan = {
                    "portfolio_source": "s5_handoff_empty_limited",
                    "s6_card_authoring_limited": True,
                    "s6_card_authoring_warnings": [
                        "S3–S5未传入可写卡装备；S6保留上游结果并受限交付"
                    ],
                }
                briefs = []
            else:
                planner_text = await host._run_core_json(
                    agent_id,
                    system
                    + " 你先只完成S6组合规划，不写完整能力画像。依据query与S5前置合同形成由"
                    "证据闭环和独立作战价值决定数量的装备卡身份蓝图（最多12张）。每张卡锁定唯一"
                    "主装备、发射/释放域、目标、直接战果、公开基线和不可替代差异；实质重复项必须"
                    "合并。不得因凑固定数量而新增或淘汰候选。card_briefs.name只能逐字复制"
                    "locked_pre_s6_candidate_names中的名称，不得创造、清理、压缩、扩写或同义改写。"
                    "card_briefs.position从1连续编号。只输出严格JSON。",
                    {
                        **dict(step_input),
                        "locked_pre_s6_candidate_names": pre_s6_candidate_names,
                    },
                    planner_schema,
                    2400,
                    phase="winning_s6_portfolio_plan",
                )
                plan = _parse_json_object(planner_text)
                briefs = [
                    dict(item)
                    for item in plan.get("card_briefs", [])
                    if isinstance(item, Mapping)
                ][:card_capacity]
                for position, brief in enumerate(briefs):
                    if position < len(pre_s6_candidate_names):
                        brief["name"] = pre_s6_candidate_names[position]
        briefs = [
            _prepare_pre_s6_card_contract(
                brief,
                query=str(step_input.get("query", "")),
            )
            for brief in briefs
        ]
        if not briefs:
            limited_result = {
                key: [] if isinstance(value, list) else ""
                for key, value in schema.items()
            }
            limited_result["concept_directions"] = []
            limited_result["capability_image_drafts"] = []
            limited_result["s6_card_authoring_limited"] = True
            limited_result["s6_card_authoring_warnings"] = list(
                plan.get("s6_card_authoring_warnings", [])
            ) or ["S6没有收到可写卡的冻结装备，已保留S1–S5结果"]
            emit_swarm_event(
                "winning_s6_card_authoring_limited",
                actor=agent_id,
                card_position=0,
                status="limited",
                failure_type="empty_s5_handoff",
            )
            return limited_result
        # Dynamic-v2 deliberately does not make S6 depend on S5's prose,
        # indicators, classification or evidence contract.  Those fields are
        # authored by the isolated S6 model from the three-item semantic
        # input; checking them here would reintroduce the old lock-in before
        # the model gets a chance to reason.
        pre_s6_contract_issues: list[str] = []
        if not dynamic_s6_authoring:
            for position, brief in enumerate(briefs, start=1):
                if not _indicator_portrait_is_specific(brief.get("indicator_portrait")):
                    pre_s6_contract_issues.append(
                        f"S5第{position}项指标画像未闭合测量轴、对照基线与判退条件"
                    )
                if not _query_relevance_is_specific(brief.get("query_relevance")):
                    pre_s6_contract_issues.append(
                        f"S5第{position}项未闭合任务对象、作战阶段、威胁压力和直接战果关联"
                    )
                boundary = str(brief.get("evidence_boundary", "") or "").strip()
                if boundary and not _evidence_boundary_is_public_semantic(boundary):
                    pre_s6_contract_issues.append(
                        f"S5第{position}项证据边界不是公开证据支持/不支持的语义陈述"
                    )
        if pre_s6_contract_issues:
            emit_swarm_event(
                "winning_s6_card_authoring_limited",
                actor=agent_id,
                card_position=0,
                status="limited",
                failure_type="s5_handoff_semantic_warning",
                warnings=pre_s6_contract_issues[:8],
            )
        emit_swarm_event(
            "winning_s5_handoff_quality_gate_completed",
            card_count=len(briefs),
            indicator_contracts=len(briefs),
            query_relevance_contracts=len(briefs),
            status="completed",
        )
        brief_names = [str(item.get("name", "")).strip() for item in briefs]
        if not all(brief_names) or len(set(brief_names)) != len(brief_names):
            emit_swarm_event(
                "winning_s6_card_authoring_limited",
                actor=agent_id,
                card_position=0,
                status="limited",
                failure_type="s5_handoff_title_warning",
                warnings=["S5交接中存在空标题或重复标题；S6按冻结身份继续写卡"],
            )

        card_semaphore = asyncio.Semaphore(
            max(1, min(6, int(handoff.get("s6_parallelism", 6) or 6)))
        )
        resume_s6_only = requested_resume_steps == [6] and bool(
            shared.get("prior_winning_analysis")
        )
        card_cache_scope = str(
            shared.get("run_id") or shared.get("topic") or "winning-s6"
        )

        def card_cache_key(brief: Mapping[str, Any]) -> tuple[str, str]:
            identity = str(
                brief.get("hypothesis_id") or brief.get("name") or ""
            ).strip()
            return card_cache_scope, identity

        def limited_card_from_brief(
            position: int,
            brief: Mapping[str, Any],
            failure: BaseException,
        ) -> tuple[int, dict[str, Any], str]:
            """Preserve an S5-approved weapon when its prose call is unavailable.

            The S5 handoff already contains the frozen identity, combat role,
            mechanism, process, evidence boundary and falsification contract.
            Reformat those existing semantics into the S6 card shape without
            inventing a replacement weapon, model fact or evidence reference.
            Provider availability is recorded as an audit limitation rather
            than promoted to a portfolio-level business failure.
            """

            direction = dict(brief)
            if dynamic_s6_authoring:
                # Dynamic-v2 never fabricates prose locally. Preserve the
                # frozen S5 decision spine and mark the card limited until an
                # S6 provider can author its portrait.
                direction.pop("capability_portrait", None)
                direction.pop("capability_portrait_modules", None)
                direction.pop("semantic_consistency_check", None)
                direction["s6_authoring_status"] = "limited_provider_failure"
                direction["s6_authoring_failure_type"] = type(failure).__name__
                draft = str(
                    direction.get("concise_winning_summary")
                    or direction.get("target_and_direct_effect")
                    or direction.get("name")
                    or ""
                ).strip()
                return position, direction, draft
            identity_contract = direction.get("portfolio_identity_contract", {})
            identity_contract = (
                dict(identity_contract)
                if isinstance(identity_contract, Mapping)
                else {}
            )
            operational_axes = identity_contract.get("operational_axes", {})
            operational_axes = (
                dict(operational_axes) if isinstance(operational_axes, Mapping) else {}
            )
            process = direction.get("operational_process", [])
            if not isinstance(process, list) or not process:
                process = operational_axes.get("mechanism_and_timing", [])
            if not isinstance(process, list) or not process:
                process = direction.get("mechanism_chain", [])
            process = [str(item).strip() for item in process if str(item).strip()]
            if process:
                direction["operational_process"] = process

            equipment_form = str(
                direction.get("equipment_form")
                or direction.get("primary_equipment_identity")
                or direction.get("name")
                or ""
            ).strip()
            direct_effect = str(
                direction.get("military_value")
                or direction.get("target_and_direct_effect")
                or direction.get("capability_outcome")
                or direction.get("unique_operational_role")
                or ""
            ).strip()
            mechanism = str(
                direction.get("winning_mechanism")
                or direction.get("operational_mechanism")
                or direction.get("depth_mechanism")
                or direction.get("non_substitutable_difference")
                or ""
            ).strip()
            if not str(direction.get("operational_mechanism", "")).strip():
                direction["operational_mechanism"] = mechanism or "；".join(process)
            if not str(direction.get("military_value", "")).strip():
                direction["military_value"] = direct_effect
            if not str(direction.get("capability_outcome", "")).strip():
                direction["capability_outcome"] = direct_effect
            if not str(direction.get("winning_mechanism", "")).strip():
                direction["winning_mechanism"] = mechanism
            if not str(direction.get("capability_portrait", "")).strip():
                direction["capability_portrait"] = build_agent_led_capability_portrait(
                    name=direction.get("name", ""),
                    scenario=(
                        direction.get("target_scenario")
                        or direction.get("query_relevance")
                        or str(step_input.get("query", ""))
                    ),
                    problem=(
                        direction.get("problem_statement")
                        or direction.get("capability_gap")
                    ),
                    principle=(direction.get("scientific_principle") or mechanism),
                    technologies=(
                        direction.get("enabling_technologies")
                        or direction.get("system_interfaces")
                        or direction.get("equipment_forms")
                        or []
                    ),
                    operational_concept=(
                        direction.get("operational_concept")
                        or direction.get("unique_operational_role")
                        or direction.get("operational_mechanism")
                    ),
                    operational_steps=process,
                    capability=(
                        direction.get("capability_outcome")
                        or direction.get("function")
                        or direction.get("unique_operational_role")
                    ),
                    effect=direct_effect,
                    winning_mechanism=(
                        direction.get("concise_winning_summary")
                        or direction.get("winning_summary_seed")
                        or direction.get("non_substitutable_difference")
                        or mechanism
                    ),
                    equipment_form=equipment_form,
                    baseline=direction.get("baseline_system", ""),
                    failure_boundary=(
                        direction.get("failure_boundary")
                        or direction.get("failure_boundaries")
                        or []
                    ),
                    verification_plan=direction.get("validation_plan", []),
                )
            direction["semantic_consistency_check"] = {
                "process_actor": equipment_form,
                "launch_or_release_mode": str(
                    direction.get("launch_or_release_domain", "")
                ),
                "target_and_direct_effect": str(
                    direction.get("target_and_direct_effect") or direct_effect
                ),
                "checked_fields": [
                    "name",
                    "primary_equipment_identity",
                    "equipment_form",
                    "operational_process",
                    "capability_portrait",
                ],
                "consistent": True,
                "resolution_note": (
                    "主装备、发射域、目标、作战流程和直接战果均沿用同一冻结候选，"
                    "未发生换装或跨卡吸收。"
                ),
            }
            direction["s6_authoring_status"] = "limited_provider_failure"
            direction["s6_authoring_failure_type"] = type(failure).__name__
            draft = str(
                direction.get("concise_winning_summary")
                or direction.get("capability_outcome")
                or direction.get("military_value")
                or direction.get("name")
                or ""
            ).strip()
            return position, direction, draft

        # The in-memory cache disappears when a worker/process restarts.
        # Rehydrate it from the persisted S6 checkpoint so a resume never
        # reauthors cards that already completed successfully.
        prior_analysis = shared.get("prior_winning_analysis", {})
        prior_directions = (
            prior_analysis.get("concept_directions", [])
            if isinstance(prior_analysis, Mapping)
            else []
        )
        if isinstance(prior_directions, list) and not dynamic_s6_authoring:
            prior_by_identity: dict[str, Mapping[str, Any]] = {}
            for item in prior_directions:
                if not isinstance(item, Mapping) or not _s6_card_is_reusable(item):
                    continue
                for identity in (
                    str(item.get("hypothesis_id", "")).strip(),
                    str(item.get("name", "")).strip(),
                ):
                    if identity:
                        prior_by_identity[identity] = item
            for brief in briefs:
                identity = str(
                    brief.get("hypothesis_id") or brief.get("name") or ""
                ).strip()
                prior = prior_by_identity.get(identity)
                if prior is None:
                    prior = prior_by_identity.get(str(brief.get("name", "")).strip())
                if prior is None:
                    continue
                prior_direction = dict(prior)
                host._s6_card_result_cache[card_cache_key(brief)] = (
                    prior_direction,
                    str(
                        prior_direction.get("capability_outcome")
                        or prior_direction.get("name")
                        or ""
                    ).strip(),
                )

        async def author_card(
            position: int,
            brief: Mapping[str, Any],
        ) -> tuple[int, dict[str, Any], str]:
            emit_swarm_event(
                "winning_s6_card_authoring_started",
                actor=agent_id,
                card_position=position,
                hypothesis_id=str(brief.get("hypothesis_id", "")),
                equipment_name=str(brief.get("name", "")),
                status="running",
            )
            async with card_semaphore:
                card_payload = (
                    _dynamic_s6_card_input(
                        brief,
                        query=str(step_input.get("query", "")),
                    )
                    if dynamic_s6_authoring
                    else {
                        "query": step_input.get("query", ""),
                        "branch": step_input.get("branch", ""),
                        "parallel_card_id": f"s6-card-{position}",
                        "portfolio_position": position,
                        "portfolio_card_count": len(briefs),
                        "assigned_card": _minimal_s6_card_handoff(brief),
                    }
                )
                card_text = await host._run_core_json(
                    agent_id,
                    _parallel_s6_card_instruction(),
                    card_payload,
                    {
                        "direction": card_direction_schema,
                        "capability_image_draft": "该装备能力画像的单句结论",
                    },
                    3200,
                    phase=(
                        f"winning_s6_parallel_card_resume_{position:02d}"
                        if resume_s6_only
                        else f"winning_s6_parallel_card_{position:02d}"
                    ),
                )
            parsed = _parse_json_object(card_text)
            direction = parsed.get("direction", {})
            if not isinstance(direction, Mapping):
                raise S6QualityError(f"S6并行第{position}张装备卡未返回结构化方向")
            direction = dict(direction)
            authored_modules = direction.get("capability_portrait_modules", {})
            if isinstance(authored_modules, Mapping):
                authored_modules = dict(authored_modules)
            else:
                # Compatibility for persisted runs and scripted test providers.
                # Live Codex calls are schema-bound to the five module fields.
                authored_modules = parse_capability_portrait_modules(
                    direction.get("capability_portrait", "")
                )
            source_name = str(brief.get("name", "")).strip()
            # A card must retain the direct-combat weapon selected by the
            # swarm. If the S6 writer accidentally swaps the visible
            # subject for a payload/carrier from another card, restore the
            # source identity and let the substantive gate request the
            # one permitted card-level repair.
            if source_name:
                direction["name"] = source_name
            # Dynamic S6 inherits only weapon identity and target/effect. It
            # authors classification, indicators, feasibility, process and
            # all portrait prose from the Query and winning-logic overview.
            protected_fields = (
                "name",
                "hypothesis_id",
                "source_hypothesis_title",
                "primary_equipment_identity",
                "equipment_form",
                "target_and_direct_effect",
            ) if dynamic_s6_authoring else (
                "name",
                "hypothesis_id",
                "source_hypothesis_title",
                "type",
                "primary_equipment_identity",
                "equipment_form",
                "equipment_family",
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "portfolio_identity_contract",
                "baseline_system",
                "capability_gap",
                "direct_evidence_refs",
                "foresight_evidence_status",
                "evidence_boundary",
                "validation_plan",
                "indicator_portrait",
                "query_relevance",
                "capability_classification",
                "equipment_semantic_assessment",
                "concise_winning_summary",
                "expert_score",
                "expert_assessment_id",
                "direct_combat_equipment",
            )
            for protected_field in protected_fields:
                protected_value = brief.get(protected_field)
                if protected_value not in (None, "", []):
                    direction[protected_field] = protected_value
            classification = direction.get("capability_classification", {})
            if isinstance(authored_modules, Mapping) and classification:
                authored_modules = dict(authored_modules)
                authored_modules["capability_classification"] = classification
            assembled_portrait = assemble_capability_portrait_modules(authored_modules)
            if assembled_portrait:
                direction["capability_portrait_modules"] = authored_modules
                direction["capability_portrait"] = assembled_portrait
            elif not str(direction.get("capability_portrait", "")).strip():
                raise S6QualityError(
                    f"S6并行第{position}张装备卡未完整返回五个能力画像模块"
                )
            authored_boundary = str(
                direction.get("evidence_boundary", "") or ""
            ).strip()
            semantic_check = direction.get("semantic_consistency_check", {})
            if (
                isinstance(semantic_check, Mapping)
                and semantic_check.get("consistent") is True
            ):
                direction["s6_authoring_status"] = "authored_semantically_consistent"
            if authored_boundary and not _evidence_boundary_is_public_semantic(
                authored_boundary
            ):
                # ``evidence_boundary`` is optional traceability context,
                # not a reason to fail an otherwise valid weapon card.
                # Invalid workflow commentary is discarded at the field
                # boundary and remains available only in audit events.
                direction.pop("evidence_boundary", None)
            # S5 owns the measurement axes, comparison baseline,
            # falsification condition and query-task relevance.  They are
            # locked above before S6 starts. S6 performs exactly one
            # parallel authoring call per card and never enters a card
            # repair session.
            emit_swarm_event(
                "winning_s6_card_authoring_completed",
                actor=agent_id,
                card_position=position,
                hypothesis_id=str(brief.get("hypothesis_id", "")),
                equipment_name=str(direction.get("name", brief.get("name", ""))),
                status="completed",
                direction=_compact_s6_authored_card_event(direction),
            )
            outcome = (
                position,
                dict(direction),
                str(parsed.get("capability_image_draft", "")).strip(),
            )
            host._s6_card_result_cache[card_cache_key(brief)] = (
                dict(outcome[1]),
                outcome[2],
            )
            return outcome

        authored: list[tuple[int, dict[str, Any], str]] = []
        pending_cards: list[tuple[int, Mapping[str, Any]]] = []
        for position, brief in enumerate(briefs, start=1):
            # A dynamic-v2 card is always authored against the current
            # Query/candidate/winning-logic tuple. Reusing a legacy cache entry
            # would silently restore S5 text and defeat the minimal handoff.
            if dynamic_s6_authoring:
                pending_cards.append((position, brief))
                continue
            cached = host._s6_card_result_cache.get(card_cache_key(brief))
            if cached is None or not _s6_card_is_reusable(cached[0]):
                if cached is not None:
                    host._s6_card_result_cache.pop(card_cache_key(brief), None)
                pending_cards.append((position, brief))
                continue
            cached_direction, cached_draft = cached
            cached_direction = dict(cached_direction)
            for protected_field in (
                "name",
                "hypothesis_id",
                "source_hypothesis_title",
                "type",
                "primary_equipment_identity",
                "equipment_form",
                "equipment_family",
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "portfolio_identity_contract",
                "baseline_system",
                "capability_gap",
                "direct_evidence_refs",
                "foresight_evidence_status",
                "evidence_boundary",
                "validation_plan",
                "indicator_portrait",
                "query_relevance",
                "capability_classification",
                "expert_score",
                "expert_assessment_id",
                "direct_combat_equipment",
            ):
                protected_value = brief.get(protected_field)
                if protected_value not in (None, "", []):
                    cached_direction[protected_field] = protected_value
            cached_boundary = str(
                cached_direction.get("evidence_boundary", "") or ""
            ).strip()
            if cached_boundary and not _evidence_boundary_is_public_semantic(
                cached_boundary
            ):
                cached_direction.pop("evidence_boundary", None)
            source_name = str(brief.get("name", "")).strip()
            if source_name:
                cached_direction["name"] = source_name
            authored.append((position, cached_direction, str(cached_draft)))
            emit_swarm_event(
                "winning_s6_card_authoring_reused",
                actor=agent_id,
                card_position=position,
                hypothesis_id=str(brief.get("hypothesis_id", "")),
                equipment_name=str(cached_direction.get("name", brief.get("name", ""))),
                status="completed",
                direction=_compact_s6_authored_card_event(cached_direction),
            )
        card_failures: list[str] = []
        if pending_cards:
            card_results = await asyncio.gather(
                *(author_card(position, brief) for position, brief in pending_cards),
                return_exceptions=True,
            )
            for (position, brief), card_result in zip(
                pending_cards,
                card_results,
                strict=True,
            ):
                if isinstance(card_result, BaseException):
                    failure_summary = (
                        f"第{position}张{str(brief.get('name', '')).strip()}："
                        f"{type(card_result).__name__}: {card_result}"
                    )
                    card_failures.append(failure_summary)
                    limited = limited_card_from_brief(
                        position,
                        brief,
                        card_result,
                    )
                    authored.append(limited)
                    host._s6_card_result_cache[card_cache_key(brief)] = (
                        dict(limited[1]),
                        limited[2],
                    )
                    emit_swarm_event(
                        "winning_s6_card_authoring_limited",
                        actor=agent_id,
                        card_position=position,
                        hypothesis_id=str(brief.get("hypothesis_id", "")),
                        equipment_name=str(brief.get("name", "")),
                        failure_type=type(card_result).__name__,
                        status="limited",
                        direction=_compact_s6_authored_card_event(limited[1]),
                    )
                    continue
                authored.append(card_result)
        authored.sort(key=lambda item: item[0])
        if selected_portfolio:
            # The dynamic swarm has already calibrated every selected
            # candidate through the blind expert judge. Unlike the
            # model-authored planner path, this direct-portfolio path has
            # no planner call to populate top-level fields. Leaving
            # ``confidence`` at the schema default (an empty string)
            # therefore makes the S6 gate fail even after every card has
            # passed authoring and preflight repair. Project the existing
            # expert/card calibration; do not invent or raise a score just
            # to cross the release threshold.
            plan["confidence"] = _s6_portfolio_confidence(
                selected_portfolio,
                [item[1] for item in authored],
            )
        result = {
            key: plan.get(key, [] if isinstance(value, list) else "")
            for key, value in schema.items()
            if key not in {"concept_directions", "capability_image_drafts"}
        }
        result["concept_directions"] = [item[1] for item in authored]
        result["capability_image_drafts"] = [
            item[2]
            or str(item[1].get("capability_outcome", "")).strip()
            or str(item[1].get("name", "")).strip()
            for item in authored
        ]
        if card_failures:
            result["s6_card_authoring_limited"] = True
            result["s6_card_authoring_warnings"] = card_failures[:8]
            result["s6_card_authoring_limited_count"] = len(card_failures)
        return result

    async def run_step(
        index: int,
        *,
        middle_cycle: int,
        prior_step_outputs: Mapping[str, Any],
        middle_feedback: list[str] | None = None,
    ) -> dict[str, Any]:
        nonlocal s6_model_repair_used
        agent_id, system, schema = steps[index - 1]

        schema = {
            **schema,
            "reasoning_node": {
                "recognition": "当前步骤形成的可审计认识",
                "evidence_refs": ["exact evidence_id or packet_id"],
                "confidence": "0..1",
                "next_action": {
                    "action": "continue|parallel|backtrack|recall|stop",
                    "target_step": "1..6 or 0",
                    "reason": "string",
                },
            },
        }
        execution_mode = step_modes[index]
        critic_feedback: list[str] = list(middle_feedback or [])
        result: dict[str, Any] = {}
        if index == 6 and middle_cycle > 1:
            result = {
                key: prior_step_outputs[key]
                for key in (
                    "concept_directions",
                    "capability_image_drafts",
                    "upstream_coverage",
                    "branch_products",
                    "evidence_validation",
                    "assumptions",
                    "open_questions",
                    "confidence",
                )
                if key in prior_step_outputs
            }
            prior_node = prior_step_outputs.get("reasoning_nodes", {}).get("6")
            if isinstance(prior_node, Mapping):
                result["reasoning_node"] = dict(prior_node)
        resume_s6_checkpoint = (
            index == 6
            and middle_cycle == 1
            and requested_resume_steps == [6]
            and bool(prior_step_outputs.get("concept_directions"))
        )
        if resume_s6_checkpoint:
            # A failed S6 checkpoint already contains the complete cards
            # and their exact residual issues. Replanning and reauthoring
            # the portfolio here discards successful work and can drift
            # the expert-approved equipment set. Seed the first inner pass
            # from the checkpoint, then let the normal deterministic gate
            # select only the cards that still need repair.
            result = {
                key: (
                    prior_step_outputs[key]
                    if key in prior_step_outputs
                    else []
                    if isinstance(value, list)
                    else {}
                    if isinstance(value, Mapping)
                    else ""
                )
                for key, value in schema.items()
            }
            directions = result.get("concept_directions", [])
            if not result.get("capability_image_drafts") and isinstance(
                directions, list
            ):
                result["capability_image_drafts"] = [
                    str(item.get("capability_outcome") or item.get("name") or "")
                    for item in directions
                    if isinstance(item, Mapping)
                ]
            prior_node = prior_step_outputs.get("reasoning_nodes", {}).get("6")
            if isinstance(prior_node, Mapping):
                result["reasoning_node"] = dict(prior_node)
        final_review: dict[str, Any] = {}
        if index == 4 and middle_cycle > 1:
            result = {
                key: prior_step_outputs[key]
                for key in (
                    "capability_mapping",
                    "dotmlpf_matrix",
                    "open_questions",
                    "confidence",
                )
                if key in prior_step_outputs
            }
            if "s4_concept_directions" in prior_step_outputs:
                result["concept_directions"] = prior_step_outputs[
                    "s4_concept_directions"
                ]
            prior_node = prior_step_outputs.get("reasoning_nodes", {}).get("4")
            if isinstance(prior_node, Mapping):
                result["reasoning_node"] = dict(prior_node)
        s6_targeted_repair = False
        s4_targeted_repair = index == 4 and middle_cycle > 1 and bool(result)
        if s6_parallel_authoring_only:
            s6_targeted_repair = False
        reuse_s6_without_model = (
            index == 6
            and middle_cycle > 1
            and bool(result)
            and (s6_model_repair_used or s6_parallel_authoring_only)
        )
        if reuse_s6_without_model:
            s6_targeted_repair = False
        s6_handoff: dict[str, Any] = {}
        # The second middle cycle is already a targeted repair informed by
        # the round critic. One bounded regeneration plus the final round
        # rereview is sufficient; repeating the full high-reasoning step a
        # second time added minutes without introducing new evidence.
        # 常规步骤默认一次通过本地门控；S6 的篇幅目标只属于
        # Codex 首稿编辑合同，不能被本地长度、句数或关键词检查
        # 转换成重试、修复或交付失败。
        step_deadline_state = host._deadline_state(priority="critical")
        deadline_pressure = index != 6 and step_deadline_state.get("mode") != "normal"
        if index == 6:
            # S6 is a one-pass, per-card Codex authoring stage. Local field,
            # length, keyword, confidence, repetition and similarity checks
            # must never buy a second model call or enter the middle loop.
            max_inner_iterations = 1
        elif middle_cycle == 1 and model_loop_critics and not deadline_pressure:
            max_inner_iterations = 2
        else:
            max_inner_iterations = 1
        for inner_iteration in range(1, max_inner_iterations + 1):
            if (
                inner_iteration > 1
                and index != 6
                and host._deadline_state(priority="critical").get("mode") != "normal"
            ):
                loop_trace.append(
                    {
                        "loop": "inner",
                        "middle_cycle": middle_cycle,
                        "step": index,
                        "agent_id": agent_id,
                        "iteration": inner_iteration,
                        "event": "deadline_skip",
                        "passed": False,
                        "issues": [
                            "进入截止收敛区间，停止第二次模型修复并保留首次有效结果。"
                        ],
                        "recommended_action": "stop",
                    }
                )
                break
            projected_prior = prior_projection(index, prior_step_outputs)
            if index == 6:
                if dynamic_s6_authoring:
                    # Dynamic S5 already froze the decision spine.  Do not
                    # rebuild the legacy portfolio/evidence contract here;
                    # that contract was the main source of prompt bloat.
                    dynamic_portfolio = (
                        accumulated.get("winning_swarm", {}).get(
                            "final_equipment_portfolio", []
                        )
                        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
                        else []
                    )
                    if not dynamic_portfolio:
                        dynamic_portfolio = accumulated.get("concept_directions", [])
                    s6_handoff = {
                        "selected_equipment_portfolio": [
                            _minimal_s6_card_handoff(item)
                            for item in dynamic_portfolio
                            if isinstance(item, Mapping)
                        ],
                        "s6_card_capacity": min(12, len(dynamic_portfolio) or 1),
                        "s6_parallelism": int(
                            host._runtime_budgets.get("s6_codex_concurrency", 6)
                        ),
                        "handoff_mode": "dynamic_s5_decision_spine",
                    }
                else:
                    s6_handoff = _capability_synthesis_handoff(
                        topic=shared["topic"],
                        branch=primary_branch,
                        prior_step_outputs=prior_step_outputs,
                        evidence_index=shared.get("evidence_index", []),
                        s6_parallelism=int(
                            host._runtime_budgets.get("s6_codex_concurrency", 6)
                        ),
                    )
                s6_valid_evidence_ids = sorted(
                    {
                        str(item.get("evidence_id", ""))
                        for item in s6_handoff.get("public_evidence", [])
                        if isinstance(item, Mapping)
                        and str(item.get("evidence_id", "")).strip()
                    }
                )
                if resume_s6_checkpoint and not isinstance(
                    result.get("reasoning_node"), Mapping
                ):
                    result["reasoning_node"] = {}
                if resume_s6_checkpoint:
                    reasoning_node = dict(result.get("reasoning_node", {}))
                    reasoning_node.setdefault(
                        "recognition",
                        "复核已保存的具体装备能力画像及其证据、场景和指标闭环",
                    )
                    reasoning_node["evidence_refs"] = list(
                        dict.fromkeys(
                            [
                                *[
                                    str(item)
                                    for item in reasoning_node.get("evidence_refs", [])
                                    if str(item).strip()
                                ],
                                *s6_valid_evidence_ids[:4],
                            ]
                        )
                    )
                    reasoning_node.setdefault(
                        "confidence",
                        result.get("confidence", 0.68) or 0.68,
                    )
                    reasoning_node.setdefault(
                        "next_action",
                        {
                            "action": "continue",
                            "target_step": 0,
                            "reason": "完成S6发布门复核后进入报告生成",
                        },
                    )
                    result["reasoning_node"] = reasoning_node
                s6_first_pass_contract = (
                    {"mode": "dynamic_minimal_card", "identity_frozen_by": "S5"}
                    if dynamic_s6_authoring
                    else _s6_first_pass_quality_contract(
                        topic=str(shared["topic"]),
                        handoff=s6_handoff,
                    )
                )
                step_input = {
                    "query": shared["topic"],
                    "branch": primary_branch,
                    "execution_profile_id": shared.get("execution_profile_id", ""),
                    "analysis_priority": analysis_priority_contract,
                    "branch_deliverables": list(branch_product_schema),
                    "capability_synthesis_handoff": s6_handoff,
                    "first_pass_quality_contract": s6_first_pass_contract,
                    "valid_evidence_ids": s6_valid_evidence_ids,
                }
            else:
                shared_step_context = step_shared_context(
                    index,
                    prior_step_outputs,
                )
                step_input = {
                    **shared_step_context,
                    "valid_evidence_ids": sorted(
                        {
                            str(item.get("evidence_id", ""))
                            for item in shared_step_context.get("evidence_index", [])
                            if isinstance(item, Mapping)
                            and str(item.get("evidence_id", "")).strip()
                        }
                        if optimized_v2
                        else valid_evidence_ids
                    ),
                    "prior_step_outputs": projected_prior,
                    "loop_context": {
                        "middle_cycle": middle_cycle,
                        "inner_iteration": inner_iteration,
                        "critic_feedback": critic_feedback,
                        "execution_mode": execution_mode,
                    },
                }
            if reuse_s6_without_model:
                # A previous inner iteration already spent the one allowed
                # card-level model repair. Re-evaluate the preserved S6
                # result against the final gate, but never pay for another
                # repair or full regeneration in a later middle cycle.
                pass
            elif (
                resume_s6_checkpoint
                and inner_iteration == 1
                and not s6_parallel_authoring_only
            ):
                # The checkpoint is the first-pass candidate. Its
                # deterministic review below decides the exact per-card
                # repair targets without another portfolio-planning call.
                pass
            elif index == 4 and s4_targeted_repair:
                repair_schema = {
                    "capability_mapping": schema["capability_mapping"],
                    "dotmlpf_matrix": schema["dotmlpf_matrix"],
                    "concept_directions": schema["concept_directions"],
                }
                text = await host._run_core_json(
                    agent_id,
                    "你是S4定向修复Agent。仅修复repair_issues涉及的效果链承接、索引、"
                    "能力映射或DOTMLPF字段，保持原有方向数量、排序、有效证据引用和未被指出的"
                    "内容不变。不得扩展新方向或重做S3推理。只输出严格JSON。",
                    {
                        "topic": shared["topic"],
                        "research_route": shared["research_route"],
                        "current_result": compact_for_prompt(
                            result,
                            max_string_chars=700,
                            max_list_items=8,
                        ),
                        "repair_issues": critic_feedback,
                        "effect_chain": projected_prior.get("effect_chain", []),
                        "valid_evidence_ids": sorted(valid_evidence_ids),
                    },
                    repair_schema,
                    1800,
                    phase="winning_s4_targeted_repair",
                )
                repair = _parse_json_object(text)
                if repair:
                    result = {**result, **repair}
            elif index == 6 and (
                s6_targeted_repair
                or (
                    middle_cycle == 1
                    and inner_iteration > 1
                    and bool(result)
                    and host.provider.__class__.__module__
                    == "equipment_deep_research.providers.codex"
                )
            ):
                repair_targets = _s6_repair_targets(result, critic_feedback)
                directions = result.get("concept_directions", [])
                target_cards = [
                    {"position": position, "direction": directions[position - 1]}
                    for position in repair_targets
                    if isinstance(directions, list) and 1 <= position <= len(directions)
                ]
                protected_cards = [
                    {
                        "position": position,
                        "name": str(item.get("name", "")),
                        "type": str(item.get("type", "")),
                    }
                    for position, item in enumerate(directions, start=1)
                    if isinstance(item, Mapping) and position not in repair_targets
                ]
                direction_schema = schema["concept_directions"][0]
                repair_prompt = (
                    "你是装备能力画像单卡定向修复Agent。只修复指定装备卡，不得改动主装备身份、"
                    "装备名称、组合位置、发射/释放域、主要目标、公开基线或对象证据。direction.name"
                    "必须逐字复制current_direction.name；名称问题退回S3–S5处理。围绕query中的真实"
                    "战役/战斗地域与阶段，写清敌方目标及反制、我方运用主体、时敏交战流程、"
                    "直接战果、通信中断降级和失效边界；禁止套用其他卡流程。indicator_portrait"
                    "必须由本装备制胜机理反推2至5个专属测量轴，逐字点名baseline_system中的"
                    "公开/现役基线作对照，并明确写出若何种结果未达门槛或高于上限则判退、停止"
                    "或淘汰；不得虚构精确数值。semantic_consistency_check必须逐字段复核且"
                    "consistent为JSON布尔true。概述必须直接点名本装备。"
                    + CAPABILITY_PORTRAIT_CONCISION_GUIDANCE
                    + "只输出严格JSON。"
                )
                protected_fields = (
                    "name",
                    "hypothesis_id",
                    "source_hypothesis_title",
                    "type",
                    "primary_equipment_identity",
                    "equipment_form",
                    "equipment_family",
                    "unique_operational_role",
                    "launch_or_release_domain",
                    "target_and_direct_effect",
                    "non_substitutable_difference",
                    "portfolio_identity_contract",
                    "baseline_system",
                    "capability_gap",
                    "direct_evidence_refs",
                    "foresight_evidence_status",
                    "evidence_boundary",
                    "validation_plan",
                    "expert_score",
                    "expert_assessment_id",
                )

                async def repair_target_card(
                    target: Mapping[str, Any],
                ) -> dict[str, Any]:
                    position = int(target["position"])
                    current_direction = dict(target["direction"])
                    text = await host._run_core_json(
                        agent_id,
                        repair_prompt,
                        {
                            "parallel_card_id": f"s6-card-{position}",
                            "query": shared["topic"],
                            "branch": primary_branch,
                            "analysis_priority": analysis_priority_contract,
                            "capability_synthesis_handoff": s6_handoff,
                            "first_pass_quality_contract": s6_first_pass_contract,
                            "current_direction": current_direction,
                            "protected_cards": protected_cards,
                            "repair_issues": critic_feedback,
                            "valid_evidence_ids": step_input["valid_evidence_ids"],
                        },
                        {"direction": direction_schema},
                        3600,
                        phase=(f"winning_s6_parallel_card_repair_{position:02d}"),
                    )
                    parsed = _parse_json_object(text)
                    repaired_direction = parsed.get("direction", {})
                    if not isinstance(repaired_direction, Mapping):
                        return {
                            "position": position,
                            "direction": current_direction,
                        }
                    repaired_direction = dict(repaired_direction)
                    for field_name in protected_fields:
                        protected_value = current_direction.get(field_name)
                        if protected_value not in (None, "", []):
                            repaired_direction[field_name] = protected_value
                    return {
                        "position": position,
                        "direction": repaired_direction,
                    }

                if resume_s6_checkpoint and target_cards:
                    repair_outcomes = await asyncio.gather(
                        *(repair_target_card(target) for target in target_cards),
                        return_exceptions=True,
                    )
                    repair = {
                        "direction_repairs": [
                            item
                            for item in repair_outcomes
                            if isinstance(item, Mapping)
                        ]
                    }
                else:
                    text = await host._run_core_json(
                        agent_id,
                        repair_prompt
                        + "本次可包含多个repair_targets，但只返回这些位置及修复后的direction。",
                        {
                            "query": shared["topic"],
                            "branch": primary_branch,
                            "analysis_priority": analysis_priority_contract,
                            "capability_synthesis_handoff": s6_handoff,
                            "first_pass_quality_contract": s6_first_pass_contract,
                            "repair_targets": target_cards,
                            "capability_image_drafts": result.get(
                                "capability_image_drafts", []
                            ),
                            "protected_cards": protected_cards,
                            "repair_issues": critic_feedback,
                            "valid_evidence_ids": step_input["valid_evidence_ids"],
                        },
                        {
                            "direction_repairs": [
                                {
                                    "position": "1-based integer from repair_targets",
                                    "direction": direction_schema,
                                }
                            ]
                        },
                        min(4200, 1400 + 700 * max(1, len(repair_targets))),
                        phase="winning_s6_card_repair",
                    )
                    repair = _parse_json_object(text)
                s6_model_repair_used = True
                if repair:
                    result = _merge_s6_direction_repairs(result, repair)
            elif (
                index == 6
                and middle_cycle == 1
                and inner_iteration == 1
                # Dynamic-v2's three-item S6 contract is a profile invariant,
                # not a capability of one particular provider implementation.
                # Keep the isolated per-card authoring path even when tests or
                # deployments use a non-Codex provider.
                and (s6_parallel_authoring_only or dynamic_s6_authoring)
            ):
                result = await generate_parallel_s6_cards(
                    agent_id=agent_id,
                    system=system,
                    schema=schema,
                    step_input=step_input,
                )
            else:
                try:
                    text = await host._run_core_json(
                        agent_id,
                        system
                        + (
                            " first_pass_quality_contract是首次成稿的强制提交合同。必须在同一次调用内"
                            "先完成组合选择和逐卡内部自检，再提交唯一最终JSON；不得输出草稿或自检过程。"
                            "尤其先依据query的任务对象、威胁形态、作战阶段和制胜矛盾形成候选架构，"
                            "再收敛为具体打击、歼灭、杀伤或反杀伤武器卡；不得依据预置类别、关键词表"
                            "或命名样例机械补齐候选。提交前修正标题、完整句、"
                            "装备基线、独立差距和卡片间重复。"
                            if index == 6
                            else ""
                        )
                        + " 本步骤必须额外输出reasoning_node={recognition,evidence_refs,confidence,next_action}；"
                        "next_action只给可审计的动作建议，不输出隐藏思维过程。"
                        + f" 当前A-H分支要求本步骤按{execution_mode}强度执行："
                        + (
                            "深入展开多个备选、反证与适用边界。"
                            if execution_mode == "deep"
                            else "只保留支撑后续步骤所需的最小充分判断。"
                            if execution_mode == "light"
                            else "按标准深度完成。"
                        ),
                        step_input,
                        schema,
                        (
                            5200
                            if index == 6
                            else {
                                "light": 1800,
                                "standard": 2400,
                                "deep": 2800,
                            }.get(execution_mode, 2400)
                        ),
                        phase=f"{agent_id}_{execution_mode}",
                    )
                except ProviderRequestError:
                    # The provider performs its own retry. If S6 still
                    # cannot return a complete response, fail the stage;
                    # never replace it with a deterministic portfolio.
                    raise
                else:
                    result = _parse_json_object(text)
            if not result:
                raise ValueError(f"{agent_id} returned invalid structured JSON")
            result = sanitize_references(result)
            if index in {4, 6}:
                effect_chain_rows = projected_prior.get("effect_chain", [])
                effect_chain_count = (
                    len(effect_chain_rows) if isinstance(effect_chain_rows, list) else 0
                )
                result = _normalize_effect_chain_references(
                    result,
                    effect_chain_count,
                )
            if index == 6:
                result = _normalize_s6_deterministic_format(
                    result,
                    topic=str(shared.get("topic", "")),
                )
                result = _normalize_concept_direction_priorities(result)
            deterministic_quality_issues: list[str] = []
            deterministic_quality_warnings: list[str] = []
            if (
                index == 6
                and host.provider.__class__.__module__
                != "equipment_deep_research.providers.fake"
            ):
                deterministic_quality_warnings = _capability_direction_quality_issues(
                    result,
                    handoff=s6_handoff,
                )
                deterministic_quality_issues = _s6_delivery_blocking_issues(
                    deterministic_quality_warnings
                )
                if deterministic_quality_issues and optimized_v2:
                    lightweight_repair = _s6_can_use_lightweight_card_repair(
                        result,
                        deterministic_quality_issues,
                    )
                    loop_trace.append(
                        {
                            "loop": "inner",
                            "middle_cycle": middle_cycle,
                            "step": 6,
                            "agent_id": agent_id,
                            "iteration": inner_iteration,
                            "event": (
                                "lightweight_card_repair_planned"
                                if lightweight_repair
                                else "full_s6_quality_regeneration_planned"
                            ),
                            "passed": False,
                            "issues": deterministic_quality_issues[:4],
                            "repair_targets": (
                                _s6_repair_targets(
                                    result,
                                    deterministic_quality_issues,
                                )
                                if lightweight_repair
                                else []
                            ),
                            "recommended_action": "retry",
                        }
                    )
            # 默认使用本地结构、证据与置信度门控。只有本地门控发现实质
            # 缺陷时，中循环才调用独立批判 Agent 生成一次定向修复建议。
            if index == 6:
                review = {
                    "passed": True,
                    "issues": [],
                    "retry_guidance": [],
                    "recommended_action": "pass",
                    "backtrack_to_step": 0,
                    "recall_target": "",
                    "review_mode": "s6_advisory_diagnostics_only",
                    "warnings": deterministic_quality_warnings[:8],
                }
            elif (
                not model_loop_critics
                or fast_profile
                or deadline_pressure
                or execution_mode == "light"
                or index == 4
            ):
                missing_fields = [key for key in schema if key not in result]
                local_issues = (
                    [f"缺少结构化字段：{', '.join(missing_fields)}"]
                    if missing_fields
                    else []
                )
                try:
                    confidence = float(result.get("confidence", 0.0) or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < 0.65:
                    local_issues.append("步骤置信度低于0.65，需要定向复核")
                raw_node = result.get("reasoning_node", {})
                if isinstance(raw_node, Mapping):
                    refs = raw_node.get("evidence_refs", [])
                    if valid_reference_ids and not any(str(item) for item in refs):
                        local_issues.append(
                            "reasoning_node缺少有效证据或上游Packet引用"
                        )
                review = {
                    "passed": not local_issues,
                    "issues": local_issues,
                    "retry_guidance": [
                        "仅修复被指出的字段、证据承接或置信度问题，保留有效结论。"
                    ]
                    if local_issues
                    else [],
                    "recommended_action": "retry" if local_issues else "pass",
                    "backtrack_to_step": 0,
                    "recall_target": "",
                    "review_mode": (
                        "harness_structured_gate"
                        if index in {4, 6}
                        else "harness_fast_gate"
                    ),
                }
            elif inner_iteration == max_inner_iterations:
                missing_fields = [key for key in schema if key not in result]
                review = {
                    "passed": not missing_fields,
                    "issues": [f"重试结果仍缺少结构化字段：{', '.join(missing_fields)}"]
                    if missing_fields
                    else [],
                    "retry_guidance": [],
                    "recommended_action": ("pass" if not missing_fields else "stop"),
                    "backtrack_to_step": 0,
                    "recall_target": "",
                    "review_mode": "retry_schema_gate_then_round_critic",
                }
            else:
                critic_text = await host._run_core_json(
                    "winning_step_critic",
                    "你是制胜机理步骤批判Agent。检查当前步骤是否有输入遗漏、证据越界、"
                    "跨步跳跃、结论空泛或安全边界问题。只输出严格JSON。",
                    {
                        "step": index,
                        "agent_id": agent_id,
                        "step_context": {
                            "topic": shared["topic"],
                            "research_route": shared["research_route"],
                            "execution_mode": execution_mode,
                            "middle_cycle": middle_cycle,
                            "inner_iteration": inner_iteration,
                            "valid_evidence_ids": step_input["valid_evidence_ids"],
                            "packet_ids": [item["packet_id"] for item in packet_index],
                            "prior_step_outputs": projected_prior,
                            "critic_feedback": critic_feedback,
                            "winning_step_plan": shared["winning_step_plan"],
                            "contract_note": (
                                "skip步骤按分支蓝图视为依赖已满足，不得因其没有输出判失败；"
                                "S4的优先级和可行性是暂定判断，S5负责证据审计。"
                            ),
                        },
                        "step_output": compact_for_prompt(
                            result,
                            max_string_chars=1000,
                            max_list_items=8,
                        ),
                        "deterministic_quality_issues": deterministic_quality_issues,
                    },
                    {
                        "passed": "boolean",
                        "issues": ["string"],
                        "retry_guidance": ["string"],
                        "recommended_action": "pass|retry|recall|backtrack|stop",
                        "backtrack_to_step": "1..6 or 0",
                        "recall_target": "capability tag or empty string",
                    },
                    1200,
                    phase="winning_step_review",
                )
                review = _parse_json_object(critic_text)
            if deterministic_quality_issues:
                review = {
                    **dict(review),
                    "passed": False,
                    "issues": [
                        *deterministic_quality_issues,
                        *[str(item) for item in review.get("issues", [])],
                    ][:8],
                    "retry_guidance": deterministic_quality_issues[:6],
                    "recommended_action": (
                        "stop"
                        if s6_model_repair_used
                        or inner_iteration >= max_inner_iterations
                        else "retry"
                    ),
                }
            final_review = dict(review)
            passed = review.get("passed") is True
            recommended_action = (
                str(
                    review.get(
                        "recommended_action",
                        "pass" if passed else "stop",
                    )
                )
                .strip()
                .lower()
            )
            loop_trace.append(
                {
                    "loop": "inner",
                    "middle_cycle": middle_cycle,
                    "step": index,
                    "agent_id": agent_id,
                    "iteration": inner_iteration,
                    "passed": passed,
                    "issues": [str(item) for item in review.get("issues", [])][:4],
                    "warnings": [
                        str(item) for item in review.get("warnings", [])
                    ][:4],
                    "recommended_action": recommended_action,
                    "backtrack_to_step": review.get("backtrack_to_step", 0),
                    "recall_target": str(review.get("recall_target", "")),
                }
            )
            if passed or inner_iteration == max_inner_iterations:
                break
            # 只有可在当前输入上原地修复的字段/表达问题才重试。
            # recall/backtrack/stop 需要新增证据或改变上游输入，立即用相同
            # 上下文重跑只会增加耗时并放大不一致，交由中循环统一处理。
            if recommended_action != "retry":
                break
            critic_feedback = [str(item) for item in review.get("retry_guidance", [])][
                :6
            ]
            if index == 6:
                s6_targeted_repair = False
        # S6 review findings are advisory. Candidate identity and semantic
        # admission were already decided by S5; local prose/shape checks may
        # request a bounded rewrite but must never convert a completed card
        # into a hard task failure.
        raw_reasoning_node = result.pop("reasoning_node", {})
        reasoning_node = (
            dict(raw_reasoning_node) if isinstance(raw_reasoning_node, Mapping) else {}
        )
        return {
            "result": result,
            "assumptions": [
                str(item) for item in result.get("assumptions", []) if str(item).strip()
            ],
            "open_questions": [
                str(item)
                for item in result.get("open_questions", [])
                if str(item).strip()
            ],
            "reasoning_node": reasoning_node,
            "run": {
                "step": index,
                "agent_id": agent_id,
                "middle_cycle": middle_cycle,
                "execution_mode": execution_mode,
                "confidence": result.get("confidence"),
                "open_question_count": len(result.get("open_questions", [])),
                "status": "completed",
                "reasoning_node": reasoning_node,
                "next_action": reasoning_node.get("next_action", {}),
                "critic_action": str(final_review.get("recommended_action", "pass")),
                "critic_issues": [
                    str(item)
                    for item in final_review.get("issues", [])
                    if str(item).strip()
                ][:4],
                "critic_recall_target": str(final_review.get("recall_target", "")),
                "critic_backtrack_to_step": final_review.get("backtrack_to_step", 0),
            },
        }

    execution_contract = (
        dict(shared.get("execution_contract", {}))
        if isinstance(shared.get("execution_contract", {}), Mapping)
        else {}
    )
    core_step_dependency_map = swarm_controller.core_dependencies_from_dag(
        execution_contract.get("logical_agent_dag", {})
        if isinstance(execution_contract.get("logical_agent_dag", {}), Mapping)
        else {}
    )
    physical_cohorts: list[tuple[int, ...]] = []
    if aggressive_compaction:
        for raw_cohort in execution_contract.get("physical_cohorts", []):
            if not isinstance(raw_cohort, Sequence) or isinstance(
                raw_cohort, (str, bytes)
            ):
                continue
            cohort = tuple(
                int(item)
                for item in raw_cohort
                if str(item).isdigit() and int(item) in range(1, 7)
            )
            if len(cohort) >= 2:
                physical_cohorts.append(cohort)

    async def run_physical_cohort(
        indices: tuple[int, ...],
        *,
        middle_cycle: int,
        prior_step_outputs: Mapping[str, Any],
        middle_feedback: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute causally ordered logical S-agents in one provider turn."""
        cohort_id = "cohort-" + "-".join(f"s{index}" for index in indices)
        schemas = {
            f"S{index}": {
                **steps[index - 1][2],
                "reasoning_node": {
                    "recognition": "当前逻辑步骤形成的可审计认识",
                    "evidence_refs": ["exact evidence_id or packet_id"],
                    "confidence": "0..1",
                    "next_action": {
                        "action": "continue|backtrack|recall|stop",
                        "target_step": "1..6 or 0",
                        "reason": "string",
                    },
                },
            }
            for index in indices
        }
        logical_contracts = [
            {
                "step": index,
                "agent_id": steps[index - 1][0],
                "execution_mode": step_modes[index],
                "depends_on_steps": [
                    dependency
                    for dependency in {
                        1: (),
                        2: (1,),
                        3: (1, 2),
                        4: (3,),
                        5: (4,),
                        6: (4, 5),
                    }[index]
                    if dependency in indices
                ],
                "role_contract": cohort_role_contract(index),
                # The authoritative nested schema is already supplied once
                # through the provider's output_schema option. Repeating it
                # in the user payload materially inflated S4/S5 input size.
                "required_output_fields": list(schemas[f"S{index}"].keys()),
            }
            for index in indices
        ]
        cohort_agents = set().union(
            *(packet_agents_by_step[index] for index in indices)
        )
        cohort_prior = prior_projection(indices[0], prior_step_outputs)
        cohort_claims = military_claims_for_steps(indices) if optimized_v2 else []
        if optimized_v2:
            cohort_packets: list[Mapping[str, Any]] = []
            cohort_packet_index = military_packet_refs_for_claims(cohort_claims)
            cohort_evidence = evidence_for_claims(
                cohort_claims,
                prior_step_outputs=cohort_prior,
                limit=12 if primary_branch_for_packets == "C" else 10,
            )
        else:
            cohort_packets = [
                item
                for item in shared.get("packets", [])
                if isinstance(item, Mapping)
                and str(item.get("agent_id", "")) in cohort_agents
            ]
            cohort_packet_index = packet_index
            cohort_evidence = _prioritized_evidence_index(
                shared.get("evidence_index", []),
                preferred_ids=_collect_reference_ids(cohort_prior),
                allowed_agents=cohort_agents,
                limit=12 if primary_branch_for_packets == "C" else 10,
            )
        cohort_valid_reference_ids = {
            str(item.get("packet_id", ""))
            for item in cohort_packet_index
            if str(item.get("packet_id", ""))
        } | {
            str(item.get("evidence_id", ""))
            for item in cohort_evidence
            if str(item.get("evidence_id", ""))
        }
        cohort_input = {
            "topic": shared["topic"],
            "query": shared["topic"],
            "research_route": shared["research_route"],
            "execution_profile_id": shared["execution_profile_id"],
            "analysis_priority": analysis_priority_contract,
            "discovery_blueprint": step_shared_context(indices[0]).get(
                "discovery_blueprint", {}
            ),
            "logical_contracts": logical_contracts,
            "required_branch_products": list(
                execution_contract.get("branch_products", [])
            )[:10],
            "prior_step_outputs": (
                cohort_prior
                if optimized_v2
                else compact_for_prompt(
                    prior_step_outputs,
                    max_string_chars=1000,
                    max_list_items=10,
                )
            ),
            "packet_index": _compact_prompt_value(
                cohort_packet_index,
                max_string_chars=220 if optimized_v2 else 280,
                max_list_items=6 if optimized_v2 else 8,
            ),
            "packets": (
                [packet_projection(item, step=indices[0]) for item in cohort_packets]
                if optimized_v2
                else _compact_prompt_value(
                    cohort_packets,
                    max_string_chars=(
                        1200 if primary_branch_for_packets == "C" else 520
                    ),
                    max_list_items=(14 if primary_branch_for_packets == "C" else 8),
                )
            ),
            "secondary_cross_agent_constraints": (
                _compact_prompt_value(
                    cohort_claims,
                    max_string_chars=460,
                    max_list_items=8,
                )
                if optimized_v2
                else []
            ),
            "branch_products": (
                _compact_prompt_value(
                    military_branch_products,
                    max_string_chars=360,
                    max_list_items=8,
                )
                if optimized_v2
                and primary_branch_for_packets == "C"
                and any(index in {3, 4, 5} for index in indices)
                else {}
            ),
            "evidence_index": _compact_prompt_value(
                cohort_evidence,
                max_string_chars=240 if optimized_v2 else 320,
                max_list_items=len(cohort_evidence) if optimized_v2 else 24,
            ),
            "valid_reference_ids": sorted(
                cohort_valid_reference_ids if optimized_v2 else valid_reference_ids
            ),
            "middle_cycle": middle_cycle,
            "repair_guidance": list(middle_feedback or [])[:8],
            "cohort_rule": (
                "始终以topic中的军事任务为第一锚点，先按各角色的military_divergence_contract"
                "发散竞争性作战机制，再按logical_contracts顺序完成分析；后一步必须显式消费本次"
                "前一步结果，并严格执行各自role_contract、required_output_fields和"
                "required_branch_products；字段结构以唯一的output_schema为准。"
                "每个逻辑结果都要按自身军事角色写清军事任务"
                "效果、作用机理和失效边界；不得合并逻辑结果或跳过字段。"
                + (
                    "本Cohort含S1/S2：每个逻辑Agent只保留3条机制真正不同的核心判断，"
                    "defense_decomposition、operational_review和winning_paths各最多3项，"
                    "每项按竞争假设/现役基线—关键机制—直接军事效果—对手反适应—失败边界"
                    "压缩为120至180字；assumptions和open_questions各最多2项。不得复述"
                    "场景Packet、来源摘要或相邻字段，完整细节留在结构化前置材料中。"
                    if set(indices) == {1, 2}
                    else ""
                )
                + (
                    "本Cohort含S4/S5：S4 concept_directions和S5 gap_assessment固定各保留4项"
                    "最高价值且一一对应的方向，capability_mapping最多4项、dotmlpf_matrix最多3项，"
                    "s6_preflight固定只写3个装备桶。若同时含S3，breakthrough_directions和effect_chain"
                    "各最多4项。所有数组元素最多140字；S4/S5对象字段各30至80字，除明确要求的数组外"
                    "每个字段只写一个完整句。优先给差异化判断、证据边界和验证闸门，禁止在相邻字段"
                    "重复背景、机理和军事价值；完整长画像统一留给S6确定性扩展。整个logical_results"
                    "必须是紧凑JSON，建议不超过7500字，不得用长段落消耗输出。"
                    if {4, 5}.issubset(set(indices))
                    else ""
                )
            ),
        }
        text = await host._run_core_json(
            f"winning_{cohort_id}",
            "你是制胜分析物理Cohort执行器。一次模型调用承载多个具有上下游关系的"
            "逻辑Agent，以减少重复上下文和检索；逻辑职责、因果顺序、证据引用和独立"
            "输出必须完整保留。topic决定研究议程，上游只提供事实、约束和反证，禁止把上游"
            "措辞直接扩写为下游结论。所有结论必须服务打击、歼灭、反制、拒止、威慑、抗毁或"
            "持续作战中的明确任务效果。兵棋或压力测试缺少校准数据时只能输出定性等级、比较排序、"
            "适用条件和置信度，禁止虚构精确百分比。只输出严格JSON。",
            cohort_input,
            {"logical_results": schemas},
            min(
                5600 if {4, 5}.issubset(set(indices)) else 7600,
                sum(
                    {
                        "light": 1800,
                        "standard": 2400,
                        "deep": 2800,
                    }.get(step_modes[index], 2400)
                    for index in indices
                ),
            ),
            phase=f"winning_{cohort_id}",
        )
        payload = _parse_json_object(text)
        logical_results = payload.get("logical_results", {})
        if not isinstance(logical_results, Mapping):
            logical_results = {}
        outcomes: list[dict[str, Any]] = []
        for index in indices:
            agent_id = steps[index - 1][0]
            schema = schemas[f"S{index}"]
            raw_result = logical_results.get(f"S{index}", {})
            result = dict(raw_result) if isinstance(raw_result, Mapping) else {}
            result = sanitize_references(result)
            missing_fields = [key for key in schema if key not in result]
            try:
                confidence = float(result.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            issues = [
                *(
                    [f"缺少结构化字段：{', '.join(missing_fields)}"]
                    if missing_fields
                    else []
                ),
                *(["步骤置信度低于0.65，需要残差复核"] if confidence < 0.65 else []),
            ]
            loop_trace.append(
                {
                    "loop": "inner",
                    "middle_cycle": middle_cycle,
                    "step": index,
                    "agent_id": agent_id,
                    "iteration": 1,
                    "passed": not issues,
                    "issues": issues,
                    "recommended_action": "pass" if not issues else "backtrack",
                    "physical_cohort_id": cohort_id,
                }
            )
            raw_node = result.pop("reasoning_node", {})
            reasoning_node = dict(raw_node) if isinstance(raw_node, Mapping) else {}
            outcomes.append(
                {
                    "result": result,
                    "assumptions": [
                        str(item)
                        for item in result.get("assumptions", [])
                        if str(item).strip()
                    ],
                    "open_questions": [
                        str(item)
                        for item in result.get("open_questions", [])
                        if str(item).strip()
                    ],
                    "reasoning_node": reasoning_node,
                    "run": {
                        "step": index,
                        "agent_id": agent_id,
                        "middle_cycle": middle_cycle,
                        "execution_mode": step_modes[index],
                        "confidence": result.get("confidence"),
                        "open_question_count": len(result.get("open_questions", [])),
                        "status": "completed" if result else "limited",
                        "reasoning_node": reasoning_node,
                        "next_action": reasoning_node.get("next_action", {}),
                        "critic_action": "pass" if not issues else "backtrack",
                        "critic_issues": issues,
                        "physical_cohort_id": cohort_id,
                        "logical_result_preserved": True,
                    },
                }
            )
        return outcomes

    async def run_tactic_validation_wave() -> None:
        concepts = accumulated.get("tactic_concepts", [])
        concept_rows = [dict(item) for item in concepts if isinstance(item, Mapping)][
            :3
        ]
        if aggressive_compaction and len(concept_rows) == 3:
            validations = []
            for index, concept in enumerate(concept_rows, start=1):
                tactic_id = str(concept.get("tactic_id") or f"T{index}")
                failure_conditions = [
                    str(item)
                    for item in concept.get("failure_conditions", [])
                    if str(item).strip()
                ][:3]
                evidence_refs = [
                    str(item)
                    for item in concept.get("evidence_refs", [])
                    if str(item) in valid_reference_ids
                ][:6]
                applicable_scenarios = [
                    str(item)
                    for item in concept.get("applicable_scenarios", [])
                    if str(item).strip()
                ][:6]
                validations.append(
                    {
                        "task_id": f"validation-{tactic_id}",
                        "tactic_id": tactic_id,
                        "public_evidence": evidence_refs,
                        "feasibility": "medium",
                        "counter_evidence": failure_conditions
                        or ["缺少独立反证时不得上调为高可行性"],
                        "technical_boundaries": [
                            "强电磁、弱网、节点损耗与目标信息过期必须同时进入压力测试",
                            "无校准数据时只比较任务链闭合等级，不给精确效能百分比",
                        ],
                        "failure_conditions": failure_conditions
                        or ["关键任务链在代表性对抗条件下不能闭合"],
                        "applicable_scenarios": applicable_scenarios,
                        "confidence": min(
                            0.76,
                            max(
                                0.65,
                                float(concept.get("confidence", 0.68) or 0.68),
                            ),
                        ),
                    }
                )
            accumulated["tactic_validation_results"] = validations
            accumulated["tactic_validation_tasks"] = [
                {
                    "task_id": str(item["task_id"]),
                    "tactic_id": str(item["tactic_id"]),
                    "validation_axes": [
                        "public_evidence",
                        "feasibility",
                        "counter_evidence",
                        "technical_boundary",
                    ],
                }
                for item in validations
            ]
            for item in validations:
                row = {
                    "step": 0,
                    "agent_id": f"tactic_validation_{item['tactic_id']}",
                    "middle_cycle": 1,
                    "execution_mode": "deterministic_frontloaded_validation",
                    "status": "completed",
                    "confidence": item["confidence"],
                    "physical_cohort_id": "tactic-validation-frontloaded",
                    "logical_result_preserved": True,
                }
                runs.append(row)
                host._emit_winning_progress(row)
            loop_trace.append(
                {
                    "loop": "validation",
                    "step": 2,
                    "event": "frontloaded_deterministic_validation",
                    "passed": True,
                    "issues": [],
                }
            )
            return
        text = await host._run_core_json(
            "tactic_validation_cohort",
            "你是A分支战法验证波次。对T1、T2、T3分别执行公开资料可行性核验、"
            "反证搜索、技术边界和失效条件审查。允许一次物理调用合并，但必须返回三份"
            "独立逻辑结果；不得合并结论或用精确百分比虚构兵棋结果。只输出严格JSON。",
            {
                "topic": shared["topic"],
                "tactic_concepts": concept_rows,
                "scenario_packets": [
                    item
                    for item in shared.get("packets", [])
                    if isinstance(item, Mapping)
                    and item.get("agent_id") == "combat_scenario"
                ],
                "evidence_index": shared.get("evidence_index", []),
                "valid_reference_ids": sorted(valid_reference_ids),
            },
            {
                "validations": [
                    {
                        "task_id": "validation-T1|validation-T2|validation-T3",
                        "tactic_id": "T1|T2|T3",
                        "public_evidence": ["exact evidence_id or packet_id"],
                        "feasibility": "high|medium|low",
                        "counter_evidence": ["string"],
                        "technical_boundaries": ["string"],
                        "failure_conditions": ["string"],
                        "applicable_scenarios": ["scenario_id"],
                        "confidence": "0..1",
                    }
                ]
            },
            4200,
            phase="tactic_validation_wave",
        )
        payload = _parse_json_object(text)
        validations = [
            sanitize_references(dict(item))
            for item in payload.get("validations", [])
            if isinstance(item, Mapping)
        ][:3]
        accumulated["tactic_validation_results"] = validations
        accumulated["tactic_validation_tasks"] = [
            {
                "task_id": str(item.get("task_id", f"validation-{index + 1}")),
                "tactic_id": str(item.get("tactic_id", f"T{index + 1}")),
                "validation_axes": [
                    "public_evidence",
                    "feasibility",
                    "counter_evidence",
                    "technical_boundary",
                ],
            }
            for index, item in enumerate(validations)
        ]
        for index, item in enumerate(validations, start=1):
            row = {
                "step": 0,
                "agent_id": f"tactic_validation_{item.get('tactic_id', index)}",
                "middle_cycle": 1,
                "execution_mode": "parallel_validation",
                "status": "completed",
                "confidence": item.get("confidence"),
                "physical_cohort_id": "tactic-validation-wave",
                "logical_result_preserved": True,
            }
            runs.append(row)
            host._emit_winning_progress(row)
        if len(validations) != 3:
            loop_trace.append(
                {
                    "loop": "validation",
                    "step": 2,
                    "passed": False,
                    "issues": [f"A分支需要3份独立战法验证，当前{len(validations)}份"],
                    "recommended_action": "backtrack",
                    "backtrack_to_step": 2,
                }
            )

    def commit_step(outcome: Mapping[str, Any]) -> None:
        row = dict(outcome["run"])
        index = int(row["step"])
        all_assumptions.extend(outcome.get("assumptions", []))
        all_open_questions.extend(outcome.get("open_questions", []))
        reasoning_node = dict(outcome.get("reasoning_node", {}))
        if reasoning_node:
            reasoning_nodes[str(index)] = reasoning_node
        step_result = dict(outcome["result"])
        if index == 4 and "concept_directions" in step_result:
            # S4 owns provisional mappings; S6 owns the final capability portrait.
            # A later S4 backtrack must never silently replace a completed S6 result.
            step_result["s4_concept_directions"] = step_result.pop("concept_directions")
        if index == 6:
            directions = step_result.get("concept_directions", [])
            direction_count = len(directions) if isinstance(directions, list) else 0
            if direction_count:
                normalized_nodes = _normalize_priority_references(
                    reasoning_nodes,
                    direction_count,
                )
                if isinstance(normalized_nodes, Mapping):
                    reasoning_nodes.clear()
                    reasoning_nodes.update(
                        {
                            str(key): dict(value)
                            for key, value in normalized_nodes.items()
                            if isinstance(value, Mapping)
                        }
                    )
        accumulated.update(step_result)
        accumulated["reasoning_nodes"] = dict(reasoning_nodes)
        runs.append(row)
        host._emit_winning_progress(row)

    # 真实数据依赖：S3←{S1,S2}，S4←{S3}，S5←{S4}，S6←{S4,S5}。
    # S5 必须消费 S4 的能力映射/约束矩阵后才能做装备差距排序，避免
    # 跨步跳跃触发整段 S3-S6 回溯。
    step_dependency_map = core_step_dependency_map

    def plan_step_waves(selected: set[int]) -> list[tuple[int, ...]]:
        """依据分支蓝图激活的步骤拓扑排布可并行波次。

        skip/复用步骤视为依赖已满足（其结论经 prior 累积上下文提供）。
        全量激活时等价于静态波次 ((1,2),(3,),(4,),(5,),(6,))；分支裁剪或
        定向重跑时波次自动收缩，减少串行轮次。
        """
        pending = sorted(selected)
        satisfied = {index for index in range(1, 7) if index not in selected}
        waves: list[tuple[int, ...]] = []
        while pending:
            wave = tuple(
                index
                for index in pending
                if all(dep in satisfied for dep in step_dependency_map[index])
            )
            if not wave:
                wave = (pending[0],)
            waves.append(wave)
            satisfied.update(wave)
            pending = [index for index in pending if index not in wave]
        return waves

    async def run_step_waves(
        selected_steps: Sequence[int],
        *,
        middle_cycle: int,
        middle_feedback: list[str] | None = None,
    ) -> None:
        selected = set(selected_steps)
        if shared["execution_profile_id"] == "optimized_v2" and middle_cycle == 1:
            selected_cohorts = [
                cohort for cohort in physical_cohorts if set(cohort) <= selected
            ]
            cohort_members = {step for cohort in selected_cohorts for step in cohort}
            units: list[tuple[int, ...]] = [
                *selected_cohorts,
                *((step,) for step in sorted(selected - cohort_members)),
            ]
            pending_units = list(units)
            satisfied = {step for step in range(1, 7) if step not in selected}
            dependency_map = step_dependency_map
            while pending_units:
                ready_units = [
                    unit
                    for unit in pending_units
                    if all(
                        dependency in satisfied or dependency in unit
                        for step in unit
                        for dependency in dependency_map[step]
                    )
                ]
                if not ready_units:
                    ready_units = [pending_units[0]]
                if (
                    primary_branch == "A"
                    and any(3 in unit for unit in ready_units)
                    and "tactic_validation_results" not in accumulated
                ):
                    if host._optional_work_allowed(
                        priority="critical",
                        minimum_remaining_seconds=180.0,
                    ):
                        await run_tactic_validation_wave()
                    else:
                        accumulated["tactic_validation_budget_skipped"] = True
                        loop_trace.append(
                            {
                                "loop": "validation",
                                "event": "deadline_skip",
                                "passed": True,
                                "issues": [
                                    "运行进入截止收敛区间，跳过可选战法验证波次。"
                                ],
                            }
                        )
                prior = dict(accumulated)

                async def execute_unit(unit: tuple[int, ...]) -> list[dict[str, Any]]:
                    if len(unit) > 1:
                        return await run_physical_cohort(
                            unit,
                            middle_cycle=middle_cycle,
                            prior_step_outputs=prior,
                            middle_feedback=middle_feedback,
                        )
                    return [
                        await run_step(
                            unit[0],
                            middle_cycle=middle_cycle,
                            prior_step_outputs=prior,
                            middle_feedback=middle_feedback,
                        )
                    ]

                batches = await asyncio.gather(
                    *(execute_unit(unit) for unit in ready_units)
                )
                for outcomes in batches:
                    for outcome in sorted(
                        outcomes, key=lambda item: int(item["run"]["step"])
                    ):
                        commit_step(outcome)
                for unit in ready_units:
                    satisfied.update(unit)
                    pending_units.remove(unit)
            return
        use_pipeline = (
            os.environ.get(
                "EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER",
                "1",
            ).strip()
            != "0"
        )
        if not use_pipeline:
            # 传统固定波次调度（向后兼容，设 =0 可回退）。
            for wave in plan_step_waves(selected):
                prior_step_outputs = dict(accumulated)
                outcomes = await asyncio.gather(
                    *(
                        run_step(
                            index,
                            middle_cycle=middle_cycle,
                            prior_step_outputs=prior_step_outputs,
                            middle_feedback=middle_feedback,
                        )
                        for index in wave
                    )
                )
                for outcome in sorted(
                    outcomes,
                    key=lambda item: int(item["run"]["step"]),
                ):
                    commit_step(outcome)
            return

        # 动态流水线调度：步骤依赖满足后立即启动，无需等待同波次
        # 其他步骤。skip/复用步骤视为依赖已满足；提交后立即唤醒调度器
        # 检查新就绪步骤，使 S4 完成即可启动 S6（若 S5 也已完成）。
        satisfied = {index for index in range(1, 7) if index not in selected}
        pending = set(selected)
        running: dict[int, asyncio.Task] = {}
        failures: list[BaseException] = []
        wake = asyncio.Event()

        async def run_and_commit(index: int) -> None:
            try:
                outcome = await run_step(
                    index,
                    middle_cycle=middle_cycle,
                    prior_step_outputs=dict(accumulated),
                    middle_feedback=middle_feedback,
                )
                commit_step(outcome)
                satisfied.add(index)
            except BaseException as exc:
                failures.append(exc)
            finally:
                running.pop(index, None)
                wake.set()

        while pending or running:
            if failures:
                pending_tasks = list(running.values())
                for task in pending_tasks:
                    task.cancel()
                if pending_tasks:
                    await asyncio.gather(
                        *pending_tasks,
                        return_exceptions=True,
                    )
                raise failures[0]
            ready = sorted(
                index
                for index in pending
                if all(dep in satisfied for dep in step_dependency_map[index])
            )
            for index in ready:
                pending.discard(index)
                running[index] = asyncio.create_task(run_and_commit(index))
            if not running:
                # 依赖无法满足（异常情况）：退化为串行启动剩余步骤。
                if pending:
                    fallback = min(pending)
                    pending.discard(fallback)
                    running[fallback] = asyncio.create_task(run_and_commit(fallback))
                else:
                    break
            wake.clear()
            await wake.wait()
        if failures:
            raise failures[0]

    core_swarm_schedule = swarm_controller.plan_core_schedule(
        active_steps=active_steps,
        step_modes=step_modes,
        physical_cohorts=physical_cohorts,
        dependency_map=core_step_dependency_map,
    )

    try:
        if dynamic_swarm_enabled:
            await execute_dynamic_mission_graph()
            # The dynamic Mission Graph owns S1-S5 candidate generation,
            # competition and evidence closure, but it deliberately does
            # not author user-facing capability portraits.  Always hand
            # the selected portfolio to the dedicated parallel S6 writer
            # before evaluating the delivery gate.  Previously the
            # portfolio was validated as if it were already an S6 result,
            # so upstream audit wording or a provisional title could fail
            # the run without any S6 Codex session ever starting.
            if 6 in active_steps:
                await run_step_waves([6], middle_cycle=1)
        elif swarm_enabled:
            early_steps = [index for index in active_steps if index in {1, 2}]
            first_wave_units = [execute_swarm_breadth()]
            if early_steps:
                first_wave_units.append(run_step_waves(early_steps, middle_cycle=1))
            first_wave_results = await asyncio.gather(
                *first_wave_units,
                return_exceptions=True,
            )
            for outcome in first_wave_results:
                if isinstance(outcome, BaseException) and not (
                    isinstance(outcome, (RuntimeError, TimeoutError, ValueError))
                    and _is_harness_budget_error(outcome)
                ):
                    raise outcome
            await execute_swarm_challenges()
            await execute_swarm_convergence()
            remaining_steps = [index for index in active_steps if index not in {1, 2}]
            if remaining_steps:
                await run_step_waves(remaining_steps, middle_cycle=1)
        else:
            await run_step_waves(active_steps, middle_cycle=1)
    except (RuntimeError, TimeoutError, ValueError) as exc:
        if isinstance(exc, S6QualityError):
            raise
        deadline_state = host._deadline_state(priority="critical")
        deadline_limited = (
            _is_harness_budget_error(exc) or deadline_state.get("mode") != "normal"
        )
        if not deadline_limited:
            raise
        accumulated["winning_deadline_limited"] = True
        accumulated["winning_deadline_reason"] = type(exc).__name__
        loop_trace.append(
            {
                "loop": "winning",
                "cycle": 1,
                "event": "deadline_finalize",
                "passed": True,
                "issues": [
                    "制胜主链到达收敛时限，保留已完成步骤并停止启动新的深度调用。"
                ],
            }
        )

    for index in range(1, len(steps) + 1):
        if index in active_steps:
            continue
        skipped_row = {
            "step": index,
            "agent_id": steps[index - 1][0],
            "middle_cycle": 1,
            "execution_mode": (step_modes[index] if requested_resume_steps else "skip"),
            "status": (
                "reused_from_prior_analysis"
                if requested_resume_steps
                else "skipped_by_branch_blueprint"
            ),
        }
        runs.append(skipped_row)
        host._emit_winning_progress(skipped_row)

    inner_failures = _latest_inner_loop_failures(loop_trace)
    failed_inner_steps = {
        int(item.get("step", 0) or 0)
        for item in inner_failures
        if int(item.get("step", 0) or 0) in range(1, 7)
    }
    deadline_skip_round_critic = not host._optional_work_allowed(
        priority="normal",
        minimum_remaining_seconds=180.0,
    )
    exhausted_s6_repair = failed_inner_steps == {6} and s6_model_repair_used
    skip_round_critic = (
        (not model_loop_critics and not inner_failures)
        or deadline_skip_round_critic
        or exhausted_s6_repair
    )
    deterministic_round_review = {
        "passed": not inner_failures,
        "rerun_from_step": 0,
        "issues": [
            str(issue) for item in inner_failures for issue in item.get("issues", [])
        ][:8],
        "affected_fields": [],
        "rerun_guidance": [],
        "rerun_steps": [],
        "requires_new_evidence": False,
        "evidence_requests": [],
    }
    round_review_text = json.dumps(
        deterministic_round_review,
        ensure_ascii=False,
    )
    if deadline_skip_round_critic and inner_failures:
        accumulated["round_critic_budget_skipped"] = True
        accumulated["middle_loop_limited"] = True
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 1,
                "event": "deadline_skip",
                "passed": False,
                "issues": [
                    "剩余时间不足以启动可选中循环批判；保留最新步骤结果并标记受限。"
                ],
            }
        )
    elif exhausted_s6_repair:
        accumulated["s6_additional_review_skipped"] = True
        accumulated["middle_loop_limited"] = True
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 1,
                "event": "repair_exhausted",
                "passed": False,
                "issues": [
                    "S6已使用唯一卡片级模型修复，不再启动无新增证据的批判和回跑。"
                ],
            }
        )
    if not skip_round_critic:
        try:
            round_review_text = await host._run_core_json(
                "winning_round_critic",
                "你是制胜机理中循环批判Agent。检查S1-S6之间的因果连续性、证据一致性、"
                "路线侧重、遗漏维度、军事任务效果和能力图像可追溯性。流程完整但缺少打击、歼灭、"
                "反制、拒止、威慑、抗毁或持续作战作用机理及失效边界时不得通过。必要时指定最早回溯点和最小受影响步骤集合；"
                "不要因上游轻微措辞或引用格式问题机械重跑所有稳定下游步骤。若问题必须新增证据才能"
                "解决，设置requires_new_evidence=true，并最多给出2个窄化补证任务；每个任务只指定"
                "一个最匹配的已选业务Agent、1个明确问题和受影响S步骤，不得要求重跑基线。只输出严格JSON。",
                {
                    "topic": shared["topic"],
                    "research_route": shared["research_route"],
                    "discovery_blueprint": step_shared_context(6).get(
                        "discovery_blueprint", {}
                    ),
                    "packet_index": (
                        military_packet_refs_for_claims(military_value_claims)
                        if optimized_v2
                        else packet_index
                    ),
                    "valid_evidence_ids": [
                        str(item.get("evidence_id", ""))
                        for item in shared.get("evidence_index", [])
                        if isinstance(item, Mapping)
                        and str(item.get("evidence_id", "")).strip()
                    ],
                    "six_step_outputs": round_review_projection(accumulated),
                    "inner_critic_findings": [
                        {
                            "step": item.get("step"),
                            "recommended_action": item.get("recommended_action"),
                            "issues": item.get("issues", []),
                            "backtrack_to_step": item.get("backtrack_to_step", 0),
                            "recall_target": item.get("recall_target", ""),
                        }
                        for item in loop_trace
                        if item.get("loop") == "inner"
                        and item.get("passed") is not True
                    ],
                    "allowed_target_agent_ids": list(
                        shared.get("selected_business_agent_ids", [])
                    ),
                    "winning_step_plan": shared["winning_step_plan"],
                    "review_contract": (
                        "execution_mode=skip的步骤按分支蓝图视为依赖已满足，不得因缺少该步骤输出判失败，"
                        "也不得把skip步骤指定为rerun_from_step。只指出实际激活步骤中的证据或因果缺口。"
                    ),
                },
                {
                    "passed": "boolean",
                    "rerun_from_step": "1..6 or 0",
                    "issues": ["string"],
                    "affected_fields": [
                        "defense_decomposition|operational_review|winning_paths|"
                        "breakthrough_directions|effect_chain|capability_mapping|"
                        "dotmlpf_matrix|gap_assessment"
                    ],
                    "rerun_guidance": ["string"],
                    "rerun_steps": ["1..6"],
                    "requires_new_evidence": "boolean",
                    "evidence_requests": [
                        {
                            "question": "single narrow evidence question",
                            "target_agent_id": "one allowed business agent id",
                            "affected_steps": ["1..6"],
                            "source_preferences": [
                                "primary or authoritative source type"
                            ],
                            "reason": "why this evidence can change the conclusion",
                        }
                    ],
                },
                1600,
                phase="winning_round_review",
            )
        except (RuntimeError, TimeoutError) as exc:
            if not _is_harness_budget_error(exc):
                raise
            accumulated["round_critic_budget_skipped"] = True
            loop_trace.append(
                {
                    "loop": "middle",
                    "cycle": 1,
                    "event": "budget_skip",
                    "passed": True,
                    "issues": [
                        "可选中循环模型批判因运行预算到达而跳过；"
                        "已使用步骤内批判结果继续确定性门控。"
                    ],
                }
            )
    round_review = _parse_json_object(round_review_text)
    try:
        rerun_from = int(round_review.get("rerun_from_step", 0) or 0)
    except (TypeError, ValueError):
        rerun_from = 0
    middle_passed = round_review.get("passed") is True
    loop_trace.append(
        {
            "loop": "middle",
            "cycle": 1,
            "passed": middle_passed,
            "rerun_from_step": rerun_from,
            "issues": [str(item) for item in round_review.get("issues", [])][:6],
        }
    )
    # A skipped step is an intentional branch decision, not shorthand for the
    # next active step. Reject the critic's skipped target instead of silently
    # remapping it and paying for an unrelated rerun.
    if rerun_from not in active_steps:
        rerun_from = 0
    requires_new_evidence = round_review.get("requires_new_evidence") is True
    allowed_targets = {
        str(item)
        for item in shared.get("selected_business_agent_ids", [])
        if str(item).strip()
    }
    targeted_requests: list[dict[str, Any]] = []
    if requires_new_evidence:
        for item in round_review.get("evidence_requests", []):
            if not isinstance(item, Mapping):
                continue
            question = str(item.get("question", "")).strip()
            target_agent_id = str(item.get("target_agent_id", "")).strip()
            if not question or target_agent_id not in allowed_targets:
                continue
            affected_steps: list[int] = []
            for raw_step in item.get("affected_steps", []):
                try:
                    step = int(raw_step)
                except (TypeError, ValueError):
                    continue
                if step in range(1, 7) and step not in affected_steps:
                    affected_steps.append(step)
            targeted_requests.append(
                {
                    "question": question,
                    "target_agent_id": target_agent_id,
                    "affected_steps": affected_steps or [4, 5, 6],
                    "source_preferences": [
                        str(value)
                        for value in item.get("source_preferences", [])
                        if str(value).strip()
                    ][:3],
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
            if len(targeted_requests) >= 2:
                break
    if (
        not middle_passed
        and (targeted_requests or rerun_from)
        and not host._optional_work_allowed(
            priority="critical",
            minimum_remaining_seconds=180.0,
        )
    ):
        accumulated["middle_backtrack_budget_skipped"] = True
        accumulated["middle_loop_limited"] = True
        targeted_requests = []
        rerun_from = 0
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 2,
                "event": "deadline_skip",
                "passed": False,
                "issues": [
                    "中循环复核结束时已进入截止收敛区间，取消补证与回溯，保留最新检查点。"
                ],
            }
        )
    if targeted_requests:
        accumulated["evidence_supplement_pending"] = True
        accumulated["targeted_evidence_requests"] = targeted_requests
        accumulated["suggested_resume_steps"] = sorted(
            {
                *(
                    step
                    for request in targeted_requests
                    for step in request["affected_steps"]
                ),
                6,
            }
        )
    elif not middle_passed and rerun_from:
        feedback = [str(item) for item in round_review.get("rerun_guidance", [])][:8]
        requested_steps = []
        for item in round_review.get("rerun_steps", []):
            try:
                step = int(item)
            except (TypeError, ValueError):
                continue
            if step in active_steps and step not in requested_steps:
                requested_steps.append(step)
        failed_inner_steps = {
            int(item.get("step", 0) or 0)
            for item in inner_failures
            if item.get("passed") is not True
        }
        if failed_inner_steps == {6} and 6 in active_steps:
            # A bounded S6 repair must never drag the stable S4 mapping
            # back into another expensive model call. If the only failed
            # inner gate belongs to S6, the middle-cycle residual is S6.
            requested_steps = [6]
        issue_text = " ".join(
            str(item) for item in round_review.get("issues", [])
        ).lower()
        traceability_only = (
            bool(issue_text)
            and any(
                marker in issue_text
                for marker in (
                    "索引",
                    "编号",
                    "derived_from",
                    "可追溯",
                    "引用",
                    "承接说明",
                    "承接不足",
                )
            )
            and not any(
                marker in issue_text
                for marker in (
                    "能力方向缺失",
                    "差距等级错误",
                    "优先级错误",
                    "证据矛盾",
                    "结论错误",
                    "需要新增证据",
                )
            )
        )
        if traceability_only:
            # When the critic identifies the final image as the earliest
            # affected step, S4 is already stable and must not be paid for
            # again. Only include S4 when the backtrack genuinely begins
            # at or before the mapping layer.
            repair_candidates = (6,) if rerun_from >= 6 else (4, 6)
            requested_steps = [
                step for step in repair_candidates if step in active_steps
            ]
        if not requested_steps:
            # 智能回溯：依据 critic 标注的受影响字段，只重跑真正受影响的
            # 下游步骤，而非机械重跑 rerun_from 之后的全部步骤。
            # 字段级影响映射：(字段, 产出步骤) -> 受影响的下游步骤集合。
            field_impact_map = {
                ("defense_decomposition", 1): {2, 3},
                ("operational_review", 2): {3, 6},
                ("winning_paths", 2): {3, 6},
                ("breakthrough_directions", 3): {4},
                ("effect_chain", 3): {4, 6},
                ("capability_mapping", 4): {5, 6},
                ("dotmlpf_matrix", 4): {6},
                ("gap_assessment", 5): {6},
            }
            affected_fields = [
                str(item)
                for item in round_review.get("affected_fields", [])
                if str(item).strip()
            ]
            if affected_fields:
                impacted: set[int] = {rerun_from}
                for field in affected_fields:
                    impacted.add(rerun_from)
                    impacted.update(field_impact_map.get((field, rerun_from), set()))
                requested_steps = sorted(
                    index for index in active_steps if index in impacted
                )
            if not requested_steps:
                # 无字段信息时退回粗粒度：rerun_from 之后的全部激活步骤。
                requested_steps = [
                    index for index in active_steps if index >= rerun_from
                ]
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 2,
                "event": "intelligent_backtrack",
                "rerun_from_step": rerun_from,
                "rerun_steps": requested_steps,
                "affected_fields": [
                    str(item) for item in round_review.get("affected_fields", [])
                ][:8],
            }
        )
        middle_rerun_completed = True
        try:
            await run_step_waves(
                requested_steps,
                middle_cycle=2,
                middle_feedback=feedback,
            )
        except (RuntimeError, TimeoutError, ValueError) as exc:
            deadline_state = host._deadline_state(priority="critical")
            if not (
                _is_harness_budget_error(exc) or deadline_state.get("mode") != "normal"
            ):
                raise
            middle_rerun_completed = False
            accumulated["middle_backtrack_budget_skipped"] = True
            accumulated["middle_loop_limited"] = True

        residual_inner_failures = [
            item
            for item in loop_trace
            if item.get("loop") == "inner"
            and int(item.get("middle_cycle", 1) or 1) == 2
            and item.get("passed") is not True
        ]
        run_model_rereview = (
            model_loop_critics
            and middle_rerun_completed
            and host._optional_work_allowed(
                priority="normal",
                minimum_remaining_seconds=120.0,
            )
        )
        if not run_model_rereview:
            accumulated["round_rereview_budget_skipped"] = True
            second_review = {
                "passed": middle_rerun_completed and not residual_inner_failures,
                "issues": [
                    "使用残差步骤的本地结构、证据与置信度门控完成二次复核；"
                    + (
                        "未发现新的步骤内失败。"
                        if middle_rerun_completed and not residual_inner_failures
                        else "仍有未闭合问题，结果保留并标记受限。"
                    )
                ],
            }
            loop_trace.append(
                {
                    "loop": "middle",
                    "cycle": 2,
                    "event": "deterministic_rereview",
                    "passed": second_review["passed"],
                    "issues": list(second_review["issues"]),
                }
            )
        else:
            try:
                second_review_text = await host._run_core_json(
                    "winning_round_critic",
                    "你是制胜机理中循环批判Agent。复核回溯后的S1-S6因果连续性、证据一致性、"
                    "路线侧重、军事任务价值和能力图像可追溯性。已达到中循环上限，只输出是否通过和剩余问题。",
                    {
                        "topic": shared["topic"],
                        "research_route": shared["research_route"],
                        "packet_index": (
                            military_packet_refs_for_claims(military_value_claims)
                            if optimized_v2
                            else packet_index
                        ),
                        "middle_cycle": 2,
                        "six_step_outputs": round_review_projection(accumulated),
                        "winning_step_plan": shared["winning_step_plan"],
                        "review_contract": "skip步骤不得作为缺失项或失败原因。",
                    },
                    {"passed": "boolean", "issues": ["string"]},
                    1200,
                    phase="winning_round_rereview",
                )
                second_review = _parse_json_object(second_review_text)
            except (RuntimeError, TimeoutError) as exc:
                if not _is_harness_budget_error(exc):
                    raise
                # A missed optional re-review must not discard the latest
                # valid residual checkpoint.
                accumulated["round_rereview_budget_skipped"] = True
                second_review = {
                    "passed": not residual_inner_failures,
                    "issues": [
                        "可选二次中循环复核因运行预算到达而跳过；"
                        + (
                            "保留已通过步骤内批判的残差修订结果。"
                            if not residual_inner_failures
                            else "残差步骤内门控仍有问题，保留结果但继续标记受限。"
                        )
                    ],
                }
                loop_trace.append(
                    {
                        "loop": "middle",
                        "cycle": 2,
                        "event": "budget_skip",
                        "passed": second_review["passed"],
                        "issues": list(second_review["issues"]),
                    }
                )
        second_passed = second_review.get("passed") is True
        loop_trace.append(
            {
                "loop": "middle",
                "cycle": 2,
                "passed": second_passed,
                "rerun_from_step": rerun_from,
                "issues": [str(item) for item in second_review.get("issues", [])][:6],
            }
        )
        accumulated["middle_loop_limited"] = not second_passed
    final_s6_handoff = _capability_synthesis_handoff(
        topic=shared["topic"],
        branch=primary_branch,
        prior_step_outputs=accumulated,
        evidence_index=shared.get("evidence_index", []),
        s6_parallelism=int(
            host._runtime_budgets.get("s6_codex_concurrency", 6)
        ),
    )
    if not [
        item
        for item in accumulated.get("concept_directions", [])
        if isinstance(item, Mapping) and str(item.get("name", "")).strip()
    ] and accumulated.get("winning_deadline_limited"):
        accumulated["s6_card_authoring_limited"] = True
        accumulated.setdefault("s6_card_authoring_warnings", []).append(
            "S6在收敛时限内未形成新画像，保留S5冻结组合并继续受限交付"
        )
    dynamic_portfolio = (
        accumulated.get("winning_swarm", {}).get("final_equipment_portfolio", [])
        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
        else []
    )
    if dynamic_swarm_enabled and dynamic_portfolio:
        # The expert-selected portfolio remains authoritative for weapon
        # membership and identity.  Preserve the parallel S6 sessions'
        # equipment-specific scenes, processes and capability portraits;
        # replacing them with deterministic merge-stage drafts discards
        # the most valuable user-facing work and reintroduces templates.
        accumulated["concept_directions"] = (
            _merge_dynamic_portfolio_with_s6_authored_cards(
                dynamic_portfolio,
                accumulated.get("concept_directions", []),
            )
        )
        accumulated["capability_synthesis"] = [
            str(item.get("name", ""))
            for item in dynamic_portfolio
            if str(item.get("name", "")).strip()
        ]
        expert_scores = [
            float(item["expert_score"])
            for item in dynamic_portfolio
            if isinstance(item.get("expert_score"), (int, float))
        ]
        if expert_scores:
            accumulated["confidence"] = sum(expert_scores) / len(expert_scores)
        normalized_dynamic = _normalize_s6_deterministic_format(
            {
                "concept_directions": accumulated["concept_directions"],
                "confidence": accumulated.get("confidence", 0.68),
            },
            topic=str(shared.get("topic", "")),
        )
        normalized_dynamic = _normalize_concept_direction_priorities(normalized_dynamic)
        accumulated["concept_directions"] = list(
            normalized_dynamic.get("concept_directions", [])
        )
        accumulated["capability_synthesis"] = [
            str(item.get("name", ""))
            for item in accumulated["concept_directions"]
            if isinstance(item, Mapping) and str(item.get("name", "")).strip()
        ]
        winning_swarm_summary = accumulated.get("winning_swarm", {})
        if isinstance(winning_swarm_summary, dict):
            # Keep every delivery surface on the same authoritative,
            # normalized S6 cards. Otherwise the UI/swarm audit retains
            # pre-normalization titles while capability_images.json and
            # the report consume the compact final names and portraits.
            winning_swarm_summary["final_equipment_portfolio"] = [
                dict(item)
                for item in accumulated["concept_directions"]
                if isinstance(item, Mapping)
            ]
    final_s6_all_issues = (
        _capability_direction_quality_issues(
            accumulated,
            handoff=final_s6_handoff,
        )
        if host.provider.__class__.__module__
        != "equipment_deep_research.providers.fake"
        else []
    )
    # The final deterministic evaluation is authoritative.  Do not append
    # stale first-pass critic messages after local normalization or the one
    # bounded card repair has already resolved them; doing so previously
    # made L1-L3 fail on an obsolete title/support diagnosis.
    final_s6_all_issues = list(dict.fromkeys(final_s6_all_issues))[:32]
    final_s6_issues = (
        []
        if dynamic_swarm_enabled
        else _s6_portrait_repair_issues(final_s6_all_issues)
    )
    s6_low_repair_attempted = bool(s6_model_repair_used)
    s6_low_repair_error = ""
    if final_s6_issues and not s6_model_repair_used:
        # All modes receive one bounded low-reasoning repair for substantive
        # content/evidence defects. Diversity, count and style findings are
        # front-loaded as generation guidance and remain warnings here.
        s6_low_repair_attempted = True
        repair_targets = _s6_repair_targets(accumulated, final_s6_issues)
        portrait_module_targets = _s6_portrait_module_repair_targets(
            accumulated,
            final_s6_issues,
        )
        current_directions = accumulated.get("concept_directions", [])
        target_cards = [
            {
                "position": position,
                "direction": current_directions[position - 1],
            }
            for position in repair_targets
            if isinstance(current_directions, list)
            and 1 <= position <= len(current_directions)
        ]
        protected_cards = [
            {
                "position": position,
                "name": str(item.get("name", "")),
                "type": str(item.get("type", "")),
            }
            for position, item in enumerate(current_directions, start=1)
            if isinstance(item, Mapping) and position not in repair_targets
        ]
        emit_swarm_event(
            "winning_s6_low_repair_started",
            repair_targets=repair_targets,
            issues=final_s6_issues[:8],
            reasoning_effort="low",
        )
        try:
            direction_schema = steps[5][2]["concept_directions"][0]
            if portrait_module_targets:
                async def repair_portrait_modules(
                    target: Mapping[str, Any],
                ) -> list[Mapping[str, Any]]:
                    position = int(target["position"])
                    repair_text = await host._run_core_json(
                        "winning_s6_image",
                        "你是S6能力画像单模块修复Agent。只重写repair_modules列出的失败模块；"
                        "不得返回、改写或同义改写其他模块，也不得改变装备名称、身份、顺序、"
                        "发射域、目标、结构化事实或证据字段。能力画像是决策短卡，不是报告；修复模块没有"
                        "最低字数、固定句数或统一句式，只保留该栏独有且改变军事判断的信息。"
                        + CAPABILITY_PORTRAIT_CONCISION_GUIDANCE
                        + "技术栏由Codex结合本装备重新判断关键"
                        "技术痛点，讲清原理、具体实现、解除的限制和工程边界，不套固定技术链或组件清单；流程栏"
                        "落到具体战役/战斗场景和交战时序；效果栏只写战果、能力与验收轴；制胜栏"
                        "选择最强创新焦点，讲清该装备颠覆的常规制胜手段、创造的新战法、改写的交战"
                        "关系以及形成的决定性优势；不得写基线综述、技术清单、流程复述、失效、证据、"
                        "成熟度、验证或发展信息，不得使用箭头或分步骤展开。"
                        "只输出严格JSON。",
                        {
                            "parallel_card_id": f"s6-card-{position}",
                            "query": shared["topic"],
                            "repair_target": target,
                            "repair_modules": portrait_module_targets[position],
                            "repair_issues": [
                                issue
                                for issue in final_s6_issues
                                if f"第{position}项" in issue
                            ],
                        },
                        {
                            "portrait_module_repairs": [
                                {
                                    "position": "1-based integer from repair_target",
                                    "module_repairs": [
                                        {
                                            "module": "overview|technology_implementation|operational_process|capability_effects|winning_logic",
                                            "content": "仅对应失败模块的精简正文，不含栏目标题；写到该栏独有结论完整即停止",
                                        }
                                    ],
                                }
                            ]
                        },
                        min(
                            2400,
                            700
                            + 400
                            * max(1, len(portrait_module_targets[position])),
                        ),
                        phase=f"winning_s6_portrait_module_repair_{position:02d}",
                    )
                    parsed = _parse_json_object(repair_text)
                    rows = parsed.get("portrait_module_repairs", [])
                    allowed_modules = set(portrait_module_targets[position])
                    filtered_rows: list[Mapping[str, Any]] = []
                    for item in rows:
                        if not isinstance(item, Mapping):
                            continue
                        filtered_rows.append(
                            {
                                "position": position,
                                "module_repairs": [
                                    row
                                    for row in item.get("module_repairs", [])
                                    if isinstance(row, Mapping)
                                    and str(row.get("module", ""))
                                    in allowed_modules
                                ],
                            }
                        )
                    return filtered_rows

                repair_outcomes = await asyncio.gather(
                    *(repair_portrait_modules(target) for target in target_cards),
                    return_exceptions=True,
                )
                repair = {
                    "portrait_module_repairs": [
                        row
                        for outcome in repair_outcomes
                        if isinstance(outcome, list)
                        for row in outcome
                    ]
                }
            else:
                repair_text = await host._run_core_json(
                "winning_s6_image",
                "你是动态蜂群交付前的S6低成本快速修复Agent。只重写repair_targets指定卡片，"
                "不得改变任何卡片的装备名称、顺序、类型或主装备身份；direction.name必须逐字复制"
                "repair_targets中原卡名称。名称问题必须退回S3–S5，S6只修复能力画像内容。"
                "不得改变protected_cards的内容。优先修复内容缺失和证据错配："
                "补齐真实作战阶段与地域、敌方目标/威胁及反制、我方具体武器装备主体、"
                "由该装备部署/值班方式、发射或释放域、感知授权、效应方式、战果判定与再组织逻辑"
                "自然推导、步骤数由真实交战因果链决定的专属流程和直接战果；禁止套用跨卡共享流程骨架；"
                "每张重写卡必须完整保留schema字段，并在同次输出前完成整卡语义自检；"
                "semantic_consistency_check.consistent必须使用JSON布尔值true而不是字符串。"
                "若问题涉及卡片重复，不得在S6替换装备或改名，应保持原候选并让发布门退回S3–S5处理；"
                "具名型号或装备族不要求存在同型号对象级公开证据；可保留相邻基线或通用场景引用，"
                "有引用时尽量写清用途与推演边界；没有公开引用也不得因此失败，未验证部分可纳入失效条件与验证淘汰路径。字数不是通过或失败条件，"
                "不要为压缩或扩写而损害事实、因果和可读性。"
                + CAPABILITY_PORTRAIT_CONCISION_GUIDANCE
                + "只输出严格JSON。",
                {
                    "query": shared["topic"],
                    "branch": primary_branch,
                    "capability_synthesis_handoff": final_s6_handoff,
                    "repair_targets": target_cards,
                    "protected_cards": protected_cards,
                    "repair_issues": final_s6_issues,
                    "valid_evidence_ids": sorted(
                        {
                            str(item.get("evidence_id", ""))
                            for item in final_s6_handoff.get("public_evidence", [])
                            if isinstance(item, Mapping)
                            and str(item.get("evidence_id", "")).strip()
                        }
                    ),
                },
                {
                    "direction_repairs": [
                        {
                            "position": "1-based integer from repair_targets",
                            "direction": direction_schema,
                        }
                    ]
                },
                min(4200, 1400 + 700 * max(1, len(repair_targets))),
                phase="winning_s6_card_repair",
                )
                repair = _parse_json_object(repair_text)
            if repair:
                repaired = (
                    _merge_s6_portrait_module_repairs(accumulated, repair)
                    if portrait_module_targets
                    else _merge_s6_direction_repairs(accumulated, repair)
                )
                repaired = _normalize_s6_deterministic_format(
                    repaired,
                    topic=str(shared.get("topic", "")),
                )
                repaired = _normalize_concept_direction_priorities(repaired)
                accumulated["concept_directions"] = list(
                    repaired.get("concept_directions", [])
                )
                accumulated["capability_synthesis"] = [
                    str(item.get("name", ""))
                    for item in accumulated["concept_directions"]
                    if isinstance(item, Mapping) and str(item.get("name", "")).strip()
                ]
                winning_swarm_summary = accumulated.get("winning_swarm", {})
                if isinstance(winning_swarm_summary, dict):
                    winning_swarm_summary["final_equipment_portfolio"] = [
                        dict(item)
                        for item in accumulated["concept_directions"]
                        if isinstance(item, Mapping)
                    ]
            final_s6_all_issues = list(
                dict.fromkeys(
                    _capability_direction_quality_issues(
                        accumulated,
                        handoff=final_s6_handoff,
                    )
                )
            )[:32]
            final_s6_issues = (
                []
                if dynamic_swarm_enabled
                else _s6_portrait_repair_issues(final_s6_all_issues)
            )
            emit_swarm_event(
                "winning_s6_low_repair_completed",
                repair_targets=repair_targets,
                remaining_issues=final_s6_all_issues[:8],
                passed=not final_s6_issues,
                reasoning_effort="low",
            )
        except Exception as exc:
            s6_low_repair_error = f"{type(exc).__name__}: {exc}"
            emit_swarm_event(
                "winning_s6_low_repair_limited",
                repair_targets=repair_targets,
                issues=final_s6_issues[:8],
                failure_type=type(exc).__name__,
                reasoning_effort="low",
            )

    # Dynamic-v2 quality is front-loaded into the Query, frozen card and one
    # strong S6 authoring turn. Deterministic text-shape checks remain visible
    # as diagnostics, but they neither rewrite nor block a semantically
    # consistent authored card.
    residual_s6_issues = list(final_s6_issues)
    nonblocking_s6_warnings = [
        issue for issue in final_s6_all_issues if issue not in set(residual_s6_issues)
    ]
    s6_release_state = _s6_release_gate_state(
        residual_s6_issues,
        nonblocking_s6_warnings,
    )
    accumulated["s6_quality_gate_passed"] = s6_release_state["passed"]
    accumulated["s6_quality_gate_failed"] = s6_release_state["failed"]
    accumulated["s6_quality_gate_limited"] = s6_release_state["limited"]
    accumulated["s6_quality_gate_issues"] = s6_release_state["issues"]
    accumulated["s6_quality_warnings"] = s6_release_state["warnings"]
    accumulated["s6_low_repair_attempted"] = s6_low_repair_attempted
    final_s6_cards = [
        _compact_s6_authored_card_event(item)
        for item in accumulated.get("concept_directions", [])
        if isinstance(item, Mapping) and str(item.get("name", "")).strip()
    ]
    runtime_budget = (
        accumulated.get("winning_swarm", {}).get("budget", {})
        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
        else {}
    )
    runtime_budget = runtime_budget if isinstance(runtime_budget, Mapping) else {}
    emit_swarm_event(
        "winning_s6_release_gate_evaluated",
        passed=s6_release_state["passed"],
        failed=s6_release_state["failed"],
        limited=s6_release_state["limited"],
        issues=s6_release_state["issues"][:16],
        warnings=s6_release_state["warnings"][:16],
        authored_cards=final_s6_cards,
        card_count=len(final_s6_cards),
        maximum_concurrency=runtime_budget.get("maximum_concurrency"),
        maximum_observed_concurrency=runtime_budget.get(
            "maximum_observed_concurrency"
        ),
    )
    if s6_low_repair_error:
        accumulated["s6_low_repair_error"] = s6_low_repair_error
    if swarm_enabled or dynamic_swarm_enabled:
        latest_core_runs: dict[int, dict[str, Any]] = {}
        for row in runs:
            try:
                step = int(row.get("step", 0))
            except (TypeError, ValueError):
                continue
            if step in active_steps:
                latest_core_runs[step] = dict(row)
        completed_core_steps = sorted(
            step
            for step, row in latest_core_runs.items()
            if row.get("status") in {"completed", "reused_from_prior_analysis"}
        )
        limited_core_steps = sorted(
            step for step in active_steps if step not in completed_core_steps
        )
        core_gate_passed = (
            set(active_steps) <= set(completed_core_steps)
            and not accumulated.get("middle_loop_limited")
            and not final_s6_issues
        )
        finalized_core_schedule = {
            **core_swarm_schedule,
            "completed_steps": [f"S{step}" for step in completed_core_steps],
            "limited_steps": [f"S{step}" for step in limited_core_steps],
            "latest_runs": [
                {
                    "step": f"S{step}",
                    "agent_id": str(row.get("agent_id", "")),
                    "execution_mode": str(row.get("execution_mode", "")),
                    "middle_cycle": int(row.get("middle_cycle", 1) or 1),
                    "status": str(row.get("status", "")),
                    "confidence": row.get("confidence"),
                }
                for step, row in sorted(latest_core_runs.items())
            ],
            "quality_gate_passed": core_gate_passed,
            "status": "completed" if core_gate_passed else "limited",
        }
        swarm_summary = (
            dict(accumulated.get("winning_swarm", {}))
            if isinstance(accumulated.get("winning_swarm", {}), Mapping)
            else {}
        )
        swarm_summary.setdefault("policy", dict(swarm_controller.policy))
        swarm_summary.setdefault("task_graph", [to_plain(item) for item in swarm_tasks])
        swarm_summary.setdefault("finalists", [])
        swarm_summary["core_schedule"] = finalized_core_schedule
        swarm_summary["specialist_execution_batches"] = [
            {
                "wave": wave,
                "batch": batch,
                "task_ids": [
                    str(row.get("agent_id", ""))
                    for row in runs
                    if row.get("execution_mode") == "dynamic"
                    and int(row.get("wave", 0) or 0) == wave
                    and int(row.get("batch", 0) or 0) == batch
                ],
            }
            for wave, batch in sorted(
                {
                    (
                        int(row.get("wave", 0) or 0),
                        int(row.get("batch", 0) or 0),
                    )
                    for row in runs
                    if row.get("execution_mode") == "dynamic"
                    and int(row.get("wave", 0) or 0) > 0
                    and int(row.get("batch", 0) or 0) > 0
                }
            )
        ]
        active_set = set(active_steps)
        finalist_count = len(swarm_summary.get("finalists", []))
        dynamic_portfolio_ready = bool(
            swarm_summary.get("final_equipment_portfolio", [])
        )
        raw_portfolio_gate = swarm_summary.get("portfolio_quality_gate", {})
        raw_portfolio_gate = (
            raw_portfolio_gate if isinstance(raw_portfolio_gate, Mapping) else {}
        )
        diversity_only_warning = bool(
            not bool(raw_portfolio_gate.get("direct_equipment_diversity_passed", True))
            and bool(raw_portfolio_gate.get("direct_combat_main_body_passed"))
            and bool(
                raw_portfolio_gate.get(
                    "s6_handoff_gate_passed",
                    raw_portfolio_gate.get("capability_portrait_gate_passed"),
                )
            )
            and bool(raw_portfolio_gate.get("equipment_diversity_passed"))
            and not raw_portfolio_gate.get("hard_blockers")
        )
        if diversity_only_warning:
            # Older checkpoints may have serialized ``passed=false``
            # solely because the preferred family count was missed.  On
            # resume, normalize that legacy value so the UI and Reporter
            # observe the same non-blocking release decision.
            raw_portfolio_gate = {
                **dict(raw_portfolio_gate),
                "passed": True,
                "direct_equipment_diversity_limited": True,
            }
            swarm_summary["portfolio_quality_gate"] = raw_portfolio_gate
        portfolio_quality_gate_passed = (
            bool(raw_portfolio_gate.get("passed")) or diversity_only_warning
            if str(swarm_controller.policy.get("policy_id"))
            == "winning_swarm_dynamic_v2"
            else bool(raw_portfolio_gate.get("passed", finalist_count > 0))
        )
        final_merge = {
            "strategy": "candidate_ledger_plus_isolated_core_commits",
            "candidate_ledger_ready": finalist_count > 0,
            "finalist_count": finalist_count,
            "s4_mapping_ready": (
                4 not in active_set
                or bool(accumulated.get("capability_mapping"))
                or dynamic_portfolio_ready
            ),
            "s5_gap_review_ready": (
                5 not in active_set
                or bool(accumulated.get("gap_assessment"))
                or dynamic_portfolio_ready
            ),
            "s6_portfolio_ready": (
                6 not in active_set
                or bool(accumulated.get("concept_directions"))
                or dynamic_portfolio_ready
            ),
            "core_quality_gate_passed": core_gate_passed,
            "portfolio_quality_gate_passed": portfolio_quality_gate_passed,
        }
        final_merge["passed"] = bool(
            final_merge["candidate_ledger_ready"]
            and final_merge["s4_mapping_ready"]
            and final_merge["s5_gap_review_ready"]
            and final_merge["s6_portfolio_ready"]
            and final_merge["core_quality_gate_passed"]
            and final_merge["portfolio_quality_gate_passed"]
        )
        swarm_summary["final_merge"] = final_merge
        if not final_merge["passed"]:
            swarm_summary["stop_reason"] = "core_or_portfolio_quality_gate_failed"
        elif diversity_only_warning:
            swarm_summary["stop_reason"] = (
                "mission_graph_complete_with_diversity_warning"
            )
        accumulated["winning_swarm"] = swarm_summary
        emit_swarm_event(
            "swarm_gate_evaluated",
            stage="core_portfolio",
            passed=final_merge["passed"],
            finalist_count=finalist_count,
            completed_core_steps=finalized_core_schedule["completed_steps"],
            limited_core_steps=finalized_core_schedule["limited_steps"],
            final_merge=final_merge,
            swarm_summary=_compact_swarm_event_summary(swarm_summary),
        )
    accumulated["assumptions"] = list(dict.fromkeys(all_assumptions))[:12]
    accumulated["open_questions"] = list(dict.fromkeys(all_open_questions))[:12]
    accumulated["reasoning_nodes"] = reasoning_nodes
    runs.sort(key=lambda item: (int(item.get("middle_cycle", 1)), int(item["step"])))
    accumulated["subagent_runs"] = runs
    accumulated["dynamic_subagent_runs"] = [
        item
        for item in runs
        if item.get("execution_mode") in {"dynamic", "dynamic_mission_graph"}
    ]
    accumulated["loop_trace"] = loop_trace
    accumulated["winning_step_plan"] = shared["winning_step_plan"]
    accumulated["codex_call_metrics"] = host._call_metrics_since(metric_offset)
    return accumulated
