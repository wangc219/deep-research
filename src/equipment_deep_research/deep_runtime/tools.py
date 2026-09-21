"""Equipment-research tools executed by the adapted nanobot runner.

Isolated proposers, the adversarial judge and parallel S6 column writers remain
orchestrator implementations. Follow-up turns prefer one model-led deepen
call that still does internal multi-dimensional, multi-angle divergence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from equipment_deep_research.deep_runtime.commands import help_visible_summary
from equipment_deep_research.deep_runtime.identity import IDENTITY_NAME
from equipment_deep_research.deep_runtime.provider_runtime import run_json_with_provider
from equipment_deep_research.deep_runtime.state import TurnState
from equipment_deep_research.domain.research_gaps import (
    sanitize_public_research_gaps,
    sanitize_public_research_prose,
)

ToolHandler = Callable[[TurnState], Awaitable[dict[str, Any]]]

_DIRECTION_FIELDS = (
    "name",
    "innovation_variant_name",
    "innovation_thesis",
    "winning_angle",
    "changed_assumption",
    "equipment_form",
    "innovation_equipment_form",
    "operational_mechanism",
    "decisive_target",
    "direct_damage_mechanism",
    "mission_kill_criterion",
    "military_value",
    "direct_military_effects",
    "related_scenario",
    "capability_gap",
    "novelty",
    "disruptive_difference",
    "implementation_concept",
    # Keep the research frontier's falsifiable branch metadata across
    # follow-up turns while dropping provider-only fields from the model
    # handoff.
    "adversary_response",
    "feasibility_anchor",
    "rejection_risk",
    "branch_id",
    "branch_type",
    "novelty_delta",
    "counterfactual_test",
    "research_probe",
)

_RESEARCH_DIMENSIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("winning_angle", ("winning_angle",)),
    ("changed_assumption", ("changed_assumption",)),
    ("equipment_form", ("equipment_form", "innovation_equipment_form")),
    ("operational_mechanism", ("operational_mechanism",)),
    ("decisive_target", ("decisive_target",)),
    ("direct_damage_mechanism", ("direct_damage_mechanism",)),
    ("mission_kill_criterion", ("mission_kill_criterion",)),
    ("direct_military_effects", ("direct_military_effects", "military_value")),
    ("disruptive_difference", ("disruptive_difference", "novelty")),
)

_GAP_QUESTIONS = {
    "winning_angle": "该方向通过什么新的时间、空间或成本关系夺取主动？",
    "changed_assumption": "它改写了哪条长期默认成立的作战假设？",
    "equipment_form": "承担该机理的具体单装备构型是什么？",
    "operational_mechanism": "从进入到作用的因果链如何闭合？",
    "decisive_target": "它优先作用于哪个明确目标或脆弱环节？",
    "direct_damage_mechanism": "最终如何兑现为直接物理作用或等价任务效果？",
    "mission_kill_criterion": "什么可观察结果表明目标退出当前任务周期？",
    "direct_military_effects": "该构型最终带来什么直接军事效果？",
    "disruptive_difference": "相对现有装备，它的构型或作用关系发生了什么跃迁？",
}

_RESEARCH_DIMENSION_LABELS = {
    "winning_angle": "制胜切入点",
    "changed_assumption": "被改写假设",
    "equipment_form": "装备构型",
    "operational_mechanism": "作用机理",
    "decisive_target": "关键打击对象",
    "direct_damage_mechanism": "直接毁伤机理",
    "mission_kill_criterion": "任务失能判据",
    "direct_military_effects": "直接军事效果",
    "disruptive_difference": "颠覆性差异",
}


def _text(value: Any, limit: int = 900) -> str:
    return " ".join(str(value or "").split()).strip()[: max(0, int(limit))]


def _memory(state: TurnState) -> dict[str, Any]:
    memory = state.inbound.working_memory
    return dict(memory) if isinstance(memory, Mapping) else {}


def _directions_from_memory(memory: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw = memory.get("candidate_directions")
    if not isinstance(raw, list):
        return rows
    for item in raw[:3]:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"), 240)
        if not name:
            continue
        direction = {
            key: (
                bool(item.get(key))
                if key == "stable"
                else _text(item.get(key), 900)
            )
            for key in (*_DIRECTION_FIELDS, "stable")
            if item.get(key) not in (None, "", [], {})
        }
        direction["name"] = name
        direction["innovation_variant_name"] = _text(
            item.get("innovation_variant_name") or name, 240
        )
        if not direction.get("innovation_equipment_form") and direction.get(
            "equipment_form"
        ):
            direction["innovation_equipment_form"] = direction["equipment_form"]
        if not direction.get("direct_military_effects") and direction.get(
            "military_value"
        ):
            direction["direct_military_effects"] = direction["military_value"]
        if not direction.get("disruptive_difference") and direction.get("novelty"):
            direction["disruptive_difference"] = direction["novelty"]
        direction["stable"] = bool(item.get("stable", False))
        rows.append(direction)
    return rows


def _summaries_from_memory(memory: Mapping[str, Any]) -> list[str]:
    raw = memory.get("latest_summary")
    if isinstance(raw, list):
        return sanitize_public_research_gaps(raw[:4], limit=4, item_limit=600)
    rationale = sanitize_public_research_prose(memory.get("selection_rationale"), limit=900)
    return [rationale] if rationale else []


def _questions_from_memory(memory: Mapping[str, Any]) -> list[str]:
    raw = memory.get("open_questions")
    if not isinstance(raw, list):
        return []
    return sanitize_public_research_gaps(raw[:4], limit=4, item_limit=400)


def _adjudication_from_memory(memory: Mapping[str, Any]) -> dict[str, Any]:
    decisions = memory.get("decisions")
    decisions = decisions if isinstance(decisions, list) else []
    reviews = []
    order = []
    for item in decisions[:8]:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("candidate") or item.get("candidate_name"), 240)
        if not name:
            continue
        verdict = _text(item.get("verdict"), 32).lower() or "keep"
        reviews.append(
            {
                "candidate_name": name,
                "verdict": verdict,
                "decisive_issue": _text(item.get("reason"), 500),
            }
        )
        if verdict != "reject":
            order.append(name)
    if not order:
        order = [
            _text(item.get("name"), 240)
            for item in _directions_from_memory(memory)
            if item.get("stable")
        ][:3]
    return {
        "review_summary": _text(
            memory.get("selection_rationale")
            or "沿用上一轮对抗裁决，本轮不再重开议事。",
            1200,
        ),
        "mission_focus": _text(memory.get("current_objective"), 800),
        "candidate_reviews": reviews,
        "selection_order": order[:3],
        "adjudication_complete": bool(order),
    }


def _research_action(state: TurnState) -> str:
    configured = _text(state.payload.get("deep_research_mode"), 32).lower()
    if configured in {"research_council", "diverge", "challenge", "synthesize"}:
        return configured
    if state.current_action:
        return state.current_action
    for name in reversed(state.plan):
        if name in {
            "research_council",
            "diverge",
            "deepen",
            "challenge",
            "synthesize",
            "author_s6",
            "inspect_memory",
            "help",
        }:
            return name
    return "deepen"


_RESEARCH_DIRECTION_ACTIONS = frozenset(
    {"research_council", "diverge", "deepen", "challenge", "synthesize"}
)


def _latest_observed_directions(state: TurnState) -> list[dict[str, Any]]:
    """Return directions from the most recent completed research action."""

    for observation in reversed(state.observations):
        if not isinstance(observation, Mapping):
            continue
        if observation.get("kind") != "tool_result":
            continue
        if _text(observation.get("tool"), 40) not in _RESEARCH_DIRECTION_ACTIONS:
            continue
        result = observation.get("result")
        if not isinstance(result, Mapping):
            continue
        raw = result.get("concept_directions")
        if isinstance(raw, list):
            directions = [dict(item) for item in raw if isinstance(item, Mapping)]
            if directions:
                return directions

    # Some callers restore only the compact completion trace and result map.
    # Preserve the same newest-first semantics when observations are absent.
    for action in reversed(state.completed_tools):
        if action not in _RESEARCH_DIRECTION_ACTIONS:
            continue
        result = state.results.get(action)
        if not isinstance(result, Mapping):
            continue
        raw = result.get("concept_directions")
        if isinstance(raw, list):
            directions = [dict(item) for item in raw if isinstance(item, Mapping)]
            if directions:
                return directions
    return []


def _compact_direction_handoff(
    directions: list[Mapping[str, Any]] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project observed directions before sending them into a new model turn.

    Tool results can contain evidence, provider diagnostics, or UI metadata
    alongside the decision.  Follow-up reasoning only needs the bounded
    candidate projection, so keep the same shape as restored working memory
    and prevent those incidental fields from growing the next context window.
    """

    return _directions_from_memory({"candidate_directions": list(directions)})


