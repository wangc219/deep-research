"""双人独立标注活动、提交版本与专家仲裁的 PostgreSQL 仓储。"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select

from platform_core.knowledge.training.annotation_workflow import AnnotationCampaignSpec
from platform_core.knowledge.training.pilot_coverage import pilot_coverage_blockers
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgeFile,
    KnowledgeGraphAnnotationAdjudication,
    KnowledgeGraphAnnotationAssignment,
    KnowledgeGraphAnnotationCampaign,
    KnowledgeGraphAnnotationDraft,
    KnowledgeGraphAnnotationSubmission,
    KnowledgeSourceDocument,
)


class KnowledgeGraphAnnotationRepository:
    """集中维护双标活动的事务、角色分配和 append-only 版本。"""

    async def create_campaign(
        self,
        *,
        kb_id: str,
        spec: AnnotationCampaignSpec,
        created_by: str,
    ) -> dict[str, Any]:
        """在单一事务内校验来源版本并创建活动及全部任务。"""
        document_ids = [item.document_id for item in spec.assignments]
        participant_uids = sorted(
            {uid for assignment in spec.assignments for uid in [*assignment.annotator_ids, assignment.arbitrator_id]}
        )
        async with pg_manager.get_async_session_context() as session:
            active_uids = set(
                await session.scalars(
                    select(User.uid).where(
                        User.uid.in_(participant_uids),
                        User.is_deleted == 0,
                    )
                )
            )
            missing_participants = sorted(set(participant_uids) - active_uids)
            if missing_participants:
                raise ValueError(f"以下标注参与者不存在或已删除: {missing_participants}")

            documents = (
                await session.execute(
                    select(KnowledgeSourceDocument).where(
                        KnowledgeSourceDocument.kb_id == kb_id,
                        KnowledgeSourceDocument.document_id.in_(document_ids),
                    )
                )
            ).scalars()
            document_by_id = {item.document_id: item for item in documents}
            missing_documents = sorted(set(document_ids) - set(document_by_id))
            if missing_documents:
                raise ValueError(f"以下来源文档不存在或不属于知识库: {missing_documents}")
            if spec.pilot_mode:
                coverage_blockers = pilot_coverage_blockers(
                    source_types={str(item.source_type) for item in document_by_id.values()},
                    languages={str(item.language) for item in document_by_id.values()},
                    domains={str(item.domain) for item in document_by_id.values() if str(item.domain)},
                    acceptance_languages=spec.acceptance_languages,
                )
                if coverage_blockers:
                    raise ValueError(f"Pilot 标注文档覆盖不足: {coverage_blockers}")

            version_conditions = [
                (KnowledgeDocumentVersion.document_id == item.document_id)
                & (KnowledgeDocumentVersion.version == item.document_version)
                for item in spec.assignments
            ]
            versions = (
                await session.execute(select(KnowledgeDocumentVersion).where(or_(*version_conditions)))
            ).scalars()
            version_keys = {(item.document_id, item.version) for item in versions}
            missing_versions = sorted(
                (item.document_id, item.document_version)
                for item in spec.assignments
                if (item.document_id, item.document_version) not in version_keys
            )
            if missing_versions:
                raise ValueError(f"以下不可变文档版本不存在: {missing_versions}")

            block_rows = (
                await session.execute(
                    select(
                        KnowledgeChunk.file_id,
                        KnowledgeChunk.document_version,
                        func.count(KnowledgeChunk.id),
                    )
                    .where(
                        KnowledgeChunk.file_id.in_([item.file_id for item in document_by_id.values()]),
                    )
                    .group_by(KnowledgeChunk.file_id, KnowledgeChunk.document_version)
                )
            ).all()
            block_counts = {(file_id, version): int(count) for file_id, version, count in block_rows}
            missing_blocks = [
                (item.document_id, item.document_version)
                for item in spec.assignments
                if not block_counts.get((document_by_id[item.document_id].file_id, item.document_version))
            ]
            if missing_blocks:
                raise ValueError(f"以下文档版本尚无可标注 Block: {missing_blocks}")

            campaign_id = uuid.uuid4().hex
            campaign = KnowledgeGraphAnnotationCampaign(
                campaign_id=campaign_id,
                kb_id=kb_id,
                name=spec.name,
                guideline_version=spec.guideline_version,
                ontology_version=spec.ontology_version,
                pilot_mode=spec.pilot_mode,
                acceptance_languages=spec.acceptance_languages,
                status="active",
                created_by=created_by,
            )
            session.add(campaign)
            await session.flush()
            session.add_all(
                [
                    KnowledgeGraphAnnotationAssignment(
                        assignment_id=uuid.uuid4().hex,
                        campaign_id=campaign_id,
                        document_id=item.document_id,
                        document_version=item.document_version,
                        split=item.split,
                        annotator_a_uid=item.annotator_ids[0],
                        annotator_b_uid=item.annotator_ids[1],
                        arbitrator_uid=item.arbitrator_id,
                        status="assigned",
                    )
                    for item in spec.assignments
                ]
            )
            await session.flush()
            return _campaign_payload(campaign, assignment_count=len(spec.assignments))

    async def list_campaigns(self, kb_id: str) -> list[dict[str, Any]]:
        """返回知识库内活动及权威任务进度。"""
        async with pg_manager.get_async_session_context() as session:
            campaigns = list(
                await session.scalars(
                    select(KnowledgeGraphAnnotationCampaign)
                    .where(KnowledgeGraphAnnotationCampaign.kb_id == kb_id)
                    .order_by(KnowledgeGraphAnnotationCampaign.created_at.desc())
                )
            )
            counts = (
                await session.execute(
                    select(
                        KnowledgeGraphAnnotationAssignment.campaign_id,
                        KnowledgeGraphAnnotationAssignment.status,
                        KnowledgeGraphAnnotationAssignment.split,
                        func.count(),
                    )
                    .join(KnowledgeGraphAnnotationCampaign)
                    .where(KnowledgeGraphAnnotationCampaign.kb_id == kb_id)
                    .group_by(
                        KnowledgeGraphAnnotationAssignment.campaign_id,
                        KnowledgeGraphAnnotationAssignment.status,
                        KnowledgeGraphAnnotationAssignment.split,
                    )
                )
            ).all()

        by_campaign: dict[str, list[tuple[str, str, int]]] = {}
        for campaign_id, status, split, count in counts:
            by_campaign.setdefault(str(campaign_id), []).append((str(status), str(split), int(count)))
        return [
            _campaign_payload(campaign, progress=_progress_payload(by_campaign.get(campaign.campaign_id, [])))
            for campaign in campaigns
        ]

    async def list_user_assignments(
        self,
        *,
        kb_id: str,
        user_id: str,
        campaign_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """只列出当前用户被分配为标注员或仲裁专家的任务。"""
        role_filter = or_(
            KnowledgeGraphAnnotationAssignment.annotator_a_uid == user_id,
            KnowledgeGraphAnnotationAssignment.annotator_b_uid == user_id,
            KnowledgeGraphAnnotationAssignment.arbitrator_uid == user_id,
        )
        conditions = [KnowledgeGraphAnnotationCampaign.kb_id == kb_id, role_filter]
        if campaign_id:
            conditions.append(KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id)
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeGraphAnnotationAssignment,
                        KnowledgeGraphAnnotationCampaign,
                        KnowledgeSourceDocument,
                        KnowledgeFile,
                    )
                    .select_from(KnowledgeGraphAnnotationAssignment)
                    .join(
                        KnowledgeGraphAnnotationCampaign,
                        KnowledgeGraphAnnotationCampaign.campaign_id == KnowledgeGraphAnnotationAssignment.campaign_id,
                    )
                    .join(
                        KnowledgeSourceDocument,
                        KnowledgeSourceDocument.document_id == KnowledgeGraphAnnotationAssignment.document_id,
                    )
                    .join(KnowledgeFile, KnowledgeFile.file_id == KnowledgeSourceDocument.file_id)
                    .where(*conditions)
                    .order_by(KnowledgeGraphAnnotationAssignment.created_at.asc())
                )
            ).all()
            assignment_ids = [assignment.assignment_id for assignment, *_ in rows]
            drafts = (
                list(
                    await session.scalars(
                        select(KnowledgeGraphAnnotationDraft).where(
                            KnowledgeGraphAnnotationDraft.assignment_id.in_(assignment_ids),
                            KnowledgeGraphAnnotationDraft.annotator_uid == user_id,
                        )
                    )
                )
                if assignment_ids
                else []
            )
        draft_by_assignment = {draft.assignment_id: draft for draft in drafts}
        items = [
            _assignment_payload(assignment, campaign, document, file, user_id=user_id)
            for assignment, campaign, document, file in rows
        ]
        for item in items:
            draft = draft_by_assignment.get(item["assignment_id"])
            item["draft_available"] = draft is not None
            item["draft_submitted"] = bool(draft and draft.last_submitted_draft_sha256 == draft.payload_sha256)
            item["draft_updated_at"] = draft.updated_at.isoformat() if draft else None
        return items

    async def get_assignment(self, assignment_id: str) -> dict[str, Any] | None:
        """加载任务、固定来源版本及可逐字核对的权威 Block。"""
        async with pg_manager.get_async_session_context() as session:
            row = (
                await session.execute(
                    select(
                        KnowledgeGraphAnnotationAssignment,
                        KnowledgeGraphAnnotationCampaign,
                        KnowledgeSourceDocument,
                        KnowledgeFile,
                    )
                    .select_from(KnowledgeGraphAnnotationAssignment)
                    .join(
                        KnowledgeGraphAnnotationCampaign,
                        KnowledgeGraphAnnotationCampaign.campaign_id == KnowledgeGraphAnnotationAssignment.campaign_id,
                    )
                    .join(
                        KnowledgeSourceDocument,
                        KnowledgeSourceDocument.document_id == KnowledgeGraphAnnotationAssignment.document_id,
                    )
                    .join(KnowledgeFile, KnowledgeFile.file_id == KnowledgeSourceDocument.file_id)
                    .where(KnowledgeGraphAnnotationAssignment.assignment_id == assignment_id)
                )
            ).one_or_none()
            if row is None:
                return None
            assignment, campaign, document, file = row
            blocks = list(
                await session.scalars(
                    select(KnowledgeChunk)
                    .where(
                        KnowledgeChunk.file_id == document.file_id,
                        KnowledgeChunk.document_version == assignment.document_version,
                    )
                    .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.id.asc())
                )
            )
            payload = _assignment_payload(assignment, campaign, document, file)
            payload["blocks"] = [_block_payload(block) for block in blocks]
            return payload

    async def get_draft(self, *, assignment_id: str, annotator_uid: str) -> dict[str, Any] | None:
        """只读取指定标注员在该任务下的本人草稿。"""
        async with pg_manager.get_async_session_context() as session:
            draft = await session.scalar(
                select(KnowledgeGraphAnnotationDraft).where(
                    KnowledgeGraphAnnotationDraft.assignment_id == assignment_id,
                    KnowledgeGraphAnnotationDraft.annotator_uid == annotator_uid,
                )
            )
            return _draft_payload(draft) if draft else None

    async def list_drafts(
        self,
        *,
        kb_id: str,
        campaign_id: str,
        annotator_uid: str,
    ) -> list[dict[str, Any]]:
        """列出一个活动中当前标注员本人的持久草稿。"""
        async with pg_manager.get_async_session_context() as session:
            drafts = list(
                await session.scalars(
                    select(KnowledgeGraphAnnotationDraft)
                    .join(
                        KnowledgeGraphAnnotationAssignment,
                        KnowledgeGraphAnnotationAssignment.assignment_id == KnowledgeGraphAnnotationDraft.assignment_id,
                    )
                    .join(
                        KnowledgeGraphAnnotationCampaign,
                        KnowledgeGraphAnnotationCampaign.campaign_id == KnowledgeGraphAnnotationAssignment.campaign_id,
                    )
                    .where(
                        KnowledgeGraphAnnotationCampaign.kb_id == kb_id,
                        KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id,
                        KnowledgeGraphAnnotationDraft.annotator_uid == annotator_uid,
                    )
                    .order_by(KnowledgeGraphAnnotationAssignment.created_at.asc())
                )
            )
            return [_draft_payload(draft) for draft in drafts]

    async def save_draft(
        self,
        *,
        assignment_id: str,
        annotator_uid: str,
        annotation_payload: dict[str, Any],
        payload_sha256: str,
        source_kind: str,
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        """保存或更新本人工作草稿，不创建正式 revision。"""
        async with pg_manager.get_async_session_context() as session:
            assignment = await session.scalar(
                select(KnowledgeGraphAnnotationAssignment).where(
                    KnowledgeGraphAnnotationAssignment.assignment_id == assignment_id
                )
            )
            if assignment is None:
                raise LookupError("标注任务不存在")
            if annotator_uid not in {assignment.annotator_a_uid, assignment.annotator_b_uid}:
                raise PermissionError("当前用户不是该任务的指定标注员")
            if assignment.status == "completed":
                raise ValueError("任务已完成仲裁，不能继续修改草稿")

            draft = await session.scalar(
                select(KnowledgeGraphAnnotationDraft)
                .where(
                    KnowledgeGraphAnnotationDraft.assignment_id == assignment_id,
                    KnowledgeGraphAnnotationDraft.annotator_uid == annotator_uid,
                )
                .with_for_update()
            )
            if draft is None:
                draft = KnowledgeGraphAnnotationDraft(
                    draft_id=uuid.uuid4().hex,
                    assignment_id=assignment_id,
                    annotator_uid=annotator_uid,
                    annotation_payload=annotation_payload,
                    payload_sha256=payload_sha256,
                    source_kind=source_kind,
                    provenance=provenance,
                )
                session.add(draft)
            else:
                draft.annotation_payload = annotation_payload
                draft.payload_sha256 = payload_sha256
                draft.source_kind = source_kind
                draft.provenance = provenance
                draft.updated_at = datetime.now(UTC)
            await session.flush()
            return _draft_payload(draft)

    async def append_submission(
        self,
        *,
        assignment_id: str,
        annotator_uid: str,
        annotation_payload: dict[str, Any],
        payload_sha256: str,
        draft_payload_sha256: str | None = None,
    ) -> dict[str, Any]:
        """锁定任务并追加当前标注员的新 revision，绝不覆盖旧稿。"""
        async with pg_manager.get_async_session_context() as session:
            assignment = await session.scalar(
                select(KnowledgeGraphAnnotationAssignment)
                .where(KnowledgeGraphAnnotationAssignment.assignment_id == assignment_id)
                .with_for_update()
            )
            if assignment is None:
                raise LookupError("标注任务不存在")
            if annotator_uid not in {assignment.annotator_a_uid, assignment.annotator_b_uid}:
                raise PermissionError("当前用户不是该任务的指定标注员")
            if assignment.status == "completed":
                raise ValueError("任务已完成仲裁，不能继续追加初稿")
            latest_revision = await session.scalar(
                select(func.max(KnowledgeGraphAnnotationSubmission.revision)).where(
                    KnowledgeGraphAnnotationSubmission.assignment_id == assignment_id,
                    KnowledgeGraphAnnotationSubmission.annotator_uid == annotator_uid,
                )
            )
            revision = int(latest_revision or 0) + 1
            submission = KnowledgeGraphAnnotationSubmission(
                submission_id=uuid.uuid4().hex,
                assignment_id=assignment_id,
                annotator_uid=annotator_uid,
                revision=revision,
                annotation_payload=annotation_payload,
                payload_sha256=payload_sha256,
            )
            session.add(submission)
            await session.flush()

            if draft_payload_sha256:
                draft = await session.scalar(
                    select(KnowledgeGraphAnnotationDraft).where(
                        KnowledgeGraphAnnotationDraft.assignment_id == assignment_id,
                        KnowledgeGraphAnnotationDraft.annotator_uid == annotator_uid,
                        KnowledgeGraphAnnotationDraft.payload_sha256 == draft_payload_sha256,
                    )
                )
                if draft:
                    draft.last_submitted_draft_sha256 = draft_payload_sha256
                    draft.last_submitted_revision = revision
                    draft.last_submitted_at = datetime.now(UTC)

            submitted_roles = await session.scalar(
                select(func.count(func.distinct(KnowledgeGraphAnnotationSubmission.annotator_uid))).where(
                    KnowledgeGraphAnnotationSubmission.assignment_id == assignment_id,
                    KnowledgeGraphAnnotationSubmission.annotator_uid.in_(
                        [assignment.annotator_a_uid, assignment.annotator_b_uid]
                    ),
                )
            )
            assignment.status = "awaiting_adjudication" if int(submitted_roles or 0) == 2 else "annotating"
            await self._refresh_campaign_status(session, assignment.campaign_id)
            return {
                "submission_id": submission.submission_id,
                "assignment_id": assignment_id,
                "revision": revision,
                "payload_sha256": payload_sha256,
                "assignment_status": assignment.status,
            }

    async def bulk_append_submissions(
        self,
        *,
        campaign_id: str,
        annotator_uid: str,
        items: list[dict[str, Any]],
        expected_draft_count: int,
    ) -> dict[str, Any]:
        """在一个事务内把本人所有有变化的草稿追加为不可变 revision。"""
        async with pg_manager.get_async_session_context() as session:
            assignments = list(
                await session.scalars(
                    select(KnowledgeGraphAnnotationAssignment)
                    .where(KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id)
                    .with_for_update()
                )
            )
            assignment_by_id = {assignment.assignment_id: assignment for assignment in assignments}
            authorized_ids = {
                assignment.assignment_id
                for assignment in assignments
                if annotator_uid in {assignment.annotator_a_uid, assignment.annotator_b_uid}
                and assignment.status != "completed"
            }
            drafts = (
                list(
                    await session.scalars(
                        select(KnowledgeGraphAnnotationDraft)
                        .where(
                            KnowledgeGraphAnnotationDraft.assignment_id.in_(authorized_ids),
                            KnowledgeGraphAnnotationDraft.annotator_uid == annotator_uid,
                        )
                        .with_for_update()
                    )
                )
                if authorized_ids
                else []
            )
            eligible = {
                draft.assignment_id: draft
                for draft in drafts
                if draft.last_submitted_draft_sha256 != draft.payload_sha256
            }
            if len(eligible) != expected_draft_count:
                raise ValueError(f"可提交草稿数量已从 {expected_draft_count} 变为 {len(eligible)}，请刷新后再次确认")
            item_by_assignment = {str(item["assignment_id"]): item for item in items}
            if set(item_by_assignment) != set(eligible):
                raise ValueError("批量提交内容与当前可提交草稿不一致，请刷新后重试")

            revision_rows = (
                (
                    await session.execute(
                        select(
                            KnowledgeGraphAnnotationSubmission.assignment_id,
                            func.max(KnowledgeGraphAnnotationSubmission.revision),
                        )
                        .where(
                            KnowledgeGraphAnnotationSubmission.assignment_id.in_(eligible),
                            KnowledgeGraphAnnotationSubmission.annotator_uid == annotator_uid,
                        )
                        .group_by(KnowledgeGraphAnnotationSubmission.assignment_id)
                    )
                ).all()
                if eligible
                else []
            )
            latest_revision = {assignment_id: int(revision) for assignment_id, revision in revision_rows}
            submitted = []
            submitted_at = datetime.now(UTC)
            for assignment_id, draft in eligible.items():
                item = item_by_assignment[assignment_id]
                if item["draft_payload_sha256"] != draft.payload_sha256:
                    raise ValueError("草稿在批量校验期间发生变化，请重新确认")
                revision = latest_revision.get(assignment_id, 0) + 1
                submission = KnowledgeGraphAnnotationSubmission(
                    submission_id=uuid.uuid4().hex,
                    assignment_id=assignment_id,
                    annotator_uid=annotator_uid,
                    revision=revision,
                    annotation_payload=item["annotation_payload"],
                    payload_sha256=item["payload_sha256"],
                    submitted_at=submitted_at,
                )
                session.add(submission)
                draft.last_submitted_draft_sha256 = draft.payload_sha256
                draft.last_submitted_revision = revision
                draft.last_submitted_at = submitted_at
                submitted.append(
                    {
                        "assignment_id": assignment_id,
                        "submission_id": submission.submission_id,
                        "revision": revision,
                    }
                )
            await session.flush()

            submitted_role_rows = (
                (
                    await session.execute(
                        select(
                            KnowledgeGraphAnnotationSubmission.assignment_id,
                            func.count(func.distinct(KnowledgeGraphAnnotationSubmission.annotator_uid)),
                        )
                        .where(KnowledgeGraphAnnotationSubmission.assignment_id.in_(eligible))
                        .group_by(KnowledgeGraphAnnotationSubmission.assignment_id)
                    )
                ).all()
                if eligible
                else []
            )
            submitted_roles = {assignment_id: int(count) for assignment_id, count in submitted_role_rows}
            for assignment_id in eligible:
                assignment_by_id[assignment_id].status = (
                    "awaiting_adjudication" if submitted_roles.get(assignment_id, 0) == 2 else "annotating"
                )
            campaign_status = await self._refresh_campaign_status(session, campaign_id)
            return {
                "campaign_id": campaign_id,
                "submitted_count": len(submitted),
                "skipped_unchanged_count": len(drafts) - len(eligible),
                "campaign_status": campaign_status,
                "submissions": submitted,
            }

    async def get_latest_submissions(self, assignment_id: str) -> dict[str, dict[str, Any]]:
        """按标注员返回最新 revision；调用方负责角色隔离。"""
        async with pg_manager.get_async_session_context() as session:
            submissions = list(
                await session.scalars(
                    select(KnowledgeGraphAnnotationSubmission)
                    .where(KnowledgeGraphAnnotationSubmission.assignment_id == assignment_id)
                    .order_by(
                        KnowledgeGraphAnnotationSubmission.annotator_uid.asc(),
                        KnowledgeGraphAnnotationSubmission.revision.desc(),
                    )
                )
            )
        latest: dict[str, dict[str, Any]] = {}
        for submission in submissions:
            latest.setdefault(
                submission.annotator_uid,
                {
                    "submission_id": submission.submission_id,
                    "annotator_uid": submission.annotator_uid,
                    "revision": submission.revision,
                    "payload_sha256": submission.payload_sha256,
                    "submitted_at": submission.submitted_at.isoformat(),
                    "annotation_payload": submission.annotation_payload,
                },
            )
        return latest

    async def save_adjudication(
        self,
        *,
        assignment_id: str,
        arbitrator_uid: str,
        final_payload: dict[str, Any],
        payload_sha256: str,
        disagreement_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """保存唯一专家终稿并原子推进任务与活动状态。"""
        async with pg_manager.get_async_session_context() as session:
            assignment = await session.scalar(
                select(KnowledgeGraphAnnotationAssignment)
                .where(KnowledgeGraphAnnotationAssignment.assignment_id == assignment_id)
                .with_for_update()
            )
            if assignment is None:
                raise LookupError("标注任务不存在")
            if arbitrator_uid != assignment.arbitrator_uid:
                raise PermissionError("当前用户不是该任务的指定仲裁专家")
            existing = await session.scalar(
                select(KnowledgeGraphAnnotationAdjudication.adjudication_id).where(
                    KnowledgeGraphAnnotationAdjudication.assignment_id == assignment_id
                )
            )
            if existing is not None:
                raise ValueError("该任务已经完成专家仲裁，终稿不可覆盖")
            submitted_roles = await session.scalar(
                select(func.count(func.distinct(KnowledgeGraphAnnotationSubmission.annotator_uid))).where(
                    KnowledgeGraphAnnotationSubmission.assignment_id == assignment_id,
                    KnowledgeGraphAnnotationSubmission.annotator_uid.in_(
                        [assignment.annotator_a_uid, assignment.annotator_b_uid]
                    ),
                )
            )
            if int(submitted_roles or 0) != 2:
                raise ValueError("两名标注员尚未都提交独立初稿，不能保存仲裁终稿")

            adjudication = KnowledgeGraphAnnotationAdjudication(
                adjudication_id=uuid.uuid4().hex,
                assignment_id=assignment_id,
                arbitrator_uid=arbitrator_uid,
                final_payload=final_payload,
                payload_sha256=payload_sha256,
                disagreement_summary=disagreement_summary,
            )
            session.add(adjudication)
            assignment.status = "completed"
            await session.flush()
            campaign_status = await self._refresh_campaign_status(session, assignment.campaign_id)
            return {
                "adjudication_id": adjudication.adjudication_id,
                "assignment_id": assignment_id,
                "payload_sha256": payload_sha256,
                "assignment_status": "completed",
                "campaign_status": campaign_status,
            }

    async def export_adjudicated_gold(self, campaign_id: str) -> list[dict[str, Any]]:
        """仅在全部任务完成后导出按文档排序的仲裁金标。"""
        async with pg_manager.get_async_session_context() as session:
            campaign = await session.get(KnowledgeGraphAnnotationCampaign, campaign_id)
            if campaign is None:
                raise LookupError("标注活动不存在")
            if campaign.status not in {"completed", "sealed"}:
                raise ValueError("标注活动尚未全部完成，禁止导出不完整金标")
            rows = (
                await session.execute(
                    select(
                        KnowledgeGraphAnnotationAssignment.document_id,
                        KnowledgeGraphAnnotationAdjudication.final_payload,
                    )
                    .join(
                        KnowledgeGraphAnnotationAdjudication,
                        KnowledgeGraphAnnotationAdjudication.assignment_id
                        == KnowledgeGraphAnnotationAssignment.assignment_id,
                    )
                    .where(KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id)
                    .order_by(KnowledgeGraphAnnotationAssignment.document_id.asc())
                )
            ).all()
            assignment_count = await session.scalar(
                select(func.count()).where(KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id)
            )
            if len(rows) != int(assignment_count or 0):
                raise ValueError("仲裁终稿数量与任务数量不一致，禁止导出")
            return [dict(payload) for _, payload in rows]

    async def _refresh_campaign_status(self, session, campaign_id: str) -> str:
        campaign = await session.get(KnowledgeGraphAnnotationCampaign, campaign_id)
        statuses = list(
            await session.scalars(
                select(KnowledgeGraphAnnotationAssignment.status).where(
                    KnowledgeGraphAnnotationAssignment.campaign_id == campaign_id
                )
            )
        )
        if statuses and all(status == "completed" for status in statuses):
            campaign.status = "completed"
        elif any(status in {"awaiting_adjudication", "adjudicating"} for status in statuses):
            campaign.status = "adjudicating"
        else:
            campaign.status = "active"
        return campaign.status


def _campaign_payload(
    campaign: KnowledgeGraphAnnotationCampaign,
    *,
    assignment_count: int | None = None,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "campaign_id": campaign.campaign_id,
        "kb_id": campaign.kb_id,
        "name": campaign.name,
        "guideline_version": campaign.guideline_version,
        "ontology_version": campaign.ontology_version,
        "pilot_mode": campaign.pilot_mode,
        "acceptance_languages": list(campaign.acceptance_languages or []),
        "status": campaign.status,
        "created_by": campaign.created_by,
        "created_at": campaign.created_at.isoformat(),
        "updated_at": campaign.updated_at.isoformat(),
    }
    if assignment_count is not None:
        result["assignment_count"] = assignment_count
    if progress is not None:
        result["progress"] = progress
    return result


def _assignment_payload(
    assignment: KnowledgeGraphAnnotationAssignment,
    campaign: KnowledgeGraphAnnotationCampaign,
    document: KnowledgeSourceDocument,
    file: KnowledgeFile,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    role = None
    if user_id in {assignment.annotator_a_uid, assignment.annotator_b_uid}:
        role = "annotator"
    elif user_id == assignment.arbitrator_uid:
        role = "arbitrator"
    metadata = dict(document.source_metadata or {})
    return {
        "assignment_id": assignment.assignment_id,
        "campaign_id": assignment.campaign_id,
        "kb_id": campaign.kb_id,
        "campaign_name": campaign.name,
        "guideline_version": campaign.guideline_version,
        "ontology_version": campaign.ontology_version,
        "document_id": assignment.document_id,
        "document_version": assignment.document_version,
        "split": assignment.split,
        "status": assignment.status,
        "role": role,
        "annotator_ids": [assignment.annotator_a_uid, assignment.annotator_b_uid],
        "arbitrator_id": assignment.arbitrator_uid,
        "title": str(metadata.get("title") or file.original_filename or file.filename),
        "language": document.language,
        "source_type": document.source_type,
        "domain": document.domain,
        "created_at": assignment.created_at.isoformat(),
        "updated_at": assignment.updated_at.isoformat(),
    }


def _block_payload(block: KnowledgeChunk) -> dict[str, Any]:
    return {
        "block_id": block.chunk_id,
        "text": block.content,
        "page": block.page_number,
        "block_type": block.block_type,
        "heading_path": block.heading_path or [],
        "bbox": block.bbox,
        "start_char": block.start_char_pos,
        "end_char": block.end_char_pos,
        "parser": block.parser_name,
        "parser_version": block.parser_version,
    }


def _draft_payload(draft: KnowledgeGraphAnnotationDraft) -> dict[str, Any]:
    return {
        "draft_id": draft.draft_id,
        "assignment_id": draft.assignment_id,
        "annotator_uid": draft.annotator_uid,
        "annotation_payload": draft.annotation_payload,
        "payload_sha256": draft.payload_sha256,
        "source_kind": draft.source_kind,
        "provenance": draft.provenance or {},
        "submitted": draft.last_submitted_draft_sha256 == draft.payload_sha256,
        "last_submitted_revision": draft.last_submitted_revision,
        "last_submitted_at": draft.last_submitted_at.isoformat() if draft.last_submitted_at else None,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def _progress_payload(rows: list[tuple[str, str, int]]) -> dict[str, Any]:
    by_status = Counter()
    by_split = Counter()
    for status, split, count in rows:
        by_status[status] += count
        by_split[split] += count
    total = sum(by_status.values())
    completed = by_status.get("completed", 0)
    return {
        "total": total,
        "completed": completed,
        "completion_rate": completed / total if total else 0.0,
        "by_status": dict(sorted(by_status.items())),
        "by_split": {split: by_split.get(split, 0) for split in ("train", "dev", "test")},
    }
