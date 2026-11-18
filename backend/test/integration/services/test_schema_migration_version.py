"""深度研究平台 Schema 版本事实在真实 PostgreSQL 上的集成测试。"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.storage.postgres.manager import BUSINESS_SCHEMA_VERSION, KNOWLEDGE_SCHEMA_VERSION, PostgresManager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeGraphEntity,
    KnowledgeGraphHypothesis,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

LEGACY_TASK_TABLE_SQL = """
CREATE TABLE tasks (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    payload JSONB,
    result JSONB,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITHOUT TIME ZONE,
    completed_at TIMESTAMP WITHOUT TIME ZONE
)
"""


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本文件自行创建隔离 Schema，不依赖运行中的 API。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """隔离 Schema 测试没有 HTTP 资源需要清理。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """隔离 Schema 测试没有 Sandbox 资源需要清理。"""
    yield


def _scoped_manager(engine) -> PostgresManager:
    """创建不触碰进程单例的隔离 manager。"""
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager._initialized = True
    return manager


async def _create_isolated_manager(prefix: str):
    """创建位于独立 PostgreSQL Schema 的 manager 与清理句柄。"""
    schema = f"{prefix}_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    return schema, admin_engine, scoped_engine, _scoped_manager(scoped_engine)


async def _drop_isolated_schema(schema: str, admin_engine, scoped_engine) -> None:
    """释放隔离 Schema 及其 engine。"""
    await scoped_engine.dispose()
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await admin_engine.dispose()


async def test_schema_migration_lock_serializes_real_postgres_sessions() -> None:
    """两个 migrator 竞争同一 advisory lock 时只允许一个进入临界区。"""
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    manager = _scoped_manager(engine)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_migrator() -> None:
        async with manager.schema_migration_lock():
            first_entered.set()
            await release_first.wait()

    async def second_migrator() -> None:
        await first_entered.wait()
        async with manager.schema_migration_lock():
            second_entered.set()

    first_task = asyncio.create_task(first_migrator())
    second_task = asyncio.create_task(second_migrator())
    try:
        await asyncio.wait_for(first_entered.wait(), timeout=2)
        await asyncio.sleep(0.1)
        assert second_entered.is_set() is False
        release_first.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)
        assert second_entered.is_set() is True
    finally:
        release_first.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)
        await engine.dispose()