def _research_topology(action: str) -> str:
    return {
        "research_council": "parallel_isolated_council",
        "diverge": "integrated_open_divergence",
        "deepen": "memory_led_multilens_deepen",
        "challenge": "adversarial_assumption_audit",
        "synthesize": "comparative_frontier_synthesis",
        "author_s6": "confirmed_s6_authoring",
        "inspect_memory": "memory_restore",
        "help": "command_help",
    }.get(action, "adaptive_research")


def _add_research_signals(
    result: dict[str, Any], state: TurnState, *, action: str | None = None
) -> dict[str, Any]:
    """Attach non-blocking research assessment while keeping legacy fields.

    The old ``quality_gate`` object remains for API compatibility. During
    research it reports readiness only; incomplete dimensions become explicit
    gaps and never discard a direction or suppress a visible answer.
    """

    resolved_action = action or _research_action(state)
    supplied_assessment = result.get("research_assessment")
    supplied_assessment = (
        supplied_assessment if isinstance(supplied_assessment, Mapping) else {}
    )
    raw_directions = result.get("concept_directions")
    directions = raw_directions if isinstance(raw_directions, list) else []
    reviews: list[dict[str, Any]] = []
    existing_gaps = [
        _text(item, 500)
        for item in (
            result.get("research_gaps")
            if isinstance(result.get("research_gaps"), list)
            else []
        )[:8]
        if _text(item, 500)
    ]
    gaps: list[str] = list(existing_gaps)
    coverage = {name: 0 for name, _fields in _RESEARCH_DIMENSIONS}
    ready_count = 0
    normalized: list[dict[str, Any]] = []
    for raw in directions[:3]:
        if not isinstance(raw, Mapping):
            continue
        direction = dict(raw)
        name = _text(
            direction.get("name") or direction.get("innovation_variant_name"),
            240,
        )
        if not name:
            continue
        direction["name"] = name
        direction["innovation_variant_name"] = name
        missing: list[str] = []
        for dimension, fields in _RESEARCH_DIMENSIONS:
            if any(_text(direction.get(field), 8) for field in fields):
                coverage[dimension] += 1
            else:
                missing.append(dimension)
        core_ready = _direction_research_ready(direction)
        if resolved_action != "author_s6":
            direction["stable"] = core_ready
        if core_ready:
            ready_count += 1
        completeness = round(
            (len(_RESEARCH_DIMENSIONS) - len(missing))
            / len(_RESEARCH_DIMENSIONS),
            3,
        )
        missing_labels = [
            _RESEARCH_DIMENSION_LABELS.get(dimension, dimension)
            for dimension in missing
        ]
        reviews.append(
            {
                "candidate_name": name,
                "research_ready": core_ready,
                "completeness": completeness,
                "missing_dimensions": missing_labels,
                "missing_dimension_keys": missing,
            }
        )
        if missing:
            gaps.append(
                f"{name}待补研究维度：{'、'.join(missing_labels)}。"
                f"建议追问：{_GAP_QUESTIONS[missing[0]]}"
            )
        normalized.append(direction)
    result["concept_directions"] = normalized

    open_questions = result.get("open_questions")
    if isinstance(open_questions, list):
        for question in open_questions[:4]:
            content = _text(question, 500)
            if content and content not in gaps:
                gaps.append(content)

    legacy_gate = result.get("quality_gate")
    legacy_gate = legacy_gate if isinstance(legacy_gate, Mapping) else {}
    if resolved_action == "author_s6":
        missing_s6 = [
            _text(item, 120)
            for item in (
                legacy_gate.get("missing_s6_columns")
                if isinstance(legacy_gate.get("missing_s6_columns"), list)
                else []
            )
            if _text(item, 120)
        ]
        if missing_s6:
            gaps.append(f"S6 待补或待加强栏目：{'、'.join(missing_s6)}")
        for item in (
            legacy_gate.get("block_reasons")
            if isinstance(legacy_gate.get("block_reasons"), list)
            else []
        )[:4]:
            advisory = _text(item, 500)
            if advisory and advisory not in gaps:
                gaps.append(f"S6 advisory：{advisory}")

    conductor = state.conductor if isinstance(state.conductor, Mapping) else {}
    orchestration = result.get("orchestration")
    orchestration = orchestration if isinstance(orchestration, Mapping) else {}
    lenses: list[str] = []
    for key in ("divergence_axes", "internal_dimensions"):
        raw_lenses = orchestration.get(key)
        raw_lenses = raw_lenses if isinstance(raw_lenses, list) else []
        for value in raw_lenses:
            lens = _text(value, 120)
            if lens and lens not in lenses:
                lenses.append(lens)
            if len(lenses) >= 8:
                break
        if len(lenses) >= 8:
            break
    rationale = _text(conductor.get("rationale"), 600)
    if not rationale:
        rationale = {
            "research_council": "用隔离并行提案扩大解空间，再做交叉挑战与综合。",
            "diverge": "在一次集成推理中重新展开正交假设，避免固定席位成为流程负担。",
            "deepen": "沿工作记忆中的候选做多透镜深化，只推进本轮真正新增的问题。",
            "challenge": "集中寻找反例、最低成本反制与失效边界，再修订候选。",
            "synthesize": "比较现有假设与冲突，形成可继续研究的前沿。",
            "author_s6": "用户已明确确认，将研究方向固定为 S6 五栏能力卡。",
            "inspect_memory": "只读恢复当前分支研究记忆。",
            "help": "仅展示可用研究命令。",
        }.get(resolved_action, "按本轮问题选择最小充分研究动作。")
    result["research_strategy"] = {
        "mode": resolved_action,
        "topology": _research_topology(resolved_action),
        "actions": list(state.plan)[:4],
        "rationale": rationale,
        "lenses": lenses,
        "fixed_pipeline": False,
        "s6_requires_confirmation": True,
    }
    average = (
        round(
            sum(float(item["completeness"]) for item in reviews) / len(reviews),
            3,
        )
        if reviews
        else 0.0
    )
    research_actions = {"research_council", "diverge", "deepen", "challenge", "synthesize"}
    supplied_recommendation = _text(
        supplied_assessment.get("recommended_action"), 40
    ).lower()
    supplied_scope = _text(
        supplied_assessment.get("recommendation_scope"), 24
    ).lower()
    if supplied_recommendation in research_actions:
        recommended_action = supplied_recommendation
        # Unscoped provider output is advisory. Only an explicit same-turn
        # assessment may extend the bounded tool loop automatically.
        recommendation_scope = (
            supplied_scope
            if supplied_scope in {"same_turn", "next_turn"}
            else "next_turn"
        )
    else:
        recommended_action = ""
        if normalized:
            if resolved_action == "diverge" and len(normalized) >= 2:
                recommended_action = "challenge"
            elif resolved_action == "challenge":
                recommended_action = "synthesize"
        recommendation_scope = "next_turn" if recommended_action else ""
    result["research_assessment"] = {
        "non_blocking": True,
        "research_complete": bool(normalized)
        or resolved_action in {"help", "inspect_memory"},
        "completion_semantics": (
            "本轮已形成可继续研究的候选或完成只读动作；"
            "research_complete 不表示所有研究缺口已经关闭。"
        ),
        "candidate_count": len(normalized),
        "research_ready_count": ready_count,
        "average_completeness": average,
        "dimension_coverage": coverage,
        "candidate_reviews": reviews,
        "diversity": {
            "independent_directions": len(normalized),
            "assessment": (
                "broad" if len(normalized) >= 3 else "focused" if normalized else "empty"
            ),
        },
        "unresolved_gap_count": len(gaps),
        "recommended_action": recommended_action,
        "recommendation_scope": recommendation_scope,
        "gaps": gaps[:8],
        "research_gaps": gaps[:8],
        "advisories": gaps[:8],
    }
    result["research_gaps"] = gaps[:8]

    if resolved_action != "author_s6":
        gate = result.get("quality_gate")
        gate = dict(gate) if isinstance(gate, Mapping) else {}
        gate.update(
            {
                "publishable": False,
                "direction_ready": ready_count > 0,
                "passed_directions": ready_count,
                "candidate_reviews": reviews,
                "missing_s6_columns": [],
                "block_reasons": [],
                "non_blocking": True,
            }
        )
        result["quality_gate"] = gate
        if resolved_action in {
            "research_council",
            "diverge",
            "deepen",
            "challenge",
            "synthesize",
        }:
            result["finalization_status"] = (
                "awaiting_user_confirmation" if ready_count else "analysis_only"
            )
    return result


