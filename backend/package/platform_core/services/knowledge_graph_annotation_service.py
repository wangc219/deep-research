"""双标隔离、原文校验、本体约束与专家仲裁应用服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from platform_core.knowledge.training.annotation_workflow import (
    AnnotationCampaignSpec,
    compare_independent_annotations,
)
from platform_core.knowledge.training.gold_contract import (
    GoldAnnotationProvenance,
    GoldDocument,
)
from platform_core.repositories.knowledge_graph_annotation_repository import (
    KnowledgeGraphAnnotationRepository,
)
from platform_core.repositories.user_repository import UserRepository
from platform_core.services.knowledge_graph_governance_service import KnowledgeGraphGovernanceService


class KnowledgeGraphAnnotationService:
    """执行不可绕过的角色隔离、权威 Block 和金标质量规则。"""

    def __init__(
        self,
        repository: KnowledgeGraphAnnotationRepository | None = None,
        governance_service: KnowledgeGraphGovernanceService | None = None,
        user_repository: UserRepository | None = None,
    ):
        self.repository = repository or KnowledgeGraphAnnotationRepository()
        self.governance_service = governance_service or KnowledgeGraphGovernanceService()
        self.user_repository = user_repository or UserRepository()

    async def create_campaign(
        self,
        *,
        kb_id: str,
        spec: AnnotationCampaignSpec,
        created_by: str,
    ) -> dict[str, Any]:
        """验证固定本体后创建一个不可跨文档切分的双标活动。"""
        await self._validate_active_participants(spec)
        ontology = await self.governance_service.get_ontology(spec.ontology_version)
        if ontology.get("version") != spec.ontology_version:
            raise ValueError("本体版本解析结果与活动指定版本不一致")
        return await self.repository.create_campaign(kb_id=kb_id, spec=spec, created_by=created_by)

    async def list_campaigns(self, kb_id: str) -> list[dict[str, Any]]:
        """返回活动与 train/dev/test 权威进度。"""
        return await self.repository.list_campaigns(kb_id)

    async def list_user_campaigns(self, *, kb_id: str, user_id: str) -> list[dict[str, Any]]:
        """只返回当前账号实际参与的标注活动。"""
        assignments = await self.repository.list_user_assignments(kb_id=kb_id, user_id=user_id)
        visible_campaign_ids = {item["campaign_id"] for item in assignments}
        campaigns = await self.repository.list_campaigns(kb_id)
        return [item for item in campaigns if item["campaign_id"] in visible_campaign_ids]

    async def list_user_assignments(
        self,
        *,
        kb_id: str,
        user_id: str,
        campaign_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """只返回当前用户本人被分配的标注或仲裁任务。"""
        return await self.repository.list_user_assignments(
            kb_id=kb_id,
            user_id=user_id,
            campaign_id=campaign_id,
        )

    async def get_assignment(
        self,
        *,
        kb_id: str,
        assignment_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """按当前用户角色返回任务，双方提交前绝不泄露另一份初稿。"""
        assignment = await self._get_authorized_assignment(kb_id, assignment_id, user_id)
        latest = await self.repository.get_latest_submissions(assignment_id)
        both_submitted = all(user in latest for user in assignment["annotator_ids"])
        role = _role_for_user(assignment, user_id)
        response = _public_assignment(assignment, role=role)
        response["both_submitted"] = both_submitted

        if both_submitted:
            left = GoldDocument.model_validate(latest[assignment["annotator_ids"][0]]["annotation_payload"])
            right = GoldDocument.model_validate(latest[assignment["annotator_ids"][1]]["annotation_payload"])
            response["submissions"] = [_public_submission(latest[user]) for user in assignment["annotator_ids"]]
            response["difference"] = compare_independent_annotations(left, right)
        elif role == "annotator" and user_id in latest:
            response["submissions"] = [_public_submission(latest[user_id])]
            response["difference"] = None
        else:
            response["submissions"] = []
            response["difference"] = None
        response["draft"] = (
            await self.repository.get_draft(assignment_id=assignment_id, annotator_uid=user_id)
            if role == "annotator"
            else None
        )
        return response

    async def save_annotation_draft(
        self,
        *,
        kb_id: str,
        assignment_id: str,
        user_id: str,
        payload: dict[str, Any],
        source_kind: str = "manual",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """校验并保存本人可修改草稿，但不生成正式 revision。"""
        assignment = await self._get_authorized_assignment(kb_id, assignment_id, user_id)
        if _role_for_user(assignment, user_id) != "annotator":
            raise PermissionError("只有任务指定标注员可以保存工作草稿")
        if source_kind not in {"ai_prelabel", "manual"}:
            raise ValueError("草稿 source_kind 必须是 ai_prelabel 或 manual")
        provenance = dict(provenance or {})
        if source_kind == "ai_prelabel":
            _validate_ai_draft_provenance(provenance, user_id)

        document = GoldDocument.model_validate(payload)
        document.annotation = None
        self._validate_authoritative_document(document, assignment)
        ontology = await self.governance_service.get_ontology(assignment["ontology_version"])
        self._validate_ontology(document, ontology, final=False)
        normalized = document.model_dump(mode="json")
        return await self.repository.save_draft(
            assignment_id=assignment_id,
            annotator_uid=user_id,
            annotation_payload=normalized,
            payload_sha256=_canonical_sha256(normalized),
            source_kind=source_kind,
            provenance=provenance,
        )

    async def submit_annotation(
        self,
        *,
        kb_id: str,
        assignment_id: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """由指定标注员追加不可变初稿 revision。"""
        assignment = await self._get_authorized_assignment(kb_id, assignment_id, user_id)
        if _role_for_user(assignment, user_id) != "annotator":
            raise PermissionError("只有任务指定的两名标注员可以提交独立初稿")
        if assignment["status"] == "completed":
            raise ValueError("任务已经完成仲裁，不能继续追加初稿")

        document = GoldDocument.model_validate(payload)
        document.annotation = None
        self._validate_authoritative_document(document, assignment)
        ontology = await self.governance_service.get_ontology(assignment["ontology_version"])
        self._validate_ontology(document, ontology, final=False)
        draft_payload = document.model_dump(mode="json")
        existing_draft = await self.repository.get_draft(
            assignment_id=assignment_id,
            annotator_uid=user_id,
        )
        draft = await self.repository.save_draft(
            assignment_id=assignment_id,
            annotator_uid=user_id,
            annotation_payload=draft_payload,
            payload_sha256=_canonical_sha256(draft_payload),
            source_kind=existing_draft["source_kind"] if existing_draft else "manual",
            provenance=existing_draft["provenance"] if existing_draft else {},
        )
        document.annotation = GoldAnnotationProvenance(
            annotator_ids=[user_id],
            adjudicated=False,
            guideline_version=assignment["guideline_version"],
            completed_at=datetime.now(UTC),
        )
        normalized = document.model_dump(mode="json")
        return await self.repository.append_submission(
            assignment_id=assignment_id,
            annotator_uid=user_id,
            annotation_payload=normalized,
            payload_sha256=_canonical_sha256(normalized),
            draft_payload_sha256=draft["payload_sha256"],
        )

    async def bulk_submit_annotations(
        self,
        *,
        kb_id: str,
        campaign_id: str,
        user_id: str,
        expected_draft_count: int,
    ) -> dict[str, Any]:
        """以一次显式确认提交活动内本人所有有变化草稿。"""
        campaigns = await self.repository.list_campaigns(kb_id)
        campaign = next((item for item in campaigns if item["campaign_id"] == campaign_id), None)
        if campaign is None:
            raise LookupError("标注活动不存在或不属于该知识库")
        drafts = await self.repository.list_drafts(
            kb_id=kb_id,
            campaign_id=campaign_id,
            annotator_uid=user_id,
        )
        eligible = [draft for draft in drafts if not draft["submitted"]]
        if len(eligible) != expected_draft_count:
            raise ValueError(f"可提交草稿数量已从 {expected_draft_count} 变为 {len(eligible)}，请刷新后再次确认")
        if not eligible:
            raise ValueError("当前活动没有尚未提交或已发生变化的本人草稿")

        completed_at = datetime.now(UTC)
        items = []
        ontology = None
        for draft in eligible:
            assignment = await self._get_authorized_assignment(kb_id, draft["assignment_id"], user_id)
            if _role_for_user(assignment, user_id) != "annotator":
                raise PermissionError("批量提交只允许处理当前用户的独立标注任务")
            document = GoldDocument.model_validate(draft["annotation_payload"])
            document.annotation = None
            self._validate_authoritative_document(document, assignment)
            if ontology is None:
                ontology = await self.governance_service.get_ontology(assignment["ontology_version"])
            self._validate_ontology(document, ontology, final=False)
            document.annotation = GoldAnnotationProvenance(
                annotator_ids=[user_id],
                adjudicated=False,
                guideline_version=assignment["guideline_version"],
                completed_at=completed_at,
            )
            normalized = document.model_dump(mode="json")
            items.append(
                {
                    "assignment_id": assignment["assignment_id"],
                    "draft_payload_sha256": draft["payload_sha256"],
                    "annotation_payload": normalized,
                    "payload_sha256": _canonical_sha256(normalized),
                }
            )
        return await self.repository.bulk_append_submissions(
            campaign_id=campaign_id,
            annotator_uid=user_id,
            items=items,
            expected_draft_count=expected_draft_count,
        )

    async def adjudicate(
        self,
        *,
        kb_id: str,
        assignment_id: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """仅允许指定第三人基于两份初稿写入唯一金标终稿。"""
        assignment = await self._get_authorized_assignment(kb_id, assignment_id, user_id)
        if _role_for_user(assignment, user_id) != "arbitrator":
            raise PermissionError("只有任务指定的第三名仲裁专家可以提交终稿")
        latest = await self.repository.get_latest_submissions(assignment_id)
        if not all(annotator in latest for annotator in assignment["annotator_ids"]):
            raise ValueError("两名标注员尚未都提交独立初稿，不能开始仲裁")

        document = GoldDocument.model_validate(payload)
        self._validate_authoritative_document(document, assignment)
        ontology = await self.governance_service.get_ontology(assignment["ontology_version"])
        self._validate_ontology(document, ontology, final=True)
        document.annotation = GoldAnnotationProvenance(
            annotator_ids=list(assignment["annotator_ids"]),
            arbitrator_id=user_id,
            adjudicated=True,
            guideline_version=assignment["guideline_version"],
            completed_at=datetime.now(UTC),
        )
        normalized = document.model_dump(mode="json")
        left = GoldDocument.model_validate(latest[assignment["annotator_ids"][0]]["annotation_payload"])
        right = GoldDocument.model_validate(latest[assignment["annotator_ids"][1]]["annotation_payload"])
        difference = compare_independent_annotations(left, right)
        return await self.repository.save_adjudication(
            assignment_id=assignment_id,
            arbitrator_uid=user_id,
            final_payload=normalized,
            payload_sha256=_canonical_sha256(normalized),
            disagreement_summary=difference,
        )

    async def export_campaign(
        self,
        *,
        kb_id: str,
        campaign_id: str,
    ) -> dict[str, Any]:
        """导出完成仲裁且再次通过统一契约校验的 GoldDocument 数组。"""
        campaigns = await self.repository.list_campaigns(kb_id)
        campaign = next((item for item in campaigns if item["campaign_id"] == campaign_id), None)
        if campaign is None:
            raise LookupError("标注活动不存在或不属于该知识库")
        payloads = await self.repository.export_adjudicated_gold(campaign_id)
        documents = [GoldDocument.model_validate(payload) for payload in payloads]
        export_payload = [item.model_dump(mode="json") for item in documents]
        return {
            "campaign_id": campaign_id,
            "kb_id": kb_id,
            "document_count": len(export_payload),
            "documents": export_payload,
            "sha256": _canonical_sha256(export_payload),
        }

    async def _get_authorized_assignment(
        self,
        kb_id: str,
        assignment_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        assignment = await self.repository.get_assignment(assignment_id)
        if assignment is None or assignment["kb_id"] != kb_id:
            raise LookupError("标注任务不存在")
        if _role_for_user(assignment, user_id) is None:
            raise PermissionError("当前用户不是该任务的标注员或仲裁专家")
        if not assignment["blocks"]:
            raise ValueError("任务固定的文档版本没有可标注 Block")
        return assignment

    async def _validate_active_participants(self, spec: AnnotationCampaignSpec) -> None:
        """拒绝不存在或已软删除的标注员和仲裁专家账号。"""
        requested_uids = sorted(
            {uid for assignment in spec.assignments for uid in [*assignment.annotator_ids, assignment.arbitrator_id]}
        )
        users = await self.user_repository.list_active_by_uids(requested_uids)
        active_uids = {str(user.uid) for user in users}
        missing = sorted(set(requested_uids) - active_uids)
        if missing:
            raise ValueError(f"以下标注参与者不存在或已删除: {missing}")

    @staticmethod
    def _validate_authoritative_document(document: GoldDocument, assignment: dict[str, Any]) -> None:
        if document.document_id != assignment["document_id"]:
            raise ValueError("提交 document_id 与任务不一致")
        if document.split != assignment["split"]:
            raise ValueError("提交 split 与任务固定切分不一致")
        if document.source_version != str(assignment["document_version"]):
            raise ValueError("提交 source_version 与任务固定文档版本不一致")
        if document.language != assignment["language"]:
            raise ValueError("提交 language 与来源文档不一致")
        if document.source_type != assignment["source_type"]:
            raise ValueError("提交 source_type 与来源文档不一致")
        if document.domain != assignment["domain"]:
            raise ValueError("提交 domain 与来源文档不一致")

        authoritative = [
            {"block_id": block["block_id"], "text": block["text"], "page": block["page"]}
            for block in assignment["blocks"]
        ]
        submitted = [block.model_dump(mode="json") for block in document.blocks]
        if submitted != authoritative:
            raise ValueError("提交的 Block、顺序或原文与 PostgreSQL 权威文档版本不一致")

    @staticmethod
    def _validate_ontology(document: GoldDocument, ontology: dict[str, Any], *, final: bool) -> None:
        entity_types = {item["code"] for item in ontology.get("entity_types") or []}
        relation_types = {item["code"]: item for item in ontology.get("relation_types") or []}
        entity_by_id = {item.entity_id: item for item in document.entities}
        for entity in document.entities:
            if entity.type not in entity_types:
                raise ValueError(f"实体 {entity.entity_id} 使用了本体外类型 {entity.type}")
            if final and not entity.canonical_entity_id:
                raise ValueError(f"仲裁终稿实体 {entity.entity_id} 缺少 canonical_entity_id")

        for relation in document.relations:
            definition = relation_types.get(relation.type)
            if definition is None:
                raise ValueError(f"关系 {relation.relation_id} 使用了本体外类型 {relation.type}")
            source = entity_by_id[relation.source_entity_id]
            target = entity_by_id[relation.target_entity_id]
            if source.type not in definition["head_types"] or target.type not in definition["tail_types"]:
                raise ValueError(f"关系 {relation.relation_id} 的起止实体类型违反本体约束")
            if source.entity_id == target.entity_id and not definition.get("allow_self", False):
                raise ValueError(f"关系 {relation.relation_id} 不允许自环")
            if definition.get("hypothesis_only") and relation.claim_level != "Hypothesis":
                raise ValueError(f"探索性关系 {relation.relation_id} 必须标记为 Hypothesis")
            evidence_blocks = {span.block_id for span in relation.evidence_spans}
            if not evidence_blocks.issubset(set(relation.evidence_block_ids)):
                raise ValueError(f"关系 {relation.relation_id} 的 evidence_block_ids 未覆盖全部证据 Span")
            if relation.claim_level == "Fact" and not relation.evidence_spans:
                raise ValueError(f"Fact 关系 {relation.relation_id} 必须包含可回切证据 Span")


def _role_for_user(assignment: dict[str, Any], user_id: str) -> str | None:
    if user_id in assignment["annotator_ids"]:
        return "annotator"
    if user_id == assignment["arbitrator_id"]:
        return "arbitrator"
    return None


def _public_assignment(assignment: dict[str, Any], *, role: str) -> dict[str, Any]:
    return {key: value for key, value in assignment.items() if key not in {"annotator_ids", "arbitrator_id"}} | {
        "role": role
    }


def _public_submission(submission: dict[str, Any]) -> dict[str, Any]:
    return {
        "submission_id": submission["submission_id"],
        "annotator_uid": submission["annotator_uid"],
        "revision": submission["revision"],
        "payload_sha256": submission["payload_sha256"],
        "submitted_at": submission["submitted_at"],
        "annotation_payload": submission["annotation_payload"],
    }


def _canonical_sha256(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_ai_draft_provenance(provenance: dict[str, Any], user_id: str) -> None:
    if (
        provenance.get("annotation_kind") != "ai_prelabel"
        or provenance.get("formal_gold_eligible") is not False
        or provenance.get("human_confirmed") is not False
    ):
        raise ValueError("AI 草稿缺少不可冒充真人提交的谱系标记")
    if str(provenance.get("intended_human_reviewer") or "") != user_id:
        raise PermissionError("AI 草稿不属于当前登录标注员")
