"""Nanobot-style agent loop specialized for single-equipment deep research."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from equipment_deep_research.deep_runtime.capabilities import load_capability_registry
from equipment_deep_research.deep_runtime.channel import (
    InboundMessage,
    MessageBus,
    MessageBusClosed,
    OutboundMessage,
)
from equipment_deep_research.deep_runtime.commands import command_question, parse_slash_command
from equipment_deep_research.deep_runtime.conductor import resolve_turn_plan
from equipment_deep_research.deep_runtime.identity import IDENTITY_NAME, IDENTITY_SKILL
from equipment_deep_research.deep_runtime.planner import inbound_from_payload, plan_turn
from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime
from equipment_deep_research.deep_runtime.runner import (
    _stop_requested,
    emit_runtime_checkpoint,
    run_planned_tools,
)
from equipment_deep_research.deep_runtime.state import TurnState
from equipment_deep_research.deep_runtime.workspace import DeepWorkspace
from equipment_deep_research.deep_runtime.memory_runtime import restore_workspace_context, consolidate_workspace_memory
from equipment_deep_research.deep_runtime.subagents import (
    LightweightSubagentRunner,
    tasks_from_payload,
)
from equipment_deep_research.deep_runtime.tool_registry import ToolRegistry, build_tool_registry
from equipment_deep_research.harness.event_bus import sanitize_runtime_payload


def _attach_identity(payload: dict[str, Any]) -> dict[str, Any]:
    parent = payload.get("deep_parent_context")
    parent = dict(parent) if isinstance(parent, Mapping) else {}
    if not str(parent.get("identity") or "").strip():
        parent["identity"] = IDENTITY_SKILL
    payload["deep_parent_context"] = parent
    return payload


_CANONICAL_IDENTITY_FIELDS = (
    "source_equipment_identity",
    "primary_equipment_identity",
    "equipment_form",
    "name",
    "title",
    "card_binding_id",
    "hypothesis_id",
    "capability_id",
)


def _canonical_identity_projection(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return the immutable source-equipment identity for isolated probes.

    The parent context can contain a large, provider-specific snapshot.  A
    subagent only needs the small identity projection below: it may propose a
    new innovation variant, but it must not silently switch the source
    equipment, card lineage, or target to another object.
    """

    parent = payload.get("deep_parent_context")
    parent = parent if isinstance(parent, Mapping) else {}
    candidates: list[Any] = [
        payload.get("equipment_identity"),
        payload.get("canonical_identity"),
        payload.get("source_equipment"),
        parent.get("equipment_identity"),
        parent.get("canonical_identity"),
        parent.get("source_equipment"),
        parent.get("candidate"),
        parent.get("canonical_candidate"),
    ]
    projection: dict[str, str] = {}
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            for field in _CANONICAL_IDENTITY_FIELDS:
                value = " ".join(str(candidate.get(field) or "").split()).strip()
                if value and field not in projection:
                    projection[field] = value[:240]
        elif isinstance(candidate, str) and candidate.strip():
            projection.setdefault("source_equipment_identity", " ".join(candidate.split())[:240])
    # Top-level fields are authoritative when a host has already resolved a
    # server-owned candidate; client-supplied nested context cannot replace
    # those values.
    for field in _CANONICAL_IDENTITY_FIELDS:
        value = " ".join(str(payload.get(field) or "").split()).strip()
        if value:
            projection[field] = value[:240]
    return projection


