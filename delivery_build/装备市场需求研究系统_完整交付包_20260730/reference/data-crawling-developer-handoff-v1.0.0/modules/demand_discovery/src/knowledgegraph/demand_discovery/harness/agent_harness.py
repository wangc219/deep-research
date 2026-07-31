"""High-level discovery harness: phase, queues, snapshot, and save point.

``DiscoveryHarness`` is the demand-discovery translation of Pi's
``agent-harness.ts``. It wraps the stateless :class:`AgentLoop` and adds the
runtime state the loop deliberately omits:

- a ``phase`` state machine (``idle`` / ``turn`` / ...),
- the three differentiated injection queues (``steer`` / ``follow_up`` /
  ``next_turn``) with Pi's queue semantics,
- a per-turn snapshot of messages / tools / active tool names / options,
- ``pending_domain_proposals`` and ``pending_trace_proposals`` captured from
  tool results during a turn and flushed only at the save point,
- the save point itself, emitted after every ``turn_end``.

Domain writes are never executed here directly. Tools emit proposals; the
harness captures them during the turn and hands them to the registered save
point callback (a later task wires that callback to the real domain / trace
stores).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.agent_loop import (
    AgentLoop,
    AgentLoopConfig,
    TurnState,
)
from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.cancellation import CancelToken
from knowledgegraph.demand_discovery.harness.compaction import (
    CompactionRecord,
    CompactionSettings,
    append_domain_index,
    estimate_context_tokens,
    find_cut_point,
    should_compact,
)
from knowledgegraph.demand_discovery.harness.context_cleanup import (
    apply_transient_cleanup,
)
from knowledgegraph.demand_discovery.harness.context_pack import (
    ContextPack,
    ContextPackBuilder,
)
from knowledgegraph.demand_discovery.harness.event_stream import StreamError
from knowledgegraph.demand_discovery.harness.event_bus import (
    EventBus,
    RuntimeEvent,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent
from knowledgegraph.demand_discovery.harness.session_store import MemorySessionStore
from knowledgegraph.demand_discovery.harness.tools import (
    BeforeToolCall,
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.tool_result_mediator import (
    MediatedToolResult,
    mediate_tool_result,
)
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore
from knowledgegraph.demand_discovery.harness.types import (
    AgentMessage,
    AssistantContentBlock,
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
    UserMessage,
)
from knowledgegraph.demand_discovery.llm.types import LLMContext
from knowledgegraph.demand_discovery.workers.prompts import (
    COMPACTION_PROMPT,
    WRAP_UP_PROMPT,
)


Phase = str  # "idle" | "turn" | "compaction" | "branch_summary" | "retry"

SavePointCallback = Callable[
    [list[DomainWriteProposal], list[DomainTraceProposal]], None
]
EventHandler = Callable[[AgentEvent], None]

COST_EXPANDING_TOOL_NAMES = {
    "spawn_worker",
    "search_sources",
    "fetch_page",
    "read_document",
}


@dataclass
class ApparentStopContext:
    last_assistant_text: str
    budget_state: str
    follow_up_attempt_count: int
    recent_domain_delta: dict[str, int] = field(default_factory=dict)
    recent_trace_events: list[dict[str, Any]] = field(default_factory=list)
    repeated_injection_keys: set[str] = field(default_factory=set)


class DiscoveryHarness:
    """Stateful runtime around :class:`AgentLoop`."""

    def __init__(
        self,
        provider: Any,
        tools: list[ToolDefinition] | None = None,
        session_store: MemorySessionStore | None = None,
        trace_store: DomainTraceStore | None = None,
        domain_store: DomainStore | None = None,
        context_builder: ContextPackBuilder | None = None,
        context_token_budget: int = 1200,
        run_id: str = "harness",
        agent_run_id: str = "agent",
        worker_id: str = "worker",
        budget: RunBudget | None = None,
        compaction_settings: CompactionSettings | None = None,
        cancel_token: CancelToken | None = None,
        system_prompt: str = "",
        event_bus: EventBus | None = None,
        parent_event_id: str = "",
        before_tool_call: BeforeToolCall | None = None,
        apparent_stop_follow_up_policy: Callable[
            [ApparentStopContext], list[str]
        ]
        | None = None,
        model_options: dict[str, Any] | None = None,
        tool_result_mediator: Callable[[ToolResult], MediatedToolResult] | None = (
            mediate_tool_result
        ),
    ) -> None:
        self._provider = provider
        self._tools: list[ToolDefinition] = list(tools or [])
        self._loop = AgentLoop()
        self._session_store = session_store
        self._trace_store = trace_store
        self._domain_store = domain_store
        self._context_builder = context_builder
        self._context_token_budget = context_token_budget
        self._context_snapshot: ContextPack | None = None
        self._current_task_brief = ""
        self._run_id = run_id
        self._agent_run_id = agent_run_id
        self._worker_id = worker_id
        self._trace_id = "trace-harness"
        self._cancel_token = cancel_token or CancelToken()
        self._system_prompt = system_prompt
        self._event_bus = event_bus
        self._parent_event_id = parent_event_id
        self._external_before_tool_call = before_tool_call
        self._apparent_stop_follow_up_policy = apparent_stop_follow_up_policy
        self._model_options = dict(model_options or {})
        self._tool_result_mediator = tool_result_mediator
        self._last_run_aborted = False
        self._budget = budget
        self._budget_state = "normal"
        self._wrap_turns_left = 0
        self._compaction_settings = compaction_settings or CompactionSettings()
        self._compaction: CompactionRecord | None = None
        self._last_context_tokens = 0
        self._last_loop_assistant_text = ""
        self._policy_follow_up_attempt_count = 0
        self._recent_policy_injection_keys: set[str] = set()
        self._last_policy_domain_counts = self._domain_counts()
        self._recent_policy_trace_index = 0

        self._phase: Phase = "idle"
        self._messages: list[AgentMessage] = []
        self._active_tool_names: list[str] = []

        # Injection queues with Pi semantics.
        self._steer_queue: list[str] = []
        self._follow_up_queue: list[str] = []
        # next_turn uses two buckets: items queued during a run are carried and
        # injected at the *following* prompt, not the current one.
        self._next_turn_queue: list[str] = []
        self._next_turn_carry: list[str] = []

        # Pending domain / trace proposals captured during the current turn and
        # flushed at the save point. Kept as two explicit queues, never merged.
        self._pending_domain: list[DomainWriteProposal] = []
        self._pending_trace: list[DomainTraceProposal] = []

        self._subscribers: list[EventHandler] = []
        self._save_point_cb: SavePointCallback | None = None

    # -- introspection -----------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def active_tool_names(self) -> list[str]:
        return list(self._active_tool_names)

    @property
    def context_snapshot(self) -> ContextPack | None:
        return self._context_snapshot

    @property
    def messages(self) -> list[AgentMessage]:
        return list(self._messages)

    def pending_steer_count(self) -> int:
        return len(self._steer_queue)

    def pending_follow_up_count(self) -> int:
        return len(self._follow_up_queue)

    def pending_next_turn_count(self) -> int:
        return len(self._next_turn_carry) + len(self._next_turn_queue)

    def pending_domain_proposal_count(self) -> int:
        return len(self._pending_domain)

    def pending_trace_proposal_count(self) -> int:
        return len(self._pending_trace)

    @property
    def last_run_aborted(self) -> bool:
        return self._last_run_aborted

    # -- queue / config setters -------------------------------------------

    def steer(self, text: str) -> None:
        """Inject a current-turn message (drained after the next turn)."""
        self._steer_queue.append(text)

    def follow_up(self, text: str) -> None:
        """Inject a message that runs after the agent would otherwise stop."""
        self._follow_up_queue.append(text)

    def next_turn(self, text: str) -> None:
        """Schedule a message for the prompt after the next run.

        Mirrors Pi: ``next_turn`` schedules input for after the current run, so
        a message queued while idle is carried through the next prompt and
        injected at the one after it. Preserved across :meth:`abort`.
        """
        self._next_turn_queue.append(text)
        self._append_session_entry(
            "queue_update",
            {"queue": "next_turn", "op": "push", "text": text},
        )

    def set_active_tools(self, names: list[str]) -> None:
        """Record the active tool subset for the next provider request."""
        self._active_tool_names = list(names)
        self._append_session_entry(
            "active_tools", {"active_tool_names": list(self._active_tool_names)}
        )

    def abort(self) -> None:
        """Clear steer / follow-up queues, preserve next-turn, and cancel the run."""
        self._steer_queue.clear()
        self._follow_up_queue.clear()
        self._cancel_token.cancel("user_abort")

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def on_save_point(self, callback: SavePointCallback) -> None:
        self._save_point_cb = callback

    # -- main entry --------------------------------------------------------

    async def prompt(self, text: str) -> AgentMessage:
        """Run one user-initiated prompt to completion; return last assistant.

        Only starts when the harness is ``idle``. Injects any carried next-turn
        messages, arms the next-turn queue for the following prompt, runs the
        loop, flushes proposals at each save point, and returns to ``idle`` with
        a ``settled`` event.
        """

        if self._phase != "idle":
            raise RuntimeError(f"prompt() requires idle phase, got {self._phase!r}")

        self._phase = "turn"
        self._current_task_brief = text
        self._last_run_aborted = False
        self._policy_follow_up_attempt_count = 0
        self._recent_policy_injection_keys.clear()
        self._last_policy_domain_counts = self._domain_counts()
        self._recent_policy_trace_index = (
            len(self._domain_store.trace_events)
            if self._domain_store is not None
            else 0
        )
        if self._cancel_token.cancelled:
            self._cancel_token = CancelToken()

        # Inject the carried next-turn messages, then arm the current queue for
        # the following prompt.
        carried = list(self._next_turn_carry)
        self._next_turn_carry = list(self._next_turn_queue)
        self._next_turn_queue = []
        if self._next_turn_carry:
            self._append_session_entry(
                "queue_update",
                {
                    "queue": "next_turn",
                    "op": "carry",
                    "items": list(self._next_turn_carry),
                },
            )

        for carried_text in carried:
            message = UserMessage(content=carried_text, timestamp=0)
            self._messages.append(message)
            self._append_session_message(message)
        if carried:
            self._append_session_entry(
                "queue_update",
                {
                    "queue": "next_turn",
                    "op": "drain",
                    "count": len(carried),
                    "items": list(carried),
                },
            )
        message = UserMessage(content=text, timestamp=0)
        self._messages.append(message)
        self._append_session_message(message)
        active_tools = self._snapshot_tools()
        loop_messages = self._project_messages()
        initial_loop_message_count = len(loop_messages)
        config = AgentLoopConfig(
            run_id=self._run_id,
            agent_run_id=self._agent_run_id,
            worker_id=self._worker_id,
            system_prompt=self._system_prompt,
            cancel_token=self._cancel_token,
            options={**self._model_options, "budget_state": self._budget_state},
            before_tool_call=self._before_tool_call,
            tool_result_mediator=self._tool_result_mediator,
            prepare_next_turn=self._prepare_next_turn,
            get_steering_messages=self._drain_steer,
            get_follow_up_messages=self._drain_follow_up,
            on_event=self._handle_loop_event,
        )

        stream = self._loop.run(
            messages=loop_messages,
            provider=self._provider,
            tools=active_tools,
            config=config,
        )

        try:
            async for _event in stream:
                pass

            final_messages = stream.result()
            self._messages.extend(final_messages[initial_loop_message_count:])
            await self._maybe_compact()
            settled_payload = {"aborted": True} if self._last_run_aborted else {}
            self._append_session_entry("settled", settled_payload)
            self._emit_own("settled", settled_payload)
            self._phase = "idle"
            return self._last_assistant()
        except Exception:
            payload = {"is_error": True}
            self._append_session_entry("settled", payload)
            self._emit_own("settled", payload)
            self._phase = "idle"
            raise

    # -- internals ---------------------------------------------------------

    def _snapshot_tools(self) -> list[ToolDefinition]:
        if not self._active_tool_names:
            return list(self._tools)
        active = set(self._active_tool_names)
        return [t for t in self._tools if t.name in active]

    def _project_messages(self) -> list[AgentMessage]:
        if self._compaction is None:
            return list(self._messages)
        summary_message = UserMessage(
            content=f"Research memory summary:\n{self._compaction.summary}",
            timestamp=0,
            metadata={
                "compaction": True,
                "cut_index": self._compaction.cut_index,
                "split_turn": self._compaction.split_turn,
            },
        )
        return [summary_message, *self._messages[self._compaction.cut_index :]]

    def _prepare_next_turn(self, state: TurnState) -> None:
        # Setter changes during a turn affect the next provider request, not
        # the in-flight one. Refresh the loop state at this save-point boundary.
        state.tools = self._snapshot_tools()
        state.options.update(self._model_options)
        state.options["budget_state"] = self._budget_state
        if self._budget is None:
            return None

        if self._budget_state == "wrapping_up":
            self._wrap_turns_left -= 1
            if self._wrap_turns_left <= 0:
                state.stop = True
                return None
            state.options["budget_state"] = "wrapping_up"
            return None

        dimension = self._budget.exhausted()
        if dimension is None:
            return None

        self._budget_state = "wrapping_up"
        self._wrap_turns_left = 2
        message = UserMessage(
            content=WRAP_UP_PROMPT,
            timestamp=0,
            metadata={"budget_state": "wrapping_up", "dimension": dimension},
        )
        state.messages.append(message)
        self._append_session_message(message)
        state.options["budget_state"] = "wrapping_up"
        payload = {
            "dimension": dimension,
            "budget": self._budget.remaining_summary(),
        }
        self._append_session_entry("budget_exhausted", payload)
        self._emit_own("budget_exhausted", payload)
        return None

    def _drain_steer(self) -> list[AgentMessage]:
        drained = [UserMessage(content=t, timestamp=0) for t in self._steer_queue]
        self._steer_queue.clear()
        return drained

    def _drain_follow_up(self) -> list[AgentMessage]:
        drained = [UserMessage(content=t, timestamp=0) for t in self._follow_up_queue]
        self._follow_up_queue.clear()
        if not drained and self._apparent_stop_follow_up_policy is not None:
            ctx = ApparentStopContext(
                last_assistant_text=self._last_assistant_text(),
                budget_state=self._budget_state,
                follow_up_attempt_count=self._policy_follow_up_attempt_count,
                recent_domain_delta=self._recent_domain_delta(),
                recent_trace_events=self._recent_trace_events(),
                repeated_injection_keys=set(self._recent_policy_injection_keys),
            )
            policy_texts = self._apparent_stop_follow_up_policy(ctx)
            filtered: list[str] = []
            body_delta = int(
                ctx.recent_domain_delta.get("open_source_body_artifacts", 0) or 0
            ) + int(ctx.recent_domain_delta.get("body_artifact_refs", 0) or 0)
            for text in policy_texts:
                key = _follow_up_text_key(text)
                if key in self._recent_policy_injection_keys and body_delta <= 0:
                    continue
                self._recent_policy_injection_keys.add(key)
                filtered.append(text)
            if filtered:
                self._policy_follow_up_attempt_count += 1
                self._append_session_entry(
                    "queue_update",
                    {
                        "queue": "follow_up",
                        "op": "policy_inject",
                        "count": len(filtered),
                        "items": list(filtered),
                    },
                )
            drained = [UserMessage(content=t, timestamp=0) for t in filtered]
            self._last_policy_domain_counts = self._domain_counts()
        return drained

    def _handle_loop_event(self, event: AgentEvent) -> None:
        if self._budget is not None and event.type == "message_end":
            usage = dict(event.payload.get("usage", {}) or {})
            self._budget.charge_usage(usage)
            self._last_context_tokens = _input_tokens_from_usage(usage)
        if self._budget is None and event.type == "message_end":
            self._last_context_tokens = _input_tokens_from_usage(
                dict(event.payload.get("usage", {}) or {})
            )
        if self._budget is not None and event.type == "tool_execution_end":
            self._budget.charge_tool_call()
        if event.type == "message_appended":
            message_payload = dict(event.payload.get("message", {}))
            if message_payload.get("role") == "assistant":
                self._last_loop_assistant_text = _assistant_payload_text(message_payload)
            self._append_session_entry("message", message_payload)
        if event.type == "tool_result_mediated":
            self._handle_tool_result_mediated(event.payload)
        if event.type == "tool_execution_end":
            self._capture_proposals(event.payload)
        # Re-broadcast loop events to subscribers before harness-own events.
        self._broadcast(event)
        if event.type == "turn_end":
            if event.payload.get("aborted"):
                self._handle_aborted_turn()
                return
            self._save_point()

    def _before_tool_call(
        self, call: ToolCall, ctx: ToolExecutionContext
    ) -> ToolResult | None:
        ctx.budget_state = self._budget_state
        if (
            self._budget is None
            or self._budget_state != "wrapping_up"
            or call.name not in COST_EXPANDING_TOOL_NAMES
        ):
            if self._external_before_tool_call is not None:
                return self._external_before_tool_call(call, ctx)
            return None

        payload = {
            "tool_call_id": call.id,
            "tool_name": call.name,
            "budget": self._budget.remaining_summary(),
        }
        self._append_session_entry("budget_tool_blocked", payload)
        self._emit_own("budget_tool_blocked", payload)
        return ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            content="预算已进入收尾态，只能整理既有发现",
            details={"budget_state": "wrapping_up"},
            is_error=True,
        )

    def _capture_proposals(self, payload: dict[str, Any]) -> None:
        domain = payload.get("domain_proposals") or []
        trace = payload.get("trace_proposals") or []
        self._pending_domain.extend(domain)
        self._pending_trace.extend(trace)

    def _handle_tool_result_mediated(self, payload: dict[str, Any]) -> None:
        if not payload.get("pause_requested"):
            return
        control_event = dict(payload.get("control_event", {}) or {})
        if control_event.get("overall_status") != "needs_auth":
            return
        interrupt = _auth_interrupt_payload(control_event.get("interrupt"))
        event_payload = {
            "tool_call_id": str(payload.get("tool_call_id", "")),
            "tool_name": str(payload.get("tool_name", "")),
            "overall_status": "needs_auth",
            "interrupt": interrupt,
            "source_statuses": list(control_event.get("source_statuses", []) or []),
        }
        self._append_session_entry("auth_required", event_payload)
        self._emit_own("auth_required", event_payload)

    def _save_point(self) -> None:
        """Flush pending proposals, then emit the save_point event.

        The save_point event always fires at turn_end; the registered callback
        only fires when there is at least one proposal to flush.
        """
        domain = list(self._pending_domain)
        trace = list(self._pending_trace)

        if (domain or trace) and self._save_point_cb is not None:
            self._save_point_cb(domain, trace)

        if self._domain_store is not None:
            self._flush_domain_store(domain, trace)

        if self._trace_store is not None:
            for proposal in trace:
                self._trace_store.append_from_proposal(
                    proposal,
                    trace_id=self._trace_id,
                    actor="harness",
                )

        self._pending_domain.clear()
        self._pending_trace.clear()

        context_rebuilt = self._rebuild_context_snapshot()

        payload = {
            "domain_flushed": len(domain),
            "trace_flushed": len(trace),
            "context_rebuilt": context_rebuilt,
        }

        self._append_session_entry(
            "save_point",
            payload,
        )

        self._emit_own("save_point", payload)

    def _handle_aborted_turn(self) -> None:
        self._last_run_aborted = True
        dropped_domain = len(self._pending_domain)
        dropped_trace = len(self._pending_trace)
        self._pending_domain.clear()
        self._pending_trace.clear()
        payload = {
            "dropped_domain": dropped_domain,
            "dropped_trace": dropped_trace,
            "reason": self._cancel_token.reason or "cancelled",
        }
        self._append_session_entry("aborted", payload)
        self._emit_own(
            "save_point",
            {
                "domain_flushed": 0,
                "trace_flushed": 0,
                "context_rebuilt": False,
                "aborted": True,
            },
        )

    def _last_assistant(self) -> AgentMessage:
        for message in reversed(self._messages):
            if message.role == "assistant":
                return message
        if self._last_run_aborted:
            return AgentMessage(
                role="assistant",
                content=[],
                timestamp=0,
                is_error=True,
                metadata={
                    "aborted": True,
                    "error_message": self._cancel_token.reason or "cancelled",
                },
            )
        raise RuntimeError("no assistant message produced")

    def _last_assistant_text(self) -> str:
        try:
            message = self._last_assistant()
        except RuntimeError:
            return self._last_loop_assistant_text
        if isinstance(message.content, str):
            return message.content
        return "\n".join(
            block.text for block in message.content if block.type == "text"
        )

    def _domain_counts(self) -> dict[str, int]:
        if self._domain_store is None:
            return {
                "sources": 0,
                "evidence": 0,
                "open_source_body_artifacts": 0,
                "web_research_sessions": 0,
                "body_artifact_refs": 0,
            }
        return {
            "sources": len(self._domain_store.sources),
            "evidence": len(self._domain_store.evidence),
            "open_source_body_artifacts": len(
                getattr(self._domain_store, "open_source_body_artifacts", {})
            ),
            "web_research_sessions": len(
                getattr(self._domain_store, "web_research_sessions", {})
            ),
            "body_artifact_refs": self._body_artifact_trace_count(),
        }

    def _recent_domain_delta(self) -> dict[str, int]:
        current = self._domain_counts()
        return {
            key: current.get(key, 0) - self._last_policy_domain_counts.get(key, 0)
            for key in current
        }

    def _body_artifact_trace_count(self) -> int:
        if self._domain_store is None:
            return 0
        return sum(
            1
            for event in self._domain_store.trace_events
            if event.event_type
            in {
                "read_document_completed",
                "open_source_body_fetched",
                "document_downloaded",
            }
        )

    def _recent_trace_events(self) -> list[dict[str, Any]]:
        if self._domain_store is None:
            return []
        events = self._domain_store.trace_events[self._recent_policy_trace_index :]
        self._recent_policy_trace_index = len(self._domain_store.trace_events)
        return [
            {
                "event_type": event.event_type,
                "target_type": event.target_type,
                "target_id": event.target_id,
                "summary": event.summary,
                "output_refs": list(event.output_refs),
            }
            for event in events[-20:]
        ]

    def _emit_own(self, event_type: str, payload: dict[str, Any]) -> None:
        self._broadcast(
            AgentEvent(
                type=event_type,
                run_id=self._run_id,
                agent_run_id=self._agent_run_id,
                payload=payload,
            )
        )

    def _broadcast(self, event: AgentEvent) -> None:
        if self._parent_event_id and "parent_event_id" not in event.payload:
            event.payload["parent_event_id"] = self._parent_event_id
        for handler in self._subscribers:
            handler(event)
        if self._event_bus is not None:
            self._event_bus.publish(
                RuntimeEvent(
                    category="agent_runtime",
                    event_type=event.type,
                    run_id=event.run_id,
                    agent_run_id=event.agent_run_id,
                    parent_event_id=self._parent_event_id,
                    payload=dict(event.payload),
                    timestamp=event.timestamp,
                )
            )

    def _append_session_message(self, message: AgentMessage) -> None:
        self._append_session_entry("message", message.to_dict())

    def _append_session_entry(self, entry_type: str, payload: dict[str, Any]) -> None:
        if self._session_store is None:
            return
        self._session_store.append(entry_type, payload, run_id=self._run_id)

    async def _maybe_compact(self) -> None:
        settings = self._compaction_settings
        context_tokens = max(
            self._last_context_tokens,
            estimate_context_tokens(self._messages),
        )
        if not should_compact(context_tokens, settings):
            return

        cut = find_cut_point(self._messages, settings.keep_recent_tokens)
        if self._compaction is not None and cut.index <= self._compaction.cut_index:
            return

        previous_phase = self._phase
        self._phase = "compaction"
        try:
            summary_text = await self._request_compaction_summary(cut.index)
            summary = append_domain_index(summary_text, self._build_run_state())
            record = CompactionRecord(
                summary=summary,
                cut_index=cut.index,
                split_turn=cut.split_turn,
            )
            self._compaction = record
            payload = record.to_dict()
            self._append_session_entry("compaction", payload)
            self._emit_own("compaction", payload)
        except Exception as exc:
            payload = {"error": str(exc)}
            self._append_session_entry("compaction_failed", payload)
            self._emit_own("compaction_failed", payload)
        finally:
            self._phase = previous_phase

    async def _request_compaction_summary(self, cut_index: int) -> str:
        context = LLMContext(
            messages=list(self._messages[:cut_index]),
            system_prompt=COMPACTION_PROMPT,
            metadata={"purpose": "compaction"},
        )
        provider_stream = self._provider.stream(
            context,
            [],
            {"cancel_token": self._cancel_token, "purpose": "compaction"},
        )
        async for _event in provider_stream:
            self._cancel_token.raise_if_cancelled()
        try:
            assistant = provider_stream.result()
        except StreamError as exc:
            raise RuntimeError(str(exc)) from exc
        if getattr(assistant, "is_error", False):
            raise RuntimeError(getattr(assistant, "error_message", "") or "compaction failed")
        if self._budget is not None:
            self._budget.charge_usage(dict(getattr(assistant, "usage", {}) or {}))
        text = assistant.text().strip()
        if not text:
            raise RuntimeError("compaction produced empty summary")
        return text

    def _rebuild_context_snapshot(self) -> bool:
        if self._context_builder is None:
            return False
        self._context_snapshot = self._context_builder.build(
            agent_role="orchestrator",
            task_brief=self._current_task_brief,
            run_state=self._build_run_state(),
            token_budget=self._context_token_budget,
        )
        return True

    def _build_run_state(self) -> dict[str, Any]:
        run_state: dict[str, Any] = {}
        if self._domain_store is not None:
            run_state.update(self._domain_store.to_run_state())
        trace_events = (
            [event.to_dict() for event in self._trace_store.events()]
            if self._trace_store is not None
            else []
        )
        existing_trace_events = list(run_state.get("trace_events", []))
        run_state.update(
            {
                "messages": [message.to_dict() for message in self._messages],
                "active_tool_names": list(self._active_tool_names),
                "trace_events": [*existing_trace_events, *trace_events],
            }
        )
        return run_state

    def _flush_domain_store(
        self,
        domain: list[DomainWriteProposal],
        trace: list[DomainTraceProposal],
    ) -> None:
        self._validate_domain_trace_pairs(domain, trace)
        trace_count_before = len(self._domain_store.trace_events)
        staged = self._domain_store.clone()
        for proposal in domain:
            staged.apply_domain_proposal(proposal)
        for proposal in trace:
            staged.append_trace_from_proposal(
                proposal,
                actor="harness",
                trace_id=self._trace_id,
            )
        self._domain_store.replace_from(staged)
        self._domain_store.append_accepted_proposals(domain)
        self._domain_store.append_accepted_trace_events(
            self._domain_store.trace_events[trace_count_before:]
        )

    def _validate_domain_trace_pairs(
        self,
        domain: list[DomainWriteProposal],
        trace: list[DomainTraceProposal],
    ) -> None:
        for proposal in domain:
            target_type, target_id, allowed_events = self._expected_trace(proposal)
            if (
                self._domain_store is not None
                and proposal.object_type == "CandidateDemand"
                and proposal.action == "upsert"
            ):
                existing = self._domain_store.candidates.get(target_id)
                new_status = str(proposal.payload.get("status", "candidate_demand"))
                if (
                    existing is not None
                    and existing.status == "demand_report"
                    and new_status == "candidate_demand"
                ):
                    allowed_events = {"candidate_status_rolled_back"}
            matched = any(
                (
                    trace_proposal.target_type == target_type
                    and trace_proposal.target_id == target_id
                    or target_id in trace_proposal.output_refs
                )
                and trace_proposal.event_type in allowed_events
                for trace_proposal in trace
            )
            if not matched:
                raise ValueError(
                    "domain proposal missing matching trace proposal: "
                    f"{proposal.action} {proposal.object_type} {target_id}"
                )

    @staticmethod
    def _expected_trace(
        proposal: DomainWriteProposal,
    ) -> tuple[str, str, set[str]]:
        payload = proposal.payload
        if proposal.object_type == "SourceRecord" and proposal.action == "upsert":
            return (
                "SourceRecord",
                str(payload.get("source_id", "")),
                {"source_seen", "source_updated"},
            )
        if proposal.object_type == "EvidenceCard" and proposal.action == "upsert":
            return (
                "EvidenceCard",
                str(payload.get("evidence_id", "")),
                {"evidence_created", "evidence_updated"},
            )
        if proposal.object_type == "CandidateDemand" and proposal.action == "upsert":
            event = (
                "candidate_updated"
                if payload.get("candidate_id") and payload.get("candidate_id") != ""
                else "candidate_created"
            )
            return (
                "CandidateDemand",
                str(payload.get("candidate_id", "")),
                {"candidate_created", "candidate_updated", event},
            )
        if proposal.object_type == "CandidateDemand" and proposal.action == "merge":
            return (
                "CandidateDemand",
                str(payload.get("surviving_candidate_id", "")),
                {"candidate_merged"},
            )
        if proposal.object_type == "AuditReport" and proposal.action == "append":
            return (
                "AuditReport",
                str(payload.get("audit_id", "")),
                {"audit_completed"},
            )
        if proposal.object_type == "DemandReport" and proposal.action == "append":
            return (
                "DemandReport",
                str(payload.get("report_id", "")),
                {"report_generated"},
            )
        if proposal.object_type == "ResearchLead" and proposal.action == "upsert":
            return (
                "ResearchLead",
                str(payload.get("lead_id", "")),
                {
                    "research_leads_discovered",
                    "research_leads_recorded",
                    "document_downloaded",
                },
            )
        if proposal.object_type == "ReadingQueue" and proposal.action == "upsert":
            return (
                "ReadingQueue",
                str(payload.get("queue_id", "")),
                {"research_leads_discovered", "research_leads_recorded"},
            )
        if proposal.object_type == "ResearchRound" and proposal.action == "upsert":
            return (
                "ResearchRound",
                str(payload.get("round_id", "")),
                {
                    "research_round_planned",
                    "research_round_started",
                    "research_round_updated",
                },
            )
        if proposal.object_type == "JudgementReport" and proposal.action == "upsert":
            return (
                "JudgementReport",
                str(payload.get("judgement_id", "")),
                {"judgement_recorded"},
            )
        if proposal.object_type == "OpenSearchPlan" and proposal.action == "upsert":
            return (
                "OpenSearchPlan",
                str(payload.get("plan_id", "")),
                {"open_search_plan_created", "open_search_plan_updated"},
            )
        if proposal.object_type == "OpenSourceLead" and proposal.action == "upsert":
            return (
                "OpenSourceLead",
                str(payload.get("lead_id", "")),
                {"open_source_lead_recorded"},
            )
        if proposal.object_type == "OpenSourceBodyArtifact" and proposal.action == "upsert":
            return (
                "OpenSourceBodyArtifact",
                str(payload.get("body_id", "")),
                {"open_source_body_fetched"},
            )
        if proposal.object_type == "SourceQualityAssessment" and proposal.action == "upsert":
            return (
                "SourceQualityAssessment",
                str(payload.get("assessment_id", "")),
                {"source_quality_assessed"},
            )
        if proposal.object_type == "BrowserRecipeDraft" and proposal.action == "upsert":
            return (
                "BrowserRecipeDraft",
                str(payload.get("recipe_id", "")),
                {"browser_recipe_draft_created"},
            )
        if proposal.object_type == "WebResearchSession" and proposal.action == "upsert":
            return (
                "WebResearchSession",
                str(payload.get("session_id", "")),
                {"web_research_session_updated"},
            )
        if proposal.object_type == "WorkerSelfCheck" and proposal.action == "upsert":
            return (
                "WorkerSelfCheck",
                str(payload.get("check_id", "")),
                {"worker_self_check_recorded"},
            )
        if proposal.object_type == "FollowUpInstruction" and proposal.action == "upsert":
            return (
                "FollowUpInstruction",
                str(payload.get("instruction_id", "")),
                {"worker_follow_up_planned"},
            )
        raise ValueError(
            f"unsupported domain proposal: {proposal.action} {proposal.object_type}"
        )

    @classmethod
    def from_session(
        cls,
        session_path: Any,
        *,
        provider: Any,
        tools: list[ToolDefinition],
        domain_store: DomainStore,
        trace_store: DomainTraceStore | None = None,
        context_builder: ContextPackBuilder | None = None,
        run_id: str | None = None,
    ) -> "DiscoveryHarness":
        from knowledgegraph.demand_discovery.harness.session_store import (
            JsonlSessionStore,
        )

        session_store = JsonlSessionStore(session_path, run_id=run_id or "")
        resolved_run_id = run_id or session_store.run_id or "harness"
        entries = session_store.entries()
        restore_index = -1
        for index, entry in enumerate(entries):
            if entry.type in {"save_point", "settled", "aborted", "compaction"}:
                restore_index = index
        replay_entries = entries[: restore_index + 1] if restore_index >= 0 else entries
        dropped_entries = entries[restore_index + 1 :] if restore_index >= 0 else []

        harness = cls(
            provider=provider,
            tools=tools,
            session_store=session_store,
            trace_store=trace_store,
            domain_store=domain_store,
            context_builder=context_builder,
            run_id=resolved_run_id,
        )
        for entry in replay_entries:
            if entry.type == "message":
                message = _message_from_dict(entry.payload)
                harness._messages.append(message)
                cleanup = dict(message.metadata.get("transient_cleanup", {}) or {})
                if cleanup and not message.is_error:
                    apply_transient_cleanup(harness._messages, cleanup)
            elif entry.type == "active_tools":
                harness._active_tool_names = list(
                    entry.payload.get("active_tool_names", [])
                )
            elif entry.type == "queue_update":
                if entry.payload.get("queue") != "next_turn":
                    continue
                if entry.payload.get("op") == "push":
                    harness._next_turn_queue.append(str(entry.payload.get("text", "")))
                elif entry.payload.get("op") == "carry":
                    harness._next_turn_carry = [
                        str(item) for item in entry.payload.get("items", [])
                    ]
                    harness._next_turn_queue.clear()
                elif entry.payload.get("op") == "drain":
                    items = [str(item) for item in entry.payload.get("items", [])]
                    if items:
                        harness._next_turn_carry = [
                            item
                            for item in harness._next_turn_carry
                            if item not in items
                        ]
                    else:
                        harness._next_turn_queue.clear()
                        harness._next_turn_carry.clear()
            elif entry.type == "compaction":
                harness._compaction = CompactionRecord(
                    summary=str(entry.payload.get("summary", "")),
                    cut_index=int(entry.payload.get("cut_index", 0)),
                    split_turn=bool(entry.payload.get("split_turn", False)),
                )

        if dropped_entries:
            after_entry_id = (
                entries[restore_index].entry_id if restore_index >= 0 else ""
            )
            session_store.append(
                "recovered_from_crash",
                {
                    "dropped_entries": len(dropped_entries),
                    "after_entry_id": after_entry_id,
                },
                run_id=resolved_run_id,
            )
        return harness


def _message_from_dict(data: dict[str, Any]) -> AgentMessage:
    content = data.get("content", "")
    if isinstance(content, list):
        content = [
            AssistantContentBlock(
                type=str(block.get("type", "")),
                text=str(block.get("text", "")),
                id=str(block.get("id", "")),
                name=str(block.get("name", "")),
                arguments=dict(block.get("arguments", {})),
            )
            for block in content
        ]
    return AgentMessage(
        role=str(data.get("role", "")),
        content=content,
        timestamp=int(data.get("timestamp", 0)),
        tool_call_id=str(data.get("tool_call_id", "")),
        tool_name=str(data.get("tool_name", "")),
        is_error=bool(data.get("is_error", False)),
        metadata=dict(data.get("metadata", {})),
    )


def _auth_interrupt_payload(value: Any) -> dict[str, Any]:
    interrupt = dict(value or {}) if isinstance(value, dict) else {}
    payload: dict[str, Any] = {}
    interrupt_type = str(interrupt.get("type", "")).strip()
    provider = str(interrupt.get("provider", "")).strip()
    user_message = str(interrupt.get("user_message", "")).strip()
    if interrupt_type:
        payload["type"] = interrupt_type
    if provider:
        payload["provider"] = provider
    if user_message:
        payload["user_message"] = user_message
    return payload


def _assistant_payload_text(data: dict[str, Any]) -> str:
    content = data.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _input_tokens_from_usage(usage: dict[str, Any]) -> int:
    value = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _follow_up_text_key(text: str) -> str:
    return " ".join(text.split())[:500]
