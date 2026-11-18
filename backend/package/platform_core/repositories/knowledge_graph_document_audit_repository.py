"""文档分流、研究链和知识卡的 PostgreSQL 权威仓储。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeDocumentCard,
    KnowledgeDocumentTriage,
    KnowledgeFile,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeResearchThread,
    KnowledgeSourceDocument,
)


class KnowledgeGraphDocumentAuditRepository:
    """把文档审计与图抽取器、HTTP 和前端隔离。"""

    async def load_documents(
        self,
        *,
        kb_id: str,
        document_ids: list[str],
        include_graph: bool,
    ) -> list[dict[str, Any]]:
        """加载当前文档版本及可回切的 Block，按需聚合权威图记录。"""
        requested = list(dict.fromkeys(str(item) for item in document_ids if item))
        if not requested:
            return []
        async with pg_manager.get_async_session_context() as session:
            source_rows = (
                await session.execute(
                    select(KnowledgeSourceDocument, KnowledgeFile)
                    .join(KnowledgeFile, KnowledgeFile.file_id == KnowledgeSourceDocument.file_id)
                    .where(
                        KnowledgeSourceDocument.kb_id == kb_id,
                        KnowledgeSourceDocument.document_id.in_(requested),
                    )
                )
            ).all()
            version_keys = [(str(source.file_id), int(source.current_version or 1)) for source, _file in source_rows]
            chunks = []
            if version_keys:
                chunks = list(
                    (
                        await session.scalars(
                            select(KnowledgeChunk)
                            .where(
                                KnowledgeChunk.kb_id == kb_id,
                                tuple_(KnowledgeChunk.file_id, KnowledgeChunk.document_version).in_(version_keys),
                            )
                            .order_by(KnowledgeChunk.file_id.asc(), KnowledgeChunk.chunk_index.asc())
                        )
                    ).all()
                )
            mention_rows = []
            relation_rows = []
            if include_graph and chunks:
                chunk_ids = [str(item.chunk_id) for item in chunks]
                mention_rows = (
                    await session.execute(
                        select(KnowledgeGraphEntityMention, KnowledgeGraphEntity)
                        .join(
                            KnowledgeGraphEntity,
                            KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityMention.entity_id,
                        )
                        .where(
                            KnowledgeGraphEntityMention.kb_id == kb_id,
                            KnowledgeGraphEntityMention.chunk_id.in_(chunk_ids),
                            KnowledgeGraphEntityMention.review_status.notin_(["rejected", "superseded"]),
                        )
                    )
                ).all()
                relation_rows = (
                    await session.execute(
                        select(KnowledgeGraphTripleMention, KnowledgeGraphTriple)
                        .join(
                            KnowledgeGraphTriple,
                            KnowledgeGraphTriple.triple_id == KnowledgeGraphTripleMention.triple_id,
                        )
                        .where(
                            KnowledgeGraphTripleMention.kb_id == kb_id,
                            KnowledgeGraphTripleMention.chunk_id.in_(chunk_ids),
                            KnowledgeGraphTripleMention.review_status.notin_(["rejected", "superseded"]),
                        )
                    )
                ).all()

        source_by_key = {
            (str(source.file_id), int(source.current_version or 1)): (source, file) for source, file in source_rows
        }
        chunks_by_document: dict[str, list[Any]] = {}
        document_by_chunk: dict[str, str] = {}
        chunk_by_id = {str(item.chunk_id): item for item in chunks}
        for chunk in chunks:
            row = source_by_key.get((str(chunk.file_id), int(chunk.document_version or 1)))
            if row is None:
                continue
            document_id = str(row[0].document_id)
            chunks_by_document.setdefault(document_id, []).append(chunk)
            document_by_chunk[str(chunk.chunk_id)] = document_id

        entities_by_document: dict[str, dict[str, dict[str, Any]]] = {}
        for mention, entity in mention_rows:
            chunk = chunk_by_id.get(str(mention.chunk_id))
            document_id = document_by_chunk.get(str(mention.chunk_id))
            if chunk is None or document_id is None:
                continue
            item = entities_by_document.setdefault(document_id, {}).setdefault(
                str(entity.entity_id),
                {
                    "entity_id": str(entity.entity_id),
                    "label": str(entity.label),
                    "name": str(entity.name),
                    "lifecycle_status": str(entity.lifecycle_status or "active"),
                    "mentions": [],
                },
            )
            item["mentions"].append(
                {
                    "block_id": str(chunk.chunk_id),
                    "page": chunk.page_number,
                    "start": mention.start_char,
                    "end": mention.end_char,
                    "heading_path": list(chunk.heading_path or []),
                    "confidence": mention.confidence,
                    "extraction_method": "entity_mention",
                    "model_version": mention.model_version,
                    "ontology_version": mention.ontology_version,
                    "review_status": str(mention.review_status or "pending"),
                }
            )

        relations_by_document: dict[str, dict[str, dict[str, Any]]] = {}
        for mention, relation in relation_rows:
            document_id = document_by_chunk.get(str(mention.chunk_id))
            if document_id is None:
                continue
            item = relations_by_document.setdefault(document_id, {}).setdefault(
                str(relation.triple_id),
                {
                    "triple_id": str(relation.triple_id),
                    "source_entity_id": str(relation.source_entity_id),
                    "target_entity_id": str(relation.target_entity_id),
                    "relation_type": str(relation.relation_type),
                    "lifecycle_status": str(relation.lifecycle_status or "active"),
                    "review_status": str(mention.review_status or "pending"),
                    "claim_level": str(mention.claim_level or "Inference"),
                    "evidence_spans": [],
                },
            )
            for span in mention.evidence_spans or []:
                normalized = dict(span)
                normalized.setdefault("block_id", str(mention.chunk_id))
                normalized.update(
                    {
                        "claim_level": str(mention.claim_level or "Inference"),
                        "confidence": mention.confidence,
                        "extraction_method": str(mention.extractor_type or "relation_mention"),
                        "model_version": mention.model_version,
                        "ontology_version": mention.ontology_version,
                        "pipeline_revision": mention.pipeline_revision,
                        "review_status": str(mention.review_status or "pending"),
                    }
                )
                if normalized not in item["evidence_spans"]:
                    item["evidence_spans"].append(normalized)
            if mention.review_status == "accepted":
                item["review_status"] = "accepted"

        row_by_document = {str(source.document_id): (source, file) for source, file in source_rows}
        documents = []
        for document_id in requested:
            row = row_by_document.get(document_id)
            if row is None:
                continue
            source, file = row
            document_chunks = chunks_by_document.get(document_id) or []
            documents.append(
                {
                    "kb_id": kb_id,
                    "document_id": document_id,
                    "document_version": int(source.current_version or 1),
                    "title": str(file.original_filename or file.filename or document_id),
                    "source_summary": {
                        "source_type": str(source.source_type or "unknown"),
                        "language": str(source.language or "unknown"),
                        "domain": str(source.domain or ""),
                        "content_hash": source.content_hash,
                    },
                    "blocks": [
                        {
                            "block_id": str(chunk.chunk_id),
                            "text": str(chunk.content or ""),
                            "page": chunk.page_number,
                            "heading_path": list(chunk.heading_path or []),
                            "bbox": chunk.bbox,
                        }
                        for chunk in document_chunks
                    ],
                    "entities": list((entities_by_document.get(document_id) or {}).values()),
                    "relations": list((relations_by_document.get(document_id) or {}).values()),
                }
            )
        return documents

    async def persist_triage(
        self,
        *,
        kb_id: str,
        results: list[dict[str, Any]],
        apply_filter: bool,
    ) -> None:
        """幂等保存分流结果；仅在显式启用时影响待抽取 Chunk。"""
        async with pg_manager.get_async_session_context() as session:
            for result in results:
                values = {
                    "document_id": result["document_id"],
                    "document_version": result["document_version"],
                    "kb_id": kb_id,
                    "document_kind": result["document_kind"],
                    "triage_level": result["triage_level"],
                    "eligible_for_extraction": result["eligible_for_extraction"],
                    "reason": result["reason"],
                    "signals": result["signals"],
                    "evidence": result["evidence"],
                    "rule_version": result["rule_version"],
                    "input_hash": result["input_hash"],
                }
                statement = insert(KnowledgeDocumentTriage).values(**values)
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["document_id", "document_version"],
                        set_={
                            key: value
                            for key, value in values.items()
                            if key not in {"document_id", "document_version"}
                        },
                    )
                )
            if apply_filter:
                await self._apply_filter_in_session(session, results)

    async def persist_document_knowledge(
        self,
        *,
        document: dict[str, Any],
        bundle: dict[str, Any],
        pipeline_revision: str,
    ) -> None:
        """以文档、版本和 pipeline revision 原子替换派生审计视图。"""
        document_id = str(document["document_id"])
        document_version = int(document["document_version"])
        async with pg_manager.get_async_session_context() as session:
            await session.execute(
                delete(KnowledgeResearchThread).where(
                    KnowledgeResearchThread.document_id == document_id,
                    KnowledgeResearchThread.document_version == document_version,
                    KnowledgeResearchThread.pipeline_revision == pipeline_revision,
                )
            )
            await session.execute(
                delete(KnowledgeDocumentCard).where(
                    KnowledgeDocumentCard.document_id == document_id,
                    KnowledgeDocumentCard.document_version == document_version,
                    KnowledgeDocumentCard.pipeline_revision == pipeline_revision,
                )
            )
            session.add_all(KnowledgeResearchThread(**item) for item in bundle["threads"])
            session.add(KnowledgeDocumentCard(**bundle["card"]))

    async def list_cards(
        self,
        *,
        kb_id: str,
        governance_status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """返回知识卡摘要，避免列表接口携带全部 Span。"""
        conditions = [KnowledgeDocumentCard.kb_id == kb_id]
        if governance_status:
            conditions.append(KnowledgeDocumentCard.governance_status == governance_status)
        async with pg_manager.get_async_session_context() as session:
            cards = list(
                (
                    await session.scalars(
                        select(KnowledgeDocumentCard)
                        .where(*conditions)
                        .order_by(KnowledgeDocumentCard.updated_at.desc(), KnowledgeDocumentCard.card_id.asc())
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
        return [_serialize_card(card, include_evidence=False) for card in cards]

    async def get_card(self, *, kb_id: str, card_id: str) -> dict[str, Any] | None:
        """返回知识卡、研究链及证据引用。"""
        async with pg_manager.get_async_session_context() as session:
            card = await session.scalar(
                select(KnowledgeDocumentCard).where(
                    KnowledgeDocumentCard.kb_id == kb_id,
                    KnowledgeDocumentCard.card_id == card_id,
                )
            )
            if card is None:
                return None
            threads = list(
                (
                    await session.scalars(
                        select(KnowledgeResearchThread)
                        .where(
                            KnowledgeResearchThread.kb_id == kb_id,
                            KnowledgeResearchThread.document_id == card.document_id,
                            KnowledgeResearchThread.document_version == card.document_version,
                            KnowledgeResearchThread.pipeline_revision == card.pipeline_revision,
                        )
                        .order_by(KnowledgeResearchThread.thread_type.asc(), KnowledgeResearchThread.title.asc())
                    )
                ).all()
            )
        payload = _serialize_card(card, include_evidence=True)
        payload["threads"] = [_serialize_thread(item) for item in threads]
        return payload

    @staticmethod
    async def _apply_filter_in_session(session: Any, results: list[dict[str, Any]]) -> None:
        for result in results:
            source = await session.scalar(
                select(KnowledgeSourceDocument).where(
                    KnowledgeSourceDocument.document_id == result["document_id"],
                    KnowledgeSourceDocument.current_version == result["document_version"],
                )
            )
            if source is None:
                continue
            excluded = not bool(result["eligible_for_extraction"])
            await session.execute(
                update(KnowledgeChunk)
                .where(
                    KnowledgeChunk.file_id == source.file_id,
                    KnowledgeChunk.document_version == source.current_version,
                    KnowledgeChunk.graph_indexed.is_not(True),
                )
                .values(
                    graph_excluded=excluded,
                    graph_exclusion_reason=result["reason"] if excluded else None,
                )
            )


def _serialize_card(card: KnowledgeDocumentCard, *, include_evidence: bool) -> dict[str, Any]:
    payload = {
        "card_id": card.card_id,
        "document_id": card.document_id,
        "document_version": card.document_version,
        "title": card.title,
        "source_summary": card.source_summary or {},
        "triage": card.triage or {},
        "content_overview": card.content_overview,
        "main_thread_id": card.main_thread_id,
        "sub_thread_ids": card.sub_thread_ids or [],
        "core_entity_ids": card.core_entity_ids or [],
        "core_relation_ids": card.core_relation_ids or [],
        "technology_families": card.technology_families or [],
        "capability_gains": card.capability_gains or [],
        "application_directions": card.application_directions or [],
        "maturity": card.maturity or {},
        "heat_signals": card.heat_signals or {},
        "innovation_potential": card.innovation_potential or {},
        "uncertainty": card.uncertainty,
        "pipeline_revision": card.pipeline_revision,
        "ontology_version": card.ontology_version,
        "governance_status": card.governance_status,
        "updated_at": card.updated_at.isoformat() if card.updated_at else None,
    }
    if include_evidence:
        payload["evidence_refs"] = card.evidence_refs or []
        payload["key_metrics"] = card.key_metrics or []
        payload["transfer_potential"] = card.transfer_potential or {}
        payload["graph_rag_hints"] = card.graph_rag_hints or {}
        payload["narrative_report"] = card.narrative_report or {}
    return payload


def _serialize_thread(thread: KnowledgeResearchThread) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "thread_type": thread.thread_type,
        "title": thread.title,
        "technical_line": thread.technical_line or [],
        "capability_direction": thread.capability_direction or [],
        "application_direction": thread.application_direction or [],
        "military_value": thread.military_value or {},
        "innovation_signals": thread.innovation_signals or [],
        "entity_ids": thread.entity_ids or [],
        "relation_ids": thread.relation_ids or [],
        "evidence_refs": thread.evidence_refs or [],
        "uncertainty": thread.uncertainty,
        "confidence": thread.confidence,
        "governance_status": thread.governance_status,
    }