def _annotate_runtime(result: dict[str, Any], state: TurnState) -> dict[str, Any]:
    _add_research_signals(result, state)
    result["runtime"] = {
        "engine": "equipment_deep_runtime_v2",
        "identity": IDENTITY_NAME,
        "tools": list(state.completed_tools),
        "active_skill_ids": [
            str(item.get("skill_id", ""))
            for item in state.active_skills
            if str(item.get("skill_id", "")).strip()
        ],
        "plugin_ids": list(state.capabilities.get("plugin_ids", [])),
        "mcp_servers": list(state.capabilities.get("mcp_servers", [])),
        "command": state.inbound.command or "",
        "plan": list(state.plan),
        "conductor": dict(state.conductor),
        "research_mode": _research_action(state),
        "tool_registry": (
            state.tool_registry.public_payload()
            if state.tool_registry is not None
            else {}
        ),
    }
    return result


def _empty_gate(*, direction_ready: bool, require_s6: bool) -> dict[str, Any]:
    return {
        "publishable": False,
        "direction_ready": direction_ready,
        "passed_directions": int(direction_ready),
        "candidate_reviews": [],
        "missing_s6_columns": [] if not require_s6 else ["overview"],
        "block_reasons": [] if direction_ready else ["未形成可审核的候选方向"],
    }


def _direction_research_ready(direction: Mapping[str, Any]) -> bool:
    """Check coherence for continued research without requiring nine fields."""

    return bool(
        _text(
            direction.get("equipment_form")
            or direction.get("innovation_equipment_form"),
            8,
        )
        and _text(direction.get("operational_mechanism"), 8)
        and any(
            _text(direction.get(field), 8)
            for field in (
                "winning_angle",
                "changed_assumption",
                "decisive_target",
                "direct_damage_mechanism",
                "mission_kill_criterion",
                "direct_military_effects",
                "disruptive_difference",
            )
        )
    )


