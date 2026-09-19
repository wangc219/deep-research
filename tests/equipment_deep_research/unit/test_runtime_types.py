from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from equipment_deep_research.domain.proposals import DomainWriteProposal, TraceProposal
from equipment_deep_research.harness.event_bus import EventBus, sanitize_runtime_payload
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


def test_public_sanitizer_redacts_secrets_inside_strings_urls_and_pem() -> None:
    private_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "pem-secret-material\n"
        "-----END PRIVATE KEY-----"
    )
    safe = sanitize_runtime_payload(
        {
            "text": (
                "access_token=access-secret api_key=api-secret token=token-secret "
                "password=password-secret secret=secret-value cookie=session-secret "
                "Authorization: Bearer bearer-secret "
                "https://example.test/path?ok=1&access_token=query-secret "
                f"{private_key}"
            ),
            "long_error": "x" * 80 + " api_key=tail-secret",
        },
        max_string_length=48,
    )

    serialized = json.dumps(safe, ensure_ascii=False)
    for secret in (
        "access-secret",
        "api-secret",
        "token-secret",
        "password-secret",
        "secret-value",
        "session-secret",
        "bearer-secret",
        "query-secret",
        "pem-secret-material",
        "tail-secret",
    ):
        assert secret not in serialized
    assert "<redacted>" in serialized
    assert safe["long_error"].endswith("<truncated>")


def test_public_sanitizer_redacts_provider_and_hidden_reasoning_fields() -> None:
    safe = sanitize_runtime_payload(
        {
            "provider_metadata": {"model": "private"},
            "raw_session": "session-private",
            "raw_messages": ["hidden"],
            "nested": {"chain_of_thought": "hidden reasoning"},
            "visible": "kept",
        }
    )

    assert safe["provider_metadata"] == "<redacted>"
    assert safe["raw_session"] == "<redacted>"
    assert safe["raw_messages"] == "<redacted>"
    assert safe["nested"]["chain_of_thought"] == "<redacted>"
    assert safe["visible"] == "kept"


def test_event_bus_assigns_monotonic_sequences_per_run() -> None:
    bus = EventBus()

    first = bus.publish(RuntimeEvent("agent", "started", "run-1"))
    other_run = bus.publish(RuntimeEvent("agent", "started", "run-2"))
    second = bus.publish(RuntimeEvent("agent", "finished", "run-1"))

    assert [first.sequence, other_run.sequence, second.sequence] == [1, 1, 2]


def test_event_bus_seed_continues_above_authoritative_run_sequence() -> None:
    bus = EventBus(initial_sequences={"run-1": 7})

    first = bus.publish(RuntimeEvent("agent", "resumed", "run-1"))
    bus.seed("run-1", 3)
    second = bus.publish(RuntimeEvent("agent", "finished", "run-1"))

    assert [first.sequence, second.sequence] == [8, 9]


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


def test_cancelled_error_listener_is_isolated_and_next_event_is_delivered() -> None:
    bus = EventBus()
    seen: list[tuple[str, int]] = []
    failed_once = False

    def cancel_once(event: RuntimeEvent) -> None:
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise asyncio.CancelledError("listener cancelled itself")

    bus.subscribe(cancel_once)
    bus.subscribe(lambda event: seen.append((event.event_type, event.sequence)))

    first = bus.publish(RuntimeEvent("agent", "first", "run-1"))
    second = bus.publish(RuntimeEvent("agent", "second", "run-1"))

    assert (first.sequence, second.sequence) == (1, 2)
    assert seen == [("first", 1), ("second", 2)]
    assert bus.listener_error_count == 1


