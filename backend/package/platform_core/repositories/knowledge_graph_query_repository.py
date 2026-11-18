"""实体、关系、证据和图谱版本的 PostgreSQL 只读查询仓储。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeGraphChangeEvent,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityAlias,
    KnowledgeGraphEntityMention,
    KnowledgeGraphEntityRedirect,
    KnowledgeGraphRevision,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeSourceDocument,
)

ACCEPTED_CLAIM_LEVELS = {"Fact", "Inference"}


class KnowledgeGraphQueryRepository:
    """从 PostgreSQL 权威事实源组装可追溯的图谱查询结果。"""

    async def get_entity_detail(
        self,
        *,
        kb_id: str,
        entity_id: str,
        evidence_limit: int = 100,
    ) -> dict[str, Any]:
        """返回实体、别名、已接受证据、redirect 和版本事件。"""
        async with pg_manager.get_async_session_context() as session:
            entity = await session.scalar(
                select(KnowledgeGraphEntity).where(
                    KnowledgeGraphEntity.kb_id == kb_id,
                    KnowledgeGraphEntity.entity_id == entity_id,
                )
            )
            if entity is None:
                raise LookupError("实体不存在")

            aliases = list(
                await session.scalars(
                    select(KnowledgeGraphEntityAlias)
                    .where(KnowledgeGraphEntityAlias.entity_id == entity_id)
                    .order_by(KnowledgeGraphEntityAlias.language.asc(), KnowledgeGraphEntityAlias.alias.asc())
                )
            )
            mention_conditions = (
                KnowledgeGraphEntityMention.kb_id == kb_id,
                KnowledgeGraphEntityMention.entity_id == entity_id,
                KnowledgeGraphEntityMention.review_status == "accepted",
            )
            evidence_count = await session.scalar(
                select(func.count()).select_from(KnowledgeGraphEntityMention).where(*mention_conditions)
            )
            mention_rows = (
                await session.execute(
                    select(
                        KnowledgeGraphEntityMention,
                        KnowledgeChunk,
                        KnowledgeFile,
                        KnowledgeSourceDocument.document_id,
                        KnowledgeSourceDocument.source_type,
                        KnowledgeSourceDocument.language,
                        KnowledgeSourceDocument.domain,
                    )
                    .join(KnowledgeChunk, KnowledgeChunk.chunk_id == KnowledgeGraphEntityMention.chunk_id)
                    .join(KnowledgeFile, KnowledgeFile.file_id == KnowledgeGraphEntityMention.file_id)
                    .outerjoin(KnowledgeSourceDocument, KnowledgeSourceDocument.file_id == KnowledgeFile.file_id)
                    .where(
                        *mention_conditions,
                    )
                    .order_by(KnowledgeGraphEntityMention.created_at.desc(), KnowledgeGraphEntityMention.id.desc())
                    .limit(max(1, min(evidence_limit, 500)))
                )
            ).all()
            if not mention_rows:
                raise LookupError("实体不存在已接受的原文证据")

            redirects = list(
                await session.scalars(
                    select(KnowledgeGraphEntityRedirect)
                    .where(
                        KnowledgeGraphEntityRedirect.kb_id == kb_id,
                        (
                            (KnowledgeGraphEntityRedirect.source_entity_id == entity_id)
                            | (KnowledgeGraphEntityRedirect.target_entity_id == entity_id)
                        ),
                    )
                    .order_by(KnowledgeGraphEntityRedirect.created_at.asc())
                )
            )
            changes = list(
                await session.scalars(
                    select(KnowledgeGraphChangeEvent)
                    .where(
                        KnowledgeGraphChangeEvent.kb_id == kb_id,
                        KnowledgeGraphChangeEvent.target_type == "entity",
                        KnowledgeGraphChangeEvent.target_id == entity_id,
                    )
                    .order_by(KnowledgeGraphChangeEvent.created_at.asc())
                )
            )

        return {
            "entity": _entity_payload(entity),
            "aliases": [_alias_payload(row) for row in aliases],
            "evidence": [_entity_evidence_payload(*row) for row in mention_rows],
            "redirects": [_redirect_payload(row) for row in redirects],
            "history": [_change_payload(row) for row in changes],
            "evidence_count": int(evidence_count or 0),
            "review_status": "accepted",
        }

    async def get_relation_detail(
        self,
        *,
        kb_id: str,
        triple_id: str,
        evidence_limit: int = 100,
    ) -> dict[str, Any]:
        """返回关系端点及已接受 Fact/Inference 的证据和适用条件。"""
        source_entity = aliased(KnowledgeGraphEntity)
        target_entity = aliased(KnowledgeGraphEntity)
        async with pg_manager.get_async_session_context() as session:
            relation_row = (
                await session.execute(
                    select(KnowledgeGraphTriple, source_entity, target_entity)
                    .join(source_entity, source_entity.entity_id == KnowledgeGraphTriple.source_entity_id)
                    .join(target_entity, target_entity.entity_id == KnowledgeGraphTriple.target_entity_id)
                    .where(
                        KnowledgeGraphTriple.kb_id == kb_id,
                        KnowledgeGraphTriple.triple_id == triple_id,
                    )
                )
            ).one_or_none()
            if relation_row is None:
                raise LookupError("关系不存在")

            mention_conditions = (
                KnowledgeGraphTripleMention.kb_id == kb_id,
                KnowledgeGraphTripleMention.triple_id == triple_id,
                KnowledgeGraphTripleMention.review_status == "accepted",
                KnowledgeGraphTripleMention.claim_level.in_(sorted(ACCEPTED_CLAIM_LEVELS)),
            )
            evidence_count = await session.scalar(
                select(func.count()).select_from(KnowledgeGraphTripleMention).where(*mention_conditions)
            )
            evidence_facets = (
                await session.execute(
                    select(
                        KnowledgeGraphTripleMention.claim_level,
                        KnowledgeGraphTripleMention.applicable_conditions,
                    ).where(*mention_conditions)
                )
            ).all()
            mention_rows = (
                await session.execute(
                    select(
                        KnowledgeGraphTripleMention,
                        KnowledgeChunk,
                        KnowledgeFile,
                        KnowledgeSourceDocument.document_id,
                        KnowledgeSourceDocument.source_type,
                        KnowledgeSourceDocument.language,
                        KnowledgeSourceDocument.domain,
                    )
                    .join(KnowledgeChunk, KnowledgeChunk.chunk_id == KnowledgeGraphTripleMention.chunk_id)
                    .join(KnowledgeFile, KnowledgeFile.file_id == KnowledgeGraphTripleMention.file_id)
                    .outerjoin(KnowledgeSourceDocument, KnowledgeSourceDocument.file_id == KnowledgeFile.file_id)
                    .where(
                        *mention_conditions,
                    )
                    .order_by(KnowledgeGraphTripleMention.created_at.desc(), KnowledgeGraphTripleMention.id.desc())
                    .limit(max(1, min(evidence_limit, 500)))
                )
            ).all()
            if not mention_rows:
                raise LookupError("关系不存在已接受的 Fact/Inference 证据")

            relation, source, target = relation_row
            changes = list(
                await session.scalars(
                    select(KnowledgeGraphChangeEvent)
                    .where(
                        KnowledgeGraphChangeEvent.kb_id == kb_id,
                        KnowledgeGraphChangeEvent.target_type == "relation",
                        KnowledgeGraphChangeEvent.target_id == triple_id,
                    )
                    .order_by(KnowledgeGraphChangeEvent.created_at.asc())
                )
            )

        evidence = [_relation_evidence_payload(*row) for row in mention_rows]
        conditions = sorted(
            {
                str(condition)
                for _, applicable_conditions in evidence_facets
                for condition in applicable_conditions or []
                if str(condition).strip()
            }
        )
        return {
            "relation": {
                "triple_id": relation.triple_id,
                "type": relation.relation_type,
                "source_entity_id": relation.source_entity_id,
                "target_entity_id": relation.target_entity_id,
                "content": relation.content,
                "lifecycle_status": relation.lifecycle_status,
                "superseded_by_triple_id": relation.superseded_by_triple_id,
                "valid_from": _iso(relation.valid_from),
                "valid_to": _iso(relation.valid_to),
                "relation_version": relation.relation_version,
                "created_at": _iso(relation.created_at),
                "updated_at": _iso(relation.updated_at),
            },
            "source": _entity_payload(source),
            "target": _entity_payload(target),
            "claim_levels": sorted({claim_level for claim_level, _ in evidence_facets}),
            "applicable_conditions": conditions,
            "evidence": evidence,
            "history": [_change_payload(row) for row in changes],
            "evidence_count": int(evidence_count or 0),
            "review_status": "accepted",
        }

    async def list_revisions(self, *, kb_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """按时间倒序返回图谱 revision。"""
        conditions = [KnowledgeGraphRevision.kb_id == kb_id]
        async with pg_manager.get_async_session_context() as session:
            total = await session.scalar(select(func.count()).select_from(KnowledgeGraphRevision).where(*conditions))
            rows = list(
                await session.scalars(
                    select(KnowledgeGraphRevision)
                    .where(*conditions)
                    .order_by(KnowledgeGraphRevision.created_at.desc(), KnowledgeGraphRevision.revision_id.desc())
                    .limit(max(1, min(limit, 500)))
                    .offset(max(offset, 0))
                )
            )
        return {"items": [_revision_payload(row) for row in rows], "count": int(total or 0)}

    async def list_changes(
        self,
        *,
        kb_id: str,
        graph_revision: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按 revision 或知识目标筛选不可变变更事件。"""
        conditions = [KnowledgeGraphChangeEvent.kb_id == kb_id]
        if graph_revision:
            conditions.append(KnowledgeGraphChangeEvent.graph_revision == graph_revision)
        if target_type:
            conditions.append(KnowledgeGraphChangeEvent.target_type == target_type)
        if target_id:
            conditions.append(KnowledgeGraphChangeEvent.target_id == target_id)

        async with pg_manager.get_async_session_context() as session:
            total = await session.scalar(select(func.count()).select_from(KnowledgeGraphChangeEvent).where(*conditions))
            rows = list(
                await session.scalars(
                    select(KnowledgeGraphChangeEvent)
                    .where(*conditions)
                    .order_by(
                        KnowledgeGraphChangeEvent.created_at.desc(),
                        KnowledgeGraphChangeEvent.event_id.desc(),
                    )
                    .limit(max(1, min(limit, 500)))
                    .offset(max(offset, 0))
                )
            )
        return {"items": [_change_payload(row) for row in rows], "count": int(total or 0)}


