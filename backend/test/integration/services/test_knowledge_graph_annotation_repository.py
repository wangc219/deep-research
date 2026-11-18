from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.knowledge.training.annotation_workflow import (
    AnnotationAssignmentSpec,
    AnnotationCampaignSpec,
)
from platform_core.repositories import knowledge_graph_annotation_repository as repository_module
from platform_core.repositories.knowledge_graph_annotation_repository import (
    KnowledgeGraphAnnotationRepository,
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


async def test_annotation_repository_persists_append_only_revisions_and_unique_adjudication(monkeypatch):
    schema = f"pytest_annotation_repo_{uuid.uuid4().hex[:16]}"
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
            await session.execute(
                text("CREATE TABLE users (uid VARCHAR PRIMARY KEY, is_deleted INTEGER NOT NULL DEFAULT 0)")
            )
            await session.execute(
                text("INSERT INTO users (uid, is_deleted) VALUES ('ann-a', 0), ('ann-b', 0), ('expert', 0)")
            )
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
                    domain="radar",
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
            await session.flush()
            session.add(
                KnowledgeChunk(
                    chunk_id="block-1",
                    file_id="file",
                    kb_id="kb",
                    chunk_index=0,
                    content="相控阵雷达提升探测能力。",
                    document_version=1,
                    page_number=1,
                )
            )

        repository = KnowledgeGraphAnnotationRepository()
        with pytest.raises(ValueError, match="不存在或已删除"):
            await repository.create_campaign(
                kb_id="kb",
                spec=AnnotationCampaignSpec(
                    name="invalid-participant",
                    ontology_version="defense-kg-1.0",
                    pilot_mode=False,
                    assignments=[
                        AnnotationAssignmentSpec(
                            document_id="doc",
                            document_version=1,
                            split="train",
                            annotator_ids=["ann-a", "missing-user"],
                            arbitrator_id="expert",
                        )
                    ],
                ),
                created_by="owner",
            )

        campaign = await repository.create_campaign(
            kb_id="kb",
            spec=AnnotationCampaignSpec(
                name="local-test",
                ontology_version="defense-kg-1.0",
                pilot_mode=False,
                assignments=[
                    AnnotationAssignmentSpec(
                        document_id="doc",
                        document_version=1,
                        split="train",
                        annotator_ids=["ann-a", "ann-b"],
                        arbitrator_id="expert",
                    )
                ],
            ),
            created_by="owner",
        )
        assignments = await repository.list_user_assignments(kb_id="kb", user_id="ann-a")
        assignment_id = assignments[0]["assignment_id"]
        assignment = await repository.get_assignment(assignment_id)

        with pytest.raises(PermissionError, match="指定标注员"):
            await repository.append_submission(
                assignment_id=assignment_id,
                annotator_uid="intruder",
                annotation_payload={"revision": 1},
                payload_sha256="0" * 64,
            )
        with pytest.raises(PermissionError, match="指定仲裁专家"):
            await repository.save_adjudication(
                assignment_id=assignment_id,
                arbitrator_uid="intruder",
                final_payload={"document_id": "doc"},
                payload_sha256="0" * 64,
                disagreement_summary={},
            )
        with pytest.raises(ValueError, match="尚未都提交"):
            await repository.save_adjudication(
                assignment_id=assignment_id,
                arbitrator_uid="expert",
                final_payload={"document_id": "doc"},
                payload_sha256="0" * 64,
                disagreement_summary={},
            )

        saved_draft = await repository.save_draft(
            assignment_id=assignment_id,
            annotator_uid="ann-a",
            annotation_payload={"revision": "draft"},
            payload_sha256="f" * 64,
            source_kind="ai_prelabel",
            provenance={"annotation_kind": "ai_prelabel", "human_confirmed": False},
        )
        bulk = await repository.bulk_append_submissions(
            campaign_id=campaign["campaign_id"],
            annotator_uid="ann-a",
            expected_draft_count=1,
            items=[
                {
                    "assignment_id": assignment_id,
                    "draft_payload_sha256": "f" * 64,
                    "annotation_payload": {"revision": "bulk"},
                    "payload_sha256": "1" * 64,
                }
            ],
        )
        repeated = await repository.bulk_append_submissions(
            campaign_id=campaign["campaign_id"],
            annotator_uid="ann-a",
            expected_draft_count=0,
            items=[],
        )
        drafts = await repository.list_drafts(
            kb_id="kb",
            campaign_id=campaign["campaign_id"],
            annotator_uid="ann-a",
        )

        first = await repository.append_submission(
            assignment_id=assignment_id,
            annotator_uid="ann-a",
            annotation_payload={"revision": 1},
            payload_sha256="a" * 64,
        )
        second = await repository.append_submission(
            assignment_id=assignment_id,
            annotator_uid="ann-a",
            annotation_payload={"revision": 2},
            payload_sha256="b" * 64,
        )
        other = await repository.append_submission(
            assignment_id=assignment_id,
            annotator_uid="ann-b",
            annotation_payload={"revision": 1},
            payload_sha256="c" * 64,
        )
        latest = await repository.get_latest_submissions(assignment_id)
        adjudication = await repository.save_adjudication(
            assignment_id=assignment_id,
            arbitrator_uid="expert",
            final_payload={"document_id": "doc"},
            payload_sha256="d" * 64,
            disagreement_summary={"agreement": True},
        )
        exported = await repository.export_adjudicated_gold(campaign["campaign_id"])

        assert assignment["blocks"][0]["text"] == "相控阵雷达提升探测能力。"
        assert saved_draft["source_kind"] == "ai_prelabel"
        assert bulk["submitted_count"] == 1
        assert repeated["submitted_count"] == 0
        assert drafts[0]["submitted"] is True
        assert (first["revision"], second["revision"], other["revision"]) == (2, 3, 1)
        assert latest["ann-a"]["annotation_payload"] == {"revision": 2}
        assert adjudication["campaign_status"] == "completed"
        assert exported == [{"document_id": "doc"}]

        with pytest.raises(ValueError, match="不能继续追加"):
            await repository.append_submission(
                assignment_id=assignment_id,
                annotator_uid="ann-a",
                annotation_payload={"revision": 3},
                payload_sha256="e" * 64,
            )
        with pytest.raises(ValueError, match="不可覆盖"):
            await repository.save_adjudication(
                assignment_id=assignment_id,
                arbitrator_uid="expert",
                final_payload={"document_id": "doc"},
                payload_sha256="e" * 64,
                disagreement_summary={},
            )
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
