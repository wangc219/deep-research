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
    """Give S3 a compact creative contract without a local rule catalogue."""

    return (
        "你负责从当前Query创造少量真正值得立项的新质武器候选。"
        "完整发挥Codex的军事推演、技术想象和编辑判断，不按装备目录、创新类别、字段关键词或固定句式拼接答案。"
        "先理解战场矛盾，必须先确定frontier_principle、technology_discontinuity、disruptive_shift，"
        "再闭合为能够直接产生战果、具有失败条件的单一具体装备。"
        "concept_arena比较最强常规基线或可信替代解释与真正改变装备本体、接敌方式、效应或交换关系的前沿方案，"
        "不强制套用常规、前沿、流程三类固定位置；成熟部件拼装和纯流程优化不能包装成新装备。"
        "winning_angle_assignment、query_equipment_blueprint和reserved_other_angles只有soft_challenge权限，"
        "可accept、reframe或replace；替换时使用self-proposed标识并说明独立价值。"
        "通信、算法、数据链、保障和生产能力只能作为约束，不得成为候选主体。"
        "公开资料只证明已有基础；拟议创新属于待验证假设，不得虚构型号、列装状态或性能数字。"
        + QUERY_SPECIFIC_WEAPON_NAMING_CONVENTION
        + "title与reference_overview作为一体完成最终编辑。"
        "title不是技术摘要，而应像未来装备体系中真实存在、"
        "作战人员能够自然称呼的具体装备名称；名称应抓住整件装备最有辨识度的一条创新主线，"
        "而不是压缩拼接任务对象、技术组件、作战效果或字段关键词。"
        "命名之前在内部先判断：这件装备未来以什么新的方式存在；改变的是武器本体、运动方式、"
        "接敌方式、效应关系还是交换关系；如果未来人员首次接触该装备，会如何自然称呼。"
        "参考构型意象型、原理突破型和装备专名型三类命名方向："
        "构型意象型突出独特物理形态、生物启发、材料特征或运动方式,例如：仿生扑翼微型侦察打击弹、潮汐滑翔远程效应器;"
        "原理突破型突出改变装备存在方式的新原理或新效应机制,例如：超材料隐身巡弋器、相变热源诱导弹、等离子流控飞行器;"
        "装备专名型采用自然代号或意象名称结合具体装备身份。类似真实装备体系中的自然名称，由代号/意象+装备身份组成。"
        "例如：“玄鸟”远域感知打击器、“逐浪”跨介质无人作战艇、“苍穹织网”智能效应系统"
        "最终只输出最符合整件装备创新主线的一种创新新质名称。"
        "只输出schema规定的严格JSON，不输出推理过程。"
    )


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
        "你是S6单装备能力画像作者，在独立Codex CLI会话中只完成assigned_card这一张卡。"
        "名称、主装备身份、发射或释放域、目标与直接战果、能力分类、装备语义判断、指标画像、"
        "Query关联和组合成员关系均由S5冻结，必须逐项继承；不得改名、换装、重新分类、补造候选，"
        "不得推测或吸收其他组合卡的身份、流程或战果。"
        "你拥有本卡场景推演、技术论证、作战流程和文字编辑权。先整体理解Query与装备的制胜矛盾，"
        "再直接写成决策短卡，不复述研究过程、证据过程或上游字段。"
        "能力画像必须输出capability_portrait_modules的五栏，每栏约120至150个中文字作为软编辑目标；"
        "完整性优先，允许因装备机理自然略短或略长，不逐栏计数，不因篇幅偏差失败、重试或截断。"
        "overview只讲传统能力为何失效、本装备改变的核心关系和直接战果。"
        "technology_implementation深入说明可复用底座、决定性瓶颈、核心原理怎样落实到装备本体、"
        "必须打通的接口/能源/材料/控制/制造约束，以及样机、半实物或对抗试验和判退结果；"
        "不得用成熟度标签、热门技术或组件清单代替可实现性论证。"
        "operational_process只写决定成败的装备专属节点；每个节点自然交代行动主体、进入条件、关键动作、"
        "任务状态变化和转入下一节点的条件，重点展开授权或效应窗口、战果确认和再组织逻辑，"
        "禁止套用发现—决策—打击—评估等通用流程。"
        "capability_effects只写相对基线新增的能力、可验证战场结果以及由此开发的新任务或新场景。"
        "winning_logic说明敌方原有优势、传统方案为何不能维持、本装备改变的成本/时间/暴露/毁伤/"
        "攻防消耗等主要交换关系，以及迫使对手新增的防御或组织成本。"
        "创新必须落到真实军事需求和敌我关系，不能停留在智能化、无人化、网络化、隐身化等常识标签。"
        "能力分类必须显示在画像开头；已有分类逐项继承，仅在为空时按主要可验收战果自然形成，"
        "不得为覆盖毁伤、突防等示例凑类。"
        "成稿前在本次会话内静默编辑：删除跨栏重复、背景复述、字段拼接、生僻造词、无解释缩写、"
        "同义句和不改变军事判断的修饰语；使用一线设计人员能直接理解的通俗准确中文。"
        "检查主装备、流程主体、作用域、目标和直接战果始终一致，semantic_consistency_check.consistent"
        "必须为JSON布尔值true。最终只输出schema规定的严格JSON。"
    )


