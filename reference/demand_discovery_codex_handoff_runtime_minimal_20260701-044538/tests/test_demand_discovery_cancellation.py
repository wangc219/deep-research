from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import threading
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.cancellation import (  # noqa: E402
    CancelToken,
    RunCancelled,
)
from knowledgegraph.demand_discovery.harness.session_store import (  # noqa: E402
    MemorySessionStore,
)
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.llm.model_config import ModelConfig  # noqa: E402
from knowledgegraph.demand_discovery.llm.responses_adapter import (  # noqa: E402
    ResponsesProvider,
)


class CancelTokenTests(unittest.TestCase):
    def test_cancel_propagates_to_derived_token(self) -> None:
        parent = CancelToken()
        child = parent.derive()

        parent.cancel("user_abort")

        self.assertTrue(child.cancelled)
        self.assertEqual(child.reason, "user_abort")
        with self.assertRaises(RunCancelled):
            child.raise_if_cancelled()

    def test_timeout_marks_token_cancelled(self) -> None:
        token = CancelToken(timeout_ms=1)

        async def wait_for_timeout() -> None:
            await asyncio.sleep(0.02)

        asyncio.run(wait_for_timeout())

        self.assertTrue(token.cancelled)
        self.assertEqual(token.reason, "timeout")


class DemandDiscoveryCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_abort_mid_turn_drops_pending_proposals_and_preserves_next_turn(
        self,
    ) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "call-source", "name": "make_source", "arguments": {}}]
                ),
                FakeResponse(
                    tool_calls=[
                        {"id": "call-fast", "name": "fast_evidence", "arguments": {}},
                        {"id": "call-slow", "name": "slow_evidence", "arguments": {}},
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        store = DomainStore()
        session = MemorySessionStore()
        harness = DiscoveryHarness(
            provider=provider,
            tools=[_source_tool(), _fast_evidence_tool(), _slow_evidence_tool()],
            domain_store=store,
            session_store=session,
        )
        harness.next_turn("preserved")
        settled: list[dict] = []
        harness.subscribe(
            lambda event: settled.append(event.payload)
            if event.type == "settled"
            else None
        )

        task = asyncio.create_task(harness.prompt("go"))
        await _wait_until(lambda: "src-1" in store.sources)
        await _wait_until(lambda: harness.pending_domain_proposal_count() >= 1)

        harness.abort()
        await asyncio.wait_for(task, timeout=1.0)

        self.assertEqual(harness.phase, "idle")
        self.assertEqual(harness.pending_next_turn_count(), 1)
        self.assertIn("src-1", store.sources)
        self.assertEqual(store.evidence, {})
        aborted_entries = [entry for entry in session.entries() if entry.type == "aborted"]
        self.assertEqual(len(aborted_entries), 1)
        self.assertEqual(aborted_entries[0].payload["dropped_domain"], 1)
        self.assertEqual(aborted_entries[0].payload["dropped_trace"], 1)
        self.assertEqual(settled[-1].get("aborted"), True)

        provider.append_responses([FakeResponse(text="after-abort")])
        message = await harness.prompt("again")
        self.assertFalse(message.is_error)

    async def test_tool_timeout_returns_error_result_and_loop_continues(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "call-timeout", "name": "timeout_tool", "arguments": {}}]
                ),
                FakeResponse(text="done-after-timeout"),
            ]
        )

        async def timeout_tool(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            await asyncio.sleep(0.1)
            return ToolResult(call.id, call.name, "late", {})

        tool = ToolDefinition(
            "timeout_tool",
            "",
            {"type": "object", "properties": {}},
            timeout_tool,
            timeout_ms=10,
        )
        harness = DiscoveryHarness(provider=provider, tools=[tool])

        message = await harness.prompt("go")

        self.assertEqual(message.content[0].text, "done-after-timeout")

    async def test_abort_before_real_provider_first_line_settles_quickly(self) -> None:
        transport_started = threading.Event()
        allow_transport_to_finish = threading.Event()

        def slow_transport(request, timeout_ms):
            transport_started.set()
            allow_transport_to_finish.wait(timeout=5)
            yield 'data: {"type":"response.output_text.delta","delta":"late"}'
            yield ""
            yield 'data: {"type":"response.completed"}'
            yield ""

        provider = ResponsesProvider(
            ModelConfig(provider="custom", model="gpt-test"),
            api_key="test-key",
            transport=slow_transport,
        )
        harness = DiscoveryHarness(provider=provider)
        settled: list[dict] = []
        harness.subscribe(
            lambda event: settled.append(event.payload)
            if event.type == "settled"
            else None
        )

        task = asyncio.create_task(harness.prompt("go"))
        started = await asyncio.to_thread(transport_started.wait, 1)
        self.assertTrue(started)

        harness.abort()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        finally:
            allow_transport_to_finish.set()

        self.assertEqual(harness.phase, "idle")
        self.assertEqual(settled[-1].get("aborted"), True)


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def _source_tool() -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        return ToolResult(
            call.id,
            call.name,
            "source",
            {},
            domain_proposals=[
                DomainWriteProposal(
                    "upsert",
                    "SourceRecord",
                    {
                        "source_id": "src-1",
                        "title": "Source",
                        "source_name": "Demo",
                        "source_tier": "A",
                        "source_type": "demo",
                        "url_or_path": "demo://src-1",
                    },
                )
            ],
            trace_proposals=[
                DomainTraceProposal(
                    "source_seen",
                    "SourceRecord",
                    "src-1",
                    "source seen",
                    output_refs=["src-1"],
                )
            ],
        )

    return ToolDefinition(
        "make_source",
        "",
        {"type": "object", "properties": {}},
        execute,
    )


def _fast_evidence_tool() -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        return ToolResult(
            call.id,
            call.name,
            "fast evidence",
            {},
            domain_proposals=[
                DomainWriteProposal(
                    "upsert",
                    "EvidenceCard",
                    {
                        "evidence_id": "ev-fast",
                        "source_id": "src-1",
                        "claim": "claim",
                        "evidence_summary": "summary",
                    },
                )
            ],
            trace_proposals=[
                DomainTraceProposal(
                    "evidence_created",
                    "EvidenceCard",
                    "ev-fast",
                    "created evidence",
                    input_refs=["src-1"],
                    output_refs=["ev-fast"],
                )
            ],
        )

    return ToolDefinition(
        "fast_evidence",
        "",
        {"type": "object", "properties": {}},
        execute,
    )


def _slow_evidence_tool() -> ToolDefinition:
    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        await asyncio.sleep(5)
        ctx.cancel_token.raise_if_cancelled()
        return ToolResult(call.id, call.name, "slow evidence", {})

    return ToolDefinition(
        "slow_evidence",
        "",
        {"type": "object", "properties": {}},
        execute,
    )


if __name__ == "__main__":
    unittest.main()
