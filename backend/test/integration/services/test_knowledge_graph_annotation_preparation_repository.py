from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.knowledge.training.pilot_campaign import PilotSelectionEntry, PilotSelectionManifest
from platform_core.repositories import knowledge_graph_annotation_preparation_repository as preparation_module
from platform_core.repositories import knowledge_graph_source_repository as source_module
from platform_core.repositories.knowledge_graph_annotation_preparation_repository import (
    KnowledgeGraphAnnotationPreparationRepository,
)
from platform_core.storage.postgres.manager import PostgresManager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeSourceDocument,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_preflight_registers_only_explicitly_selected_authoritative_sources(monkeypatch):
    schema = f"pytest_annotation_prepare_{uuid.uuid4().hex[:16]}"
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
    monkeypatch.setattr(preparation_module, "pg_manager", manager)
    monkeypatch.setattr(source_module, "pg_manager", manager)

    try:
        await manager.create_knowledge_tables()
        manifest = _manifest()
        first = manifest.entries[0]
        second = manifest.entries[1]
        async with manager.get_async_session_context() as session:
            session.add(KnowledgeBase(kb_id="kb", name="kb", kb_type="milvus"))
            await session.flush()
            session.add_all(
                [
                    KnowledgeFile(
                        file_id="file-001",
                        kb_id="kb",
                        filename="source.pdf",
                        file_type="pdf",
                        content_hash=first.content_sha256,
                        processing_params={},
                    ),
                    KnowledgeFile(
                        file_id="file-002",
                        kb_id="kb",
                        filename="existing-source.pdf",
                        file_type="pdf",
                        content_hash=second.content_sha256,
                        processing_params={},
                    ),
                ]
            )
            await session.flush()
            session.add(
                KnowledgeSourceDocument(
                    document_id="authority-doc-002",
                    kb_id="kb",
                    file_id="file-002",
                    source_type=second.source_type,
                    language=second.language,
                    domain=second.domain,
                    content_hash=second.content_sha256,
                    current_version=1,
                )
            )
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id="block-001",
                    file_id="file-001",
                    kb_id="kb",
                    chunk_index=0,
                    content="相控阵雷达提升探测能力。",
                    document_version=2,
                    parser_name="native-pdf",
                    parser_version="1.0",
                )
            )
            session.add(
                KnowledgeChunk(
                    chunk_id="block-002",
                    file_id="file-002",
                    kb_id="kb",
                    chunk_index=0,
                    content="氮化镓器件支持宽带射频前端。",
                    document_version=1,
                    parser_name="native-pdf",
                    parser_version="1.0",
                )
            )

        repository = KnowledgeGraphAnnotationPreparationRepository()
        before = await repository.preflight(manifest, kb_id="kb")
        registered = await repository.register_authoritative_documents(kb_id="kb", result=before)
        after = await repository.preflight(manifest, kb_id="kb")

        assert before.report["mapping"]["status_counts"] == {
            "missing_authoritative_document": 1,
            "missing_document_version": 1,
            "missing_knowledge_file": 298,
        }
        assert registered == 2
        assert after.report["mapping"]["status_counts"] == {
            "missing_knowledge_file": 298,
            "ready": 2,
        }
        assert after.report["mapping"]["authoritative_bindings"] == 2
        assert after.report["campaign_spec_ready"] is False
        assert "source.pdf" not in str(after.report)
        assert "/private/" not in str(after.report)

        async with manager.get_async_session_context() as session:
            sources = list(
                await session.scalars(select(KnowledgeSourceDocument).order_by(KnowledgeSourceDocument.file_id))
            )
            versions = list(
                await session.scalars(select(KnowledgeDocumentVersion).order_by(KnowledgeDocumentVersion.document_id))
            )
        assert len(sources) == 2
        assert (sources[0].source_type, sources[0].language, sources[0].domain) == (
            first.source_type,
            first.language,
            first.domain,
        )
        assert sources[0].current_version == 2
        assert sources[1].document_id == "authority-doc-002"
        assert {(item.document_id, item.version) for item in versions} == {
            ("file-001", 2),
            ("authority-doc-002", 1),
        }
        assert all(len(item.input_hash) == 64 for item in versions)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()


def _manifest() -> PilotSelectionManifest:
    splits = ["train"] * 210 + ["dev"] * 30 + ["test"] * 60
    entries = [
        PilotSelectionEntry(
            document_id=f"src_{index:064x}",
            split=split,
            source_type="paper" if index % 2 == 0 else "patent",
            language="zh" if index % 3 else "en",
            domain=f"domain-{index % 6}",
            domain_annotation_kind="human",
            content_sha256=f"{index:064x}",
        )
        for index, split in enumerate(splits)
    ]
    return PilotSelectionManifest(entries=entries, manifest_sha256="f" * 64)