def _dynamic_role_contract_handoff(contract: Any, task: Any) -> dict[str, Any]:
    """Expose authority and handoff boundaries without replaying rule lists."""

    node = str(contract.mission_node)
    authority = {
        "S1": "自主重构对手成功逻辑、体系依赖、反适应与失效窗口；不预定装备答案。",
        "S2": "自主比较任务组织、力量运用和非装备对照；不预定装备答案。",
        "S3": "自主定义问题并创造具体武器候选，可接受、重构或替换多样性建议。",
        "S4": "与S3同权创造具体武器候选，不承担后置物化或机械补全。",
        "S5": "拥有组合语义准入、合并、判退、证据边界和工程可行性审查权。",
        "S6": "只对S5冻结装备撰写画像，不改变身份、分类、指标或Query关联。",
    }.get(node, "在声明节点内自主完成军事判断。")
    handoff = {
        "S1": "只交接制胜问题、竞争解释、反适应和失败边界。",
        "S2": "只交接任务关系、非装备对照、制胜问题和失败边界。",
        "S3": "交接装备身份、制胜机理、直接战果、证据边界和可证伪条件。",
        "S4": "交接装备身份、制胜机理、直接战果、证据边界和可证伪条件。",
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
        optimized_v2
        and host.provider_kind == "codex_cli"
        and getattr(host.provider, "provider_type", "") == "codex_cli"
    )

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
        ]
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
        repair_reserve = int(
            swarm_controller.policy.get("expert_repair_reserved_instances", 0)
        )
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
        recruited_pairs: set[tuple[str, str]] = set()
        instance_hypothesis_ids: dict[str, set[str]] = {}
        reasoning_seeds_by_instance: dict[str, list[dict[str, Any]]] = {}
        winning_angle_assignments: dict[str, dict[str, Any]] = {}
        query_equipment_blueprint: dict[str, Any] = {}
        winning_angle_refresh_task: asyncio.Task[None] | None = None
        candidate_id_aliases: dict[str, str] = {}
        semantic_clustered_ledger_version = -1
        candidate_competition_converged = False
        s3_active_instances_materialized = False
        s4_candidate_fanout_materialized = False
        initial_expert_review_scope: set[str] | None = None
        dynamic_instance_retry_counts: dict[str, int] = {}
        portfolio_innovation_audits_by_instance: dict[str, dict[str, Any]] = {}
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
            """Build non-authoritative diversity challenges for S3/S4 creators.

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
                        "升级边界和反模板边界，并列出若干尚待S3/S4独立验证的开放断点；不要指定唯一物理创新、"
                        "唯一战场存在方式或唯一制胜逻辑。"
                        "combat_dimensions只是可选作战效应视角，不是固定分类、十二条生产线、数量配额或质量门。"
                        "根据Query只激活真正相关且能导向不同装备思考空间的维度；可以不使用多数维度，也可提出"
                        "Query特有的OTHER维度。每个激活维度写入replacement_angles，只能形成soft_challenge："
                        "后续Agent可以accept、reframe或replace。不得预先给出装备名称、装备家族、技术套餐、"
                        "成品构型或必须继承的答案。"
                        "S3和S4职责相同，都是创新装备生成者。把激活维度自然分配给可用容量即可，不区分首轮、"
                        "二轮、主线或补救线。maximum_active只是并发容量上限，不要求填满；同一维度只有在Query"
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
                    "authority": "soft_challenge",
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
                        "这是可挑战的观察视角，不限定技术、构型、装备家族或名称。Agent必须先独立理解"
                        "完整Query，然后可接受、重构或替换本提示；替换时可使用OTHER:<自然标签>并以"
                        "self-proposed:<id>标识，只需说明相对其他软挑战的新任务链断点或制胜关系。"
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
                display_name = f"{dimension or '开放'}维度创新装备 Agent {label}"
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
                        f"独立分析完整Query及{target or '关键作战阶段'}，自主发散创新武器装备。"
                        f"多样性侦察员建议从{dimension or '开放创新'}视角挑战"
                        f"{mechanism or changed_variable or '新的制胜关系'}并观察{result or '直接军事效果'}；"
                        "这只是soft_challenge，不是预定答案。可接受、重构或用Query驱动的OTHER方向替换。"
                        "比较不同物理创新、战场存在方式和装备身份，独立完成自然名称与一句制胜说明。"
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
            if (
                candidate_scope
                and instance.archetype != "independent_portfolio_reviewer"
            ):
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
            prioritized_evidence = _prioritize_winning_evidence_index(
                shared.get("evidence_index", []),
                archetype=instance.archetype,
            )
            if (
                instance.mission_node in {"S3", "S4"}
                and not instance.hypothesis_id
                and not dynamic_instance_retry_counts.get(instance.instance_id, 0)
            ):
                # Public equipment catalogues define the later comparison
                # boundary; they must not anchor the first innovation turn to
                # familiar model families.
                prioritized_evidence = [
                    item
                    for item in prioritized_evidence
                    if str(item.get("created_by", "")) != "weapon_equipment"
                    and not str(item.get("evidence_id", "")).startswith(
                        "ev-weapon_equipment-"
                    )
                ]
            candidate_evidence_ids = {
                evidence_id
                for candidate in candidate_snapshot
                for evidence_id in candidate.get("evidence_ids", [])
                if str(evidence_id).strip()
            }
            if candidate_evidence_ids:
                prioritized_evidence = _quality_judge_scoped_evidence_index(
                    prioritized_evidence,
                    candidate_evidence_ids,
                )
            compact_evidence_index = _compact_prompt_value(
                prioritized_evidence,
                max_string_chars=(
                    140
                    if instance.archetype == "independent_portfolio_reviewer"
                    else 260
                ),
                max_list_items=(
                    6
                    if instance.archetype == "independent_portfolio_reviewer"
                    else 18
                    if instance.mission_node == "S6"
                    else 14
                ),
            )
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
            if instance.mission_node in {"S5", "S6"}:
                common_input["s6_release_preflight"] = {
                    "identity_and_scene": (
                        "保持主装备、目标、作用域、直接战果和装备专属流程一致"
                    ),
                    "evidence_boundary": (
                        "已知基线与拟议增量分开；缺少同名公开型号不机械淘汰，也不得虚构成熟度"
                    ),
                    "quality_basis": "军事因果、技术可实现性、证据边界和可证伪性",
                }
            if instance.mission_node in {"S5", "S6"} and baseline_boundaries:
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
                common_input["query_equipment_blueprint"] = dict(
                    query_equipment_blueprint
                )
                common_input["combat_dimension_assignment"] = {
                    key: dimension_assignment.get(key, "")
                    for key in (
                        "assignment_id",
                        "active",
                        "source",
                        "authority",
                        "allowed_response_modes",
                        "self_proposed_id_pattern",
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
                        "reserved_other_angles",
                        "rule",
                    )
                }
            if instance.archetype == "independent_portfolio_reviewer":
                common_input["disruptive_paradigm_seed_library_v2"] = (
                    disruptive_seed_context(
                        str(shared["topic"]),
                        branch=primary_branch,
                        agent_id=instance.archetype,
                    )
                )
            if instance.instance_id in portfolio_innovation_audits_by_instance:
                common_input["portfolio_innovation_audit"] = dict(
                    portfolio_innovation_audits_by_instance[instance.instance_id]
                )
            if instance.mission_node in {"S1", "S2"} and not instance.hypothesis_id:
                output_schema = {
                    "reasoning_seeds": [
                        {
                            "mechanism_thesis": "query-specific opponent or operational mechanism, not an equipment title",
                            "incumbent_success_logic": "why the current opponent or operational paradigm remains effective",
                            "lock_in_dependency": "the dependency, incentive or timing relationship that keeps the incumbent paradigm stable",
                            "paradigm_break_condition": "a concrete future condition under which that success logic stops holding",
                            "changed_confrontation_variable": "the relationship that could be changed",
                            "direct_military_result": "decisive battlefield result if the thesis holds",
                            "equipment_implications": [
                                "open-ended implications for S3; not preselected candidates"
                            ],
                            "competing_explanation": "a materially different explanation or route",
                            "non_equipment_control": "the strongest doctrine, process or ordinary upgrade explanation that must be ruled out before new equipment is justified",
                            "adversary_adaptation": "how the opponent could neutralize the thesis",
                            "failure_boundary": "falsifiable condition",
                            "evidence_ids": ["exact evidence_id or packet_id"],
                        }
                    ],
                    "quality_residuals": ["string"],
                    "stop_reason": "string",
                }
                instruction = (
                    "本节点只形成制胜机理问题与竞争解释，不直接批量命名装备候选，也不向候选账本写卡。"
                    "前置winning_problem_propositions只是Codex对Query形成的开放问题图，不是答案；"
                    "本会话可改写、合并或全部舍弃，不得继承其中的固定措辞形成装备名称或技术路线。"
                    "S1聚焦对手体系依赖、适应路径和可利用窗口；S2聚焦任务组织、决策权、力量运用和"
                    "效应递进关系。先写清现行范式的成功逻辑和锁定依赖，再提出使其失效的具体条件；"
                    "禁止把现役短板、一般性能不足或热门技术趋势直接改写成颠覆机会。每条reasoning_seed"
                    "必须由完整Query和证据产生，写清改变的对抗变量、"
                    "直接军事结果、竞争解释、对手反适应与失败边界。equipment_implications只是交给S3"
                    "继续发散的问题提示，禁止写成固定装备目录、最终名称或每类一项的配额。"
                    "在确有独立边际价值时优先保留2至4条彼此不同的reasoning_seed，差异必须落在"
                    "任务链断点、对抗变量、核心机理或直接战果，而不是换平台、换弹型或换措辞；"
                    "不足两条时如实少产出，不为数量拼凑。未进入首轮S3分配的高价值seed将作为"
                    "空分支的预计算备用命题，因而也必须具备完整的反适应和失败边界。"
                    "每条还要给出non_equipment_control：若调整条令、流程、编组或对现役装备普通升级即可"
                    "取得同一直接战果，就把它保留为对照解释，不得冒充新质装备牵引。"
                    "被关键词激活的证据通道和种子卡必须经过本Codex会话消化，可全部舍弃。"
                    + _open_s3_theme_instruction()
                )
                phase = "winning_swarm_dynamic_reasoning_seed"
            elif instance.mission_node in {"S3", "S4"} and not instance.hypothesis_id:
                output_schema: dict[str, Any] = {
                    "concept_arena": [
                        {
                            "concept_id": "short local id",
                            "comparison_position": "strongest_conventional|frontier_discontinuity|workflow_or_mature_assembly",
                            "technical_or_operational_leap": "the distinct non-incremental opportunity explored",
                            "weapon_architecture": "the concrete direct-combat weapon form implied by that opportunity",
                            "decisive_effect": "the direct battlefield result and changed exchange relationship",
                            "conventional_absorption_test": "why an ordinary upgrade can or cannot absorb it",
                            "frontier_credibility_test": "whether the enabling principle can plausibly alter the weapon body and what would falsify it",
                            "disposition": "selected|reserve|rejected",
                        }
                    ],
                    "hypotheses": [
                        {
                            "title": "string",
                            "winning_angle_id": "combat_dimension_assignment.assignment_id when accepted/reframed, or self-proposed:<short-id> when replaced",
                            "combat_dimension": "exact assigned combat dimension",
                            "dimension_winning_logic": "how the candidate wins from this dimension under the Query blueprint",
                            "original_paradigm": "the conventional relationship or assumption this candidate overturns",
                            "disruptive_shift": "the new winning relationship created by this weapon",
                            "independence_thesis": "why this is not a renamed variant of any reserved_other_angle",
                            "naming_rationale": "holistic editorial reason this is a natural, memorable name for the complete weapon; do not decompose or justify every word",
                            "decisive_advantage_thesis": "why this specific weapon can change the outcome in the query's engagement window rather than merely improve a generic metric",
                            "cross_query_distinction": "which configuration, mechanism and naming elements must change under another target, phase or threat",
                            "nearest_public_baseline": "string",
                            "changed_confrontation_variable": "string",
                            "mechanism_chain": ["string"],
                            "direct_military_effects": ["string"],
                            "equipment_forms": ["specific equipment form"],
                            "project_function": "who uses this equipment, under what conditions, to perform what action and produce what mission result",
                            "reference_overview": "one compact winning sentence displayed directly below the weapon name, usually 35-80 Chinese characters as an editorial target rather than a gate; state the distinctive battlefield condition, disruptive relationship and direct combat result without repeating the title or using a fixed template",
                            "system_interfaces": [
                                "concrete platform, payload, C2, fire-control or support interface"
                            ],
                            "novelty_delta": "string",
                            "frontier_principle": "required concrete enabling principle, architecture or effect actually embodied by this weapon",
                            "technology_discontinuity": "required reason the strongest conventional upgrade or process change cannot absorb the winning increment",
                            "technology_horizon": "required bounded horizon such as 3-5 years|5-10 years|longer exploration, without asserting unsupported readiness",
                            "engineering_bottleneck": "required primary physics, integration, cost, safety or test question that could falsify this concept; semantic content, not a local string gate",
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
                            "implementation_path": "new|upgrade|system_link|non_materiel",
                        }
                    ],
                    "quality_residuals": ["string"],
                    "stop_reason": "string",
                }
                # The schema and governed inputs retain all audit constraints.
                # Use a compact creative brief for the actual Codex call so the
                # model reasons about the weapon instead of imitating a rule list.
                instruction = _creative_s3_candidate_instruction()
                dimension_assignment = common_input.get(
                    "combat_dimension_assignment", {}
                )
                instruction += (
                    "先依据完整Query和upstream_reasoning_seeds自主定义问题并形成候选空间，再把"
                    "query_equipment_blueprint与combat_dimension_assignment仅作为soft_challenge。"
                    "可accept、reframe或replace；替换时用self-proposed:<简短id>，并说明相对其他方向"
                    "独立的任务断点、核心机理或直接战果。S3与S4同为一次性创新装备创作会话，"
                    "不存在首轮、物化或补救分工；维度字段用于交接，不得反向拼成title。"
                )
                if isinstance(dimension_assignment, Mapping):
                    instruction += (
                        "在内部比较不同物理创新与战场存在方式，只输出自然成立的候选；数量不是门槛。"
                    )
                if instance.archetype in {
                    "direct_combat_equipment_generator",
                    "remote_precision_munition_generator",
                    "mass_scalable_combat_family_generator",
                }:
                    instruction += (
                        "公开资料只界定已有基线；具名现役属性须有对象证据，未来增量可用相邻技术或"
                        "效应机理支撑并明确为待验证假设。缺少同名型号或引用不导致机械失败。"
                        "每条保持一个主装备，装备构型、制胜机理、作战运用、接口、失败边界和可证伪试验"
                        "必须闭合；evidence_boundary只写事实支持范围，不得混入内部流程。"
                    )
                if "portfolio_direction_shortfall" in instance.trigger_residuals:
                    instruction += _portfolio_gap_completion_instruction(
                        str(shared.get("topic", ""))
                    )
                if "frontier_innovation_shortfall" in instance.trigger_residuals:
                    instruction += _portfolio_frontier_completion_instruction()
                if instance.archetype == "direct_combat_equipment_generator":
                    instruction += _direct_combat_generator_diversity_instruction()
                    instruction += (
                        "先服从query_combat_equipment_divergence_brief选择目标和武器构型。"
                        "公开型号只在Codex推演出的候选与其任务对象、平台和机理直接匹配时核对；"
                        "不得默认生成任何共享示例装备。"
                    )
                elif instance.archetype == "remote_precision_munition_generator":
                    instruction += (
                        "若形成多个候选，必须依据query_combat_equipment_divergence_brief分属不同发射域、"
                        "目标包线或飞行/毁伤逻辑；候选是否成立由独立机理和对象证据决定，并优先使用与query目标直接匹配的公开装备基线。"
                        "任何公开型号都不能成为默认配对。每条只选择一个有接口锚点的主增量，其余写成边界或验证"
                        "条件；禁止把多个热门能力堆叠成复合创新。"
                    )
                elif instance.archetype == "mass_scalable_combat_family_generator":
                    instruction += (
                        "仅在query确有饱和消耗、成本交换、产能或快速补充压力时形成规模化装备族；"
                        "装备主体和毁伤对象仍必须由query决定，任何低成本巡航效应器或低空无人平台"
                        "都不得固定占用候选。柔性重组只能写成固定构型之间的"
                        "工厂换产、多源替代和批次鉴定，不得声称战场现场换装即可形成新型号。"
                    )
                phase = "winning_swarm_dynamic_seed"
            else:
                output_schema = {
                    "contributions": [
                        {
                            "hypothesis_id": "exact ledger hypothesis_id",
                            "merge_target": f"{instance.merge_target}",
                            "title": "complete replacement title for bounded expert repair only",
                            "replacement_title": "S4/S5 only: concise semantic rename when the current title fails the shared naming contract; otherwise empty",
                            "nearest_public_baseline": "complete replacement baseline for bounded expert repair only",
                            "changed_confrontation_variable": "complete replacement confrontation variable for bounded expert repair only",
                            "findings": ["incremental finding"],
                            "mechanism_chain": [
                                "complete replacement mechanism chain for bounded expert repair only"
                            ],
                            "mechanism_chain_updates": ["string"],
                            "direct_military_effects": ["string"],
                            "equipment_forms": ["specific equipment form"],
                            "project_function": "complete project function; required for equipment candidates",
                            "system_interfaces": [
                                "concrete platform, payload, C2, fire-control or support interface"
                            ],
                            "novelty_delta": "string",
                            "frontier_principle": "preserve S3 frontier principle; only narrow unsupported scope without replacing the innovation thesis",
                            "technology_discontinuity": "preserve the S3 discontinuity; only clarify why conventional absorption fails",
                            "technology_horizon": "preserve or evidence-bound the S3 horizon",
                            "engineering_bottleneck": "preserve or sharpen the falsifiable S3 engineering bottleneck",
                            "original_paradigm": "preserve the incumbent winning relationship; fill only if missing unless governed expert repair replaces the identity bundle",
                            "disruptive_shift": "preserve the S3 relationship inversion; do not substitute a generic novelty claim",
                            "independence_thesis": "preserve why this candidate is not an incremental or renamed sibling",
                            "naming_rationale": "holistic editorial reason for preserving or naturally renaming the complete weapon; never a word-by-word field mapping",
                            "decisive_advantage_thesis": "repair the query-specific battle-winning advantage before S6",
                            "cross_query_distinction": "repair what configuration, mechanism and naming must change under another query",
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
                            "implementation_path": "new|upgrade|system_link|non_materiel",
                            "patch_mode": "append|replace_bounded_claims",
                            "replace_fields": [
                                "field name replaced only during expert repair"
                            ],
                            "residuals_resolved": ["string"],
                            "incremental_quality": "0..1",
                            "recommendation": "retain|revise|reject",
                        }
                    ],
                    "portfolio_review": ["string"],
                    "stop_reason": "string",
                }
                instruction = (
                    "只向当前不可变账本中的候选提交结构化增量。每项贡献必须使用精确"
                    "hypothesis_id和声明的merge_target。S3/S4已经独立生成创新装备；S5是候选"
                    "语义准入、同义合并、证据与可行性判断的唯一责任节点，S6只撰写已入选装备画像。"
                    "hypothesis_id只能从candidate_ledger.allowed_hypothesis_ids逐字复制，禁止"
                    "自行创造新ID或在contributions中新增候选。若研究中发现账本外的新装备，"
                    "只能写入portfolio_review并明确标注portfolio_direction_shortfall，交由受治理的"
                    "S5贡献应核对敌方目标/威胁及反制、"
                    "我方主装备与时敏交战流程、直接战果，并逐装备核对证据层级；现役升级严审对象"
                    "证据，前瞻新研允许相邻项目/组成技术/机理证据与较低置信度，不得把这些问题留到"
                    "最终质量门事后发现。字数不是硬门。"
                    "跨Agent交接只允许传递装备身份、场景、机理、直接战果、证据事实、不确定性和"
                    "可证伪边界；S1—S6、Agent、评审意见、补写要求、交接状态和执行过程只能进入"
                    "审计事件，不得写入findings、evidence_boundary、failure_boundaries或其他候选字段。"
                    "evidence_boundary必须是面向报告读者的证据认识边界，只写公开材料支持什么、"
                    "不支持什么以及哪些属于待验证假设；发现污染时必须在S5合并前舍弃或自然重写，"
                    "不得冻结后交给S6。"
                    "S5必须继续用query_combat_equipment_divergence_brief审查装备构型与主题因果关系；"
                    "若候选只是共享示例换名或与Query目标、阶段、毁伤效果脱节，应在当前前置节点修正或淘汰。"
                    "S5必须消费并比较S3/S4生成的frontier_principle、technology_discontinuity、"
                    "technology_horizon和engineering_bottleneck；只能依据证据边界收窄夸大表述、补清接口"
                    "和可证伪条件，不得把技术构型型名称重新压缩成抽象动作词，也不得在此阶段才补造前沿原理、"
                    "颠覆机理或新装备身份。若S3语义本身不成立，应判退或返回组合缺口，不进行事后创新包装。"
                    "S5还必须逐项复核original_paradigm、disruptive_shift和independence_thesis，并用"
                    "最强常规升级和非装备对照做吸收测试。"
                    "若删去前沿构型后，常规方案仍能原样完成同一接敌链、授权时机、效应触发、直接战果和"
                    "判退试验，则必须revise或reject，不能靠novelty_delta和新名称包装过关。"
                    "装备名称已经由其S3/S4生成Codex按完整装备语义完成。S5不得本地拼名或事后美化；"
                    "名称与装备机理不一致时只能recommendation=revise或reject，并明确语义原因。"
                    + _query_led_combat_equipment_theme_instruction()
                    + "若输入含disruptive_paradigm_seed_library_v2，审查候选是否真正改变所选种子卡"
                    "对应的成本、平台、时间、效应、体系或博弈关系；未形成query因果映射时舍弃，"
                    "不得为覆盖种子而增项。"
                )
                if instance.archetype == "equipment_capability_image_repairer":
                    instruction += (
                        "若原候选的装备形态、机理、成本或产能主张超出公开证据，必须设置"
                        "patch_mode=replace_bounded_claims，并在replace_fields中列出需要整体"
                        "替换的字段；允许成套替换title、nearest_public_baseline、"
                        "changed_confrontation_variable、mechanism_chain、direct_military_effects、"
                        "equipment_forms、project_function、evidence_ids、novelty_delta、naming_rationale、"
                        "original_paradigm、disruptive_shift、independence_thesis、decisive_advantage_thesis、"
                        "cross_query_distinction与implementation_path。标题、对抗变量、"
                        "机理链、军事效果和装备形态必须描述同一个证据边界内的固定原型；若删除"
                        "途中更新、末段确认、动态改瞄、弹间协同或现场换装等能力，必须同步从"
                        "标题和机理链中删除，不能仅追加验证要求或保留已被专家否定的概念。"
                        "公开证据必须证明具体装备基线，拟议增量则按工程假设身份修复：不能虚构其"
                        "已经存在，但也不能因为尚未公开列装就删除；应收缩到一个有物理/接口锚点、"
                        "有反证和可证伪试验的增量。成熟基线属性重包装仍必须删除。"
                    )
                if instance.archetype == "evidence_verifier":
                    instruction += (
                        "本节点是整合式S5审计，必须覆盖candidate_ledger中的全部候选，不按装备家族"
                        "抽样。对每项候选同时完成四类检查：一是公开基线、证据引用、反证和不确定性；"
                        "二是TRL、成本、产能、工业依赖与规模化补充边界；三是可证伪指标、最近对照"
                        "方案、试验条件和明确判退阈值；四是名称、主装备、改变变量、核心机理和直接"
                        "战果是否保持同一语义身份。可以合并证据边界、trl_constraints、cost_constraints、"
                        "industrial_constraints、validation_plan和failure_boundaries，但不得因候选同族、"
                        "证据数量少或缺少同名公开型号而机械删除前瞻新研方向。"
                    )
                if instance.archetype == "independent_portfolio_reviewer":
                    output_schema = {
                        "contributions": [],
                        "portfolio_review": [
                            "candidate id + retain|merge|reject + one-sentence five-axis reason"
                        ],
                        "stop_reason": "string",
                    }
                    instruction = (
                        "执行快速独立组合评审，不生成、改写或补强候选。只比较目标对象、任务链断点、"
                        "改变的对抗变量、核心制胜机理和直接军事战果；同族装备只要制胜关系可独立验收"
                        "即可并存，换名、换发射域或接口扩写不得单独占位。逐候选给出retain、merge或"
                        "reject及一句高信息密度理由；同时确认整合式证据审计已覆盖TRL、成本、产能、"
                        "工业边界、可证伪试验和判退条件。证据仅用于确认边界，不重做取证，不输出长篇论证。"
                    )
                    phase = "winning_swarm_dynamic_portfolio_review_fast"
                else:
                    phase = "winning_swarm_dynamic_merge"
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
            candidates_by_id = {item.hypothesis_id: item for item in hypotheses}
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
            """Plan a bounded blind-review scope without deleting candidates.

            The complete governed ledger remains visible to the candidate
            board and downstream semantic clustering.  Review capacity limits
            one Codex call, not the existence of an independently generated
            weapon direction.
            """

            nonlocal initial_expert_review_scope
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

        async def semantic_cluster_candidate_ledger(*, scope_id: str) -> dict[str, str]:
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

        def materialize_s4_candidate_fanout() -> None:
            """Bind one isolated S4 realization session to every retained candidate."""

            nonlocal graph, s4_candidate_fanout_materialized
            if s4_candidate_fanout_materialized or ledger is None:
                return
            retained_ids = [item.hypothesis_id for item in ledger.hypotheses]
            s4_rows = [
                item for item in graph.agent_instances if item.mission_node == "S4"
            ]
            templates = [item for item in s4_rows if not item.hypothesis_id]
            bound_by_candidate = {
                canonical_candidate_id(item.hypothesis_id): item
                for item in s4_rows
                if item.hypothesis_id
            }
            if not templates and not bound_by_candidate:
                return
            template = templates[0] if templates else s4_rows[0]
            s3_dependencies = [
                item.instance_id
                for item in graph.agent_instances
                if item.mission_node == "S3" and not item.hypothesis_id
            ]
            s3_wave = max(
                (
                    item.wave
                    for item in graph.agent_instances
                    if item.instance_id in s3_dependencies
                ),
                default=template.wave - 1,
            )
            realized: list[WinningAgentInstance] = []
            for ordinal, hypothesis_id in enumerate(retained_ids, start=1):
                existing = bound_by_candidate.get(hypothesis_id)
                instance_id = (
                    existing.instance_id
                    if existing is not None
                    else template.instance_id
                    if ordinal == 1
                    else "winning-s4-realization-"
                    + sha256(f"{graph.graph_id}:{hypothesis_id}".encode()).hexdigest()[
                        :16
                    ]
                )
                realized.append(
                    replace(
                        existing or template,
                        instance_id=instance_id,
                        display_name=f"装备实现 Agent {ordinal}",
                        hypothesis_id=hypothesis_id,
                        depends_on=list(s3_dependencies),
                        wave=s3_wave + 1,
                        trigger_residuals=list(
                            dict.fromkeys(
                                [
                                    *(existing or template).trigger_residuals,
                                    "candidate_realization_required",
                                ]
                            )
                        ),
                    )
                )

            old_s4_ids = {item.instance_id for item in s4_rows}
            for instance_id in old_s4_ids:
                pending.pop(instance_id, None)
            for item in realized:
                pending[item.instance_id] = item

            other_instances = [
                item for item in graph.agent_instances if item.mission_node != "S4"
            ]
            s4_ids = [item.instance_id for item in realized]
            evidence_ids = [
                item.instance_id
                for item in other_instances
                if item.mission_node == "S5" and item.archetype == "evidence_verifier"
            ]
            rebound_others: list[WinningAgentInstance] = []
            for item in other_instances:
                if item.mission_node != "S5":
                    rebound_others.append(item)
                    continue
                if item.archetype == "evidence_verifier":
                    depends_on = [*s3_dependencies, *s4_ids]
                elif item.archetype == "independent_portfolio_reviewer":
                    depends_on = [*s4_ids, *evidence_ids]
                else:
                    depends_on = list(s4_ids)
                rebound = replace(
                    item,
                    depends_on=list(dict.fromkeys(depends_on)),
                    wave=(s3_wave + 2),
                )
                rebound_others.append(rebound)
                if item.instance_id in pending:
                    pending[item.instance_id] = rebound

            all_instances = [*rebound_others, *realized]
            dependencies = {
                item.instance_id: list(item.depends_on) for item in all_instances
            }
            maximum_wave = max((item.wave for item in all_instances), default=0)
            waves = [
                [item.instance_id for item in all_instances if item.wave == wave]
                for wave in range(1, maximum_wave + 1)
            ]
            seeds = {key: list(value) for key, value in graph.s_node_seeds.items()}
            seeds["S4"] = s4_ids
            graph = replace(
                graph,
                agent_instances=all_instances,
                dependencies=dependencies,
                waves=waves,
                s_node_seeds=seeds,
                maximum_instances=max(graph.maximum_instances, len(all_instances)),
            )
            s4_candidate_fanout_materialized = True
            emit_swarm_event(
                "winning_s4_candidate_fanout_materialized",
                actor="winning_swarm_controller",
                graph_id=graph.graph_id,
                retained_candidate_count=len(retained_ids),
                s4_instance_count=len(realized),
                s4_instance_ids=s4_ids,
                hypothesis_ids=retained_ids,
                rule="one_retained_candidate_one_isolated_s4_instance",
            )

        def scope_for_instance(
            item: WinningAgentInstance,
            ledger_snapshot: HypothesisLedgerVersion | None,
        ) -> set[str]:
            if item.hypothesis_id:
                return {canonical_candidate_id(item.hypothesis_id)}
            if (
                item.archetype
                in {"evidence_verifier", "independent_portfolio_reviewer"}
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

        async def execute_quality_expert_judge(
            ledger_snapshot: HypothesisLedgerVersion,
            *,
            hypothesis_ids: set[str] | None = None,
        ) -> tuple[dict[str, WinningExpertAssessment], dict[str, Any]]:
            """Run S5's isolated, read-only Codex CLI semantic admission.

            The judge cannot contribute to or rewrite a hypothesis.  It
            receives no producer identity, prior score or selection status;
            its normalized dimensions become the portfolio objectives.
            """

            if not swarm_controller.policy.get("expert_judge_enabled"):
                return {}, {"status": "disabled", "assessments": []}
            spec = SWARM_SPECIALIST_ARCHETYPES["quality_expert_judge"]
            contract = swarm_controller.govern_role_contract(
                {"archetype": "quality_expert_judge", **spec},
                mission_node="S5",
            )
            instance_id = (
                "winning-quality-judge-"
                + sha256(
                    f"{graph.graph_id}:{ledger_snapshot.version}".encode()
                ).hexdigest()[:16]
            )
            candidate_count = sum(
                hypothesis_ids is None or item.hypothesis_id in hypothesis_ids
                for item in ledger_snapshot.hypotheses
            )
            task = SpecialistTask(
                task_id=instance_id,
                agent_instance_id=instance_id,
                archetype="quality_expert_judge",
                display_name=contract.display_name,
                wave=max((item.wave for item in graph.agent_instances), default=0) + 1,
                purpose=contract.purpose,
                merge_target="S5",
                expected_quality_gain=0.0,
                max_output_tokens=_quality_judge_output_token_budget(candidate_count),
                allow_child_spawn=False,
            )
            runtime_agent_id = "winning_s5_semantic_admission"
            scoped_provider = host._provider_for(
                runtime_agent_id, isolation_id=instance_id
            )
            runtime_contract = _swarm_runtime_audit_contract(
                task,
                getattr(scoped_provider, "snapshot", lambda: {})(),
                runtime_agent_id=runtime_agent_id,
                session_ref=_swarm_session_ref(task),
            )
            ordered = sorted(
                (
                    item
                    for item in ledger_snapshot.hypotheses
                    if hypothesis_ids is None or item.hypothesis_id in hypothesis_ids
                ),
                key=lambda item: sha256(
                    f"{graph.graph_id}:{item.hypothesis_id}".encode()
                ).hexdigest(),
            )
            label_map = {
                f"候选-{index:02d}": item for index, item in enumerate(ordered, start=1)
            }
            blind_candidates = []
            for blind_label, item in label_map.items():
                blind_candidates.append(
                    _quality_judge_candidate_payload(
                        item,
                        blind_label=blind_label,
                    )
                )
            candidate_evidence_ids = {
                evidence_id for item in ordered for evidence_id in item.evidence_ids
            }
            output_schema = {
                "assessments": [
                    {
                        "blind_label": "exact candidate blind_label",
                        "verdict": "pass|revise|reject",
                        "dimension_scores": {
                            "domain_relevance": "0..1",
                            "equipment_capability_fit": "0..1",
                            "innovation": "0..1",
                            "military_value": "0..1",
                            "decisive_advantage": "0..1",
                            "query_specificity": "0..1",
                            "causal_coherence": "0..1",
                            "credibility": "0..1",
                            "engineering_feasibility": "0..1",
                            "robustness": "0..1",
                        },
                        "strengths": ["specific strength"],
                        "weaknesses": ["specific weakness"],
                        "rejection_reasons": ["blocking reason"],
                        "residuals": ["quality residual"],
                        "equipment_classification": "direct_combat|unmanned_combat|upgrade|system_link|support_only|non_equipment",
                        "innovation_type": "mechanism|operational|equipment_architecture|integration|incremental|none",
                        "confidence": "0..1",
                        "evidence_ids": ["exact evidence_id used in judgement"],
                    }
                ],
                "portfolio_findings": ["cross-candidate finding"],
                "portfolio_innovation_audit": {
                    "frontier_breadth_sufficient": "boolean",
                    "portfolio_mode": "diverse|same_equipment_family|same_mechanism|process_only|uncertain",
                    "homogeneity_reason": "why the portfolio is or is not overly concentrated",
                    "completion_recommended": "boolean",
                    "missing_frontier_opportunity": {
                        "query_gap": "uncovered Query-specific task or confrontation gap",
                        "enabling_principle": "optional enabling principle, architecture, effect or operational concept; not a buzzword list",
                        "innovation_mode": "frontier|innovative|disruptive|new_quality|hybrid",
                        "equipment_implication": "specific direct-combat weapon concept or architecture implied by the opportunity",
                        "direct_military_effect": "direct battlefield result",
                        "disruptive_delta": "what traditional capability, gap, employment concept or implementation style is changed",
                        "conventional_absorption_limit": "optional reason ordinary improvement cannot fully absorb it",
                        "engineering_bottleneck": "optional later-stage engineering question; never a completion prerequisite",
                    },
                    "audit_reason": "bounded reason for or against one completion pass",
                },
                "stop_reason": "string",
            }
            emit_swarm_event(
                "winning_quality_judge_recruited",
                actor=instance_id,
                graph_id=graph.graph_id,
                role_contract=to_plain(contract),
                candidate_count=len(blind_candidates),
                **runtime_contract,
            )
            emit_swarm_event(
                "winning_quality_judge_started",
                actor=instance_id,
                graph_id=graph.graph_id,
                ledger_id=ledger_snapshot.ledger_id,
                ledger_version=ledger_snapshot.version,
                **runtime_contract,
            )
            started_at = monotonic()
            try:
                text = await host._run_core_json(
                    runtime_agent_id,
                    "你是制胜机理与军事装备论证的独立质量专家。你只评判、不生成候选、不修改账本。"
                    "必须逐项判断研究对象是否落在任务领域，是否形成具体装备能力而非算法/通信/保障空壳，"
                    "相对最近公开基线是否存在实质创新，军事价值是否由因果链直接导出，证据与工程判断是否可信。"
                    "decisive_advantage必须评判该装备是否能在Query指定交战窗口形成足以改变胜负的压倒、"
                    "拒止、突防、毁伤、拦截或持续火力优势；一般性性能改善不得高分。query_specificity必须"
                    "评判其构型、机理和名称是否由本Query独有目标、阶段和威胁共同决定；换题仍成立的模板候选"
                    "必须revise或reject。名称新颖不等于修辞新奇，必须能解释独有主装备、直接战果和制胜机理。"
                    "还要独立朗读候选名称：若名称像字段截词拼接、技术组件清单、流程标签、口号，或用华丽代号"
                    "遮蔽不清楚的主装备身份，即使naming_rationale非空也必须降低query_specificity并要求改名；"
                    "自然的描述名不因没有代号而降分，专名或代号也不因修辞醒目而加分。"
                    "证据职责必须分层：公开直接证据必须证明具体型号或装备族的最近基线、既有任务属性、"
                    "平台/弹体身份和可确认接口；对于明确标为拟议升级、新研构型或待验证假设的未来增量，"
                    "不得要求公开资料证明它已经列装或已经实现。此类增量应依据是否具有明确物理或接口锚点、"
                    "是否只改变一个可辨识的作战/装备关系、是否给出反证、失败边界和可证伪试验来评价。"
                    "这里的‘可确认接口’只约束候选声称已经存在于公开基线中的接口；对明确标注为新增、"
                    "待集成或待验证的接口，不要求公开资料证明现有产品已经具备，也不得仅因缺少型号级公开"
                    "接口图纸而降低credibility或驳回。应把质量、供电、热、电磁兼容、软件鉴定和试验归因"
                    "评价计入engineering_feasibility。若厂商或军方对象页能够证明装备身份与既有任务属性，"
                    "而未公开内部实现细节，应记录为不确定性或验证前置条件，而不是自动判为证据门失败。"
                    "若候选设置了基线表征门，并明确一旦现役基线已具备同类闭环就终止项目，则未知的内部"
                    "实现不得被臆测为既有能力并据此拒绝；只评价该重叠淘汰门是否真实可执行。"
                    "若候选把基线事实写成已实现增量，或把成熟产品已有属性重新命名为创新，仍须降分或驳回；"
                    "但不能仅以‘公开资料尚未证明未来增量已存在’作为拒绝理由。"
                    "不得因字段齐全而给满分；必须拉开候选差异。领域偏离、支撑能力冒充主装备、热门词堆叠、"
                    "因果断裂、无证据精确指标或无失败边界应降分或驳回。若候选以具体无人打击平台、"
                    "巡飞弹、远程精确制导弹药、压制/拦截效应器或直接毁伤载荷为主对象，应按"
                    "direct_combat或unmanned_combat评估；不能因其包含必要体系接口而自动归为system_link。"
                    "若主体仍是网络、算法、通信或保障，则必须归为system_link/support_only。"
                    "还必须做组合内语义去重：同一装备家族不自动构成重复；若接敌链、授权时机、效应触发、"
                    "对手被迫反应、直接战果或独立验收/判退命题至少一项发生足以改变立项决定的实质变化，"
                    "两个候选可以同时pass。若两个候选的主装备本体、最近公开基线、改变的对抗变量、"
                    "制胜关系、直接战果和验证命题实质相同，只是换了修饰词、代号、发射描述或流程措辞，只允许其中"
                    "较强者pass，其余必须标记semantic_duplicate并revise/reject。不能因为名称不同或字段齐全"
                    "就把同义变体视为多项新质装备，也不能仅因同族而合并具有不同可验收制胜逻辑的候选。"
                    "必须读取query_combat_equipment_divergence_brief中的任务对象、威胁形态、作战阶段、"
                    "地域约束、制胜矛盾和conditional_priority_observation_lenses。若候选落入无人、低空、"
                    "远程、精确打击、反辐射、诱饵、反无人或规模化等熟悉类别，但当前Query未触发相应镜头，"
                    "且候选不能用query_relevance证明该类别是由本题因果链独立推导出的，则判为"
                    "query_domain_leakage并要求revise；不得留到S6再修。反之，Query明确触发时不得因类别"
                    "常见而自动淘汰，应继续按对象证据、直接战果、新质增量和独立组合价值评审。"
                    "评判时还必须前置检查候选能否直接投影为S6装备画像：是否具备真实作战阶段、"
                    "敌方目标或威胁及反制、我方具体武器装备主体、时敏交战流程和直接战果，"
                    "以及证据层级是否与装备声明相匹配。现役升级或声称公开型号既有能力时，具名型号/"
                    "装备族有对象级证据应优先引用；没有时不得虚构既有属性，但不因缺证据直接淘汰。前瞻新研构型可采用相邻项目、组成技术、效应机理"
                    "或类比装备证据，不因缺少同名型号直接revise/reject；证据边界、反证、失效条件和"
                    "可证伪验证路径有则记录为优先补全项。没有公开引用时不得因此失败，但若把未来"
                    "指标写成既成事实，仍须拦截。"
                    "这些问题不得留到最终组合后才首次发现。字数只作为表达建议，不得据此降级或驳回。"
                    "完成逐项评判后还要执行组合创新审计，但该审计不修改任何候选：区分真正的前沿、"
                    "创新、颠覆、新质组合与同一装备族/同一机理的流程变体。不能因为候选分别讨论授权、"
                    "复核、战损评估和复攻就自动认定前瞻性充分；若它们主要仍是同一常规装备上的措辞"
                    "或流程微调，应标记process_only。若当前Query仍存在一个明确未覆盖、能够牵引具体"
                    "直接战斗装备、形成直接军事效果，并在传统能力提升、传统缺口弥补、新作战运用、"
                    "制胜战法或能力实现样式上产生实质创新/颠覆增量的机会，可设置"
                    "completion_recommended=true，并只给出一个missing_frontier_opportunity。该审计"
                    "先判断前沿价值和新质增量，不要求机会已经证明为可落实的物理/工程断层，也不要求"
                    "成熟度、工程瓶颈、证据完备或可证伪试验齐全；这些留给后续装备化与工程论证。"
                    "可从新原理、新构型、新效应、新作战运用、跨域组合，以及感知、推进、材料能源、"
                    "直接毁伤、制造成本、自主群体架构等开放维度思考，但不得按维度配额、复制示例或"
                    "堆叠热门词；与Query无直接因果、没有具体装备或没有直接战果时必须判不推荐。"
                    + _query_led_combat_equipment_theme_instruction()
                    + "忽略候选顺序，只输出严格JSON。",
                    {
                        "topic": shared["topic"],
                        "research_route": shared["research_route"],
                        "query_led_combat_equipment_themes": (
                            _query_led_combat_equipment_theme_contract()
                        ),
                        "query_combat_equipment_divergence_brief": (
                            _query_combat_equipment_divergence_brief(
                                str(shared["topic"]),
                                structured_query_brief=shared.get(
                                    "structured_query_brief", {}
                                ),
                            )
                        ),
                        "disruptive_paradigm_seed_library_v2": (
                            disruptive_seed_context(
                                str(shared["topic"]),
                                branch=primary_branch,
                                agent_id="quality_expert_judge",
                            )
                        ),
                        "evaluation_contract": {
                            "semantic_verdict_is_authoritative": True,
                            "numeric_dimensions_are_diagnostic_only": True,
                            "local_hard_gate": False,
                            "read_only": True,
                            "producer_identity_hidden": True,
                            "portfolio_requirement": {
                                "selection_rule": "所有通过query因果、直接军事效果和独立性评审的候选均可入选；对象证据有则优先保留、无则不因此淘汰；数量不是淘汰理由",
                                "s6_card_capacity": int(
                                    swarm_controller.policy.get("finalist_maximum", 12)
                                ),
                                "direct_combat_equipment_must_be_main_body": True,
                                "query_semantics_select_weapon_families": True,
                                "priority_observation_lenses_are_non_exhaustive": True,
                                "support_only_main_directions_forbidden": True,
                            },
                            "s6_release_preflight_required": True,
                            "length_is_non_blocking": True,
                            "frontier_evidence_relaxation": bool(
                                swarm_controller.policy.get(
                                    "frontier_evidence_relaxation"
                                )
                            ),
                            "frontier_confidence_is_not_a_hard_failure": True,
                        },
                        "blind_candidates": blind_candidates,
                        "evidence_index": _compact_prompt_value(
                            _quality_judge_scoped_evidence_index(
                                shared.get("evidence_index", []),
                                candidate_evidence_ids,
                            ),
                            max_string_chars=260,
                            max_list_items=18,
                        ),
                        "valid_reference_ids": sorted(valid_reference_ids),
                    },
                    output_schema,
                    task.max_output_tokens,
                    phase="winning_s5_semantic_admission",
                )
                result = _parse_json_object(text)
                if not result:
                    raise ValueError("quality expert returned invalid JSON")
                raw_assessments = result.get("assessments", [])
                if not isinstance(raw_assessments, list):
                    raw_assessments = []
                assessment_by_id: dict[str, WinningExpertAssessment] = {}
                seen_labels: set[str] = set()
                for raw in raw_assessments:
                    if not isinstance(raw, Mapping):
                        continue
                    blind_label = str(raw.get("blind_label", "")).strip()
                    hypothesis = label_map.get(blind_label)
                    if hypothesis is None or blind_label in seen_labels:
                        continue
                    seen_labels.add(blind_label)
                    assessment = swarm_controller.expert_assessment_from_mapping(
                        raw,
                        hypothesis=hypothesis,
                        blind_label=blind_label,
                        valid_evidence_ids=set(valid_reference_ids),
                        session_ref=runtime_contract["session_ref"],
                    )
                    assessment_by_id[hypothesis.hypothesis_id] = assessment
                    emit_swarm_event(
                        "winning_quality_judge_assessed",
                        actor=instance_id,
                        graph_id=graph.graph_id,
                        hypothesis_id=hypothesis.hypothesis_id,
                        assessment=to_plain(assessment),
                    )
                missing_ids = [
                    item.hypothesis_id
                    for item in ordered
                    if item.hypothesis_id not in assessment_by_id
                ]
                emit_swarm_event(
                    "winning_quality_judge_completed",
                    actor=instance_id,
                    graph_id=graph.graph_id,
                    assessed_count=len(assessment_by_id),
                    missing_hypothesis_ids=missing_ids,
                    elapsed_seconds=round(monotonic() - started_at, 3),
                    **runtime_contract,
                )
                return assessment_by_id, {
                    "status": ("completed" if not missing_ids else "limited"),
                    "role_contract": to_plain(contract),
                    "agent_instance_id": instance_id,
                    "session_ref": runtime_contract["session_ref"],
                    "assessments": [
                        to_plain(item) for item in assessment_by_id.values()
                    ],
                    "portfolio_findings": [
                        str(item)
                        for item in result.get("portfolio_findings", [])
                        if str(item).strip()
                    ][:8],
                    "portfolio_innovation_audit": (
                        _normalize_portfolio_innovation_audit(
                            result.get("portfolio_innovation_audit", {})
                        )
                    ),
                    "missing_hypothesis_ids": missing_ids,
                    "elapsed_seconds": round(monotonic() - started_at, 3),
                }
            except BaseException as exc:
                emit_swarm_event(
                    "winning_quality_judge_failed",
                    actor=instance_id,
                    graph_id=graph.graph_id,
                    failure_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                    **runtime_contract,
                )
                return {}, {
                    "status": "failed",
                    "role_contract": to_plain(contract),
                    "agent_instance_id": instance_id,
                    "session_ref": runtime_contract["session_ref"],
                    "assessments": [],
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:500],
                }

        async def execute_expert_repair_wave(
            assessments: Mapping[str, WinningExpertAssessment],
            *,
            maximum_candidates_override: int | None = None,
        ) -> dict[str, Any]:
            """Repair the strongest ``revise`` candidates, then rebase.

            The expert remains read-only.  Its residuals are routed to
            existing governed S3/S4/S5 roles, executed in parallel against
            one ledger snapshot, and committed through normal versioned
            merge receipts.
            """

            nonlocal graph, ledger, batch_index, maximum_observed_concurrency
            if ledger is None or not swarm_controller.policy.get(
                "expert_repair_enabled"
            ):
                return {"status": "disabled", "tasks": [], "merged_count": 0}
            eligible = swarm_controller.select_expert_repair_assessments(
                assessments,
                hypotheses={item.hypothesis_id: item for item in ledger.hypotheses},
            )
            maximum_candidates = int(
                swarm_controller.policy["expert_repair_max_candidates"]
            )
            if maximum_candidates_override is not None:
                maximum_candidates = min(
                    maximum_candidates,
                    max(0, int(maximum_candidates_override)),
                )
            eligible = eligible[:maximum_candidates]
            repair_reserve = int(
                swarm_controller.policy.get(
                    "expert_repair_reserved_instances", maximum_candidates
                )
            )
            repair_capacity = min(
                graph.maximum_instances,
                len(graph.agent_instances) + min(repair_reserve, len(eligible)),
            )
            repair_wave = (
                max(
                    (item.wave for item in graph.agent_instances),
                    default=0,
                )
                + 1
            )
            repair_instances: list[WinningAgentInstance] = []
            repair_rows: list[dict[str, Any]] = []
            for assessment in eligible:
                if len(graph.agent_instances) >= repair_capacity:
                    break
                archetype = swarm_controller.repair_archetype_for_assessment(assessment)
                spec = SWARM_SPECIALIST_ARCHETYPES.get(archetype)
                if not spec:
                    continue
                quota_residuals = (
                    ["direct_combat_equipment_insufficient"]
                    if assessment.passed
                    and assessment.equipment_classification
                    not in {"direct_combat", "unmanned_combat"}
                    else []
                )
                residuals = list(
                    dict.fromkeys(
                        [
                            *quota_residuals,
                            *assessment.residuals,
                            *assessment.rejection_reasons,
                            *assessment.weaknesses,
                        ]
                    )
                )[:8]
                contract = swarm_controller.govern_role_contract(
                    {
                        "archetype": archetype,
                        **spec,
                        "purpose": (
                            str(spec["purpose"])
                            + " 本实例只修复专家首轮盲评指出的残差，"
                            "不得扩写无关背景或覆盖其他候选。"
                        ),
                        "trigger_residuals": residuals,
                    },
                    mission_node=str(spec["merge_target"]),
                )
                graph = swarm_controller.recruit_into_mission_graph(
                    graph,
                    contract,
                    hypothesis_id=assessment.hypothesis_id,
                    expected_quality_gain=max(
                        float(swarm_controller.policy["minimum_expected_gain"]),
                        0.04,
                    ),
                    depends_on=[],
                )
                recruited = graph.agent_instances[-1]
                recruited = replace(
                    recruited,
                    wave=repair_wave,
                    trigger_residuals=residuals,
                )
                repaired_waves = [
                    [item for item in wave if item != recruited.instance_id]
                    for wave in graph.waves
                ]
                while len(repaired_waves) < repair_wave:
                    repaired_waves.append([])
                repaired_waves[repair_wave - 1].append(recruited.instance_id)
                graph = replace(
                    graph,
                    role_contracts=[*graph.role_contracts[:-1], contract],
                    agent_instances=[*graph.agent_instances[:-1], recruited],
                    waves=repaired_waves,
                )
                contracts[contract.role_contract_id] = contract
                repair_instances.append(recruited)
                repair_rows.append(
                    {
                        "agent_instance_id": recruited.instance_id,
                        "hypothesis_id": assessment.hypothesis_id,
                        "archetype": archetype,
                        "merge_target": recruited.merge_target,
                        "expert_assessment_id": assessment.assessment_id,
                        "residuals": residuals,
                    }
                )
                emit_swarm_event(
                    "winning_quality_repair_planned",
                    actor=recruited.instance_id,
                    graph_id=graph.graph_id,
                    role_contract=to_plain(contract),
                    instance=to_plain(recruited),
                    expert_assessment_id=assessment.assessment_id,
                    hypothesis_id=assessment.hypothesis_id,
                    residuals=residuals,
                )
            if not repair_instances:
                return {
                    "status": "not_needed_or_no_capacity",
                    "tasks": repair_rows,
                    "merged_count": 0,
                }
            snapshot = ledger
            batch_index += 1
            execution_batches.append(
                {
                    "batch": batch_index,
                    "instance_ids": [item.instance_id for item in repair_instances],
                    "mission_nodes": [item.mission_node for item in repair_instances],
                    "base_ledger_version": snapshot.version,
                    "purpose": "expert_residual_repair",
                }
            )
            maximum_observed_concurrency = max(
                maximum_observed_concurrency, len(repair_instances)
            )
            outcomes = await asyncio.gather(
                *[
                    call_instance(
                        item,
                        ledger_snapshot=snapshot,
                        batch_index=batch_index,
                        candidate_scope={item.hypothesis_id},
                    )
                    for item in repair_instances
                ],
                return_exceptions=True,
            )
            merged_count = 0
            failed_count = 0
            merged_hypothesis_ids: set[str] = set()
            for instance, outcome in zip(repair_instances, outcomes):
                completed_instances.add(instance.instance_id)
                instance_hypothesis_ids[instance.instance_id] = {instance.hypothesis_id}
                if isinstance(outcome, BaseException):
                    failed_instances.add(instance.instance_id)
                    failed_count += 1
                    emit_swarm_event(
                        "winning_quality_repair_failed",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        hypothesis_id=instance.hypothesis_id,
                        failure_type=type(outcome).__name__,
                        error_message=str(outcome)[:500],
                    )
                    continue
                _, result, base_version = outcome
                runs.append(
                    {
                        "step": int(instance.mission_node[1:]),
                        "agent_id": instance.instance_id,
                        "template_agent_id": f"winning_swarm_{instance.archetype}",
                        "middle_cycle": 1,
                        "execution_mode": "expert_residual_repair",
                        "wave": instance.wave,
                        "batch": batch_index,
                        "merge_target": instance.merge_target,
                        "status": "completed",
                    }
                )
                raw_rows = result.get("contributions", [])
                if isinstance(raw_rows, Mapping):
                    raw_rows = [raw_rows]
                if not isinstance(raw_rows, list):
                    raw_rows = []
                for ordinal, raw in enumerate(raw_rows, start=1):
                    if not isinstance(raw, Mapping):
                        continue
                    hypothesis_id = str(raw.get("hypothesis_id", ""))
                    if hypothesis_id != instance.hypothesis_id:
                        continue
                    try:
                        quality = max(
                            0.0,
                            min(1.0, float(raw.get("incremental_quality", 0.0))),
                        )
                    except (TypeError, ValueError):
                        quality = 0.0
                    recommendation = str(raw.get("recommendation", "revise"))[:80]
                    findings = [
                        str(item)
                        for item in raw.get("findings", [])
                        if str(item).strip()
                    ][:8]
                    accepted = bool(
                        findings
                        and recommendation != "reject"
                    )
                    patch_fields = {
                        key: raw.get(key)
                        for key in (
                            "title",
                            "nearest_public_baseline",
                            "changed_confrontation_variable",
                            "findings",
                            "mechanism_chain",
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
                            "patch_mode",
                            "replace_fields",
                        )
                        if raw.get(key) not in (None, "", [], {})
                    }
                    repaired_evidence_ids = swarm_controller.sanitize_evidence_ids(
                        raw.get(
                            "evidence_ids",
                            raw.get("evidence_refs", []),
                        ),
                        set(valid_reference_ids),
                    )
                    if repaired_evidence_ids:
                        patch_fields["evidence_ids"] = list(repaired_evidence_ids)
                    contribution = WinningContribution(
                        contribution_id=(
                            "winning-expert-repair-"
                            + sha256(
                                f"{instance.instance_id}:{hypothesis_id}:{ordinal}".encode()
                            ).hexdigest()[:16]
                        ),
                        agent_instance_id=instance.instance_id,
                        role_contract_id=instance.role_contract_id,
                        hypothesis_id=hypothesis_id,
                        merge_target=instance.merge_target,
                        base_ledger_version=base_version,
                        hypothesis_patch=patch_fields,
                        quality_dimensions={"incremental_quality": quality},
                        evidence_ids=repaired_evidence_ids,
                        residuals_resolved=[
                            str(item)
                            for item in raw.get("residuals_resolved", [])
                            if str(item).strip()
                        ][:8],
                        incremental_quality=quality,
                        recommendation=recommendation,
                        accepted=accepted,
                    )
                    contribution_rows.append(contribution)
                    ledger_after, receipt = swarm_controller.merge_contribution(
                        ledger, contribution
                    )
                    merge_receipts.append(receipt)
                    if receipt.rebase_required:
                        contribution = swarm_controller.rebase_contribution(
                            contribution, ledger
                        )
                        ledger_after, receipt = swarm_controller.merge_contribution(
                            ledger, contribution
                        )
                        merge_receipts.append(receipt)
                    ledger = ledger_after
                    if receipt.status == "merged":
                        merged_count += 1
                        merged_hypothesis_ids.add(hypothesis_id)
                    emit_swarm_event(
                        "winning_quality_repair_completed",
                        actor=instance.instance_id,
                        graph_id=graph.graph_id,
                        hypothesis_id=hypothesis_id,
                        contribution_id=contribution.contribution_id,
                        status=receipt.status,
                        resulting_ledger_version=receipt.resulting_ledger_version,
                    )
            return {
                "status": "completed" if not failed_count else "limited",
                "tasks": repair_rows,
                "merged_count": merged_count,
                "merged_hypothesis_ids": sorted(merged_hypothesis_ids),
                "failed_count": failed_count,
                "base_ledger_version": snapshot.version,
                "resulting_ledger_version": ledger.version,
            }

        async def execute_portfolio_gap_completion_wave(
            assessments: Mapping[str, WinningExpertAssessment],
            *,
            innovation_audit: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Generate distinct replacements when expert pruning leaves a gap.

            Repairing a baseline-only or over-coupled concept cannot always
            create genuine novelty. One bounded S3 generator therefore gets
            the complete assessed ledger and may add the independently
            evidenced, non-duplicate direct-equipment hypotheses that fit
            the remaining governed candidate capacity.
            The new rows still require the independent expert judge; this
            path never promotes a failed candidate by quota alone.
            """

            nonlocal graph, ledger, batch_index, maximum_observed_concurrency
            if ledger is None:
                return {
                    "status": "not_available",
                    "created_count": 0,
                    "created_hypothesis_ids": [],
                }
            minimum = int(swarm_controller.policy.get("finalist_minimum", 1))
            coverage = swarm_controller.passed_portfolio_coverage(
                ledger,
                assessments,
            )
            normalized_innovation_audit = _normalize_portfolio_innovation_audit(
                innovation_audit or {}
            )
            frontier_shortfall = _portfolio_innovation_completion_requested(
                normalized_innovation_audit
            )
            passed_count = int(coverage["passed_count"])
            if coverage["ready"] and not frontier_shortfall:
                return {
                    "status": "not_required",
                    "created_count": 0,
                    "created_hypothesis_ids": [],
                    "portfolio_coverage": coverage,
                }
            if len(graph.agent_instances) >= graph.maximum_instances:
                return {
                    "status": "no_capacity",
                    "created_count": 0,
                    "created_hypothesis_ids": [],
                }

            completion_archetype = (
                "weak_signal_scout"
                if frontier_shortfall
                else "disruptive_mechanism_generator"
            )
            spec = SWARM_SPECIALIST_ARCHETYPES[completion_archetype]
            failed_rows = sorted(
                (item for item in assessments.values() if not item.passed),
                key=lambda item: (-item.weighted_score, item.hypothesis_id),
            )
            residual_digest = [
                text
                for item in failed_rows[:4]
                for text in (
                    item.rejection_reasons[:1]
                    or item.weaknesses[:1]
                    or item.residuals[:1]
                )
            ][:4]
            contract = swarm_controller.govern_role_contract(
                {
                    "archetype": completion_archetype,
                    **spec,
                    "purpose": (
                        (
                            "专家组合创新审计确认现有候选仍存在前沿、新质或颠覆性机会缺口。"
                            "缺口摘要："
                            + str(
                                normalized_innovation_audit.get(
                                    "missing_frontier_opportunity", {}
                                )
                            )[:1000]
                            + "。执行一次有界前沿补全；已有通过候选全部保留。"
                            if frontier_shortfall
                            else "专家首轮后组合有"
                            f"{passed_count}项合格，尚未满足{minimum}项可直接承担作战任务、"
                            "且已通过五轴语义独立性判断的装备方向。"
                        )
                        + "对照完整候选账本与驳回原因，生成数量由证据、机制独立性和剩余"
                        "候选容量决定的不重复、可独立立项和可证伪替代武器方向；不得凑数。"
                        + (
                            "主要驳回边界：" + "；".join(residual_digest)
                            if residual_digest
                            else ""
                        )
                    ),
                    "trigger_residuals": [
                        "portfolio_direction_shortfall",
                        "direct_combat_equipment_insufficient",
                        *(
                            ["frontier_innovation_shortfall"]
                            if frontier_shortfall
                            else []
                        ),
                    ],
                },
                mission_node="S3",
            )
            graph = swarm_controller.recruit_into_mission_graph(
                graph,
                contract,
                hypothesis_id="",
                expected_quality_gain=max(
                    0.04,
                    float(swarm_controller.policy["minimum_expected_gain"]),
                ),
                depends_on=[],
            )
            instance = graph.agent_instances[-1]
            completion_wave = (
                max(
                    (item.wave for item in graph.agent_instances[:-1]),
                    default=0,
                )
                + 1
            )
            instance = replace(
                instance,
                wave=completion_wave,
                trigger_residuals=[
                    "portfolio_direction_shortfall",
                    "direct_combat_equipment_insufficient",
                    *(["frontier_innovation_shortfall"] if frontier_shortfall else []),
                ],
            )
            if frontier_shortfall:
                portfolio_innovation_audits_by_instance[instance.instance_id] = dict(
                    normalized_innovation_audit
                )
            repaired_waves = [
                [item for item in wave if item != instance.instance_id]
                for wave in graph.waves
            ]
            while len(repaired_waves) < completion_wave:
                repaired_waves.append([])
            repaired_waves[completion_wave - 1].append(instance.instance_id)
            graph = replace(
                graph,
                role_contracts=[*graph.role_contracts[:-1], contract],
                agent_instances=[*graph.agent_instances[:-1], instance],
                waves=repaired_waves,
            )
            contracts[contract.role_contract_id] = contract
            snapshot = ledger
            candidate_scope = {item.hypothesis_id for item in snapshot.hypotheses}
            batch_index += 1
            execution_batches.append(
                {
                    "batch": batch_index,
                    "instance_ids": [instance.instance_id],
                    "mission_nodes": ["S3"],
                    "base_ledger_version": snapshot.version,
                    "purpose": "expert_portfolio_gap_completion",
                }
            )
            maximum_observed_concurrency = max(maximum_observed_concurrency, 1)
            emit_swarm_event(
                "winning_portfolio_gap_completion_planned",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                passed_count=passed_count,
                finalist_minimum=minimum,
                direct_combat_equipment_count=(
                    coverage["direct_combat_equipment_count"]
                ),
                distinct_direct_equipment_family_count=(
                    coverage["distinct_direct_equipment_family_count"]
                ),
                preferred_distinct_direct_equipment=(
                    coverage["preferred_distinct_direct_equipment"]
                ),
                candidate_count=len(snapshot.hypotheses),
                frontier_innovation_shortfall=frontier_shortfall,
                portfolio_innovation_audit=normalized_innovation_audit,
            )
            try:
                _, result, _ = await call_instance(
                    instance,
                    ledger_snapshot=snapshot,
                    batch_index=batch_index,
                    candidate_scope=candidate_scope,
                )
            except BaseException as exc:
                failed_instances.add(instance.instance_id)
                completed_instances.add(instance.instance_id)
                emit_swarm_event(
                    "winning_portfolio_gap_completion_failed",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    failure_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                )
                return {
                    "status": "failed",
                    "created_count": 0,
                    "created_hypothesis_ids": [],
                    "error_type": type(exc).__name__,
                }

            completed_instances.add(instance.instance_id)
            runs.append(
                {
                    "step": 3,
                    "agent_id": instance.instance_id,
                    "template_agent_id": (f"winning_swarm_{completion_archetype}"),
                    "middle_cycle": 1,
                    "execution_mode": "expert_portfolio_gap_completion",
                    "wave": instance.wave,
                    "batch": batch_index,
                    "merge_target": "S3",
                    "status": "completed",
                }
            )
            raw_rows = result.get("hypotheses", [])
            if not isinstance(raw_rows, list):
                raw_rows = []
            passed_hypotheses = [
                item
                for item in snapshot.hypotheses
                if item.hypothesis_id in assessments
                and assessments[item.hypothesis_id].passed
            ]
            raw_rows, recovered_count = _prepare_portfolio_gap_completion_rows(
                raw_rows,
                shared.get("evidence_index", []),
                topic=str(shared.get("topic", "")),
                passed_hypotheses=passed_hypotheses,
            )
            if recovered_count:
                emit_swarm_event(
                    "winning_specialized_seed_recovered",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    archetype=(
                        "frontier_portfolio_gap_completion"
                        if frontier_shortfall
                        else "offensive_portfolio_gap_completion"
                    ),
                    recovered_count=recovered_count,
                    candidate_count=len(raw_rows),
                    stop_reason=str(result.get("stop_reason", ""))[:300],
                )
            before_ids = {item.hypothesis_id for item in ledger.hypotheses}
            produced_ids: set[str] = set()
            task = task_for_instance(instance)
            remaining_candidate_capacity = max(
                0,
                int(swarm_controller.policy.get("breadth_hypothesis_maximum", 12))
                - len(snapshot.hypotheses),
            )
            for ordinal, raw in enumerate(
                raw_rows[:remaining_candidate_capacity], start=1
            ):
                if not isinstance(raw, Mapping):
                    continue
                candidate = swarm_controller.hypothesis_from_mapping(
                    raw,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                    ordinal=ordinal,
                )
                hypotheses.append(candidate)
                produced_ids.add(candidate.hypothesis_id)
                emit_swarm_event(
                    "winning_candidate_branch_created",
                    actor=instance.instance_id,
                    graph_id=graph.graph_id,
                    hypothesis_id=candidate.hypothesis_id,
                    mission_node="S3",
                    score=candidate.score,
                    completion_reason="portfolio_direction_shortfall",
                )
            id_remap = refresh_candidate_ledger()
            resolved_ids = {
                canonical_candidate_id(id_remap.get(hypothesis_id, hypothesis_id))
                for hypothesis_id in produced_ids
            }
            current_ids = {item.hypothesis_id for item in ledger.hypotheses}
            created_ids = sorted(
                hypothesis_id
                for hypothesis_id in resolved_ids
                if hypothesis_id in current_ids and hypothesis_id not in before_ids
            )
            instance_hypothesis_ids[instance.instance_id] = set(created_ids)
            emit_swarm_event(
                "winning_portfolio_gap_completion_completed",
                actor=instance.instance_id,
                graph_id=graph.graph_id,
                created_count=len(created_ids),
                created_hypothesis_ids=created_ids,
                stop_reason=str(result.get("stop_reason", ""))[:300],
            )
            return {
                "status": "completed" if created_ids else "empty",
                "created_count": len(created_ids),
                "created_hypothesis_ids": created_ids,
                "agent_instance_id": instance.instance_id,
                "base_ledger_version": snapshot.version,
                "resulting_ledger_version": ledger.version,
                "portfolio_coverage_before": coverage,
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
            s3_s4_generation_finished = all(
                item.instance_id in completed_instances | failed_instances
                for item in graph.agent_instances
                if item.mission_node in {"S3", "S4"} and not item.hypothesis_id
            )
            downstream_waiting = any(
                item.mission_node in {"S5", "S6"} for item in pending.values()
            )
            if (
                not candidate_competition_converged
                and ledger is not None
                and not running_instances
                and s3_s4_generation_finished
                and downstream_waiting
            ):
                compact_candidate_ledger_for_review()
                if ledger is not None:
                    semantic_clustered_ledger_version = ledger.version
                emit_swarm_event(
                    "winning_candidate_competition_converged",
                    actor="winning_swarm_controller",
                    graph_id=graph.graph_id,
                    candidate_count=(
                        len(ledger.hypotheses) if ledger is not None else 0
                    ),
                    convergence_stage="before_s5",
                    rule=(
                        "S3/S4按Query维度完成创新装备生成后，由S5统一执行语义准入、合并与判退"
                    ),
                )
                candidate_competition_converged = True
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
                        or all(
                            seed_instance.instance_id
                            in completed_instances | failed_instances
                            for seed_instance in graph.agent_instances
                            if seed_instance.mission_node in {"S3", "S4"}
                            and not seed_instance.hypothesis_id
                        )
                    )
                    and (
                        item.archetype != "independent_portfolio_reviewer"
                        or (
                            not any(
                                other.instance_id != item.instance_id
                                and other.archetype != "independent_portfolio_reviewer"
                                for other in pending.values()
                            )
                            and not any(
                                running_item.archetype
                                != "independent_portfolio_reviewer"
                                for running_item, _, _ in running_instances.values()
                            )
                        )
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
                    produced_candidates: list[WinningHypothesis] = []
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
                        produced_candidates.append(candidate)
                        emit_swarm_event(
                            "winning_candidate_branch_created",
                            actor=instance.instance_id,
                            graph_id=graph.graph_id,
                            hypothesis_id=candidate.hypothesis_id,
                            mission_node=instance.mission_node,
                            score=candidate.score,
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
                    if instance.mission_node not in {"S3", "S4"}:
                        for candidate in produced_candidates:
                            candidate_id = id_remap.get(
                                candidate.hypothesis_id,
                                candidate.hypothesis_id,
                            )
                            governed_candidate = next(
                                (
                                    item
                                    for item in ledger.hypotheses
                                    if item.hypothesis_id == candidate_id
                                ),
                                None,
                            )
                            if governed_candidate is None:
                                continue
                            gate = swarm_controller.evaluate_gate(
                                governed_candidate, stage="targeted"
                            )
                            declared_residuals = [
                                str(item)
                                for item in result.get("quality_residuals", [])
                                if str(item).strip()
                            ]
                            # Sparse public evidence is a confidence and
                            # boundary annotation for a forward-looking
                            # S3 concept, not a reason to materialize a new
                            # verifier session per candidate. The shared
                            # S5 evidence reviewer still checks any claims
                            # that survive semantic competition.
                            non_recruiting_residuals = {
                                "evidence_insufficient",
                                "equipment_object_evidence_missing",
                            }
                            recruitment_residuals = list(
                                dict.fromkeys(
                                    residual
                                    for residual in [
                                        *declared_residuals,
                                        *gate.residuals,
                                    ]
                                    if residual not in non_recruiting_residuals
                                )
                            )
                            for residual in recruitment_residuals[:2]:
                                archetype = swarm_controller.archetype_for_residual(
                                    residual
                                )
                                pair = (candidate_id, archetype)
                                if (
                                    pair in recruited_pairs
                                    or len(graph.agent_instances)
                                    >= producer_instance_limit
                                ):
                                    continue
                                spec = SWARM_SPECIALIST_ARCHETYPES.get(archetype)
                                if not spec:
                                    continue
                                contract = swarm_controller.govern_role_contract(
                                    {"archetype": archetype, **spec},
                                    mission_node=str(spec["merge_target"]),
                                )
                                graph = swarm_controller.recruit_into_mission_graph(
                                    graph,
                                    contract,
                                    hypothesis_id=candidate_id,
                                    expected_quality_gain=max(
                                        0.03, instance.expected_quality_gain
                                    ),
                                    depends_on=[instance.instance_id],
                                )
                                recruited = graph.agent_instances[-1]
                                contracts[contract.role_contract_id] = contract
                                pending[recruited.instance_id] = recruited
                                recruited_pairs.add(pair)
                                emit_swarm_event(
                                    "winning_agent_instance_recruited",
                                    actor=recruited.instance_id,
                                    graph_id=graph.graph_id,
                                    role_contract=to_plain(contract),
                                    instance=to_plain(recruited),
                                    trigger_residual=residual,
                                    hypothesis_id=candidate_id,
                                )
                else:
                    if ledger is None:
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
                    scope_id=f"{graph.graph_id}:pre-expert"
                )
            compact_candidate_ledger_for_review()
        (
            initial_expert_assessments,
            initial_expert_summary,
        ) = await execute_quality_expert_judge(
            ledger,
            hypothesis_ids=initial_expert_review_scope,
        )
        expert_assessments = dict(initial_expert_assessments)
        expert_rounds = [initial_expert_summary]
        expert_repair_waves: list[dict[str, Any]] = []
        portfolio_completion_waves: list[dict[str, Any]] = []
        portfolio_completion_attempted = False
        maximum_expert_rounds = int(
            host._runtime_budgets.get("maximum_quality_judge_model_calls", 2)
        )
        finalist_minimum = int(swarm_controller.policy.get("finalist_minimum", 1))
        frontloaded_dynamic = (
            swarm_controller.policy.get("policy_id") == "winning_swarm_dynamic_v2"
        )
        while len(expert_rounds) < maximum_expert_rounds:
            coverage = swarm_controller.passed_portfolio_coverage(
                ledger,
                expert_assessments,
            )
            portfolio_innovation_audit = _normalize_portfolio_innovation_audit(
                expert_rounds[-1].get("portfolio_innovation_audit", {})
            )
            frontier_completion_requested = _portfolio_innovation_completion_requested(
                portfolio_innovation_audit
            )
            passed_count = int(coverage["passed_count"])
            # The first expert pass uses a compact blind pool. A ready
            # pool must not hide other independently generated weapon
            # candidates from the dynamic portfolio review.
            if coverage["ready"]:
                refresh_candidate_ledger()
            unassessed_after_refresh = {
                item.hypothesis_id for item in ledger.hypotheses
            } - set(expert_assessments)
            if (
                coverage["ready"]
                and not unassessed_after_refresh
                and not frontier_completion_requested
            ):
                break
            if not portfolio_completion_attempted:
                portfolio_completion_attempted = True
                # The compact first blind-review pool is not the complete
                # mission-graph ledger. Restore the bounded ledger and use
                # the second expert call on diverse, previously unassessed
                # candidates before paying for another generator. This
                # keeps the expert gate intact while avoiding the failure
                # mode where 18 useful candidates collapse to three passed
                # variants from one equipment family.
                refresh_candidate_ledger()
                review_capacity = max(
                    1,
                    int(swarm_controller.policy.get("expert_candidate_pool_maximum", 8))
                    - 1,
                )
                unassessed_ids = (
                    swarm_controller.select_unassessed_portfolio_candidates(
                        ledger,
                        expert_assessments,
                        maximum=review_capacity,
                    )
                )
                if unassessed_ids:
                    completion_summary = {
                        "status": "existing_ledger_reused",
                        "created_count": 0,
                        "created_hypothesis_ids": [],
                        "reused_count": len(unassessed_ids),
                        "reused_hypothesis_ids": list(unassessed_ids),
                    }
                elif frontloaded_dynamic:
                    # Dynamic-v2 completes divergence before realization. Do
                    # not reopen S3 after S4/S5 or an expert portfolio review;
                    # late innovation residuals remain an auditable finding for
                    # the next run rather than spawning a post-hoc generator.
                    completion_summary = {
                        "status": "frontloaded_generation_closed",
                        "created_count": 0,
                        "created_hypothesis_ids": [],
                        "reused_count": 0,
                        "reused_hypothesis_ids": [],
                    }
                    portfolio_completion_waves.append(completion_summary)
                    break
                else:
                    completion_summary = await execute_portfolio_gap_completion_wave(
                        expert_assessments,
                        innovation_audit=portfolio_innovation_audit,
                    )
                portfolio_completion_waves.append(completion_summary)
                completion_ids = set(
                    completion_summary.get("created_hypothesis_ids", [])
                )
                rejudge_ids = {
                    *completion_ids,
                    *unassessed_ids,
                }
                remaining_repair_slots = _portfolio_remaining_repair_slots(
                    passed_count=passed_count,
                    finalist_minimum=finalist_minimum,
                    completion_count=len(completion_ids),
                )
                if frontloaded_dynamic:
                    remaining_repair_slots = 0
                if passed_count < finalist_minimum:
                    # Reserve one targeted repair lane even when the
                    # restored ledger already offers enough unassessed
                    # candidates. It runs in parallel and shares the same
                    # final expert call.
                    if not frontloaded_dynamic:
                        remaining_repair_slots = max(
                            1,
                            remaining_repair_slots,
                        )
                combined_repair_attempted = False
                if remaining_repair_slots:
                    combined_repair_attempted = True
                    repair_summary = await execute_expert_repair_wave(
                        expert_assessments,
                        maximum_candidates_override=remaining_repair_slots,
                    )
                    expert_repair_waves.append(repair_summary)
                    rejudge_ids.update(repair_summary.get("merged_hypothesis_ids", []))
                if rejudge_ids:
                    cluster_remap = await semantic_cluster_candidate_ledger(
                        scope_id=f"{graph.graph_id}:pre-expert-round-{len(expert_rounds) + 1}"
                    )
                    for source_id, target_id in cluster_remap.items():
                        expert_assessments.pop(source_id, None)
                        rejudge_ids.discard(source_id)
                        rejudge_ids.add(canonical_candidate_id(target_id))
                    ledger_ids = {item.hypothesis_id for item in ledger.hypotheses}
                    rejudge_ids = {
                        canonical_candidate_id(item)
                        for item in rejudge_ids
                        if canonical_candidate_id(item) in ledger_ids
                    }
                    (
                        completion_assessments,
                        completion_expert_summary,
                    ) = await execute_quality_expert_judge(
                        ledger,
                        hypothesis_ids=rejudge_ids,
                    )
                    expert_assessments.update(completion_assessments)
                    expert_rounds.append(completion_expert_summary)
                    continue
                if combined_repair_attempted:
                    break
            repair_summary = await execute_expert_repair_wave(expert_assessments)
            expert_repair_waves.append(repair_summary)
            if not repair_summary.get("merged_count", 0):
                break
            repaired_hypothesis_ids = set(
                repair_summary.get("merged_hypothesis_ids", [])
            )
            cluster_remap = await semantic_cluster_candidate_ledger(
                scope_id=f"{graph.graph_id}:pre-repair-expert-round-{len(expert_rounds) + 1}"
            )
            for source_id, target_id in cluster_remap.items():
                expert_assessments.pop(source_id, None)
                repaired_hypothesis_ids.discard(source_id)
                repaired_hypothesis_ids.add(canonical_candidate_id(target_id))
            ledger_ids = {item.hypothesis_id for item in ledger.hypotheses}
            repaired_hypothesis_ids = {
                canonical_candidate_id(item)
                for item in repaired_hypothesis_ids
                if canonical_candidate_id(item) in ledger_ids
            }
            (
                repaired_assessments,
                repaired_expert_summary,
            ) = await execute_quality_expert_judge(
                ledger,
                hypothesis_ids=repaired_hypothesis_ids,
            )
            expert_assessments.update(repaired_assessments)
            expert_rounds.append(repaired_expert_summary)
        merged_repair_ids = list(
            dict.fromkeys(
                hypothesis_id
                for wave in expert_repair_waves
                for hypothesis_id in wave.get("merged_hypothesis_ids", [])
            )
        )
        expert_repair_summary = {
            "status": (
                "completed"
                if any(wave.get("merged_count", 0) for wave in expert_repair_waves)
                else "not_required"
            ),
            "merged_count": sum(
                int(wave.get("merged_count", 0) or 0) for wave in expert_repair_waves
            ),
            "merged_hypothesis_ids": merged_repair_ids,
            "waves": expert_repair_waves,
        }
        portfolio_completion_summary = {
            "status": (
                "completed"
                if any(
                    wave.get("created_count", 0) for wave in portfolio_completion_waves
                )
                else (
                    str(portfolio_completion_waves[-1].get("status", "not_required"))
                    if portfolio_completion_waves
                    else "not_required"
                )
            ),
            "created_count": sum(
                int(wave.get("created_count", 0) or 0)
                for wave in portfolio_completion_waves
            ),
            "created_hypothesis_ids": list(
                dict.fromkeys(
                    hypothesis_id
                    for wave in portfolio_completion_waves
                    for hypothesis_id in wave.get("created_hypothesis_ids", [])
                )
            ),
            "reused_count": sum(
                int(wave.get("reused_count", 0) or 0)
                for wave in portfolio_completion_waves
            ),
            "reused_hypothesis_ids": list(
                dict.fromkeys(
                    hypothesis_id
                    for wave in portfolio_completion_waves
                    for hypothesis_id in wave.get("reused_hypothesis_ids", [])
                )
            ),
            "waves": portfolio_completion_waves,
        }
        final_expert_summary = expert_rounds[-1]
        latest_expert_status = str(final_expert_summary.get("status", "limited"))
        effective_expert_status = _effective_expert_judge_status(
            expert_rounds,
            assessed_count=len(expert_assessments),
            expected_count=len(ledger.hypotheses),
        )
        expert_judge_summary = {
            **final_expert_summary,
            # Preserve a complete first-round blind review when the
            # optional targeted rejudge suffers a transport/auth failure.
            # Previously assessed candidates conservatively retain their
            # prior score; the failed latest round remains visible.
            "status": effective_expert_status,
            "latest_round_status": latest_expert_status,
            "rejudge_degraded": (
                effective_expert_status == "completed"
                and latest_expert_status != "completed"
            ),
            "assessments": [to_plain(item) for item in expert_assessments.values()],
            "round_count": len(expert_rounds),
            "rounds": expert_rounds,
            "repair_wave": expert_repair_summary,
            "portfolio_completion_wave": portfolio_completion_summary,
        }
        expert_objectives = {
            hypothesis_id: swarm_controller.expert_objective_scores(assessment)
            for hypothesis_id, assessment in expert_assessments.items()
        }
        decision: PortfolioDecision = swarm_controller.portfolio_decision(
            ledger,
            objective_scores=expert_objectives,
            expert_assessments=expert_assessments,
        )
        emit_swarm_event(
            "winning_inner_loop_evaluated",
            actor="winning_s5_semantic_admission",
            graph_id=graph.graph_id,
            loop="inner",
            cycle=int(expert_judge_summary.get("round_count", 1) or 1),
            passed=decision.quality_judge_passed,
            candidate_count=len(expert_assessments),
            repaired_count=int(expert_repair_summary.get("merged_count", 0) or 0),
            issues=[
                f"{assessment.hypothesis_id}:{assessment.verdict}"
                for assessment in expert_assessments.values()
                if assessment.verdict != "pass"
            ][:8],
        )
        selected_ids = set(decision.selected_hypothesis_ids)
        final_hypotheses = [
            item for item in ledger.hypotheses if item.hypothesis_id in selected_ids
        ]
        pending_verification_ids = {
            item.hypothesis_id
            for item in final_hypotheses
            if not (
                item.hypothesis_id in expert_assessments
                and expert_assessments[item.hypothesis_id].passed
            )
            and swarm_controller.assessment_allows_pending_verification(
                item,
                expert_assessments.get(item.hypothesis_id),
            )
        }

        def capability_direction(
            item: WinningHypothesis,
            position: int,
        ) -> dict[str, Any]:
            assessment = expert_assessments.get(item.hypothesis_id)
            semantic_identity = swarm_controller.equipment_family_signature(item)
            equipment_form = _winning_primary_equipment_form(item)
            military_value = "；".join(item.direct_military_effects[:3])
            mechanism = "→".join(item.mechanism_chain[:5])
            failure_boundary = "；".join(item.failure_boundaries[:3])
            validation = "；".join(item.validation_plan[:3])
            constraints = [
                *item.trl_constraints,
                *item.cost_constraints,
                *item.industrial_constraints,
            ]
            engineering_score = (
                assessment.dimension_scores.get("engineering_feasibility", 0.0)
                if assessment is not None
                else item.score
            )
            feasibility = (
                "4"
                if engineering_score >= 0.78
                else "3"
                if engineering_score >= 0.62
                else "2"
            )
            direction_type = (
                "upgrade" if item.implementation_path == "upgrade" else "new_capability"
            )
            equipment_classification = (
                str(assessment.equipment_classification).strip().lower()
                if assessment is not None
                else ""
            )
            direct_combat_equipment = swarm_controller.is_direct_combat_equipment(
                item,
                assessment,
            )
            candidate_title = _winning_portfolio_title(item)
            visible_name = candidate_title
            capability_gap = (
                f"现有基线“{item.nearest_public_baseline}”尚不能在"
                f"“{item.changed_confrontation_variable}”变化后稳定形成："
                f"{military_value or item.novelty_delta}"
            )
            topic_text = str(shared.get("topic", ""))
            target_scenario = _winning_combat_scene(
                topic_text,
                equipment_form=equipment_form,
                changed_variable=item.changed_confrontation_variable,
            )
            scientific_principle = (
                item.frontier_principle
                or item.changed_confrontation_variable
                or item.novelty_delta
                or "任务闭环与体系协同原理"
            )
            enabling_technologies = list(
                dict.fromkeys(
                    [
                        item.frontier_principle,
                        item.technology_discontinuity,
                        *item.equipment_forms[:2],
                        *item.system_interfaces[:3],
                    ]
                )
            )
            enabling_technologies = [
                value for value in enabling_technologies if str(value).strip()
            ]
            operational_concept = (
                f"以{equipment_form or '具体武器平台'}实施分散部署、任务装订、"
                "受控交战、效应评估和再组织"
            )
            project_function = (
                item.project_function or military_value or item.novelty_delta
            )
            capability_outcome = military_value or item.novelty_delta
            winning_mechanism = (
                f"相对{item.nearest_public_baseline}，{item.novelty_delta}；"
                f"{item.technology_discontinuity + '；' if item.technology_discontinuity else ''}"
                f"通过{mechanism or '压缩任务闭环'}改变对手的时间、成本、平台或毁伤交换关系"
            )
            capability_portrait = build_agent_led_capability_portrait(
                name=visible_name,
                scenario=target_scenario,
                problem=capability_gap,
                principle=scientific_principle,
                technologies=enabling_technologies,
                operational_concept=operational_concept,
                operational_steps=item.mechanism_chain,
                capability=capability_outcome,
                effect=military_value or item.novelty_delta,
                winning_mechanism=winning_mechanism,
                equipment_form=equipment_form,
            )
            confidence = (
                assessment.weighted_score if assessment is not None else item.score
            )
            pending_verification = item.hypothesis_id in pending_verification_ids
            prioritized_evidence_refs = _prioritize_equipment_evidence_refs(
                item.evidence_ids
            )
            has_direct_object_evidence = any(
                ref.startswith("ev-weapon_equipment-")
                for ref in prioritized_evidence_refs
            )
            foresight_evidence_status = (
                "direct_object_baseline"
                if direction_type == "upgrade" or has_direct_object_evidence
                else "analogous_project_evidence"
            )
            return {
                "hypothesis_id": item.hypothesis_id,
                "name": visible_name,
                "source_hypothesis_title": _winning_portfolio_title(item),
                "priority": f"P{position}",
                "type": direction_type,
                "function": project_function,
                "project_function": project_function,
                "feasibility": feasibility,
                "feasibility_basis": "依据专家工程可行性评分、公开基线及TRL/成本/产能约束分级，仍须样机和对抗试验校准。",
                "horizon": item.technology_horizon or "mid",
                "direct_evidence_refs": list(prioritized_evidence_refs[:3]),
                "foresight_evidence_status": foresight_evidence_status,
                "evidence_boundary": item.evidence_boundary,
                "derived_from": ["公开证据与候选制胜机理综合"],
                "military_value": military_value,
                "depth_mechanism": mechanism,
                "foresight": "；".join(item.cross_scenario_results[:2]),
                "novelty": item.novelty_delta,
                "frontier_principle": item.frontier_principle,
                "technology_discontinuity": item.technology_discontinuity,
                "technology_horizon": item.technology_horizon,
                "engineering_bottleneck": item.engineering_bottleneck,
                "strike_countermeasure_value": military_value,
                "equipment_form": equipment_form,
                "equipment_semantic_identity": semantic_identity,
                "equipment_classification": equipment_classification,
                "equipment_semantic_assessment": {
                    "classification": equipment_classification,
                    "direct_combat_effect": direct_combat_equipment,
                    "support_only": equipment_classification
                    in {"system_link", "support_only", "non_equipment"},
                    "unmanned_combat": equipment_classification
                    == "unmanned_combat",
                    "concrete_equipment": equipment_classification
                    != "non_equipment",
                    "query_alignment_confirmed": bool(
                        assessment is not None and assessment.passed
                    ),
                    "rationale": "；".join(
                        assessment.strengths[:2]
                        if assessment is not None
                        else []
                    ),
                },
                "primary_equipment_identity": equipment_form,
                "unique_operational_role": project_function,
                "launch_or_release_domain": "由该装备任务构型限定的部署、发射或释放域",
                "target_and_direct_effect": military_value,
                "winning_summary_seed": item.reference_overview,
                "non_substitutable_difference": item.changed_confrontation_variable,
                "portfolio_identity_contract": {
                    "hypothesis_id": item.hypothesis_id,
                    "immutable_fields": [
                        "primary_equipment_identity",
                        "equipment_form",
                        "launch_or_release_domain",
                        "target_and_direct_effect",
                        "baseline_system",
                        "direct_evidence_refs",
                    ],
                    "operational_axes": {
                        "platform_or_release_form": equipment_form,
                        "target_and_direct_effect": military_value,
                        "changed_confrontation_variable": (
                            item.changed_confrontation_variable
                        ),
                        "mechanism_and_timing": list(item.mechanism_chain[:4]),
                        "verification_and_failure_boundary": [
                            *item.validation_plan[:2],
                            *item.failure_boundaries[:2],
                        ],
                    },
                    "minimum_cross_card_independent_axes": int(
                        swarm_controller.policy.get(
                            "same_family_minimum_independent_axes",
                            2,
                        )
                    ),
                    "downstream_mutation_scope": (
                        "S4-S5只补全或收窄，S6只撰写已选卡；"
                        "不得新增、删除、换装或重命名主装备"
                    ),
                },
                "operational_mechanism": mechanism,
                "target_scenario": target_scenario,
                "problem_statement": capability_gap,
                "scientific_principle": scientific_principle,
                "enabling_technologies": enabling_technologies,
                "operational_concept": operational_concept,
                "operational_process": list(item.mechanism_chain[:6]),
                "capability_outcome": capability_outcome,
                "winning_mechanism": winning_mechanism,
                "development_path": (
                    f"围绕{equipment_form}开展工程样机、体系接口和对抗试验；"
                    f"关键瓶颈为{item.engineering_bottleneck or '待样机试验识别'}；"
                    f"通过条件为{validation}。"
                ),
                "future_trigger": "；".join(item.cross_scenario_results[:2]),
                "adversary_adaptation": "；".join(item.adversary_adaptations[:3]),
                "failure_boundary": failure_boundary,
                "query_relevance": (
                    f"通过改变“{item.changed_confrontation_variable}”，"
                    f"在当前任务链中形成{military_value}。"
                ),
                "baseline_system": item.nearest_public_baseline,
                "capability_gap": capability_gap,
                "upgrade_package": list(
                    dict.fromkeys(
                        [
                            *item.equipment_forms[:4],
                            *item.system_interfaces[:4],
                        ]
                    )
                )[:6]
                if direction_type == "upgrade"
                else [],
                "combat_effect_uplift": military_value,
                "strike_chain_contribution": mechanism,
                "upgrade_boundary": "；".join(constraints[:3]),
                "capability_portrait": capability_portrait,
                "confidence": confidence,
                "verification_status": (
                    "pending" if pending_verification else "assessed"
                ),
                "confidence_limited": pending_verification,
                "selection_quality_status": (
                    "new_frontier_pending_verification"
                    if pending_verification
                    else "expert_assessed"
                ),
                "mission_effects": list(item.direct_military_effects),
                "mechanism_chain": list(item.mechanism_chain),
                "equipment_forms": list(item.equipment_forms),
                "system_interfaces": list(item.system_interfaces),
                "constraints": constraints,
                "validation_plan": list(item.validation_plan),
                "evidence_ids": list(item.evidence_ids),
                "failure_boundaries": list(item.failure_boundaries),
                "score": item.score,
                "expert_score": (
                    expert_assessments[item.hypothesis_id].weighted_score
                    if item.hypothesis_id in expert_assessments
                    else None
                ),
                "expert_assessment_id": (
                    expert_assessments[item.hypothesis_id].assessment_id
                    if item.hypothesis_id in expert_assessments
                    else ""
                ),
                "direct_combat_equipment": (
                    direct_combat_equipment
                ),
            }

        raw_equipment_portfolio = [
            capability_direction(item, position)
            for position, item in enumerate(final_hypotheses, start=1)
        ]

        async def close_s5_handoff_contract(
            position: int,
            card: Mapping[str, Any],
        ) -> tuple[int, dict[str, Any] | None, str]:
            """Let S5 close one finalist's falsifiable delivery contract.

            S3 has frozen naming in the candidate-authoring Codex turn. This
            turn only locks the remaining identity and decision contracts.
            """

            emit_swarm_event(
                "winning_s5_handoff_contract_started",
                actor="winning_swarm_independent_portfolio_reviewer",
                graph_id=graph.graph_id,
                card_position=position,
                hypothesis_id=str(card.get("hypothesis_id", "")),
                equipment_name=str(card.get("name", "")),
                status="running",
            )
            authored = dict(card)
            failure_reason = ""
            try:
                contract_text = await host._run_core_json(
                    "winning_swarm_independent_portfolio_reviewer",
                    "你是与候选生成和S6画像写作隔离的S5交接合同Agent。S3候选生成Codex会话已经在"
                    "确定创新原理和制胜关系后完成并冻结名称；本调用不得改名。先联合理解"
                    "name、source_hypothesis_title、equipment_form、project_function、mechanism_chain、"
                    "target_and_direct_effect与validation_plan，判断实际执行接敌并产生直接战果的唯一"
                    "主装备。frozen_name必须逐字复制assigned_candidate.name；不得清理标点、压缩、扩写、"
                    "同义替换或再次命名。复杂价值由concise_winning_summary承载。不得换装、增加候选"
                    "或撰写能力画像。随后形成四项简洁、可证伪、可交接的合同。"
                    "capability_classification按本装备在当前Query中的主要可验收战场结果确定主维度，"
                    "可使用毁伤、突防或其他更贴切的自然维度；辅维度最多两个，不按示例补齐。"
                    "同时输出equipment_semantic_assessment：必须基于完整候选、Query和作战因果"
                    "进行语义判断，不得依据标题关键词、型号格式或装备名词后缀分类。classification"
                    "使用direct_combat、unmanned_combat、upgrade、system_link、support_only或"
                    "non_equipment；并分别给出是否产生直接战斗效果、是否仅属支援、是否无人作战、"
                    "是否精确弹药、是否为具体装备对象以及是否与Query一致的JSON布尔值和简要理由。"
                    "indicator_portrait要从本装备独有机理推导少量关键测量轴，说明与哪类现有"
                    "任务链或同类装备在相同对抗条件下比较，以及出现什么结果时应判退或停止转段；"
                    "不得虚构精确数值，也不得用所有装备通用的射程、成本、精度清单代替机理推导。"
                    "query_relevance要自然写清该装备对应的任务对象、作战阶段、主要威胁压力和"
                    "直接军事战果，并说明其制胜关系为何不可由组合内其他候选替代。"
                    "concise_winning_summary是显示在冻结装备名称下方的一句精简制胜说明：通常控制"
                    "在25—70个中文字符，直接写最独特的战场特征或改变变量、适用场景/目标与直接战果，"
                    "使读者不展开画像也能理解为何制胜。不要复述装备名称，不写证据、验证、内部流程、"
                    "技术组件清单或泛化口号，不套统一句式。winning_summary_seed只供理解候选，可自然"
                    "重写或舍弃。该字段仅作展示和S6补充语境，不参与身份判定、质量硬门或S6改名。"
                    "other_finalists只用于避免合同语义重复，不得吸收其装备身份或机理。只输出JSON。",
                    {
                        "query": str(shared.get("topic", "")),
                        "assigned_candidate": dict(card),
                        "other_finalists": [
                            {
                                "name": str(item.get("name", "")),
                                "unique_operational_role": str(
                                    item.get("unique_operational_role", "")
                                ),
                                "non_substitutable_difference": str(
                                    item.get("non_substitutable_difference", "")
                                ),
                                "target_and_direct_effect": str(
                                    item.get("target_and_direct_effect", "")
                                ),
                            }
                            for other_position, item in enumerate(
                                raw_equipment_portfolio,
                                start=1,
                            )
                            if other_position != position
                        ],
                    },
                    {
                        "identity_status": "resolved|not_resolvable_from_candidate",
                        "naming_contract_passed": "boolean: frozen_name exactly copies assigned_candidate.name",
                        "frozen_name": "逐字复制assigned_candidate.name，不得再次命名",
                        "primary_equipment_identity": "唯一执行接敌并产生直接战果的主装备及平台/弹体边界",
                        "identity_resolution": "说明为何这是单一可立项装备；不得引用关键词或后缀规则",
                        "capability_classification": {
                            "primary_dimension": "主要能力维度",
                            "secondary_dimensions": ["最多两个辅助能力维度"],
                            "classification_basis": "主要战果、关键流程节点和制胜关系为何支持该分类",
                        },
                        "equipment_semantic_assessment": {
                            "classification": "direct_combat|unmanned_combat|upgrade|system_link|support_only|non_equipment",
                            "direct_combat_effect": "boolean",
                            "support_only": "boolean",
                            "unmanned_combat": "boolean",
                            "precision_munition": "boolean",
                            "concrete_equipment": "boolean",
                            "query_alignment_confirmed": "boolean",
                            "rationale": "基于完整军事语义的判断理由，不得引用关键词规则",
                        },
                        "indicator_portrait": (
                            "本装备机理专属的测量轴、同条件对照基线、可证伪判退或停止条件"
                        ),
                        "query_relevance": (
                            "任务对象、作战阶段、威胁压力、直接军事战果与不可替代制胜关系"
                        ),
                        "concise_winning_summary": (
                            "25-70个中文字符的一句制胜说明：独特战场特征/改变变量 + 场景或目标 + 直接战果"
                        ),
                    },
                    1200,
                    phase=f"winning_s5_handoff_contract_{position:02d}",
                )
                contract = _parse_json_object(contract_text)
                identity_status = (
                    str(contract.get("identity_status", "")).strip().lower()
                )
                frozen_name = _clean_capability_handoff_text(
                    contract.get("frozen_name", ""),
                    limit=None,
                )
                primary_identity = _clean_capability_handoff_text(
                    contract.get("primary_equipment_identity", ""),
                    limit=None,
                )
                naming_contract_passed = bool(
                    contract.get("naming_contract_passed", False)
                )
                if (
                    identity_status == "resolved"
                    and naming_contract_passed
                    and frozen_name == str(authored.get("name", ""))
                    and primary_identity
                ):
                    authored["primary_equipment_identity"] = primary_identity
                    authored["semantic_identity_resolution"] = (
                        _clean_capability_handoff_text(
                            contract.get("identity_resolution", ""),
                            limit=None,
                        )
                    )
                authored["indicator_portrait"] = _clean_capability_handoff_text(
                    contract.get("indicator_portrait", ""),
                    limit=None,
                )
                authored["query_relevance"] = _clean_capability_handoff_text(
                    contract.get("query_relevance", ""),
                    limit=None,
                )
                raw_classification = contract.get("capability_classification", {})
                if isinstance(raw_classification, Mapping):
                    primary_dimension = _clean_capability_handoff_text(
                        raw_classification.get("primary_dimension", ""),
                        limit=80,
                    )
                    secondary_dimensions = [
                        _clean_capability_handoff_text(item, limit=80)
                        for item in raw_classification.get("secondary_dimensions", [])
                        if str(item).strip()
                    ][:2]
                    classification_basis = _clean_capability_handoff_text(
                        raw_classification.get("classification_basis", ""),
                        limit=None,
                    )
                    if primary_dimension and classification_basis:
                        authored["capability_classification"] = {
                            "primary_dimension": primary_dimension,
                            "secondary_dimensions": secondary_dimensions,
                            "classification_basis": classification_basis,
                        }
                raw_assessment = contract.get("equipment_semantic_assessment", {})
                if isinstance(raw_assessment, Mapping):
                    assessment_classification = str(
                        raw_assessment.get("classification", "")
                    ).strip().lower()
                    boolean_fields = (
                        "direct_combat_effect",
                        "support_only",
                        "unmanned_combat",
                        "precision_munition",
                        "concrete_equipment",
                        "query_alignment_confirmed",
                    )
                    if assessment_classification and all(
                        isinstance(raw_assessment.get(field), bool)
                        for field in boolean_fields
                    ):
                        authored["equipment_classification"] = (
                            assessment_classification
                        )
                        authored["equipment_semantic_assessment"] = {
                            "classification": assessment_classification,
                            **{
                                field: raw_assessment[field]
                                for field in boolean_fields
                            },
                            "rationale": _clean_capability_handoff_text(
                                raw_assessment.get("rationale", ""),
                                limit=None,
                            ),
                        }
                concise_winning_summary = _clean_capability_handoff_text(
                    contract.get("concise_winning_summary", ""),
                    limit=180,
                )
                if concise_winning_summary:
                    authored["concise_winning_summary"] = concise_winning_summary
            except Exception as exc:
                failure_reason = f"{type(exc).__name__}: {exc}"

            if not all(
                str(authored.get(field, "")).strip()
                for field in (
                    "primary_equipment_identity",
                    "indicator_portrait",
                    "query_relevance",
                )
            ):
                # A transport or malformed-output failure must not discard
                # every otherwise valid finalist.  This bounded projection
                # is a last-resort S5 contract, never user-facing portrait
                # prose and never a source of new candidate semantics.
                authored = _prepare_pre_s6_card_contract(
                    authored,
                    query=str(shared.get("topic", "")),
                )
            # Only missing contract fields are diagnosed locally.  Whether a
            # name denotes one concrete weapon and whether the indicator/query
            # prose is semantically specific belong to the S5 Codex judgement.
            handoff_warnings: list[str] = []
            if not str(authored.get("primary_equipment_identity", "")).strip():
                handoff_warnings.append("主装备身份合同缺失")
            if not str(authored.get("indicator_portrait", "")).strip():
                handoff_warnings.append("指标合同未闭合")
            if not str(authored.get("query_relevance", "")).strip():
                handoff_warnings.append("Query关联合同未闭合")
            if not isinstance(authored.get("capability_classification"), Mapping):
                handoff_warnings.append("能力分类合同未闭合")
            authored_assessment = authored.get(
                "equipment_semantic_assessment", {}
            )
            if not isinstance(authored_assessment, Mapping) or not str(
                authored_assessment.get("classification", "")
            ).strip() or not all(
                isinstance(authored_assessment.get(field), bool)
                for field in (
                    "direct_combat_effect",
                    "support_only",
                    "unmanned_combat",
                    "precision_munition",
                    "concrete_equipment",
                    "query_alignment_confirmed",
                )
            ):
                handoff_warnings.append("装备语义合同未闭合")
            if failure_reason:
                handoff_warnings.insert(0, failure_reason)

            identity_contract = authored.get("portfolio_identity_contract", {})
            identity_contract = (
                dict(identity_contract)
                if isinstance(identity_contract, Mapping)
                else {}
            )
            identity_contract["pre_s6_quality_contract"] = {
                "indicator_portrait": authored.get("indicator_portrait", ""),
                "query_relevance": authored.get("query_relevance", ""),
                "capability_classification": authored.get(
                    "capability_classification", {}
                ),
                "equipment_semantic_assessment": authored.get(
                    "equipment_semantic_assessment", {}
                ),
                "owner": "S5_handoff_agent",
                "s6_mutation_allowed": False,
            }
            if str(authored.get("concise_winning_summary", "")).strip():
                identity_contract["pre_s6_supplemental_context"] = {
                    "concise_winning_summary": authored["concise_winning_summary"],
                    "purpose": "name_subtitle_and_s6_context_only",
                    "quality_gate_required": False,
                    "s6_mutation_allowed": False,
                }
            identity_contract["pre_s6_identity_contract"] = {
                "status": (
                    "resolved_by_s5_semantic_agent"
                    if str(authored.get("semantic_identity_resolution", "")).strip()
                    else "preserved_from_expert_selected_candidate"
                ),
                "name": str(authored.get("name", "")),
                "primary_equipment_identity": str(
                    authored.get("primary_equipment_identity", "")
                ),
                "method": "whole_candidate_military_semantics",
                "s6_mutation_allowed": False,
            }
            authored["portfolio_identity_contract"] = identity_contract
            if handoff_warnings:
                authored["pre_s6_handoff_warnings"] = handoff_warnings[:8]
            emit_swarm_event(
                "winning_s5_handoff_contract_completed",
                actor="winning_swarm_independent_portfolio_reviewer",
                graph_id=graph.graph_id,
                card_position=position,
                hypothesis_id=str(card.get("hypothesis_id", "")),
                equipment_name=str(card.get("name", "")),
                warnings=handoff_warnings[:8],
                status="limited" if handoff_warnings else "completed",
            )
            return position, authored, "；".join(handoff_warnings)

        handoff_results = await asyncio.gather(
            *(
                close_s5_handoff_contract(position, card)
                for position, card in enumerate(
                    raw_equipment_portfolio,
                    start=1,
                )
            ),
            return_exceptions=True,
        )
        equipment_portfolio: list[dict[str, Any]] = []
        limited_handoff_count = 0
        for position, outcome in enumerate(handoff_results, start=1):
            source_card = raw_equipment_portfolio[position - 1]
            if isinstance(outcome, BaseException):
                authored_card = _prepare_pre_s6_card_contract(
                    source_card,
                    query=str(shared.get("topic", "")),
                )
                authored_card["pre_s6_handoff_warnings"] = [
                    f"{type(outcome).__name__}: {outcome}"
                ]
                equipment_portfolio.append(authored_card)
                limited_handoff_count += 1
                emit_swarm_event(
                    "winning_s5_handoff_contract_completed",
                    actor="winning_swarm_independent_portfolio_reviewer",
                    graph_id=graph.graph_id,
                    card_position=position,
                    hypothesis_id=str(source_card.get("hypothesis_id", "")),
                    equipment_name=str(source_card.get("name", "")),
                    warnings=[f"{type(outcome).__name__}: {outcome}"[:400]],
                    status="limited",
                )
                continue
            _, authored_card, warning = outcome
            if authored_card is None:
                authored_card = _prepare_pre_s6_card_contract(
                    source_card,
                    query=str(shared.get("topic", "")),
                )
                warning = warning or "S5交接未返回结构化卡片，已保留冻结候选语义"
            if warning:
                limited_handoff_count += 1
            equipment_portfolio.append(authored_card)
        if not equipment_portfolio:
            equipment_portfolio = [
                _prepare_pre_s6_card_contract(
                    card,
                    query=str(shared.get("topic", "")),
                )
                for card in raw_equipment_portfolio
            ]
            limited_handoff_count = len(equipment_portfolio)
        emit_swarm_event(
            "winning_s5_handoff_contracts_completed",
            actor="winning_swarm_independent_portfolio_reviewer",
            graph_id=graph.graph_id,
            selected_count=len(equipment_portfolio),
            rejected_count=0,
            limited_count=limited_handoff_count,
            status="limited" if limited_handoff_count else "completed",
        )
        direct_combat_count = sum(
            bool(item.get("direct_combat_equipment")) for item in equipment_portfolio
        )
        direct_hypotheses = [
            item
            for item in final_hypotheses
            if swarm_controller.is_direct_combat_equipment(
                item,
                expert_assessments.get(item.hypothesis_id),
            )
        ]
        direct_equipment_family_counts = swarm_controller.equipment_family_counts(
            direct_hypotheses
        )
        distinct_direct_equipment_family_count = len(direct_equipment_family_counts)
        complete_portrait_count = sum(
            all(
                (
                    str(item.get("name", "")).strip(),
                    str(item.get("equipment_form", "")).strip(),
                    str(item.get("military_value", "")).strip(),
                    str(item.get("operational_mechanism", "")).strip(),
                    str(item.get("baseline_system", "")).strip(),
                    str(item.get("capability_gap", "")).strip(),
                    str(item.get("target_scenario", "")).strip(),
                    str(item.get("problem_statement", "")).strip(),
                    str(item.get("scientific_principle", "")).strip(),
                    item.get("enabling_technologies"),
                    str(item.get("operational_concept", "")).strip(),
                    item.get("operational_process"),
                    str(item.get("capability_outcome", "")).strip(),
                    str(item.get("winning_mechanism", "")).strip(),
                    item.get("system_interfaces"),
                    item.get("failure_boundaries"),
                    item.get("validation_plan"),
                )
            )
            for item in equipment_portfolio
        )
        capability_portrait_gate_passed = complete_portrait_count == len(
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
            and capability_portrait_gate_passed
            and equipment_diversity_passed
            and decision.quality_judge_passed
            and expert_judge_summary.get("status") == "completed"
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

        # Make every disposition explainable to the UI.  A candidate that
        # is not a standalone S6 card is not silently "eliminated": it
        # either failed a substantive quality/evidence test, or remains a
        # governed variant/constraint of a selected weapon family.
        selected_by_id = {item.hypothesis_id: item for item in final_hypotheses}
        candidate_lineage: list[dict[str, Any]] = []
        for item in ledger.hypotheses:
            row = to_plain(item)
            assessment = expert_assessments.get(item.hypothesis_id)
            if assessment is not None:
                row["expert_score"] = assessment.weighted_score
                row["selection_dimensions"] = {
                    "innovation": assessment.dimension_scores.get("innovation", 0.0),
                    "military_value": assessment.dimension_scores.get(
                        "military_value", 0.0
                    ),
                    "decisive_advantage": assessment.dimension_scores.get(
                        "decisive_advantage", 0.0
                    ),
                    "query_specificity": assessment.dimension_scores.get(
                        "query_specificity", 0.0
                    ),
                    "credibility": assessment.dimension_scores.get("credibility", 0.0),
                }
            if item.hypothesis_id in selected_by_id:
                is_pending = item.hypothesis_id in pending_verification_ids
                row.update(
                    selection_status=(
                        "selected_pending_verification" if is_pending else "selected"
                    ),
                    selection_reason_code=(
                        "frontier_pending_verification_backfill"
                        if is_pending
                        else "independent_evidence_closed_loop"
                    ),
                    selection_reason=(
                        "直接作战装备身份和Query因果成立；因专家认为对象证据、成熟度或对抗边界仍需核验，"
                        "按新质性与制胜价值补入S6，画像标记为待核验，不作为已列装事实。"
                        if is_pending
                        else "已通过Query因果、直接军事效果与独立性评审；可追溯对象证据有则保留，作为独立S6装备画像并行生成。"
                    ),
                    s6_eligible=True,
                    verification_status="pending" if is_pending else "assessed",
                    confidence_limited=is_pending,
                )
            elif assessment is not None and assessment.passed:
                row.update(
                    selection_status="not_selected_capacity",
                    selection_reason_code="s6_review_capacity",
                    selection_reason=(
                        "经独立Codex语义评审保留，但本轮超过S6审阅容量；"
                        "未按名称、装备家族或关键词机械合并，保留在候选账本供下一轮复核。"
                    ),
                    s6_eligible=False,
                )
            else:
                reasons = (
                    list(assessment.rejection_reasons)
                    if assessment is not None
                    else list(decision.dominance_reasons.get(item.hypothesis_id, []))
                )
                row.update(
                    # This lineage board is a research catalogue, not the
                    # delivery gate itself. Candidates that are unsuitable
                    # for a full S6 card remain inspectable reference
                    # weapons while the expert assessment retains the
                    # underlying quality/evidence findings for audit.
                    selection_status="reference",
                    selection_reason_code="reference_weapon_not_authored",
                    selection_reason=(
                        "本轮不进入S6详细画像；保留为参考武器，其对象证据、Query因果或"
                        "直接军事效果仍需补强。"
                        + ((" 参考依据：" + "；".join(reasons[:2])) if reasons else "")
                    ),
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
            "expert_judge": expert_judge_summary,
            "expert_assessments": [
                to_plain(item) for item in expert_assessments.values()
            ],
            "finalists": [to_plain(item) for item in final_hypotheses],
            "final_equipment_portfolio": equipment_portfolio,
            "portfolio_quality_gate": {
                "passed": portfolio_quality_gate_passed,
                "direction_count": len(equipment_portfolio),
                "direct_combat_equipment_count": direct_combat_count,
                "complete_capability_portrait_count": complete_portrait_count,
                "capability_portrait_gate_passed": capability_portrait_gate_passed,
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
                "selection_rule": "独立Codex按完整Query、因果与五轴语义作组合判断；本地字段、证据数量和家族数量只作诊断，不淘汰候选",
                "s6_card_capacity": int(
                    swarm_controller.policy.get("finalist_maximum", 12)
                ),
                "direct_combat_equipment_must_be_main_body": True,
                "expert_judge_required": bool(
                    swarm_controller.policy.get("expert_judge_required")
                ),
                "expert_judge_status": expert_judge_summary.get("status"),
                "expert_judge_passed": decision.quality_judge_passed,
                "expert_assessed_count": len(expert_assessments),
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
                "reserved_quality_judge_calls": int(
                    host._runtime_budgets.get("maximum_quality_judge_model_calls", 1)
                ),
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
        pre_s6_contract_issues: list[str] = []
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
        if isinstance(prior_directions, list):
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
                card_text = await host._run_core_json(
                    agent_id,
                    _parallel_s6_card_instruction(),
                    {
                        "query": step_input.get("query", ""),
                        "branch": step_input.get("branch", ""),
                        "parallel_card_id": f"s6-card-{position}",
                        "portfolio_position": position,
                        "portfolio_card_count": len(briefs),
                        "assigned_card": dict(brief),
                    },
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
            # Preserve the blind expert's selected weapon identity and
            # object-level evidence while allowing this S6 session to own
            # the scenario, operational process and capability portrait.
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
                "equipment_semantic_assessment",
                "concise_winning_summary",
                "expert_score",
                "expert_assessment_id",
                "direct_combat_equipment",
            ):
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
                s6_first_pass_contract = _s6_first_pass_quality_contract(
                    topic=str(shared["topic"]),
                    handoff=s6_handoff,
                )
                step_input = {
                    "query": shared["topic"],
                    "branch": primary_branch,
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
                and s6_parallel_authoring_only
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
    final_s6_issues = _s6_portrait_repair_issues(final_s6_all_issues)
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
            final_s6_issues = _s6_portrait_repair_issues(final_s6_all_issues)
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

    # Every deterministic S6 finding is advisory. S3-S5 own equipment
    # identity and military-semantic admission; S6 cannot delete, retry or
    # fail a frozen candidate because of local text-shape predicates.
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
            and bool(raw_portfolio_gate.get("capability_portrait_gate_passed"))
            and bool(raw_portfolio_gate.get("equipment_diversity_passed"))
            and bool(raw_portfolio_gate.get("expert_judge_passed"))
            and str(raw_portfolio_gate.get("expert_judge_status", "")) == "completed"
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
