from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import pytest

from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal
from equipment_deep_research.harness.event_bus import EventBus
from equipment_deep_research.harness.events import RuntimeEvent
from equipment_deep_research.tools.definitions import (
    ToolCall,
    ToolDefinition,
    ToolExecutionContext,
    ToolResult,
)


def test_event_bus_redacts_credentials_and_truncates_payload() -> None:
    bus = EventBus(max_string_length=32)
    seen: list[RuntimeEvent] = []
    bus.subscribe(seen.append)

    bus.publish(
        RuntimeEvent(
            "tool",
            "called",
            "run-1",
            payload={
                "authorization": "Bearer secret",
                "nested": {
                    "api_key": "api-secret",
                    "items": [{"refresh_token": "token-secret"}],
                },
                "text": "x" * 100 + "TAIL-MUST-NOT-LEAK",
            },
        )
    )

    assert seen[0].payload["authorization"] == "<redacted>"
    assert seen[0].payload["nested"]["api_key"] == "<redacted>"
    assert seen[0].payload["nested"]["items"][0]["refresh_token"] == "<redacted>"
    assert seen[0].payload["text"].endswith("<truncated>")
    assert "TAIL-MUST-NOT-LEAK" not in seen[0].payload["text"]


def test_event_bus_assigns_monotonic_sequences_per_run() -> None:
    bus = EventBus()

    first = bus.publish(RuntimeEvent("agent", "started", "run-1"))
    other_run = bus.publish(RuntimeEvent("agent", "started", "run-2"))
    second = bus.publish(RuntimeEvent("agent", "finished", "run-1"))

    assert [first.sequence, other_run.sequence, second.sequence] == [1, 1, 2]


def test_subscriber_failure_is_isolated_without_reusing_sequence() -> None:
    bus = EventBus()
    seen: list[RuntimeEvent] = []

    def fail(_: RuntimeEvent) -> None:
        raise RuntimeError("subscriber failed")

    bus.subscribe(fail)
    bus.subscribe(seen.append)

    first = bus.publish(RuntimeEvent("tool", "called", "run-1"))
    second = bus.publish(RuntimeEvent("tool", "returned", "run-1"))

    assert [first.sequence, second.sequence] == [1, 2]
    assert [event.sequence for event in seen] == [1, 2]
    assert bus.listener_error_count == 2


def test_runtime_event_has_stable_transport_metadata() -> None:
    event = RuntimeEvent("tool", "called", "run-1")

    first = event.to_plain()
    second = event.to_plain()

    assert first["event_id"] == second["event_id"]
    assert first["event_id"].startswith("event-")
    assert first["schema_version"] == "1.0"
    created_at = datetime.fromisoformat(first["created_at"])
    assert created_at.utcoffset() == timezone.utc.utcoffset(created_at)
    json.dumps(first, ensure_ascii=False, sort_keys=True)


def test_tool_result_keeps_domain_and_trace_proposals_separate() -> None:
    domain = DomainWriteProposal(
        "p1",
        "EvidenceCard",
        "upsert",
        {"evidence_id": "ev-1"},
        "ev-1",
    )
    trace = TraceProposal(
        "t1",
        "evidence_created",
        "agent-a",
        {"evidence_id": "ev-1"},
    )
    result = ToolResult(
        call_id="c1",
        content="ok",
        domain_proposals=[domain],
        trace_proposals=[trace],
    )

    assert result.domain_proposals == [domain]
    assert result.trace_proposals == [trace]
    assert result.to_plain()["domain_proposals"][0]["proposal_id"] == "p1"
    assert result.to_plain()["trace_proposals"][0]["proposal_id"] == "t1"
    json.dumps(result.to_plain(), ensure_ascii=False, sort_keys=True)


def test_tool_definition_requires_async_handler_and_excludes_it_from_plain_data() -> None:
    async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            content=f"{context.agent_id}:{call.arguments['value']}",
        )

    definition = ToolDefinition(
        name="echo",
        description="Echo one value.",
        input_schema={"type": "object"},
        handler=handler,
    )
    call = ToolCall("call-1", "echo", {"value": "hello"})
    context = ToolExecutionContext("run-1", "agent-a")

    result = asyncio.run(definition.handler(call, context))

    assert result.content == "agent-a:hello"
    assert definition.to_plain() == {
        "name": "echo",
        "description": "Echo one value.",
        "input_schema": {"type": "object"},
    }
    json.dumps(definition.to_plain(), ensure_ascii=False, sort_keys=True)

    with pytest.raises(TypeError, match="async"):
        ToolDefinition("sync", "invalid", {}, lambda call, context: result)  # type: ignore[arg-type]


def test_runtime_values_are_plain_json_serializable() -> None:
    values = [
        ToolCall("call-1", "echo", {"value": [1, "two"]}),
        ToolExecutionContext("run-1", "agent-a", {"echo": True}),
        DomainWriteProposal("p1", "EvidenceCard", "append", {"id": "ev-1"}, "ev-1"),
        TraceProposal("t1", "created", "agent-a", {"id": "ev-1"}),
        RuntimeEvent("tool", "called", "run-1", payload={"ok": True}),
    ]

    for value in values:
        json.dumps(value.to_plain(), ensure_ascii=False, sort_keys=True)
