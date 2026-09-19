"""Model-led turn conductor, adapted from nanobot tool-choice and OpenOPC orchestration.

The model chooses the cheapest research tool that answers this expert turn.
It cannot invent speakers, dump parent evidence, or skip the S6 confirmation
gate.  Opening turns still skip this call and run isolated proposers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from equipment_deep_research.deep_runtime.identity import IDENTITY_SKILL
from equipment_deep_research.deep_runtime.provider_runtime import run_json_with_provider
from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime
from equipment_deep_research.deep_runtime.planner import (
    InboundTurn,
    conductor_may_choose_tool,
    intent_from_plan,
    plan_turn,
    sanitize_plan,
    tool_from_intent,
)

if TYPE_CHECKING:
    from equipment_deep_research.deep_runtime.state import TurnState

CONDUCT_SCHEMA: dict[str, Any] = {
    "intent": "deepen|diverge|challenge|synthesize|reopen_council|author|memory",
    "rationale": "string",
    "tools": ["deepen"],
    "focus_candidate": "string",
    "focus_lens": "string",
}

NEXT_ACTION_SCHEMA: dict[str, Any] = {
    "action": "finish|deepen|diverge|challenge|synthesize|research_council",
    "rationale": "string",
    "unresolved_question": "string",
}

_CLOSURE_FIELDS = (
    "winning_angle",
    "changed_assumption",
    "equipment_form",
    "operational_mechanism",
    "decisive_target",
    "direct_damage_mechanism",
    "mission_kill_criterion",
    "direct_military_effects",
    "disruptive_difference",
)


def _text(value: Any, limit: int = 400) -> str:
    return " ".join(str(value or "").split()).strip()[: max(0, int(limit))]


def should_conduct(inbound: InboundTurn) -> bool:
    return conductor_may_choose_tool(inbound)


def working_memory_snapshot(inbound: InboundTurn) -> dict[str, Any]:
    memory = inbound.working_memory if isinstance(inbound.working_memory, Mapping) else {}
    directions: list[dict[str, Any]] = []
    raw = memory.get("candidate_directions")
    rows = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
    for item in rows[:3]:
        if not isinstance(item, Mapping):
            continue
        name = _text(item.get("name"), 120)
        if not name:
            continue
        missing = [
            field for field in _CLOSURE_FIELDS if not _text(item.get(field), 8)
        ]
        directions.append(
            {
                "name": name,
                "stable": bool(item.get("stable")),
                "winning_angle": _text(item.get("winning_angle"), 180),
                "equipment_form": _text(item.get("equipment_form"), 180),
                "missing_fields": missing,
            }
        )
    questions = memory.get("open_questions")
    open_questions = [
        _text(item, 180)
        for item in (questions if isinstance(questions, list) else [])[:4]
        if _text(item, 180)
    ]
    return {
        "question": inbound.content,
        "has_closed_stable_direction": inbound.has_closed_stable_direction,
        "current_objective": _text(memory.get("current_objective"), 240),
        "selection_rationale": _text(memory.get("selection_rationale"), 400),
        "open_questions": open_questions,
        "directions": directions,
    }


def _parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        import json

        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _emit(host: Any, row: Mapping[str, Any]) -> None:
    emit = getattr(host, "_emit_deep_dialogue_progress", None)
    if not callable(emit):
        return
    try:
        emit(dict(row))
    except Exception:
        return


def _normalize_tools(raw: Any, intent: Any) -> list[str]:
    tools: list[str] = []
    if isinstance(raw, str) and raw.strip():
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        tools = [str(item).strip() for item in raw if str(item).strip()]
    mapped = tool_from_intent(intent)
    if mapped and mapped not in tools:
        tools = [mapped, *tools]
    return tools


async def resolve_turn_plan(
    host: Any,
    inbound: InboundTurn,
    payload: Mapping[str, Any],
    *,
    provider_runtime: ProviderRuntime | None = None,
) -> tuple[list[str], dict[str, Any]]:
    heuristic = plan_turn(inbound)
    meta = {
        "intent": intent_from_plan(heuristic),
        "rationale": "",
        "source": "heuristic",
        "tools": list(heuristic),
        "focus_candidate": "",
        "focus_lens": "",
    }
    fallback_is_council = "research_council" in heuristic
    fallback_text = (
        "指挥链路未返回有效选择，按专家的重开要求进入隔离发散。"
        if fallback_is_council
        else "指挥链路未返回有效选择，本轮在已有方向上做内部多维发散，不重开三席。"
    )
    fallback_summary = (
        "回退到重新隔离发散。"
        if fallback_is_council
        else "回退到工作记忆上的内部多维深化。"
    )
    if not should_conduct(inbound):
        return heuristic, meta

    snapshot = working_memory_snapshot(inbound)
    _emit(
        host,
        {
            "event_type": "deep_agent_started",
            "stage": "context",
            "status": "running",
            "progress": 0.16,
            "kind": "summary",
            "round": "conduct",
            "role": "任务编排",
            "axis": "本轮工具选择",
            "agent_id": "deep_dialogue_orchestrator",
            "summary_text": "正在根据专家问题与工作记忆选择本轮研究动作：追问走内部多维发散，不默认重开三席流水线。",
        },
    )
    try:
        raw = await run_json_with_provider(
            host,
            "deep_dialogue_orchestrator",
            f"""{IDENTITY_SKILL}

