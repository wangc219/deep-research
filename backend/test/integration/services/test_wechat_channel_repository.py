"""真实 PostgreSQL 验证视频号目录迁移、并发合并及用户隔离。"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from platform_core.repositories import wechat_channel_repository as module
from platform_core.repositories.wechat_channel_repository import WechatChannelRepository
from platform_core.storage.postgres.manager import PostgresManager

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """仅测试隔离 Schema。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """不创建业务知识库。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """不使用用户沙盒。"""
    yield


@pytest.fixture
async def database(monkeypatch):
    """每个用例使用独立 Schema，结束自动彻底删除。"""
    schema = "pytest_channels_" + uuid4().hex[:16]
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    manager._initialized = True
    monkeypatch.setattr(module, "pg_manager", manager)
    try:
        await manager.upgrade_knowledge_schema_v6_to_v7()
        await manager.upgrade_knowledge_schema_v6_to_v7()
        yield manager
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_migration_merge_ordering_and_cross_user_isolation(database):
    """同一个视频号在两个用户中独立，更新保留历史且按发布时间分页。"""
    repo = WechatChannelRepository()
    first = await repo.merge(
        "alice",
        "视频号",
        "account@finder",
        [
            {"oid": "old", "title": "旧视频", "published_at": 100},
            {"oid": "pin", "title": "置顶", "published_at": 10},
        ],
        complete=True,
    )
    assert first["video_count"] == first["new_count"] == 2
    second = await repo.merge(
        "alice",
        "account@finder",
        "account@finder",
        [
            {"oid": "new", "title": "新视频", "published_at": 500},
            {"oid": "old", "title": "更新标题", "published_at": 100},
        ],
        complete=False,
    )
    assert second["new_count"] == 1 and second["video_count"] == 3
    assert second["history_complete"] and second["account"] == "视频号"
    assert (await repo.find("alice", "视频号"))["username"] == "account@finder"
    assert await repo.find("bob", "视频号") is None
    assert await repo.videos("bob", first["id"]) is None
    assert not await repo.delete("bob", first["id"])
    own = await repo.videos("alice", first["id"], limit=2)
    assert [v["oid"] for v in own["videos"]] == ["new", "old"]
    assert own["videos"][1]["title"] == "更新标题"
    assert (await repo.videos("alice", first["id"], offset=2))["videos"][0]["oid"] == "pin"
    selected = await repo.pending_videos("alice", first["id"], {"new"}, 1)
    assert selected["completed_count"] == 1 and selected["total_count"] == 3
    assert [v["oid"] for v in selected["videos"]] == ["old"]
    assert len((await repo.pending_videos("alice", first["id"], set(), None))["videos"]) == 3
    assert (await repo.pending_videos("bob", first["id"], set(), None))["videos"] == []
    filtered = await repo.videos("alice", first["id"], keyword="更新", published_after=90, published_before=110)
    assert filtered["total_count"] == 1 and filtered["videos"][0]["oid"] == "old"
    assert not (await repo.videos("alice", first["id"], keyword="%"))["videos"]
    assert not (await repo.videos("alice", first["id"], published_after=501))["videos"]
    other = await repo.merge("bob", "同号", "account@finder", [{"oid": "old"}], complete=False)
    assert other["id"] != first["id"]
    assert len(await repo.list_owned("alice")) == len(await repo.list_owned("bob")) == 1
    assert await repo.delete("alice", first["id"])
    assert await repo.videos("alice", first["id"]) is None
    async with database.async_engine.begin() as conn:
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM wechat_channel_videos WHERE channel_id=:id"), {"id": first["id"]}
            )
            == 0
        )
        tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
        assert "wechat_channels" in tables and "wechat_channel_videos" in tables
    assert (await repo.list_owned("bob"))[0]["video_count"] == 1


async def test_concurrent_sync_never_loses_history(database):
    """并发同步同账号没有重复行、丢更新或错误新增计数。"""
    repo = WechatChannelRepository()
    results = await asyncio.gather(
        *[
            repo.merge("alice", "视频号", "account@finder", [{"oid": str(i)}, {"oid": "shared"}], complete=i == 0)
            for i in range(8)
        ]
    )
    assert sum(result["new_count"] for result in results) == 9
    saved = (await repo.list_owned("alice"))[0]
    assert saved["video_count"] == 9 and saved["history_complete"]
