"""本体注册与人工审核的 PostgreSQL 仓储。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from platform_core.knowledge.graphs.ontology_versioning import normalize_ontology_definition
from platform_core.knowledge.graphs.projection_contract import build_review_projection_event
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphConflict,
    KnowledgeGraphProjectionOutbox,
    KnowledgeGraphReviewDecision,
    KnowledgeGraphRevision,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    OntologyEntityType,
    OntologyRelationType,
    OntologyVersion,
)

REVIEW_DECISIONS = {"accepted", "rejected", "disputed", "superseded"}
REVIEW_TARGETS = {"entity_mention", "relation_mention"}
CONFLICT_TARGETS = REVIEW_TARGETS | {"entity", "relation"}
CONFLICT_STATUSES = {"open", "resolved", "dismissed", "superseded"}
CONFLICT_SEVERITIES = {"low", "medium", "high", "critical"}


def _serialize_ontology_version(
    record: OntologyVersion,
    *,
    include_definition: bool = True,
) -> dict[str, Any]:
    """序列化本体版本，避免 ORM 对象越过仓储边界。"""
    payload = {
        "version": record.version,
        "name": record.name,
        "status": record.status,
        "previous_version": record.previous_version,
        "change_reason": record.change_reason,
        "created_by": record.created_by,
        "effective_at": record.effective_at.isoformat() if record.effective_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "entity_type_count": len((record.definition or {}).get("entity_types") or []),
        "relation_type_count": len((record.definition or {}).get("relation_types") or []),
    }
    if include_definition:
        payload["definition"] = dict(record.definition)
    return payload


class KnowledgeGraphGovernanceRepository:
    """集中维护本体快照与不可变审核日志。"""

    async def register_ontology(
        self,
        definition: dict[str, Any],
        *,
        created_by: str | None = None,
        previous_version: str | None = None,
        change_reason: str = "初始军事武器装备技术本体",
        effective_at: datetime | None = None,
    ) -> str:
        """幂等注册一个不可静默覆盖的本体版本。"""
        definition = normalize_ontology_definition(definition)
        version = str(definition["version"])
        change_reason = change_reason.strip()
        if not change_reason:
            raise ValueError("本体版本变更原因不能为空")
        if previous_version == version:
            raise ValueError("本体版本不能以前述自身作为前序版本")
        effective_at = effective_at or datetime.now(UTC)
        async with pg_manager.get_async_session_context() as session:
            existing = await session.get(OntologyVersion, version)
            if existing is not None:
                if existing.definition != definition:
                    raise ValueError(f"本体版本 {version} 已存在且定义不同，必须创建新版本")
                if existing.previous_version != previous_version or existing.change_reason != change_reason:
                    raise ValueError(f"本体版本 {version} 已存在且版本元数据不同，禁止静默覆盖")
                if existing.effective_at is None:
                    existing.effective_at = effective_at
                return version

            if previous_version is not None and await session.get(OntologyVersion, previous_version) is None:
                raise LookupError(f"前序本体版本不存在: {previous_version}")

            session.add(
                OntologyVersion(
                    version=version,
                    name=str(definition["name"]),
                    definition=definition,
                    status="active",
                    previous_version=previous_version,
                    change_reason=change_reason,
                    created_by=created_by,
                    effective_at=effective_at,
                )
            )
            await session.flush()
            session.add_all(
                [
                    OntologyEntityType(
                        ontology_version=version,
                        code=item["code"],
                        name_zh=item["name_zh"],
                        description=item.get("description") or "",
                        definition=item,
                    )
                    for item in definition["entity_types"]
                ]
            )
            session.add_all(
                [
                    OntologyRelationType(
                        ontology_version=version,
                        code=item["code"],
                        name_zh=item["name_zh"],
                        description=item.get("description") or "",
                        head_types=item["head_types"],
                        tail_types=item["tail_types"],
                        directed=bool(item.get("directed", True)),
                        allow_self=bool(item.get("allow_self", False)),
                        hypothesis_only=bool(item.get("hypothesis_only", False)),
                        definition=item,
                    )
                    for item in definition["relation_types"]
                ]
            )
        return version

    async def get_ontology(self, version: str) -> dict[str, Any] | None:
        """读取已注册的完整本体快照。"""
        async with pg_manager.get_async_session_context() as session:
            record = await session.get(OntologyVersion, version)
            return dict(record.definition) if record is not None else None

    async def get_ontology_version(self, version: str) -> dict[str, Any] | None:
        """读取本体快照及其版本治理元数据。"""
        async with pg_manager.get_async_session_context() as session:
            record = await session.get(OntologyVersion, version)
            return _serialize_ontology_version(record) if record is not None else None

    async def list_ontology_versions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """按生效时间倒序列出不可变本体版本。"""
        async with pg_manager.get_async_session_context() as session:
            records = (
                await session.scalars(
                    select(OntologyVersion)
                    .order_by(OntologyVersion.effective_at.desc().nullslast(), OntologyVersion.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [_serialize_ontology_version(record, include_definition=False) for record in records]

    async def list_review_queue(
        self,
        *,
        kb_id: str,
        status: str = "pending",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """返回带原文证据的实体与关系列表。"""
        async with pg_manager.get_async_session_context() as session:
            entity_rows = (
                await session.execute(
                    select(
                        KnowledgeGraphEntityMention,
                        KnowledgeGraphEntity,
                        KnowledgeChunk,
                    )
                    .join(
                        KnowledgeGraphEntity,
                        KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityMention.entity_id,
                    )
                    .join(KnowledgeChunk, KnowledgeChunk.chunk_id == KnowledgeGraphEntityMention.chunk_id)
                    .where(
                        KnowledgeGraphEntityMention.kb_id == kb_id,
                        KnowledgeGraphEntityMention.review_status == status,
                    )
                    .order_by(KnowledgeGraphEntityMention.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            remaining = max(limit - len(entity_rows), 0)
            source_entity = aliased(KnowledgeGraphEntity)
            target_entity = aliased(KnowledgeGraphEntity)
            relation_rows = []
            if remaining:
                relation_rows = (
                    await session.execute(
                        select(
                            KnowledgeGraphTripleMention,
                            KnowledgeGraphTriple,
                            source_entity.name,
                            target_entity.name,
                            KnowledgeChunk,
                        )
                        .join(
                            KnowledgeGraphTriple,
                            KnowledgeGraphTriple.triple_id == KnowledgeGraphTripleMention.triple_id,
                        )
                        .join(source_entity, source_entity.entity_id == KnowledgeGraphTriple.source_entity_id)
                        .join(target_entity, target_entity.entity_id == KnowledgeGraphTriple.target_entity_id)
                        .join(KnowledgeChunk, KnowledgeChunk.chunk_id == KnowledgeGraphTripleMention.chunk_id)
                        .where(
                            KnowledgeGraphTripleMention.kb_id == kb_id,
                            KnowledgeGraphTripleMention.review_status == status,
                        )
                        .order_by(KnowledgeGraphTripleMention.id.asc())
                        .limit(remaining)
                    )
                ).all()

        items = [
            {
                "target_type": "entity_mention",
                "target_id": str(mention.id),
                "entity_id": entity.entity_id,
                "entity_type": entity.label,
                "standard_name": entity.name,
                "mention_text": mention.mention_text,
                "alignment": _entity_alignment_metadata(entity.attributes),
                "confidence": mention.confidence,
                "model_version": mention.model_version,
                "ontology_version": mention.ontology_version,
                "review_status": mention.review_status,
                "chunk_id": mention.chunk_id,
                "file_id": mention.file_id,
                "evidence_text": chunk.content,
                "evidence_spans": [{"start": mention.start_char, "end": mention.end_char}],
                "evidence_location": _chunk_evidence_location(chunk),
            }
            for mention, entity, chunk in entity_rows
        ]
        items.extend(
            {
                "target_type": "relation_mention",
                "target_id": str(mention.id),
                "triple_id": triple.triple_id,
                "source_name": source_name,
                "target_name": target_name,
                "relation_type": triple.relation_type,
                "claim_level": mention.claim_level,
                "confidence": mention.confidence,
                "model_version": mention.model_version,
                "ontology_version": mention.ontology_version,
                "review_status": mention.review_status,
                "chunk_id": mention.chunk_id,
                "file_id": mention.file_id,
                "evidence_text": chunk.content,
                "evidence_quote": mention.evidence_quote,
                "evidence_spans": mention.evidence_spans or [],
                "reasoning_basis": mention.reasoning_basis,
                "applicable_conditions": mention.applicable_conditions or [],
                "secondary_review": mention.secondary_review,
                "uncertainty": mention.uncertainty,
                "evidence_location": _chunk_evidence_location(chunk),
            }
            for mention, triple, source_name, target_name, chunk in relation_rows
        )
        return items

    async def decide(
        self,
        *,
        kb_id: str,
        target_type: str,
        target_id: str,
        decision: str,
        reviewer_uid: str,
        reason: str = "",
        decided_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """锁定候选、更新审核状态并写入不可变决定。"""
        if target_type not in REVIEW_TARGETS:
            raise ValueError(f"不支持的审核目标: {target_type}")
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"不支持的审核决定: {decision}")
        try:
            mention_id = int(target_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("target_id 必须是 mention 数字 ID") from exc

        model = KnowledgeGraphEntityMention if target_type == "entity_mention" else KnowledgeGraphTripleMention
        async with pg_manager.get_async_session_context() as session:
            mention = await session.scalar(
                select(model).where(model.id == mention_id, model.kb_id == kb_id).with_for_update()
            )
            if mention is None:
                raise LookupError("审核目标不存在")
            previous_payload = {
                "review_status": mention.review_status,
                "confidence": mention.confidence,
            }
            mention.review_status = decision
            await self._invalidate_review_vectors(
                session,
                kb_id=kb_id,
                target_type=target_type,
                mention=mention,
            )
            decision_id = uuid.uuid4().hex
            session.add(
                KnowledgeGraphReviewDecision(
                    decision_id=decision_id,
                    kb_id=kb_id,
                    target_type=target_type,
                    target_id=target_id,
                    decision=decision,
                    previous_payload=previous_payload,
                    decided_payload=decided_payload,
                    reason=reason,
                    reviewer_uid=reviewer_uid,
                )
            )
            conflict_id = None
            if decision == "disputed":
                conflict = await self._register_conflict_in_session(
                    session,
                    kb_id=kb_id,
                    conflict_type="review_dispute",
                    left_target_type=target_type,
                    left_target_id=target_id,
                    right_target_type=None,
                    right_target_id=None,
                    severity="medium",
                    summary=reason or "人工审核将候选标记为有争议",
                    details={
                        "review_decision_id": decision_id,
                        "previous_payload": previous_payload,
                        "decided_payload": decided_payload,
                    },
                    detected_by=reviewer_uid,
                )
                conflict_id = conflict.conflict_id
            else:
                await self._close_target_conflicts_in_session(
                    session,
                    kb_id=kb_id,
                    target_type=target_type,
                    target_id=target_id,
                    decision=decision,
                    resolution=reason,
                    resolved_by=reviewer_uid,
                )
            projection_event = build_review_projection_event(
                kb_id=kb_id,
                chunk_id=mention.chunk_id,
                target_type=target_type,
                entity_id=mention.entity_id if target_type == "entity_mention" else None,
                triple_id=mention.triple_id if target_type == "relation_mention" else None,
                review_status=decision,
                decision_id=decision_id,
                ontology_version=mention.ontology_version,
            )
            session.add(
                KnowledgeGraphRevision(
                    revision_id=projection_event["graph_revision"],
                    kb_id=kb_id,
                    ontology_version=projection_event["ontology_version"],
                    reason=projection_event["reason"],
                    summary=projection_event["summary"],
                    created_by=reviewer_uid,
                )
            )
            session.add(
                KnowledgeGraphProjectionOutbox(
                    event_id=projection_event["event_id"],
                    kb_id=kb_id,
                    chunk_id=mention.chunk_id,
                    graph_revision=projection_event["graph_revision"],
                    payload=projection_event["payload"],
                    status="pending",
                )
            )
        return {
            "decision_id": decision_id,
            "target_type": target_type,
            "target_id": target_id,
            "review_status": decision,
            "projection_event_id": projection_event["event_id"],
            "conflict_id": conflict_id,
        }

    @staticmethod
    async def _invalidate_review_vectors(session, *, kb_id: str, target_type: str, mention) -> None:
        """审核改变权威语义后重建受影响向量及对应 Chunk 完成状态。"""
        entity_ids: set[str] = set()
        triple_ids: set[str] = set()
        if target_type == "entity_mention":
            entity_ids.add(str(mention.entity_id))
        else:
            triple_id = str(mention.triple_id)
            triple_ids.add(triple_id)
            triple = await session.scalar(
                select(KnowledgeGraphTriple).where(
                    KnowledgeGraphTriple.kb_id == kb_id,
                    KnowledgeGraphTriple.triple_id == triple_id,
                )
            )
            if triple is not None:
                entity_ids.update((str(triple.source_entity_id), str(triple.target_entity_id)))

        reset_values = {
            "vector_status": "pending",
            "vector_attempt_count": 0,
            "vector_last_error": None,
            "vector_next_retry_at": None,
            "vector_locked_until": None,
            "vector_lock_token": None,
            "updated_at": func.now(),
        }
        if entity_ids:
            await session.execute(
                update(KnowledgeGraphEntity)
                .where(
                    KnowledgeGraphEntity.kb_id == kb_id,
                    KnowledgeGraphEntity.entity_id.in_(entity_ids),
                    KnowledgeGraphEntity.lifecycle_status == "active",
                )
                .values(**reset_values)
            )
        if triple_ids:
            await session.execute(
                update(KnowledgeGraphTriple)
                .where(
                    KnowledgeGraphTriple.kb_id == kb_id,
                    KnowledgeGraphTriple.triple_id.in_(triple_ids),
                    KnowledgeGraphTriple.lifecycle_status == "active",
                )
                .values(**reset_values)
            )

        affected_chunks = []
        if entity_ids:
            affected_chunks.append(
                KnowledgeChunk.chunk_id.in_(
                    select(KnowledgeGraphEntityMention.chunk_id).where(
                        KnowledgeGraphEntityMention.kb_id == kb_id,
                        KnowledgeGraphEntityMention.entity_id.in_(entity_ids),
                    )
                )
            )
        if triple_ids:
            affected_chunks.append(
                KnowledgeChunk.chunk_id.in_(
                    select(KnowledgeGraphTripleMention.chunk_id).where(
                        KnowledgeGraphTripleMention.kb_id == kb_id,
                        KnowledgeGraphTripleMention.triple_id.in_(triple_ids),
                    )
                )
            )
        if affected_chunks:
            await session.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.kb_id == kb_id, or_(*affected_chunks))
                .values(graph_indexed=False)
            )

    async def register_conflict(
        self,
        *,
        kb_id: str,
        conflict_type: str,
        left_target_type: str,
        left_target_id: str,
        right_target_type: str | None,
        right_target_id: str | None,
        severity: str,
        summary: str,
        details: dict[str, Any] | None,
        detected_by: str,
    ) -> dict[str, Any]:
        """幂等登记一个人工或自动检测出的冲突。"""
        _validate_conflict_input(
            left_target_type=left_target_type,
            left_target_id=left_target_id,
            right_target_type=right_target_type,
            right_target_id=right_target_id,
            severity=severity,
            summary=summary,
        )
        async with pg_manager.get_async_session_context() as session:
            conflict = await self._register_conflict_in_session(
                session,
                kb_id=kb_id,
                conflict_type=conflict_type,
                left_target_type=left_target_type,
                left_target_id=left_target_id,
                right_target_type=right_target_type,
                right_target_id=right_target_id,
                severity=severity,
                summary=summary,
                details=details or {},
                detected_by=detected_by,
            )
            await session.flush()
            result = _serialize_conflict(conflict)
        return result

    async def list_conflicts(
        self,
        *,
        kb_id: str,
        status: str = "open",
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """读取冲突治理队列。"""
        if status not in CONFLICT_STATUSES:
            raise ValueError(f"不支持的冲突状态: {status}")
        if severity is not None and severity not in CONFLICT_SEVERITIES:
            raise ValueError(f"不支持的冲突严重度: {severity}")
        conditions = [KnowledgeGraphConflict.kb_id == kb_id, KnowledgeGraphConflict.status == status]
        if severity is not None:
            conditions.append(KnowledgeGraphConflict.severity == severity)
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeGraphConflict)
                    .where(*conditions)
                    .order_by(KnowledgeGraphConflict.created_at.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return [_serialize_conflict(row) for row in rows]

    async def resolve_conflict(
        self,
        *,
        kb_id: str,
        conflict_id: str,
        status: str,
        resolution: str,
        resolved_by: str,
    ) -> dict[str, Any]:
        """锁定并裁决一个仍处于 open 的冲突。"""
        if status not in {"resolved", "dismissed", "superseded"}:
            raise ValueError("冲突裁决状态必须是 resolved、dismissed 或 superseded")
        if not resolution.strip():
            raise ValueError("冲突裁决必须填写处理结论")
        async with pg_manager.get_async_session_context() as session:
            conflict = await session.scalar(
                select(KnowledgeGraphConflict)
                .where(
                    KnowledgeGraphConflict.kb_id == kb_id,
                    KnowledgeGraphConflict.conflict_id == conflict_id,
                )
                .with_for_update()
            )
            if conflict is None:
                raise LookupError("冲突记录不存在")
            if conflict.status != "open":
                raise ValueError("只有 open 冲突可以裁决")
            conflict.status = status
            conflict.resolution = resolution.strip()
            conflict.resolved_by = resolved_by
            conflict.resolved_at = datetime.now(UTC)
            conflict.updated_at = datetime.now(UTC)
            await session.flush()
            result = _serialize_conflict(conflict)
        return result

    async def _register_conflict_in_session(
        self,
        session,
        *,
        kb_id: str,
        conflict_type: str,
        left_target_type: str,
        left_target_id: str,
        right_target_type: str | None,
        right_target_id: str | None,
        severity: str,
        summary: str,
        details: dict[str, Any],
        detected_by: str,
    ) -> KnowledgeGraphConflict:
        """在调用方事务中创建或复用确定性冲突。"""
        _validate_conflict_input(
            left_target_type=left_target_type,
            left_target_id=left_target_id,
            right_target_type=right_target_type,
            right_target_id=right_target_id,
            severity=severity,
            summary=summary,
        )
        fingerprint = _conflict_fingerprint(
            conflict_type=conflict_type,
            left_target_type=left_target_type,
            left_target_id=left_target_id,
            right_target_type=right_target_type,
            right_target_id=right_target_id,
        )
        conflict_id = uuid.uuid4().hex
        statement = insert(KnowledgeGraphConflict).values(
            conflict_id=conflict_id,
            kb_id=kb_id,
            fingerprint=fingerprint,
            conflict_type=conflict_type,
            left_target_type=left_target_type,
            left_target_id=left_target_id,
            right_target_type=right_target_type,
            right_target_id=right_target_id,
            status="open",
            severity=severity,
            summary=summary.strip(),
            details=details,
            detected_by=detected_by,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["kb_id", "fingerprint"],
                set_={
                    "status": "open",
                    "severity": statement.excluded.severity,
                    "summary": statement.excluded.summary,
                    "details": statement.excluded.details,
                    "detected_by": statement.excluded.detected_by,
                    "resolution": "",
                    "resolved_by": None,
                    "resolved_at": None,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        return await session.scalar(
            select(KnowledgeGraphConflict).where(
                KnowledgeGraphConflict.kb_id == kb_id,
                KnowledgeGraphConflict.fingerprint == fingerprint,
            )
        )

    async def _close_target_conflicts_in_session(
        self,
        session,
        *,
        kb_id: str,
        target_type: str,
        target_id: str,
        decision: str,
        resolution: str,
        resolved_by: str,
    ) -> None:
        """审核形成确定结论时关闭目标仍未处理的冲突。"""
        status = "superseded" if decision == "superseded" else "resolved"
        conclusion = resolution.strip() or f"审核决定更新为 {decision}"
        await session.execute(
            update(KnowledgeGraphConflict)
            .where(
                KnowledgeGraphConflict.kb_id == kb_id,
                KnowledgeGraphConflict.left_target_type == target_type,
                KnowledgeGraphConflict.left_target_id == target_id,
                KnowledgeGraphConflict.status == "open",
            )
            .values(
                status=status,
                resolution=conclusion,
                resolved_by=resolved_by,
                resolved_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )


def _chunk_evidence_location(chunk: KnowledgeChunk) -> dict[str, Any]:
    """把结构化 Block 谱系投影到审核响应，证据正文仍来自权威 Chunk。"""
    return {
        "document_version": int(chunk.document_version or 1),
        "page": chunk.page_number,
        "block_type": chunk.block_type,
        "heading_path": chunk.heading_path or [],
        "bbox": chunk.bbox,
        "start_char": chunk.start_char_pos,
        "end_char": chunk.end_char_pos,
        "parser": chunk.parser_name,
        "parser_version": chunk.parser_version,
    }


def _entity_alignment_metadata(attributes: Any) -> dict[str, Any] | None:
    """只暴露平台写入的实体对齐审计元数据。"""
    if not isinstance(attributes, dict):
        return None
    alignment = attributes.get("alignment")
    return dict(alignment) if isinstance(alignment, dict) else None


def _validate_conflict_input(
    *,
    left_target_type: str,
    left_target_id: str,
    right_target_type: str | None,
    right_target_id: str | None,
    severity: str,
    summary: str,
) -> None:
    """校验多态冲突目标和治理字段。"""
    if left_target_type not in CONFLICT_TARGETS or not left_target_id:
        raise ValueError("冲突左侧目标无效")
    if (right_target_type is None) != (right_target_id is None):
        raise ValueError("冲突右侧目标类型和 ID 必须同时提供")
    if right_target_type is not None and right_target_type not in CONFLICT_TARGETS:
        raise ValueError("冲突右侧目标类型无效")
    if severity not in CONFLICT_SEVERITIES:
        raise ValueError(f"不支持的冲突严重度: {severity}")
    if not summary.strip():
        raise ValueError("冲突摘要不能为空")


def _conflict_fingerprint(
    *,
    conflict_type: str,
    left_target_type: str,
    left_target_id: str,
    right_target_type: str | None,
    right_target_id: str | None,
) -> str:
    """为同一知识库内的同类目标冲突生成稳定指纹。"""
    payload = {
        "conflict_type": conflict_type,
        "left": [left_target_type, left_target_id],
        "right": [right_target_type, right_target_id] if right_target_type is not None else None,
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize_conflict(conflict: KnowledgeGraphConflict) -> dict[str, Any]:
    """把冲突记录转为稳定治理响应。"""
    return {
        "conflict_id": conflict.conflict_id,
        "kb_id": conflict.kb_id,
        "conflict_type": conflict.conflict_type,
        "left_target_type": conflict.left_target_type,
        "left_target_id": conflict.left_target_id,
        "right_target_type": conflict.right_target_type,
        "right_target_id": conflict.right_target_id,
        "status": conflict.status,
        "severity": conflict.severity,
        "summary": conflict.summary,
        "details": conflict.details or {},
        "detected_by": conflict.detected_by,
        "resolution": conflict.resolution,
        "resolved_by": conflict.resolved_by,
        "resolved_at": conflict.resolved_at.isoformat() if conflict.resolved_at else None,
        "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
        "updated_at": conflict.updated_at.isoformat() if conflict.updated_at else None,
    }
