from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.knowledge.training.annotation_workflow import AnnotationAssignmentSpec, AnnotationCampaignSpec
from platform_core.services.knowledge_graph_annotation_service import KnowledgeGraphAnnotationService

pytestmark = pytest.mark.asyncio


class _Governance:
    async def get_ontology(self, version: str):
        definition = ontology_payload()
        assert definition["version"] == version
        return definition


class _Repository:
    def __init__(self):
        self.assignment = _assignment()
        self.latest = {}
        self.appended = None
        self.adjudicated = None
        self.campaign = None
        self.draft = None

    async def create_campaign(self, **kwargs):
        self.campaign = kwargs
        return {"campaign_id": "campaign"}

    async def get_assignment(self, assignment_id: str):
        return deepcopy(self.assignment) if assignment_id == "assignment" else None

    async def get_latest_submissions(self, assignment_id: str):
        assert assignment_id == "assignment"
        return deepcopy(self.latest)

    async def get_draft(self, **kwargs):
        return deepcopy(self.draft)

    async def save_draft(self, **kwargs):
        self.draft = {
            "payload_sha256": "d" * 64,
            "source_kind": kwargs["source_kind"],
            "provenance": kwargs["provenance"],
            "annotation_payload": kwargs["annotation_payload"],
        }
        return deepcopy(self.draft)

    async def append_submission(self, **kwargs):
        self.appended = kwargs
        return {"revision": 1, "assignment_status": "annotating"}

    async def save_adjudication(self, **kwargs):
        self.adjudicated = kwargs
        return {"assignment_status": "completed", "campaign_status": "completed"}

    async def list_campaigns(self, kb_id: str):
        return [{"campaign_id": "campaign", "kb_id": kb_id}]

    async def list_drafts(self, **kwargs):
        return [deepcopy(self.draft)] if self.draft else []

    async def bulk_append_submissions(self, **kwargs):
        self.bulk_appended = kwargs
        return {"submitted_count": len(kwargs["items"]), "skipped_unchanged_count": 0}



class _UserRepository:
    def __init__(self, active_uids: set[str]):
        self.active_uids = active_uids

    async def list_active_by_uids(self, uids: list[str]):
        return [SimpleNamespace(uid=uid) for uid in uids if uid in self.active_uids]


async def test_campaign_requires_real_active_participant_accounts():
    repository = _Repository()
    spec = AnnotationCampaignSpec(
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
    )
    incomplete_users = _UserRepository({"ann-a", "expert"})
    service = KnowledgeGraphAnnotationService(
        repository=repository,
        governance_service=_Governance(),
        user_repository=incomplete_users,
    )

    with pytest.raises(ValueError, match="不存在或已删除"):
        await service.create_campaign(kb_id="kb", spec=spec, created_by="owner")
    assert repository.campaign is None

    service = KnowledgeGraphAnnotationService(
        repository=repository,
        governance_service=_Governance(),
        user_repository=_UserRepository({"ann-a", "ann-b", "expert"}),
    )
    result = await service.create_campaign(kb_id="kb", spec=spec, created_by="owner")

    assert result == {"campaign_id": "campaign"}
    assert repository.campaign["spec"] is spec


async def test_assignment_hides_other_draft_until_both_submit():
    repository = _Repository()
    repository.latest = {"ann-a": _submission("ann-a", _gold_document())}
    service = KnowledgeGraphAnnotationService(repository=repository, governance_service=_Governance())

    annotator_view = await service.get_assignment(
        kb_id="kb",
        assignment_id="assignment",
        user_id="ann-a",
    )
    arbitrator_view = await service.get_assignment(
        kb_id="kb",
        assignment_id="assignment",
        user_id="expert",
    )

    assert [item["annotator_uid"] for item in annotator_view["submissions"]] == ["ann-a"]
    assert annotator_view["difference"] is None
    assert arbitrator_view["submissions"] == []
    assert "annotator_ids" not in annotator_view
    assert "arbitrator_id" not in annotator_view


async def test_assignment_exposes_deterministic_difference_after_both_submit():
    repository = _Repository()
    left = _gold_document()
    right = _gold_document()
    right["entities"][0]["canonical_entity_id"] = "canonical-other"
    repository.latest = {
        "ann-a": _submission("ann-a", left),
        "ann-b": _submission("ann-b", right),
    }
    service = KnowledgeGraphAnnotationService(repository=repository, governance_service=_Governance())

    result = await service.get_assignment(kb_id="kb", assignment_id="assignment", user_id="expert")

    assert result["both_submitted"] is True
    assert len(result["submissions"]) == 2
    assert result["difference"]["agreement"] is False
    assert result["difference"]["disagreement_count"] == 4


