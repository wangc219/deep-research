from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.repositories import knowledge_graph_document_enhancement_repository as document_repository_module
from platform_core.repositories import knowledge_graph_repository as graph_repository_module
from platform_core.repositories.knowledge_graph_document_enhancement_repository import (
    KnowledgeGraphDocumentEnhancementRepository,
)
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphProjectionOutbox,
    KnowledgeGraphRevision,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeSourceDocument,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_document_enhancement_repository_uses_canonical_entities_and_preserves_review(monkeypatch):
    schema = f"pytest_docre_repo_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
    manager._initialized = True
    monkeypatch.setattr(document_repository_module, "pg_manager", manager)
    monkeypatch.setattr(graph_repository_module, "pg_manager", manager)

    try:
        await manager.create_knowledge_tables()
        async with manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id="kb", name="kb", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id="file", kb_id="kb", filename="paper.pdf"))
            await session.flush()
            session.add(
                KnowledgeSourceDocument(
                    document_id="doc",
                    kb_id="kb",
                    file_id="file",
                    source_type="paper",
                    language="zh",
                    current_version=1,
                )
            )
            await session.flush()
            session.add(
                KnowledgeDocumentVersion(
                    document_id="doc",
                    version=1,
                    content_hash="content",
                    input_hash="input",
                )
            )
            session.add_all(
                [
                    KnowledgeChunk(
                        chunk_id="block-1",
                        file_id="file",
                        kb_id="kb",
                        chunk_index=0,
                        content="氮化镓组件用于雷达前端",
                        document_version=1,
                        page_number=1,
                    ),
                    KnowledgeChunk(
                        chunk_id="block-2",
                        file_id="file",
                        kb_id="kb",
                        chunk_index=1,
                        content="宽带感知能力得到提升",
                        document_version=1,
                        page_number=2,
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id="entity-1",
                        kb_id="kb",
                        normalized_name="氮化镓组件",
                        label="Component",
                        name="氮化镓组件",
                    ),
                    KnowledgeGraphEntity(
                        entity_id="entity-2",
                        kb_id="kb",
                        normalized_name="宽带感知",
                        label="Capability",
                        name="宽带感知",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id="entity-1",
                        kb_id="kb",
                        file_id="file",
                        chunk_id="block-1",
                        mention_text="氮化镓组件",
                        start_char=0,
                        end_char=5,
                        confidence=0.94,
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id="entity-2",
                        kb_id="kb",
                        file_id="file",
                        chunk_id="block-2",
                        mention_text="宽带感知",
                        start_char=0,
                        end_char=4,
                        confidence=0.92,
                    ),
                ]
            )

        repository = KnowledgeGraphDocumentEnhancementRepository()
        documents = await repository.load_documents(kb_id="kb", document_ids=["doc"])

        assert len(documents) == 1
        assert [item["entity_id"] for item in documents[0]["entities"]] == ["entity-1", "entity-2"]
        document_entity = {
            "entity_id": str(uuid.uuid4()),
            "kb_id": "kb",
            "normalized_name": "雷达前端",
            "label": "ProductSystem",
            "name": "雷达前端",
            "attributes": [],
            "content": "雷达前端",
            "mention_text": "雷达前端",
            "block_id": "block-1",
            "start_char": 7,
            "end_char": 11,
            "confidence": 0.88,
            "model_version": "local:military-chat",
            "ontology_version": "defense-kg-1.0",
            "review_status": "pending",
        }
        await repository.align_entity_records(kb_id="kb", entities=[document_entity])
        assert (
            await repository.persist_entity_mentions(
                kb_id="kb",
                document=documents[0],
                entities=[document_entity],
                ontology_version="defense-kg-1.0",
                pipeline_revision="hybrid-v2-r1",
            )
            == 1
        )
        async with manager.get_async_session_context() as session:
            enhanced_mention = await session.scalar(
                select(KnowledgeGraphEntityMention).where(KnowledgeGraphEntityMention.mention_text == "雷达前端")
            )
            assert enhanced_mention.review_status == "pending"
            await session.execute(
                update(KnowledgeGraphEntityMention)
                .where(KnowledgeGraphEntityMention.id == enhanced_mention.id)
                .values(review_status="accepted")
            )
        await repository.persist_entity_mentions(
            kb_id="kb",
            document=documents[0],
            entities=[document_entity],
            ontology_version="defense-kg-1.0",
            pipeline_revision="hybrid-v2-r1",
        )
        async with manager.get_async_session_context() as session:
            enhanced_mention = await session.scalar(
                select(KnowledgeGraphEntityMention).where(KnowledgeGraphEntityMention.mention_text == "雷达前端")
            )
            assert enhanced_mention.review_status == "accepted"

        relation = {
            "type": "ENABLES_CAPABILITY",
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
            "confidence": 1.0,
            "confidence_kind": "hard_label",
            "evidence_spans": [
                {"block_id": "block-1", "start": 0, "end": 5},
                {"block_id": "block-2", "start": 0, "end": 4},
            ],
            "applicable_conditions": [],
            "hypothesis_only": False,
            "model_sources": ["lightrag_document_re", "lightrag_document_relation"],
            "model_versions": {
                "lightrag_document_re": "lightrag-doc-v1",
                "lightrag_document_relation": "local:military-chat",
            },
            "model_consensus": True,
        }
        assert (
            await repository.persist_relations(
                kb_id="kb",
                document=documents[0],
                relations=[relation],
                model_version="lightrag-doc-v1",
                ontology_version="defense-kg-1.0",
                pipeline_revision="hybrid-v2-r1",
            )
            == 1
        )

        async with manager.get_async_session_context() as session:
            mention = await session.scalar(select(KnowledgeGraphTripleMention))
            assert mention.claim_level == "Inference"
            assert mention.review_status == "pending"
            assert mention.extractor_type == "document_relation_ensemble"
            assert mention.model_version == (
                "lightrag_document_re=lightrag-doc-v1,lightrag_document_relation=local:military-chat"
            )
            assert "达成一致" in mention.reasoning_basis
            assert {item["block_id"] for item in mention.evidence_spans} == {"block-1", "block-2"}
            assert "hard label" in mention.uncertainty
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphTriple)) == 1
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphRevision)) == 2
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphProjectionOutbox)) == 2
            outboxes = list((await session.scalars(select(KnowledgeGraphProjectionOutbox))).all())
            outbox = next(item for item in outboxes if item.payload["triple_records"])
            endpoint_records = {record["entity_id"]: record for record in outbox.payload["entity_records"]}
            assert endpoint_records["entity-1"]["has_mention"] is False
            assert endpoint_records["entity-2"]["has_mention"] is False
            await session.execute(update(KnowledgeGraphTripleMention).values(review_status="accepted"))

        await repository.persist_relations(
            kb_id="kb",
            document=documents[0],
            relations=[relation],
            model_version="lightrag-doc-v1",
            ontology_version="defense-kg-1.0",
            pipeline_revision="hybrid-v2-r1",
        )
        async with manager.get_async_session_context() as session:
            mention = await session.scalar(select(KnowledgeGraphTripleMention))
            assert mention.review_status == "accepted"
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphTriple)) == 1
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphProjectionOutbox)) == 2
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


