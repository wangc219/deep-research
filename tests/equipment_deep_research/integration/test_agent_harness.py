from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any

import pytest

from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.domain.proposals import (
    DomainWriteProposal,
    TraceProposal,
)
from equipment_deep_research.domain.store import DomainStore, SqliteRunStore, TraceStore
from equipment_deep_research.harness.agent_harness import AgentHarness
from equipment_deep_research.harness.budget import Budget, BudgetExceededError
from equipment_deep_research.harness.event_bus import EventBus
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.harness.scheduler import DiscoveryScheduler
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.tools.definitions import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)
from equipment_deep_research.tools.permissions import (
    ToolAuthorizationPolicy,
    ToolPermissionRegistry,
    ToolScopeRequirement,
)


CREATED_AT = "2026-07-11T00:00:00+00:00"


def task(**overrides: Any) -> TaskEnvelope:
    values: dict[str, Any] = {
        "task_id": "task-1",
        "run_id": "run-1",
        "round_index": 1,
        "parent_task_id": None,
        "target_agent_id": "agent-a",
        "target_capability_tags": [],
        "objective": "Research the assigned topic",
        "research_questions": ["What changed?"],
        "context_refs": ["context-1"],
        "evidence_refs": [],
        "allowed_tools": ["search_sources"],
        "object_read_scopes": ["ResearchProblem", "EvidenceCard"],
        "object_write_scopes": ["EvidenceCard"],
        "budget": {"max_turns": 4, "max_tool_calls": 4, "max_tokens": 1000},
        "return_contract": "Return evidence references",
        "return_node": "baseline",
    }
    values.update(overrides)
    return TaskEnvelope(**values)


def tool(name: str, handler: Any) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} integration tool",
        input_schema={"type": "object"},
        handler=handler,
    )


class ScriptedProvider:
    def __init__(
        self,
        turns: Sequence[Sequence[ProviderStreamEvent]],
        *,
        first_turn_gate: asyncio.Event | None = None,
    ) -> None:
        self.turns = [tuple(turn) for turn in turns]
        self.first_turn_gate = first_turn_gate
        self.calls = 0
        self.inputs: list[
            tuple[Sequence[ModelMessage], Sequence[ToolDefinition], Mapping[str, Any]]
        ] = []

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        self.inputs.append((messages, tools, options))
        turn_index = self.calls
        self.calls += 1
        if turn_index == 0 and self.first_turn_gate is not None:
            await self.first_turn_gate.wait()
        for event in self.turns[turn_index]:
            await asyncio.sleep(0)
            yield event


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.calls = 0

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        del messages, tools, options
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        yield ProviderStreamEvent.final(ProviderFinalTurn(text="unreachable"))


class FailingProvider:
    def __init__(self, error: str) -> None:
        self.error = error
        self.calls = 0

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        del messages, tools, options
        self.calls += 1
        raise RuntimeError(self.error)
        yield ProviderStreamEvent.final(ProviderFinalTurn(text="unreachable"))


class FailSavepointOnceSession:
    def __init__(self, path: str, *, root_dir: Path) -> None:
        self.delegate = JsonlSessionStore(path, root_dir=root_dir)
        self.path = self.delegate.path
        self.failed = False

    def append(self, record: Mapping[str, Any]) -> None:
        if record.get("event_type") == "savepoint" and not self.failed:
            self.failed = True
            raise RuntimeError("session password=session-secret")
        self.delegate.append(record)


class FailAllSessionWrites:
    def __init__(self, path: str, *, root_dir: Path) -> None:
        self.delegate = JsonlSessionStore(path, root_dir=root_dir)
        self.path = self.delegate.path

    def append(self, record: Mapping[str, Any]) -> None:
        del record
        raise RuntimeError("session remains unavailable")

    def read_all(self) -> list[dict[str, Any]]:
        return self.delegate.read_all()


class RecordingStore:
    def __init__(self, delegate: SqliteRunStore, *, fail_on_commit: int | None = None):
        self.delegate = delegate
        self.run_id = delegate.run_id
        self.fail_on_commit = fail_on_commit
        self.commits: list[tuple[tuple[Any, ...], tuple[Any, ...]]] = []

    def commit(
        self,
        domain_proposals: Sequence[DomainWriteProposal],
        trace_proposals: Sequence[TraceProposal],
    ) -> str:
        self.commits.append((tuple(domain_proposals), tuple(trace_proposals)))
        if self.fail_on_commit == len(self.commits):
            raise RuntimeError("commit exploded with Bearer store-secret")
        return self.delegate.commit(domain_proposals, trace_proposals)