async def tool_help(state: TurnState) -> dict[str, Any]:
    from equipment_deep_research.agents.workflows.orchestrator import (
        _emit_deep_dialogue_live_progress,
    )

    summary = help_visible_summary()
    _emit_deep_dialogue_live_progress(
        state.host,
        {
            "event_type": "deep_agent_completed",
            "stage": "context",
            "status": "completed",
            "progress": 0.2,
            "kind": "answer",
            "round": "command",
            "role": "命令路由",
            "agent_id": "deep_dialogue_runtime",
            "text": summary[0],
            "summary_text": "已列出定向深研命令，本轮不启动议事。",
        },
    )
    memory = _memory(state)
    directions = _directions_from_memory(memory)
    status = _text(memory.get("finalization_status"), 48) or "analysis_only"
    return _annotate_runtime(
        {
            "visible_summary": summary,
            "selection_rationale": "斜杠命令 /help 已处理，未调用议事工具。",
            "concept_directions": directions,
            "capability_card_draft": {},
            "adjudication": _adjudication_from_memory(memory),
            "open_questions": _questions_from_memory(memory)
            or ["继续追问以深化已有方向，或使用 /card 成卡。"],
            "finalization_status": status,
            "quality_gate": _empty_gate(
                direction_ready=any(item.get("stable") for item in directions),
                require_s6=False,
            ),
            "agent_dialogue": [
                {
                    "agent_id": "deep_dialogue_runtime",
                    "role": "命令路由",
                    "axis": "slash_command",
                    "round": "command",
                    "summary": summary[0],
                    "proposal_names": [item.get("name", "") for item in directions[:3]],
                }
            ],
            "orchestration": {
                "pattern": "slash_command",
                "rounds": 1,
                "phases": ["help"],
                "divergence_axes": [],
                "internal_dimensions": [],
                "requested_agents": 0,
                "completed_divergence_agents": 0,
                "degraded": False,
                "quality_gate_passed": False,
                "finalization_status": status,
            },
        },
        state,
    )


async def tool_inspect_memory(state: TurnState) -> dict[str, Any]:
    from equipment_deep_research.agents.workflows.orchestrator import (
        _emit_deep_dialogue_live_progress,
        _govern_deep_dialogue_final,
        _seed_identity_keys,
    )

    memory = _memory(state)
    directions = _directions_from_memory(memory)
    summaries = _summaries_from_memory(memory) or [
        "当前分支尚无已压缩的决策记忆；没有候选时才会启动隔离三席。"
    ]
    # An optional file-backed workspace contributes long-term Dream memory to
    # the read-only inspection turn.  It is deliberately bounded and labelled
    # as archival context so it cannot silently replace the branch checkpoint.
    external_workspace = state.workspace
    if external_workspace is not None:
        try:
            parent = state.payload.get("deep_parent_context")
            parent = parent if isinstance(parent, Mapping) else {}
            session_id = str(state.payload.get("session_id") or parent.get("session_id") or "")
            branch_id = str(state.payload.get("branch_id") or parent.get("branch_id") or "main")
            durable = (
                external_workspace.memory.read_context(session_id=session_id, branch_id=branch_id)
                if session_id else external_workspace.memory.read_memory()
            )
        except Exception:
            durable = ""
        if durable:
            excerpt = " ".join(durable.split())[:800]
            summaries = [*summaries, f"长期 Dream 记忆：{excerpt}"][:4]
    names = [item["name"] for item in directions if item.get("name")]
    _emit_deep_dialogue_live_progress(
        state.host,
        {
            "event_type": "deep_agent_completed",
            "stage": "context",
            "status": "completed",
            "progress": 0.22,
            "kind": "answer",
            "round": "memory",
            "role": "决策记忆",
            "agent_id": "deep_dialogue_memory",
            "deliverable_refs": names,
            "proposal_names": names,
            "text": "；".join(summaries)[:1200],
            "summary_text": "已读取当前分支工作记忆，未重开议事。",
        },
    )
    final = _govern_deep_dialogue_final(
        {
            "visible_summary": summaries,
            "selection_rationale": _text(
                memory.get("selection_rationale") or "；".join(summaries), 900
            ),
            "concept_directions": directions,
            "capability_card_draft": {},
            "open_questions": _questions_from_memory(memory),
            "adjudication": _adjudication_from_memory(memory),
        },
        seed_keys=_seed_identity_keys(state.payload),
        require_s6=False,
    )
    final["adjudication"] = _adjudication_from_memory(memory)
    final["agent_dialogue"] = [
        {
            "agent_id": "deep_dialogue_memory",
            "role": "决策记忆",
            "axis": "工作记忆检查点",
            "round": "memory",
            "summary": "；".join(summaries)[:1200],
            "proposal_names": names,
        }
    ]
    final["orchestration"] = {
        "pattern": "memory_inspect",
        "rounds": 1,
        "phases": ["inspect_memory"],
        "divergence_axes": [],
        "internal_dimensions": [],
        "requested_agents": 1,
        "completed_divergence_agents": 0,
        "degraded": False,
        "quality_gate_passed": False,
        "finalization_status": final.get("finalization_status", "analysis_only"),
    }
    if not final.get("open_questions"):
        final["open_questions"] = [
            "哪个方向最值得写成五栏能力卡？",
            "对手最低成本反制后，该构型靠什么继续制衡？",
            "使用 /card 沿当前方向成卡，或继续追问以深化已有方向。",
        ]
    return _annotate_runtime(final, state)


