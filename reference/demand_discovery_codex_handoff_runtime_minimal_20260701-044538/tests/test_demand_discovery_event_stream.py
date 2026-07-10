from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.event_stream import (  # noqa: E402
    AsyncEventStream,
)


class DemandDiscoveryEventStreamTests(unittest.TestCase):
    def test_yields_events_in_pushed_order(self) -> None:
        async def scenario() -> list[int]:
            stream: AsyncEventStream = AsyncEventStream()

            async def producer() -> None:
                for value in (1, 2, 3):
                    stream.push(value)
                stream.end()

            asyncio.ensure_future(producer())
            seen: list[int] = []
            async for event in stream:
                seen.append(event)
            return seen

        self.assertEqual(asyncio.run(scenario()), [1, 2, 3])

    def test_end_stops_iteration_and_exposes_result(self) -> None:
        async def scenario() -> tuple[list[int], str]:
            stream: AsyncEventStream = AsyncEventStream()
            stream.push(10)
            stream.end("final-value")

            seen: list[int] = []
            async for event in stream:
                seen.append(event)
            return seen, stream.result()

        seen, result = asyncio.run(scenario())
        self.assertEqual(seen, [10])
        self.assertEqual(result, "final-value")

    def test_error_emits_error_event_and_finishes(self) -> None:
        async def scenario() -> list[Any]:
            stream: AsyncEventStream = AsyncEventStream()
            stream.push("ok")
            stream.error("boom")

            seen: list[Any] = []
            async for event in stream:
                seen.append(event)
            return seen

        seen = asyncio.run(scenario())
        # last event should signal the error; stream must terminate after it
        self.assertEqual(seen[0], "ok")
        self.assertEqual(len(seen), 2)
        error_event = seen[-1]
        self.assertTrue(
            getattr(error_event, "type", None) == "error"
            or (isinstance(error_event, dict) and error_event.get("type") == "error")
        )

    def test_error_marks_result_as_raising(self) -> None:
        async def scenario() -> None:
            stream: AsyncEventStream = AsyncEventStream()
            stream.error("boom")
            async for _ in stream:
                pass
            stream.result()

        with self.assertRaises(Exception):
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