def _workspace_from_payload(payload: Mapping[str, Any]) -> DeepWorkspace | None:
    """Resolve the optional external workspace carried by a turn payload.

    The SQL dialogue ledger remains authoritative for existing API callers.
    A worker that supplies ``workspace_path`` opts into the portable nanobot
    state space; callers can also pass an already opened ``DeepWorkspace``.
    ``workspace_required`` makes a failed bind visible instead of silently
    degrading to in-memory state.
    """

    parent = payload.get("deep_parent_context")
    parent = parent if isinstance(parent, Mapping) else {}
    identity = payload.get("equipment_identity")
    if not isinstance(identity, Mapping):
        identity = payload.get("canonical_identity")
    if not isinstance(identity, Mapping):
        identity = parent.get("equipment_identity")
    if not isinstance(identity, Mapping):
        identity = parent.get("canonical_identity")
    requested_identity = dict(identity) if isinstance(identity, Mapping) else {}
    requested_workspace_id = str(
        payload.get("workspace_id") or parent.get("workspace_id") or ""
    ).strip()
    existing = payload.get("deep_workspace")
    if isinstance(existing, DeepWorkspace):
        if requested_workspace_id and existing.workspace_id != requested_workspace_id:
            raise ValueError("workspace identity namespace mismatch")
        if requested_identity:
            existing.assert_identity(requested_identity)
        return existing
    raw_path = (
        payload.get("workspace_path")
        or payload.get("deep_workspace_path")
        or parent.get("workspace_path")
    )
    if not str(raw_path or "").strip():
        return None
    try:
        return DeepWorkspace.open(
            str(raw_path),
            workspace_id=requested_workspace_id,
            identity=requested_identity or None,
        )
    except ValueError as exc:
        # A bound workspace must never be reused for another equipment
        # identity.  This is a hard lineage invariant even when the caller
        # did not mark the optional file store as required.
        detail = str(exc).lower()
        if "identity" in detail or "namespace" in detail:
            raise
        if bool(payload.get("workspace_required")):
            raise
        return None
    except Exception:
        if bool(payload.get("workspace_required")):
            raise
        return None


