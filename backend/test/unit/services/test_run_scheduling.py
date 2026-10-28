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


@pytest.mark.parametrize("configured", ["auto", "0", "none", "unlimited"])
def test_subagent_user_capacity_can_follow_worker_backpressure(monkeypatch, configured):
    """长程分片不设固定每用户数量时，Worker 总槽位仍提供真实容量边界。"""
    monkeypatch.setenv("AGENT_USER_SUBAGENT_MAX_RUNNING", configured)

    assert scheduling.user_run_limit("subagent") is None


def test_explicit_user_capacity_is_still_supported(monkeypatch):
    """管理员仍可为共享环境配置公平性配额。"""
    monkeypatch.setenv("AGENT_USER_SUBAGENT_MAX_RUNNING", "7")

    assert scheduling.user_run_limit("subagent") == 7


def test_subagent_lane_capacity_follows_shared_resource_snapshot(monkeypatch):
    monkeypatch.setattr(
        "platform_core.services.resource_budget.read_budget",
        lambda: {"subagent_slots": 13},
    )

    assert scheduling.lane_run_limit("subagent") == 13
    assert scheduling.lane_run_limit("chat") is None


def test_subagent_lane_capacity_is_unbounded_when_governor_is_disabled(monkeypatch):
    monkeypatch.setattr("platform_core.services.resource_budget.read_budget", lambda: None)

    assert scheduling.lane_run_limit("subagent") is None


def test_tool_parallelism_uses_dynamic_capacity_only_when_enabled(monkeypatch):
    monkeypatch.setattr(scheduling, "lane_run_limit", lambda _lane: 13)
    monkeypatch.delenv("AGENT_ADAPTIVE_TOOL_PARALLELISM", raising=False)
    assert scheduling.tool_parallelism_limit(4) == 4

    monkeypatch.setenv("AGENT_ADAPTIVE_TOOL_PARALLELISM", "true")
    assert scheduling.tool_parallelism_limit(4) == 13