def _entity_payload(entity: KnowledgeGraphEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "normalized_name": entity.normalized_name,
        "type": entity.label,
        "attributes": entity.attributes or {},
        "lifecycle_status": entity.lifecycle_status,
        "superseded_by_entity_id": entity.superseded_by_entity_id,
        "valid_from": _iso(entity.valid_from),
        "valid_to": _iso(entity.valid_to),
        "entity_version": entity.entity_version,
        "created_at": _iso(entity.created_at),
        "updated_at": _iso(entity.updated_at),
    }


def _alias_payload(alias: KnowledgeGraphEntityAlias) -> dict[str, Any]:
    return {
        "alias": alias.alias,
        "normalized_alias": alias.normalized_alias,
        "language": alias.language,
        "source": alias.source,
        "confidence": alias.confidence,
        "created_at": _iso(alias.created_at),
    }


def _entity_evidence_payload(
    mention: KnowledgeGraphEntityMention,
    chunk: KnowledgeChunk,
    file: KnowledgeFile,
    document_id: str | None,
    source_type: str | None,
    language: str | None,
    domain: str | None,
) -> dict[str, Any]:
    return {
        "mention_id": str(mention.id),
        "mention_text": mention.mention_text,
        "span": {"start": mention.start_char, "end": mention.end_char},
        "confidence": mention.confidence,
        "model_version": mention.model_version,
        "ontology_version": mention.ontology_version,
        "file_id": mention.file_id,
        "filename": file.original_filename or file.filename,
        "document_id": document_id,
        "source_type": source_type,
        "language": language,
        "domain": domain,
        "chunk_id": mention.chunk_id,
        "evidence_text": chunk.content,
        "location": _evidence_location(chunk),
        "created_at": _iso(mention.created_at),
    }


