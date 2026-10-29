"""交互投影合并新旧来源，完整统计不依赖浏览器逐页回放。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from platform_core.services import equipment_research_service as service


@pytest.mark.asyncio
async def test_compact_interactions_keep_new_postgres_events_and_richer_trace(monkeypatch):
    """文件落后时仍保留 PostgreSQL 新事件；同 ID 文件正文优先并只计一次。"""
    run = SimpleNamespace(
        id="run-merged", status="completed", payload={}, error="", topic="测试", research_route="auto"
    )

    def row(sequence, event_id, summary):
        """构造与 PostgreSQL 事件信封一致的记录。"""
        return {
            "sequence": sequence,
            "event_type": "run_result_saved",
            "payload": {"event_id": event_id, "event_type": "run_result_saved", "summary": summary},
        }

    pg_rows = [row(1, "shared", "旧摘要"), row(2, "new", "新增终态"), row(3, "new", "新增终态")]
    repo = SimpleNamespace(
        list_events=AsyncMock(return_value=[SimpleNamespace(to_dict=lambda r=r: r) for r in pg_rows])
    )
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(
        service, "_load_run_trace_and_summary", lambda _run: ([row(1, "shared", "文件中的丰富摘要")], {})
    )
    result = await service.get_run_interactions(db=object(), user=object(), run_id=run.id)
    assert result["counts"]["events"] == 2
    assert {e["event_id"]: e["summary"] for e in result["events"]} == {"shared": "文件中的丰富摘要", "new": "新增终态"}
    repo.list_events.assert_awaited_once_with(run.id, after_seq=0, limit=50_000)


@pytest.mark.asyncio
async def test_compact_event_count_remains_complete_with_large_postgres_history(monkeypatch):
    """2480 条记录只返回 120 条关键投影，完整计数与首尾事件保持正确。"""
    run = SimpleNamespace(id="run-large", status="completed", payload={}, error="", topic="测试", research_route="auto")
    rows = [
        SimpleNamespace(
            to_dict=lambda i=i: {
                "sequence": i + 1,
                "event_type": "run_result_saved",
                "payload": {"event_id": f"event-{i}", "event_type": "run_result_saved"},
            }
        )
        for i in range(2480)
    ]
    repo = SimpleNamespace(list_events=AsyncMock(return_value=rows))
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(service, "_load_run_trace_and_summary", lambda _run: ([], {}))
    result = await service.get_run_interactions(db=object(), user=object(), run_id=run.id)
    assert result["counts"]["events"] == 2480
    assert len(result["events"]) == 120
    assert result["events"][0]["event_id"] == "event-0"
    assert result["events"][-1]["event_id"] == "event-2479"
    assert repo.list_events.await_count == 1