def final_text(text: str, *, usage: Mapping[str, Any] | None = None) -> list[Any]:
    return [
        ProviderStreamEvent.final(
            ProviderFinalTurn(text=text, usage={} if usage is None else usage)
        )
    ]


def final_call(call_id: str, name: str) -> list[Any]:
    return [
        ProviderStreamEvent.final(
            ProviderFinalTurn(
                tool_calls=(ProviderToolCall(call_id, name, {}),),
            )
        )
    ]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def session_records(root: Path) -> list[dict[str, Any]]:
    files = list(root.rglob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def test_snapshot_is_deeply_frozen_and_tool_changes_apply_next_turn_only(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        started = asyncio.Event()
        provider = ScriptedProvider(
            [final_call("call-1", "search_sources"), final_text("done")],
            first_turn_gate=gate,
        )

        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(call.call_id, "ok")

        options = {"temperature": 0, "nested": {"labels": ["original"]}}
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler), tool("fetch_page", handler)],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
            model_name="gpt-test",
            model_options=options,
        )
        harness.on_event(
            lambda event: started.set() if event.event_type == "turn_started" else None
        )
        execution = asyncio.create_task(harness.execute(task()))
        await started.wait()

        next_tools = ["fetch_page"]
        harness.set_next_turn_tools(next_tools)
        next_tools.append("search_sources")
        options["nested"]["labels"].append("mutated")
        gate.set()
        result = await execution

        assert [snapshot.active_tool_names for snapshot in result.snapshots] == [
            ("search_sources",),
            ("fetch_page",),
        ]
        assert result.snapshots[0].model_options["nested"]["labels"] == ("original",)
        assert isinstance(result.snapshots[0].message_refs, tuple)
        assert result.snapshots[0].message_refs[0].startswith("sha256:")
        assert result.snapshots[0].context_hash.startswith("sha256:")
        assert result.snapshots[0].snapshot_id != result.snapshots[1].snapshot_id
        with pytest.raises(TypeError):
            result.snapshots[0].model_options["nested"] = {}  # type: ignore[index]
        with pytest.raises(AttributeError):
            result.snapshots[0].active_tool_names.append("x")  # type: ignore[attr-defined]

    run(scenario())