async def test_cross_document_relations_use_only_accepted_mentions_and_persist_multisource(monkeypatch):
    schema = f"pytest_cross_docre_{uuid.uuid4().hex[:16]}"
    admin_engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        os.environ["POSTGRES_URL"],
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    manager = object.__new__(PostgresManager)
    PostgresManager.__init__(manager)
    manager.async_engine = engine
    manager.AsyncSession = async_sessionmaker(engine, expire_on_commit=False)
    manager._initialized = True
    monkeypatch.setattr(document_repository_module, "pg_manager", manager)
    monkeypatch.setattr(graph_repository_module, "pg_manager", manager)

    try:
        await manager.create_knowledge_tables()
        async with manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id="kb", name="kb", kb_type="milvus"))
            await session.flush()
            session.add_all(
                [
                    KnowledgeFile(file_id="file-a", kb_id="kb", filename="paper-a.pdf"),
                    KnowledgeFile(file_id="file-b", kb_id="kb", filename="paper-b.pdf"),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeSourceDocument(
                        document_id="doc-a",
                        kb_id="kb",
                        file_id="file-a",
                        source_type="paper",
                        language="zh",
                        current_version=1,
                    ),
                    KnowledgeSourceDocument(
                        document_id="doc-b",
                        kb_id="kb",
                        file_id="file-b",
                        source_type="paper",
                        language="zh",
                        current_version=1,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeDocumentVersion(
                        document_id="doc-a",
                        version=1,
                        content_hash="content-a",
                        input_hash="input-a",
                    ),
                    KnowledgeDocumentVersion(
                        document_id="doc-b",
                        version=1,
                        content_hash="content-b",
                        input_hash="input-b",
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeChunk(
                        chunk_id="block-a",
                        file_id="file-a",
                        kb_id="kb",
                        chunk_index=0,
                        content="氮化镓组件提升宽带感知能力",
                        document_version=1,
                        page_number=1,
                    ),
                    KnowledgeChunk(
                        chunk_id="block-b",
                        file_id="file-b",
                        kb_id="kb",
                        chunk_index=0,
                        content="测试表明氮化镓组件增强宽带感知能力",
                        document_version=1,
                        page_number=2,
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id="component",
                        kb_id="kb",
                        normalized_name="氮化镓组件",
                        label="Component",
                        name="氮化镓组件",
                    ),
                    KnowledgeGraphEntity(
                        entity_id="capability",
                        kb_id="kb",
                        normalized_name="宽带感知能力",
                        label="Capability",
                        name="宽带感知能力",
                    ),
                    KnowledgeGraphEntity(
                        entity_id="pending-only",
                        kb_id="kb",
                        normalized_name="待审实体",
                        label="KeyTechnology",
                        name="待审实体",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id="component",
                        kb_id="kb",
                        file_id="file-a",
                        chunk_id="block-a",
                        mention_text="氮化镓组件",
                        start_char=0,
                        end_char=5,
                        confidence=0.96,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id="capability",
                        kb_id="kb",
                        file_id="file-a",
                        chunk_id="block-a",
                        mention_text="宽带感知能力",
                        start_char=7,
                        end_char=13,
                        confidence=0.95,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id="component",
                        kb_id="kb",
                        file_id="file-b",
                        chunk_id="block-b",
                        mention_text="氮化镓组件",
                        start_char=4,
                        end_char=9,
                        confidence=0.94,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id="capability",
                        kb_id="kb",
                        file_id="file-b",
                        chunk_id="block-b",
                        mention_text="宽带感知能力",
                        start_char=11,
                        end_char=17,
                        confidence=0.93,
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id="pending-only",
                        kb_id="kb",
                        file_id="file-a",
                        chunk_id="block-a",
                        mention_text="提升",
                        start_char=5,
                        end_char=7,
                        confidence=0.88,
                        review_status="pending",
                    ),
                ]
            )

        repository = KnowledgeGraphDocumentEnhancementRepository()
        expanded_documents = await repository.load_cross_document_scope(
            kb_id="kb",
            seed_document_ids=["doc-a"],
            accepted_mentions_only=True,
            max_documents=8,
        )
        assert [item["document_id"] for item in expanded_documents] == ["doc-a", "doc-b"]

        documents = await repository.load_documents(
            kb_id="kb",
            document_ids=["doc-a", "doc-b"],
            accepted_mentions_only=True,
        )

        assert len(documents) == 2
        assert {item["entity_id"] for document in documents for item in document["entities"]} == {
            "component",
            "capability",
        }
        relation = {
            "type": "ENABLES_CAPABILITY",
            "source_entity_id": "component",
            "target_entity_id": "capability",
            "confidence": 0.93,
            "evidence_spans": [
                {"document_id": "doc-a", "block_id": "block-a", "start": 0, "end": 13},
                {"document_id": "doc-b", "block_id": "block-b", "start": 0, "end": 17},
            ],
            "applicable_conditions": [],
        }
        assert (
            await repository.persist_cross_document_relations(
                kb_id="kb",
                documents=documents,
                relations=[relation],
                model_version="local:military-chat",
                ontology_version="defense-kg-1.0",
                pipeline_revision="hybrid-v2-r1",
            )
            == 1
        )

        async with manager.get_async_session_context() as session:
            mention = await session.scalar(select(KnowledgeGraphTripleMention))
            assert mention.claim_level == "Inference"
            assert mention.review_status == "pending"
            assert mention.extractor_type == "lightrag_cross_document_relation"
            assert mention.expert_review_required is True
            assert {item["document_id"] for item in mention.evidence_spans} == {"doc-a", "doc-b"}
            outbox = await session.scalar(select(KnowledgeGraphProjectionOutbox))
            metadata = outbox.payload["graph_payload"]["metadata"]
            assert metadata["support_level"] == "multi_source"
            assert metadata["source_document_count"] == 2
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphRevision)) == 1
            await session.execute(update(KnowledgeGraphTripleMention).values(review_status="accepted"))

        await repository.persist_cross_document_relations(
            kb_id="kb",
            documents=documents,
            relations=[relation],
            model_version="local:military-chat",
            ontology_version="defense-kg-1.0",
            pipeline_revision="hybrid-v2-r1",
        )
        async with manager.get_async_session_context() as session:
            mention = await session.scalar(select(KnowledgeGraphTripleMention))
            assert mention.review_status == "accepted"
            assert await session.scalar(select(func.count()).select_from(KnowledgeGraphProjectionOutbox)) == 1
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
