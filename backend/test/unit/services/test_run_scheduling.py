"""验证独立队列路由及每池健康检查，避免部署后静默投错队列。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager
import pytest

from platform_core.services import run_scheduling as scheduling
from platform_core.services import agent_run_service, readiness_service


@pytest.mark.parametrize(
    ("kind", "source", "slug", "lane"),
    [
        ("chat", "chat", "chatbot", "chat"),
        ("chat", "equipment_deep_research", "custom-deep", "deep"),
        ("resume", "chat", "deep-research", "deep"),
        ("subagent", "subagent", "research-child", "subagent"),
    ],
)
@pytest.mark.asyncio
async def test_persisted_run_routes_to_own_pool(monkeypatch, kind, source, slug, lane):
    monkeypatch.setenv("AGENT_RUN_SPLIT_QUEUES", "true")
    run = SimpleNamespace(run_type=kind, source=source, agent_slug=slug)
    pool = SimpleNamespace(enqueue_job=AsyncMock())

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr(agent_run_service, "get_arq_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(agent_run_service.pg_manager, "get_async_session_context", session)
    monkeypatch.setattr(
        agent_run_service, "AgentRunRepository", lambda db: SimpleNamespace(get_run=AsyncMock(return_value=run))
    )
    await agent_run_service.enqueue_agent_run("owned-run")
    pool.enqueue_job.assert_awaited_once_with(
        "process_agent_run", "owned-run", _job_id="run:owned-run", _queue_name=scheduling.AGENT_QUEUES[lane]
    )


@pytest.mark.asyncio
async def test_readiness_requires_every_enabled_pool(monkeypatch):
    monkeypatch.setenv("AGENT_RUN_SPLIT_QUEUES", "true")
    missing = scheduling.agent_health_key("deep")
    redis = SimpleNamespace(
        get=AsyncMock(side_effect=lambda key: None if key == missing else "healthy"),
        pttl=AsyncMock(return_value=1000),
    )
    monkeypatch.setattr(readiness_service, "get_redis_client", AsyncMock(return_value=redis))
    with pytest.raises(readiness_service.WorkerUnavailableError):
        await readiness_service._probe_worker()
