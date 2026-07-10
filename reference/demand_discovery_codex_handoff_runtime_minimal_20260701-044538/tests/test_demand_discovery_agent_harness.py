from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.agent_harness import (  # noqa: E402
    DiscoveryHarness,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent  # noqa: E402
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
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402


def _text_provider(*texts: str) -> FakeProvider:
    provider = FakeProvider()
    provider.set_responses([FakeResponse(text=t) for t in texts])
    return provider


class DemandDiscoveryHarnessPhaseTests(unittest.TestCase):
    def test_prompt_returns_assistant_message_and_returns_to_idle(self) -> None:
        harness = DiscoveryHarness(provider=_text_provider("answer"))
        self.assertEqual(harness.phase, "idle")

        message = asyncio.run(harness.prompt("hello"))

        self.assertEqual(message.role, "assistant")
        self.assertEqual(message.content[0].text, "answer")
        self.assertEqual(harness.phase, "idle")

    def test_settled_event_emitted_after_prompt(self) -> None:
        harness = DiscoveryHarness(provider=_text_provider("a"))
        seen: list[str] = []
        harness.subscribe(lambda e: seen.append(e.type))

        asyncio.run(harness.prompt("hi"))

        self.assertIn("save_point", seen)
        self.assertIn("settled", seen)
        # settled is the last harness event
        self.assertEqual(seen[-1], "settled")

    def test_next_turn_preserved_for_following_prompt(self) -> None:
        # First prompt produces "first"; a queued next_turn message should be
        # injected into the *next* prompt, not the current one.
        harness = DiscoveryHarness(provider=_text_provider("first", "second"))
        harness.next_turn("inject-me")

        asyncio.run(harness.prompt("go"))
        # the next_turn queue is consumed at the start of the next prompt
        self.assertEqual(harness.pending_next_turn_count(), 1)

        asyncio.run(harness.prompt("go-again"))
        self.assertEqual(harness.pending_next_turn_count(), 0)

    def test_abort_clears_steer_and_follow_up_but_keeps_next_turn(self) -> None:
        harness = DiscoveryHarness(provider=_text_provider("x"))
        harness.steer("steer-msg")
        harness.follow_up("follow-msg")
        harness.next_turn("next-msg")

        harness.abort()

        self.assertEqual(harness.pending_steer_count(), 0)
        self.assertEqual(harness.pending_follow_up_count(), 0)
        self.assertEqual(harness.pending_next_turn_count(), 1)

    def test_provider_error_settles_and_returns_to_idle(self) -> None:
        def boom(context, state) -> AssistantMessage:
            raise RuntimeError("provider failure")

        provider = FakeProvider()
        provider.set_responses([FakeResponse(factory=boom)])
        harness = DiscoveryHarness(provider=provider)
        seen: list[str] = []
        harness.subscribe(lambda e: seen.append(e.type))

        message = asyncio.run(harness.prompt("go"))

        self.assertTrue(message.is_error)
        self.assertEqual(harness.phase, "idle")
        self.assertEqual(
            seen,
            [
                "agent_start",
                "turn_start",
                "message_start",
                "message_end",
                "message_appended",
                "turn_end",
                "save_point",
                "agent_end",
                "settled",
            ],
        )


class DemandDiscoveryHarnessSavePointTests(unittest.TestCase):
    def _proposal_tool(self) -> ToolDefinition:
        async def make_evidence(
            call: ToolCall, ctx: ToolExecutionContext
        ) -> ToolResult:
            return ToolResult(
                tool_call_id=call.id,
                tool_name=call.name,
                content="created evidence",
                details={"evidence_id": "ev-1"},
                domain_proposals=[
                    DomainWriteProposal(
                        action="upsert",
                        object_type="EvidenceCard",
                        payload={"evidence_id": "ev-1"},
                    )
                ],
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-1",
                        payload_summary="created ev-1",
                        output_refs=["ev-1"],
                    )
                ],
            )

        return ToolDefinition(
            name="make_evidence",
            description="",
            parameters_schema={"type": "object", "properties": {}},
            execute=make_evidence,
        )

    def test_proposals_flush_only_at_save_point(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {"id": "c1", "name": "make_evidence", "arguments": {}}
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        flushed: list[tuple[int, int]] = []

        harness = DiscoveryHarness(provider=provider, tools=[self._proposal_tool()])

        def on_save_point(domain, trace) -> None:
            flushed.append((len(domain), len(trace)))

        harness.on_save_point(on_save_point)

        asyncio.run(harness.prompt("go"))

        # exactly one domain proposal and one trace proposal flushed at save point
        self.assertEqual(flushed, [(1, 1)])
        # after flush the pending queues are empty
        self.assertEqual(harness.pending_domain_proposal_count(), 0)
        self.assertEqual(harness.pending_trace_proposal_count(), 0)

    def test_set_active_tools_affects_only_next_request(self) -> None:
        harness = DiscoveryHarness(provider=_text_provider("a", "b"))
        harness.set_active_tools(["make_evidence"])
        self.assertEqual(harness.active_tool_names, ["make_evidence"])
        # changing active tools does not raise mid-idle and is recorded
        harness.set_active_tools([])
        self.assertEqual(harness.active_tool_names, [])

    def test_turn_active_tool_update_affects_next_provider_request(self) -> None:
        class RecordingProvider(FakeProvider):
            def __init__(self) -> None:
                super().__init__()
                self.request_tool_names: list[list[str]] = []

            def stream(self, context, tools, options):
                self.request_tool_names.append([tool.name for tool in tools])
                return super().stream(context, tools, options)

        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "old", "arguments": {}}]
                ),
                FakeResponse(text="done"),
            ]
        )

        async def old(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(call.id, call.name, "ok", {})

        async def new(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(call.id, call.name, "ok", {})

        tools = [
            ToolDefinition("old", "", {"type": "object", "properties": {}}, old),
            ToolDefinition("new", "", {"type": "object", "properties": {}}, new),
        ]
        harness = DiscoveryHarness(provider=provider, tools=tools)
        harness.set_active_tools(["old"])

        def switch_tools(event: AgentEvent) -> None:
            if event.type == "tool_execution_end":
                harness.set_active_tools(["new"])

        harness.subscribe(switch_tools)

        asyncio.run(harness.prompt("go"))

        self.assertEqual(provider.request_tool_names, [["old"], ["new"]])

    def test_external_before_tool_call_hook_can_block_tool_execution(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "blocked", "arguments": {}}]
                ),
                FakeResponse(text="done"),
            ]
        )
        executed = False

        async def blocked(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            nonlocal executed
            executed = True
            return ToolResult(call.id, call.name, "should not run", {})

        def before(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult | None:
            return ToolResult(call.id, call.name, "blocked by hook", {}, is_error=True)

        harness = DiscoveryHarness(
            provider=provider,
            tools=[
                ToolDefinition(
                    "blocked",
                    "",
                    {"type": "object", "properties": {}},
                    blocked,
                )
            ],
            before_tool_call=before,
        )

        asyncio.run(harness.prompt("go"))

        self.assertFalse(executed)
        tool_results = [message for message in harness.messages if message.role == "tool_result"]
        self.assertEqual(tool_results[0].content, "blocked by hook")
        self.assertTrue(tool_results[0].is_error)

    def test_save_point_failed_domain_batch_leaves_store_unchanged(self) -> None:
        from knowledgegraph.demand_discovery.domain.store import DomainStore

        async def mixed_batch_tool(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(
                call.id,
                call.name,
                "mixed batch",
                {},
                domain_proposals=[
                    DomainWriteProposal(
                        action="upsert",
                        object_type="SourceRecord",
                        payload={
                            "source_id": "src-ok",
                            "title": "Source",
                            "source_name": "Demo",
                            "source_tier": "A",
                            "source_type": "demo",
                            "url_or_path": "demo://source",
                            "summary_text": "summary",
                            "summary_source": "model_generated",
                            "collection_decision": "use_as_evidence",
                        },
                    ),
                    DomainWriteProposal(
                        action="upsert",
                        object_type="EvidenceCard",
                        payload={
                            "evidence_id": "ev-bad",
                            "source_id": "missing-source",
                            "claim": "claim",
                            "evidence_summary": "summary",
                        },
                    ),
                ],
                trace_proposals=[
                    DomainTraceProposal(
                        event_type="source_seen",
                        target_type="SourceRecord",
                        target_id="src-ok",
                        payload_summary="source seen src-ok",
                        output_refs=["src-ok"],
                    ),
                    DomainTraceProposal(
                        event_type="evidence_created",
                        target_type="EvidenceCard",
                        target_id="ev-bad",
                        payload_summary="created evidence ev-bad",
                        input_refs=["missing-source"],
                        output_refs=["ev-bad"],
                    ),
                ],
            )

        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {"id": "c1", "name": "mixed_batch", "arguments": {}}
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        store = DomainStore()
        harness = DiscoveryHarness(
            provider=provider,
            tools=[
                ToolDefinition(
                    "mixed_batch",
                    "",
                    {"type": "object", "properties": {}},
                    mixed_batch_tool,
                )
            ],
            domain_store=store,
        )

        with self.assertRaises(Exception):
            asyncio.run(harness.prompt("go"))

        self.assertEqual(store.sources, {})
        self.assertEqual(store.evidence, {})
        self.assertEqual(store.trace_events, [])
        self.assertEqual(harness.phase, "idle")


if __name__ == "__main__":
    unittest.main()
