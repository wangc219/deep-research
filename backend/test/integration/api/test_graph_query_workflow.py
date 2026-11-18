from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, OperationLog, User
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeGraphChangeEvent,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityAlias,
    KnowledgeGraphEntityMention,
    KnowledgeGraphRevision,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeSourceDocument,
)
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_graph_query_http_returns_only_accepted_evidence_and_version_history(test_client):
    suffix = uuid.uuid4().hex[:10]
    kb_id = f"query-kb-{suffix}"
    file_id = f"query-file-{suffix}"
    document_id = f"query-doc-{suffix}"
    block_id = f"query-block-{suffix}"
    second_block_id = f"query-block-second-{suffix}"
    source_id = f"query-source-{suffix}"
    target_id = f"query-target-{suffix}"
    pending_id = f"query-pending-{suffix}"
    triple_id = f"query-triple-{suffix}"
    hypothesis_id = f"query-hypothesis-{suffix}"
    revision_id = f"query-revision-{suffix}"
    event_id = f"query-event-{suffix}"
    user_id = None

    try:
        async with pg_manager.get_async_session_context() as session:
            department_id = await session.scalar(select(Department.id).order_by(Department.id.asc()).limit(1))
            assert department_id is not None, "集成测试需要至少一个已存在部门"
            user = User(
                username=f"pytest_graph_query_{suffix}",
                uid=f"pytest-graph-query-{suffix}",
                password_hash="disabled-test-login",
                role="superadmin",
                department_id=department_id,
            )
            session.add(user)
            await session.flush()
            user_id = user.id
            session.add(
                KnowledgeBase(
                    kb_id=kb_id,
                    name=f"pytest_graph_query_{suffix}",
                    kb_type="milvus",
                    created_by=user.uid,
                )
            )
            await session.flush()
            session.add(
                KnowledgeFile(
                    file_id=file_id,
                    kb_id=kb_id,
                    filename="query-paper.pdf",
                    original_filename="实体关系查询论文.pdf",
                    file_type="pdf",
                )
            )
            await session.flush()
            session.add(
                KnowledgeSourceDocument(
                    document_id=document_id,
                    kb_id=kb_id,
                    file_id=file_id,
                    source_type="paper",
                    language="zh",
                    domain="radar",
                    current_version=1,
                )
            )
            await session.flush()
            session.add(
                KnowledgeDocumentVersion(
                    document_id=document_id,
                    version=1,
                    content_hash="content-hash",
                    input_hash="input-hash",
                )
            )
            session.add(
                KnowledgeChunk(
                    chunk_id=block_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=0,
                    content="相控阵雷达在完成阵列校准后提升探测能力。",
                    document_version=1,
                    page_number=3,
                    block_type="paragraph",
                    heading_path=["系统设计", "信号处理"],
                    parser_name="native-pdf",
                    parser_version="1",
                )
            )
            session.add(
                KnowledgeChunk(
                    chunk_id=second_block_id,
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=1,
                    content="另一组试验证据表明相控阵雷达可以提升探测能力。",
                    document_version=1,
                    page_number=4,
                    block_type="paragraph",
                    heading_path=["4 试验验证"],
                    parser_name="native-pdf",
                    parser_version="1",
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
                        attributes={"domain": "radar"},
                    ),
                    KnowledgeGraphEntity(
                        entity_id=target_id,
                        kb_id=kb_id,
                        normalized_name="探测能力",
                        label="Capability",
                        name="探测能力",
                    ),
                    KnowledgeGraphEntity(
                        entity_id=pending_id,
                        kb_id=kb_id,
                        normalized_name="待审核技术",
                        label="KeyTechnology",
                        name="待审核技术",
                    ),
                ]
            )
            await session.flush()
            session.add(
                KnowledgeGraphEntityAlias(
                    entity_id=source_id,
                    alias="Phased Array Radar",
                    normalized_alias="phased array radar",
                    language="en",
                    source="manual",
                    confidence=1.0,
                )
            )
            session.add_all(
                [
                    KnowledgeGraphEntityMention(
                        entity_id=source_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=block_id,
                        mention_text="相控阵雷达",
                        start_char=0,
                        end_char=5,
                        confidence=0.96,
                        model_version="lightrag.5-multi-v1",
                        ontology_version="defense-kg-1.0",
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=source_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=second_block_id,
                        mention_text="相控阵雷达",
                        start_char=10,
                        end_char=15,
                        confidence=0.91,
                        model_version="lightrag-defense-v1",
                        ontology_version="defense-kg-1.0",
                        review_status="accepted",
                    ),
                    KnowledgeGraphEntityMention(
                        entity_id=pending_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=block_id,
                        mention_text="待审核技术",
                        start_char=6,
                        end_char=11,
                        confidence=0.62,
                        review_status="pending",
                    ),
                ]
            )
            session.add_all(
                [
                    KnowledgeGraphTriple(
                        triple_id=triple_id,
                        kb_id=kb_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relation_type="ENABLES_CAPABILITY",
                        content="相控阵雷达提升探测能力",
                    ),
                    KnowledgeGraphTriple(
                        triple_id=hypothesis_id,
                        kb_id=kb_id,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relation_type="POTENTIAL_FOR",
                        content="相控阵雷达可能支持探测能力",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphTripleMention(
                        triple_id=triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=block_id,
                        text="相控阵雷达提升探测能力",
                        extractor_type="lightrag_primary",
                        claim_level="Fact",
                        confidence=0.93,
                        evidence_quote="相控阵雷达在完成阵列校准后提升探测能力",
                        evidence_spans=[{"start": 0, "end": 21}],
                        reasoning_basis="原文直接陈述",
                        applicable_conditions=["完成阵列校准"],
                        uncertainty="未覆盖未校准状态",
                        expert_review_required=False,
                        review_status="accepted",
                        model_version="lightrag.5-multi-v1",
                        ontology_version="defense-kg-1.0",
                        pipeline_revision="hybrid-v2-r1",
                    ),
                    KnowledgeGraphTripleMention(
                        triple_id=triple_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=second_block_id,
                        text="相控阵雷达可以提升探测能力",
                        extractor_type="lightrag_primary",
                        claim_level="Inference",
                        confidence=0.88,
                        evidence_quote="另一组试验证据表明相控阵雷达可以提升探测能力",
                        evidence_spans=[{"start": 10, "end": 25}],
                        reasoning_basis="多组试验证据归纳",
                        applicable_conditions=["另一组试验条件"],
                        uncertainty="试验条件仍需复现",
                        expert_review_required=False,
                        review_status="accepted",
                        model_version="lightrag-defense-v1",
                        ontology_version="defense-kg-1.0",
                        pipeline_revision="hybrid-v2-r1",
                    ),
                    KnowledgeGraphTripleMention(
                        triple_id=hypothesis_id,
                        kb_id=kb_id,
                        file_id=file_id,
                        chunk_id=block_id,
                        text="相控阵雷达可能支持探测能力",
                        claim_level="Hypothesis",
                        confidence=0.71,
                        evidence_spans=[{"start": 0, "end": 21}],
                        review_status="accepted",
                    ),
                ]
            )
            session.add(
                KnowledgeGraphRevision(
                    revision_id=revision_id,
                    kb_id=kb_id,
                    ontology_version="defense-kg-1.0",
                    reason="query_api_test",
                    summary={"triple_id": triple_id},
                    created_by=user.uid,
                )
            )
            session.add(
                KnowledgeGraphChangeEvent(
                    event_id=event_id,
                    kb_id=kb_id,
                    graph_revision=revision_id,
                    event_type="relation_reviewed",
                    target_type="relation",
                    target_id=triple_id,
                    before_payload={"review_status": "pending"},
                    after_payload={"review_status": "accepted"},
                    reason="expert review",
                    source_ref={"mention_id": "1"},
                    created_by=user.uid,
                )
            )

        headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(user_id)})}"}
        unauthorized = await test_client.get(f"/api/graph/databases/{kb_id}/entities/{source_id}")
        assert unauthorized.status_code == 401

        entity_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/entities/{source_id}",
            params={"evidence_limit": 1},
            headers=headers,
        )
        assert entity_response.status_code == 200, entity_response.text
        entity = entity_response.json()["data"]
        assert entity["entity"]["entity_id"] == source_id
        assert entity["aliases"][0]["alias"] == "Phased Array Radar"
        assert entity["evidence_count"] == 2
        assert len(entity["evidence"]) == 1
        assert entity["evidence"][0]["location"]["page"] == 4
        assert entity["evidence"][0]["document_id"] == document_id

        pending_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/entities/{pending_id}",
            headers=headers,
        )
        assert pending_response.status_code == 404

        relation_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/relations/{triple_id}",
            params={"evidence_limit": 1},
            headers=headers,
        )
        assert relation_response.status_code == 200, relation_response.text
        relation = relation_response.json()["data"]
        assert relation["relation"]["type"] == "ENABLES_CAPABILITY"
        assert relation["evidence_count"] == 2
        assert len(relation["evidence"]) == 1
        assert relation["claim_levels"] == ["Fact", "Inference"]
        assert relation["applicable_conditions"] == ["另一组试验条件", "完成阵列校准"]
        assert relation["evidence"][0]["evidence_text"].startswith("另一组试验证据")

        hypothesis_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/relations/{hypothesis_id}",
            headers=headers,
        )
        assert hypothesis_response.status_code == 404

        revisions_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/revisions",
            headers=headers,
        )
        assert revisions_response.status_code == 200, revisions_response.text
        assert revisions_response.json()["data"]["items"][0]["revision_id"] == revision_id

        changes_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/changes",
            params={"graph_revision": revision_id, "target_type": "relation", "target_id": triple_id},
            headers=headers,
        )
        assert changes_response.status_code == 200, changes_response.text
        changes = changes_response.json()["data"]
        assert changes["count"] == 1
        assert changes["items"][0]["event_id"] == event_id
    finally:
        async with pg_manager.get_async_session_context() as session:
            await session.execute(delete(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if user_id is not None:
                await session.execute(delete(OperationLog).where(OperationLog.user_id == user_id))
                await session.execute(delete(User).where(User.id == user_id))
