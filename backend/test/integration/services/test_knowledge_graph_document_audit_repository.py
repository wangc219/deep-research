from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.knowledge.graphs.document_knowledge_audit import build_document_knowledge, triage_document
from platform_core.repositories import knowledge_graph_document_audit_repository as repository_module
from platform_core.repositories.knowledge_graph_document_audit_repository import (
    KnowledgeGraphDocumentAuditRepository,
)
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentCard,
    KnowledgeFile,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeResearchThread,
    KnowledgeSourceDocument,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_document_audit_repository_filters_and_persists_card(monkeypatch):
    schema = f"pytest_document_audit_{uuid.uuid4().hex[:16]}"
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
    monkeypatch.setattr(repository_module, "pg_manager", manager)

    try:
        await manager.create_knowledge_tables()
        async with manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id="kb", name="kb", kb_type="milvus"))
            await session.flush()
            session.add(KnowledgeFile(file_id="file", kb_id="kb", filename="paper-2025.pdf"))
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
            content = "摘要 本文面向雷达装备抗干扰任务。" + "实验结果表明自适应技术提升感知能力。" * 80
            technology_start = content.index("自适应技术")
            technology_end = technology_start + len("自适应技术")
            capability_start = content.index("感知能力")
            capability_end = capability_start + len("感知能力")
            bbox = [10, 20, 300, 60]
            session.add(
                KnowledgeChunk(
                    chunk_id="block",
                    file_id="file",
                    kb_id="kb",
                    chunk_index=0,
                    content=content,
                    document_version=1,
                    page_number=1,
                    heading_path=["方法"],
                    bbox=bbox,
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntity(
                        entity_id="tech",
                        kb_id="kb",
                        normalized_name="自适应技术",
                        label="KeyTechnology",
                        name="自适应技术",
                    ),
                    KnowledgeGraphEntity(
                        entity_id="cap",
                        kb_id="kb",
                        normalized_name="感知能力",
                        label="Capability",
                        name="感知能力",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id="tech",
                        kb_id="kb",
                        file_id="file",
                        chunk_id="block",
                        start_char=technology_start,
                        end_char=technology_end,
                        confidence=0.94,
                        model_version="lightrag.5-multi-v1",
                        ontology_version="defense-kg-1.0",
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id="cap",
                        kb_id="kb",
                        file_id="file",
                        chunk_id="block",
                        start_char=capability_start,
                        end_char=capability_end,
                    ),
                ]
            )
            session.add(
                KnowledgeGraphTriple(
                    triple_id="relation",
                    kb_id="kb",
                    source_entity_id="tech",
                    target_entity_id="cap",
                    relation_type="ENABLES_CAPABILITY",
                    content="自适应技术提升感知能力",
                )
            )
            await session.flush()
            session.add(
                KnowledgeGraphTripleMention(
                    triple_id="relation",
                    kb_id="kb",
                    file_id="file",
                    chunk_id="block",
                    extractor_type="lightrag_joint_ie",
                    claim_level="Fact",
                    confidence=0.86,
                    review_status="accepted",
                    model_version="lightrag.5-multi-v1",
                    ontology_version="defense-kg-1.0",
                    pipeline_revision="hybrid-v2-r1",
                    evidence_spans=[
                        {
                            "block_id": "block",
                            "start": technology_start,
                            "end": technology_end,
                            "page": 1,
                        }
                    ],
                )
            )

        repository = KnowledgeGraphDocumentAuditRepository()
        raw_document = (await repository.load_documents(kb_id="kb", document_ids=["doc"], include_graph=False))[0]
        triage = triage_document(raw_document)
        await repository.persist_triage(kb_id="kb", results=[triage], apply_filter=True)
        document = (await repository.load_documents(kb_id="kb", document_ids=["doc"], include_graph=True))[0]
        bundle = build_document_knowledge(
            document,
            triage=triage,
            pipeline_revision="hybrid-v2-r1",
            ontology_version="defense-kg-1.0",
        )
        await repository.persist_document_knowledge(
            document=document,
            bundle=bundle,
            pipeline_revision="hybrid-v2-r1",
        )

        async with manager.get_async_session_context() as session:
            chunk = await session.scalar(select(KnowledgeChunk))
            card = await session.scalar(select(KnowledgeDocumentCard))
            thread = await session.scalar(select(KnowledgeResearchThread))
            assert chunk.graph_excluded is False
            assert card.technology_families == ["自适应技术"]
            assert card.capability_gains == ["感知能力"]
            assert thread.evidence_refs

        detail = await repository.get_card(kb_id="kb", card_id=bundle["card"]["card_id"])
        assert detail is not None
        assert detail["threads"]
        assert detail["evidence_refs"]
        technology_evidence = next(
            item
            for item in detail["evidence_refs"]
            if item["start"] == technology_start and item["end"] == technology_end
        )
        assert technology_evidence == {
            "block_id": "block",
            "page": 1,
            "start": technology_start,
            "end": technology_end,
            "entity_ids": ["tech"],
            "triple_ids": ["relation"],
            "supports": [
                {
                    "kind": "entity",
                    "id": "tech",
                    "evidence_use": "entity_identification",
                    "evidence_use_label": "关键技术识别",
                    "entity_type": "KeyTechnology",
                    "claim_level": None,
                    "review_status": "accepted",
                    "confidence": 0.94,
                    "extraction_method": "entity_mention",
                    "model_version": "lightrag.5-multi-v1",
                    "ontology_version": "defense-kg-1.0",
                    "pipeline_revision": None,
                },
                {
                    "kind": "relation",
                    "id": "relation",
                    "evidence_use": "relation_support",
                    "evidence_use_label": "ENABLES_CAPABILITY 支撑",
                    "relation_type": "ENABLES_CAPABILITY",
                    "claim_level": "Fact",
                    "review_status": "accepted",
                    "confidence": 0.86,
                    "extraction_method": "lightrag_joint_ie",
                    "model_version": "lightrag.5-multi-v1",
                    "ontology_version": "defense-kg-1.0",
                    "pipeline_revision": "hybrid-v2-r1",
                },
            ],
            "text": content[technology_start:technology_end],
            "rebuildable": True,
            "heading_path": ["方法"],
            "bbox": bbox,
        }
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