def _record_workspace_turn(
    workspace: DeepWorkspace,
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    """Persist one complete turn when the caller explicitly enables it."""

    if not bool(payload.get("workspace_record_turn")):
        return
    session_id = str(
        payload.get("session_id")
        or (
            payload.get("deep_parent_context", {}).get("session_id", "")
            if isinstance(payload.get("deep_parent_context"), Mapping)
            else ""
        )
        or ""
    ).strip()
    if not session_id:
        return
    branch_id = str(payload.get("branch_id") or "main").strip() or "main"
    question = str(payload.get("workspace_user_content") or payload.get("question") or payload.get("topic") or "").strip()
    if question:
        workspace.sessions.append_message(
            session_id,
            role="user",
            content=question,
            branch_id=branch_id,
        )
    visible = result.get("visible_summary")
    if isinstance(visible, Sequence) and not isinstance(visible, (str, bytes)):
        answer = "\n".join(str(item).strip() for item in visible if str(item).strip())
    else:
        answer = str(visible or "").strip()
    assistant_message = None
    if answer:
        assistant_message = workspace.sessions.append_message(
            session_id,
            role="assistant",
            content=answer,
            branch_id=branch_id,
            metadata={"runtime": result.get("runtime", {}), "research_result": sanitize_runtime_payload(result, max_string_length=12000)},
        )
    previous = {}
    try:
        parent = payload.get("deep_parent_context")
        parent = parent if isinstance(parent, Mapping) else {}
        loaded = parent.get("working_memory")
        if not isinstance(loaded, Mapping):
            loaded = payload.get("working_memory")
        if not isinstance(loaded, Mapping):
            loaded = workspace.sessions.load_working_memory(session_id, branch_id=branch_id)
        if isinstance(loaded, Mapping):
            previous = dict(loaded)
    except Exception:
        previous = {}
    from equipment_deep_research.domain.conversation import build_working_memory

    checkpoint = build_working_memory(
        answer=result,
        question=question,
        branch_id=branch_id,
        previous=previous,
        source_message_id=str(assistant_message.get("message_id", "")) if assistant_message else "",
        source_sequence=int(assistant_message.get("sequence", 0)) if assistant_message else 0,
    )
    workspace.sessions.save_working_memory(
        session_id,
        checkpoint,
        branch_id=branch_id,
    )

    # Journal only the semantic result.  The full transcript is already in
    # sessions/<id>.jsonl; this keeps Dream input small and copyable.
    workspace.memory.append_history(
        "research checkpoint: " + json.dumps(checkpoint, ensure_ascii=False),
        session_id=session_id,
        branch_id=branch_id,
        role="checkpoint",
    )


def _apply_command_intent(payload: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_slash_command(payload.get("question") or payload.get("topic"))
    if not parsed.name:
        return payload
    payload["question"] = command_question(parsed)
    if parsed.name == "card":
        payload["authoring_requested"] = True
    elif parsed.name in {"memory", "help", "diverge", "challenge", "synthesize"}:
        payload["authoring_requested"] = False
    if parsed.name in {"diverge", "challenge", "synthesize"}:
        payload["deep_research_mode"] = parsed.name
    return payload


def _assemble(state: TurnState) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    result_order = list(reversed(state.completed_tools))
    result_order.extend(
        name
        for name in (
            "author_s6",
            "synthesize",
            "challenge",
            "diverge",
            "deepen",
            "research_council",
            "inspect_memory",
            "help",
        )
        if name not in result_order
    )
    for name in result_order:
        candidate = state.results.get(name)
        if isinstance(candidate, Mapping) and candidate:
            result = dict(candidate)
            break
    if result is None:
        result = {
            "visible_summary": ["本轮未执行研究工具。"],
            "concept_directions": [],
            "capability_card_draft": {},
            "finalization_status": "analysis_only",
            "quality_gate": {
                "publishable": False,
                "direction_ready": False,
                "block_reasons": ["本轮未执行研究工具"],
            },
            "orchestration": {
                "pattern": "equipment_deep_runtime",
                "rounds": 0,
                "phases": [],
                "requested_agents": 0,
                "completed_divergence_agents": 0,
                "degraded": True,
                "quality_gate_passed": False,
                "finalization_status": "analysis_only",
            },
        }
    # S6 columns are independent durable outputs.  A late runtime adapter or
    # replay may assemble an older wrapper with an empty field even though the
    # authoritative author_s6 observation already contains that column. Merge
    # only non-empty values so completion is monotonic and no finished column
    # can be erased by a later empty result.
    merged_draft = result.get("capability_card_draft")
    merged_draft = dict(merged_draft) if isinstance(merged_draft, Mapping) else {}
    for tool_name in ("author_s6", *reversed(state.completed_tools)):
        candidate = state.results.get(tool_name)
        if not isinstance(candidate, Mapping):
            continue
        draft = candidate.get("capability_card_draft")
        if not isinstance(draft, Mapping):
            continue
        for key in (
            "overview",
            "technology_implementation",
            "operational_process",
            "capability_effects",
            "winning_logic",
        ):
            if not str(merged_draft.get(key, "") or "").strip() and str(
                draft.get(key, "") or ""
            ).strip():
                merged_draft[key] = draft[key]
    if merged_draft:
        result["capability_card_draft"] = merged_draft
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
        "status": state.status,
        "turn_count": state.turn_count,
        "tool_call_count": state.tool_call_count,
        "max_turns": state.max_turns,
        "max_tool_calls": state.max_tool_calls,
        "stop_reason": state.stop_reason,
        "observation_count": len(state.observations),
        "policy_trace": [dict(item) for item in state.policy_trace],
        "tool_registry": (
            state.tool_registry.public_payload()
            if state.tool_registry is not None
            else {}
        ),
        "provider": (
            state.provider_runtime.snapshot()
            if state.provider_runtime is not None
            else {}
        ),
        "subagents": {
            "requested": len(state.subagent_results),
            "completed": sum(
                1
                for item in state.subagent_results
                if str(item.get("status", "")) == "completed"
            ),
            "results": list(state.subagent_results)[:4],
        },
    }
    if state.subagent_results:
        result["subagent_results"] = list(state.subagent_results)[:4]
    safe = sanitize_runtime_payload(result, max_string_length=12000)
    return dict(safe) if isinstance(safe, Mapping) else {}


def _runtime_limit(payload: Mapping[str, Any], key: str, default: int) -> int:
    budget = payload.get("deep_runtime_budget")
    budget = budget if isinstance(budget, Mapping) else {}
    raw = budget.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, 12))