async def tool_author_s6(state: TurnState) -> dict[str, Any]:
    from equipment_deep_research.agents.workflows.orchestrator import (
        _compact_deep_dialogue_seed_payload,
        _consume_deep_dialogue_steers,
        _emit_deep_dialogue_live_progress,
        _govern_deep_dialogue_final,
        _clean_technology_column_text,
        _seed_identity_keys,
        _write_deep_dialogue_s6_columns,
    )

    if not (
        state.inbound.card_intent and state.inbound.has_closed_stable_direction
    ):
        return _annotate_runtime(
            {
                "visible_summary": ["当前方向尚未闭合，不能进入五栏成卡。"],
                "selection_rationale": "S6 成卡需要用户明确确认，并且工作记忆中已有闭合的稳定方向。",
                "concept_directions": _directions_from_memory(_memory(state)),
                "capability_card_draft": {},
                "open_questions": ["请先继续深化候选方向，闭合作用机理、直接毁伤与任务失能判据。"],
                "finalization_status": "analysis_only",
                "quality_gate": _empty_gate(direction_ready=False, require_s6=True),
                "orchestration": {
                    "pattern": "s6_authoring_blocked",
                    "rounds": 0,
                    "phases": [],
                    "requested_agents": 0,
                    "completed_divergence_agents": 0,
                    "degraded": False,
                    "quality_gate_passed": False,
                    "finalization_status": "analysis_only",
                },
            },
            state,
        )

    inspected = state.results.get("inspect_memory")
    inspected = inspected if isinstance(inspected, Mapping) else {}
    memory = _memory(state)
    directions = _directions_from_memory(memory) or list(
        inspected.get("concept_directions") or []
    )
    summaries = _summaries_from_memory(memory) or list(
        inspected.get("visible_summary") or []
    )
    rationale = _text(
        memory.get("selection_rationale")
        or inspected.get("selection_rationale")
        or "基于已收敛方向成卡，不再扩展新的候选方向。",
        900,
    )
    spine = {
        "visible_summary": summaries or ["沿已收敛方向写入五栏能力画像。"],
        "selection_rationale": rationale,
        "concept_directions": directions,
        "adjudication": inspected.get("adjudication")
        or _adjudication_from_memory(memory),
    }
    seed_keys = _seed_identity_keys(state.payload)
    preview = _govern_deep_dialogue_final(
        dict(spine), seed_keys=seed_keys, require_s6=False
    )
    if not preview["quality_gate"]["direction_ready"] and any(
        _direction_research_ready(item)
        for item in directions
        if isinstance(item, Mapping)
    ):
        # The former nine-field closure check is advisory during research.
        # Explicit /card confirmation may fix a coherent partial direction;
        # omitted dimensions remain visible in research_gaps.
        preview["concept_directions"] = [
            {**dict(item), "stable": True}
            for item in directions[:3]
            if isinstance(item, Mapping)
        ]
        preview["finalization_status"] = "awaiting_user_confirmation"
        preview["quality_gate"] = {
            "publishable": False,
            "direction_ready": True,
            "passed_directions": len(preview["concept_directions"]),
            "candidate_reviews": [],
            "missing_s6_columns": [],
            "block_reasons": [],
            "non_blocking": True,
        }
    if not preview["quality_gate"]["direction_ready"]:
        preview["visible_summary"] = [
            "当前稳定方向未通过成卡前的结构闭合检查，本轮没有重新发散。"
        ]
        preview["capability_card_draft"] = {}
        preview["finalization_status"] = "analysis_only"
        preview["open_questions"] = [
            "请先补齐装备构型、作用机理、直接毁伤和任务失能判据，再次确认成卡。"
        ]
        preview["orchestration"] = {
            "pattern": "s6_authoring_blocked",
            "rounds": 1,
            "phases": ["inspect_memory"],
            "requested_agents": 0,
            "completed_divergence_agents": 0,
            "degraded": False,
            "quality_gate_passed": False,
            "finalization_status": "analysis_only",
        }
        return _annotate_runtime(preview, state)

    _consume_deep_dialogue_steers(state.host, state.payload, "s6_authoring")
    names = [
        _text(item.get("name"), 120)
        for item in preview.get("concept_directions", [])[:3]
        if isinstance(item, Mapping) and _text(item.get("name"), 120)
    ]
    _emit_deep_dialogue_live_progress(
        state.host,
        {
            "event_type": "deep_agent_started",
            "stage": "s6_authoring",
            "status": "running",
            "progress": 0.58,
            "kind": "summary",
            "round": "authoring",
            "role": "能力画像综合总编",
            "axis": "S6 五栏成卡",
            "agent_id": "deep_thinking_dialogue",
            "deliverable_refs": names,
            "proposal_names": names,
            "summary_text": "已锁定工作记忆中的稳定方向，正在并行生成五栏能力画像；各栏完成后即时回传。",
        },
    )
    synthesis_payload = _compact_deep_dialogue_seed_payload(
        state.payload, include_naming=True
    )
    synthesis_payload["deep_skill_prompt"] = state.skill_prompt
    draft, failures = await _write_deep_dialogue_s6_columns(
        state.host,
        synthesis_payload=synthesis_payload,
        synthesis_spine=preview,
        provider_runtime=state.provider_runtime,
        checkpoint_callback=state.payload.get("checkpoint_callback"),
        card_authoring_id=str(
            state.payload.get("card_authoring_id")
            or state.payload.get("job_id")
            or ""
        ),
        resume_checkpoint=(
            state.payload.get("s6_column_checkpoint")
            if isinstance(state.payload.get("s6_column_checkpoint"), Mapping)
            else None
        ),
    )
    # Keep the atomic five-field card invariant at the tool boundary as well
    # as inside the parallel writer.  Older adapters can still return a
    # four-field projection after a failed technology call; preserve that
    # missing field as an honest, resumable research boundary.  Never inject
    # a generic paragraph here: only an actual model response may complete the
    # technology column.
    technology_text = _text(draft.get("technology_implementation"), 6000)
    if technology_text:
        draft = dict(draft)
        draft["technology_implementation"] = _clean_technology_column_text(
            technology_text, preview
        )
    if not _text(draft.get("technology_implementation"), 8):
        draft = dict(draft)
        draft.pop("technology_implementation", None)
        technology_failure_present = any(
            "technology_implementation" in str(item)
            or "装备与技术实现" in str(item)
            for item in failures
        )
        if not technology_failure_present:
            failures = [*failures, "第2栏“装备与技术实现”未完成"]
        # The parallel writer already emits this state for its own failures.
        # Emit it here only for legacy adapters that returned a missing field
        # without a failure marker, avoiding duplicate status bubbles.
        if not technology_failure_present:
            _emit_deep_dialogue_live_progress(
                state.host,
                {
                    "event_type": "deep_agent_progress",
                    "stage": "s6_authoring",
                    "status": "partial",
                    "progress": 0.86,
                    "kind": "summary",
                    "round": "authoring",
                    "role": "装备与技术实现栏主笔",
                    "agent_id": "deep_thinking_dialogue",
                    "column_key": "technology_implementation",
                    "technology_research_status": "pending_retry",
                    "text": "第 2 栏模型恢复尚未返回正文，已保留其他栏目；本轮不伪造完成状态。",
                    "summary_text": "第 2 栏待模型恢复后补写，五栏能力画像暂不发布。",
                },
            )
    preview["capability_card_draft"] = draft
    if failures:
        preview["finalization_status"] = "analysis_only"
        preview["open_questions"] = [*failures, *_questions_from_memory(memory)][:5]
    final = _govern_deep_dialogue_final(
        preview, seed_keys=seed_keys, require_s6=True
    )
    # S6 publication is now a user-confirmed transition, not an evidence or
    # prose-quality gate. Keep the former gate findings as research advisories,
    # while requiring only that all five structural columns were returned.
    governed_gate = final.get("quality_gate")
    governed_gate = dict(governed_gate) if isinstance(governed_gate, Mapping) else {}
    s6_advisories = [
        _text(item, 500)
        for item in (
            governed_gate.get("block_reasons")
            if isinstance(governed_gate.get("block_reasons"), list)
            else []
        )[:6]
        if _text(item, 500)
    ]
    required_columns = (
        "overview",
        "technology_implementation",
        "operational_process",
        "capability_effects",
        "winning_logic",
    )
    missing_columns = [
        name for name in required_columns if not _text(draft.get(name), 8)
    ]
    # Explicit user confirmation fixes the current direction as a draft only
    # after the shared five-column task has returned every required field.
    structurally_complete = bool(final.get("concept_directions")) and bool(
        draft
    ) and not missing_columns and all(
        _text(draft.get(name), 8) for name in required_columns
    )
    if structurally_complete:
        final["finalization_status"] = "candidate_ready"
        governed_gate.update(
            {
                "publishable": True,
                "direction_ready": True,
                "missing_s6_columns": missing_columns,
                "block_reasons": [],
                "non_blocking": True,
            }
        )
    else:
        final["finalization_status"] = "analysis_only"
        governed_gate.update(
            {
                "publishable": False,
                "missing_s6_columns": missing_columns,
                "block_reasons": [],
                "non_blocking": True,
            }
        )
    final["quality_gate"] = governed_gate
    if s6_advisories or missing_columns:
        final["research_gaps"] = [
            *(
                [f"S6 待补栏目：{'、'.join(missing_columns)}"]
                if missing_columns
                else []
            ),
            *[f"S6 advisory：{item}" for item in s6_advisories],
        ][:8]
    final["adjudication"] = spine["adjudication"]
    final["agent_dialogue"] = [
        {
            "agent_id": "deep_dialogue_memory",
            "role": "决策记忆",
            "axis": "工作记忆检查点",
            "round": "memory",
            "summary": "沿用已收敛方向成卡，跳过三席发散与对抗裁决。",
            "proposal_names": names,
        },
        {
            "agent_id": "deep_thinking_dialogue",
            "role": "能力画像综合总编",
            "axis": "S6 五栏成卡",
            "round": "synthesis",
            "summary": _text(
                final.get("selection_rationale")
                or (
                    "已完成候选收敛、命名和 S6 五栏成卡。"
                    if final["quality_gate"]["publishable"]
                    else "已按记忆方向写栏；因质量门未通过，本轮仅保留分析。"
                ),
                1200,
            ),
            "proposal_names": names,
        },
    ]
    final["orchestration"] = {
        "pattern": "memory_restore_s6_authoring",
        "rounds": 2,
        "phases": ["inspect_memory", "s6_synthesis"],
        "divergence_axes": [],
        "internal_dimensions": [],
        "requested_agents": 1,
        "completed_divergence_agents": 0,
        "degraded": bool(failures),
        "quality_gate_passed": bool(final["quality_gate"]["publishable"]),
        "finalization_status": final["finalization_status"],
    }
    if not _text(" ".join(str(item) for item in (final.get("open_questions") or []))):
        gate = final.get("quality_gate", {})
        reasons = list(gate.get("block_reasons") or []) if isinstance(gate, Mapping) else []
        final["open_questions"] = (
            [f"请补全后重试：{reasons[0]}"]
            if reasons
            else [
                "五栏成卡后，哪一栏还需要针对反制边界继续追问？",
                "装备与技术实现是否已闭合检索、路线取舍与工程瓶颈？",
            ]
        )
    _emit_deep_dialogue_live_progress(
        state.host,
        {
            "event_type": "deep_agent_completed",
            "stage": "s6_authoring",
            "status": "completed" if structurally_complete else "partial",
            "progress": 0.92,
            "kind": "answer",
            "round": "synthesis",
            "role": "能力画像综合总编",
            "axis": "S6 五栏成卡",
            "agent_id": "deep_thinking_dialogue",
            "deliverable_refs": names,
            "proposal_names": names,
            "completed_count": len(required_columns) - len(missing_columns),
            "total_count": len(required_columns),
            "text": (
                "五栏已全部完成，正在整理完整结果。"
                if structurally_complete
                else f"已完成 {len(required_columns) - len(missing_columns)}/5 栏；仍有缺口，未创建能力画像版本。"
            ),
            "summary_text": (
                "五栏已全部完成，正在整理完整结果。"
                if structurally_complete
                else "五栏任务已结束但仍有缺口，已保留研究结果，未创建能力画像版本。"
            ),
        },
    )
    return _annotate_runtime(final, state)


