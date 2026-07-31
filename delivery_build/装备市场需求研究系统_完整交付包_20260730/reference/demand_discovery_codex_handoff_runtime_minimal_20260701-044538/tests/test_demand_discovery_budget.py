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
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.events import AgentEvent  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    AgentMessage,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.workers.prompts import (  # noqa: E402
    WRAP_UP_PROMPT,
)


class RecordingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.request_messages: list[list[AgentMessage]] = []
        self.request_tool_names: list[list[str]] = []

    def stream(self, context, tools, options):
        self.request_messages.append(list(context.messages))
        self.request_tool_names.append([tool.name for tool in tools])
        return super().stream(context, tools, options)


class DemandDiscoveryBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_budget_exhaustion_injects_wrap_up_next_request(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(
                    text="large enough response to exceed the tiny budget",
                    tool_calls=[{"id": "c1", "name": "noop", "arguments": {}}],
                ),
                FakeResponse(text="wrapped"),
            ]
        )
        events: list[AgentEvent] = []
        harness = DiscoveryHarness(
            provider=provider,
            tools=[_tool("noop")],
            budget=RunBudget(max_tokens=1),
        )
        harness.subscribe(events.append)

        await harness.prompt("start")

        second_request_texts = [
            str(message.content) for message in provider.request_messages[1]
        ]
        self.assertTrue(any(WRAP_UP_PROMPT in item for item in second_request_texts))
        exhausted = [event for event in events if event.type == "budget_exhausted"]
        self.assertEqual(len(exhausted), 1)
        self.assertEqual(exhausted[0].payload["dimension"], "tokens")

    async def test_wrap_up_allows_two_provider_requests_then_stops(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(
                    text="overspend",
                    tool_calls=[{"id": "c1", "name": "noop", "arguments": {}}],
                ),
                FakeResponse(
                    text="wrap one",
                    tool_calls=[{"id": "c2", "name": "noop", "arguments": {}}],
                ),
                FakeResponse(
                    text="wrap two",
                    tool_calls=[{"id": "c3", "name": "noop", "arguments": {}}],
                ),
                FakeResponse(text="must not be consumed"),
            ]
        )
        harness = DiscoveryHarness(
            provider=provider,
            tools=[_tool("noop")],
            budget=RunBudget(max_tokens=1),
        )

        await harness.prompt("start")

        self.assertEqual(len(provider.request_messages), 3)
        self.assertEqual(provider.pending_count(), 1)

    async def test_max_tool_calls_triggers_budget_exhausted(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "noop", "arguments": {}}]
                ),
                FakeResponse(text="wrapped"),
            ]
        )
        events: list[AgentEvent] = []
        harness = DiscoveryHarness(
            provider=provider,
            tools=[_tool("noop")],
            budget=RunBudget(max_tool_calls=1),
        )
        harness.subscribe(events.append)

        await harness.prompt("start")

        exhausted = [event for event in events if event.type == "budget_exhausted"]
        self.assertEqual(len(exhausted), 1)
        self.assertEqual(exhausted[0].payload["dimension"], "tool_calls")

    async def test_wrap_up_blocks_cost_expanding_tools(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(
                    text="overspend",
                    tool_calls=[{"id": "c1", "name": "noop", "arguments": {}}],
                ),
                FakeResponse(
                    tool_calls=[
                        {"id": "c2", "name": "search_sources", "arguments": {}}
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        search_ran = False

        async def search_sources(
            call: ToolCall, ctx: ToolExecutionContext
        ) -> ToolResult:
            nonlocal search_ran
            search_ran = True
            return ToolResult(call.id, call.name, "searched", {})

        events: list[AgentEvent] = []
        harness = DiscoveryHarness(
            provider=provider,
            tools=[_tool("noop"), _tool("search_sources", search_sources)],
            budget=RunBudget(max_tokens=1),
        )
        harness.subscribe(events.append)

        await harness.prompt("start")

        self.assertFalse(search_ran)
        blocked = [event for event in events if event.type == "budget_tool_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].payload["tool_name"], "search_sources")
        tool_messages = [m for m in harness.messages if m.role == "tool_result"]
        self.assertTrue(tool_messages[-1].is_error)
        self.assertIn("预算已进入收尾态", str(tool_messages[-1].content))

    async def test_without_budget_cost_expanding_tools_are_not_blocked(self) -> None:
        provider = RecordingProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {"id": "c1", "name": "search_sources", "arguments": {}}
                    ]
                ),
                FakeResponse(text="done"),
            ]
        )
        search_ran = False

        async def search_sources(
            call: ToolCall, ctx: ToolExecutionContext
        ) -> ToolResult:
            nonlocal search_ran
            self.assertEqual(ctx.budget_state, "normal")
            search_ran = True
            return ToolResult(call.id, call.name, "searched", {})

        harness = DiscoveryHarness(
            provider=provider,
            tools=[_tool("search_sources", search_sources)],
        )

        await harness.prompt("start")

        self.assertTrue(search_ran)


def _tool(name: str, execute=None) -> ToolDefinition:
    async def default_execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        return ToolResult(call.id, call.name, "ok", {})

    return ToolDefinition(
        name=name,
        description="",
        parameters_schema={"type": "object", "properties": {}},
        execute=execute or default_execute,
    )


if __name__ == "__main__":
    unittest.main()
