"""Stateful task harness around the domain-free agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from hashlib import sha256
import inspect
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any, cast

from equipment_deep_research.domain.messages import (
    AgentExecutionResult,
    TaskEnvelope,
    TurnSnapshot,
)
from equipment_deep_research.domain.models import new_stable_id, now_iso
from equipment_deep_research.domain.proposals import (
    DomainWriteProposal,
    TraceProposal,
    freeze_plain,
    thaw_plain,
)
from equipment_deep_research.harness.agent_loop import (
    AgentLoop,
    AgentLoopConfig,
    AgentLoopEvent,
    AgentLoopResult,
    TurnSnapshotInput,
)
from equipment_deep_research.harness.budget import Budget
from equipment_deep_research.harness.event_bus import (
    EventBus,
    sanitize_runtime_payload,
)
from equipment_deep_research.harness.events import RuntimeEvent
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.providers.base import ModelMessage, ModelProvider
from equipment_deep_research.tools.definitions import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)
from equipment_deep_research.tools.permissions import ToolAuthorizationPolicy


HarnessEventCallback = Callable[[RuntimeEvent], None | Awaitable[None]]

_LONG_ERROR_LIMIT = 512
_OBJECT_ID_FIELDS = {
    "ResearchProblem": "problem_id",
    "EvidenceCard": "evidence_id",
    "BaselineFindingPacket": "packet_id",
    "RecallRequest": "recall_id",
    "AgentRecommendation": "recommendation_id",
    "WinningMechanismStageOutput": "stage_id",
    "CapabilityImageItem": "capability_id",
    "AuditResult": "audit_id",
    "ResearchReport": "report_id",
}


class AgentHarness:
    """Execute one task with snapshots, budgets, authorization, and savepoints."""

    def __init__(
        self,
        provider: ModelProvider,
        tools: Sequence[ToolDefinition] | Mapping[str, ToolDefinition],
        store: Any,
        *,
        sessions_root: str | Path,
        loop: AgentLoop | None = None,
        model_name: str = "gpt-5.5",
        model_options: Mapping[str, Any] | None = None,
        authorization_policy: ToolAuthorizationPolicy | None = None,
        on_event: HarnessEventCallback | None = None,
        event_bus: EventBus | None = None,
        session_store_factory: Callable[[str, Path], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.store = store
        self.sessions_root = Path(sessions_root)
        self.loop = loop or AgentLoop()
        self.model_name = str(model_name)
        self.model_options = cast(
            Mapping[str, Any], freeze_plain(model_options or {})
        )
        self.authorization_policy = authorization_policy or ToolAuthorizationPolicy.default()
        self.event_bus = event_bus or EventBus()
        self._session_store_factory = session_store_factory
        self._monotonic = monotonic
        self._tools = _normalize_tools(tools)
        self._state_lock = Lock()
        self._pending_listener_awaitables: list[Awaitable[Any]] = []
        self._async_listener_error_count = 0
        self._next_turn_tools: tuple[str, ...] | None = None
        self._executing = False
        self.last_session_store: JsonlSessionStore | None = None
        self.last_session_path: Path | None = None
        if on_event is not None:
            self.on_event(on_event)

    @property
    def listener_error_count(self) -> int:
        with self._state_lock:
            return self.event_bus.listener_error_count + self._async_listener_error_count

    def on_event(self, callback: HarnessEventCallback) -> Callable[[], None]:
        if not callable(callback):
            raise TypeError("event callback must be callable")

        def bus_listener(event: RuntimeEvent) -> None:
            response = callback(event)
            if inspect.isawaitable(response):
                with self._state_lock:
                    self._pending_listener_awaitables.append(response)

        return self.event_bus.subscribe(
            bus_listener,
            categories={"agent_harness"},
        )

    def set_next_turn_tools(self, tool_names: Sequence[str]) -> None:
        names = tuple(str(name) for name in tool_names)
        if len(names) != len(set(names)):
            raise ValueError("next-turn tool names must be unique")
        with self._state_lock:
            self._next_turn_tools = names

    async def execute(self, task: TaskEnvelope) -> AgentExecutionResult:
        if not isinstance(task, TaskEnvelope):
            raise TypeError("task must be a TaskEnvelope")
        self._begin_execution()
        execution_id = new_stable_id("execution")
        try:
            if self._session_store_factory is None:
                session = JsonlSessionStore(
                    f"{execution_id}.jsonl",
                    root_dir=self.sessions_root,
                )
            else:
                session = self._session_store_factory(
                    f"{execution_id}.jsonl",
                    self.sessions_root,
                )
        except BaseException:
            self._end_execution()
            raise
        self.last_session_store = session
        self.last_session_path = session.path

        snapshots: list[TurnSnapshot] = []
        output_refs: list[str] = []
        evidence_ids: list[str] = []
        checkpoint_id: str | None = None
        committed_turns: set[int] = set()
        commit_attempted: set[int] = set()
        denied_turns: set[int] = set()
        pending_domains: dict[int, list[DomainWriteProposal]] = {}
        pending_traces: dict[int, list[TraceProposal]] = {}
        tool_call_ids: dict[int, list[str]] = {}
        core_error: BaseException | None = None
        tool_permission_errors: list[PermissionError] = []
        budget: Budget | None = None
        terminal_recorded = False

        def result(status: str, error: str | None = None) -> AgentExecutionResult:
            return AgentExecutionResult(
                execution_id=execution_id,
                task_id=task.task_id,
                agent_id=task.target_agent_id,
                status=status,
                output_refs=tuple(output_refs),
                evidence_ids=tuple(evidence_ids),
                checkpoint_id=checkpoint_id,
                error=error,
                snapshots=tuple(snapshots),
            )

        def append_session(event_type: str, payload: Mapping[str, Any]) -> None:
            record = sanitize_runtime_payload(
                {
                "event_type": event_type,
                "execution_id": execution_id,
                "task_id": task.task_id,
                "agent_id": task.target_agent_id,
                "created_at": now_iso(),
                "schema_version": "1.0",
                    **dict(payload),
                },
                max_string_length=self.event_bus.max_string_length,
            )
            session.append(cast(Mapping[str, Any], record))

        async def emit_external(event_type: str, payload: Mapping[str, Any]) -> None:
            await self._publish_external(
                RuntimeEvent(
                    category="agent_harness",
                    event_type=event_type,
                    run_id=task.run_id,
                    payload=payload,
                )
            )

        def commit_batch(
            turn_index: int,
            domains: Sequence[DomainWriteProposal],
            traces: Sequence[TraceProposal],
        ) -> None:
            nonlocal checkpoint_id
            commit_attempted.add(turn_index)
            domain_batch = tuple(domains)
            trace_batch = tuple(traces)
            batch_hash = _hash_plain(
                {
                    "domain_proposals": [
                        proposal.to_plain() for proposal in domain_batch
                    ],
                    "trace_proposals": [proposal.to_plain() for proposal in trace_batch],
                }
            )
            append_session(
                "savepoint_pending",
                {
                    "turn_index": turn_index,
                    "batch_hash": batch_hash,
                    "domain_proposal_count": len(domain_batch),
                    "trace_proposal_count": len(trace_batch),
                },
            )
            committed_checkpoint_id = self.store.commit(domain_batch, trace_batch)
            checkpoint_id = committed_checkpoint_id
            committed_turns.add(turn_index)
            _extend_output_refs(output_refs, evidence_ids, domain_batch)
            try:
                append_session(
                    "savepoint",
                    {
                        "turn_index": turn_index,
                        "batch_hash": batch_hash,
                        "checkpoint_id": checkpoint_id,
                        "domain_proposal_refs": [
                            f"domain:{proposal.proposal_id}"
                            for proposal in domain_batch
                        ],
                        "trace_proposal_refs": [
                            f"trace:{proposal.proposal_id}" for proposal in trace_batch
                        ],
                    },
                )
            except BaseException as session_error:
                reconciliation = TraceProposal(
                    proposal_id=f"reconcile-{execution_id}-turn-{turn_index}",
                    event_type="session_write_failed",
                    actor=task.target_agent_id,
                    payload={
                        "execution_id": execution_id,
                        "task_id": task.task_id,
                        "turn_index": turn_index,
                        "session_event": "savepoint",
                        "batch_hash": batch_hash,
                        "committed_checkpoint_id": committed_checkpoint_id,
                        "recovery_status": "reconcile_required",
                        "error_type": type(session_error).__name__,
                    },
                )
                try:
                    checkpoint_id = self.store.commit((), (reconciliation,))
                except BaseException as reconciliation_error:
                    session_error.add_note(
                        "failed to persist session reconciliation marker: "
                        f"{type(reconciliation_error).__name__}"
                    )
                raise

        def commit_turn(turn_index: int, status: str) -> None:
            domains = tuple(pending_domains.get(turn_index, ()))
            traces = tuple(pending_traces.get(turn_index, ())) + (
                _harness_trace(
                    execution_id=execution_id,
                    task=task,
                    turn_index=turn_index,
                    status=status,
                    snapshot=_snapshot_for_turn(snapshots, turn_index),
                    tool_call_ids=tool_call_ids.get(turn_index, ()),
                ),
            )
            commit_batch(turn_index, domains, traces)

        def finalize_uncommitted_turn(status: str) -> None:
            if not snapshots:
                return
            turn_index = snapshots[-1].turn_index
            if turn_index in committed_turns or turn_index in commit_attempted:
                return
            trace = _harness_trace(
                execution_id=execution_id,
                task=task,
                turn_index=turn_index,
                status=status,
                snapshot=snapshots[-1],
                tool_call_ids=tool_call_ids.get(turn_index, ()),
            )
            commit_batch(turn_index, (), (trace,))

        try:
            append_session(
                "task_received",
                {
                    "run_id": task.run_id,
                    "round_index": task.round_index,
                    "parent_task_id": task.parent_task_id,
                    "objective_ref": _hash_plain(task.objective),
                    "research_question_refs": [
                        _hash_plain(question) for question in task.research_questions
                    ],
                    "context_refs": _reference_projection(task.context_refs),
                    "evidence_refs": _reference_projection(task.evidence_refs),
                    "allowed_tools": list(task.allowed_tools),
                    "object_read_scopes": list(task.object_read_scopes),
                    "object_write_scopes": list(task.object_write_scopes),
                    "budget": dict(task.budget),
                    "return_node": task.return_node,
                },
            )
            await emit_external("task_received", {"execution_id": execution_id})

            task.validate()
            if getattr(self.store, "run_id", task.run_id) != task.run_id:
                raise ValueError("task run_id does not match SqliteRunStore run_id")
            budget = Budget(task.budget, monotonic=self._monotonic)
            read_scopes = tuple(task.object_read_scopes)
            write_scopes = tuple(task.object_write_scopes)
            active_tool_names = tuple(task.allowed_tools)

            initial_messages = (_task_message(task),)

            def record_tool_permission_error(error: PermissionError) -> None:
                if not tool_permission_errors:
                    tool_permission_errors.append(error)

            async def prepare_turn(snapshot_input: TurnSnapshotInput) -> TurnSnapshotInput:
                nonlocal active_tool_names, core_error
                try:
                    next_tools = self._consume_next_turn_tools()
                    if next_tools is not None:
                        active_tool_names = next_tools
                    requested_tool_names = active_tool_names
                    authorized_definitions: list[ToolDefinition] = []
                    candidate_denials: list[PermissionError] = []
                    for name in requested_tool_names:
                        definition = self._tools.get(name)
                        if definition is None:
                            raise ValueError(f"unknown active tool: {name}")
                        try:
                            self.authorization_policy.authorize(
                                name,
                                active_tool_names=requested_tool_names,
                                object_read_scopes=read_scopes,
                                object_write_scopes=write_scopes,
                            )
                        except PermissionError as exc:
                            candidate_denials.append(exc)
                            continue
                        authorized_definitions.append(definition)

                    if requested_tool_names and not authorized_definitions:
                        raise PermissionError(
                            "; ".join(str(error) for error in candidate_denials)
                            or "no active tools are authorized"
                        )
                    active_tool_names = tuple(
                        definition.name for definition in authorized_definitions
                    )
                    selected = tuple(
                        _authorized_tool(
                            definition,
                            policy=self.authorization_policy,
                            active_tool_names=active_tool_names,
                            object_read_scopes=read_scopes,
                            object_write_scopes=write_scopes,
                            budget=budget,
                            on_permission_error=record_tool_permission_error,
                        )
                        for definition in authorized_definitions
                    )

                    if not budget.try_start_turn():
                        denied_turns.add(snapshot_input.turn_index)
                        return snapshot_input

                    prepared = TurnSnapshotInput(
                        turn_index=snapshot_input.turn_index,
                        messages=snapshot_input.messages,
                        tools=selected,
                        options=self.model_options,
                    )
                    frozen_snapshot = _turn_snapshot(
                        prepared,
                        model_name=self.model_name,
                        budget=budget,
                    )
                    snapshots.append(frozen_snapshot)
                    append_session(
                        "turn_snapshot",
                        frozen_snapshot.to_plain(),
                    )
                    await emit_external(
                        "turn_snapshot",
                        {
                            "turn_index": prepared.turn_index,
                            "snapshot_id": frozen_snapshot.snapshot_id,
                        },
                    )
                    return prepared
                except BaseException as exc:
                    if not isinstance(exc, asyncio.CancelledError):
                        core_error = exc
                    raise

            async def budget_exhausted(snapshot_input: TurnSnapshotInput) -> bool:
                return snapshot_input.turn_index in denied_turns

            async def on_loop_event(event: AgentLoopEvent) -> None:
                nonlocal core_error
                try:
                    turn_index = event.turn_index
                    if event.event_type == "turn_started":
                        assert turn_index is not None
                        await emit_external(
                            "turn_started",
                            {
                                "turn_index": turn_index,
                                "snapshot_id": _snapshot_for_turn(
                                    snapshots, turn_index
                                ).snapshot_id,
                            },
                        )
                    elif event.event_type == "assistant_message":
                        assert turn_index is not None and event.message is not None
                        message_ref = _message_ref(event.message)
                        append_session(
                            "assistant_message",
                            {
                                "turn_index": turn_index,
                                "message_ref": message_ref,
                                "role": event.message.role,
                                "tool_calls": [
                                    {
                                        "call_id": call.call_id,
                                        "name": call.name,
                                    }
                                    for call in event.message.tool_calls
                                ],
                            },
                        )
                        budget.record_tokens(_usage_tokens(event.message.metadata))
                        await emit_external(
                            "assistant_message",
                            {"turn_index": turn_index, "message_ref": message_ref},
                        )
                    elif event.event_type == "tool_result":
                        assert (
                            turn_index is not None
                            and event.tool_result is not None
                            and event.tool_call is not None
                        )
                        result_value = event.tool_result
                        pending_domains.setdefault(turn_index, []).extend(
                            result_value.domain_proposals
                        )
                        pending_traces.setdefault(turn_index, []).extend(
                            result_value.trace_proposals
                        )
                        tool_call_ids.setdefault(turn_index, []).append(
                            event.tool_call.call_id
                        )
                        proposal_refs = [
                            f"domain:{proposal.proposal_id}"
                            for proposal in result_value.domain_proposals
                        ] + [
                            f"trace:{proposal.proposal_id}"
                            for proposal in result_value.trace_proposals
                        ]
                        append_session(
                            "tool_result",
                            {
                                "turn_index": turn_index,
                                "call_id": event.tool_call.call_id,
                                "tool_name": event.tool_call.name,
                                "result_ref": _hash_plain(result_value.to_plain()),
                                "is_error": result_value.is_error,
                                "proposal_refs": proposal_refs,
                            },
                        )
                        await emit_external(
                            "tool_result",
                            {
                                "turn_index": turn_index,
                                "call_id": event.tool_call.call_id,
                                "tool_name": event.tool_call.name,
                                "is_error": result_value.is_error,
                            },
                        )
                    elif event.event_type == "turn_end":
                        assert turn_index is not None
                        commit_turn(turn_index, str(event.payload.get("status", "ended")))
                        await emit_external(
                            "turn_end",
                            {
                                "turn_index": turn_index,
                                "checkpoint_id": checkpoint_id,
                            },
                        )
                    elif event.event_type in {"loop_completed", "loop_failed"}:
                        await emit_external(event.event_type, event.payload)
                except BaseException as exc:
                    if not isinstance(exc, asyncio.CancelledError):
                        core_error = exc
                    raise

            configured_max_turns = (
                64 if budget.max_turns is None else max(1, budget.max_turns + 1)
            )
            loop_config = AgentLoopConfig(
                run_id=task.run_id,
                agent_id=task.target_agent_id,
                max_turns=configured_max_turns,
                options=self.model_options,
                permissions={
                    "allowed_tools": active_tool_names,
                    "object_read_scopes": read_scopes,
                    "object_write_scopes": write_scopes,
                },
                prepare_turn=prepare_turn,
                budget_exhausted=budget_exhausted,
                on_event=on_loop_event,
            )

            loop_result: AgentLoopResult
            timeout = budget.remaining_seconds()
            try:
                if timeout is None or timeout <= 0:
                    loop_result = await self.loop.run(
                        initial_messages,
                        self.provider,
                        tuple(self._tools.values()),
                        loop_config,
                    )
                else:
                    loop_result = await asyncio.wait_for(
                        self.loop.run(
                            initial_messages,
                            self.provider,
                            tuple(self._tools.values()),
                            loop_config,
                        ),
                        timeout=timeout,
                    )
            except TimeoutError:
                finalize_uncommitted_turn("budget_exhausted")
                append_session(
                    "task_completed",
                    {
                        "status": "budget_exhausted",
                        "checkpoint_id": checkpoint_id,
                    },
                )
                terminal_recorded = True
                await emit_external(
                    "task_completed",
                    {"status": "budget_exhausted", "checkpoint_id": checkpoint_id},
                )
                return result("budget_exhausted")

            if tool_permission_errors:
                raise tool_permission_errors[0]
            if isinstance(core_error, PermissionError):
                raise core_error
            if loop_result.status == "failed":
                finalize_uncommitted_turn("failed")
                error = _safe_error(
                    core_error or loop_result.error or "execution failed",
                    max_string_length=self.event_bus.max_string_length,
                )
                append_session(
                    "task_failed",
                    {
                        "status": "failed",
                        "checkpoint_id": checkpoint_id,
                        "error": "execution failed",
                        "error_type": _error_type(core_error),
                    },
                )
                terminal_recorded = True
                await emit_external("task_failed", {"status": "failed"})
                return result("failed", error)

            append_session(
                "task_completed",
                {
                    "status": loop_result.status,
                    "checkpoint_id": checkpoint_id,
                    "output_refs": output_refs,
                    "evidence_ids": evidence_ids,
                },
            )
            terminal_recorded = True
            await emit_external(
                "task_completed",
                {"status": loop_result.status, "checkpoint_id": checkpoint_id},
            )
            return result(loop_result.status)
        except asyncio.CancelledError as exc:
            try:
                finalize_uncommitted_turn("cancelled")
            except Exception as persistence_error:
                exc.add_note(
                    "failed to persist cancellation savepoint: "
                    f"{type(persistence_error).__name__}"
                )
            if not terminal_recorded:
                try:
                    append_session(
                        "task_cancelled",
                        {"status": "cancelled", "checkpoint_id": checkpoint_id},
                    )
                    await emit_external("task_cancelled", {"status": "cancelled"})
                except Exception as persistence_error:
                    exc.add_note(
                        "failed to persist task_cancelled: "
                        f"{type(persistence_error).__name__}"
                    )
            raise
        except PermissionError as exc:
            error = _safe_error(
                exc,
                max_string_length=self.event_bus.max_string_length,
            )
            if not terminal_recorded:
                try:
                    append_session(
                        "task_failed",
                        {
                            "status": "failed",
                            "checkpoint_id": checkpoint_id,
                            "error": "permission denied",
                            "error_type": type(exc).__name__,
                        },
                    )
                    await emit_external("task_failed", {"status": "failed"})
                except Exception as persistence_error:
                    exc.add_note(
                        "failed to persist permission denial: "
                        f"{type(persistence_error).__name__}"
                    )
            raise
        except Exception as exc:
            try:
                finalize_uncommitted_turn("failed")
            except Exception:
                pass
            error = _safe_error(
                exc,
                max_string_length=self.event_bus.max_string_length,
            )
            if not terminal_recorded:
                try:
                    append_session(
                        "task_failed",
                        {
                            "status": "failed",
                            "checkpoint_id": checkpoint_id,
                            "error": "execution failed",
                            "error_type": type(exc).__name__,
                        },
                    )
                    await emit_external("task_failed", {"status": "failed"})
                except Exception:
                    pass
            return result("failed", error)
        finally:
            self._end_execution()

    async def _publish_external(self, event: RuntimeEvent) -> None:
        self.event_bus.publish(event)
        while True:
            with self._state_lock:
                awaitables = tuple(self._pending_listener_awaitables)
                self._pending_listener_awaitables.clear()
            if not awaitables:
                return
            for awaitable in awaitables:
                try:
                    await awaitable
                except asyncio.CancelledError:
                    current_task = asyncio.current_task()
                    if current_task is not None and current_task.cancelling() > 0:
                        raise
                    with self._state_lock:
                        self._async_listener_error_count += 1
                except Exception:
                    with self._state_lock:
                        self._async_listener_error_count += 1

    def _consume_next_turn_tools(self) -> tuple[str, ...] | None:
        with self._state_lock:
            value = self._next_turn_tools
            self._next_turn_tools = None
            return value

    def _begin_execution(self) -> None:
        with self._state_lock:
            if self._executing:
                raise RuntimeError("AgentHarness.execute does not support concurrent tasks")
            self._executing = True

    def _end_execution(self) -> None:
        with self._state_lock:
            self._executing = False
            self._next_turn_tools = None


def _normalize_tools(
    tools: Sequence[ToolDefinition] | Mapping[str, ToolDefinition],
) -> dict[str, ToolDefinition]:
    values = tuple(tools.values()) if isinstance(tools, Mapping) else tuple(tools)
    if not all(isinstance(tool, ToolDefinition) for tool in values):
        raise TypeError("tools must contain only ToolDefinition values")
    names = [tool.name for tool in values]
    if len(names) != len(set(names)):
        raise ValueError("tool names must be unique")
    return {tool.name: tool for tool in values}


def _authorized_tool(
    definition: ToolDefinition,
    *,
    policy: ToolAuthorizationPolicy,
    active_tool_names: Sequence[str],
    object_read_scopes: Sequence[str],
    object_write_scopes: Sequence[str],
    budget: Budget,
    on_permission_error: Callable[[PermissionError], None],
) -> ToolDefinition:
    async def authorized_handler(
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        try:
            policy.authorize(
                call.name,
                active_tool_names=active_tool_names,
                object_read_scopes=object_read_scopes,
                object_write_scopes=object_write_scopes,
            )
            budget.record_tool_call()
            current_context = ToolExecutionContext(
                run_id=context.run_id,
                agent_id=context.agent_id,
                permissions={
                    "active_tool_names": list(active_tool_names),
                    "object_read_scopes": list(object_read_scopes),
                    "object_write_scopes": list(object_write_scopes),
                },
            )
            result = await definition.handler(call, current_context)
            if not isinstance(result, ToolResult):
                return cast(ToolResult, result)
            return policy.authorize_result(
                call.name,
                result,
                active_tool_names=active_tool_names,
                object_read_scopes=object_read_scopes,
                object_write_scopes=object_write_scopes,
                agent_id=current_context.agent_id,
                call_id=call.call_id,
            )
        except PermissionError as exc:
            on_permission_error(exc)
            raise

    return ToolDefinition(
        name=definition.name,
        description=definition.description,
        input_schema=definition.input_schema,
        handler=authorized_handler,
    )


def _task_message(task: TaskEnvelope) -> ModelMessage:
    return ModelMessage(
        role="user",
        content={
            "task_id": task.task_id,
            "objective": task.objective,
            "research_questions": list(task.research_questions),
            "context_refs": list(task.context_refs),
            "evidence_refs": list(task.evidence_refs),
            "return_contract": task.return_contract,
            "return_node": task.return_node,
        },
        metadata={"round_index": task.round_index},
    )


def _turn_snapshot(
    snapshot_input: TurnSnapshotInput,
    *,
    model_name: str,
    budget: Budget,
) -> TurnSnapshot:
    messages_plain = [message.to_plain() for message in snapshot_input.messages]
    return TurnSnapshot(
        message_refs=tuple(_hash_plain(message) for message in messages_plain),
        context_hash=_hash_plain(messages_plain),
        active_tool_names=tuple(tool.name for tool in snapshot_input.tools),
        model_name=model_name,
        model_options=snapshot_input.options,
        budget_remaining=budget.remaining(),
        turn_index=snapshot_input.turn_index,
    )


def _message_ref(message: ModelMessage) -> str:
    return _hash_plain(message.to_plain())


def _reference_projection(values: Sequence[str]) -> dict[str, Any]:
    return {
        "count": len(values),
        "refs": [_hash_plain(value) for value in values],
    }


def _hash_plain(value: Any) -> str:
    encoded = json.dumps(
        thaw_plain(freeze_plain(value)),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _snapshot_for_turn(
    snapshots: Sequence[TurnSnapshot], turn_index: int
) -> TurnSnapshot:
    for snapshot in reversed(snapshots):
        if snapshot.turn_index == turn_index:
            return snapshot
    raise RuntimeError(f"missing persisted snapshot for turn {turn_index}")


def _harness_trace(
    *,
    execution_id: str,
    task: TaskEnvelope,
    turn_index: int,
    status: str,
    snapshot: TurnSnapshot,
    tool_call_ids: Sequence[str],
) -> TraceProposal:
    return TraceProposal(
        proposal_id=f"harness-{execution_id}-turn-{turn_index}-{status}",
        event_type="harness_turn",
        actor=task.target_agent_id,
        payload={
            "execution_id": execution_id,
            "task_id": task.task_id,
            "turn_index": turn_index,
            "status": status,
            "snapshot_id": snapshot.snapshot_id,
            "context_hash": snapshot.context_hash,
            "tool_call_ids": list(tool_call_ids),
        },
    )


def _extend_output_refs(
    output_refs: list[str],
    evidence_ids: list[str],
    proposals: Sequence[DomainWriteProposal],
) -> None:
    for proposal in proposals:
        id_field = _OBJECT_ID_FIELDS.get(proposal.object_type)
        object_id = proposal.payload.get(id_field) if id_field is not None else None
        if isinstance(object_id, str) and object_id:
            output_ref = f"{proposal.object_type}:{object_id}"
            if output_ref not in output_refs:
                output_refs.append(output_ref)
            if proposal.object_type == "EvidenceCard" and object_id not in evidence_ids:
                evidence_ids.append(object_id)


def _usage_tokens(metadata: Mapping[str, Any]) -> int:
    usage = metadata.get("usage")
    if not isinstance(usage, Mapping):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    count = 0
    for key in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            count += value
    return count


def _safe_error(
    error: BaseException | str,
    *,
    max_string_length: int = _LONG_ERROR_LIMIT,
) -> str:
    safe = sanitize_runtime_payload(
        str(error),
        max_string_length=min(max_string_length, _LONG_ERROR_LIMIT),
    )
    return safe if isinstance(safe, str) and safe else "execution failed"


def _error_type(error: BaseException | None) -> str:
    return "RuntimeError" if error is None else type(error).__name__


__all__ = ["AgentHarness", "HarnessEventCallback"]
