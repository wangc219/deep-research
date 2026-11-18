"""知识治理、来源版本和采集成果状态的真实 PostgreSQL 集成测试。"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.services import collection_artifact_service
from platform_core.services import knowledge_governance_service as governance
from platform_core.services import innovation_brief_service
from platform_core.services import knowledge_source_connectors
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_knowledge import KnowledgeBase, KnowledgeFile
from platform_core.storage.postgres.models_knowledge_governance import (
    BriefDeliveryOutbox,
    CollectionArtifactIngestion,
    CollectionArtifactRecord,
    InnovationBrief,
    InnovationBriefRun,
    KnowledgeSource,
    KnowledgeSourceItem,
    KnowledgeSourceRun,
)
from platform_core.utils.datetime_utils import utc_now
from platform_core.workspace.filesystem import Workspace
from platform_core.workspace.paths import ensure_user_workspace

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _async_value(value):
    return value


class _TaskContext:
    """只记录来源采集 Worker 所需的任务上下文。"""

    def __init__(self, run_id: str):
        self.payload = {"source_run_id": run_id}
        self.progress: list[tuple[int, str]] = []
        self.result = None

    async def set_progress(self, progress: int, message: str) -> None:
        self.progress.append((progress, message))

    async def raise_if_cancelled(self) -> None:
        return None

    async def set_result(self, result: dict) -> None:
        self.result = result


class _BriefTaskContext(_TaskContext):
    """提供简报 Worker 使用的运行标识。"""

    def __init__(self, run_id: str):
        super().__init__(run_id)
        self.payload = {"brief_run_id": run_id}


def _scoped_manager(engine) -> PostgresManager:
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
    manager._initialized = True
    return manager


async def _isolated_knowledge_database(prefix: str):
    schema = f"{prefix}_{uuid.uuid4().hex[:16]}"
    admin = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    manager = _scoped_manager(engine)
    await manager.create_knowledge_tables()
    return schema, admin, engine, manager, async_sessionmaker(engine, expire_on_commit=False)


async def _drop_database(schema: str, admin, engine) -> None:
    await engine.dispose()
    async with admin.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await admin.dispose()


async def test_category_tree_enforces_tenant_cycle_branch_and_references() -> None:
    """分类必须隔离组织、拒绝循环，并保护知识资产引用。"""
    schema, admin, engine, _manager, factory = await _isolated_knowledge_database("pytest_categories")
    try:
        async with factory() as db:
            root = await governance.create_category(
                db,
                tenant_id="tenant-a",
                user_uid="admin-a",
                data={"name": "无人系统"},
            )
            child = await governance.create_category(
                db,
                tenant_id="tenant-a",
                user_uid="admin-a",
                data={"name": "协同控制", "parent_id": root["id"]},
            )
            sibling = await governance.create_category(
                db,
                tenant_id="tenant-a",
                user_uid="admin-a",
                data={"name": "导弹技术"},
            )
            other_tenant = await governance.create_category(
                db,
                tenant_id="tenant-b",
                user_uid="admin-b",
                data={"name": "无人系统"},
            )

            with pytest.raises(HTTPException, match="同一层级已存在同名分类") as duplicate:
                await governance.create_category(
                    db,
                    tenant_id="tenant-a",
                    user_uid="admin-a",
                    data={"name": "无人系统"},
                )
            assert duplicate.value.status_code == 409

            with pytest.raises(HTTPException, match="自身子级"):
                await governance.update_category(
                    db,
                    tenant_id="tenant-a",
                    category_id=root["id"],
                    data={"parent_id": child["id"]},
                )
            with pytest.raises(HTTPException, match="不属于当前组织"):
                await governance.ensure_organization_category(
                    db,
                    tenant_id="tenant-a",
                    category_id=other_tenant["id"],
                )

            db.add(KnowledgeBase(kb_id="kb-a", name="分类知识库", kb_type="milvus"))
            await db.commit()
            uncategorized_tree = await governance.list_category_tree(
                db,
                tenant_id="tenant-a",
                accessible_kb_ids={"kb-a"},
            )
            assert uncategorized_tree["uncategorized"]["stats"] == {
                "knowledge_bases": 1,
                "sources": 0,
                "documents": 0,
            }
            await governance.assign_knowledge_base_category(
                db,
                tenant_id="tenant-a",
                kb_id="kb-a",
                category_id=root["id"],
            )
            assert (
                await governance.ensure_category_for_kb(
                    db,
                    tenant_id="tenant-a",
                    kb_id="kb-a",
                    category_id=child["id"],
                )
            ).id == child["id"]
            with pytest.raises(HTTPException, match="主分类之下"):
                await governance.ensure_category_for_kb(
                    db,
                    tenant_id="tenant-a",
                    kb_id="kb-a",
                    category_id=sibling["id"],
                )
            with pytest.raises(HTTPException, match="知识资产引用"):
                await governance.delete_category(db, tenant_id="tenant-a", category_id=root["id"])

            await governance.update_category(
                db,
                tenant_id="tenant-a",
                category_id=child["id"],
                data={"active": False},
            )
            with pytest.raises(HTTPException, match="停用分类"):
                await governance.ensure_organization_category(
                    db,
                    tenant_id="tenant-a",
                    category_id=child["id"],
                )
            assert (
                await governance.ensure_category_for_kb(
                    db,
                    tenant_id="tenant-a",
                    kb_id="kb-a",
                    category_id=child["id"],
                    allow_inactive=True,
                )
            ).id == child["id"]
            active_tree = await governance.list_category_tree(db, tenant_id="tenant-a")
            full_tree = await governance.list_category_tree(
                db,
                tenant_id="tenant-a",
                include_inactive=True,
            )

        assert {row["id"] for row in active_tree["flat"]} == {root["id"], sibling["id"]}
        assert {row["id"] for row in full_tree["flat"]} == {root["id"], child["id"], sibling["id"]}
    finally:
        await _drop_database(schema, admin, engine)


async def test_postgresql_connector_reads_view_with_filter_cursor_and_byte_limit() -> None:
    """数据库来源仅反射表/视图，游标列自动投影且总字节数有界。"""
    schema, admin, engine, _manager, _factory = await _isolated_knowledge_database("pytest_db_connector")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE source_documents ("
                    "id INTEGER PRIMARY KEY, title TEXT, body TEXT, status TEXT, updated_at INTEGER)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO source_documents VALUES "
                    "(1, '旧记录', 'old', 'published', 1),"
                    "(2, '新记录 A', repeat('A', 90), 'published', 2),"
                    "(3, '新记录 B', repeat('B', 90), 'published', 3),"
                    "(4, '草稿', 'draft', 'draft', 4)"
                )
            )
            await connection.execute(text("CREATE VIEW source_documents_view AS SELECT * FROM source_documents"))

        url = make_url(os.environ["POSTGRES_URL"])
        credential = {
            "host": url.host,
            "port": url.port or 5432,
            "database": url.database,
            "username": url.username,
            "password": url.password or "",
        }
        items = await asyncio.to_thread(
            knowledge_source_connectors._collect_database,
            "postgresql",
            {
                "schema": schema,
                "table": "source_documents_view",
                "content_columns": ["body"],
                "title_column": "title",
                "primary_key": "id",
                "cursor_column": "updated_at",
                "filters": [{"column": "status", "operator": "eq", "value": "published"}],
                "cursor_value": 1,
                "max_rows": 100,
                "max_bytes": 180,
            },
            credential,
        )

        assert len(items) == 1
        assert items[0]["external_key"] == "2"
        assert items[0]["metadata"]["cursor"] == 2
        assert "新记录 A" in items[0]["markdown"]
    finally:
        await _drop_database(schema, admin, engine)


async def test_source_collection_versions_deduplicates_and_emits_pending_review_briefs(monkeypatch) -> None:
    """新内容进入暂存区，重复内容不再通知，变化内容生成新版本。"""
    schema, admin, engine, manager, factory = await _isolated_knowledge_database("pytest_source_versions")
    try:
        async with factory() as db:
            db.add(KnowledgeBase(kb_id="kb-source", name="来源知识库", kb_type="milvus"))
            await db.commit()
            source_data = await governance.create_source(
                db,
                tenant_id="tenant-a",
                user_uid="owner-a",
                data={
                    "kb_id": "kb-source",
                    "name": "无人前沿来源",
                    "source_type": "web_search",
                    "config": {"queries": ["无人系统"]},
                    "notify_on_new": True,
                },
            )
            await innovation_brief_service.create_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="owner-a",
                data={
                    "name": "无人前沿简报",
                    "topics": ["无人系统"],
                    "source_ids": [source_data["id"]],
                },
            )

        versions = [
            "# 集群试验\n\n首轮试验完成。",
            "# 集群试验\n\n首轮试验完成。",
            "# 集群试验\n\n第二轮试验完成并调整协同策略。",
        ]
        call_index = 0

        async def collect_items(_source_type, _config, _credential):
            nonlocal call_index
            markdown = versions[call_index]
            call_index += 1
            return [
                {
                    "external_key": "swarm-test",
                    "canonical_url": "https://example.test/swarm-test",
                    "title": "集群试验",
                    "markdown": markdown,
                    "metadata": {"cursor": call_index, "published_at": "2026-10-31"},
                }
            ]

        monkeypatch.setattr(governance, "pg_manager", manager)
        monkeypatch.setattr(governance, "collect_source_items", collect_items)

        results = []
        for index in range(3):
            async with factory() as db:
                run = KnowledgeSourceRun(
                    id=f"source-run-{index}",
                    source_id=source_data["id"],
                    owner_uid="owner-a",
                    trigger="manual",
                    config_snapshot={},
                )
                db.add(run)
                await db.commit()
            results.append(await governance.run_knowledge_source_collection(_TaskContext(run.id)))

        async with factory() as db:
            items = list((await db.scalars(select(KnowledgeSourceItem).order_by(KnowledgeSourceItem.version))).all())
            briefs = list((await db.scalars(select(InnovationBrief).order_by(InnovationBrief.created_at))).all())
            deliveries = list((await db.scalars(select(BriefDeliveryOutbox))).all())
            source = await db.get(KnowledgeSource, source_data["id"])
            file_count = int(await db.scalar(select(func.count(KnowledgeFile.file_id))) or 0)

        pending_items = sorted(
            (row for row in items if row.review_status == "pending"),
            key=lambda row: row.version,
        )
        duplicate_items = [row for row in items if row.review_status == "duplicate"]
        assert [(row.version, row.review_status) for row in pending_items] == [(1, "pending"), (2, "pending")]
        assert pending_items[1].previous_item_id == pending_items[0].id
        assert len(duplicate_items) == 1
        assert duplicate_items[0].previous_item_id == pending_items[0].id
        assert duplicate_items[0].metadata_json["duplicate_content_hash"] == pending_items[0].content_hash
        assert results[0]["created"] == 1 and results[0]["notified_subscriptions"] == 1
        assert results[1]["created"] == 0 and results[1]["duplicates"] == 1
        assert results[2]["created"] == 1 and results[2]["notified_subscriptions"] == 1
        assert source.cursor == {"value": 3}
        assert file_count == 0
        assert len(briefs) == 2
        assert all(row.brief_type == "collection_update" and row.unread for row in briefs)
        assert all(not row.sections["confirmed_facts"] for row in briefs)
        assert all(item["pending_review"] for row in briefs for item in row.evidence)
        assert sorted(row.status for row in deliveries) == ["delivered", "delivered", "disabled", "disabled"]
    finally:
        await _drop_database(schema, admin, engine)


async def test_article_state_aggregates_current_content_across_knowledge_bases() -> None:
    """同一内容多知识库入库时成功优先，内容变化后回到已下载。"""
    schema, admin, engine, _manager, factory = await _isolated_knowledge_database("pytest_article_state")
    try:
        async with factory() as db:
            db.add_all(
                [
                    KnowledgeBase(kb_id="kb-a", name="A", kb_type="milvus"),
                    KnowledgeBase(kb_id="kb-b", name="B", kb_type="milvus"),
                    KnowledgeBase(kb_id="kb-c", name="C", kb_type="milvus"),
                ]
            )
            record = CollectionArtifactRecord(
                id="artifact-record",
                owner_uid="owner-a",
                source="wechat-articles",
                artifact_key="artifact-key",
                title="前沿文章",
                canonical_url="https://mp.weixin.qq.com/s/article",
                content_hash="hash-v1",
                primary_path="/采集成果/公众号文章/前沿文章/正文.md",
                import_path="/采集成果/公众号文章/前沿文章/正文.md",
                files=["/采集成果/公众号文章/前沿文章/正文.md"],
                status="failed",
                failure_stage="ingest",
                error="B 入库失败",
            )
            db.add(record)
            await db.flush()
            db.add_all(
                [
                    CollectionArtifactIngestion(
                        id="ingest-a",
                        artifact_id=record.id,
                        kb_id="kb-a",
                        content_hash="hash-v1",
                        task_id="task-a",
                        status="imported",
                        created_by="owner-a",
                    ),
                    CollectionArtifactIngestion(
                        id="ingest-b",
                        artifact_id=record.id,
                        kb_id="kb-b",
                        content_hash="hash-v1",
                        task_id="task-b",
                        status="failed",
                        error="B 入库失败",
                        created_by="owner-a",
                    ),
                ]
            )
            await db.commit()

            payload = {"articles": [{"title": "前沿文章", "link": f"{record.canonical_url}/"}]}
            merged = await collection_artifact_service.merge_article_listing_states(
                db,
                uid="owner-a",
                payload=payload,
            )
            assert merged["articles"][0]["download_state"] == "imported"
            assert merged["articles"][0]["failure_stage"] is None
            assert len(merged["articles"][0]["ingestions"]) == 2

            db.add(
                CollectionArtifactIngestion(
                    id="ingest-c",
                    artifact_id=record.id,
                    kb_id="kb-c",
                    content_hash="hash-v1",
                    task_id="task-c",
                    status="importing",
                    created_by="owner-a",
                )
            )
            await db.commit()
            importing = await collection_artifact_service.merge_article_listing_states(
                db,
                uid="owner-a",
                payload={"articles": [{"title": "前沿文章"}]},
            )
            assert importing["articles"][0]["download_state"] == "importing"

            record.content_hash = "hash-v2"
            record.status = "downloaded"
            record.failure_stage = None
            record.error = ""
            await db.commit()
            changed = await collection_artifact_service.merge_article_listing_states(
                db,
                uid="owner-a",
                payload={"articles": [{"title": "前沿文章"}]},
            )
            article = changed["articles"][0]
            assert article["download_state"] == "downloaded"
            assert "target_kb_id" not in article
            assert len(article["ingestions"]) == 3
    finally:
        await _drop_database(schema, admin, engine)


async def test_article_state_is_user_scoped_but_admin_can_see_global_downloads() -> None:
    """普通用户只看本人下载状态，管理员按所有用户的最高处理状态聚合。"""
    schema, admin, engine, _manager, factory = await _isolated_knowledge_database("pytest_article_scope")
    try:
        async with factory() as db:
            common = {
                "source": "wechat-articles",
                "title": "跨用户共享文章",
                "canonical_url": "https://mp.weixin.qq.com/s/shared-article",
                "content_hash": "shared-hash",
                "primary_path": "/采集成果/公众号文章/跨用户共享文章/正文.md",
                "import_path": "/采集成果/公众号文章/跨用户共享文章/正文.md",
                "files": ["/采集成果/公众号文章/跨用户共享文章/正文.md"],
            }
            db.add_all(
                [
                    CollectionArtifactRecord(
                        id="artifact-owner-a",
                        owner_uid="owner-a",
                        artifact_key="artifact-key-a",
                        status="failed",
                        failure_stage="download",
                        error="owner-a 下载失败",
                        **common,
                    ),
                    CollectionArtifactRecord(
                        id="artifact-owner-b",
                        owner_uid="owner-b",
                        artifact_key="artifact-key-b",
                        status="downloaded",
                        failure_stage=None,
                        error="",
                        **common,
                    ),
                ]
            )
            await db.commit()

            user_payload = {"articles": [{"title": common["title"], "link": f"{common['canonical_url']}/"}]}
            user_result = await collection_artifact_service.merge_article_listing_states(
                db,
                uid="owner-a",
                payload=user_payload,
            )
            user_article = user_result["articles"][0]
            assert user_article["download_state"] == "failed"
            assert user_article["download_scope"] == "user"
            assert user_article["download_owner_count"] == 1
            assert user_article["download_error"] == "owner-a 下载失败"

            admin_payload = {"articles": [{"title": common["title"], "link": common["canonical_url"]}]}
            admin_result = await collection_artifact_service.merge_article_listing_states(
                db,
                uid="owner-a",
                payload=admin_payload,
                global_scope=True,
            )
            admin_article = admin_result["articles"][0]
            assert admin_article["download_state"] == "downloaded"
            assert admin_article["download_scope"] == "global"
            assert admin_article["download_owner_count"] == 2
            assert admin_article["ingestions"] == []
            assert "record_id" not in admin_article
            assert "target_kb_id" not in admin_article
            assert "ingest_task_id" not in admin_article
            assert "knowledge_file_id" not in admin_article
    finally:
        await _drop_database(schema, admin, engine)


async def test_daily_and_weekly_briefs_persist_threshold_layers_dedup_and_outboxes(monkeypatch) -> None:
    """无显著日报保持已读，周报固定未读，并跨日报周报过滤重复信号。"""
    schema, admin, engine, manager, factory = await _isolated_knowledge_database("pytest_brief_delivery")
    try:
        async with factory() as db:
            subscription = await innovation_brief_service.create_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="owner-a",
                data={
                    "name": "无人颠覆技术观察",
                    "topics": ["无人系统"],
                    "reminder_sensitivity": "conservative",
                    "significance_threshold": 95,
                    "research_explorer_enabled": False,
                },
            )

        async def collect_evidence(_snapshot, _plan, _context):
            return (
                [
                    {
                        "id": "evidence-1",
                        "title": "无人系统概念研究",
                        "excerpt": "单一公开来源的早期概念，尚无独立交叉印证。",
                        "url": "https://example.test/concept",
                        "source": "Example",
                        "source_type": "web_search",
                        "review_status": "external",
                        "pending_review": False,
                        "published_at": "2026-10-31",
                        "discovered_at": "2026-10-31T00:00:00Z",
                    }
                ],
                [],
            )

        async def discover_hypotheses(_snapshot, _plan, _context):
            return (
                [
                    {
                        "title": "低成本无人平台与定向能节点协同",
                        "claim_level": "Hypothesis",
                        "verification": "需要试验数据验证",
                    }
                ],
                [],
            )

        async def expand_queries(subscription, **_kwargs):
            return innovation_brief_service._expand_query_plan(
                innovation_brief_service._subscription_view(subscription)
            ), []

        monkeypatch.setattr(innovation_brief_service, "pg_manager", manager)
        monkeypatch.setattr(innovation_brief_service, "_collect_evidence", collect_evidence)
        monkeypatch.setattr(innovation_brief_service, "_discover_hypotheses", discover_hypotheses)
        monkeypatch.setattr(innovation_brief_service, "_expand_query_plan_with_agent", expand_queries)
        monkeypatch.setattr(
            innovation_brief_service,
            "_assess_brief_quality",
            lambda _sections: {
                "passed": True,
                "failures": [],
                "qualified_finding_count": 0,
                "fact_count": 0,
                "inference_count": 1,
                "qualified_hypothesis_count": 1,
            },
        )
        monkeypatch.setattr(
            innovation_brief_service,
            "_resolve_brief_model_spec",
            lambda _db: _async_value(""),
        )

        for brief_type in ("daily", "weekly"):
            async with factory() as db:
                run = InnovationBriefRun(
                    id=f"brief-run-{brief_type}",
                    subscription_id=subscription["id"],
                    owner_uid="owner-a",
                    brief_type=brief_type,
                    status="pending",
                    scheduled_for=utc_now() - timedelta(minutes=5) if brief_type == "daily" else None,
                    stats={"trigger": "integration"},
                )
                db.add(run)
                await db.commit()
            await innovation_brief_service.run_innovation_brief(_BriefTaskContext(run.id))

        async with factory() as db:
            briefs = list((await db.scalars(select(InnovationBrief).order_by(InnovationBrief.brief_type))).all())
            runs = list((await db.scalars(select(InnovationBriefRun))).all())
            outboxes = list((await db.scalars(select(BriefDeliveryOutbox))).all())

        by_type = {row.brief_type: row for row in briefs}
        assert by_type["daily"].significant is False
        assert by_type["daily"].unread is False
        assert by_type["weekly"].significant is False
        assert by_type["weekly"].unread is True
        assert all(row.sections["confirmed_facts"] == [] for row in briefs)
        assert by_type["daily"].sections["innovation_hypotheses"][0]["claim_level"] == "Hypothesis"
        assert by_type["weekly"].sections["innovation_hypotheses"] == []
        assert len(by_type["daily"].evidence) == 1
        assert by_type["weekly"].evidence == []
        assert "未发现需要重复推送" in by_type["weekly"].summary
        assert all(row.stats["selected_item_count"] <= 10 for row in runs)
        assert all(row.stats["effective_significance_threshold"] == 100 for row in runs)
        assert all(row.stats["reminder_sensitivity"] == "conservative" for row in runs)
        daily_run = next(row for row in runs if row.brief_type == "daily")
        assert daily_run.stats["delivery_status"] == "published"
        assert daily_run.stats["delivery_lag_ms"] >= 5 * 60 * 1000
        assert sorted(row.status for row in outboxes) == ["delivered", "delivered", "disabled", "disabled"]
    finally:
        await _drop_database(schema, admin, engine)


async def test_due_schedulers_advance_and_allow_next_brief_schedule(monkeypatch) -> None:
    """来源任务保持单运行，简报则按不同推送时刻持续提前准备。"""
    schema, admin, engine, manager, factory = await _isolated_knowledge_database("pytest_due_schedules")
    published: list[str] = []
    created_task_ids: list[str] = []

    async def create_task(_db, **_kwargs):
        task_id = f"scheduled-task-{len(created_task_ids) + 1}"
        created_task_ids.append(task_id)
        return SimpleNamespace(id=task_id)

    async def publish_task(task) -> None:
        published.append(task.id)

    monkeypatch.setattr(governance, "pg_manager", manager)
    monkeypatch.setattr(innovation_brief_service, "pg_manager", manager)
    monkeypatch.setattr(governance.tasker, "create_in_session", create_task)
    monkeypatch.setattr(governance.tasker, "publish", publish_task)

    try:
        async with factory() as db:
            db.add(KnowledgeBase(kb_id="kb-scheduled", name="定时知识库", kb_type="milvus"))
            await db.commit()
            source = await governance.create_source(
                db,
                tenant_id="tenant-a",
                user_uid="owner-a",
                data={
                    "kb_id": "kb-scheduled",
                    "name": "定时来源",
                    "source_type": "upload",
                    "config": {},
                    "cron_expression": "* * * * *",
                    "timezone": "Asia/Shanghai",
                },
            )
            subscription = await innovation_brief_service.create_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="owner-a",
                data={
                    "name": "定时简报",
                    "topics": ["无人系统"],
                    "daily_cron": "* * * * *",
                    "weekly_enabled": False,
                },
            )
            source_row = await db.get(KnowledgeSource, source["id"])
            subscription_row = await db.get(
                innovation_brief_service.InnovationBriefSubscription,
                subscription["id"],
            )
            source_row.next_run_at = utc_now() - timedelta(minutes=1)
            subscription_row.next_daily_at = utc_now() - timedelta(minutes=1)
            await db.commit()

        assert await governance.claim_due_source_runs(limit=5) == 1
        assert await innovation_brief_service.claim_due_brief_runs(limit=5) == 1

        async with factory() as db:
            source_run = await db.scalar(select(KnowledgeSourceRun))
            brief_run = await db.scalar(select(InnovationBriefRun))
            source_row = await db.get(KnowledgeSource, source["id"])
            subscription_row = await db.get(
                innovation_brief_service.InnovationBriefSubscription,
                subscription["id"],
            )
            assert source_run.trigger == "scheduled" and source_run.status == "pending"
            assert brief_run.stats["trigger"] == "scheduled" and brief_run.status == "pending"
            assert source_row.next_run_at > utc_now()
            assert subscription_row.next_daily_at > utc_now()

            source_row.next_run_at = utc_now() - timedelta(minutes=1)
            subscription_row.next_daily_at = utc_now() - timedelta(minutes=1)
            await db.commit()

        assert await governance.claim_due_source_runs(limit=5) == 0
        assert await innovation_brief_service.claim_due_brief_runs(limit=5) == 1
        assert created_task_ids == ["scheduled-task-1", "scheduled-task-2", "scheduled-task-3"]
        assert published == created_task_ids
    finally:
        await _drop_database(schema, admin, engine)


async def test_brief_prepares_before_schedule_and_publishes_once(monkeypatch) -> None:
    """提前准备的简报到点前不可见，到点后只产生一次站内投递。"""
    schema, admin, engine, manager, factory = await _isolated_knowledge_database("pytest_brief_prepare")
    created_tasks: list[str] = []

    async def create_task(_db, **_kwargs):
        task_id = f"prepare-task-{len(created_tasks) + 1}"
        created_tasks.append(task_id)
        return SimpleNamespace(id=task_id)

    async def publish_task(_task) -> None:
        return None

    monkeypatch.setattr(innovation_brief_service, "pg_manager", manager)
    monkeypatch.setattr(innovation_brief_service.tasker, "create_in_session", create_task)
    monkeypatch.setattr(innovation_brief_service.tasker, "publish", publish_task)

    try:
        async with factory() as db:
            subscription = await innovation_brief_service.create_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="owner-a",
                data={
                    "name": "准点简报",
                    "topics": ["无人系统"],
                    "daily_enabled": True,
                    "weekly_enabled": False,
                },
            )
            subscription_row = await db.get(
                innovation_brief_service.InnovationBriefSubscription,
                subscription["id"],
            )
            scheduled_for = utc_now() + timedelta(minutes=30)
            subscription_row.next_daily_at = scheduled_for
            await db.commit()

        assert await innovation_brief_service.claim_due_brief_runs(limit=5) == 1

        async with factory() as db:
            run = await db.scalar(select(InnovationBriefRun))
            subscription_row = await db.get(
                innovation_brief_service.InnovationBriefSubscription,
                subscription["id"],
            )
            assert run.scheduled_for == scheduled_for
            assert run.stats["prepare_ahead_minutes"] == innovation_brief_service.BRIEF_PREPARE_AHEAD_MINUTES
            assert subscription_row.next_daily_at > scheduled_for
            run.status = "prepared"
            brief = InnovationBrief(
                id="prepared-brief",
                run_id=run.id,
                subscription_id=subscription["id"],
                owner_uid="owner-a",
                brief_type="daily",
                title="提前准备完成",
                summary="到点前不可见",
                sections={},
                evidence=[],
                max_score=0,
                significant=False,
                unread=False,
                published_at=None,
            )
            db.add(brief)
            await db.commit()
            hidden = await innovation_brief_service.list_briefs(
                db,
                owner_uid="owner-a",
                brief_type=None,
                unread=None,
                page=1,
                page_size=20,
            )
            assert hidden["items"] == []

            run.scheduled_for = utc_now() - timedelta(seconds=1)
            subscription_row.next_daily_at = run.scheduled_for
            await db.commit()

        assert await innovation_brief_service.claim_due_brief_runs(limit=5) == 0
        assert await innovation_brief_service.publish_due_briefs() == 1
        assert await innovation_brief_service.publish_due_briefs() == 0

        async with factory() as db:
            visible = await innovation_brief_service.list_briefs(
                db,
                owner_uid="owner-a",
                brief_type=None,
                unread=None,
                page=1,
                page_size=20,
            )
            outboxes = list((await db.scalars(select(BriefDeliveryOutbox))).all())
            run = await db.scalar(select(InnovationBriefRun))
            assert [item["id"] for item in visible["items"]] == ["prepared-brief"]
            assert visible["items"][0]["unread"] is True
            assert sorted(row.status for row in outboxes) == ["delivered", "disabled"]
            assert run.status == "completed"
            assert run.stats["delivery_status"] == "published"
            assert run.stats["delivery_lag_ms"] >= 1000

            cancelled_run = InnovationBriefRun(
                id="prepared-disabled-run",
                subscription_id=subscription["id"],
                owner_uid="owner-a",
                brief_type="daily",
                status="prepared",
                scheduled_for=utc_now() + timedelta(hours=1),
                stats={"trigger": "scheduled"},
            )
            db.add(cancelled_run)
            await db.flush()
            db.add(
                InnovationBrief(
                    id="prepared-disabled-brief",
                    run_id=cancelled_run.id,
                    subscription_id=subscription["id"],
                    owner_uid="owner-a",
                    brief_type="daily",
                    title="不应投递",
                    summary="订阅关闭后应取消",
                    sections={},
                    evidence=[],
                    max_score=0,
                    significant=False,
                    unread=False,
                )
            )
            await db.commit()
            await innovation_brief_service.update_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="owner-a",
                subscription_id=subscription["id"],
                data={"enabled": False},
            )
            cancelled_run = await db.get(InnovationBriefRun, "prepared-disabled-run")
            cancelled_brief = await db.get(InnovationBrief, "prepared-disabled-brief")
            assert cancelled_run.status == "cancelled"
            assert cancelled_brief is None
    finally:
        await _drop_database(schema, admin, engine)


async def test_daily_and_weekly_same_schedule_prepare_independently(monkeypatch) -> None:
    """同一订阅日报、周报同时到点时分别创建任务，不因订阅级互斥漏掉其一。"""
    schema, admin, engine, manager, factory = await _isolated_knowledge_database("pytest_brief_dual_schedule")
    created_tasks: list[str] = []

    async def create_task(_db, **_kwargs):
        task_id = f"dual-task-{len(created_tasks) + 1}"
        created_tasks.append(task_id)
        return SimpleNamespace(id=task_id)

    async def publish_task(_task) -> None:
        return None

    monkeypatch.setattr(innovation_brief_service, "pg_manager", manager)
    monkeypatch.setattr(innovation_brief_service.tasker, "create_in_session", create_task)
    monkeypatch.setattr(innovation_brief_service.tasker, "publish", publish_task)

    try:
        async with factory() as db:
            subscription = await innovation_brief_service.create_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="owner-a",
                data={"name": "双报同点", "topics": ["无人系统"]},
            )
            row = await db.get(innovation_brief_service.InnovationBriefSubscription, subscription["id"])
            scheduled_for = utc_now() + timedelta(minutes=30)
            row.next_daily_at = scheduled_for
            row.next_weekly_at = scheduled_for
            await db.commit()

        assert await innovation_brief_service.claim_due_brief_runs(limit=10) == 2
        assert await innovation_brief_service.claim_due_brief_runs(limit=10) == 0

        async with factory() as db:
            runs = list((await db.scalars(select(InnovationBriefRun))).all())
            assert {run.brief_type for run in runs} == {"daily", "weekly"}
            assert {run.scheduled_for for run in runs} == {scheduled_for}
            assert len(created_tasks) == 2
    finally:
        await _drop_database(schema, admin, engine)


async def test_brief_without_internal_scope_does_not_read_tenant_staging(monkeypatch) -> None:
    """未选择知识库或来源的订阅只能使用公网证据，不能旁路读取组织暂存区。"""
    schema, admin, engine, manager, factory = await _isolated_knowledge_database("pytest_brief_scope")

    async def no_web_results(_source_type, _config, _credential):
        return []

    async def no_hypotheses(_snapshot, _plan, _context):
        return [], []

    async def expand_queries(subscription, **_kwargs):
        return innovation_brief_service._expand_query_plan(
            innovation_brief_service._subscription_view(subscription)
        ), []

    monkeypatch.setattr(innovation_brief_service, "pg_manager", manager)
    monkeypatch.setattr(innovation_brief_service, "collect_source_items", no_web_results)
    monkeypatch.setattr(innovation_brief_service, "_discover_hypotheses", no_hypotheses)
    monkeypatch.setattr(innovation_brief_service, "_expand_query_plan_with_agent", expand_queries)
    monkeypatch.setattr(
        innovation_brief_service,
        "_resolve_brief_model_spec",
        lambda _db: _async_value(""),
    )

    try:
        async with factory() as db:
            db.add(KnowledgeBase(kb_id="kb-private", name="内部知识库", kb_type="milvus"))
            await db.commit()
            source = await governance.create_source(
                db,
                tenant_id="tenant-a",
                user_uid="source-owner",
                data={
                    "kb_id": "kb-private",
                    "name": "未订阅来源",
                    "source_type": "upload",
                    "config": {},
                },
            )
            item = KnowledgeSourceItem(
                id="private-staging",
                source_id=source["id"],
                kb_id="kb-private",
                external_key="private",
                title="内部待审核证据",
                markdown="# 内部证据",
                content_hash="private-hash",
                review_status="pending",
            )
            db.add(item)
            subscription = await innovation_brief_service.create_subscription(
                db,
                tenant_id="tenant-a",
                owner_uid="other-user",
                data={
                    "name": "仅公网简报",
                    "topics": ["无人系统"],
                    "research_explorer_enabled": False,
                },
            )
            run = InnovationBriefRun(
                id="brief-scope-run",
                subscription_id=subscription["id"],
                owner_uid="other-user",
                brief_type="daily",
                status="pending",
                stats={},
            )
            db.add(run)
            await db.commit()

        await innovation_brief_service.run_innovation_brief(_BriefTaskContext(run.id))

        async with factory() as db:
            brief = await db.scalar(select(InnovationBrief).where(InnovationBrief.run_id == run.id))
            persisted_run = await db.get(InnovationBriefRun, run.id)
        assert brief is None
        assert persisted_run.status == "failed"
        assert persisted_run.stats["quality_gate_passed"] is False
        assert persisted_run.stats["delivery_status"] == "quality_blocked"
    finally:
        await _drop_database(schema, admin, engine)


async def test_artifact_ingestion_is_idempotent_retriable_and_multi_kb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """同一内容同库幂等，失败可重试，并允许进入不同知识库。"""
    schema, admin, engine, _manager, factory = await _isolated_knowledge_database("pytest_artifact_ingest")
    monkeypatch.setenv("DEEP_RESEARCH_USER_DATA_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("COLLECTION_ARTIFACT_DATA_ROOT", str(tmp_path / "artifacts"))
    uid = "artifact-owner"
    artifact_key = "artifact-key"
    path = "/采集成果/公众号文章/幂等成果/正文.md"
    ensure_user_workspace(uid)
    workspace = Workspace(uid)
    collection_artifact_service.write_artifact_file(workspace, path, "# 幂等成果\n\n正文".encode())
    with collection_artifact_service.manifest(uid, "wechat-articles") as state:
        state["items"][artifact_key] = {
            "id": artifact_key,
            "title": "幂等成果",
            "account": "示例公众号",
            "canonical_url": "https://mp.weixin.qq.com/s/idempotent",
            "folder": "/采集成果/公众号文章/幂等成果",
            "primary_path": path,
            "import_path": path,
            "files": [path],
            "updated_at": 1,
        }

    created_tasks: list[str] = []

    async def create_task(_db, **_kwargs):
        task_id = f"task-{len(created_tasks) + 1}"
        created_tasks.append(task_id)
        return SimpleNamespace(id=task_id)

    async def publish_task(_task) -> None:
        return None

    async def upload(_bucket, object_name, _content):
        return f"minio://documents/{object_name}"

    monkeypatch.setattr(collection_artifact_service.tasker, "create_in_session", create_task)
    monkeypatch.setattr(collection_artifact_service.tasker, "publish", publish_task)
    monkeypatch.setattr(collection_artifact_service, "aupload_file_to_minio", upload)

    try:
        async with factory() as db:
            db.add_all(
                [
                    KnowledgeBase(kb_id="kb-a", name="A", kb_type="milvus"),
                    KnowledgeBase(kb_id="kb-b", name="B", kb_type="milvus"),
                ]
            )
            await db.commit()
            projection = collection_artifact_service.list_artifacts(uid, "wechat-articles")
            await collection_artifact_service.sync_artifact_records(
                db,
                uid=uid,
                source="wechat-articles",
                projection=projection,
            )

            first = await collection_artifact_service.ingest_artifacts(
                db,
                uid=uid,
                source="wechat-articles",
                ids=[artifact_key, artifact_key],
                kb_id="kb-a",
                category_id=None,
            )
            assert first["submitted"] == 1
            assert first["items"] == [{"id": artifact_key, "status": "importing", "task_id": "task-1"}]

            duplicate = await collection_artifact_service.ingest_artifacts(
                db,
                uid=uid,
                source="wechat-articles",
                ids=[artifact_key],
                kb_id="kb-a",
                category_id=None,
            )
            assert duplicate["submitted"] == 0
            assert duplicate["items"][0]["idempotent"] is True
            assert duplicate["items"][0]["task_id"] == "task-1"

            ingestion_a = await db.scalar(
                select(CollectionArtifactIngestion).where(CollectionArtifactIngestion.kb_id == "kb-a")
            )
            await collection_artifact_service.finish_artifact_ingestion(
                db,
                SimpleNamespace(payload={"artifact_ingestion_id": ingestion_a.id}),
                {"items": [{"file_id": None}]},
            )
            await db.commit()

            second_kb = await collection_artifact_service.ingest_artifacts(
                db,
                uid=uid,
                source="wechat-articles",
                ids=[artifact_key],
                kb_id="kb-b",
                category_id=None,
            )
            assert second_kb["items"][0]["task_id"] == "task-2"
            ingestion_b = await db.scalar(
                select(CollectionArtifactIngestion).where(CollectionArtifactIngestion.kb_id == "kb-b")
            )
            await collection_artifact_service.fail_artifact_ingestion(
                db,
                SimpleNamespace(payload={"artifact_ingestion_id": ingestion_b.id}),
                "模拟入库失败",
            )
            await db.commit()

            retry = await collection_artifact_service.ingest_artifacts(
                db,
                uid=uid,
                source="wechat-articles",
                ids=[artifact_key],
                kb_id="kb-b",
                category_id=None,
            )
            assert retry["items"][0]["task_id"] == "task-3"
            retried_b = await db.scalar(
                select(CollectionArtifactIngestion).where(CollectionArtifactIngestion.kb_id == "kb-b")
            )
            ingestion_count = int(await db.scalar(select(func.count(CollectionArtifactIngestion.id))) or 0)

        assert created_tasks == ["task-1", "task-2", "task-3"]
        assert retried_b.id == ingestion_b.id
        assert retried_b.status == "importing"
        assert ingestion_count == 2
    finally:
        await _drop_database(schema, admin, engine)