你是创新舱指挥，不是流水线调度员。根据专家本轮问题和工作记忆，选择最少工具完成这一轮。
可选工具：
- deepen：已有候选时，一次推理内做多维度、多角度发散，再收敛到本轮专家问题；不要为走流程重开三席，也不要只修补一个字段。
- diverge：重新探索正交假设；适合用户要求扩展解空间，但无需固定三席和固定裁决。
- challenge：已有候选时专门寻找反例、最低成本反制和失效边界，再修订候选。
- synthesize：已有多条候选或多轮结论时做比较综合，保留冲突与待验证假设，不写能力卡。
- research_council：仅当需要多路隔离提案和独立交叉挑战（彻底推翻、强争议或现有方向无法回答本问）。
- inspect_memory：只读记忆。
- author_s6：仅当用户已确认成卡且方向已闭合。
已匹配的程序性 Skill 只约束执行方法和质量门，不会扩大可选工具范围。
优先选择能回答本问的最小动作；允许按观察结果在后续一轮补 challenge 或 synthesize。
禁止把普通追问默认成「三席提案 → 对抗裁决 → 五栏成卡」。
禁止把 deepen 理解成单点修补；它仍须内部多角度发散。
禁止输出父任务证据、制造参数或具体操作步骤。
只输出 JSON。""",
            {
                "identity": IDENTITY_SKILL,
                "working_memory": snapshot,
                "question": inbound.content,
                "authoring_requested": inbound.authoring_requested,
                "matched_skills": list(payload.get("deep_skill_catalog", []))[:6],
            },
            CONDUCT_SCHEMA,
            800,
            phase="deep_research_conduct",
            runtime=provider_runtime,
        )
        chosen = _parse_json(raw)
        proposed_tools = _normalize_tools(
            chosen.get("tools"), chosen.get("intent")
        )
        if not proposed_tools:
            raise ValueError("conductor returned no governed tool choice")
    except Exception:
        _emit(
            host,
            {
                "event_type": "deep_agent_completed",
                "stage": "context",
                "status": "completed",
                "progress": 0.18,
                "kind": "answer",
                "round": "conduct",
                "role": "任务编排",
                "axis": "本轮工具选择",
                "agent_id": "deep_dialogue_orchestrator",
                "text": fallback_text,
                "summary_text": fallback_summary,
            },
        )
        return heuristic, meta

    plan = sanitize_plan(proposed_tools, inbound)
    rationale = _text(chosen.get("rationale"), 400)
    focus_candidate = _text(chosen.get("focus_candidate"), 120)
    focus_lens = _text(chosen.get("focus_lens"), 80)
    meta = {
        "intent": _text(chosen.get("intent"), 40) or intent_from_plan(plan),
        "rationale": rationale,
        "source": "model",
        "tools": list(plan),
        "focus_candidate": focus_candidate,
        "focus_lens": focus_lens,
    }
    if isinstance(payload, dict) and (focus_candidate or focus_lens):
        payload["deep_research_focus"] = {
            "candidate": focus_candidate,
            "lens": focus_lens,
        }
    summary = rationale or (
        "本轮在已有方向上做内部多维发散，不重开三席。"
        if "deepen" in plan
        else "本轮需要重新独立发散。"
        if "research_council" in plan
        else "本轮按指挥选择执行。"
    )
    _emit(
        host,
        {
            "event_type": "deep_agent_completed",
            "stage": "context",
            "status": "completed",
            "progress": 0.18,
            "kind": "answer",
            "round": "conduct",
            "role": "任务编排",
            "axis": "本轮工具选择",
            "agent_id": "deep_dialogue_orchestrator",
            "text": summary,
            "summary_text": summary,
        },
    )
    return plan, meta


async def resolve_next_action(state: TurnState) -> str | None:
    """Choose one action for the next loop turn from current observations.

    The default policy executes the governed plan once.  Calling it again after
    every observation leaves a narrow extension point for an observation-aware
    policy without adding another model call to ordinary dialogue turns.
    """

    attempted = set(state.completed_tools) | {
        str(item.get("tool", ""))
        for item in state.observations
        if item.get("kind") == "tool_result"
    }
    for name in sanitize_plan(state.plan, state.inbound):
        if name not in attempted:
            return name
    # Tool observations may recommend one bounded follow-up action. This is
    # the nanobot-style policy -> observation -> policy continuation point;
    # command and S6 gates are still enforced by ``sanitize_next_action``.
    for observation in reversed(state.observations):
        result = observation.get("result") if isinstance(observation, Mapping) else None
        if not isinstance(result, Mapping):
            continue
        assessment = result.get("research_assessment")
        assessment = assessment if isinstance(assessment, Mapping) else {}
        strategy = result.get("research_strategy")
        strategy = strategy if isinstance(strategy, Mapping) else {}
        recommended = _text(
            assessment.get("recommended_action")
            or strategy.get("next_action"),
            40,
        )
        recommendation_scope = _text(
            assessment.get("recommendation_scope")
            or strategy.get("next_action_scope"),
            24,
        ).lower()
        if (
            recommendation_scope == "same_turn"
            and recommended
            and recommended not in attempted
        ):
            return recommended

    # A deployment may opt into a true observation-aware continuation.  The
    # first action still comes from the compact turn plan; only after a real
    # tool result can the model spend one bounded decision call to finish or
    # choose a distinct follow-up.  Runner budgets and sanitize_next_action
    # remain the execution authority, including the explicit S6 gate.
    if not bool(state.payload.get("adaptive_tool_loop")):
        return None
    if state.provider_runtime is None or not state.completed_tools:
        return None
    if state.inbound.command in {"help", "memory", "card"}:
        return None
    if any(
        item.get("kind") == "adaptive_policy_decision"
        for item in state.observations
        if isinstance(item, Mapping)
    ):
        return None
    latest = next(
        (
            item.get("result")
            for item in reversed(state.observations)
            if isinstance(item, Mapping)
            and item.get("kind") == "tool_result"
            and isinstance(item.get("result"), Mapping)
        ),
        {},
    )
    if not latest:
        return None
    remaining = max(0, min(state.max_turns - state.turn_count, state.max_tool_calls - state.tool_call_count))
    if remaining <= 0:
        return None
    try:
        raw = await run_json_with_provider(
            state.host,
            "deep_dialogue_orchestrator",
            f"""{IDENTITY_SKILL}

