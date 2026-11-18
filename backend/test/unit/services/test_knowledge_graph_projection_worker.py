from __future__ import annotations

import asyncio

import pytest

from platform_core.services.knowledge_graph_projection_worker import (
    KnowledgeGraphProjectionWorker,
    start_knowledge_graph_projection_worker,
    stop_knowledge_graph_projection_worker,
)


class FakeGraphService:
    def __init__(self):
        self.calls: list[tuple[str | None, int]] = []

    async def replay_projection_outbox(self, kb_id: str | None, *, limit: int):
        self.calls.append((kb_id, limit))
        return {"claimed": 0, "completed": 0, "failed": 0}


@pytest.mark.asyncio
async def test_projection_worker_consumes_global_outbox_batch():
    service = FakeGraphService()
    worker = KnowledgeGraphProjectionWorker(service, batch_size=7, poll_seconds=0.01)

    result = await worker.run_once()

    assert result == {"claimed": 0, "completed": 0, "failed": 0}
    assert service.calls == [(None, 7)]


@pytest.mark.asyncio
async def test_projection_worker_follows_parent_worker_lifecycle(monkeypatch):
    calls = 0

    async def fake_run_forever(self):
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()

    monkeypatch.setattr(KnowledgeGraphProjectionWorker, "run_forever", fake_run_forever)
    ctx = {}

    start_knowledge_graph_projection_worker(ctx)
    await asyncio.sleep(0)
    await stop_knowledge_graph_projection_worker(ctx)

    assert calls == 1
    assert "knowledge_graph_projection_task" not in ctx