def test_process_level_listener_error_rethrows_after_drainer_cleanup() -> None:
    bus = EventBus()
    seen: list[int] = []
    failed_once = False

    def exit_once(_: RuntimeEvent) -> None:
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise SystemExit("stop")

    bus.subscribe(exit_once)
    bus.subscribe(lambda event: seen.append(event.sequence))

    with pytest.raises(SystemExit, match="stop"):
        bus.publish(RuntimeEvent("agent", "first", "run-1"))

    second = bus.publish(RuntimeEvent("agent", "second", "run-1"))

    assert second.sequence == 2
    assert seen == [2]


def test_same_run_concurrent_publish_is_delivered_strictly_in_sequence() -> None:
    bus = EventBus()
    first_started = Event()
    release_first = Event()
    observed: list[tuple[str, int]] = []

    def listener(event: RuntimeEvent) -> None:
        observed.append(("start", event.sequence))
        if event.sequence == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        observed.append(("end", event.sequence))

    bus.subscribe(listener)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            bus.publish,
            RuntimeEvent("tool", "first", "run-1"),
        )
        assert first_started.wait(timeout=2)
        second_future = executor.submit(
            bus.publish,
            RuntimeEvent("tool", "second", "run-1"),
        )
        assert not second_future.done()
        release_first.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert (first.sequence, second.sequence) == (1, 2)
    assert observed == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]


def test_reentrant_publish_waits_until_current_event_finishes_all_listeners() -> None:
    bus = EventBus()
    observed: list[str] = []
    nested_events: list[RuntimeEvent] = []

    def first_listener(event: RuntimeEvent) -> None:
        observed.append(f"first:{event.event_type}")
        if event.event_type == "outer":
            nested_events.append(bus.publish(RuntimeEvent("tool", "inner", "run-1")))
            observed.append("nested:return")

    def second_listener(event: RuntimeEvent) -> None:
        observed.append(f"second:{event.event_type}")

    bus.subscribe(first_listener)
    bus.subscribe(second_listener)

    outer = bus.publish(RuntimeEvent("tool", "outer", "run-1"))

    assert outer.sequence == 1
    assert nested_events[0].sequence == 2
    assert observed == [
        "first:outer",
        "nested:return",
        "second:outer",
        "first:inner",
        "second:inner",
    ]


def test_different_runs_have_independent_drainers() -> None:
    bus = EventBus()
    run_one_started = Event()
    release_run_one = Event()
    run_two_seen = Event()

    def listener(event: RuntimeEvent) -> None:
        if event.run_id == "run-1":
            run_one_started.set()
            assert release_run_one.wait(timeout=2)
        else:
            run_two_seen.set()

    bus.subscribe(listener)

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_one_future = executor.submit(
            bus.publish,
            RuntimeEvent("tool", "called", "run-1"),
        )
        assert run_one_started.wait(timeout=2)
        run_two_future = executor.submit(
            bus.publish,
            RuntimeEvent("tool", "called", "run-2"),
        )
        assert run_two_seen.wait(timeout=2)
        assert run_two_future.result(timeout=2).sequence == 1
        release_run_one.set()
        assert run_one_future.result(timeout=2).sequence == 1


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

    assert result.domain_proposals == (domain,)
    assert result.trace_proposals == (trace,)
    assert result.to_plain()["domain_proposals"][0]["proposal_id"] == "p1"
    assert result.to_plain()["trace_proposals"][0]["proposal_id"] == "t1"
    json.dumps(result.to_plain(), ensure_ascii=False, sort_keys=True)


def test_tool_result_rejects_proposals_in_the_wrong_channel() -> None:
    domain = DomainWriteProposal("p1", "EvidenceCard", "upsert", {}, "ev-1")
    trace = TraceProposal("t1", "created", "agent-a", {})

    with pytest.raises(TypeError, match="domain_proposals"):
        ToolResult("c1", "bad", domain_proposals=[trace])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="trace_proposals"):
        ToolResult("c1", "bad", trace_proposals=[domain])  # type: ignore[list-item]


