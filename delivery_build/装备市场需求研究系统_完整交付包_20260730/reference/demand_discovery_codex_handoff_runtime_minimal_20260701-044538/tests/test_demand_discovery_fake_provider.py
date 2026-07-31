from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    AssistantContentBlock,
)
from knowledgegraph.demand_discovery.llm.fake_provider import (  # noqa: E402
    FakeProvider,
    FakeResponse,
)
from knowledgegraph.demand_discovery.llm.types import (  # noqa: E402
    AssistantMessage,
    LLMContext,
)


def _run_stream(provider: FakeProvider, context: LLMContext) -> AssistantMessage:
    async def scenario() -> AssistantMessage:
        stream = provider.stream(context, tools=[], options={})
        async for _ in stream:
            pass
        return stream.result()

    return asyncio.run(scenario())


class DemandDiscoveryFakeProviderTests(unittest.TestCase):
    def test_queued_responses_consumed_in_order(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [FakeResponse(text="first"), FakeResponse(text="second")]
        )
        context = LLMContext(messages=[])

        self.assertEqual(provider.pending_count(), 2)
        first = _run_stream(provider, context)
        self.assertEqual(first.text(), "first")
        self.assertEqual(provider.pending_count(), 1)
        second = _run_stream(provider, context)
        self.assertEqual(second.text(), "second")
        self.assertEqual(provider.pending_count(), 0)

    def test_exhausted_queue_returns_error_message(self) -> None:
        provider = FakeProvider()
        context = LLMContext(messages=[])

        message = _run_stream(provider, context)
        self.assertTrue(message.is_error)

    def test_append_responses_extends_queue(self) -> None:
        provider = FakeProvider()
        provider.set_responses([FakeResponse(text="a")])
        provider.append_responses([FakeResponse(text="b")])
        self.assertEqual(provider.pending_count(), 2)

    def test_response_factory_sees_context_and_call_count(self) -> None:
        seen: list[tuple[int, int]] = []

        def factory(context: LLMContext, state: dict) -> AssistantMessage:
            seen.append((len(context.messages), state["call_count"]))
            return AssistantMessage(
                content=[AssistantContentBlock(type="text", text="dynamic")]
            )

        provider = FakeProvider()
        provider.set_responses([FakeResponse(factory=factory)])
        context = LLMContext(messages=[object(), object()])  # type: ignore[list-item]

        message = _run_stream(provider, context)
        self.assertEqual(message.text(), "dynamic")
        self.assertEqual(seen, [(2, 1)])

    def test_assistant_message_can_include_text_and_tool_calls(self) -> None:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    text="calling",
                    tool_calls=[
                        {"id": "call-1", "name": "echo", "arguments": {"text": "hi"}}
                    ],
                )
            ]
        )
        context = LLMContext(messages=[])

        message = _run_stream(provider, context)
        self.assertEqual(message.text(), "calling")
        calls = message.tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "echo")
        self.assertEqual(calls[0].arguments, {"text": "hi"})

    def test_raised_exception_becomes_provider_error(self) -> None:
        def boom(context: LLMContext, state: dict) -> AssistantMessage:
            raise RuntimeError("provider failure")

        provider = FakeProvider()
        provider.set_responses([FakeResponse(factory=boom)])
        context = LLMContext(messages=[])

        async def scenario() -> list:
            stream = provider.stream(context, tools=[], options={})
            seen = []
            async for event in stream:
                seen.append(event)
            return seen

        events = asyncio.run(scenario())
        self.assertTrue(
            any(getattr(e, "type", None) == "error" for e in events)
        )


if __name__ == "__main__":
    unittest.main()
