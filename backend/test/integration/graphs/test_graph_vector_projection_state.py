from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select

from server.routers import graph_router
from platform_core.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.implementations.milvus import MilvusKB
from platform_core.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from platform_core.repositories.knowledge_graph_acceptance_repository import KnowledgeGraphAcceptanceRepository
from platform_core.repositories.knowledge_graph_evolution_repository import KnowledgeGraphEvolutionRepository
from platform_core.repositories.knowledge_graph_governance_repository import KnowledgeGraphGovernanceRepository
from platform_core.repositories.knowledge_graph_repository import KnowledgeGraphRepository
from platform_core.services.knowledge_graph_projection_rebuild_service import (
    KnowledgeGraphProjectionRebuildService,
)
from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.knowledge.training.pilot_requirements import (
    PILOT_GRAPH_QUOTAS,
    PILOT_QUOTAS,
)
from platform_core.services.knowledge_graph_acceptance_service import REQUIRED_ACCEPTANCE_CRITERIA
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.neo4j import get_shared_neo4j_connection, safe_neo4j_label
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityAlias,
    KnowledgeGraphEntityMention,
    KnowledgeGraphHypothesis,
    KnowledgeGraphProjectionOutbox,
    KnowledgeGraphReviewDecision,
    KnowledgeGraphRevision,
    KnowledgeGraphBuildRun,
    KnowledgeGraphBuildStageRun,
    KnowledgeGraphConflict,
    KnowledgeGraphEvaluationRun,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeGraphTrendSnapshot,
    KnowledgeDocumentVersion,
    KnowledgeSourceDocument,
)