def test_runtime_values_are_isolated_from_constructor_containers() -> None:
    event_payload = {"nested": {"items": ["original"]}}
    call_arguments = {"nested": {"items": ["original"]}}
    permissions = {"nested": {"items": ["original"]}}
    details = {"nested": {"items": ["original"]}}
    input_schema = {"properties": {"value": {"type": "string"}}}
    domain_payload = {"nested": {"items": ["original"]}}
    trace_payload = {"nested": {"items": ["original"]}}

    domain = DomainWriteProposal("p1", "EvidenceCard", "upsert", domain_payload, "ev-1")
    trace = TraceProposal("t1", "created", "agent-a", trace_payload)
    domain_proposals = [domain]
    trace_proposals = [trace]
    result = ToolResult(
        "c1",
        "ok",
        details,
        domain_proposals,
        trace_proposals,
    )

    async def handler(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        return result

    values = [
        RuntimeEvent("tool", "called", "run-1", event_payload),
        ToolCall("c1", "echo", call_arguments),
        ToolExecutionContext("run-1", "agent-a", permissions),
        result,
        ToolDefinition("echo", "Echo", input_schema, handler),
        domain,
        trace,
    ]

    event_payload["nested"]["items"].append("mutated")
    call_arguments["nested"]["items"].append("mutated")
    permissions["nested"]["items"].append("mutated")
    details["nested"]["items"].append("mutated")
    input_schema["properties"]["value"]["type"] = "number"
    domain_payload["nested"]["items"].append("mutated")
    trace_payload["nested"]["items"].append("mutated")
    domain_proposals.clear()
    trace_proposals.clear()

    for value in values:
        plain = value.to_plain()
        json.dumps(plain, ensure_ascii=False, sort_keys=True)

    assert values[0].to_plain()["payload"]["nested"]["items"] == ["original"]
    assert values[1].to_plain()["arguments"]["nested"]["items"] == ["original"]
    assert values[2].to_plain()["permissions"]["nested"]["items"] == ["original"]
    assert result.to_plain()["details"]["nested"]["items"] == ["original"]
    assert values[4].to_plain()["input_schema"]["properties"]["value"]["type"] == "string"
    assert domain.to_plain()["payload"]["nested"]["items"] == ["original"]
    assert trace.to_plain()["payload"]["nested"]["items"] == ["original"]
    assert result.domain_proposals == (domain,)
    assert result.trace_proposals == (trace,)


def test_listener_cannot_mutate_event_seen_by_later_subscribers() -> None:
    bus = EventBus()
    seen: list[dict[str, object]] = []

    def mutating_listener(event: RuntimeEvent) -> None:
        event.payload["status"] = "mutated"  # type: ignore[index]

    def recording_listener(event: RuntimeEvent) -> None:
        seen.append(event.to_plain()["payload"])

    bus.subscribe(mutating_listener)
    bus.subscribe(recording_listener)

    published = bus.publish(
        RuntimeEvent("tool", "called", "run-1", {"status": "original"})
    )

    assert bus.listener_error_count == 1
    assert seen == [{"status": "original"}]
    assert published.to_plain()["payload"] == {"status": "original"}


def test_runtime_values_reject_non_json_mutable_values() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        RuntimeEvent("tool", "called", "run-1", {"unsupported": {"mutable"}})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_runtime_values_reject_non_finite_floats(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        DomainWriteProposal(
            "p1",
            "EvidenceCard",
            "upsert",
            {"score": value},
            "save-e1",
        )


def test_runtime_values_support_strict_json_serialization() -> None:
    proposal = DomainWriteProposal(
        "p1",
        "EvidenceCard",
        "upsert",
        {"score": 0.5},
        "save-e1",
    )

    json.dumps(proposal.to_plain(), allow_nan=False)


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


def test_harness_imports_in_a_cold_python_process() -> None:
    root = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        [sys.executable, "-c", "from equipment_deep_research.harness.agent_harness import AgentHarness"],
        check=False,
        capture_output=True,
        text=True,
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
    )
    assert completed.returncode == 0, completed.stderr