async def tool_deepen(state: TurnState) -> dict[str, Any]:
    from equipment_deep_research.agents.dynamic_prompt_resources import (
        load_dynamic_winning_prompt,
    )
    from equipment_deep_research.agents.workflows.orchestrator import (
        DEEP_DIALOGUE_DIVERGENCE_AXES,
        DEEP_DIALOGUE_INTERNAL_DIMENSIONS,
        DEEP_DIALOGUE_SYNTHESIS_SPINE_SCHEMA,
        _compact_deep_dialogue_seed_payload,
        _deep_dialogue_json,
        _deep_dialogue_naming_assignments,
        _deep_dialogue_naming_format_contract,
        _emit_deep_dialogue_live_progress,
        _govern_deep_dialogue_final,
        _seed_identity_keys,
    )
    from equipment_deep_research.deep_runtime.identity import IDENTITY_SKILL

    mode = _research_action(state)
    if mode not in {"deepen", "diverge", "challenge", "synthesize"}:
        mode = "deepen"
    memory = _memory(state)
    inspected = state.results.get("inspect_memory")
    inspected = inspected if isinstance(inspected, Mapping) else {}
    previous_directions = _latest_observed_directions(state)
    directions = _compact_direction_handoff(previous_directions)
    if not directions:
        directions = _directions_from_memory(memory)
    if not directions:
        directions = _compact_direction_handoff(
            [
                item
                for item in (inspected.get("concept_directions") or [])
                if isinstance(item, Mapping)
            ]
        )
    if not directions and mode != "diverge":
        return await tool_research_council(state)

    payload = state.payload
    payload["authoring_requested"] = False
    naming_assignments = _deep_dialogue_naming_assignments(payload)
    payload["deep_dialogue_naming_assignments"] = naming_assignments
    payload["random_naming_style_assignment"] = naming_assignments[
        "deep_thinking_dialogue"
    ]
    seed_payload = _compact_deep_dialogue_seed_payload(payload, include_naming=True)
    focus = payload.get("deep_research_focus")
    focus = focus if isinstance(focus, Mapping) else {}
    names = [item.get("name", "") for item in directions if item.get("name")]
    seed_keys = _seed_identity_keys(payload)
    deepen_payload = {
        **seed_payload,
        "working_memory": {
            "current_objective": _text(memory.get("current_objective"), 400),
            "selection_rationale": _text(memory.get("selection_rationale"), 900),
            "candidate_directions": directions,
            "open_questions": _questions_from_memory(memory),
        },
        "adjudication": inspected.get("adjudication")
        or _adjudication_from_memory(memory),
        "expert_question": state.inbound.content,
        "deep_research_focus": {
            "candidate": _text(focus.get("candidate"), 120),
            "lens": _text(focus.get("lens"), 80),
        },
        "internal_divergence": {
            "axes": list(DEEP_DIALOGUE_DIVERGENCE_AXES),
            "dimensions": list(DEEP_DIALOGUE_INTERNAL_DIMENSIONS),
        },
    }
    naming_contract = _deep_dialogue_naming_format_contract(
        deepen_payload.get("random_naming_style_assignment")
        if isinstance(deepen_payload.get("random_naming_style_assignment"), Mapping)
        else None
    )
    naming_common = load_dynamic_winning_prompt(
        "common", section="naming_convention"
    ).strip()
    mode_contract = {
        "deepen": (
            "以已有候选为基线，先做多维度、多角度交叉发散，再围绕专家问题深化、分叉或有依据替换。"
            "禁止原样复述或只补一个字段。"
        ),
        "diverge": (
            "暂不受既有候选排序约束，重新生成彼此正交且信息增益高的假设。"
            "先扩展解空间，再只保留能够说明装备构型与作用机理的方向。"
        ),
        "challenge": (
            "不以淘汰为目标，而是为每个已有候选寻找最强反例、最低成本反制和失效边界；"
            "根据挑战结果修订假设、构型或作用机理，并保留仍有研究价值的少数意见。"
        ),
        "synthesize": (
            "不再无目的增加候选。比较已有方向的共同假设、真实分歧与互补关系，"
            "形成研究前沿、假设账本和下一轮最有信息增益的问题。"
        ),
    }[mode]
    mode_labels = {
        "deepen": ("deepen", "内部多维发散", "多维度多角度交叉发散"),
        "diverge": ("diverge", "开放式深度发散", "正交假设与信息增益"),
        "challenge": ("challenge", "对抗挑战", "反例、反制与失效边界"),
        "synthesize": ("synthesize", "研究前沿综合", "冲突保留与比较收敛"),
    }
    round_name, role_name, axis_name = mode_labels[mode]
    _emit_deep_dialogue_live_progress(
        state.host,
        {
            "event_type": "deep_agent_started",
            "stage": "s4_mapping",
            "status": "running",
            "progress": 0.42,
            "kind": "summary",
            "round": round_name,
            "role": role_name,
            "axis": axis_name,
            "agent_id": "deep_thinking_dialogue",
            "deliverable_refs": names,
            "proposal_names": names,
            "summary_text": f"{role_name}已启动；本轮按问题选择必要透镜，不强制重开固定三席与裁决流水线。",
        },
    )
    spine: dict[str, Any] | None = None
    try:
        raw = await run_json_with_provider(
            state.host,
            "deep_thinking_dialogue",
            f"""{IDENTITY_SKILL}

你是创新舱的综合总编。不要再走固定三席提案、固定对抗裁决、五栏成卡的过场；根据本轮研究动作完成最小充分推理。
本轮动作：{mode}。{mode_contract}

研究透镜（按动作取舍，不要求机械逐项输出）：
- 内部维度：{"、".join(DEEP_DIALOGUE_INTERNAL_DIMENSIONS)}
- 互斥角度：{"、".join(DEEP_DIALOGUE_DIVERGENCE_AXES)}
1) 先识别本轮问题最需要的维度，可增减或组合透镜；不要为了凑流程逐项复述。
2) 比较后标出同义改写、参数升级、源装备换壳与因果链断点；这些是研究提示，不得让整轮答复消失。
3) 最多外抛 3 个彼此正交的方向。尽量给出 winning_angle、changed_assumption、equipment_form、operational_mechanism、decisive_target、direct_damage_mechanism、mission_kill_criterion、direct_military_effects、disruptive_difference；暂缺项必须转为 research gap，不得伪造补齐。
4) divergence_steps 写清比较了什么、发现了什么反例或冲突、为何保留或修订。visible_summary 首条写清本轮相对工作记忆推进了什么。
终点是物理毁伤与可观察任务失能；认知、电磁、信息只能赋能发现、突防、进入或命中。不要写 S6 五栏正文。
{state.skill_prompt}
{naming_contract}
{naming_common}

只输出综合主线 schema 要求的严格 JSON。""",
            deepen_payload,
            DEEP_DIALOGUE_SYNTHESIS_SPINE_SCHEMA,
            7000,
            phase="deep_contextual_dialogue_deepen",
            runtime=state.provider_runtime,
        )
        spine = _deep_dialogue_json(raw)
    except Exception:
        spine = None

    if not isinstance(spine, Mapping) or not spine:
        spine = {
            "visible_summary": [
                f"本轮{role_name}未完整返回，已保留可恢复的已有方向；可换个问法继续。"
            ],
            "selection_rationale": _text(
                memory.get("selection_rationale")
                or inspected.get("selection_rationale"),
                900,
            )
            or "沿用上一轮已收敛方向。",
            "concept_directions": directions,
            "open_questions": _questions_from_memory(memory)
            or ["请指出要继续闭合的缺口，或明确说推翻当前方向。"],
        }
    spine["capability_card_draft"] = {}
    if not spine.get("adjudication"):
        spine["adjudication"] = deepen_payload["adjudication"]
    final = _govern_deep_dialogue_final(
        spine, seed_keys=seed_keys, require_s6=False
    )
    final["adjudication"] = spine.get("adjudication") or deepen_payload["adjudication"]
    final["capability_card_draft"] = {}
    out_names = [
        _text(item.get("name"), 120)
        for item in (final.get("concept_directions") or [])[:3]
        if isinstance(item, Mapping) and _text(item.get("name"), 120)
    ]
    steps = [
        item
        for item in (final.get("divergence_steps") or spine.get("divergence_steps") or [])
        if isinstance(item, Mapping) and _text(item.get("text") or item.get("title"), 8)
    ]
    dialogue = []
    for index, step in enumerate(steps[:3]):
        axis = (
            DEEP_DIALOGUE_DIVERGENCE_AXES[index]
            if index < len(DEEP_DIALOGUE_DIVERGENCE_AXES)
            else _text(step.get("title") or step.get("stage"), 80)
            or f"内部角度{index + 1}"
        )
        summary = _text(step.get("text") or step.get("title"), 1200)
        title = _text(step.get("title"), 80) or axis
        dialogue.append(
            {
                "agent_id": "deep_thinking_dialogue",
                "role": f"{'内部发散' if mode == 'deepen' else role_name} · {title}",
                "axis": axis,
                "round": round_name,
                "summary": summary,
                "proposal_names": out_names,
            }
        )
        _emit_deep_dialogue_live_progress(
            state.host,
            {
                "event_type": "deep_agent_completed",
                "stage": "s4_mapping",
                "status": "completed",
                "progress": round(0.55 + 0.08 * index, 3),
                "kind": "answer",
                "round": round_name,
                "role": f"{'内部发散' if mode == 'deepen' else role_name} · {title}",
                "axis": axis,
                "agent_id": "deep_thinking_dialogue",
                "deliverable_refs": out_names,
                "proposal_names": out_names,
                "text": summary[:1200],
                "summary_text": f"内部角度「{axis}」已完成交叉比较。",
            },
        )
    dialogue.append(
        {
            "agent_id": "deep_thinking_dialogue",
            "role": role_name,
            "axis": axis_name,
            "round": round_name,
            "summary": _text(
                final.get("selection_rationale")
                or "；".join(str(item) for item in (final.get("visible_summary") or [])[:2]),
                1200,
            ),
            "proposal_names": out_names,
        }
    )
    final["agent_dialogue"] = dialogue
    final["orchestration"] = {
        "pattern": {
            "deepen": "memory_led_internal_multidim_deepen",
            "diverge": "adaptive_integrated_divergence",
            "challenge": "memory_led_adversarial_challenge",
            "synthesize": "memory_led_frontier_synthesis",
        }[mode],
        "rounds": 1,
        "phases": [
            {
                "deepen": "internal_multidim_deepen",
                "diverge": "integrated_divergence",
                "challenge": "adversarial_challenge",
                "synthesize": "frontier_synthesis",
            }[mode]
        ],
        "divergence_axes": list(DEEP_DIALOGUE_DIVERGENCE_AXES),
        "internal_dimensions": list(DEEP_DIALOGUE_INTERNAL_DIMENSIONS),
        "requested_agents": 1,
        "completed_divergence_agents": 0,
        "degraded": not bool(final.get("concept_directions")),
        "quality_gate_passed": False,
        "finalization_status": final.get("finalization_status", "analysis_only"),
    }
    if not _text(" ".join(str(item) for item in (final.get("open_questions") or []))):
        final["open_questions"] = [
            "内部比较后，哪个角度最值得继续追问？",
            "若要推翻当前方向，请直接说明要改写的作战关系。",
            "使用 /card 沿当前方向写成五栏能力卡。",
        ]
    _emit_deep_dialogue_live_progress(
        state.host,
        {
            "event_type": "deep_agent_completed",
            "stage": "s4_mapping",
            "status": "completed",
            "progress": 0.88,
            "kind": "answer",
            "round": round_name,
            "role": role_name,
            "axis": axis_name,
            "agent_id": "deep_thinking_dialogue",
            "deliverable_refs": out_names,
            "proposal_names": out_names,
            "text": (
                f"{role_name}：{_text(final.get('selection_rationale'), 900)}"
                + (f" · 方向：{'、'.join(out_names)}" if out_names else "")
            )[:1200],
            "summary_text": f"{role_name}已形成可继续追问的研究前沿，等待下一步动作。",
        },
    )
    return _annotate_runtime(final, state)