@pytest_asyncio.fixture
async def pg_pool():
    # The integration schema fixture uses its own anyio loop. Recreate the
    # SQLAlchemy pool in this test loop before exercising repository leases.
    pg_manager._initialized = False
    pg_manager.async_engine = None
    pg_manager.AsyncSession = None
    pg_manager.initialize()
    await pg_manager.ensure_knowledge_schema()
    await pg_manager.upgrade_knowledge_schema_v7_to_v8()
    await pg_manager.upgrade_knowledge_schema_v8_to_v9()
    await pg_manager.upgrade_knowledge_schema_v9_to_v10()
    await pg_manager.upgrade_knowledge_schema_v10_to_v11()
    await pg_manager.upgrade_knowledge_schema_v11_to_v12()
    await pg_manager.upgrade_knowledge_schema_v12_to_v13()
    await pg_manager.upgrade_knowledge_schema_v13_to_v14()
    await pg_manager.upgrade_knowledge_schema_v14_to_v15()
    await pg_manager.upgrade_knowledge_schema_v15_to_v16()
    await pg_manager.upgrade_knowledge_schema_v16_to_v17()
    await pg_manager.upgrade_knowledge_schema_v24_to_v25()
    yield
    await pg_manager.async_engine.dispose()
    pg_manager._initialized = False
    pg_manager.async_engine = None
    pg_manager.AsyncSession = None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parser_lineage_and_block_structure_reach_postgres_chunk(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_block_{suffix}"
    file_id = f"file_{suffix}"
    markdown = "# 系统设计\n\n## 信号处理\n\n宽带射频收发器提升抗干扰能力。"
    paragraph_start = markdown.index("宽带射频")

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="block lineage", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="雷达系统.md"))

        chunks = chunk_markdown(
            markdown,
            file_id,
            "雷达系统.md",
            {
                "chunk_preset_id": "separator",
                "chunk_parser_config": {"delimiter": "\\n\\n"},
                "document_version": 3,
                "parser_name": "native_markdown",
                "parser_version": "platform-unified-parser-v2",
                "parser_source_metadata": {"file_extension": ".md"},
                "parser_blocks": [
                    {
                        "start_char": paragraph_start,
                        "end_char": len(markdown),
                        "page_number": 2,
                        "block_type": "paragraph",
                        "bbox": [12, 24, 480, 220],
                        "source_metadata": {"position_kind": "layout_block"},
                    }
                ],
            },
        )
        records = MilvusKB._build_chunk_pg_records(object(), kb_id, chunks)
        await KnowledgeChunkRepository().batch_upsert(records)

        persisted = await KnowledgeChunkRepository().list_by_file_id(file_id)
        assert persisted
        assert all(chunk.document_version == 3 for chunk in persisted)
        assert all(chunk.parser_name == "native_markdown" for chunk in persisted)
        assert all(chunk.parser_version == "platform-unified-parser-v2" for chunk in persisted)
        paragraph = next(chunk for chunk in persisted if chunk.content.startswith("宽带射频"))
        assert paragraph.page_number == 2
        assert paragraph.bbox == [12, 24, 480, 220]
        assert paragraph.source_metadata["source_block_indices"] == [0]
        assert paragraph.source_metadata["source_page_numbers"] == [2]
        assert all(chunk.source_metadata["file_extension"] == ".md" for chunk in persisted)
        assert all(chunk.source_metadata["source_file"] == "雷达系统.md" for chunk in persisted)
        assert any(chunk.heading_path == ["系统设计", "信号处理"] for chunk in persisted)
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vector_projection_claim_and_finalize_chunk(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_vector_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    entity_id = f"entity_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="vector projection", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="test.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="entity",
                    graph_structure_indexed=True,
                    graph_indexed=False,
                )
            )
            session.add(
                KnowledgeGraphEntity(
                    entity_id=entity_id,
                    kb_id=kb_id,
                    normalized_name="entity",
                    label="Entity",
                    name="entity",
                    vector_status="pending",
                )
            )
            await session.flush()
            session.add(
                KnowledgeGraphEntityMention(
                    entity_id=entity_id,
                    kb_id=kb_id,
                    file_id=file_id,
                    chunk_id=chunk_id,
                )
            )

        token, records = await repo.claim_vector_records(
            kb_id=kb_id,
            record_type="entity",
            limit=10,
            lease_seconds=300,
        )

        assert records == [{"id": entity_id, "content": "entity\n实体类型：Entity"}]
        await repo.mark_vector_records_indexed(
            record_type="entity",
            record_ids=[entity_id],
            lock_token=token,
        )
        assert await repo.finalize_graph_indexed_chunks(kb_id) == 1

        async with pg_manager.get_async_session_context() as session:
            chunk = await session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.chunk_id == chunk_id))
            entity = await session.scalar(
                select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.entity_id == entity_id)
            )
            assert chunk.graph_indexed is True
            assert entity.vector_status == "indexed"
            assert entity.vector_lock_token is None
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_vector_profile_uses_only_accepted_mentions_and_relations(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_entity_profile_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    triple_id = f"triple_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="entity profile", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="profile.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="宽带射频模块提升抗干扰能力",
                    graph_structure_indexed=True,
                    graph_indexed=False,
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=source_id,
                        kb_id=kb_id,
                        normalized_name="宽带射频收发器",
                        label="Component",
                        name="宽带射频收发器",
                        vector_status="pending",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="抗干扰能力",
                        label="Capability",
                        name="抗干扰能力",
                        vector_status="indexed",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id=source_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="宽带射频模块",
                        start_char=0,
                        end_char=6,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=target_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="抗干扰能力",
                        start_char=8,
                        end_char=13,
                        review_status="accepted",
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphEntityAlias(
                        entity_id=source_id,
                        alias="宽带射频模块",
                        normalized_alias="宽带射频模块",
                        language="zh",
                        source="extraction",
                    ),
                    KnowledgeGraphEntityAlias(
                        entity_id=source_id,
                        alias="未经审核的别名",
                        normalized_alias="未经审核的别名",
                        language="zh",
                        source="extraction",
                    ),
                    KnowledgeGraphEntityAlias(
                        entity_id=source_id,
                        alias="Wideband RF Transceiver",
                        normalized_alias="wideband rf transceiver",
                        language="en",
                        source="human_governance",
                    ),
                ]
            )
            session.add(
                KnowledgeGraphTriple(
                    triple_id=triple_id,
                    kb_id=kb_id,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type="ENABLES_CAPABILITY",
                    content="宽带射频收发器 → ENABLES_CAPABILITY → 抗干扰能力",
                    vector_status="indexed",
                )
            )
            await session.flush()
            relation_mention = KnowledgeGraphTripleMention(
                triple_id=triple_id,
                kb_id=kb_id,
                file_id=file_id,
                chunk_id=chunk_id,
                claim_level="Fact",
                review_status="accepted",
                evidence_quote="宽带射频模块通过频率捷变提升抗干扰能力",
            )
            session.add(relation_mention)
            await session.flush()
            relation_mention_id = relation_mention.id

        token, records = await repo.claim_vector_records(
            kb_id=kb_id,
            record_type="entity",
            limit=10,
            lease_seconds=300,
            include_evidence_rows=True,
        )

        assert [record["id"] for record in records] == [source_id]
        content = records[0]["content"]
        assert "实体类型：Component" in content
        assert "宽带射频模块" in content
        assert "Wideband RF Transceiver" in content
        assert "未经审核的别名" not in content
        assert "ENABLES_CAPABILITY → 抗干扰能力 [Capability]" in content
        evidence_rows = records[0]["evidence_rows"]
        assert any(item["evidence_id"].startswith("entity-mention:") for item in evidence_rows)
        assert {
            "evidence_id": f"relation-mention:{relation_mention_id}",
            "kind": "relation_evidence",
            "text": "宽带射频模块通过频率捷变提升抗干扰能力",
        } in evidence_rows

        assert await repo.mark_vector_records_indexed(
            record_type="entity",
            record_ids=[source_id],
            lock_token=token,
        ) == [source_id]
        assert await repo.finalize_graph_indexed_chunks(kb_id) == 1

        await KnowledgeGraphGovernanceRepository().decide(
            kb_id=kb_id,
            target_type="relation_mention",
            target_id=str(relation_mention_id),
            decision="rejected",
            reviewer_uid="reviewer",
            reason="关系证据不足",
        )
        async with pg_manager.get_async_session_context() as session:
            entities = list(
                (
                    await session.execute(
                        select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.entity_id.in_([source_id, target_id]))
                    )
                )
                .scalars()
                .all()
            )
            triple = await session.scalar(
                select(KnowledgeGraphTriple).where(KnowledgeGraphTriple.triple_id == triple_id)
            )
            chunk = await session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.chunk_id == chunk_id))
            assert {entity.vector_status for entity in entities} == {"pending"}
            assert triple.vector_status == "pending"
            assert chunk.graph_indexed is False

        vector_store = SimpleNamespace(
            upsert_graph_records=AsyncMock(return_value=None),
            delete_graph_records=AsyncMock(return_value=None),
        )
        graph_service = MilvusGraphService(graph_repo=repo, graph_vector_store=vector_store)
        graph_service.project_projection_payload = MagicMock()
        replay = await graph_service.replay_projection_outbox(kb_id, limit=10)

        assert replay == {"claimed": 1, "completed": 1, "failed": 0}
        entity_call = next(
            call for call in vector_store.upsert_graph_records.await_args_list if call.kwargs["record_type"] == "entity"
        )
        rebuilt_by_id = {record["id"]: record["content"] for record in entity_call.kwargs["records"]}
        assert "ENABLES_CAPABILITY" not in rebuilt_by_id[source_id]
        vector_store.delete_graph_records.assert_awaited_once_with(
            kb_id,
            entity_ids=[],
            triple_ids=[triple_id],
        )
        async with pg_manager.get_async_session_context() as session:
            entities = list(
                (
                    await session.execute(
                        select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.entity_id.in_([source_id, target_id]))
                    )
                )
                .scalars()
                .all()
            )
            chunk = await session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.chunk_id == chunk_id))
            assert {entity.vector_status for entity in entities} == {"indexed"}
            assert chunk.graph_indexed is True
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inactive_relation_cannot_be_requeued_or_block_chunk_finalization(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_relation_vector_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    active_triple_id = f"active_{suffix}"
    invalid_triple_id = f"invalid_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="relation vector lifecycle", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="test.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="source enables target",
                    graph_structure_indexed=True,
                    graph_indexed=False,
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=source_id,
                        kb_id=kb_id,
                        normalized_name="source",
                        label="KeyTechnology",
                        name="source",
                        vector_status="indexed",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="target",
                        label="Capability",
                        name="target",
                        vector_status="indexed",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphTriple(
                        triple_id=active_triple_id,
                        kb_id=kb_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relation_type="ENABLES_CAPABILITY",
                        content="source enables target",
                        lifecycle_status="active",
                        vector_status="indexed",
                    ),
                    KnowledgeGraphTriple(
                        triple_id=invalid_triple_id,
                        kb_id=kb_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relation_type="POTENTIAL_FOR",
                        content="invalid relation",
                        lifecycle_status="invalid",
                        valid_to=datetime.now(UTC),
                        relation_version=2,
                        vector_status="disabled",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphTripleMention(
                        triple_id=active_triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        claim_level="Fact",
                        review_status="accepted",
                    ),
                    KnowledgeGraphTripleMention(
                        triple_id=invalid_triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                    ),
                ]
            )

        await repo.reconcile_vector_records(kb_id, all_vectors=True)
        token, records = await repo.claim_vector_records(
            kb_id=kb_id,
            record_type="triple",
            limit=10,
            lease_seconds=300,
        )

        assert [record["id"] for record in records] == [active_triple_id]
        assert await repo.mark_vector_records_indexed(
            record_type="triple",
            record_ids=[active_triple_id],
            lock_token=token,
        ) == [active_triple_id]
        assert await repo.finalize_graph_indexed_chunks(kb_id) == 1

        async with pg_manager.get_async_session_context() as session:
            invalid_triple = await session.scalar(
                select(KnowledgeGraphTriple).where(KnowledgeGraphTriple.triple_id == invalid_triple_id)
            )
            chunk = await session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.chunk_id == chunk_id))
            assert invalid_triple.vector_status == "disabled"
            assert invalid_triple.vector_lock_token is None
            assert chunk.graph_indexed is True
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redirected_entity_cannot_be_requeued_or_block_chunk_finalization(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_entity_vector_lifecycle_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    active_entity_id = f"active_{suffix}"
    redirected_entity_id = f"redirected_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="entity vector lifecycle", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="test.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="定向能技术",
                    graph_structure_indexed=True,
                    graph_indexed=False,
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=active_entity_id,
                        kb_id=kb_id,
                        normalized_name="定向能",
                        label="KeyTechnology",
                        name="定向能",
                        lifecycle_status="active",
                        vector_status="indexed",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=redirected_entity_id,
                        kb_id=kb_id,
                        normalized_name="定向能",
                        label="Capability",
                        name="定向能",
                        lifecycle_status="redirected",
                        superseded_by_entity_id=active_entity_id,
                        vector_status="indexed",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id=active_entity_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="定向能",
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=redirected_entity_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="定向能",
                        review_status="accepted",
                    ),
                ]
            )

        anchors = await repo.list_accepted_entity_ids_by_chunk_ids(
            kb_id=kb_id,
            chunk_ids=[chunk_id],
        )
        assert anchors == {chunk_id: [active_entity_id]}

        await repo.reconcile_vector_records(kb_id, all_vectors=True)
        token, records = await repo.claim_vector_records(
            kb_id=kb_id,
            record_type="entity",
            limit=10,
            lease_seconds=300,
        )

        assert [record["id"] for record in records] == [active_entity_id]
        assert await repo.mark_vector_records_indexed(
            record_type="entity",
            record_ids=[active_entity_id],
            lock_token=token,
        ) == [active_entity_id]
        assert await repo.finalize_graph_indexed_chunks(kb_id) == 1

        async with pg_manager.get_async_session_context() as session:
            redirected = await session.scalar(
                select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.entity_id == redirected_entity_id)
            )
            chunk = await session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.chunk_id == chunk_id))
            assert redirected.vector_status == "disabled"
            assert redirected.vector_lock_token is None
            assert chunk.graph_indexed is True
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mix_chunk_anchors_return_only_accepted_entity_mentions(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_mix_chunk_{suffix}"
    file_id = f"file_{suffix}"
    accepted_chunk_id = f"chunk_accepted_{suffix}"
    pending_chunk_id = f"chunk_pending_{suffix}"
    accepted_entity_id = f"accepted_{suffix}"
    pending_entity_id = f"pending_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="mix chunk anchors", kb_type="milvus"))
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="mix.md"))
            await session.flush()
            session.add_all(
                [
                    KnowledgeChunk(
                        chunk_id=accepted_chunk_id,
                        file_id=file_id,
                        kb_id=kb_id,
                        chunk_index=0,
                        content="频率捷变提高抗干扰能力。",
                    ),
                    KnowledgeChunk(
                        chunk_id=pending_chunk_id,
                        file_id=file_id,
                        kb_id=kb_id,
                        chunk_index=1,
                        content="未经审核的候选实体。",
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=accepted_entity_id,
                        kb_id=kb_id,
                        normalized_name="频率捷变",
                        label="KeyTechnology",
                        name="频率捷变",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=pending_entity_id,
                        kb_id=kb_id,
                        normalized_name="候选实体",
                        label="KeyTechnology",
                        name="候选实体",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id=accepted_entity_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=accepted_chunk_id,
                        mention_text="频率捷变",
                        start_char=0,
                        end_char=4,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=pending_entity_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=pending_chunk_id,
                        mention_text="候选实体",
                        start_char=6,
                        end_char=10,
                        review_status="pending",
                    ),
                ]
            )

        result = await repo.list_accepted_entity_ids_by_chunk_ids(
            kb_id=kb_id,
            chunk_ids=[accepted_chunk_id, pending_chunk_id],
        )
        preview_result = await repo.list_entity_ids_by_chunk_ids(
            kb_id=kb_id,
            chunk_ids=[accepted_chunk_id, pending_chunk_id],
            review_statuses=("accepted", "pending"),
        )

        assert result == {
            accepted_chunk_id: [accepted_entity_id],
            pending_chunk_id: [],
        }
        assert preview_result == {
            accepted_chunk_id: [accepted_entity_id],
            pending_chunk_id: [pending_entity_id],
        }
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_triple_vector_profile_aggregates_accepted_and_pending_cross_document_evidence(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_relation_profile_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    triple_id = f"triple_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="relation profile", kb_type="milvus"))
            session.add_all(
                [
                    KnowledgeFile(file_id=f"file_a_{suffix}", kb_id=kb_id, filename="a.md"),
                    KnowledgeFile(file_id=f"file_b_{suffix}", kb_id=kb_id, filename="b.md"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeChunk(
                        chunk_id=f"chunk_a_{suffix}",
                        file_id=f"file_a_{suffix}",
                        kb_id=kb_id,
                        chunk_index=0,
                        content="频率捷变提高抗干扰能力。",
                    ),
                    KnowledgeChunk(
                        chunk_id=f"chunk_b_{suffix}",
                        file_id=f"file_b_{suffix}",
                        kb_id=kb_id,
                        chunk_index=0,
                        content="多通道接收降低压制式干扰影响。",
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=source_id,
                        kb_id=kb_id,
                        normalized_name="宽带射频收发器",
                        label="Component",
                        name="宽带射频收发器",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="抗干扰能力",
                        label="Capability",
                        name="抗干扰能力",
                    ),
                ]
            )
            await session.flush()
            session.add(
                KnowledgeGraphTriple(
                    triple_id=triple_id,
                    kb_id=kb_id,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type="ENABLES_CAPABILITY",
                    content="宽带射频收发器 → ENABLES_CAPABILITY → 抗干扰能力",
                    vector_status="pending",
                )
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphTripleMention(
                        triple_id=triple_id,
                        kb_id=kb_id,
                        file_id=f"file_a_{suffix}",
                        chunk_id=f"chunk_a_{suffix}",
                        claim_level="Fact",
                        review_status="accepted",
                        evidence_quote="频率捷变提高抗干扰能力。",
                        applicable_conditions=["宽带工作模式"],
                    ),
                    KnowledgeGraphTripleMention(
                        triple_id=triple_id,
                        kb_id=kb_id,
                        file_id=f"file_b_{suffix}",
                        chunk_id=f"chunk_b_{suffix}",
                        claim_level="Inference",
                        review_status="pending",
                        evidence_quote="多通道接收降低压制式干扰影响。",
                        applicable_conditions=["多通道接收"],
                    ),
                ]
            )

        token, records = await repo.claim_vector_records(
            kb_id=kb_id,
            record_type="triple",
            limit=10,
            lease_seconds=300,
            include_evidence_rows=True,
        )

        assert token
        assert [record["id"] for record in records] == [triple_id]
        content = records[0]["content"]
        assert "源实体：宽带射频收发器 [Component]" in content
        assert "目标实体：抗干扰能力 [Capability]" in content
        assert "独立来源数：2" in content
        assert "知识层级：Fact、Inference" in content
        assert "证据状态：accepted、pending" in content
        assert "频率捷变提高抗干扰能力。" in content
        assert "多通道接收降低压制式干扰影响。" in content
        assert {item["text"] for item in records[0]["evidence_rows"]} == {
            "频率捷变提高抗干扰能力。",
            "多通道接收降低压制式干扰影响。",
        }
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authoritative_projection_rebuild_uses_real_postgres_neo4j_and_milvus(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_projection_rebuild_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    target_chunk_id = f"target_chunk_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    triple_id = f"triple_{suffix}"
    label = safe_neo4j_label(kb_id)
    connection = get_shared_neo4j_connection()
    graph_service = MilvusGraphService(neo4j_connection=connection)

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(
                KnowledgeBase(
                    kb_id=kb_id,
                    name="projection rebuild",
                    kb_type="milvus",
                    embedding_model_spec="local-embedding:BAAI/bge-m3",
                )
            )
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="test.md"))
            await session.flush()
            session.add_all(
                [
                    KnowledgeChunk(
                        chunk_id=chunk_id,
                        file_id=file_id,
                        kb_id=kb_id,
                        chunk_index=0,
                        content="相控阵雷达用于系统前端",
                        document_version=1,
                        page_number=1,
                        graph_structure_indexed=True,
                        graph_indexed=True,
                    ),
                    KnowledgeChunk(
                        chunk_id=target_chunk_id,
                        file_id=file_id,
                        kb_id=kb_id,
                        chunk_index=1,
                        content="跨段证据表明探测能力得到提升",
                        document_version=1,
                        page_number=2,
                        graph_structure_indexed=True,
                        graph_indexed=True,
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=source_id,
                        kb_id=kb_id,
                        normalized_name="相控阵雷达",
                        label="KeyTechnology",
                        name="相控阵雷达",
                        vector_status="indexed",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="探测能力",
                        label="Capability",
                        name="探测能力",
                        vector_status="indexed",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id=source_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="相控阵雷达",
                        start_char=0,
                        end_char=5,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=target_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=target_chunk_id,
                        mention_text="探测能力",
                        start_char=6,
                        end_char=10,
                        review_status="accepted",
                    ),
                ]
            )
            session.add(
                KnowledgeGraphTriple(
                    triple_id=triple_id,
                    kb_id=kb_id,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type="ENABLES_CAPABILITY",
                    content="相控阵雷达提升探测能力",
                    lifecycle_status="active",
                    vector_status="indexed",
                )
            )
            await session.flush()
            session.add(
                KnowledgeGraphTripleMention(
                    triple_id=triple_id,
                    kb_id=kb_id,
                    file_id=file_id,
                    chunk_id=chunk_id,
                    text="提升",
                    extractor_type="lightrag",
                    claim_level="Fact",
                    confidence=0.92,
                    evidence_quote="相控阵雷达提升探测能力",
                    evidence_spans=[{"start": 0, "end": 11}],
                    applicable_conditions=["远场条件"],
                    expert_review_required=False,
                    review_status="accepted",
                    pipeline_revision="hybrid-v2-r1",
                )
            )

        result = await KnowledgeGraphProjectionRebuildService(graph_service=graph_service).rebuild(kb_id=kb_id)

        assert result["projected_chunks"] == 2
        assert result["projected_entity_mentions"] == 2
        assert result["projected_relation_mentions"] == 1
        with connection.driver.session() as session:
            record = session.run(
                f"""
                MATCH (source:Entity:MilvusKB:`{label}` {{entity_id: $source_id}})
                      -[relation:RELATION {{triple_id: $triple_id}}]->
                      (target:Entity:MilvusKB:`{label}` {{entity_id: $target_id}})
                RETURN source.lifecycle_status AS source_lifecycle,
                       relation.review_status AS review_status,
                       relation.lifecycle_status AS relation_lifecycle,
                       relation.applicable_conditions AS conditions,
                       target.name AS target_name
                """,
                source_id=source_id,
                target_id=target_id,
                triple_id=triple_id,
            ).single()
            source_mention_count = session.run(
                f"""
                MATCH (:Chunk:MilvusKB:`{label}` {{chunk_id: $chunk_id}})
                      -[mention:MENTIONS]->
                      (:Entity:MilvusKB:`{label}` {{entity_id: $entity_id}})
                RETURN count(mention) AS count
                """,
                chunk_id=chunk_id,
                entity_id=source_id,
            ).single()["count"]
            fabricated_target_mention_count = session.run(
                f"""
                MATCH (:Chunk:MilvusKB:`{label}` {{chunk_id: $chunk_id}})
                      -[mention:MENTIONS]->
                      (:Entity:MilvusKB:`{label}` {{entity_id: $entity_id}})
                RETURN count(mention) AS count
                """,
                chunk_id=chunk_id,
                entity_id=target_id,
            ).single()["count"]
            real_target_mention_count = session.run(
                f"""
                MATCH (:Chunk:MilvusKB:`{label}` {{chunk_id: $chunk_id}})
                      -[mention:MENTIONS]->
                      (:Entity:MilvusKB:`{label}` {{entity_id: $entity_id}})
                RETURN count(mention) AS count
                """,
                chunk_id=target_chunk_id,
                entity_id=target_id,
            ).single()["count"]
        assert record is not None
        assert record["source_lifecycle"] == "active"
        assert record["review_status"] == "accepted"
        assert record["relation_lifecycle"] == "active"
        assert record["conditions"] == ["远场条件"]
        assert record["target_name"] == "探测能力"
        assert source_mention_count == 1
        assert fabricated_target_mention_count == 0
        assert real_target_mention_count == 1

        async with pg_manager.get_async_session_context() as session:
            triple = await session.scalar(
                select(KnowledgeGraphTriple).where(KnowledgeGraphTriple.triple_id == triple_id)
            )
            entities = list(
                (
                    await session.scalars(
                        select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.kb_id == kb_id)
                    )
                ).all()
            )
            assert triple.vector_status == "indexed"
            assert {entity.vector_status for entity in entities} == {"indexed"}
    finally:
        with connection.driver.session() as session:
            session.run(f"MATCH (n:MilvusKB:`{label}`) DETACH DELETE n").consume()
        graph_vector_store = await graph_service.get_graph_vector_store()
        await asyncio.to_thread(graph_vector_store.drop_graph_collections, kb_id)
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chunk_extraction_details_return_recent_failure_samples(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_extraction_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    recent_chunk_id = f"recent_chunk_{suffix}"
    repo = KnowledgeChunkRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="extraction details", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="test.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="failed extraction sample",
                )
            )
            session.add(
                KnowledgeChunk(
                    chunk_id=recent_chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=1,
                    content="recent failed extraction sample",
                )
            )

        await repo.mark_graph_extraction_failed(chunk_id, 3, "model timeout")
        await repo.mark_graph_extraction_failed(recent_chunk_id, 1, "invalid response")

        counts = await repo.count_graph_extraction_statuses_by_kb_id(kb_id)
        samples = await repo.list_graph_extraction_failed_samples(kb_id, limit=10)
        assert counts == {"pending": 0, "succeeded": 0, "failed": 2}
        assert [sample["chunk_id"] for sample in samples] == [recent_chunk_id, chunk_id]
        assert samples[1]["file_id"] == file_id
        assert samples[1]["content"] == "failed extraction sample"
        assert samples[1]["details"]["status"] == "failed"
        assert samples[1]["details"]["attempt_count"] == 3
        assert samples[1]["details"]["last_error"] == "model timeout"
        assert samples[1]["details"]["last_attempt_at"]

        await repo.mark_graph_extraction_pending(chunk_id)
        cache_manifest = {
            "schema_version": 1,
            "document": {"content_hash": "source-hash", "document_version": 1},
            "parser": {"name": "paddlex", "version": "3.1"},
            "model_versions": {"lightrag_primary": "lightrag.5-multi-v1"},
        }
        await repo.update_extraction_result(
            chunk_id,
            {
                "entities": [],
                "relations": [],
                "metadata": {
                    "extractor_type": "lightrag_primary",
                    "extraction_cache": {
                        "schema_version": 1,
                        "key": "a" * 64,
                        "manifest": cache_manifest,
                    },
                },
            },
            2,
        )
        await repo.mark_graph_extraction_pending(recent_chunk_id)
        await repo.update_extraction_result(
            recent_chunk_id,
            {"entities": [], "relations": [], "metadata": {"extractor_type": "llm"}},
            1,
        )

        counts = await repo.count_graph_extraction_statuses_by_kb_id(kb_id)
        assert counts == {"pending": 0, "succeeded": 2, "failed": 0}
        assert await repo.list_graph_extraction_failed_samples(kb_id) == []
        persisted_chunk = await repo.get_by_chunk_id(chunk_id)
        assert persisted_chunk.graph_extraction_details["cache_key"] == "a" * 64
        assert persisted_chunk.graph_extraction_details["cache_manifest"] == cache_manifest
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_upsert_persists_span_evidence_and_review_state(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_evidence_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    triple_id = f"triple_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="evidence", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="evidence.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达提升探测能力",
                )
            )

        entities = [
            {
                "entity_id": source_id,
                "kb_id": kb_id,
                "normalized_name": "相控阵雷达",
                "label": "KeyTechnology",
                "name": "相控阵雷达",
                "attributes": [],
                "mention_text": "相控阵雷达",
                "start_char": 0,
                "end_char": 5,
                "confidence": 0.93,
                "model_version": "fastino/lightrag.5-multi-v1",
                "ontology_version": "defense-kg-1.0",
                "review_status": "pending",
            },
            {
                "entity_id": target_id,
                "kb_id": kb_id,
                "normalized_name": "探测能力",
                "label": "Capability",
                "name": "探测能力",
                "attributes": [],
                "mention_text": "探测能力",
                "start_char": 7,
                "end_char": 11,
                "confidence": 0.9,
                "model_version": "fastino/lightrag.5-multi-v1",
                "ontology_version": "defense-kg-1.0",
                "review_status": "pending",
            },
        ]
        triples = [
            {
                "triple_id": triple_id,
                "kb_id": kb_id,
                "source_entity_id": source_id,
                "target_entity_id": target_id,
                "relation_type": "ENABLES_CAPABILITY",
                "content": "相控阵雷达 → ENABLES_CAPABILITY → 探测能力",
                "text": "相控阵雷达提升探测能力",
                "extractor_type": "lightrag_primary",
                "claim_level": "Fact",
                "confidence": 0.86,
                "evidence_quote": "相控阵雷达提升探测能力",
                "evidence_spans": [{"start": 0, "end": 11}],
                "reasoning_basis": "",
                "applicable_conditions": ["目标处于远场且阵列完成相位校准"],
                "secondary_review": {
                    "revision": "defense-lightrag-relation-review-v1",
                    "reviewer": "lightrag",
                    "verdict": "supported",
                    "basis": "exact_relation_match",
                    "primary_supported": True,
                    "secondary_supported": True,
                    "negative_evidence_available": False,
                    "label_quality": "weak_supervision",
                    "review_only": True,
                },
                "uncertainty": "",
                "expert_review_required": False,
                "review_status": "pending",
                "model_version": "fastino/lightrag.5-multi-v1",
                "ontology_version": "defense-kg-1.0",
                "pipeline_revision": "hybrid-v2-r1",
            }
        ]

        await repo.upsert_chunk_graph(
            kb_id=kb_id,
            file_id=file_id,
            chunk_id=chunk_id,
            entities=entities,
            triples=triples,
        )
        triples[0]["confidence"] = 0.91
        triples[0]["review_status"] = "accepted"
        await repo.upsert_chunk_graph(
            kb_id=kb_id,
            file_id=file_id,
            chunk_id=chunk_id,
            entities=entities,
            triples=triples,
        )

        async with pg_manager.get_async_session_context() as session:
            entity_mention = await session.scalar(
                select(KnowledgeGraphEntityMention).where(
                    KnowledgeGraphEntityMention.entity_id == source_id,
                    KnowledgeGraphEntityMention.chunk_id == chunk_id,
                )
            )
            triple_mention = await session.scalar(
                select(KnowledgeGraphTripleMention).where(
                    KnowledgeGraphTripleMention.triple_id == triple_id,
                    KnowledgeGraphTripleMention.chunk_id == chunk_id,
                )
            )
            assert (entity_mention.start_char, entity_mention.end_char) == (0, 5)
            assert entity_mention.ontology_version == "defense-kg-1.0"
            assert triple_mention.evidence_spans == [{"start": 0, "end": 11}]
            assert triple_mention.evidence_quote == "相控阵雷达提升探测能力"
            assert triple_mention.applicable_conditions == ["目标处于远场且阵列完成相位校准"]
            assert triple_mention.secondary_review["verdict"] == "supported"
            assert triple_mention.secondary_review["negative_evidence_available"] is False
            assert triple_mention.confidence == 0.91
            assert triple_mention.review_status == "accepted"
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_upsert_preserves_distinct_mentions_for_same_entity_and_chunk(pg_pool):
    """同一实体在同一 Block 的不同 Span 分别保存，相同 Span 幂等更新。"""
    suffix = uuid4().hex
    kb_id = f"pytest_multi_mention_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    entity_id = f"entity_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="multi mention", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="mentions.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达通过波束赋形提升相控阵雷达探测能力",
                )
            )

        base_entity = {
            "entity_id": entity_id,
            "kb_id": kb_id,
            "normalized_name": "相控阵雷达",
            "label": "KeyTechnology",
            "name": "相控阵雷达",
            "attributes": [],
            "mention_text": "相控阵雷达",
            "model_version": "fastino/lightrag.5-multi-v1",
            "ontology_version": "defense-kg-1.0",
            "review_status": "pending",
        }
        await repo.upsert_chunk_graph(
            kb_id=kb_id,
            file_id=file_id,
            chunk_id=chunk_id,
            entities=[
                {**base_entity, "start_char": 0, "end_char": 5, "confidence": 0.91},
                {**base_entity, "start_char": 13, "end_char": 18, "confidence": 0.87},
            ],
            triples=[],
        )
        await repo.upsert_chunk_graph(
            kb_id=kb_id,
            file_id=file_id,
            chunk_id=chunk_id,
            entities=[
                {
                    **base_entity,
                    "start_char": 13,
                    "end_char": 18,
                    "confidence": 0.96,
                    "review_status": "accepted",
                }
            ],
            triples=[],
        )

        async with pg_manager.get_async_session_context() as session:
            mentions = list(
                (
                    await session.scalars(
                        select(KnowledgeGraphEntityMention)
                        .where(
                            KnowledgeGraphEntityMention.entity_id == entity_id,
                            KnowledgeGraphEntityMention.chunk_id == chunk_id,
                        )
                        .order_by(KnowledgeGraphEntityMention.start_char)
                    )
                ).all()
            )

        assert [(mention.start_char, mention.end_char) for mention in mentions] == [(0, 5), (13, 18)]
        assert mentions[0].confidence == 0.91
        assert mentions[1].confidence == 0.96
        assert mentions[1].review_status == "accepted"
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_upsert_atomically_enqueues_claimable_projection(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_outbox_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    entity_id = f"entity_{suffix}"
    revision_id = f"revision_{suffix}"
    event_id = f"event_{suffix}"
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="projection outbox", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="outbox.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达",
                )
            )

        await repo.upsert_chunk_graph(
            kb_id=kb_id,
            file_id=file_id,
            chunk_id=chunk_id,
            entities=[
                {
                    "entity_id": entity_id,
                    "kb_id": kb_id,
                    "normalized_name": "相控阵雷达",
                    "label": "KeyTechnology",
                    "name": "相控阵雷达",
                    "attributes": [],
                }
            ],
            triples=[],
            projection_event={
                "event_id": event_id,
                "graph_revision": revision_id,
                "ontology_version": "defense-kg-1.0",
                "summary": {"entity_count": 1},
                "payload": {"version": 1, "chunk_id": chunk_id},
            },
        )

        async with pg_manager.get_async_session_context() as session:
            assert await session.get(KnowledgeGraphRevision, revision_id) is not None
            outbox = await session.get(KnowledgeGraphProjectionOutbox, event_id)
            assert outbox is not None
            assert outbox.status == "pending"

        token, events = await repo.claim_projection_events(kb_id=kb_id, limit=10, lease_seconds=300)
        assert events == [
            {
                "event_id": event_id,
                "kb_id": kb_id,
                "graph_revision": revision_id,
                "payload": {"version": 1, "chunk_id": chunk_id},
            }
        ]
        assert await repo.mark_projection_event_completed(event_id=event_id, lock_token=token) is True
        assert await repo.count_projection_statuses(kb_id) == {
            "pending": 0,
            "processing": 0,
            "completed": 1,
            "failed": 0,
        }
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_alignment_reuses_stable_id_through_alias(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_alias_{suffix}"
    stable_id = str(uuid4())
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="entity alias", kb_type="milvus"))
            session.add(
                KnowledgeGraphEntity(
                    entity_id=stable_id,
                    kb_id=kb_id,
                    normalized_name="相控阵雷达",
                    label="KeyTechnology",
                    name="相控阵雷达",
                )
            )
            await session.flush()
            session.add(
                KnowledgeGraphEntityAlias(
                    entity_id=stable_id,
                    alias="phased array radar",
                    normalized_alias="phased array radar",
                    language="en",
                    source="review",
                )
            )

        entities = [
            {
                "entity_id": str(uuid4()),
                "kb_id": kb_id,
                "normalized_name": "phased array radar",
                "label": "KeyTechnology",
                "name": "Phased Array Radar",
            }
        ]
        result = await repo.align_graph_records(kb_id=kb_id, entities=entities, triples=[])

        assert entities[0]["entity_id"] == stable_id
        assert result == {"unresolved_entity_ids": [], "ambiguous_candidates": {}}
        profiles = await repo.load_entity_alignment_profiles(kb_id=kb_id, entity_ids=[stable_id])
        assert profiles[stable_id]["label"] == "KeyTechnology"
        assert profiles[stable_id]["aliases"] == ["phased array radar"]
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_alignment_profile_neighbors_only_use_accepted_active_facts(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_alignment_neighbors_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    target_id = str(uuid4())
    accepted_neighbor_id = str(uuid4())
    pending_neighbor_id = str(uuid4())
    repo = KnowledgeGraphRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="alignment neighbors", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="alignment.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达形成探测能力，待审核关系不得参与实体消歧。",
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="相控阵雷达",
                        label="KeyTechnology",
                        name="相控阵雷达",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=accepted_neighbor_id,
                        kb_id=kb_id,
                        normalized_name="探测能力",
                        label="Capability",
                        name="探测能力",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=pending_neighbor_id,
                        kb_id=kb_id,
                        normalized_name="虚假邻域",
                        label="Capability",
                        name="虚假邻域",
                    ),
                ]
            )
            await session.flush()
            accepted_triple_id = str(uuid4())
            pending_triple_id = str(uuid4())
            session.add_all(
                [
                    KnowledgeGraphTriple(
                        triple_id=accepted_triple_id,
                        kb_id=kb_id,
                        source_entity_id=target_id,
                        target_entity_id=accepted_neighbor_id,
                        relation_type="ENABLES_CAPABILITY",
                        content="相控阵雷达形成探测能力",
                    ),
                    KnowledgeGraphTriple(
                        triple_id=pending_triple_id,
                        kb_id=kb_id,
                        source_entity_id=target_id,
                        target_entity_id=pending_neighbor_id,
                        relation_type="ENABLES_CAPABILITY",
                        content="待审核关系",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphTripleMention(
                        triple_id=accepted_triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        claim_level="Fact",
                        review_status="accepted",
                    ),
                    KnowledgeGraphTripleMention(
                        triple_id=pending_triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        claim_level="Fact",
                        review_status="pending",
                    ),
                ]
            )

        profiles = await repo.load_entity_alignment_profiles(kb_id=kb_id, entity_ids=[target_id])

        assert profiles[target_id]["neighbors"] == ["探测能力 [Capability]"]
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_random_entity_uuid_allocation_converges_under_concurrency(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_uuid_{suffix}"
    repo = KnowledgeGraphRepository()
    first = {
        "entity_id": str(uuid4()),
        "kb_id": kb_id,
        "normalized_name": "宽带射频收发器",
        "label": "Component",
        "name": "宽带射频收发器",
        "attributes": {},
    }
    second = {**first, "entity_id": str(uuid4())}

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="random uuid", kb_type="milvus"))

        await asyncio.gather(
            repo.allocate_entity_ids(
                kb_id=kb_id,
                entities=[first],
                triples=[],
                provisional_entity_ids={first["entity_id"]},
            ),
            repo.allocate_entity_ids(
                kb_id=kb_id,
                entities=[second],
                triples=[],
                provisional_entity_ids={second["entity_id"]},
            ),
        )

        assert first["entity_id"] == second["entity_id"]
        assert UUID(first["entity_id"]).version == 4
        async with pg_manager.get_async_session_context() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeGraphEntity)
                .where(
                    KnowledgeGraphEntity.kb_id == kb_id,
                    KnowledgeGraphEntity.normalized_name == "宽带射频收发器",
                    KnowledgeGraphEntity.label == "Component",
                )
            )
            assert count == 1
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ontology_registration_and_review_decision_are_auditable(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_review_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    entity_id = str(uuid4())
    repository = KnowledgeGraphGovernanceRepository()

    try:
        definition = ontology_payload()
        assert await repository.register_ontology(definition, created_by="reviewer") == "defense-kg-1.0"
        assert await repository.register_ontology(definition, created_by="reviewer") == "defense-kg-1.0"

        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="review", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="review.md"))
        await KnowledgeChunkRepository().batch_upsert(
            [
                {
                    "chunk_id": chunk_id,
                    "file_id": file_id,
                    "kb_id": kb_id,
                    "chunk_index": 0,
                    "content": "相控阵雷达提升探测能力",
                    "start_char_pos": 1200,
                    "end_char_pos": 1211,
                    "document_version": 2,
                    "page_number": 5,
                    "block_type": "paragraph",
                    "heading_path": ["3 系统设计", "3.2 信号处理"],
                    "bbox": [10.0, 20.0, 500.0, 220.0],
                    "parser_name": "paddlex",
                    "parser_version": "3.0",
                    "source_metadata": {"layout_score": 0.98},
                }
            ]
        )
        async with pg_manager.get_async_session_context() as session:
            session.add(
                KnowledgeGraphEntity(
                    entity_id=entity_id,
                    kb_id=kb_id,
                    normalized_name="相控阵雷达",
                    label="KeyTechnology",
                    name="相控阵雷达",
                    vector_status="indexed",
                )
            )
            await session.flush()
            mention = KnowledgeGraphEntityMention(
                entity_id=entity_id,
                kb_id=kb_id,
                file_id=file_id,
                chunk_id=chunk_id,
                mention_text="相控阵雷达",
                start_char=0,
                end_char=5,
                confidence=0.92,
                review_status="pending",
            )
            session.add(mention)
            await session.flush()
            mention_id = mention.id

        queue = await repository.list_review_queue(kb_id=kb_id)
        assert queue[0]["target_id"] == str(mention_id)
        assert queue[0]["evidence_spans"] == [{"start": 0, "end": 5}]
        assert queue[0]["evidence_location"] == {
            "document_version": 2,
            "page": 5,
            "block_type": "paragraph",
            "heading_path": ["3 系统设计", "3.2 信号处理"],
            "bbox": [10.0, 20.0, 500.0, 220.0],
            "start_char": 1200,
            "end_char": 1211,
            "parser": "paddlex",
            "parser_version": "3.0",
        }

        disputed = await repository.decide(
            kb_id=kb_id,
            target_type="entity_mention",
            target_id=str(mention_id),
            decision="disputed",
            reviewer_uid="reviewer",
            reason="需要核对同名雷达型号",
        )
        disputed_again = await repository.decide(
            kb_id=kb_id,
            target_type="entity_mention",
            target_id=str(mention_id),
            decision="disputed",
            reviewer_uid="reviewer",
            reason="需要核对同名雷达型号",
        )
        assert disputed["conflict_id"] == disputed_again["conflict_id"]
        open_conflicts = await repository.list_conflicts(kb_id=kb_id)
        assert [item["conflict_id"] for item in open_conflicts] == [disputed["conflict_id"]]

        result = await repository.decide(
            kb_id=kb_id,
            target_type="entity_mention",
            target_id=str(mention_id),
            decision="accepted",
            reviewer_uid="reviewer",
            reason="原文证据可定位",
        )
        assert result["review_status"] == "accepted"

        async with pg_manager.get_async_session_context() as session:
            decision = await session.get(KnowledgeGraphReviewDecision, result["decision_id"])
            conflict = await session.get(KnowledgeGraphConflict, disputed["conflict_id"])
            reviewed = await session.get(KnowledgeGraphEntityMention, mention_id)
            reviewed_entity = await session.scalar(
                select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.entity_id == entity_id)
            )
            projection = await session.get(
                KnowledgeGraphProjectionOutbox,
                result["projection_event_id"],
            )
            assert decision.reason == "原文证据可定位"
            assert conflict.status == "resolved"
            assert conflict.resolved_by == "reviewer"
            assert reviewed.review_status == "accepted"
            assert reviewed_entity.vector_status == "pending"
            assert reviewed_entity.vector_lock_token is None
            assert projection.status == "pending"
            assert projection.payload["event_type"] == "review_status"
            assert projection.payload["entity_id"] == entity_id
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_governance_http_round_trip_uses_real_postgres(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_review_http_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    entity_id = str(uuid4())
    reviewer = SimpleNamespace(uid="reviewer")
    app = FastAPI()
    app.include_router(graph_router.graph)
    app.dependency_overrides[graph_router.get_admin_user] = lambda: reviewer
    app.dependency_overrides[graph_router.require_knowledge_base_read] = lambda: reviewer
    app.dependency_overrides[graph_router.require_knowledge_base_manage] = lambda: reviewer

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="review http", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id=file_id, kb_id=kb_id, filename="review.md"))
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达提升探测能力",
                )
            )
            session.add(
                KnowledgeGraphEntity(
                    entity_id=entity_id,
                    kb_id=kb_id,
                    normalized_name="相控阵雷达",
                    label="KeyTechnology",
                    name="相控阵雷达",
                )
            )
            await session.flush()
            mention = KnowledgeGraphEntityMention(
                entity_id=entity_id,
                kb_id=kb_id,
                file_id=file_id,
                chunk_id=chunk_id,
                mention_text="相控阵雷达",
                start_char=0,
                end_char=5,
                confidence=0.93,
                model_version="fastino/lightrag.5-multi-v1",
                ontology_version="defense-kg-1.0",
                review_status="pending",
            )
            session.add(mention)
            await session.flush()
            mention_id = mention.id

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registered = await client.post("/graph/ontology/register-default")
            queue = await client.get("/graph/review-queue", params={"kb_id": kb_id})
            decided = await client.post(
                f"/graph/databases/{kb_id}/review-decisions",
                json={
                    "target_type": "entity_mention",
                    "target_id": str(mention_id),
                    "decision": "accepted",
                    "reason": "HTTP 人工审核通过",
                },
            )
            disputed = await client.post(
                f"/graph/databases/{kb_id}/review-decisions",
                json={
                    "target_type": "entity_mention",
                    "target_id": str(mention_id),
                    "decision": "disputed",
                    "reason": "HTTP 复核发现型号歧义",
                },
            )
            conflicts = await client.get(f"/graph/databases/{kb_id}/conflicts")
            resolved = await client.post(
                f"/graph/databases/{kb_id}/conflicts/{disputed.json()['data']['conflict_id']}/resolve",
                json={"status": "resolved", "resolution": "已核对原文，保留当前实体"},
            )

        assert registered.status_code == 200, registered.text
        assert queue.status_code == 200, queue.text
        assert queue.json()["data"]["items"][0]["evidence_spans"] == [{"start": 0, "end": 5}]
        assert decided.status_code == 200, decided.text
        assert decided.json()["data"]["review_status"] == "accepted"
        assert disputed.status_code == 200, disputed.text
        assert conflicts.status_code == 200, conflicts.text
        assert conflicts.json()["data"]["items"][0]["conflict_id"] == disputed.json()["data"]["conflict_id"]
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["data"]["status"] == "resolved"

        async with pg_manager.get_async_session_context() as session:
            reviewed = await session.get(KnowledgeGraphEntityMention, mention_id)
            projection = await session.get(
                KnowledgeGraphProjectionOutbox,
                decided.json()["data"]["projection_event_id"],
            )
            assert reviewed.review_status == "disputed"
            assert projection.payload["decision_id"] == decided.json()["data"]["decision_id"]
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_acceptance_lineage_and_http_status_use_real_postgres(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_acceptance_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    triple_id = f"triple_{suffix}"
    repository = KnowledgeGraphAcceptanceRepository()
    reviewer = SimpleNamespace(uid="reviewer")
    app = FastAPI()
    app.include_router(graph_router.graph)
    app.dependency_overrides[graph_router.get_admin_user] = lambda: reviewer
    app.dependency_overrides[graph_router.require_knowledge_base_read] = lambda: reviewer
    app.dependency_overrides[graph_router.require_knowledge_base_manage] = lambda: reviewer

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="acceptance", kb_type="milvus"))
            await session.flush()
            session.add(
                KnowledgeFile(
                    file_id=file_id,
                    kb_id=kb_id,
                    filename="paper.pdf",
                    file_type="paper",
                    content_hash="d" * 64,
                    processing_params={"source_type": "paper", "language": "zh", "domain": "雷达感知"},
                )
            )
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达提升探测能力",
                    document_version=2,
                    parser_name="paddlex",
                    parser_version="3.0",
                    graph_indexed=False,
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=source_id,
                        kb_id=kb_id,
                        normalized_name="相控阵雷达",
                        label="KeyTechnology",
                        name="相控阵雷达",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="探测能力",
                        label="Capability",
                        name="探测能力",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id=source_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="相控阵雷达",
                        start_char=0,
                        end_char=5,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=target_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        mention_text="探测能力",
                        start_char=7,
                        end_char=11,
                        review_status="accepted",
                    ),
                ]
            )
            session.add(
                KnowledgeGraphTriple(
                    triple_id=triple_id,
                    kb_id=kb_id,
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type="ENABLES_CAPABILITY",
                    content="相控阵雷达 → ENABLES_CAPABILITY → 探测能力",
                )
            )
            await session.flush()
            session.add(
                KnowledgeGraphTripleMention(
                    triple_id=triple_id,
                    kb_id=kb_id,
                    file_id=file_id,
                    chunk_id=chunk_id,
                    text="相控阵雷达提升探测能力",
                    claim_level="Fact",
                    evidence_spans=[{"start": 0, "end": 11}],
                    review_status="accepted",
                )
            )

        run = await repository.start_build_run(
            kb_id=kb_id,
            pipeline_revision="hybrid-v2-r1",
            ontology_version="defense-kg-1.0",
            model_versions={"primary": "fastino/lightrag.5-multi-v1"},
            rule_version="defense-quality-contract-v1",
            scope="pending",
            started_by="reviewer",
        )
        assert run["document_ids"] == [file_id]
        stage = await repository.start_stage(
            run_id=run["run_id"],
            stage_code="information_extraction",
            stage_order=20,
            input_payload={"document_ids": run["document_ids"]},
            model_versions={"primary": "fastino/lightrag.5-multi-v1"},
            ontology_version="defense-kg-1.0",
            rule_version="defense-quality-contract-v1",
        )
        assert await repository.finish_stage(
            stage_run_id=stage["stage_run_id"],
            status="completed",
            metrics={"processed_chunks": 1},
            output_payload={"entities": 2, "relations": 1},
        )
        assert await repository.finish_build_run(
            run_id=run["run_id"],
            status="completed",
            metrics={"success": 1, "failed": 0},
        )

        actual_counts = {
            "source_documents": 1,
            "paper_documents": 1,
            "patent_documents": 0,
            "documents_with_build_runs": 1,
            "accepted_entities": 2,
            "accepted_relations": 1,
        }
        count_thresholds = {
            "source_documents": PILOT_QUOTAS["source_documents"],
            "paper_documents": PILOT_QUOTAS["paper_documents"],
            "patent_documents": PILOT_QUOTAS["patent_documents"],
            "documents_with_build_runs": PILOT_QUOTAS["source_documents"],
            "accepted_entities": PILOT_GRAPH_QUOTAS["accepted_entities"],
            "accepted_relations": PILOT_GRAPH_QUOTAS["accepted_relations"],
        }
        failed_count_criteria = {
            criterion_id for criterion_id, actual in actual_counts.items() if actual < count_thresholds[criterion_id]
        }
        criteria = [
            {
                "id": criterion_id,
                "passed": criterion_id not in failed_count_criteria,
                **({"actual": actual_counts[criterion_id]} if criterion_id in actual_counts else {}),
            }
            for criterion_id in sorted(REQUIRED_ACCEPTANCE_CRITERIA)
        ]
        report = {
            "acceptance_contract": "defense-kg-pilot-acceptance-v5",
            "passed": False,
            "criteria": criteria,
            "failed_criteria": [item["id"] for item in criteria if not item["passed"]],
        }
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            recorded = await client.post(
                f"/graph/databases/{kb_id}/acceptance/evaluations",
                json={
                    "pipeline_revision": "hybrid-v2-r1",
                    "gold_manifest_sha256": "a" * 64,
                    "prediction_sha256": "b" * 64,
                    "report": report,
                },
            )
            recorded_again = await client.post(
                f"/graph/databases/{kb_id}/acceptance/evaluations",
                json={
                    "pipeline_revision": "hybrid-v2-r1",
                    "gold_manifest_sha256": "a" * 64,
                    "prediction_sha256": "b" * 64,
                    "report": report,
                },
            )
            status = await client.get(f"/graph/databases/{kb_id}/acceptance/status")
            build_runs = await client.get(f"/graph/databases/{kb_id}/build-runs")
            build_run_detail = await client.get(f"/graph/databases/{kb_id}/build-runs/{run['run_id']}")

        assert recorded.status_code == 200, recorded.text
        assert recorded_again.json()["data"]["evaluation_id"] == recorded.json()["data"]["evaluation_id"]
        assert status.status_code == 200, status.text
        assert build_runs.status_code == 200, build_runs.text
        assert build_run_detail.status_code == 200, build_run_detail.text
        assert build_run_detail.json()["data"]["stages"][0]["stage_code"] == "information_extraction"
        assert build_run_detail.json()["data"]["stages"][0]["input_hash"] == stage["input_hash"]
        acceptance = status.json()["data"]
        assert acceptance["passed"] is False
        assert set(acceptance["failed_criteria"]) == failed_count_criteria
        assert acceptance["stats"] == {
            "source_documents": 1,
            "paper_documents": 1,
            "patent_documents": 0,
            "documents_with_build_runs": 1,
            "accepted_entities": 2,
            "accepted_relations": 1,
            "duplicate_relation_mentions_excluded": True,
            "unreviewed_hypotheses_excluded": True,
        }

        async with pg_manager.get_async_session_context() as session:
            source = await session.get(KnowledgeSourceDocument, file_id)
            version = await session.get(KnowledgeDocumentVersion, (file_id, 2))
            build_run = await session.get(KnowledgeGraphBuildRun, run["run_id"])
            stage_run = await session.get(KnowledgeGraphBuildStageRun, stage["stage_run_id"])
            evaluation_count = await session.scalar(
                select(func.count())
                .select_from(KnowledgeGraphEvaluationRun)
                .where(KnowledgeGraphEvaluationRun.kb_id == kb_id)
            )
            assert source.source_type == "paper"
            assert version.parser_name == "paddlex"
            assert build_run.status == "completed"
            assert stage_run.status == "completed"
            assert stage_run.output_hash
            assert evaluation_count == 1
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_build_run_freezes_exact_chunk_batch_in_real_postgres(pg_pool):
    """批次运行固定精确 Chunk，并让下一批只选择尚未完成的剩余项。"""
    suffix = uuid4().hex
    kb_id = f"pytest_graph_batch_{suffix}"
    file_ids = [f"file_a_{suffix}", f"file_b_{suffix}"]
    chunk_ids = [f"chunk_{index}_{suffix}" for index in range(3)]
    repository = KnowledgeGraphAcceptanceRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="graph batch", kb_type="milvus"))
            await session.flush()
            session.add_all(
                [
                    KnowledgeFile(
                        file_id=file_ids[0],
                        kb_id=kb_id,
                        filename="paper-a.pdf",
                        file_type="paper",
                        content_hash="a" * 64,
                        processing_params={"source_type": "paper", "language": "zh"},
                    ),
                    KnowledgeFile(
                        file_id=file_ids[1],
                        kb_id=kb_id,
                        filename="paper-b.pdf",
                        file_type="paper",
                        content_hash="b" * 64,
                        processing_params={"source_type": "paper", "language": "zh"},
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeChunk(
                        chunk_id=chunk_ids[0],
                        file_id=file_ids[0],
                        kb_id=kb_id,
                        chunk_index=0,
                        content="相控阵雷达提升探测能力。",
                        document_version=1,
                        parser_name="native-pdf",
                        parser_version="1.0",
                        graph_indexed=False,
                    ),
                    KnowledgeChunk(
                        chunk_id=chunk_ids[1],
                        file_id=file_ids[0],
                        kb_id=kb_id,
                        chunk_index=1,
                        content="宽带接收机提升抗干扰能力。",
                        document_version=1,
                        parser_name="native-pdf",
                        parser_version="1.0",
                        graph_indexed=False,
                    ),
                    KnowledgeChunk(
                        chunk_id=chunk_ids[2],
                        file_id=file_ids[1],
                        kb_id=kb_id,
                        chunk_index=0,
                        content="氮化镓器件支持射频前端。",
                        document_version=1,
                        parser_name="native-pdf",
                        parser_version="1.0",
                        graph_indexed=False,
                    ),
                ]
            )

        first = await repository.start_build_run(
            kb_id=kb_id,
            pipeline_revision="hybrid-v2-r1",
            ontology_version="defense-kg-1.0",
            model_versions={"primary": "fastino/lightrag.5-multi-v1"},
            rule_version="defense-quality-contract-v1",
            scope="pending",
            max_chunks=2,
        )

        assert first["chunk_ids"] == chunk_ids[:2]
        assert first["document_ids"] == [file_ids[0]]

        async with pg_manager.get_async_session_context() as session:
            selected = list(
                await session.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.chunk_id.in_(first["chunk_ids"]))
                    .order_by(KnowledgeChunk.id)
                )
            )
            for chunk in selected:
                chunk.graph_indexed = True

        second = await repository.start_build_run(
            kb_id=kb_id,
            pipeline_revision="hybrid-v2-r1",
            ontology_version="defense-kg-1.0",
            model_versions={"primary": "fastino/lightrag.5-multi-v1"},
            rule_version="defense-quality-contract-v1",
            scope="pending",
            max_chunks=2,
        )

        assert second["chunk_ids"] == [chunk_ids[2]]
        assert second["document_ids"] == [file_ids[1]]
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_innovation_hypothesis_redirect_and_trend_use_real_postgres(pg_pool):
    suffix = uuid4().hex
    kb_id = f"pytest_evolution_{suffix}"
    file_id = f"file_{suffix}"
    chunk_id = f"chunk_{suffix}"
    source_id = f"source_{suffix}"
    target_id = f"target_{suffix}"
    old_triple_id = f"triple_old_{suffix}"
    replacement_triple_id = f"triple_new_{suffix}"
    repository = KnowledgeGraphEvolutionRepository()

    try:
        async with pg_manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id=kb_id, name="evolution", kb_type="milvus"))
            await session.flush()
            session.add(
                KnowledgeFile(
                    file_id=file_id,
                    kb_id=kb_id,
                    filename="patent.pdf",
                    file_type="patent",
                )
            )
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id=chunk_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="技术 A 可迁移至应用 B",
                    source_metadata={
                        "publication_date": "2026-08-01",
                        "patent_family_id": "family-1",
                        "citation_count": 4,
                        "validation_status": "prototype",
                        "domains": ["雷达", "通信"],
                    },
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id=source_id,
                        kb_id=kb_id,
                        normalized_name="技术a",
                        label="KeyTechnology",
                        name="技术 A",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="应用b",
                        label="ApplicationScenario",
                        name="应用 B",
                    ),
                ]
            )
            await session.flush()
            session.add(
                KnowledgeGraphEntityMention(
                    entity_id=source_id,
                    kb_id=kb_id,
                    file_id=file_id,
                    chunk_id=chunk_id,
                    mention_text="技术 A",
                    start_char=0,
                    end_char=4,
                    confidence=0.96,
                    review_status="accepted",
                )
            )
            session.add_all(
                [
                    KnowledgeGraphTriple(
                        triple_id=old_triple_id,
                        kb_id=kb_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relation_type="TRANSFERABLE_TO",
                        content="技术 A 可迁移至应用 B",
                    ),
                    KnowledgeGraphTriple(
                        triple_id=replacement_triple_id,
                        kb_id=kb_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relation_type="APPLIED_TO",
                        content="技术 A 应用于应用 B",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphTripleMention(
                        triple_id=old_triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        claim_level="Fact",
                        evidence_spans=[{"start": 0, "end": 12}],
                        review_status="accepted",
                        ontology_version="defense-kg-1.0",
                    ),
                    KnowledgeGraphTripleMention(
                        triple_id=replacement_triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=chunk_id,
                        claim_level="Fact",
                        evidence_spans=[{"start": 0, "end": 12}],
                        review_status="accepted",
                        ontology_version="defense-kg-1.0",
                    ),
                ]
            )

        candidate = {
            "hypothesis_id": f"hypothesis_{suffix}",
            "source": {"entity_id": source_id},
            "target": {"entity_id": target_id},
            "relation_type": "TRANSFERABLE_TO",
            "discovery_mode": "bottom_up",
            "claim_level": "Hypothesis",
            "score": 0.82,
            "evidence_path": {
                "path_id": "path-1",
                "relation_ids": ["r1", "r2"],
                "chunk_ids": [chunk_id],
                "file_ids": [file_id],
            },
            "mechanism_hypothesis": "技术 A 可能迁移至应用 B",
            "feasibility_basis": ["存在两跳证据路径"],
            "expected_effects": ["形成跨域应用机会"],
            "applicable_conditions": ["完成目标系统接口适配"],
            "uncertainties": ["尚无直接验证"],
            "algorithm_version": "defense-graph-innovation-v1",
        }
        saved = await repository.save_hypotheses(kb_id, [candidate])
        assert saved[0]["claim_level"] == "Hypothesis"
        assert saved[0]["review_status"] == "pending"
        assert saved[0]["applicable_conditions"] == ["完成目标系统接口适配"]

        reviewed = await repository.review_hypothesis(
            kb_id=kb_id,
            hypothesis_id=candidate["hypothesis_id"],
            decision="accepted",
            reviewer_uid="reviewer",
            reason="接受为待验证研究方向",
        )
        assert reviewed["claim_level"] == "Hypothesis"

        redirect = await repository.redirect_entity(
            kb_id=kb_id,
            source_entity_id=source_id,
            target_entity_ids=[target_id],
            operation="merge",
            reason="人工确认同一技术实体",
            created_by="reviewer",
        )
        assert redirect["target_entity_id"] == target_id
        assert redirect["projection_event_id"]
        history = await repository.entity_history(kb_id=kb_id, entity_id=source_id)
        assert history["entity"]["lifecycle_status"] == "redirected"
        assert history["redirects"][0]["operation"] == "merge"
        assert history["events"][0]["event_type"] == "entity_merge"

        observations = await repository.build_entity_observations(kb_id=kb_id, entity_id=source_id)
        assert observations == [
            {
                "period": "2026-08",
                "document_count": 1,
                "citation_count": 4,
                "patent_family_count": 1,
                "validation_count": 1,
                "domains": ["通信", "雷达"],
                "evidence_quality": 0.96,
            }
        ]

        analysis = {
            "algorithm_version": "defense-technology-evolution-v1",
            "as_of": "2026-10-30T00:00:00+00:00",
            "frontier_score": 0.78,
            "component_scores": {"recency": 0.9},
            "maturity_stage": "experimental_validation",
            "burst_level": "insufficient_data",
            "time_series": observations,
        }
        snapshot = await repository.save_trend_snapshot(
            kb_id=kb_id,
            entity_id=source_id,
            analysis=analysis,
            evidence={"source": "accepted_entity_mentions"},
        )
        assert snapshot["snapshot_id"]

        reviewer = SimpleNamespace(uid="reviewer")
        app = FastAPI()
        app.include_router(graph_router.graph)
        app.dependency_overrides[graph_router.require_knowledge_base_read] = lambda: reviewer
        app.dependency_overrides[graph_router.require_knowledge_base_manage] = lambda: reviewer
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            candidates_response = await client.get(
                f"/graph/databases/{kb_id}/innovation/candidates",
                params={"status": "accepted"},
            )
            history_response = await client.get(f"/graph/databases/{kb_id}/entities/{source_id}/history")
            evolution_response = await client.get(f"/graph/databases/{kb_id}/entities/{source_id}/evolution")
            lifecycle_response = await client.post(
                f"/graph/databases/{kb_id}/relations/{old_triple_id}/lifecycle",
                json={
                    "lifecycle_status": "superseded",
                    "superseded_by_triple_id": replacement_triple_id,
                    "reason": "新证据支持更明确的应用关系",
                },
            )
            relation_response = await client.get(f"/graph/databases/{kb_id}/relations/{old_triple_id}")

        assert candidates_response.status_code == 200, candidates_response.text
        assert candidates_response.json()["data"]["items"][0]["claim_level"] == "Hypothesis"
        assert history_response.status_code == 200, history_response.text
        assert history_response.json()["data"]["entity"]["lifecycle_status"] == "redirected"
        assert evolution_response.status_code == 200, evolution_response.text
        assert evolution_response.json()["data"]["items"][0]["snapshot_id"] == snapshot["snapshot_id"]
        assert lifecycle_response.status_code == 200, lifecycle_response.text
        assert lifecycle_response.json()["data"]["lifecycle_status"] == "superseded"
        assert lifecycle_response.json()["data"]["superseded_by_triple_id"] == replacement_triple_id
        assert relation_response.status_code == 200, relation_response.text
        assert relation_response.json()["data"]["relation"]["relation_version"] == 2

        async with pg_manager.get_async_session_context() as session:
            hypothesis = await session.get(KnowledgeGraphHypothesis, candidate["hypothesis_id"])
            trend = await session.get(KnowledgeGraphTrendSnapshot, snapshot["snapshot_id"])
            redirect_projection = await session.get(
                KnowledgeGraphProjectionOutbox,
                redirect["projection_event_id"],
            )
            old_relation = await session.scalar(
                select(KnowledgeGraphTriple).where(KnowledgeGraphTriple.triple_id == old_triple_id)
            )
            projection_events = list(
                await session.scalars(
                    select(KnowledgeGraphProjectionOutbox).where(KnowledgeGraphProjectionOutbox.kb_id == kb_id)
                )
            )
            lifecycle_projection = next(
                event for event in projection_events if (event.payload or {}).get("event_type") == "relation_lifecycle"
            )
            assert hypothesis.claim_level == "Hypothesis"
            assert hypothesis.review_status == "accepted"
            assert trend.frontier_score == pytest.approx(0.78)
            assert redirect_projection is not None
            assert redirect_projection.payload["event_type"] == "entity_redirect"
            assert redirect_projection.payload["source_entity_id"] == source_id
            assert redirect_projection.payload["target_entity_ids"] == [target_id]
            assert old_relation.lifecycle_status == "superseded"
            assert old_relation.superseded_by_triple_id == replacement_triple_id
            assert old_relation.vector_status == "disabled"
            assert lifecycle_projection.payload["triple_id"] == old_triple_id
    finally:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if kb is not None:
                await session.delete(kb)