async def _run_deep_research_turn(
    host: Any, payload: Mapping[str, Any]
) -> dict[str, Any]:
    governed = dict(payload)
    workspace = _workspace_from_payload(governed)
    restored_context = {"restored": False}
    if workspace is not None:
        # Keep the file handle in the runtime closure only.  Model payloads
        # must never receive a workspace object or a host filesystem path.
        governed["deep_workspace_id"] = workspace.workspace_id
        try:
            restored_context = restore_workspace_context(workspace, governed)
        except Exception:
            if governed.get("workspace_required"):
                raise
            restored_context = {"restored": False, "error": "workspace context unavailable"}
        governed["workspace_user_content"] = str(governed.get("question") or governed.get("topic") or "")
    governed.pop("deep_workspace", None)
    governed.pop("workspace_path", None)
    governed.pop("deep_workspace_path", None)
    governed.pop("deep_workspace_state_dir", None)
    # Transport and execution objects are dependency-injected at the runtime
    # boundary.  Remove them before model payloads are assembled so channel
    # queues, callbacks and provider instances never enter model context.
    message_bus = governed.pop("message_bus", None)
    channel_message = governed.pop("inbound_message", None)
    if not isinstance(channel_message, InboundMessage):
        channel_message = None
    injected_provider_runtime = governed.pop("provider_runtime", None)
    if not isinstance(injected_provider_runtime, ProviderRuntime):
        injected_provider_runtime = None
    injected_subagent_runner = governed.pop("subagent_runner", None)
    injected_tool_registry = governed.pop("tool_registry", None)
    persistent_mcp_host = governed.pop("persistent_mcp_host", None)
    # Compatibility marker used by early host integrations.  Executable
    # mounts now belong entirely to Persistent/ReloadingMCPHost and are never
    # copied into model-visible turn state.
    governed.pop("mcp_mounts", None)
    mcp_required = bool(governed.pop("mcp_required", False))
    governed.pop("external_tool_observations", None)
    if not isinstance(injected_tool_registry, ToolRegistry):
        injected_tool_registry = None
    enable_subagents = bool(governed.pop("enable_subagents", False))
    requested_subagent_tasks = governed.pop("subagent_tasks", None)
    command_inbound = inbound_from_payload(governed)
    governed = _apply_command_intent(governed)
    governed = _attach_identity(governed)
    canonical_identity = _canonical_identity_projection(governed)
    if canonical_identity:
        parent_identity = governed.get("deep_parent_context")
        parent_identity = dict(parent_identity) if isinstance(parent_identity, Mapping) else {}
        parent_identity["canonical_equipment_identity"] = canonical_identity
        parent_identity["identity_lock"] = (
            "单装备身份锁：所有候选必须是该源装备的创新变体；不得替换源装备或跨装备合并。"
        )
        governed["deep_parent_context"] = parent_identity
    # Rebuild the inbound turn after expanding slash commands so downstream
    # tools receive the command's procedural meaning plus explicit arguments.
    # Preserve the original parsed command and authoring decision because the
    # expanded natural-language question is intentionally no longer a slash
    # command and must not weaken deterministic routing or the S6 gate.
    inbound = replace(
        inbound_from_payload(governed),
        command=command_inbound.command,
        args=command_inbound.args,
        authoring_requested=command_inbound.authoring_requested,
        card_intent=command_inbound.card_intent,
    )
    governed["authoring_requested"] = inbound.authoring_requested
    capability_registry = load_capability_registry()
    workspace_capabilities = {"loaded": False}
    if workspace is not None:
        try:
            capability_registry = capability_registry.with_workspace(workspace)
            preferences = capability_registry.workspace_config
            budget = preferences.get("deep_runtime_budget", {})
            host_budget = governed.get("deep_runtime_budget")
            governed["deep_runtime_budget"] = {
                **budget,
                **(dict(host_budget) if isinstance(host_budget, Mapping) else {}),
            }
            workspace_capabilities = {"loaded": True, "skill_ids": [
                skill.skill_id for skill in capability_registry.skills.values() if skill.source == "workspace"
            ]}
        except (OSError, ValueError):
            if governed.get("workspace_required"):
                raise
            workspace_capabilities = {"loaded": False, "error": "workspace capabilities unavailable"}
    parent = governed.get("deep_parent_context")
    parent = dict(parent) if isinstance(parent, Mapping) else {}
    if "active_skill_ids" in parent:
        requested = parent["active_skill_ids"]
    elif "active_skill_ids" in governed:
        requested = governed["active_skill_ids"]
    else:
        requested = getattr(capability_registry, "workspace_config", {}).get("active_skill_ids", [])
    if not isinstance(requested, (list, tuple)):
        requested = []
    preliminary = capability_registry.select_skills(
        text=inbound.content,
        plan=plan_turn(inbound),
        requested=requested,
    )
    governed["deep_skill_catalog"] = [
        {
            "skill_id": item.skill_id,
            "description": item.description,
            "applies_to": list(item.applies_to),
        }
        for item in preliminary
    ]
    plan, conductor = await resolve_turn_plan(
        host,
        inbound,
        governed,
        provider_runtime=injected_provider_runtime,
    )
    selected = capability_registry.select_skills(
        text=inbound.content,
        plan=plan,
        requested=requested,
    )
    active_skills = [item.runtime_payload() for item in selected]
    parent["active_skill_ids"] = [item.skill_id for item in selected]
    parent["active_skills"] = active_skills
    governed["deep_parent_context"] = parent
    governed["active_skill_ids"] = list(parent["active_skill_ids"])
    governed["active_skills"] = active_skills
    public_capabilities = capability_registry.public_payload()
    tool_registry = injected_tool_registry or build_tool_registry(capability_registry=capability_registry)
    if injected_tool_registry is not None:
        from equipment_deep_research.deep_runtime.tools import TOOL_HANDLERS

        tool_registry.register_builtin_handlers(TOOL_HANDLERS)
    provider_runtime = injected_provider_runtime or ProviderRuntime.from_host(host)
    subagent_runner = injected_subagent_runner
    if subagent_runner is None and (enable_subagents or requested_subagent_tasks is not None):
        subagent_runner = (
            LightweightSubagentRunner(provider_runtime)
            if provider_runtime is not None
            else None
        )
    state = TurnState(
        host=host,
        payload=governed,
        inbound=inbound,
        plan=plan,
        conductor=conductor,
        active_skills=active_skills,
        skill_prompt=capability_registry.prompt_context(selected),
        capabilities={
            "plugin_ids": [
                str(item.get("plugin_id", ""))
                for item in public_capabilities.get("plugins", [])
                if isinstance(item, Mapping) and item.get("enabled")
            ],
            "mcp_servers": [
                str(item.get("server_id", ""))
                for item in public_capabilities.get("mcp_servers", [])
                if isinstance(item, Mapping) and str(item.get("server_id", "")).strip()
            ],
            "tool_names": list(tool_registry.names),
            "tool_registry": tool_registry.public_payload(),
        },
        tool_registry=tool_registry,
        provider_runtime=provider_runtime,
        subagent_runner=subagent_runner,
        workspace=workspace,
        max_turns=_runtime_limit(governed, "max_turns", 4),
        max_tool_calls=_runtime_limit(governed, "max_tool_calls", 4),
    )
    if subagent_runner is not None:
        canonical_identity = _canonical_identity_projection(governed)
        task_context = {
            "question": inbound.content,
            "candidate_names": [
                str(item.get("name", ""))[:160]
                for item in (inbound.working_memory.get("candidate_directions", [])
                             if isinstance(inbound.working_memory, Mapping)
                             and isinstance(inbound.working_memory.get("candidate_directions", []), list)
                             else [])[:3]
                if isinstance(item, Mapping) and str(item.get("name", "")).strip()
            ],
            "focus": governed.get("deep_research_focus", {}),
            "canonical_equipment_identity": canonical_identity,
            "identity_lock": (
                "只允许围绕 canonical_equipment_identity 对应的同一源装备提出创新变体；"
                "不得创建、替换或比较另一个源装备身份。"
            ),
        }
        tasks = tasks_from_payload(
            requested_subagent_tasks,
            question=inbound.content,
            context=task_context,
        )
        # ``enable_subagents`` is intentionally opt-in.  A caller can request
        # the default two orthogonal probes for /diverge without exposing a
        # second orchestration graph to ordinary follow-up turns.
        if not tasks and enable_subagents and inbound.command == "diverge":
            tasks = tasks_from_payload(True, question=inbound.content, context=task_context)
        if tasks:
            emit_progress = getattr(host, "_emit_deep_dialogue_progress", None)
            if callable(emit_progress):
                for task in tasks:
                    try:
                        emit_progress({
                            "event_type": "deep_agent_started",
                            "stage": "s3_divergence",
                            "status": "running",
                            "progress": 0.19,
                            "kind": "summary",
                            "round": "lightweight_probe",
                            "role": task.role,
                            "axis": task.task_id,
                            "agent_id": f"deep_probe_{task.task_id}",
                            "parallel": True,
                            "parallel_group": "lightweight_probes",
                            "parallelism": len(tasks),
                            "summary_text": f"{task.role}正在执行有界正交探针。",
                        })
                    except Exception:
                        pass
            subagent_results = await subagent_runner.run_many(tasks)
            state.subagent_results = [item.to_public() for item in subagent_results]
            if callable(emit_progress):
                for item in subagent_results:
                    finding = item.finding
                    if isinstance(finding, Mapping):
                        finding = finding.get("summary") or finding.get("finding") or ""
                    text = " ".join(str(finding or "").split())[:600]
                    try:
                        emit_progress({
                            "event_type": (
                                "deep_agent_completed"
                                if item.status == "completed"
                                else "deep_agent_failed"
                            ),
                            "stage": "s3_divergence",
                            "status": item.status,
                            "progress": 0.20,
                            "kind": "answer" if text else "summary",
                            "round": "lightweight_probe",
                            "role": item.role,
                            "axis": item.task_id,
                            "agent_id": f"deep_probe_{item.task_id}",
                            "parallel": True,
                            "parallel_group": "lightweight_probes",
                            "parallelism": len(tasks),
                            "text": text,
                            "summary_text": text or f"{item.role}未形成可合并发现。",
                        })
                    except Exception:
                        pass
            governed["subagent_context"] = [
                {
                    "role": item.role,
                    "status": item.status,
                    "finding": item.finding,
                    "assumptions": list(item.assumptions),
                    "next_probe": item.next_probe,
                }
                for item in subagent_results
                if item.status == "completed"
            ]
            state.observations.extend(
                {
                    "kind": "subagent_result",
                    "turn_index": 0,
                    "tool": "subagent",
                    "status": item.status,
                    "task_id": item.task_id,
                }
                for item in subagent_results
            )
    mcp_lease_active = False
    if persistent_mcp_host is not None:
        mount_registry = getattr(persistent_mcp_host, "mount_registry", None)
        if not callable(mount_registry):
            raise TypeError("persistent MCP host has no mount_registry")
        try:
            await mount_registry(tool_registry)
            mcp_lease_active = True
            # The state snapshot is constructed before transport I/O so core
            # planning remains cheap. Refresh it after a successful lease so
            # the runner/model sees the actual ready, allowlisted tools.
            state.capabilities["tool_names"] = list(tool_registry.names)
            state.capabilities["tool_registry"] = tool_registry.public_payload()
            state.capabilities["mcp_servers"] = [
                item["server_id"]
                for item in tool_registry.public_payload().get("mcp_servers", [])
                if isinstance(item, Mapping) and item.get("status") in {"ready", "registered"}
            ]
        except asyncio.CancelledError:
            raise
        except Exception:
            if mcp_required:
                raise
            # Research can continue when an optional external source is down.
            # Preserve the gap as an observation so synthesis cannot silently
            # treat the missing probe as successful evidence.
            state.observations.append({
                "kind": "mcp_host_unavailable",
                "turn_index": 0,
                "tool": "mcp_host",
                "status": "advisory_gap",
            })
            state.capabilities["mcp_status"] = "unavailable"
            state.capabilities["tool_names"] = list(tool_registry.names)
            state.capabilities["tool_registry"] = tool_registry.public_payload()
    try:
        await run_planned_tools(state)
    finally:
        if mcp_lease_active:
            unmount_registry = getattr(persistent_mcp_host, "unmount_registry", None)
            if callable(unmount_registry):
                await unmount_registry(tool_registry)
    result = _assemble(state)
    if workspace is not None:
        try:
            can_record = state.status in {"completed", "max_turns", "max_tool_calls"}
            if can_record and await _stop_requested(state):
                can_record = False
                state.status = "stopped"
                state.stop_reason = "stop_requested"
                result = _assemble(state)
                result["finalization_status"] = "partial"
            dream = {"status": "skipped"}
            if can_record and governed.get("workspace_record_turn") and any(
                name in {"deepen", "diverge", "challenge", "synthesize", "research_council"}
                for name in state.completed_tools
            ):
                dream = await consolidate_workspace_memory(state)
                if await _stop_requested(state):
                    can_record = False
                    state.status = "stopped"
                    state.stop_reason = "stop_requested"
                    result = _assemble(state)
                    result["finalization_status"] = "partial"
            if can_record:
                await emit_runtime_checkpoint(state, "tools_completed", assistant_result=result)
                _record_workspace_turn(workspace, governed, result)
            result["workspace"] = {
                "workspace_id": workspace.workspace_id,
                # Keep the state location portable and avoid exposing the
                # worker's local filesystem path through API/SSE projections.
                "state_dir": workspace.state_dir.relative_to(workspace.root).as_posix(),
                "recorded": can_record and bool(governed.get("workspace_record_turn")),
                "context": restored_context,
                "capabilities": workspace_capabilities,
                "dream": dream,
                "memory_cursor": workspace.memory.latest_cursor(),
                "dream_cursor": workspace.memory.last_dream_cursor(),
            }
        except Exception as exc:
            if type(exc).__name__ in {"_DeepJobCancelled", "_DeepJobInterrupted"}:
                raise
            if bool(governed.get("workspace_required")):
                raise
            result["workspace"] = {
                "workspace_id": workspace.workspace_id,
                "state_dir": ".deep_research",
                "recorded": False,
                "error": "workspace persistence failed",
            }
    await emit_runtime_checkpoint(
        state,
        "final_response",
        assistant_result=result,
    )
    if isinstance(message_bus, MessageBus) and channel_message is not None:
        try:
            await message_bus.publish_outbound(
                OutboundMessage(
                    channel=channel_message.channel,
                    chat_id=channel_message.chat_id,
                    content="\n".join(str(item) for item in result.get("visible_summary", [])[:3]),
                    correlation_id=channel_message.message_id,
                    reply_to=channel_message.message_id,
                    event_type="deep_research.completed",
                    payload=result,
                    metadata={"session_key": channel_message.session_key},
                )
            )
        except MessageBusClosed:
            # A channel may disconnect after the core committed its result;
            # transport closure must not turn a successful research turn into
            # a provider failure.
            pass
    return result