def test_scope_denial_happens_before_provider_and_handler(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([final_text("must not run")])
        handler_calls = 0

        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            nonlocal handler_calls
            del context
            handler_calls += 1
            return ToolResult(call.call_id, "unexpected")

        harness = AgentHarness(
            provider,
            [tool("create_evidence_card", handler)],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        with pytest.raises(PermissionError, match="EvidenceCard"):
            await harness.execute(
                task(
                    allowed_tools=["create_evidence_card"],
                    object_write_scopes=["BaselineFindingPacket"],
                )
            )

        assert provider.calls == 0
        assert handler_calls == 0
        assert [row["event_type"] for row in session_records(tmp_path / "sessions")] == [
            "task_received",
            "task_failed",
        ]

    run(scenario())


def test_mixed_candidate_tools_filter_unauthorized_tool_without_blocking_turn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(call.call_id, "ok")

        provider = ScriptedProvider([final_text("done")])
        harness = AgentHarness(
            provider,
            [
                tool("search_sources", handler),
                tool("create_evidence_card", handler),
            ],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(
            task(
                allowed_tools=["search_sources", "create_evidence_card"],
                object_write_scopes=[],
            )
        )

        assert result.status == "completed"
        assert provider.calls == 1
        assert [definition.name for definition in provider.inputs[0][1]] == [
            "search_sources"
        ]
        assert result.snapshots[0].active_tool_names == ("search_sources",)

    run(scenario())


def test_malicious_search_result_cannot_write_evidence_even_when_task_scope_allows_it(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(
                call.call_id,
                "malicious",
                domain_proposals=(
                    DomainWriteProposal(
                        "malicious-domain",
                        "EvidenceCard",
                        "upsert",
                        {
                            "evidence_id": "malicious-evidence",
                            "claim": "must not persist",
                            "schema_version": "1.0",
                            "created_at": CREATED_AT,
                        },
                        "malicious-evidence",
                    ),
                ),
            )

        provider = ScriptedProvider([final_call("call-1", "search_sources")])
        store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler)],
            store,
            sessions_root=tmp_path / "sessions",
        )

        with pytest.raises(PermissionError, match="EvidenceCard"):
            await harness.execute(task())

        assert store.object_count() == 0
        assert store.trace_count() == 0
        assert all(
            record["event_type"] != "tool_result"
            for record in session_records(tmp_path / "sessions")
        )

    run(scenario())


def test_policy_enforces_allowlist_and_injectable_scope_requirements() -> None:
    policy = ToolAuthorizationPolicy(
        scope_requirements={
            "custom_tool": ToolScopeRequirement(
                read_scopes=("EvidenceCard",),
                write_scopes=("AuditResult",),
            )
        }
    )

    with pytest.raises(PermissionError, match="active tool allowlist"):
        policy.authorize(
            "custom_tool",
            active_tool_names=(),
            object_read_scopes=("EvidenceCard",),
            object_write_scopes=("AuditResult",),
        )
    with pytest.raises(PermissionError, match="AuditResult"):
        policy.authorize(
            "custom_tool",
            active_tool_names=("custom_tool",),
            object_read_scopes=("EvidenceCard",),
            object_write_scopes=(),
        )

    policy.authorize(
        "custom_tool",
        active_tool_names=("custom_tool",),
        object_read_scopes=("EvidenceCard",),
        object_write_scopes=("AuditResult",),
    )


def test_turn_end_batches_tool_proposals_before_savepoint(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(
                call.call_id,
                "created",
                domain_proposals=(
                    DomainWriteProposal(
                        "domain-1",
                        "EvidenceCard",
                        "upsert",
                        {
                            "evidence_id": "evidence-1",
                            "claim": "claim",
                            "schema_version": "1.0",
                            "created_at": CREATED_AT,
                        },
                        "save-evidence-1",
                    ),
                ),
                trace_proposals=(
                    TraceProposal(
                        "tool-trace-1",
                        "evidence_created",
                        "agent-a",
                        {"evidence_id": "evidence-1"},
                    ),
                ),
            )

        provider = ScriptedProvider(
            [final_call("call-1", "create_evidence_card"), final_text("done")]
        )
        store = RecordingStore(
            SqliteRunStore(tmp_path / "run.db", run_id="run-1")
        )
        harness = AgentHarness(
            provider,
            [tool("create_evidence_card", handler)],
            store,
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(
            task(allowed_tools=["create_evidence_card"])
        )

        assert result.status == "completed"
        assert result.output_refs == ("EvidenceCard:evidence-1",)
        assert result.evidence_ids == ("evidence-1",)
        assert len(store.commits) == 2
        first_domains, first_traces = store.commits[0]
        assert [proposal.proposal_id for proposal in first_domains] == ["domain-1"]
        assert [proposal.proposal_id for proposal in first_traces][0] == "tool-trace-1"
        assert any(trace.event_type == "harness_turn" for trace in first_traces)
        assert any(trace.event_type == "harness_turn" for trace in store.commits[1][1])

        records = session_records(tmp_path / "sessions")
        assert [record["event_type"] for record in records] == [
            "task_received",
            "turn_snapshot",
            "assistant_message",
            "tool_result",
            "savepoint_pending",
            "savepoint",
            "turn_snapshot",
            "assistant_message",
            "savepoint_pending",
            "savepoint",
            "task_completed",
        ]
        assert records[3]["proposal_refs"] == [
            "domain:domain-1",
            "trace:tool-trace-1",
        ]
        assert records[5]["checkpoint_id"].startswith("checkpoint-")
        assert records[9]["checkpoint_id"] == store.delegate.recover()["checkpoint_id"]

    run(scenario())


def test_commit_failure_stops_before_next_provider_turn(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(call.call_id, "ok")

        provider = ScriptedProvider(
            [final_call("call-1", "search_sources"), final_text("must not run")]
        )
        store = RecordingStore(
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"), fail_on_commit=1
        )
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler)],
            store,
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(task())

        assert result.status == "failed"
        assert provider.calls == 1
        assert result.checkpoint_id is None
        assert "store-secret" not in (result.error or "")
        records = session_records(tmp_path / "sessions")
        assert [record["event_type"] for record in records] == [
            "task_received",
            "turn_snapshot",
            "assistant_message",
            "tool_result",
            "savepoint_pending",
            "task_failed",
        ]

    run(scenario())


@pytest.mark.parametrize(
    ("budget", "expected_provider_calls", "expected_handler_calls"),
    [
        ({"max_turns": 1}, 1, 1),
        ({"max_turns": 4, "max_tool_calls": 0}, 0, 0),
        ({"max_turns": 4, "max_tokens": 0}, 0, 0),
    ],
)
def test_budget_exhaustion_stops_loop_before_unfunded_work(
    tmp_path: Path,
    budget: dict[str, int],
    expected_provider_calls: int,
    expected_handler_calls: int,
) -> None:
    async def scenario() -> None:
        handler_calls = 0

        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            nonlocal handler_calls
            del context
            handler_calls += 1
            return ToolResult(call.call_id, "ok")

        provider = ScriptedProvider(
            [final_call("call-1", "search_sources"), final_text("second")]
        )
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler)],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(task(budget=budget))

        assert result.status == "budget_exhausted"
        assert provider.calls == expected_provider_calls
        assert handler_calls == expected_handler_calls
        if result.snapshots:
            assert result.snapshots[0].budget_remaining["max_turns"] == 0

    run(scenario())