async def test_v072_business_converges_current_schema_idempotently() -> None:
    """v0.7.2 发布结构一次补齐当前字段与约束，重复执行保持幂等。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_task_schema")

    try:
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            # v0.7.2 tag 没有这些字段，不能用当前 ORM 预建它们来证明迁移。
            for column in ("prepared_at", "first_output_at", "first_model_request_at"):
                await connection.execute(text(f"ALTER TABLE agent_runs DROP COLUMN {column}"))
            await connection.execute(text("ALTER TABLE agent_runs ADD COLUMN last_event_id VARCHAR(64)"))
            await connection.execute(text("DROP TABLE scheduled_agent_runs"))
            await connection.execute(text("DROP TABLE scheduled_agent_jobs"))
            await connection.execute(text("DROP TABLE tasks"))
            await connection.execute(text(LEGACY_TASK_TABLE_SQL))
            await connection.execute(
                text(
                    "INSERT INTO tasks (id, name, type, status) "
                    "VALUES ('legacy-running', 'legacy', 'knowledge_parse', 'running')"
                )
            )

        await manager.ensure_business_schema()
        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            task_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'tasks'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            run_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'agent_runs'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            row = (
                await connection.execute(
                    text("SELECT status, error, handler_version, attempt_count FROM tasks WHERE id = 'legacy-running'")
                )
            ).one()
            scheduled_tables = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = :schema "
                            "AND table_name IN ('scheduled_agent_jobs', 'scheduled_agent_runs')"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            scheduled_columns = {
                (row.table_name, row.column_name)
                for row in (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema "
                            "AND table_name IN ('scheduled_agent_jobs', 'scheduled_agent_runs')"
                        ),
                        {"schema": schema},
                    )
                )
            }
            scheduled_constraints = {
                row.conname: row.definition
                for row in (
                    await connection.execute(
                        text(
                            """
                            SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
                            FROM pg_constraint AS con
                            JOIN pg_namespace AS ns ON ns.oid = con.connamespace
                            WHERE ns.nspname = :schema
                              AND con.conname IN (
                                  'fk_scheduled_agent_jobs_project_uid',
                                  'uq_scheduled_agent_jobs_uid_creation_request',
                                  'scheduled_agent_runs_job_id_fkey',
                                  'uq_scheduled_agent_runs_job_occurrence',
                                  'uq_scheduled_agent_runs_request',
                                  'uq_scheduled_agent_runs_thread'
                              )
                            """
                        ),
                        {"schema": schema},
                    )
                )
            }
            scheduled_indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = :schema "
                            "AND tablename IN ('scheduled_agent_jobs', 'scheduled_agent_runs')"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert {
            "handler_version",
            "dedupe_key",
            "attempt_count",
            "worker_id",
            "heartbeat_at",
            "lease_expires_at",
            "timeout_seconds",
        } <= task_columns
        assert {"prepared_at", "first_output_at", "first_model_request_at"} <= run_columns
        assert "last_event_id" not in run_columns
        assert tuple(row) == ("running", None, 0, 0)
        assert scheduled_tables == {"scheduled_agent_jobs", "scheduled_agent_runs"}
        assert {
            ("scheduled_agent_jobs", "creation_request_id"),
            ("scheduled_agent_jobs", "creation_intent_hash"),
            ("scheduled_agent_jobs", "model_spec"),
            ("scheduled_agent_runs", "model_spec"),
        }.issubset(scheduled_columns)
        assert "ON DELETE CASCADE" in scheduled_constraints["fk_scheduled_agent_jobs_project_uid"]
        assert "ON DELETE CASCADE" in scheduled_constraints["scheduled_agent_runs_job_id_fkey"]
        assert (
            "UNIQUE (uid, creation_request_id)" in scheduled_constraints["uq_scheduled_agent_jobs_uid_creation_request"]
        )
        assert {
            "uq_scheduled_agent_runs_job_occurrence",
            "uq_scheduled_agent_runs_request",
            "uq_scheduled_agent_runs_thread",
        }.issubset(scheduled_constraints)
        assert {
            "ix_scheduled_agent_jobs_due",
            "ix_scheduled_agent_runs_job_created",
            "ix_scheduled_agent_runs_dispatching",
        }.issubset(scheduled_indexes)
        assert BUSINESS_SCHEMA_VERSION == 16
        async with scoped_engine.connect() as conn:
            columns = (
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = current_schema() AND table_name = 'platform_model_calls'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {"model_spec", "surface", "run_id", "status", "duration_ms", "total_tokens"} <= set(columns)
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_release_upgrade_adds_audit_columns_idempotently() -> None:
    """发布版缺失的 Trace 与 Message 审计列由完整升级补齐，且可安全重放。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_audit_schema")
    try:
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE agent_runs DROP COLUMN langfuse_trace_id"))
            audit_columns = (
                "operation_id",
                "started_at",
                "finished_at",
                "duration_ms",
                "sequence",
                "execution_status",
                "usage",
            )
            for column in audit_columns:
                await connection.execute(text(f"ALTER TABLE messages DROP COLUMN {column}"))

        await manager.ensure_business_schema()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP INDEX uq_messages_run_role_operation_id"))
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX uq_messages_run_operation_id "
                    "ON messages(run_id, operation_id) WHERE operation_id IS NOT NULL"
                )
            )
        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name IN ('agent_runs', 'messages')"
                        ),
                        {"schema": schema},
                    )
                ).all()
            )
            audit_indexes = {
                name: definition
                for name, definition in (
                    await connection.execute(
                        text(
                            "SELECT indexname, indexdef FROM pg_indexes "
                            "WHERE schemaname = :schema AND tablename = 'messages' "
                            "AND indexname LIKE 'uq_messages_run%operation_id'"
                        ),
                        {"schema": schema},
                    )
                ).all()
            }
        assert ("agent_runs", "langfuse_trace_id") in columns
        assert {("messages", column) for column in audit_columns} <= columns
        assert "uq_messages_run_operation_id" not in audit_indexes
        assert "(run_id, role, operation_id)" in audit_indexes["uq_messages_run_role_operation_id"]
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v1_to_v2_adds_file_attempt_owner_idempotently() -> None:
    """知识 schema 相邻升级为文件中间态增加 Task attempt fencing。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_knowledge_schema")
    try:
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE knowledge_files ("
                    "id SERIAL PRIMARY KEY, file_id VARCHAR(64) NOT NULL, status VARCHAR(32), "
                    "error_message TEXT, updated_at TIMESTAMPTZ)"
                )
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, status) VALUES ('legacy-file', 'parsing')")
            )

        await manager.upgrade_knowledge_schema_v1_to_v2()
        await manager.upgrade_knowledge_schema_v1_to_v2()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_files'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            legacy = (
                await connection.execute(
                    text("SELECT status, error_message FROM knowledge_files WHERE file_id = 'legacy-file'")
                )
            ).one()
        assert {"processing_task_id", "processing_owner"} <= columns
        assert tuple(legacy) == (
            "error_parsing",
            "service_interrupted: 旧执行实例中断，处理结果未知，请重试",
        )
        assert KNOWLEDGE_SCHEMA_VERSION == 27
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_timestamp_defaults_match_database_clock_in_non_utc_session() -> None:
    """带时区字段不依赖 PostgreSQL 会话时区解释无时区 UTC。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_knowledge_clock")
    try:
        await manager.create_knowledge_tables()
        session_factory = async_sessionmaker(scoped_engine, expire_on_commit=False)
        async with session_factory.begin() as session:
            await session.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
            database = KnowledgeBase(kb_id="clock-kb", name="clock", kb_type="milvus")
            session.add(database)
            await session.flush()
            database_now = await session.scalar(text("SELECT clock_timestamp()"))

        async with session_factory() as verify_session:
            await verify_session.execute(text("SET TIME ZONE 'UTC'"))
            persisted_at = await verify_session.scalar(
                text("SELECT created_at FROM knowledge_bases WHERE kb_id = 'clock-kb'")
            )

        assert persisted_at.tzinfo is not None
        assert abs((persisted_at - database_now).total_seconds()) < 2
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v8_adds_governed_graph_contract_idempotently() -> None:
    """v7 图谱表可重复升级为带 Span、审核、本体和 outbox 的 v8。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_graph_v8")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            for constraint in (
                "ck_kg_triple_lifecycle_status",
                "ck_kg_triple_relation_version",
                "ck_kg_triple_supersession",
            ):
                await connection.execute(
                    text(f"ALTER TABLE knowledge_graph_triples DROP CONSTRAINT IF EXISTS {constraint}")
                )
            await connection.execute(text("DROP INDEX IF EXISTS ix_kg_triple_lifecycle"))
            await connection.execute(text("DROP INDEX IF EXISTS ix_kg_triple_superseded_by"))
            for column in (
                "mention_text",
                "start_char",
                "end_char",
                "confidence",
                "model_version",
                "ontology_version",
                "review_status",
            ):
                await connection.execute(
                    text(f"ALTER TABLE knowledge_graph_entity_mentions DROP COLUMN IF EXISTS {column}")
                )
            for column in (
                "claim_level",
                "confidence",
                "evidence_quote",
                "evidence_spans",
                "reasoning_basis",
                "uncertainty",
                "expert_review_required",
                "review_status",
                "model_version",
                "ontology_version",
                "pipeline_revision",
            ):
                await connection.execute(
                    text(f"ALTER TABLE knowledge_graph_triple_mentions DROP COLUMN IF EXISTS {column}")
                )

        await manager.upgrade_knowledge_schema_v7_to_v8()
        await manager.upgrade_knowledge_schema_v7_to_v8()

        async with scoped_engine.connect() as connection:
            tables = set(
                (
                    await connection.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                        {"schema": schema},
                    )
                ).scalars()
            )
            entity_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_graph_entity_mentions'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            triple_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_graph_triple_mentions'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert {
            "ontology_versions",
            "ontology_entity_types",
            "ontology_relation_types",
            "knowledge_graph_entity_aliases",
            "knowledge_graph_review_decisions",
            "knowledge_graph_build_runs",
            "knowledge_graph_revisions",
            "knowledge_graph_projection_outbox",
        } <= tables
        assert {"start_char", "end_char", "confidence", "model_version", "ontology_version", "review_status"} <= (
            entity_columns
        )
        assert {
            "claim_level",
            "evidence_spans",
            "review_status",
            "pipeline_revision",
        } <= triple_columns
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v9_adds_parsed_block_lineage_idempotently() -> None:
    """v8 可重复升级为带页码、bbox、标题路径和解析器版本的 v9。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_parsed_block_v9")
    expected_columns = {
        "document_version",
        "page_number",
        "block_type",
        "heading_path",
        "bbox",
        "parser_name",
        "parser_version",
        "source_metadata",
    }
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            for column in expected_columns:
                await connection.execute(text(f"ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS {column}"))

        await manager.upgrade_knowledge_schema_v8_to_v9()
        await manager.upgrade_knowledge_schema_v8_to_v9()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_chunks'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
        assert expected_columns <= columns
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v10_adds_evolution_and_hypothesis_governance_idempotently() -> None:
    """v9 可重复升级为实体 redirect、变更事件、创新假设与趋势快照的 v10。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_graph_evolution_v10")
    expected_tables = {
        "knowledge_graph_entity_redirects",
        "knowledge_graph_change_events",
        "knowledge_graph_hypotheses",
        "knowledge_graph_trend_snapshots",
    }
    expected_entity_columns = {
        "lifecycle_status",
        "superseded_by_entity_id",
        "valid_from",
        "valid_to",
        "entity_version",
    }
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            for table in expected_tables:
                await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
            for column in expected_entity_columns:
                await connection.execute(text(f"ALTER TABLE knowledge_graph_entities DROP COLUMN IF EXISTS {column}"))

        await manager.upgrade_knowledge_schema_v9_to_v10()
        await manager.upgrade_knowledge_schema_v9_to_v10()

        async with scoped_engine.connect() as connection:
            tables = set(
                (
                    await connection.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                        {"schema": schema},
                    )
                ).scalars()
            )
            entity_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_graph_entities'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
        assert expected_tables <= tables
        assert expected_entity_columns <= entity_columns
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v11_adds_source_versions_build_lineage_and_evaluation_idempotently() -> None:
    """v10 可重复升级为来源版本、构建运行谱系和验收报告的 v11。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_graph_acceptance_v11")
    expected_tables = {
        "knowledge_source_documents",
        "knowledge_document_versions",
        "knowledge_graph_evaluation_runs",
    }
    expected_build_columns = {
        "scope",
        "document_ids",
        "rule_version",
        "started_by",
        "attempt_count",
    }
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS knowledge_graph_evaluation_runs"))
            await connection.execute(text("DROP TABLE IF EXISTS knowledge_document_versions CASCADE"))
            await connection.execute(text("DROP TABLE IF EXISTS knowledge_source_documents"))
            for column in expected_build_columns:
                await connection.execute(text(f"ALTER TABLE knowledge_graph_build_runs DROP COLUMN IF EXISTS {column}"))

        await manager.upgrade_knowledge_schema_v10_to_v11()
        await manager.upgrade_knowledge_schema_v10_to_v11()

        async with scoped_engine.connect() as connection:
            tables = set(
                (
                    await connection.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                        {"schema": schema},
                    )
                ).scalars()
            )
            build_columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_graph_build_runs'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
        assert expected_tables <= tables
        assert expected_build_columns <= build_columns
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v12_preserves_distinct_entity_mention_spans_idempotently() -> None:
    """v11 mention 唯一键可重复升级为 Span 级约束并保持旧数据幂等语义。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_graph_mentions_v12")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP INDEX IF EXISTS uq_kg_entity_mentions_span"))
            await connection.execute(text("DROP INDEX IF EXISTS uq_kg_entity_mentions_unspanned"))
            await connection.execute(
                text(
                    "ALTER TABLE knowledge_graph_entity_mentions "
                    "ADD CONSTRAINT uq_knowledge_graph_entity_mentions_entity_chunk "
                    "UNIQUE (entity_id, chunk_id)"
                )
            )

        await manager.upgrade_knowledge_schema_v11_to_v12()
        await manager.upgrade_knowledge_schema_v11_to_v12()

        async with scoped_engine.connect() as connection:
            old_constraint = await connection.scalar(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'knowledge_graph_entity_mentions' "
                    "AND constraint_name = 'uq_knowledge_graph_entity_mentions_entity_chunk'"
                ),
                {"schema": schema},
            )
            indexes = set(
                (
                    await connection.execute(
                        text(
                            "SELECT indexname FROM pg_indexes "
                            "WHERE schemaname = :schema "
                            "AND tablename = 'knowledge_graph_entity_mentions'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert old_constraint is None
        assert {"uq_kg_entity_mentions_span", "uq_kg_entity_mentions_unspanned"} <= indexes

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('kb', 'kb', 'milvus')")
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, kb_id, filename) VALUES ('file', 'kb', 'file.md')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(chunk_id, file_id, kb_id, chunk_index, content, document_version, heading_path, "
                    "graph_structure_indexed, graph_extraction_details) "
                    "VALUES ('chunk', 'file', 'kb', 0, 'entity entity', 1, jsonb_build_array(), false, "
                    "jsonb_build_object('status', 'pending', 'attempt_count', 0))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(chunk_id, file_id, kb_id, chunk_index, content, document_version, heading_path, "
                    "graph_structure_indexed, graph_extraction_details) "
                    "VALUES ('legacy-unspanned', 'file', 'kb', 1, 'entity', 1, jsonb_build_array(), false, "
                    "jsonb_build_object('status', 'pending', 'attempt_count', 0))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_entities "
                    "(entity_id, kb_id, normalized_name, label, name, lifecycle_status, entity_version, "
                    "vector_status, vector_attempt_count) "
                    "VALUES ('entity', 'kb', 'entity', 'KeyTechnology', 'entity', 'active', 1, 'pending', 0)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_entity_mentions "
                    "(entity_id, kb_id, file_id, chunk_id, start_char, end_char, review_status) VALUES "
                    "('entity', 'kb', 'file', 'chunk', 0, 6, 'pending'), "
                    "('entity', 'kb', 'file', 'chunk', 7, 13, 'pending'), "
                    "('entity', 'kb', 'file', 'legacy-unspanned', NULL, NULL, 'pending')"
                )
            )

        async with scoped_engine.connect() as connection:
            mentions = (
                await connection.execute(
                    text(
                        "SELECT chunk_id, start_char, end_char FROM knowledge_graph_entity_mentions "
                        "ORDER BY chunk_id, start_char"
                    )
                )
            ).all()
        assert mentions == [("chunk", 0, 6), ("chunk", 7, 13), ("legacy-unspanned", None, None)]

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_entity_mentions "
                        "(entity_id, kb_id, file_id, chunk_id, start_char, end_char, review_status) "
                        "VALUES ('entity', 'kb', 'file', 'chunk', 0, 6, 'pending')"
                    )
                )

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_entity_mentions "
                        "(entity_id, kb_id, file_id, chunk_id, start_char, end_char, review_status) "
                        "VALUES ('entity', 'kb', 'file', 'legacy-unspanned', NULL, NULL, 'pending')"
                    )
                )
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v13_adds_relation_applicable_conditions_idempotently() -> None:
    """v12 关系证据可重复升级并为既有 mention 回填空适用条件。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_relation_conditions_v13")
    session_factory = async_sessionmaker(scoped_engine, expire_on_commit=False)
    try:
        await manager.create_knowledge_tables()
        async with session_factory.begin() as session:
            session.add(KnowledgeBase(kb_id="kb", name="kb", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id="file", kb_id="kb", filename="file.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id="chunk",
                    file_id="file",
                    kb_id="kb",
                    chunk_index=0,
                    content="技术在低温条件下提升能力",
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id="source",
                        kb_id="kb",
                        normalized_name="技术",
                        label="KeyTechnology",
                        name="技术",
                    ),
                    KnowledgeGraphEntity(
                        entity_id="target",
                        kb_id="kb",
                        normalized_name="能力",
                        label="Capability",
                        name="能力",
                    ),
                ]
            )
            await session.flush()
            session.add(
                KnowledgeGraphTriple(
                    triple_id="triple",
                    kb_id="kb",
                    source_entity_id="source",
                    target_entity_id="target",
                    relation_type="ENABLES_CAPABILITY",
                    content="技术 → ENABLES_CAPABILITY → 能力",
                )
            )
            await session.flush()
            session.add(
                KnowledgeGraphTripleMention(
                    triple_id="triple",
                    kb_id="kb",
                    file_id="file",
                    chunk_id="chunk",
                )
            )
            session.add(
                KnowledgeGraphHypothesis(
                    hypothesis_id="hypothesis",
                    kb_id="kb",
                    source_entity_id="source",
                    target_entity_id="target",
                    relation_type="POTENTIAL_FOR",
                    discovery_mode="top_down",
                    score=0.72,
                    evidence_path=[],
                    algorithm_version="test-v1",
                )
            )

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE knowledge_graph_triple_mentions DROP COLUMN applicable_conditions")
            )
            await connection.execute(text("ALTER TABLE knowledge_graph_hypotheses DROP COLUMN applicable_conditions"))

        await manager.upgrade_knowledge_schema_v12_to_v13()
        await manager.upgrade_knowledge_schema_v12_to_v13()

        async with scoped_engine.connect() as connection:
            columns = (
                await connection.execute(
                    text(
                        "SELECT table_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = :schema "
                        "AND table_name IN ('knowledge_graph_triple_mentions', 'knowledge_graph_hypotheses') "
                        "AND column_name = 'applicable_conditions'"
                    ),
                    {"schema": schema},
                )
            ).all()
            mention_value = await connection.scalar(
                text("SELECT applicable_conditions FROM knowledge_graph_triple_mentions WHERE triple_id = 'triple'")
            )
            hypothesis_value = await connection.scalar(
                text("SELECT applicable_conditions FROM knowledge_graph_hypotheses WHERE hypothesis_id = 'hypothesis'")
            )

        assert {column.table_name for column in columns} == {
            "knowledge_graph_triple_mentions",
            "knowledge_graph_hypotheses",
        }
        assert all(column.data_type == "jsonb" for column in columns)
        assert all(column.is_nullable == "NO" for column in columns)
        assert all("[]" in column.column_default for column in columns)
        assert mention_value == []
        assert hypothesis_value == []
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v14_adds_double_annotation_and_adjudication_idempotently() -> None:
    """v13 可重复升级为双标活动，并由 PostgreSQL 保证版本与角色约束。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_annotation_v14")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE knowledge_graph_annotation_adjudications"))
            await connection.execute(text("DROP TABLE knowledge_graph_annotation_submissions"))
            await connection.execute(text("DROP TABLE knowledge_graph_annotation_assignments"))
            await connection.execute(text("DROP TABLE knowledge_graph_annotation_campaigns"))

        await manager.upgrade_knowledge_schema_v13_to_v14()
        await manager.upgrade_knowledge_schema_v13_to_v14()

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('kb', 'kb', 'milvus')")
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, kb_id, filename) VALUES ('file', 'kb', 'paper.pdf')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_source_documents "
                    "(document_id, kb_id, file_id, source_type, language, domain, current_version, "
                    "source_metadata, created_at, updated_at) "
                    "VALUES ('doc', 'kb', 'file', 'paper', 'zh', 'radar', 1, '{}'::jsonb, now(), now())"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_document_versions "
                    "(document_id, version, content_hash, input_hash, source_metadata, created_at) "
                    "VALUES ('doc', 1, 'content', 'input', '{}'::jsonb, now())"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_annotation_campaigns "
                    "(campaign_id, kb_id, name, guideline_version, ontology_version, created_by) VALUES "
                    "('campaign', 'kb', 'Pilot', 'defense-kg-annotation-v1', 'defense-kg-1.0', 'owner'), "
                    "('roles', 'kb', 'Roles', 'defense-kg-annotation-v1', 'defense-kg-1.0', 'owner'), "
                    "('versions', 'kb', 'Versions', 'defense-kg-annotation-v1', 'defense-kg-1.0', 'owner')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_annotation_assignments "
                    "(assignment_id, campaign_id, document_id, document_version, split, "
                    "annotator_a_uid, annotator_b_uid, arbitrator_uid) "
                    "VALUES ('assignment', 'campaign', 'doc', 1, 'train', 'ann-a', 'ann-b', 'expert')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_annotation_submissions "
                    "(submission_id, assignment_id, annotator_uid, revision, annotation_payload, payload_sha256) "
                    "VALUES "
                    "('sub-a-1', 'assignment', 'ann-a', 1, '{}'::jsonb, repeat('a', 64)), "
                    "('sub-a-2', 'assignment', 'ann-a', 2, '{}'::jsonb, repeat('b', 64)), "
                    "('sub-b-1', 'assignment', 'ann-b', 1, '{}'::jsonb, repeat('c', 64))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_annotation_adjudications "
                    "(adjudication_id, assignment_id, arbitrator_uid, final_payload, payload_sha256) "
                    "VALUES ('adj', 'assignment', 'expert', '{}'::jsonb, repeat('d', 64))"
                )
            )

        async with scoped_engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_name LIKE 'knowledge_graph_annotation_%'"
                    ),
                    {"schema": schema},
                )
            )
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname LIKE 'knowledge_graph_annotation_%'"
                    ),
                    {"schema": schema},
                )
            )
            revisions = list(
                await connection.scalars(
                    text(
                        "SELECT revision FROM knowledge_graph_annotation_submissions "
                        "WHERE assignment_id = 'assignment' AND annotator_uid = 'ann-a' ORDER BY revision"
                    )
                )
            )

        assert tables == {
            "knowledge_graph_annotation_campaigns",
            "knowledge_graph_annotation_assignments",
            "knowledge_graph_annotation_submissions",
            "knowledge_graph_annotation_adjudications",
        }
        assert {
            "ck_kg_annotation_campaign_status",
            "fk_kg_annotation_assignment_document_version",
            "ck_kg_annotation_assignment_document_version",
            "ck_kg_annotation_assignment_split",
            "ck_kg_annotation_assignment_status",
            "ck_kg_annotation_assignment_distinct_roles",
            "uq_kg_annotation_campaign_document",
            "ck_kg_annotation_submission_revision",
            "uq_kg_annotation_submission_revision",
            "uq_kg_annotation_adjudication_assignment",
        } <= constraints
        assert revisions == [1, 2]

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_annotation_assignments "
                        "(assignment_id, campaign_id, document_id, document_version, split, "
                        "annotator_a_uid, annotator_b_uid, arbitrator_uid) "
                        "VALUES ('bad-roles', 'roles', 'doc', 1, 'train', 'same', 'same', 'expert')"
                    )
                )

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_annotation_assignments "
                        "(assignment_id, campaign_id, document_id, document_version, split, "
                        "annotator_a_uid, annotator_b_uid, arbitrator_uid) "
                        "VALUES ('bad-version', 'versions', 'doc', 99, 'train', 'a', 'b', 'c')"
                    )
                )

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_annotation_assignments "
                        "(assignment_id, campaign_id, document_id, document_version, split, "
                        "annotator_a_uid, annotator_b_uid, arbitrator_uid) "
                        "VALUES ('duplicate-doc', 'campaign', 'doc', 1, 'dev', 'x', 'y', 'z')"
                    )
                )

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_annotation_submissions "
                        "(submission_id, assignment_id, annotator_uid, revision, "
                        "annotation_payload, payload_sha256) "
                        "VALUES ('duplicate-revision', 'assignment', 'ann-a', 2, '{}'::jsonb, repeat('e', 64))"
                    )
                )

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_graph_annotation_adjudications "
                        "(adjudication_id, assignment_id, arbitrator_uid, final_payload, payload_sha256) "
                        "VALUES ('duplicate-adj', 'assignment', 'expert', '{}'::jsonb, repeat('f', 64))"
                    )
                )
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v15_adds_stage_runs_and_conflicts_idempotently() -> None:
    """v14 可重复升级为阶段日志和冲突治理表，并保留数据库约束。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_graph_operability_v15")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE knowledge_graph_conflicts"))
            await connection.execute(text("DROP TABLE knowledge_graph_build_stage_runs"))

        await manager.upgrade_knowledge_schema_v14_to_v15()
        await manager.upgrade_knowledge_schema_v14_to_v15()

        async with scoped_engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_name IN "
                        "('knowledge_graph_build_stage_runs', 'knowledge_graph_conflicts')"
                    ),
                    {"schema": schema},
                )
            )
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname IN "
                        "('knowledge_graph_build_stage_runs', 'knowledge_graph_conflicts')"
                    ),
                    {"schema": schema},
                )
            )

        assert tables == {"knowledge_graph_build_stage_runs", "knowledge_graph_conflicts"}
        assert {
            "uq_kg_build_stage_attempt",
            "ck_kg_build_stage_order",
            "ck_kg_build_stage_attempt",
            "ck_kg_build_stage_status",
            "uq_kg_conflict_fingerprint",
            "ck_kg_conflict_status",
            "ck_kg_conflict_severity",
            "ck_kg_conflict_left_target",
            "ck_kg_conflict_right_target",
            "ck_kg_conflict_right_pair",
        } <= constraints
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v16_adds_relation_lifecycle_idempotently() -> None:
    """v15 可重复升级为关系生命周期字段，并由 PostgreSQL 约束状态组合。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_relation_lifecycle_v16")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            for column in (
                "lifecycle_status",
                "superseded_by_triple_id",
                "valid_from",
                "valid_to",
                "relation_version",
            ):
                await connection.execute(text(f"ALTER TABLE knowledge_graph_triples DROP COLUMN IF EXISTS {column}"))

        await manager.upgrade_knowledge_schema_v15_to_v16()
        await manager.upgrade_knowledge_schema_v15_to_v16()

        async with scoped_engine.connect() as connection:
            columns = {
                row.column_name: row
                for row in (
                    await connection.execute(
                        text(
                            "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name = 'knowledge_graph_triples' "
                            "AND column_name IN ('lifecycle_status', 'superseded_by_triple_id', "
                            "'valid_from', 'valid_to', 'relation_version')"
                        ),
                        {"schema": schema},
                    )
                ).all()
            }
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'knowledge_graph_triples'"
                    ),
                    {"schema": schema},
                )
            )

        assert set(columns) == {
            "lifecycle_status",
            "superseded_by_triple_id",
            "valid_from",
            "valid_to",
            "relation_version",
        }
        assert columns["lifecycle_status"].is_nullable == "NO"
        assert "active" in columns["lifecycle_status"].column_default
        assert columns["valid_from"].is_nullable == "NO"
        assert columns["relation_version"].is_nullable == "NO"
        assert {
            "ck_kg_triple_lifecycle_status",
            "ck_kg_triple_relation_version",
            "ck_kg_triple_supersession",
        } <= constraints

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('kb', 'kb', 'milvus')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_entities "
                    "(entity_id, kb_id, normalized_name, label, name, lifecycle_status, entity_version, "
                    "vector_status, vector_attempt_count) VALUES "
                    "('source', 'kb', 'source', 'KeyTechnology', 'source', 'active', 1, 'pending', 0), "
                    "('target', 'kb', 'target', 'Capability', 'target', 'active', 1, 'pending', 0)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_graph_triples "
                    "(triple_id, kb_id, source_entity_id, target_entity_id, relation_type, content, "
                    "vector_status, vector_attempt_count) "
                    "VALUES ('active', 'kb', 'source', 'target', 'ENABLES_CAPABILITY', 'active', 'pending', 0)"
                )
            )

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE knowledge_graph_triples SET lifecycle_status = 'superseded' WHERE triple_id = 'active'"
                    )
                )
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v17_governs_ontology_versions_idempotently() -> None:
    """v16 可重复升级并回填本体生效时间，同时拒绝非法生命周期。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_ontology_governance_v17")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO ontology_versions "
                    "(version, name, definition, status, change_reason, effective_at, created_at) VALUES "
                    "('legacy-ontology', 'legacy', '{}'::jsonb, 'active', 'legacy import', NULL, NOW())"
                )
            )

        await manager.upgrade_knowledge_schema_v16_to_v17()
        await manager.upgrade_knowledge_schema_v16_to_v17()

        async with scoped_engine.connect() as connection:
            effective_at = await connection.scalar(
                text("SELECT effective_at FROM ontology_versions WHERE version = 'legacy-ontology'")
            )
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'ontology_versions'"
                    ),
                    {"schema": schema},
                )
            )
        assert effective_at is not None
        assert {
            "ck_ontology_version_status",
            "ck_ontology_version_effective_at",
            "ck_ontology_version_previous",
        } <= constraints

        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO ontology_versions "
                        "(version, name, definition, status, change_reason, effective_at, created_at) VALUES "
                        "('invalid-active', 'invalid', '{}'::jsonb, 'active', 'invalid', NULL, NOW())"
                    )
                )
        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE ontology_versions SET previous_version = 'legacy-ontology' "
                        "WHERE version = 'legacy-ontology'"
                    )
                )
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v18_adds_document_audit_idempotently() -> None:
    """v17 可重复升级文档分流、研究链和知识卡 Schema。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_document_audit_v18")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE knowledge_document_cards"))
            await connection.execute(text("DROP TABLE knowledge_research_threads"))
            await connection.execute(text("DROP TABLE knowledge_document_triage"))
            await connection.execute(text("ALTER TABLE knowledge_chunks DROP COLUMN graph_exclusion_reason"))
            await connection.execute(text("ALTER TABLE knowledge_chunks DROP COLUMN graph_excluded"))

        await manager.upgrade_knowledge_schema_v17_to_v18()
        await manager.upgrade_knowledge_schema_v17_to_v18()

        async with scoped_engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                    {"schema": schema},
                )
            )
            columns = set(
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = 'knowledge_chunks'"
                    ),
                    {"schema": schema},
                )
            )
        assert {
            "knowledge_document_triage",
            "knowledge_research_threads",
            "knowledge_document_cards",
        } <= tables
        assert {"graph_excluded", "graph_exclusion_reason"} <= columns
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_v19_adds_governance_idempotently() -> None:
    """v18 可重复升级分类、来源、简报和采集成果 Schema。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_governance_v19")
    governance_tables = {
        "knowledge_categories",
        "knowledge_source_credentials",
        "knowledge_sources",
        "knowledge_source_runs",
        "knowledge_source_items",
        "innovation_brief_subscriptions",
        "innovation_brief_runs",
        "innovation_briefs",
        "brief_delivery_outbox",
        "collection_artifact_records",
        "collection_artifact_ingestions",
    }
    try:
        await manager.create_knowledge_tables()

        async with scoped_engine.connect() as connection:
            orm_index = await connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = :schema "
                    "AND tablename = 'knowledge_categories' "
                    "AND indexname = 'uq_knowledge_category_sibling_normalized'"
                ),
                {"schema": schema},
            )
        assert orm_index is not None
        assert "COALESCE" in orm_index

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO knowledge_categories "
                    "(id, tenant_id, name, description, sort_order, active, created_by, created_at, updated_at) "
                    "VALUES ('orm-root', 'tenant-a', '无人系统', '', 0, TRUE, 'tester', NOW(), NOW())"
                )
            )
        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_categories "
                        "(id, tenant_id, name, description, sort_order, active, created_by, created_at, updated_at) "
                        "VALUES "
                        "('orm-root-duplicate', 'tenant-a', '无人系统', '', 0, TRUE, 'tester', NOW(), NOW())"
                    )
                )

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "DROP TABLE brief_delivery_outbox, innovation_briefs, innovation_brief_runs, "
                    "innovation_brief_subscriptions, collection_artifact_ingestions, "
                    "collection_artifact_records, knowledge_source_items, knowledge_source_runs, "
                    "knowledge_sources, knowledge_source_credentials, knowledge_categories CASCADE"
                )
            )
            await connection.execute(text("ALTER TABLE knowledge_bases DROP COLUMN category_id"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN category_id"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN source_id"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN source_item_id"))
            await connection.execute(
                text("ALTER TABLE knowledge_graph_annotation_campaigns DROP COLUMN acceptance_languages")
            )

        await manager.upgrade_knowledge_schema_v18_to_v19()
        await manager.upgrade_knowledge_schema_v18_to_v19()

        async with scoped_engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
                    {"schema": schema},
                )
            )
            kb_columns = set(
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = 'knowledge_bases'"
                    ),
                    {"schema": schema},
                )
            )
            file_columns = set(
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema AND table_name = 'knowledge_files'"
                    ),
                    {"schema": schema},
                )
            )
            foreign_keys = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND c.contype = 'f' "
                        "AND t.relname IN ('knowledge_bases', 'knowledge_files')"
                    ),
                    {"schema": schema},
                )
            )
            indexes = set(
                await connection.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = :schema "
                        "AND indexname IN ("
                        "'uq_knowledge_category_sibling_normalized', "
                        "'ix_knowledge_source_item_queue', "
                        "'ix_innovation_brief_feed', "
                        "'ix_collection_artifact_owner_status')"
                    ),
                    {"schema": schema},
                )
            )
            subscription_defaults = (
                await connection.execute(
                    text(
                        "SELECT column_name, column_default FROM information_schema.columns "
                        "WHERE table_schema = :schema "
                        "AND table_name = 'innovation_brief_subscriptions' "
                        "AND column_name IN ('timezone', 'daily_cron', 'weekly_cron', "
                        "'reminder_sensitivity', 'significance_threshold')"
                    ),
                    {"schema": schema},
                )
            ).all()

        assert governance_tables <= tables
        assert "category_id" in kb_columns
        assert {"category_id", "source_id", "source_item_id"} <= file_columns
        assert {
            "fk_knowledge_bases_category",
            "fk_knowledge_files_category",
            "fk_knowledge_files_source",
            "fk_knowledge_files_source_item",
        } <= foreign_keys
        assert indexes == {
            "uq_knowledge_category_sibling_normalized",
            "ix_knowledge_source_item_queue",
            "ix_innovation_brief_feed",
            "ix_collection_artifact_owner_status",
        }
        assert {name for name, default in subscription_defaults if default is not None} == {
            "timezone",
            "daily_cron",
            "weekly_cron",
            "reminder_sensitivity",
            "significance_threshold",
        }

        async with scoped_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO knowledge_categories (id, tenant_id, name, created_by) "
                    "VALUES ('migration-root', 'tenant-a', '反无人系统', 'tester')"
                )
            )
        with pytest.raises(IntegrityError):
            async with scoped_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO knowledge_categories (id, tenant_id, name, created_by) "
                        "VALUES ('migration-root-duplicate', 'tenant-a', '反无人系统', 'tester')"
                    )
                )

        await manager.upgrade_knowledge_schema_v19_to_v20()
        await manager.upgrade_knowledge_schema_v19_to_v20()
        async with scoped_engine.connect() as connection:
            acceptance_default = await connection.scalar(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_schema = :schema "
                    "AND table_name = 'knowledge_graph_annotation_campaigns' "
                    "AND column_name = 'acceptance_languages'"
                ),
                {"schema": schema},
            )
        assert acceptance_default is not None
        assert "en" in acceptance_default
        assert "zh" in acceptance_default

        await manager.upgrade_knowledge_schema_v20_to_v21()
        await manager.upgrade_knowledge_schema_v20_to_v21()
        async with scoped_engine.connect() as connection:
            card_columns = set(
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema "
                        "AND table_name = 'knowledge_document_cards' "
                        "AND column_name IN ('key_metrics', 'transfer_potential', "
                        "'graph_rag_hints', 'narrative_report')"
                    ),
                    {"schema": schema},
                )
            )
        assert card_columns == {
            "key_metrics",
            "transfer_potential",
            "graph_rag_hints",
            "narrative_report",
        }

        await manager.upgrade_knowledge_schema_v21_to_v22()
        await manager.upgrade_knowledge_schema_v21_to_v22()
        async with scoped_engine.connect() as connection:
            brief_columns = set(
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = :schema "
                        "AND table_name = 'innovation_brief_subscriptions' "
                        "AND column_name IN ('open_discovery_enabled', 'research_explorer_enabled')"
                    ),
                    {"schema": schema},
                )
            )
            defaults = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name, column_default FROM information_schema.columns "
                            "WHERE table_schema = :schema "
                            "AND table_name = 'innovation_brief_subscriptions' "
                            "AND column_name IN ('open_discovery_enabled', 'research_explorer_enabled')"
                        ),
                        {"schema": schema},
                    )
                ).all()
            )
        assert brief_columns == {"open_discovery_enabled", "research_explorer_enabled"}
        assert all(str(value).casefold() == "true" for value in defaults.values())
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_video_collector_migration_is_idempotent() -> None:
    """视频号采集表可重复创建。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_video_collector")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE wechat_collector_captures"))
            await connection.execute(text("DROP TABLE wechat_collector_devices"))
        await manager.upgrade_knowledge_schema_v3_to_v4()
        await manager.upgrade_knowledge_schema_v3_to_v4()
        async with scoped_engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('wechat_collector_devices')")) is not None
            assert await connection.scalar(text("SELECT to_regclass('wechat_collector_captures')")) is not None
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_retired_article_cleanup_preserves_video_and_knowledge_data() -> None:
    """旧文章表、任务和交接物被清理，视频配对及已入库文件保持完整。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_article_removal")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text(LEGACY_TASK_TABLE_SQL))
            await connection.execute(text("CREATE TABLE wechat_article_archives (article_id text PRIMARY KEY)"))
            await connection.execute(
                text(
                    "CREATE TABLE wechat_article_destinations "
                    "(article_id text REFERENCES wechat_article_archives(article_id))"
                )
            )
            await connection.execute(text("CREATE TABLE wechat_subscriptions (subscription_id text PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO wechat_article_archives VALUES ('old')"))
            await connection.execute(text("INSERT INTO wechat_article_destinations VALUES ('old')"))
            await connection.execute(text("INSERT INTO wechat_subscriptions VALUES ('old')"))
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('keep', 'keep', 'milvus')")
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, kb_id, filename) VALUES ('keep', 'keep', 'imported.docx')")
            )
            await connection.execute(
                text(
                    "INSERT INTO wechat_collector_devices "
                    "(device_id, owner_uid, name, platform, token_digest, state, created_at) "
                    "VALUES ('video-device', 'owner', 'pc', 'macos', 'digest', '{}', now())"
                )
            )
            for task_id, task_type in [
                ("old", "wechat_article_ingest"),
                ("search", "wechat_account_discover"),
                ("video", "wxchannels_transcribe"),
                ("other", "knowledge_index"),
            ]:
                await connection.execute(
                    text("INSERT INTO tasks (id, name, type, status) VALUES (:id, 'sample', :type, 'pending')"),
                    {"id": task_id, "type": task_type},
                )
            for task_id in ("old", "video"):
                await connection.execute(
                    text(
                        "INSERT INTO wechat_collector_captures "
                        "(capture_id, task_id, execution_id, device_id, sequence, kind, detail, created_at) "
                        "VALUES (:id, :id, 'lease', 'video-device', 1, 'complete', '{}', now())"
                    ),
                    {"id": task_id},
                )
        await manager.upgrade_knowledge_schema_v5_to_v6()
        await manager.upgrade_knowledge_schema_v5_to_v6()
        async with scoped_engine.connect() as connection:
            for table in ("wechat_article_archives", "wechat_article_destinations", "wechat_subscriptions"):
                assert await connection.scalar(text("SELECT to_regclass(:name)"), {"name": table}) is None
            assert set(await connection.scalars(text("SELECT id FROM tasks"))) == {"video", "other"}
            assert list(await connection.scalars(text("SELECT task_id FROM wechat_collector_captures"))) == ["video"]
            assert await connection.scalar(text("SELECT count(*) FROM wechat_collector_devices")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM knowledge_files")) == 1
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_unversioned_knowledge_baseline_adds_timestamp_before_owner_convergence() -> None:
    """未版本化的旧表缺少 updated_at 时仍能收敛中间态。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_knowledge_baseline")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('legacy-kb', 'legacy', 'milvus')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_files (file_id, kb_id, filename, status) "
                    "VALUES ('legacy-file', 'legacy-kb', 'legacy.txt', 'indexing')"
                )
            )
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN processing_task_id"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN processing_owner"))
            await connection.execute(text("ALTER TABLE knowledge_files DROP COLUMN updated_at"))

        await manager.create_knowledge_tables()
        await manager.ensure_knowledge_schema()

        async with scoped_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status, error_message, updated_at, processing_task_id, processing_owner "
                        "FROM knowledge_files WHERE file_id = 'legacy-file'"
                    )
                )
            ).one()
        assert row.status == "error_indexing"
        assert row.error_message == "service_interrupted: 旧执行实例中断，处理结果未知，请重试"
        assert row.updated_at is not None
        assert row.processing_task_id is None
        assert row.processing_owner is None
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_schema_distinguishes_json_null_from_extracted_payload() -> None:
    """JSON null 不能冒充成功抽取，真实对象仍应兼容收敛为 succeeded。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_extraction_status")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('kb', 'kb', 'milvus')")
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, kb_id, filename) VALUES ('file', 'kb', 'file.md')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(chunk_id, file_id, kb_id, chunk_index, content, document_version, heading_path, "
                    "graph_structure_indexed, graph_indexed, graph_excluded, extraction_result, "
                    "graph_extraction_details) VALUES "
                    "('json-null', 'file', 'kb', 0, '尚未抽取', 1, jsonb_build_array(), false, false, false, "
                    "'null'::jsonb, "
                    "jsonb_build_object('status', 'succeeded')), "
                    "('real-result', 'file', 'kb', 1, '已有结果', 1, jsonb_build_array(), false, false, false, "
                    "jsonb_build_object('entities', jsonb_build_array(), 'relations', jsonb_build_array()), "
                    "jsonb_build_object('status', 'pending', 'attempt_count', 0))"
                )
            )

        await manager.ensure_knowledge_schema()
        await manager.ensure_knowledge_schema()

        async with scoped_engine.connect() as connection:
            rows = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT chunk_id, graph_extraction_details->>'status' "
                            "FROM knowledge_chunks ORDER BY chunk_id"
                        )
                    )
                ).all()
            )

        assert rows == {"json-null": "pending", "real-result": "succeeded"}
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v22_to_v23_repairs_json_null_extraction_status_idempotently() -> None:
    """v23 迁移应恢复 JSON null 为 pending，并保留真实结果为 succeeded。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_extraction_status_v23")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO knowledge_bases (kb_id, name, kb_type) VALUES ('kb', 'kb', 'milvus')")
            )
            await connection.execute(
                text("INSERT INTO knowledge_files (file_id, kb_id, filename) VALUES ('file', 'kb', 'file.md')")
            )
            await connection.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(chunk_id, file_id, kb_id, chunk_index, content, document_version, heading_path, "
                    "graph_structure_indexed, graph_indexed, graph_excluded, extraction_result, "
                    "graph_extraction_details) VALUES "
                    "('json-null', 'file', 'kb', 0, '尚未抽取', 1, jsonb_build_array(), false, false, false, "
                    "'null'::jsonb, jsonb_build_object('status', 'succeeded')), "
                    "('real-result', 'file', 'kb', 1, '已有结果', 1, jsonb_build_array(), false, false, false, "
                    "jsonb_build_object('entities', jsonb_build_array(), 'relations', jsonb_build_array()), "
                    "jsonb_build_object('status', 'pending', 'attempt_count', 0))"
                )
            )

        await manager.upgrade_knowledge_schema_v22_to_v23()
        await manager.upgrade_knowledge_schema_v22_to_v23()

        async with scoped_engine.connect() as connection:
            rows = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT chunk_id, graph_extraction_details->>'status' "
                            "FROM knowledge_chunks ORDER BY chunk_id"
                        )
                    )
                ).all()
            )

        assert rows == {"json-null": "pending", "real-result": "succeeded"}
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v23_to_v24_creates_annotation_drafts_idempotently() -> None:
    """v24 迁移应幂等创建草稿表、提交跟踪列和唯一约束。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_annotation_drafts_v24")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE knowledge_graph_annotation_drafts"))

        await manager.upgrade_knowledge_schema_v23_to_v24()
        await manager.upgrade_knowledge_schema_v23_to_v24()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = :schema "
                            "AND table_name = 'knowledge_graph_annotation_drafts'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT constraint_name FROM information_schema.table_constraints "
                            "WHERE table_schema = :schema "
                            "AND table_name = 'knowledge_graph_annotation_drafts'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert {
            "annotation_payload",
            "payload_sha256",
            "source_kind",
            "provenance",
            "last_submitted_draft_sha256",
            "last_submitted_revision",
            "last_submitted_at",
        } <= columns
        assert "uq_kg_annotation_draft_assignment_annotator" in constraints
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v24_to_v25_adds_lightrag_relation_review_idempotently() -> None:
    """v25 迁移应幂等增加可空 JSONB 逐关系复核审计。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_lightrag_review_v25")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE knowledge_graph_triple_mentions DROP COLUMN secondary_review"))

        await manager.upgrade_knowledge_schema_v24_to_v25()
        await manager.upgrade_knowledge_schema_v24_to_v25()

        async with scoped_engine.connect() as connection:
            column = (
                await connection.execute(
                    text(
                        "SELECT data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = :schema "
                        "AND table_name = 'knowledge_graph_triple_mentions' "
                        "AND column_name = 'secondary_review'"
                    ),
                    {"schema": schema},
                )
            ).one()

        assert tuple(column) == ("jsonb", "YES")
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v25_to_v26_adds_scheduled_brief_delivery_idempotently() -> None:
    """简报准备、发布和 Outbox 计划时间字段可在旧库上幂等补齐。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_brief_schedule_v26")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE innovation_brief_runs DROP COLUMN scheduled_for"))
            await connection.execute(text("ALTER TABLE innovation_briefs DROP COLUMN published_at"))
            await connection.execute(text("ALTER TABLE brief_delivery_outbox DROP COLUMN scheduled_for"))

        await manager.upgrade_knowledge_schema_v25_to_v26()
        await manager.upgrade_knowledge_schema_v25_to_v26()

        async with scoped_engine.connect() as connection:
            columns = set(
                (
                    await connection.execute(
                        text(
                            "SELECT table_name || '.' || column_name "
                            "FROM information_schema.columns "
                            "WHERE table_schema = :schema AND table_name IN ("
                            "'innovation_brief_runs', 'innovation_briefs', 'brief_delivery_outbox')"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )
            indexes = set(
                (
                    await connection.execute(
                        text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema"),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert "innovation_brief_runs.scheduled_for" in columns
        assert "innovation_briefs.published_at" in columns
        assert "brief_delivery_outbox.scheduled_for" in columns
        assert "uq_innovation_brief_scheduled_run" in indexes
        assert "ix_innovation_brief_publish_due" in indexes
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_knowledge_v26_to_v27_adds_collection_artifact_category_idempotently() -> None:
    """历史成果导入表可幂等补齐分类字段、索引和外键。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_collection_category_v27")
    try:
        await manager.create_knowledge_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("ALTER TABLE collection_artifact_ingestions DROP COLUMN category_id"))

        await manager.upgrade_knowledge_schema_v26_to_v27()
        await manager.upgrade_knowledge_schema_v26_to_v27()

        async with scoped_engine.connect() as connection:
            column = (
                await connection.execute(
                    text(
                        "SELECT data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = :schema "
                        "AND table_name = 'collection_artifact_ingestions' "
                        "AND column_name = 'category_id'"
                    ),
                    {"schema": schema},
                )
            ).one()
            indexes = set(
                (
                    await connection.execute(
                        text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema"),
                        {"schema": schema},
                    )
                ).scalars()
            )
            constraints = set(
                (
                    await connection.execute(
                        text(
                            "SELECT constraint_name FROM information_schema.table_constraints "
                            "WHERE table_schema = :schema "
                            "AND table_name = 'collection_artifact_ingestions'"
                        ),
                        {"schema": schema},
                    )
                ).scalars()
            )

        assert tuple(column) == ("character varying", "YES")
        assert "ix_collection_artifact_ingestions_category_id" in indexes
        assert "fk_collection_artifact_ingestions_category" in constraints
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_unversioned_baseline_repairs_existing_legacy_task_table() -> None:
    """未版本化数据库的 create_all + ensure 路径必须补齐旧 tasks 表。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_task_baseline")

    try:
        await manager.create_business_tables()
        async with scoped_engine.begin() as connection:
            await connection.execute(text("DROP TABLE tasks"))
            await connection.execute(text(LEGACY_TASK_TABLE_SQL))
            await connection.execute(
                text(
                    "INSERT INTO tasks (id, name, type, status) "
                    "VALUES ('legacy-pending', 'legacy', 'knowledge_parse', 'pending')"
                )
            )

        await manager.ensure_business_schema()

        async with scoped_engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT status, error, handler_version, lease_expires_at FROM tasks WHERE id = 'legacy-pending'"
                    )
                )
            ).one()
        assert tuple(row) == ("pending", None, 0, None)
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)


async def test_schema_version_is_persisted_and_runtime_validation_fails_closed() -> None:
    """版本表缺失、错误和正确三种状态必须形成精确启动结论。"""
    schema, admin_engine, scoped_engine, manager = await _create_isolated_manager("pytest_schema_version")

    try:
        with pytest.raises(RuntimeError, match="business=missing"):
            await manager.require_current_schema()

        await manager.create_schema_version_table()
        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION + 1)
        with pytest.raises(RuntimeError, match=f"business={BUSINESS_SCHEMA_VERSION + 1}"):
            await manager.require_current_schema()

        await manager.record_schema_version("business", BUSINESS_SCHEMA_VERSION)
        with pytest.raises(RuntimeError, match="knowledge=missing"):
            await manager.require_current_schema()

        await manager.record_schema_version("knowledge", KNOWLEDGE_SCHEMA_VERSION)
        await manager.require_current_schema()
        assert await manager.get_schema_versions() == {
            "business": BUSINESS_SCHEMA_VERSION,
            "knowledge": KNOWLEDGE_SCHEMA_VERSION,
        }
    finally:
        await _drop_isolated_schema(schema, admin_engine, scoped_engine)
