"""Stateful task harness around the domain-free agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re
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

_SECRET_KEY_PARTS = (
    "authorization",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "credential",
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
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
        self._monotonic = monotonic
        self._tools = _normalize_tools(tools)
        self._listeners: list[HarnessEventCallback] = []
        if on_event is not None:
            self._listeners.append(on_event)
        self._listener_error_count = 0
        self._state_lock = Lock()
        self._next_turn_tools: tuple[str, ...] | None = None
        self._executing = False
        self.last_session_store: JsonlSessionStore | None = None
        self.last_session_path: Path | None = None

    @property
    def listener_error_count(self) -> int:
        with self._state_lock:
            return self._listener_error_count

    def on_event(self, callback: HarnessEventCallback) -> Callable[[], None]:
        if not callable(callback):
            raise TypeError("event callback must be callable")
        with self._state_lock:
            self._listeners.append(callback)

        def unsubscribe() -> None:
            with self._state_lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)

        return unsubscribe

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
            session = JsonlSessionStore(
                f"{execution_id}.jsonl",
                root_dir=self.sessions_root,
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
            record = {
                "event_type": event_type,
                "execution_id": execution_id,
                "task_id": task.task_id,
                "agent_id": task.target_agent_id,
                "created_at": now_iso(),
                "schema_version": "1.0",
                **cast(dict[str, Any], _safe_plain(payload)),
            }
            session.append(record)

        async def emit_external(event_type: str, payload: Mapping[str, Any]) -> None:
            await self._emit_external(
                RuntimeEvent(
                    category="agent_harness",
                    event_type=event_type,
                    run_id=task.run_id,
                    payload=cast(Mapping[str, Any], _safe_plain(payload)),
                )
            )

        def commit_turn(turn_index: int, status: str) -> None:
            nonlocal checkpoint_id
            commit_attempted.add(turn_index)
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
            checkpoint_id = self.store.commit(domains, traces)
            committed_turns.add(turn_index)
            _extend_output_refs(output_refs, evidence_ids, domains)
            append_session(
                "savepoint",
                {
                    "turn_index": turn_index,
                    "checkpoint_id": checkpoint_id,
                    "domain_proposal_refs": [
                        f"domain:{proposal.proposal_id}" for proposal in domains
                    ],
                    "trace_proposal_refs": [
                        f"trace:{proposal.proposal_id}" for proposal in traces
                    ],
                },
            )

        def finalize_uncommitted_turn(status: str) -> None:
            if not snapshots:
                return
            turn_index = snapshots[-1].turn_index
            if turn_index in committed_turns or turn_index in commit_attempted:
                return
            commit_attempted.add(turn_index)
            trace = _harness_trace(
                execution_id=execution_id,
                task=task,
                turn_index=turn_index,
                status=status,
                snapshot=snapshots[-1],
                tool_call_ids=tool_call_ids.get(turn_index, ()),
            )
            nonlocal checkpoint_id
            checkpoint_id = self.store.commit((), (trace,))
            committed_turns.add(turn_index)
            append_session(
                "savepoint",
                {
                    "turn_index": turn_index,
                    "checkpoint_id": checkpoint_id,
                    "domain_proposal_refs": [],
                    "trace_proposal_refs": [f"trace:{trace.proposal_id}"],
                },
            )

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
                    "context_refs": list(task.context_refs),
                    "evidence_refs": list(task.evidence_refs),
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

            async def prepare_turn(snapshot_input: TurnSnapshotInput) -> TurnSnapshotInput:
                nonlocal active_tool_names, core_error
                try:
                    next_tools = self._consume_next_turn_tools()
                    if next_tools is not None:
                        active_tool_names = next_tools
                    selected: list[ToolDefinition] = []
                    for name in active_tool_names:
                        definition = self._tools.get(name)
                        if definition is None:
                            raise ValueError(f"unknown active tool: {name}")
                        self.authorization_policy.authorize(
                            name,
                            active_tool_names=active_tool_names,
                            object_read_scopes=read_scopes,
                            object_write_scopes=write_scopes,
                        )
                        selected.append(
                            _authorized_tool(
                                definition,
                                policy=self.authorization_policy,
                                active_tool_names=active_tool_names,
                                object_read_scopes=read_scopes,
                                object_write_scopes=write_scopes,
                                budget=budget,
                            )
                        )

                    if not budget.try_start_turn():
                        denied_turns.add(snapshot_input.turn_index)
                        return snapshot_input

                    prepared = TurnSnapshotInput(
                        turn_index=snapshot_input.turn_index,
                        messages=snapshot_input.messages,
                        tools=tuple(selected),
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
                        cast(Mapping[str, Any], _safe_plain(frozen_snapshot.to_plain())),
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

            if isinstance(core_error, PermissionError):
                raise core_error
            if loop_result.status == "failed":
                finalize_uncommitted_turn("failed")
                error = _safe_error(core_error or loop_result.error or "execution failed")
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
            error = _safe_error(exc)
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
            error = _safe_error(exc)
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

    async def _emit_external(self, event: RuntimeEvent) -> None:
        with self._state_lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                response = listener(event)
                if inspect.isawaitable(response):
                    await response
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling() > 0:
                    raise
                with self._state_lock:
                    self._listener_error_count += 1
            except Exception:
                with self._state_lock:
                    self._listener_error_count += 1

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
) -> ToolDefinition:
    async def authorized_handler(
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        policy.authorize(
            call.name,
            active_tool_names=active_tool_names,
            object_read_scopes=object_read_scopes,
            object_write_scopes=object_write_scopes,
        )
        budget.record_tool_call()
        return await definition.handler(call, context)

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


def _safe_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                safe[str(key)] = "<redacted>"
            else:
                safe[str(key)] = _safe_plain(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_plain(item) for item in value]
    if isinstance(value, str):
        return _BEARER_PATTERN.sub("<redacted>", value)
    return value


def _safe_error(error: BaseException | str) -> str:
    text = str(error)
    text = _BEARER_PATTERN.sub("<redacted>", text)
    if len(text) > _LONG_ERROR_LIMIT:
        text = text[:_LONG_ERROR_LIMIT] + "<truncated>"
    return text or "execution failed"


def _error_type(error: BaseException | None) -> str:
    return "RuntimeError" if error is None else type(error).__name__


__all__ = ["AgentHarness", "HarnessEventCallback"]
