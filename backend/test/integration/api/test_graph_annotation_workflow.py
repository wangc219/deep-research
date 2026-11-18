from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeGraphAnnotationCampaign,
    KnowledgeSourceDocument,
)
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_graph_annotation_http_workflow_isolates_drafts_and_exports_adjudicated_gold(
    test_client,
):
    suffix = uuid.uuid4().hex[:10]
    kb_id = f"ann-kb-{suffix}"
    file_id = f"ann-file-{suffix}"
    document_id = f"ann-doc-{suffix}"
    block_id = f"ann-block-{suffix}"
    campaign_id = None
    user_ids = []
    try:
        async with pg_manager.get_async_session_context() as session:
            department_id = await session.scalar(select(Department.id).order_by(Department.id.asc()).limit(1))
            assert department_id is not None, "集成测试需要至少一个已存在部门"
            users = [
                User(
                    username=f"pytest_ann_admin_{suffix}",
                    uid=f"pytest-ann-admin-{suffix}",
                    password_hash="disabled-test-login",
                    role="superadmin",
                    department_id=department_id,
                ),
                User(
                    username=f"pytest_ann_user_{suffix}",
                    uid=f"pytest-ann-user-{suffix}",
                    password_hash="disabled-test-login",
                    role="user",
                    department_id=department_id,
                ),
                User(
                    username=f"pytest_ann_expert_{suffix}",
                    uid=f"pytest-ann-expert-{suffix}",
                    password_hash="disabled-test-login",
                    role="user",
                    department_id=department_id,
                ),
            ]
            session.add_all(users)
            await session.flush()
            user_ids = [user.id for user in users]
            admin, annotator, expert = users
            session.add(
                KnowledgeBase(
                    kb_id=kb_id,
                    name=f"pytest_annotation_{suffix}",
                    kb_type="milvus",
                    created_by=admin.uid,
                    share_config={
                        "version": 2,
                        "read_scope": {"access_level": "user", "user_uids": [admin.uid]},
                        "manage_scope": None,
                    },
                )
            )
            await session.flush()
            session.add(
                KnowledgeFile(
                    file_id=file_id,
                    kb_id=kb_id,
                    filename="annotation-paper.pdf",
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
                    source_metadata={"title": "相控阵雷达能力论文"},
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
                    content="相控阵雷达提升探测能力。",
                    document_version=1,
                    page_number=1,
                    block_type="paragraph",
                    heading_path=["系统设计"],
                )
            )

        admin_uid = admin.uid
        annotator_uid = annotator.uid
        expert_uid = expert.uid
        admin_headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(admin.id)})}"}
        annotator_headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(annotator.id)})}"}
        expert_headers = {"Authorization": f"Bearer {AuthUtils.create_access_token({'sub': str(expert.id)})}"}

        invalid_participant = await test_client.post(
            f"/api/graph/databases/{kb_id}/annotation-campaigns",
            json={
                "name": f"pytest-invalid-participant-{suffix}",
                "guideline_version": "defense-kg-annotation-v1",
                "ontology_version": "defense-kg-1.0",
                "pilot_mode": False,
                "assignments": [
                    {
                        "document_id": document_id,
                        "document_version": 1,
                        "split": "train",
                        "annotator_ids": [admin_uid, annotator_uid],
                        "arbitrator_id": f"missing-expert-{suffix}",
                    }
                ],
            },
            headers=admin_headers,
        )
        assert invalid_participant.status_code == 422
        assert "不存在或已删除" in invalid_participant.text

        create_response = await test_client.post(
            f"/api/graph/databases/{kb_id}/annotation-campaigns",
            json={
                "name": f"pytest-campaign-{suffix}",
                "guideline_version": "defense-kg-annotation-v1",
                "ontology_version": "defense-kg-1.0",
                "pilot_mode": False,
                "assignments": [
                    {
                        "document_id": document_id,
                        "document_version": 1,
                        "split": "train",
                        "annotator_ids": [admin_uid, annotator_uid],
                        "arbitrator_id": expert_uid,
                    }
                ],
            },
            headers=admin_headers,
        )
        assert create_response.status_code == 200, create_response.text
        campaign_id = create_response.json()["data"]["campaign_id"]

        standard_campaigns = await test_client.get(
            f"/api/graph/databases/{kb_id}/annotation-campaigns",
            headers=annotator_headers,
        )
        assert standard_campaigns.status_code == 403

        admin_tasks = await test_client.get(
            f"/api/graph/databases/{kb_id}/annotation-assignments/mine",
            params={"campaign_id": campaign_id},
            headers=admin_headers,
        )
        assert admin_tasks.status_code == 200, admin_tasks.text
        assignment_id = admin_tasks.json()["data"]["items"][0]["assignment_id"]
        initial_payload = _gold_payload(document_id, block_id)

        first_submit = await test_client.post(
            f"/api/graph/databases/{kb_id}/annotation-assignments/{assignment_id}/submissions",
            json={"payload": initial_payload},
            headers=admin_headers,
        )
        assert first_submit.status_code == 200, first_submit.text
        assert first_submit.json()["data"]["revision"] == 1

        expert_before = await test_client.get(
            f"/api/graph/databases/{kb_id}/annotation-assignments/{assignment_id}",
            headers=expert_headers,
        )
        assert expert_before.status_code == 200, expert_before.text
        assert expert_before.json()["data"]["submissions"] == []
        assert expert_before.json()["data"]["difference"] is None

        second_payload = _gold_payload(document_id, block_id)
        second_payload["entities"][0]["canonical_entity_id"] = "canonical-tech-b"
        second_submit = await test_client.post(
            f"/api/graph/databases/{kb_id}/annotation-assignments/{assignment_id}/submissions",
            json={"payload": second_payload},
            headers=annotator_headers,
        )
        assert second_submit.status_code == 200, second_submit.text
        assert second_submit.json()["data"]["assignment_status"] == "awaiting_adjudication"

        expert_after = await test_client.get(
            f"/api/graph/databases/{kb_id}/annotation-assignments/{assignment_id}",
            headers=expert_headers,
        )
        assert expert_after.status_code == 200, expert_after.text
        expert_data = expert_after.json()["data"]
        assert len(expert_data["submissions"]) == 2
        assert expert_data["difference"]["agreement"] is False

        adjudication = await test_client.post(
            f"/api/graph/databases/{kb_id}/annotation-assignments/{assignment_id}/adjudication",
            json={"payload": initial_payload},
            headers=expert_headers,
        )
        assert adjudication.status_code == 200, adjudication.text
        assert adjudication.json()["data"]["campaign_status"] == "completed"

        export_response = await test_client.get(
            f"/api/graph/databases/{kb_id}/annotation-campaigns/{campaign_id}/export",
            headers=admin_headers,
        )
        assert export_response.status_code == 200, export_response.text
        exported = export_response.json()["data"]
        assert exported["document_count"] == 1
        assert len(exported["sha256"]) == 64
        provenance = exported["documents"][0]["annotation"]
        assert provenance["annotator_ids"] == [admin_uid, annotator_uid]
        assert provenance["arbitrator_id"] == expert_uid
        assert provenance["adjudicated"] is True
    finally:
        async with pg_manager.get_async_session_context() as session:
            if campaign_id:
                await session.execute(
                    delete(KnowledgeGraphAnnotationCampaign).where(
                        KnowledgeGraphAnnotationCampaign.campaign_id == campaign_id
                    )
                )
            await session.execute(delete(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            if user_ids:
                await session.execute(delete(User).where(User.id.in_(user_ids)))


def _gold_payload(document_id: str, block_id: str) -> dict:
    return {
        "document_id": document_id,
        "title": "相控阵雷达能力论文",
        "split": "train",
        "language": "zh",
        "source_type": "paper",
        "domain": "radar",
        "source_version": "1",
        "blocks": [{"block_id": block_id, "text": "相控阵雷达提升探测能力。", "page": 1}],
        "entities": [
            {
                "entity_id": "e1",
                "block_id": block_id,
                "type": "KeyTechnology",
                "text": "相控阵雷达",
                "start": 0,
                "end": 5,
                "canonical_entity_id": "canonical-tech-a",
            },
            {
                "entity_id": "e2",
                "block_id": block_id,
                "type": "Capability",
                "text": "探测能力",
                "start": 7,
                "end": 11,
                "canonical_entity_id": "canonical-capability",
            },
        ],
        "relations": [
            {
                "relation_id": "r1",
                "type": "ENABLES_CAPABILITY",
                "source_entity_id": "e1",
                "target_entity_id": "e2",
                "evidence_block_ids": [block_id],
                "evidence_spans": [
                    {
                        "block_id": block_id,
                        "start": 0,
                        "end": 11,
                        "text": "相控阵雷达提升探测能力",
                    }
                ],
                "applicable_conditions": ["完成阵列校准"],
                "claim_level": "Fact",
            }
        ],
    }