def _relation_evidence_payload(
    mention: KnowledgeGraphTripleMention,
    chunk: KnowledgeChunk,
    file: KnowledgeFile,
    document_id: str | None,
    source_type: str | None,
    language: str | None,
    domain: str | None,
) -> dict[str, Any]:
    return {
        "mention_id": str(mention.id),
        "claim_level": mention.claim_level,
        "confidence": mention.confidence,
        "extractor_type": mention.extractor_type,
        "model_version": mention.model_version,
        "ontology_version": mention.ontology_version,
        "pipeline_revision": mention.pipeline_revision,
        "evidence_quote": mention.evidence_quote,
        "evidence_spans": mention.evidence_spans or [],
        "reasoning_basis": mention.reasoning_basis,
        "applicable_conditions": mention.applicable_conditions or [],
        "secondary_review": mention.secondary_review,
        "uncertainty": mention.uncertainty,
        "expert_review_required": mention.expert_review_required,
        "file_id": mention.file_id,
        "filename": file.original_filename or file.filename,
        "document_id": document_id,
        "source_type": source_type,
        "language": language,
        "domain": domain,
        "chunk_id": mention.chunk_id,
        "evidence_text": chunk.content,
        "location": _evidence_location(chunk),
        "created_at": _iso(mention.created_at),
    }


def _evidence_location(chunk: KnowledgeChunk) -> dict[str, Any]:
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


def _redirect_payload(row: KnowledgeGraphEntityRedirect) -> dict[str, Any]:
    return {
        "redirect_id": row.redirect_id,
        "source_entity_id": row.source_entity_id,
        "target_entity_id": row.target_entity_id,
        "target_entity_ids": (row.redirect_metadata or {}).get("target_entity_ids") or [row.target_entity_id],
        "operation": row.operation,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


def _revision_payload(row: KnowledgeGraphRevision) -> dict[str, Any]:
    return {
        "revision_id": row.revision_id,
        "parent_revision_id": row.parent_revision_id,
        "ontology_version": row.ontology_version,
        "reason": row.reason,
        "summary": row.summary or {},
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


def _change_payload(row: KnowledgeGraphChangeEvent) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "graph_revision": row.graph_revision,
        "event_type": row.event_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before": row.before_payload,
        "after": row.after_payload,
        "reason": row.reason,
        "source_ref": row.source_ref or {},
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
    }


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None