你在极简 Agent Loop 中读取刚完成的工具观察。判断本轮问题是否已经得到充分回答。
若已回答，action=finish。若仍有一个关键缺口，只选择一个不同的后续动作：
- deepen：沿当前候选继续多角度闭合；
- diverge：扩大正交解空间；
- challenge：找最强反例、最低成本反制和失效边界；
- synthesize：比较并合并已有冲突；
- research_council：仅用于现有方向确实无法回答问题或需要隔离竞争提案。
不得选择 author_s6；成卡只能由用户明确确认触发。不得重复已完成动作，不得改变源装备身份。
只输出 JSON。""",
            {
                "question": state.inbound.content,
                "completed_tools": list(state.completed_tools)[-6:],
                "latest_observation": latest,
                "working_memory": working_memory_snapshot(state.inbound),
                "remaining_action_budget": min(1, remaining),
            },
            NEXT_ACTION_SCHEMA,
            600,
            phase="deep_research_adaptive_policy",
            runtime=state.provider_runtime,
        )
        decision = _parse_json(raw)
        action = _text(decision.get("action"), 40).lower()
        if action == "finish":
            action = ""
        if action in attempted:
            action = ""
        state.observations.append(
            {
                "kind": "adaptive_policy_decision",
                "turn_index": state.turn_count,
                "status": "continue" if action else "finish",
                "tool": action or "finish",
                "rationale": _text(decision.get("rationale"), 400),
                "unresolved_question": _text(decision.get("unresolved_question"), 300),
            }
        )
        rationale = _text(decision.get("rationale"), 400)
        unresolved = _text(decision.get("unresolved_question"), 300)
        next_stage = {
            "diverge": "s3_divergence",
            "research_council": "s3_divergence",
            "challenge": "council_critique",
            "deepen": "s4_mapping",
            "synthesize": "s4_mapping",
        }.get(action, "s4_mapping")
        _emit(
            state.host,
            {
                "event_type": "deep_agent_handoff" if action else "deep_agent_completed",
                "stage": next_stage,
                "status": "running" if action else "completed",
                "progress": 0.53 if action else 0.88,
                "kind": "summary",
                "round": "adaptive_policy",
                "role": "任务编排",
                "axis": "观察后续决策",
                "agent_id": "deep_dialogue_orchestrator",
                "from_agent_id": "deep_dialogue_orchestrator",
                "to_agent_id": f"deep_tool_{action}" if action else "deep_dialogue_response",
                "handoff_kind": "observation_follow_up" if action else "finish",
                "summary_text": rationale or (
                    f"观察后选择继续执行 {action}。" if action else "当前观察已足以回答本轮问题。"
                ),
                "text": unresolved,
            },
        )
        return action or None
    except Exception as exc:
        if type(exc).__name__ in {"_DeepJobCancelled", "_DeepJobInterrupted"}:
            raise
        state.observations.append(
            {
                "kind": "adaptive_policy_decision",
                "turn_index": state.turn_count,
                "status": "unavailable",
                "tool": "finish",
            }
        )
    return None
