from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.agent_loop import (  # noqa: E402
    AgentLoop,
    AgentLoopConfig,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent  # noqa: E402
from knowledgegraph.demand_discovery.harness.tools import (  # noqa: E402
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    AgentMessage,
    ToolCall,
    ToolResult,
    UserMessage,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402


async def _collect(loop: AgentLoop, **kwargs) -> tuple[list[AgentEvent], object]:
    stream = loop.run(**kwargs)
    events: list[AgentEvent] = []
    async for event in stream:
        events.append(event)
    return events, stream.result()


def _types(events: list[AgentEvent]) -> list[str]:
    return [e.type for e in events]


class DemandDiscoveryAgentLoopTests(unittest.TestCase):
    def test_no_tool_event_order(self) -> None:
        provider = FakeProvider()
        provider.set_responses([FakeResponse(text="hello")])
        loop = AgentLoop()

        events, _ = asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="hi", timestamp=1)],
                provider=provider,
                tools=[],
                config=AgentLoopConfig(),
            )
        )

        self.assertEqual(
            _types(events),
            [
                "agent_start",
                "turn_start",
                "message_start",
                "message_update",
                "message_end",
                "message_appended",
                "turn_end",
                "agent_end",
            ],
        )

    def test_final_messages_include_assistant(self) -> None:
        provider = FakeProvider()
        provider.set_responses([FakeResponse(text="answer")])
        loop = AgentLoop()

        _, final_messages = asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="q", timestamp=1)],
                provider=provider,
                tools=[],
                config=AgentLoopConfig(),
            )
        )

        roles = [m.role for m in final_messages]
        self.assertEqual(roles[0], "user")
        self.assertEqual(roles[-1], "assistant")

    def test_tool_calls_execute_and_append_results(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    text="calling",
                    tool_calls=[
                        {"id": "c1", "name": "echo", "arguments": {"text": "hi"}}
                    ],
                ),
                FakeResponse(text="done"),
            ]
        )

        async def echo(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(call.id, call.name, f"echo:{call.arguments['text']}", {})

        echo_tool = ToolDefinition(
            name="echo",
            description="",
            parameters_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
            execute=echo,
        )
        loop = AgentLoop()

        events, final_messages = asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="go", timestamp=1)],
                provider=provider,
                tools=[echo_tool],
                config=AgentLoopConfig(),
            )
        )

        tool_messages = [m for m in final_messages if m.role == "tool_result"]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].content, "echo:hi")
        self.assertIn("tool_execution_start", _types(events))
        self.assertIn("tool_execution_end", _types(events))

    def test_parallel_end_order_but_results_in_call_order(self) -> None:
        # tool "slow" is called first but finishes last; "fast" finishes first.
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {"id": "c1", "name": "slow", "arguments": {}},
                        {"id": "c2", "name": "fast", "arguments": {}},
                    ],
                ),
                FakeResponse(text="done"),
            ]
        )

        async def slow(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            await asyncio.sleep(0.05)
            return ToolResult(call.id, call.name, "slow-result", {})

        async def fast(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            await asyncio.sleep(0.01)
            return ToolResult(call.id, call.name, "fast-result", {})

        tools = [
            ToolDefinition("slow", "", {"type": "object", "properties": {}}, slow),
            ToolDefinition("fast", "", {"type": "object", "properties": {}}, fast),
        ]
        loop = AgentLoop()

        events, final_messages = asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="go", timestamp=1)],
                provider=provider,
                tools=tools,
                config=AgentLoopConfig(),
            )
        )

        # completion order: fast (c2) ends before slow (c1)
        end_events = [
            e for e in events if e.type == "tool_execution_end"
        ]
        end_ids = [e.payload["tool_call_id"] for e in end_events]
        self.assertEqual(end_ids, ["c2", "c1"])

        # but tool result messages are appended in original call order: c1, c2
        tool_messages = [m for m in final_messages if m.role == "tool_result"]
        self.assertEqual([m.tool_call_id for m in tool_messages], ["c1", "c2"])

    def test_all_terminate_stops_loop(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "stop", "arguments": {}}]
                ),
                # this second response must NOT be consumed because the loop stops
                FakeResponse(text="should-not-appear"),
            ]
        )

        async def stop(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(call.id, call.name, "stopping", {}, terminate=True)

        tools = [
            ToolDefinition("stop", "", {"type": "object", "properties": {}}, stop)
        ]
        loop = AgentLoop()

        _, _ = asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="go", timestamp=1)],
                provider=provider,
                tools=tools,
                config=AgentLoopConfig(),
            )
        )
        # one response still pending -> loop terminated after the tool batch
        self.assertEqual(provider.pending_count(), 1)

    def test_prepare_next_turn_called_before_next_request(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[{"id": "c1", "name": "noop", "arguments": {}}]
                ),
                FakeResponse(text="second-turn"),
            ]
        )

        calls: list[int] = []

        async def noop(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
            return ToolResult(call.id, call.name, "ok", {})

        def prepare_next_turn(state) -> None:
            calls.append(len(state.messages))

        tools = [
            ToolDefinition("noop", "", {"type": "object", "properties": {}}, noop)
        ]
        loop = AgentLoop()

        asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="go", timestamp=1)],
                provider=provider,
                tools=tools,
                config=AgentLoopConfig(prepare_next_turn=prepare_next_turn),
            )
        )
        # prepare_next_turn fired at least once before the second provider request
        self.assertGreaterEqual(len(calls), 1)

    def test_provider_error_keeps_lifecycle_and_returns_error_message(self) -> None:
        def boom(context, state) -> AssistantMessage:
            raise RuntimeError("provider failure")

        provider = FakeProvider()
        provider.set_responses([FakeResponse(factory=boom)])
        loop = AgentLoop()

        events, final_messages = asyncio.run(
            _collect(
                loop,
                messages=[UserMessage(content="go", timestamp=1)],
                provider=provider,
                tools=[],
                config=AgentLoopConfig(),
            )
        )

        self.assertEqual(
            _types(events),
            [
                "agent_start",
                "turn_start",
                "message_start",
                "message_end",
                "message_appended",
                "turn_end",
                "agent_end",
            ],
        )
        assistant = final_messages[-1]
        self.assertEqual(assistant.role, "assistant")
        self.assertTrue(assistant.is_error)
        self.assertEqual(
            assistant.metadata.get("error_message"), "provider failure"
        )


if __name__ == "__main__":
    unittest.main()
