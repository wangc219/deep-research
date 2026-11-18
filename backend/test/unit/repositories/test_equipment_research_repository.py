from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.repositories.equipment_research_repository import (
    EquipmentResearchRepository,
)


@pytest.mark.asyncio
async def test_event_writes_remove_nested_nul_characters() -> None:
    """单条与批量事件都必须在 PostgreSQL JSONB 边界移除 NUL。"""

    added: list[object] = []
    added_batches: list[list[object]] = []
    session = SimpleNamespace(
        add=added.append,
        add_all=lambda rows: added_batches.append(list(rows)),
        flush=AsyncMock(),
    )
    repository = EquipmentResearchRepository(session)
    repository.next_event_sequence = AsyncMock(side_effect=[1, 2])

    event = await repository.append_event(
        "run-1",
        "run\x00resumed",
        {"message\x00": "恢复\x00执行", "nested": ["A\x00B", {"value": "\x00C"}]},
    )
    batch = await repository.append_events(
        "run-1",
        [
            (
                "trace\x00event",
                {
                    "payload": {
                        "summary": "前\x00沿",
                        "literal_escape": "保留\\u0000文本",
                        "slash_then_nul": "保留反斜杠\\\x00并清除空字符",
                    }
                },
            )
        ],
    )

    assert event.event_type == "runresumed"
    assert event.payload == {
        "message": "恢复执行",
        "nested": ["AB", {"value": "C"}],
    }
    assert batch[0].event_type == "traceevent"
    assert batch[0].payload == {
        "payload": {
            "summary": "前沿",
            "literal_escape": "保留\\u0000文本",
            "slash_then_nul": "保留反斜杠\\并清除空字符",
        }
    }
    assert added == [event]
    assert added_batches == [batch]
    assert session.flush.await_count == 2
