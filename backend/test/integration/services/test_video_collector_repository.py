"""视频号设备协议的真实 PostgreSQL 归属、租约、撤销及并发重放验证。"""

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from platform_core.repositories import task_repository, video_collector_repository
from platform_core.repositories.video_collector_repository import VideoCollectorRepository
from platform_core.repositories.video_collector_repository import CollectorConflict
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_business import TaskRecord
from platform_core.storage.postgres.models_knowledge import VideoCollectorCapture, VideoCollectorDevice
from platform_core.utils.datetime_utils import utc_now_naive

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本文件只使用隔离 Schema。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """本文件不创建业务知识资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """本文件不使用沙盒。"""
    yield


@pytest.fixture
async def database(monkeypatch):
    """为每个测试创建独立 Schema，复用真实 PostgreSQL 锁与事务。"""
    schema = "pytest_video_" + uuid4().hex[:16]
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        for table in (TaskRecord.__table__, VideoCollectorDevice.__table__, VideoCollectorCapture.__table__):
            await connection.run_sync(table.create)
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    manager._initialized = True
    for module in (task_repository, video_collector_repository):
        monkeypatch.setattr(module, "pg_manager", manager)
    try:
        yield manager
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def seed(manager, *, task_type="wxchannels_transcribe"):
    """创建用户设备和正在持有有效租约的视频任务。"""
    device = SimpleNamespace(device_id="wxd_" + uuid4().hex, owner_uid="alice")
    repo = VideoCollectorRepository()
    await repo.enroll("alice", device_id=device.device_id, token="a" * 64, name="Alice PC", platform="macos")
    task_id = uuid4().hex
    async with manager.get_async_session_context() as session:
        session.add(
            TaskRecord(
                id=task_id,
                name="pytest video",
                type=task_type,
                status="running",
                result={"items": []},
                payload={
                    "operator_id": "alice",
                    "device_id": device.device_id,
                    "collection_mode": "personal",
                    "max_videos": 2,
                    "account": "账号",
                    "max_pages": 1,
                },
                worker_id="lease-a",
                lease_expires_at=utc_now_naive() + timedelta(minutes=2),
            )
        )
    return repo, device, task_id


async def test_heartbeat_only_dispatches_the_devices_own_task(database):
    repo, device, task_id = await seed(database)
    other = "wxd_" + uuid4().hex
    await repo.enroll("bob", device_id=other, token="b" * 64, name="Bob PC", platform="windows")
    assert await repo.heartbeat(other, {"channels_ready": True}) is None
    job = await repo.heartbeat(device.device_id, {"channels_ready": True})
    assert job["task_id"] == task_id and job["execution_id"] == "lease-a"
    assert "token" not in str(job)


async def test_duplicate_capture_commits_once_under_concurrency(database):
    repo, device, task_id = await seed(database)

    async def receive():
        return await repo.receive(
            device,
            task_id=task_id,
            execution_id="lease-a",
            sequence=1,
            kind="audio",
            detail={"oid": "v1", "object_key": "private"},
        )

    outcomes = await asyncio.gather(receive(), receive())
    assert sorted(outcomes) == [False, True]
    assert len(await repo.captures(task_id, "lease-a")) == 1


@pytest.mark.parametrize("change", ["owner", "device", "lease", "expired", "cancelled"])
async def test_stale_or_cross_scope_capture_is_rejected(database, change):
    repo, device, task_id = await seed(database)
    execution_id = "lease-a"
    if change == "owner":
        device.owner_uid = "bob"
    elif change == "device":
        device.device_id = "wxd_" + uuid4().hex
    elif change == "lease":
        execution_id = "previous-attempt"
    else:
        async with database.get_async_session_context() as session:
            task = await session.get(TaskRecord, task_id)
            if change == "expired":
                task.lease_expires_at = utc_now_naive() - timedelta(seconds=1)
            else:
                task.cancel_requested = 1
    with pytest.raises(CollectorConflict):
        await repo.receive(
            device, task_id=task_id, execution_id=execution_id, sequence=1, kind="audio", detail={"oid": "v1"}
        )


async def test_revoke_stops_video_task_and_blocks_already_authenticated_device(database):
    repo, device, task_id = await seed(database)
    assert await repo.revoke("alice", device.device_id)
    assert await repo.authenticate(device.device_id, "a" * 64) is None
    record = await task_repository.TaskRepository().get_by_id(task_id)
    assert record.cancel_requested
    with pytest.raises(CollectorConflict):
        await repo.receive(device, task_id=task_id, execution_id="lease-a", sequence=1, kind="audio", detail={})


async def test_discovery_task_accepts_only_public_video_list(database):
    repo, device, task_id = await seed(database, task_type="wxchannels_discover")
    with pytest.raises(CollectorConflict):
        await repo.receive(device, task_id=task_id, execution_id="lease-a", sequence=1, kind="audio", detail={})
    assert await repo.receive(
        device,
        task_id=task_id,
        execution_id="lease-a",
        sequence=1,
        kind="video_list",
        detail={"videos": [{"oid": "1", "title": "公开简介"}]},
    )


async def test_all_videos_accepts_sequence_above_old_hundred_limit(database):
    """全部任务允许第 101 条，同时保持有界序号和租约校验。"""
    repo, device, task_id = await seed(database)
    async with database.get_async_session_context() as session:
        task = await session.get(TaskRecord, task_id)
        task.payload = {**task.payload, "max_videos": None}
    assert await repo.receive(
        device, task_id=task_id, execution_id="lease-a", sequence=101, kind="audio", detail={"oid": "101"}
    )
    with pytest.raises(CollectorConflict):
        await repo.receive(device, task_id=task_id, execution_id="lease-a", sequence=202002, kind="complete", detail={})


async def test_sixteen_users_share_one_central_discovery_slot(database):
    """16 个用户同时提交时原子占用一个微信采集槽，完成后能继续调度。"""
    repo = task_repository.TaskRepository()
    ids = [uuid4().hex for _ in range(16)]
    async with database.get_async_session_context() as session:
        session.add_all(
            [
                TaskRecord(
                    id=task_id,
                    name="pytest shared collector",
                    type="wxchannels_central_discover",
                    status="pending",
                    payload={"operator_id": f"pytest-central-{i}"},
                    timeout_seconds=900,
                )
                for i, task_id in enumerate(ids)
            ]
        )
    claims = await asyncio.gather(
        *[
            repo.claim(
                task_id,
                worker_id=f"worker-{i}",
                lease_seconds=30,
                max_running=1,
                type_filter="wxchannels_central_discover",
                lock_scope="durable-task-capacity:wxchannels_central_discover",
            )
            for i, task_id in enumerate(ids)
        ]
    )
    assert sum(claimed for _, claimed in claims) == 1
    winner = next(row for row, claimed in claims if claimed)
    assert await repo.finish_owned(winner.id, worker_id=winner.worker_id, status="success", result={}, message="done")
    remaining = next(task_id for task_id in ids if task_id != winner.id)
    row, claimed = await repo.claim(
        remaining,
        worker_id="next-worker",
        lease_seconds=30,
        max_running=1,
        type_filter="wxchannels_central_discover",
        lock_scope="durable-task-capacity:wxchannels_central_discover",
    )
    assert claimed and row.status == "running"