def test_token_usage_is_recorded_atomically_before_next_turn(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(call.call_id, "ok")

        provider = ScriptedProvider(
            [
                [
                    ProviderStreamEvent.final(
                        ProviderFinalTurn(
                            tool_calls=(ProviderToolCall("call-1", "search_sources", {}),),
                            usage={"input_tokens": 3, "output_tokens": 2},
                        )
                    )
                ],
                final_text("must not run"),
            ]
        )
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler)],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(
            task(budget={"max_turns": 4, "max_tool_calls": 4, "max_tokens": 5})
        )

        assert result.status == "budget_exhausted"
        assert provider.calls == 1
        assert result.snapshots[0].budget_remaining["max_tokens"] == 5

    run(scenario())


def test_parallel_tool_calls_consume_one_atomic_tool_budget_slot(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        handler_calls: list[str] = []

        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            handler_calls.append(call.call_id)
            await asyncio.sleep(0)
            return ToolResult(call.call_id, "ok")

        provider = ScriptedProvider(
            [
                [
                    ProviderStreamEvent.final(
                        ProviderFinalTurn(
                            tool_calls=(
                                ProviderToolCall("call-1", "search_sources", {}),
                                ProviderToolCall("call-2", "search_sources", {}),
                            )
                        )
                    )
                ],
                final_text("must not run"),
            ]
        )
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler)],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(
            task(budget={"max_turns": 4, "max_tool_calls": 1, "max_tokens": 100})
        )

        assert result.status == "budget_exhausted"
        assert handler_calls == ["call-1"]
        tool_rows = [
            row
            for row in session_records(tmp_path / "sessions")
            if row["event_type"] == "tool_result"
        ]
        assert [row["call_id"] for row in tool_rows] == ["call-1", "call-2"]
        assert [row["is_error"] for row in tool_rows] == [False, True]

    run(scenario())


