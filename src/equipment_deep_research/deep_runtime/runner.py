"""Bounded policy -> tool -> observation loop with mid-turn steer injection."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from equipment_deep_research.deep_runtime.conductor import resolve_next_action
from equipment_deep_research.deep_runtime.planner import sanitize_next_action
from equipment_deep_research.deep_runtime.state import TurnState
from equipment_deep_research.deep_runtime.tools import TOOL_HANDLERS
from equipment_deep_research.deep_runtime.tool_registry import build_tool_registry
from equipment_deep_research.harness.event_bus import sanitize_runtime_payload
from equipment_deep_research.deep_runtime.research_support import project_observation, select_support_calls

ActionPolicy = Callable[[TurnState], str | None | Awaitable[str | None]]
CheckpointCallback = Callable[[dict[str, Any]], Any | Awaitable[Any]]

_STEER_STAGES = {
    "inspect_memory": "context",
    "help": "context",
    "deepen": "s4_mapping",
    "diverge": "s3_divergence",
    "challenge": "council_critique",
    "synthesize": "s4_mapping",
    "research_council": "context",
    "author_s6": "s6_authoring",
}

_CHECKPOINT_RESULT_KEYS = (
    "visible_summary",
    "selection_rationale",
    "concept_directions",
    "capability_card_draft",
    "adjudication",
    "open_questions",
    "finalization_status",
    "quality_gate",
    "research_strategy",
    "research_assessment",
    "research_gaps",
    "orchestration",
    "runtime",
    "external_data",
)
_MAX_CHECKPOINT_CHARS = 60_000


def _bounded_checkpoint_value(value: Any, *, depth: int = 0) -> Any:
    """Project runtime state into a small, JSON-compatible recovery payload."""

    if depth >= 4:
        if isinstance(value, Mapping):
            return {"truncated": True}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return []
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:24]:
            name = str(key)[:120]
            result[name] = _bounded_checkpoint_value(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            _bounded_checkpoint_value(item, depth=depth + 1)
            for item in list(value)[:8]
        ]
    return str(value)[:1200]


def _checkpoint_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: _bounded_checkpoint_value(value.get(key))
        for key in _CHECKPOINT_RESULT_KEYS
        if key in value
    }


def _checkpoint_json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _fit_checkpoint_value(value: Any, max_chars: int) -> Any:
    """Keep a JSON-compatible value inside a hard serialized character budget."""

    if max_chars <= 4:
        return None
    if _checkpoint_json_chars(value) <= max_chars:
        return value
    if isinstance(value, str):
        marker = "..."
        low, high = 0, len(value)
        while low < high:
            middle = (low + high + 1) // 2
            candidate = value[:middle] + marker
            if _checkpoint_json_chars(candidate) <= max_chars:
                low = middle
            else:
                high = middle - 1
        candidate = value[:low] + marker
        return candidate if _checkpoint_json_chars(candidate) <= max_chars else ""
    if isinstance(value, Mapping):
        fitted: dict[str, Any] = {}
        marker_key = "checkpoint_truncated"
        marker_cost = _checkpoint_json_chars({marker_key: True}) + 1
        for raw_key, item in value.items():
            key = str(raw_key)[:120]
            # Reserve room for the truncation marker before accepting any
            # field.  Without this reservation a large control field could
            # consume the complete budget and silently drop the marker that
            # tells recovery consumers the projection is lossy.
            remaining = (
                max_chars
                - _checkpoint_json_chars(fitted)
                - marker_cost
                - len(key)
                - 8
            )
            if remaining <= 4:
                break
            candidate = dict(fitted)
            candidate[key] = _fit_checkpoint_value(item, remaining)
            if _checkpoint_json_chars(candidate) > max_chars:
                break
            fitted = candidate
        candidate = {**fitted, marker_key: True}
        return candidate if _checkpoint_json_chars(candidate) <= max_chars else fitted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        fitted_items: list[Any] = []
        for item in value:
            remaining = max_chars - _checkpoint_json_chars(fitted_items) - 2
            if remaining <= 4:
                break
            candidate = [*fitted_items, _fit_checkpoint_value(item, remaining)]
            if _checkpoint_json_chars(candidate) > max_chars:
                break
            fitted_items = candidate
        return fitted_items
    return _fit_checkpoint_value(str(value), max_chars)


def _fit_checkpoint_budget(checkpoint: dict[str, Any]) -> dict[str, Any]:
    if _checkpoint_json_chars(checkpoint) <= _MAX_CHECKPOINT_CHARS:
        return checkpoint

    compact = {
        key: checkpoint.get(key)
        for key in (
            "schema_version",
            "phase",
            "status",
            "turn_count",
            "tool_call_count",
            "plan",
            "completed_tools",
            "active_skill_ids",
            "stop_reason",
            "pending_tool_calls",
        )
    }
    compact["checkpoint_truncated"] = True
    assistant = checkpoint.get("assistant_message", {})
    compact["assistant_message"] = _fit_checkpoint_value(assistant, 26_000)
    completed = checkpoint.get("completed_tool_results", [])
    if isinstance(completed, list):
        completed = completed[-4:]
    remaining = _MAX_CHECKPOINT_CHARS - _checkpoint_json_chars(compact) - 512
    compact["completed_tool_results"] = _fit_checkpoint_value(
        completed,
        max(4, remaining),
    )
    # The compact fields above are themselves user/model controlled (for
    # example a long stop reason or an unexpectedly large plan).  Apply one
    # final whole-object fit so the repository's byte/character ceiling is a
    # hard invariant rather than an estimate based on a few payload fields.
    fitted = _fit_checkpoint_value(compact, _MAX_CHECKPOINT_CHARS)
    if isinstance(fitted, dict) and _checkpoint_json_chars(fitted) <= _MAX_CHECKPOINT_CHARS:
        return fitted

    # This branch is intentionally tiny and deterministic.  It should only be
    # reachable if a future change introduces a non-JSON value or changes the
    # fitter's accounting; recovery still gets enough identity to resume.
    minimal = {
        "schema_version": str(checkpoint.get("schema_version", "deep-runtime-checkpoint-v1"))[:120],
        "phase": str(checkpoint.get("phase", ""))[:120],
        "status": str(checkpoint.get("status", ""))[:64],
        "checkpoint_truncated": True,
    }
    return _fit_checkpoint_value(minimal, _MAX_CHECKPOINT_CHARS)


def _checkpoint_callback(state: TurnState) -> CheckpointCallback | None:
    callback = state.payload.get("checkpoint_callback")
    if not callable(callback):
        callback = getattr(state.host, "_checkpoint_deep_runtime", None)
    return callback if callable(callback) else None


async def emit_runtime_checkpoint(
    state: TurnState,
    phase: str,
    *,
    action: str | None = None,
    assistant_result: Mapping[str, Any] | None = None,
) -> None:
    """Persist one bounded decision/action/observation checkpoint when configured."""

    callback = _checkpoint_callback(state)
    if callback is None:
        return
    pending = (
        [
            {
                "tool_call_id": f"deep-turn-{state.turn_count}",
                "tool_name": action,
                "turn_index": state.turn_count,
            }
        ]
        if phase == "awaiting_tools" and action
        else []
    )
    completed: list[dict[str, Any]] = []
    for observation in state.observations[-8:]:
        if not isinstance(observation, Mapping):
            continue
        kind = str(observation.get("kind", ""))
        if kind not in {"tool_result", "tool_error", "control"}:
            continue
        row = {
            "kind": kind,
            "turn_index": int(observation.get("turn_index", 0) or 0),
            "tool_name": str(observation.get("tool", ""))[:120],
            "status": str(observation.get("status", ""))[:32],
        }
        if isinstance(observation.get("result"), Mapping):
            row["result"] = _checkpoint_result(observation.get("result"))
        if observation.get("error_type"):
            row["error_type"] = str(observation.get("error_type"))[:120]
        completed.append(row)
    checkpoint = _fit_checkpoint_budget(sanitize_runtime_payload({
        "schema_version": "deep-runtime-checkpoint-v1",
        "phase": str(phase),
        "status": state.status,
        "turn_count": state.turn_count,
        "tool_call_count": state.tool_call_count,
        "plan": list(state.plan)[:8],
        "completed_tools": list(state.completed_tools)[:8],
        "active_skill_ids": [
            str(item.get("skill_id", ""))[:140]
            for item in state.active_skills[:6]
            if str(item.get("skill_id", "")).strip()
        ],
        "stop_reason": state.stop_reason,
        "assistant_message": (
            {
                "role": "assistant",
                "content": _checkpoint_result(assistant_result),
            }
            if isinstance(assistant_result, Mapping)
            else {
                "role": "assistant",
                "content": "",
                "tool_calls": pending,
            }
        ),
        "completed_tool_results": completed,
        "pending_tool_calls": pending,
    }, max_string_length=1200))
    outcome = callback(checkpoint)
    if inspect.isawaitable(outcome):
        await outcome


def _truthy_stop(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "stop",
            "stopped",
            "cancelled",
            "cancel_requested",
        }
    return bool(value)


async def _stop_requested(state: TurnState) -> bool:
    parent = state.payload.get("deep_parent_context")
    parent = parent if isinstance(parent, Mapping) else {}
    for value in (
        state.payload.get("stop_requested"),
        state.payload.get("cancel_requested"),
        state.payload.get("cancelled"),
        parent.get("stop_requested"),
        parent.get("status"),
    ):
        if _truthy_stop(value):
            return True

    callback = state.payload.get("should_stop")
    if not callable(callback):
        callback = getattr(state.host, "_should_stop_deep_runtime", None)
    if not callable(callback):
        return False
    try:
        value = callback(state)
    except TypeError:
        value = callback()
    if inspect.isawaitable(value):
        value = await value
    return _truthy_stop(value)


async def _choose_action(state: TurnState, policy: ActionPolicy) -> str | None:
    decision = policy(state)
    if inspect.isawaitable(decision):
        decision = await decision
    return decision


def _claim_steers(state: TurnState, action: str) -> bool:
    from equipment_deep_research.agents.workflows.orchestrator import (
        _consume_deep_dialogue_steers,
    )

    stage = _STEER_STAGES.get(action)
    if not stage:
        return False
    accepted = _consume_deep_dialogue_steers(state.host, state.payload, stage)
    return any(
        str(item.get("mode", "")).lower() == "interrupt_send"
        for item in accepted
    )


async def _run_support_calls(
    state: TurnState,
    support_calls: Sequence[Mapping[str, Any]],
) -> None:
    """Run independent, read-only MCP support probes as one bounded batch.

    ``select_support_calls`` already limits the batch to the remaining tool
    budget and the MCP transport applies its own per-server semaphore.  The
    old runner nevertheless awaited every call serially, turning two
    independent source probes into two full network latencies.  Fan them out
    here, then merge rows in selection order so downstream policy and
    checkpoint replay remain deterministic.  Individual adapter failures are
    advisory and stay visible to the main research action.
    """

    if not support_calls:
        return

    names = {str(entry.get("name", "")) for entry in support_calls}
    state.tool_call_count += len(support_calls)
    state.current_action = "mcp_support_batch"
    await emit_runtime_checkpoint(state, "awaiting_tools", action="mcp_support_batch")

    async def execute_one(call: Mapping[str, Any]) -> dict[str, Any]:
        name = str(call.get("name", ""))
        arguments = call.get("arguments", {})
        try:
            result = project_observation(
                await asyncio.wait_for(
                    state.tool_registry.execute_mcp(name, arguments), timeout=15
                )
            )
            return {
                "kind": "tool_result",
                "tool": name,
                "turn_index": state.turn_count,
                "status": "completed",
                "result": {"external_data": result},
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {
                "kind": "tool_error",
                "tool": name,
                "turn_index": state.turn_count,
                "status": "failed",
                "error_type": type(exc).__name__,
            }

    rows = await asyncio.gather(*(execute_one(call) for call in support_calls))
    for row in rows:
        state.observations.append(row)
        if row["status"] == "completed":
            state.completed_tools.append(str(row["tool"]))
    state.payload["external_tool_observations"] = [
        project_observation(item)
        for item in state.observations
        if item.get("tool") in names
    ][-2:]
    state.current_action = ""
    await emit_runtime_checkpoint(state, "tools_completed", action="mcp_support_batch")


async def run_planned_tools(
    state: TurnState,
    *,
    policy: ActionPolicy | None = None,
) -> TurnState:
    """Run one governed tool per turn and feed its result to the next decision."""

    action_policy = policy or resolve_next_action
    # Capability and intelligence are separate: the policy chooses a name,
    # while this per-turn registry resolves the executable implementation. A
    # lazily-created registry keeps direct TurnState callers compatible and
    # still observes monkeypatched/host-provided handlers at execution time.
    tool_registry = state.tool_registry
    if tool_registry is None:
        tool_registry = build_tool_registry(handlers=TOOL_HANDLERS)
        state.tool_registry = tool_registry
    state.max_turns = max(0, int(state.max_turns))
    state.max_tool_calls = max(0, int(state.max_tool_calls))
    while state.turn_count < state.max_turns:
        if await _stop_requested(state):
            state.status = "stopped"
            state.stop_reason = "stop_requested"
            break
        if state.completed_tools and _claim_steers(state, state.completed_tools[-1]):
            state.interrupted = True
            state.status = "stopped"
            state.stop_reason = "interrupt_send"
            state.observations.append(
                {
                    "kind": "control",
                    "turn_index": state.turn_count,
                    "status": "interrupted",
                    "tool": state.completed_tools[-1],
                }
            )
            break

        state.turn_count += 1
        proposed = await _choose_action(state, action_policy)
        has_observed_candidates = any(
            isinstance(observation.get("result"), Mapping)
            and isinstance(observation["result"].get("concept_directions"), list)
            and bool(observation["result"].get("concept_directions"))
            for observation in state.observations
            if isinstance(observation, Mapping)
        )
        action = sanitize_next_action(
            proposed,
            state.inbound,
            state.completed_tools,
            has_observed_candidates=has_observed_candidates,
        )
        state.policy_trace.append(
            {
                "turn_index": state.turn_count,
                "proposed_action": str(proposed or ""),
                "action": action or "finish",
                "observation_count": len(state.observations),
            }
        )
        if action is None:
            state.status = "completed"
            state.stop_reason = "policy_finished"
            break
        if state.tool_call_count >= state.max_tool_calls:
            state.status = "max_tool_calls"
            state.stop_reason = "max_tool_calls"
            break

        spec = tool_registry.get(action)
        if spec is None:
            state.status = "failed"
            state.stop_reason = f"unknown_tool:{action}"
            break
        if _claim_steers(state, action):
            state.interrupted = True
            state.status = "stopped"
            state.stop_reason = "interrupt_send"
            state.observations.append(
                {
                    "kind": "control",
                    "turn_index": state.turn_count,
                    "status": "interrupted",
                    "tool": action,
                }
            )
            break

        support_calls = await select_support_calls(state, action)
        if support_calls:
            if await _stop_requested(state):
                state.status = "stopped"
                state.stop_reason = "stop_requested"
                break
            if _claim_steers(state, action):
                state.interrupted = True
                break
            await _run_support_calls(state, support_calls)
        if state.status == "stopped" or state.interrupted or await _stop_requested(state):
            state.status = "stopped"
            state.stop_reason = "interrupt_send" if state.interrupted else "stop_requested"
            state.current_action = ""
            break
        if support_calls and _claim_steers(state, action):
            state.interrupted = True
            state.status = "stopped"
            state.stop_reason = "interrupt_send"
            break
        state.tool_call_count += 1
        state.current_action = action
        await emit_runtime_checkpoint(state, "awaiting_tools", action=action)
        try:
            result = await tool_registry.execute(action, state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if type(exc).__name__ in {"_DeepJobCancelled", "_DeepJobInterrupted"}:
                raise
            state.status = "failed"
            state.stop_reason = f"tool_error:{action}"
            state.observations.append(
                {
                    "kind": "tool_error",
                    "turn_index": state.turn_count,
                    "tool": action,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
            )
            await emit_runtime_checkpoint(state, "tools_completed", action=action)
            raise
        state.results[action] = result
        state.current_action = ""
        state.completed_tools.append(action)
        state.observations.append(
            {
                "kind": "tool_result",
                "turn_index": state.turn_count,
                "tool": action,
                "status": "completed",
                "result": result,
            }
        )
        await emit_runtime_checkpoint(state, "tools_completed", action=action)
        if _claim_steers(state, action):
            state.interrupted = True
            state.status = "stopped"
            state.stop_reason = "interrupt_send"
            state.observations.append(
                {
                    "kind": "control",
                    "turn_index": state.turn_count,
                    "status": "interrupted",
                    "tool": action,
                }
            )
            break
        if state.interrupted:
            state.status = "stopped"
            state.stop_reason = "interrupted"
            break
    else:
        state.status = "max_turns"
        state.stop_reason = "max_turns"

    return state