def run_deep_research_turn(host: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Synchronous entrypoint matching the existing dialogue host contract."""

    return asyncio.run(_run_deep_research_turn(host, payload))


async def run_deep_research_turn_async(
    host: Any, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Async entrypoint for channel workers and WebSocket gateways."""

    return await _run_deep_research_turn(host, payload)


_CHANNEL_RESEARCH_HINT_FIELDS = (
    "query",
    "active_skill_ids",
    "deep_research_focus",
    "deep_research_mode",
    "enable_subagents",
    "subagent_tasks",
)


async def run_deep_research_message(
    host: Any,
    bus: MessageBus,
    message: InboundMessage,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one bus message through the same core used by HTTP callers.

    Channel adapters only construct ``InboundMessage``.  Canonical target
    binding, session memory and S6 authorization remain in the host payload;
    this helper merely carries the route and correlation identity across the
    transport boundary.
    """

    if not isinstance(bus, MessageBus):
        raise TypeError("bus must be a MessageBus")
    if not isinstance(message, InboundMessage):
        raise TypeError("message must be an InboundMessage")
    # Adapter payloads only carry research hints.  Identity, persisted memory,
    # S6 authorization and in-process dependencies come from the trusted host,
    # including when the host deliberately omits an optional field.
    request = {
        key: message.payload[key]
        for key in _CHANNEL_RESEARCH_HINT_FIELDS
        if key in message.payload
    }
    request.update(dict(payload or {}))
    request.update(
        {
            "question": message.content,
            "channel": message.channel,
            "sender_id": message.sender_id,
            "chat_id": message.chat_id,
            "session_key": message.session_key,
            "inbound_message": message,
            "message_bus": bus,
        }
    )
    return await _run_deep_research_turn(host, request)