async def test_submission_rejects_modified_authoritative_block_and_normalizes_provenance():
    repository = _Repository()
    service = KnowledgeGraphAnnotationService(repository=repository, governance_service=_Governance())
    modified = _gold_document()
    modified["blocks"][0]["text"] = "相控阵雷达提升探测能力。附注"

    with pytest.raises(ValueError, match="权威文档版本"):
        await service.submit_annotation(
            kb_id="kb",
            assignment_id="assignment",
            user_id="ann-a",
            payload=modified,
        )

    await service.submit_annotation(
        kb_id="kb",
        assignment_id="assignment",
        user_id="ann-a",
        payload=_gold_document(),
    )

    annotation = repository.appended["annotation_payload"]["annotation"]
    assert annotation["annotator_ids"] == ["ann-a"]
    assert annotation["adjudicated"] is False
    assert annotation["guideline_version"] == "defense-kg-annotation-v1"
    assert len(repository.appended["payload_sha256"]) == 64


async def test_only_third_expert_can_adjudicate_and_final_requires_canonical_entities():
    repository = _Repository()
    repository.latest = {
        "ann-a": _submission("ann-a", _gold_document()),
        "ann-b": _submission("ann-b", _gold_document()),
    }
    service = KnowledgeGraphAnnotationService(repository=repository, governance_service=_Governance())

    with pytest.raises(PermissionError, match="第三名"):
        await service.adjudicate(
            kb_id="kb",
            assignment_id="assignment",
            user_id="ann-a",
            payload=_gold_document(),
        )

    missing_canonical = _gold_document()
    missing_canonical["entities"][0]["canonical_entity_id"] = None
    with pytest.raises(ValueError, match="canonical_entity_id"):
        await service.adjudicate(
            kb_id="kb",
            assignment_id="assignment",
            user_id="expert",
            payload=missing_canonical,
        )

    await service.adjudicate(
        kb_id="kb",
        assignment_id="assignment",
        user_id="expert",
        payload=_gold_document(),
    )

    final = repository.adjudicated["final_payload"]
    assert final["annotation"]["annotator_ids"] == ["ann-a", "ann-b"]
    assert final["annotation"]["arbitrator_id"] == "expert"
    assert final["annotation"]["adjudicated"] is True
    assert repository.adjudicated["disagreement_summary"]["agreement"] is True


async def test_bulk_submission_uses_one_confirmation_count_without_per_document_review_state():
    repository = _Repository()
    repository.draft = {
        "assignment_id": "assignment",
        "annotation_payload": _gold_document(),
        "payload_sha256": "d" * 64,
        "source_kind": "ai_prelabel",
        "provenance": {
            "annotation_kind": "ai_prelabel",
            "formal_gold_eligible": False,
            "human_confirmed": False,
            "intended_human_reviewer": "ann-a",
        },
        "submitted": False,
    }
    service = KnowledgeGraphAnnotationService(repository=repository, governance_service=_Governance())

    result = await service.bulk_submit_annotations(
        kb_id="kb",
        campaign_id="campaign",
        user_id="ann-a",
        expected_draft_count=1,
    )

    assert result["submitted_count"] == 1
    assert repository.bulk_appended["expected_draft_count"] == 1
    submitted = repository.bulk_appended["items"][0]["annotation_payload"]
    assert submitted["annotation"]["annotator_ids"] == ["ann-a"]
    assert submitted["annotation"]["adjudicated"] is False


def _assignment():
    return {
        "assignment_id": "assignment",
        "campaign_id": "campaign",
        "kb_id": "kb",
        "campaign_name": "Pilot",
        "guideline_version": "defense-kg-annotation-v1",
        "ontology_version": "defense-kg-1.0",
        "document_id": "doc",
        "document_version": 1,
        "split": "train",
        "status": "annotating",
        "annotator_ids": ["ann-a", "ann-b"],
        "arbitrator_id": "expert",
        "title": "文档",
        "language": "zh",
        "source_type": "paper",
        "domain": "radar",
        "blocks": [
            {
                "block_id": "block-1",
                "text": "相控阵雷达提升探测能力。",
                "page": 1,
                "block_type": "paragraph",
                "heading_path": ["系统设计"],
                "bbox": [0, 0, 10, 10],
                "start_char": 0,
                "end_char": 13,
                "parser": "native-pdf",
                "parser_version": "1",
            }
        ],
    }


def _gold_document():
    return {
        "document_id": "doc",
        "title": "文档",
        "split": "train",
        "language": "zh",
        "source_type": "paper",
        "domain": "radar",
        "source_version": "1",
        "blocks": [{"block_id": "block-1", "text": "相控阵雷达提升探测能力。", "page": 1}],
        "entities": [
            {
                "entity_id": "e1",
                "block_id": "block-1",
                "type": "KeyTechnology",
                "text": "相控阵雷达",
                "start": 0,
                "end": 5,
                "canonical_entity_id": "canonical-tech",
            },
            {
                "entity_id": "e2",
                "block_id": "block-1",
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
                "evidence_block_ids": ["block-1"],
                "evidence_spans": [
                    {
                        "block_id": "block-1",
                        "start": 0,
                        "end": 11,
                        "text": "相控阵雷达提升探测能力",
                    }
                ],
                "claim_level": "Fact",
            }
        ],
    }


def _submission(user_id: str, payload: dict):
    return {
        "submission_id": f"sub-{user_id}",
        "annotator_uid": user_id,
        "revision": 1,
        "payload_sha256": user_id.ljust(64, "0"),
        "submitted_at": "2026-10-30T00:00:00+00:00",
        "annotation_payload": payload,
    }