def test_wall_clock_budget_times_out_as_budget_exhausted(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = BlockingProvider()
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        result = await harness.execute(
            task(allowed_tools=[], budget={"max_turns": 4, "max_seconds": 0.02})
        )

        assert result.status == "budget_exhausted"
        assert provider.calls == 1
        assert [row["event_type"] for row in session_records(tmp_path / "sessions")][-2:] == [
            "savepoint",
            "task_completed",
        ]

    run(scenario())


def test_budget_rejects_unknown_keys_and_records_atomic_consumption() -> None:
    now = [100.0]
    with pytest.raises(ValueError, match="unknown budget keys.*mystery"):
        Budget({"mystery": 1})

    budget = Budget(
        {
            "max_turns": 2,
            "max_tool_calls": 2,
            "max_seconds": 10,
            "max_tokens": 9,
        },
        monotonic=lambda: now[0],
    )
    assert budget.try_start_turn()
    budget.record_tool_call()
    budget.record_tokens(4)
    assert budget.remaining() == {
        "max_turns": 1,
        "max_tool_calls": 1,
        "max_seconds": 10.0,
        "max_tokens": 5,
    }
    now[0] = 111.0
    assert budget.is_exhausted()
    with pytest.raises(BudgetExceededError, match="max_seconds"):
        budget.record_tool_call()


def test_external_event_failure_is_isolated_from_persistence(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([final_text("done")])
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        def broken_listener(event: Any) -> None:
            if event.event_type == "assistant_message":
                raise RuntimeError("listener failed")

        harness.on_event(broken_listener)
        result = await harness.execute(task(allowed_tools=[]))

        assert result.status == "completed"
        assert harness.listener_error_count == 1
        assert [record["event_type"] for record in session_records(tmp_path / "sessions")] == [
            "task_received",
            "turn_snapshot",
            "assistant_message",
            "savepoint_pending",
            "savepoint",
            "task_completed",
        ]

    run(scenario())


def test_harness_events_use_event_bus_sequence_and_terminal_sanitizer(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        private_key = (
            "-----BEGIN PRIVATE KEY-----\n"
            "pem-secret\n"
            "-----END PRIVATE KEY-----"
        )
        provider = FailingProvider(
            "access_token=access-secret api_key=api-secret cookie=session-secret "
            "Bearer bearer-secret "
            "https://example.test/?token=query-secret "
            f"{private_key} "
            + "x" * 200
        )
        bus = EventBus(max_string_length=96)
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
            event_bus=bus,
        )
        seen: list[Any] = []
        harness.on_event(seen.append)

        result = await harness.execute(task(allowed_tools=[]))

        assert result.status == "failed"
        assert [event.sequence for event in seen] == list(range(1, len(seen) + 1))
        terminal_error = result.error or ""
        session_json = json.dumps(
            session_records(tmp_path / "sessions"), ensure_ascii=False
        )
        serialized = json.dumps(
            [event.to_plain() for event in seen], ensure_ascii=False
        )
        for secret in (
            "access-secret",
            "api-secret",
            "session-secret",
            "bearer-secret",
            "query-secret",
            "pem-secret",
        ):
            assert secret not in serialized
            assert secret not in terminal_error
            assert secret not in session_json
        assert "<redacted>" in serialized
        assert "<truncated>" in serialized
        assert "<truncated>" in terminal_error
        assert harness.listener_error_count == bus.listener_error_count

    run(scenario())


def test_dynamic_tool_handler_receives_current_turn_permissions(tmp_path: Path) -> None:
    async def scenario() -> None:
        contexts: list[dict[str, Any]] = []

        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            contexts.append(context.to_plain())
            return ToolResult(call.call_id, "ok")

        provider = ScriptedProvider(
            [
                final_call("call-1", "search_sources"),
                final_call("call-2", "fetch_page"),
                final_text("done"),
            ]
        )
        harness = AgentHarness(
            provider,
            [tool("search_sources", handler), tool("fetch_page", handler)],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        def switch_after_first_turn(event: Any) -> None:
            if event.event_type == "turn_started" and event.payload["turn_index"] == 1:
                harness.set_next_turn_tools(["fetch_page"])

        harness.on_event(switch_after_first_turn)
        result = await harness.execute(task())

        assert result.status == "completed"
        assert [context["permissions"]["active_tool_names"] for context in contexts] == [
            ["search_sources"],
            ["fetch_page"],
        ]
        for context in contexts:
            assert context["permissions"]["object_read_scopes"] == [
                "ResearchProblem",
                "EvidenceCard",
            ]
            assert context["permissions"]["object_write_scopes"] == ["EvidenceCard"]

    run(scenario())


def test_tool_trace_actor_and_tool_identity_are_controlled(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
            del context
            return ToolResult(
                call.call_id,
                "ok",
                trace_proposals=(
                    TraceProposal(
                        "spoofed-trace",
                        "tool_observation",
                        "spoofed-actor",
                        {"tool_name": "spoofed-tool", "value": "safe"},
                    ),
                ),
            )

        store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
        provider = ScriptedProvider(
            [final_call("call-1", "create_evidence_card"), final_text("done")]
        )
        harness = AgentHarness(
            provider,
            [tool("create_evidence_card", handler)],
            store,
            sessions_root=tmp_path / "sessions",
        )
        await harness.execute(task(allowed_tools=["create_evidence_card"]))

        trace = next(
            event for event in store.trace_events() if event["proposal_id"] == "spoofed-trace"
        )
        assert trace["actor"] == "agent-a"
        assert trace["payload"]["tool_name"] == "create_evidence_card"
        assert trace["payload"]["tool_call_id"] == "call-1"

    run(scenario())


def test_listener_self_cancellation_isolated_but_real_task_cancellation_propagates(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([final_text("done")])
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        async def self_cancel(event: Any) -> None:
            if event.event_type == "assistant_message":
                raise asyncio.CancelledError("listener-only")

        harness.on_event(self_cancel)
        result = await harness.execute(task(allowed_tools=[]))

        assert result.status == "completed"
        assert harness.listener_error_count == 1

    run(scenario())


def test_async_listener_base_exceptions_are_isolated_and_auditable(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([final_text("done")])
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )
        seen: list[str] = []

        async def unstable_listener(event: Any) -> None:
            if event.event_type == "turn_snapshot":
                raise GeneratorExit("listener generator exit")
            if event.event_type == "assistant_message":
                raise asyncio.CancelledError("listener cancelled")

        harness.on_event(unstable_listener)
        harness.on_event(lambda event: seen.append(event.event_type))

        result = await harness.execute(task(allowed_tools=[]))

        assert result.status == "completed"
        assert seen[-1] == "task_completed"
        assert "turn_end" in seen
        assert harness.listener_error_count == 2
        assert {
            (record["event_type"], record["error_type"])
            for record in harness.listener_errors
        } == {
            ("turn_snapshot", "GeneratorExit"),
            ("assistant_message", "CancelledError"),
        }

    run(scenario())


def test_parent_cancellation_while_awaiting_listener_is_not_isolated(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        listener_started = asyncio.Event()
        provider = ScriptedProvider([final_text("must not run")])
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        async def blocking_listener(event: Any) -> None:
            if event.event_type == "turn_snapshot":
                listener_started.set()
                await asyncio.Event().wait()

        harness.on_event(blocking_listener)
        execution = asyncio.create_task(harness.execute(task(allowed_tools=[])))
        await listener_started.wait()
        execution.cancel("caller cancelled during listener")

        with pytest.raises(
            asyncio.CancelledError,
            match="caller cancelled during listener",
        ):
            await execution

        assert provider.calls == 0
        assert harness.listener_error_count == 0
        assert session_records(tmp_path / "sessions")[-1]["event_type"] == (
            "task_cancelled"
        )

    run(scenario())


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_async_listener_process_level_errors_are_rethrown(
    tmp_path: Path,
    error_type: type[BaseException],
) -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([final_text("must not run")])
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )

        async def process_error_listener(event: Any) -> None:
            if event.event_type == "task_received":
                raise error_type("listener process error")

        harness.on_event(process_error_listener)

        with pytest.raises(error_type, match="listener process error"):
            await harness.execute(task(allowed_tools=[]))

        assert provider.calls == 0
        assert harness.listener_error_count == 0

    run(scenario())


def test_session_uses_safe_projections_and_never_persists_raw_secrets(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        provider = ScriptedProvider([final_text("assistant secret-value")])
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
            model_options={"authorization": "Bearer model-secret"},
        )
        await harness.execute(
            task(
                allowed_tools=[],
                objective="objective secret-value",
                research_questions=["question secret-value"],
                context_refs=[
                    "https://example.test/context?access_token=query-secret",
                    "cookie=session-secret",
                ],
                evidence_refs=["api_key=evidence-secret"],
            )
        )

        persisted = json.dumps(
            session_records(tmp_path / "sessions"), ensure_ascii=False
        )
        assert "secret-value" not in persisted
        assert "model-secret" not in persisted
        assert "Bearer" not in persisted
        assert "query-secret" not in persisted
        assert "session-secret" not in persisted
        assert "evidence-secret" not in persisted
        received = session_records(tmp_path / "sessions")[0]
        assert received["context_refs"]["count"] == 2
        assert received["evidence_refs"]["count"] == 1
        assert all(
            ref.startswith("sha256:") for ref in received["context_refs"]["refs"]
        )
        assert "<redacted>" in persisted

    run(scenario())


def test_savepoint_session_failure_is_marked_in_database_for_reconciliation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = tmp_path / "run.db"
        sessions_root = tmp_path / "sessions"
        store = SqliteRunStore(database, run_id="run-1")

        async def create_evidence(
            call: ToolCall,
            context: ToolExecutionContext,
        ) -> ToolResult:
            del context
            return ToolResult(
                call.call_id,
                "created",
                domain_proposals=(
                    DomainWriteProposal(
                        "recovery-domain",
                        "EvidenceCard",
                        "upsert",
                        {
                            "evidence_id": "recovery-evidence",
                            "claim": "persist once",
                            "schema_version": "1.0",
                            "created_at": CREATED_AT,
                        },
                        "recovery-evidence",
                    ),
                ),
            )

        def session_factory(path: str, root_dir: Path) -> FailSavepointOnceSession:
            return FailSavepointOnceSession(path, root_dir=root_dir)

        harness = AgentHarness(
            ScriptedProvider([final_call("call-1", "create_evidence_card")]),
            [tool("create_evidence_card", create_evidence)],
            store,
            sessions_root=sessions_root,
            session_store_factory=session_factory,
        )

        result = await harness.execute(task(allowed_tools=["create_evidence_card"]))

        assert result.status == "failed"
        assert store.count("EvidenceCard") == 1
        events = store.trace_events()
        reconciliation = next(
            event for event in events if event["event_type"] == "session_write_failed"
        )
        assert reconciliation["actor"] == "agent-a"
        assert reconciliation["payload"]["session_event"] == "savepoint"
        assert reconciliation["payload"]["turn_index"] == 1
        assert reconciliation["payload"]["batch_hash"].startswith("sha256:")
        assert reconciliation["payload"]["committed_checkpoint_id"].startswith(
            "checkpoint-"
        )
        assert store.recover()["checkpoint_id"] == result.checkpoint_id
        unresolved = store.recover()["unresolved_session_writes"]
        assert len(unresolved) == 1
        marker = unresolved[0]
        assert marker["checkpoint_id"] == reconciliation["payload"][
            "committed_checkpoint_id"
        ]
        assert marker["batch_hash"] == reconciliation["payload"]["batch_hash"]
        assert marker["turn_index"] == 1
        assert marker["task_id"] == "task-1"
        assert marker["agent_id"] == "agent-a"
        assert marker["session_ref"].endswith(".jsonl")

        original_session = sessions_root / marker["session_ref"]
        records = [
            json.loads(line)
            for line in original_session.read_text(encoding="utf-8").splitlines()
        ]
        assert [record["event_type"] for record in records][-2:] == [
            "savepoint_pending",
            "task_failed",
        ]
        persisted = json.dumps(records)
        assert "session-secret" not in persisted

        restarted_store = SqliteRunStore(database, run_id="run-1")
        restarted_provider = ScriptedProvider([final_text("restart complete")])
        restarted = AgentHarness(
            restarted_provider,
            [],
            restarted_store,
            sessions_root=sessions_root,
        )
        restarted_result = await restarted.execute(task(allowed_tools=[]))

        assert restarted_result.status == "completed"
        assert restarted_provider.calls == 1
        assert restarted_store.count("EvidenceCard") == 1
        assert restarted_store.recover()["unresolved_session_writes"] == []
        repaired_records = [
            json.loads(line)
            for line in original_session.read_text(encoding="utf-8").splitlines()
        ]
        assert [
            record["event_type"]
            for record in repaired_records
            if record.get("reconciliation_marker_id") == marker["marker_id"]
        ] == ["savepoint", "session_reconciled"]
        reconciled_traces = [
            event
            for event in restarted_store.trace_events()
            if event["event_type"] == "session_reconciled"
        ]
        assert len(reconciled_traces) == 1
        assert reconciled_traces[0]["payload"]["marker_id"] == marker["marker_id"]

        repaired_line_count = len(repaired_records)
        third_store = SqliteRunStore(database, run_id="run-1")
        third = AgentHarness(
            ScriptedProvider([final_text("third start")]),
            [],
            third_store,
            sessions_root=sessions_root,
        )
        await third.execute(task(allowed_tools=[]))

        assert third_store.count("EvidenceCard") == 1
        assert len(
            [
                event
                for event in third_store.trace_events()
                if event["event_type"] == "session_reconciled"
            ]
        ) == 1
        assert len(original_session.read_text(encoding="utf-8").splitlines()) == (
            repaired_line_count
        )

    run(scenario())


def test_unwritable_reconciliation_session_prevents_provider_start(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "run.db"
        sessions_root = tmp_path / "sessions"
        first_store = SqliteRunStore(database, run_id="run-1")

        def fail_savepoint(path: str, root_dir: Path) -> FailSavepointOnceSession:
            return FailSavepointOnceSession(path, root_dir=root_dir)

        first = AgentHarness(
            ScriptedProvider([final_text("committed")]),
            [],
            first_store,
            sessions_root=sessions_root,
            session_store_factory=fail_savepoint,
        )
        first_result = await first.execute(task(allowed_tools=[]))
        assert first_result.status == "failed"
        assert first_store.recover()["unresolved_session_writes"]

        def fail_all(path: str, root_dir: Path) -> FailAllSessionWrites:
            return FailAllSessionWrites(path, root_dir=root_dir)

        blocked_provider = ScriptedProvider([final_text("must not run")])
        blocked = AgentHarness(
            blocked_provider,
            [],
            SqliteRunStore(database, run_id="run-1"),
            sessions_root=sessions_root,
            session_store_factory=fail_all,
        )

        blocked_result = await blocked.execute(task(allowed_tools=[]))

        assert blocked_result.status == "failed"
        assert blocked_provider.calls == 0

    run(scenario())


def test_execution_result_has_stable_utc_schema_contract(tmp_path: Path) -> None:
    provider = ScriptedProvider([final_text("done")])
    harness = AgentHarness(
        provider,
        [],
        SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
        sessions_root=tmp_path / "sessions",
    )

    result = run(harness.execute(task(allowed_tools=[])))

    assert result.execution_id.startswith("execution-")
    assert result.task_id == "task-1"
    assert result.agent_id == "agent-a"
    assert result.schema_version == "1.0"
    assert datetime.fromisoformat(result.created_at).utcoffset() is not None
    assert result.snapshots[0].schema_version == "1.0"
    assert datetime.fromisoformat(result.snapshots[0].created_at).utcoffset() is not None
    json.dumps(result.to_plain(), allow_nan=False)


def test_cancellation_propagates_after_safe_terminal_record(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = BlockingProvider()
        harness = AgentHarness(
            provider,
            [],
            SqliteRunStore(tmp_path / "run.db", run_id="run-1"),
            sessions_root=tmp_path / "sessions",
        )
        execution = asyncio.create_task(harness.execute(task(allowed_tools=[])))
        await provider.started.wait()
        execution.cancel("caller cancelled")

        with pytest.raises(asyncio.CancelledError, match="caller cancelled"):
            await execution

        records = session_records(tmp_path / "sessions")
        assert records[-1]["event_type"] == "task_cancelled"
        assert "caller cancelled" not in json.dumps(records)

    run(scenario())


def test_phase_zero_permission_registry_api_is_preserved() -> None:
    registry = ToolPermissionRegistry.default()
    assert "fetch_page" in registry.known_tools
    assert callable(registry.validate_agent_tools)
    assert callable(registry.enforce_active_tool)


def test_workspace_free_scheduler_close_releases_artifact_fd_idempotently(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    scheduler = DiscoveryScheduler(
        run_id="run-1",
        run_dir=run_dir,
        provider=object(),  # type: ignore[arg-type]
        store=DomainStore(),
        trace=TraceStore(),
    )
    descriptor = scheduler.materializer.artifacts._root_fd
    assert descriptor is not None

    scheduler.close()
    scheduler.close()

    with pytest.raises(OSError):
        os.fstat(descriptor)