async def tool_diverge(state: TurnState) -> dict[str, Any]:
    """Run integrated open divergence without imposing fixed external seats."""

    state.payload["deep_research_mode"] = "diverge"
    return await tool_deepen(state)


async def tool_challenge(state: TurnState) -> dict[str, Any]:
    """Stress-test remembered directions and revise them without a verdict gate."""

    state.payload["deep_research_mode"] = "challenge"
    return await tool_deepen(state)


async def tool_synthesize(state: TurnState) -> dict[str, Any]:
    """Consolidate the research frontier while preserving disagreements."""

    state.payload["deep_research_mode"] = "synthesize"
    return await tool_deepen(state)


async def tool_research_council(state: TurnState) -> dict[str, Any]:
    from equipment_deep_research.agents.dynamic_prompt_resources import (
        load_dynamic_winning_prompt,
    )
    from equipment_deep_research.agents.workflows.orchestrator import (
        _deep_dialogue_naming_assignments,
        _deep_dialogue_s6_contract,
        _run_deep_dialogue_council,
    )

    payload = state.payload
    payload["deep_research_mode"] = "research_council"
    # A council turn may produce a stable direction, but that direction did not
    # exist when the user confirmed authoring.  Keep this tool analysis-only so
    # S6 can start only from a later turn that restores the closed direction
    # from working memory and explicitly selects ``author_s6``.
    payload["authoring_requested"] = False
    payload["deep_skill_prompt"] = state.skill_prompt
    naming_assignments = _deep_dialogue_naming_assignments(payload)
    payload["deep_dialogue_naming_assignments"] = naming_assignments
    payload["random_naming_style_assignment"] = naming_assignments[
        "deep_thinking_dialogue"
    ]
    naming_contract = load_dynamic_winning_prompt(
        "common", section="naming_convention"
    ).strip()
    final = await _run_deep_dialogue_council(
        state.host,
        payload,
        naming_contract=naming_contract,
        five_column_contract=_deep_dialogue_s6_contract(),
        provider_runtime=state.provider_runtime,
    )
    return _annotate_runtime(final, state)


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "help": tool_help,
    "inspect_memory": tool_inspect_memory,
    "deepen": tool_deepen,
    "diverge": tool_diverge,
    "challenge": tool_challenge,
    "synthesize": tool_synthesize,
    "author_s6": tool_author_s6,
    "research_council": tool_research_council,
}
