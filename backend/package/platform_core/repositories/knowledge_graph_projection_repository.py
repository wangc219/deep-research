"""从 PostgreSQL 权威知识生成可重建的当前图投影快照。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import exists, func, or_, select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphRevision,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
)


@dataclass(frozen=True, slots=True)
class AuthoritativeProjectionSnapshot:
    """一个 Chunk 在某次权威读取中的完整当前投影。"""

    chunk: dict[str, Any]
    graph_payload: dict[str, Any]
    entity_records: list[dict[str, Any]]
    triple_records: list[dict[str, Any]]


class KnowledgeGraphProjectionRepository:
    """只读 PostgreSQL 投影快照端口，不负责 Neo4j 或 Milvus I/O。"""

    async def latest_revision(self, kb_id: str) -> str | None:
        async with pg_manager.get_async_session_context() as session:
            return await session.scalar(
                select(KnowledgeGraphRevision.revision_id)
                .where(KnowledgeGraphRevision.kb_id == kb_id)
                .order_by(KnowledgeGraphRevision.created_at.desc(), KnowledgeGraphRevision.revision_id.desc())
                .limit(1)
            )

    async def count_projectable_chunks(self, kb_id: str) -> int:
        entity_mention_exists = exists().where(KnowledgeGraphEntityMention.chunk_id == KnowledgeChunk.chunk_id)
        triple_mention_exists = exists().where(KnowledgeGraphTripleMention.chunk_id == KnowledgeChunk.chunk_id)
        async with pg_manager.get_async_session_context() as session:
            count = await session.scalar(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.kb_id == kb_id,
                    or_(entity_mention_exists, triple_mention_exists),
                )
            )
            return int(count or 0)

    async def list_chunk_snapshots(
        self,
        *,
        kb_id: str,
        after_id: int,
        limit: int,
    ) -> list[AuthoritativeProjectionSnapshot]:
        """按稳定 Chunk 主键分页读取当前权威 mention，不读取历史 Outbox。"""
        entity_mention_exists = exists().where(KnowledgeGraphEntityMention.chunk_id == KnowledgeChunk.chunk_id)
        triple_mention_exists = exists().where(KnowledgeGraphTripleMention.chunk_id == KnowledgeChunk.chunk_id)
        async with pg_manager.get_async_session_context() as session:
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunk)
                        .where(
                            KnowledgeChunk.kb_id == kb_id,
                            KnowledgeChunk.id > max(int(after_id), 0),
                            or_(entity_mention_exists, triple_mention_exists),
                        )
                        .order_by(KnowledgeChunk.id.asc())
                        .limit(max(1, min(int(limit), 500)))
                    )
                ).all()
            )
            if not chunks:
                return []

            chunk_ids = [str(chunk.chunk_id) for chunk in chunks]
            entity_rows = (
                await session.execute(
                    select(KnowledgeGraphEntityMention, KnowledgeGraphEntity)
                    .join(
                        KnowledgeGraphEntity,
                        KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityMention.entity_id,
                    )
                    .where(
                        KnowledgeGraphEntityMention.kb_id == kb_id,
                        KnowledgeGraphEntityMention.chunk_id.in_(chunk_ids),
                    )
                    .order_by(
                        KnowledgeGraphEntityMention.chunk_id.asc(),
                        KnowledgeGraphEntityMention.entity_id.asc(),
                        KnowledgeGraphEntityMention.start_char.asc().nullslast(),
                        KnowledgeGraphEntityMention.id.asc(),
                    )
                )
            ).all()
            triple_rows = (
                await session.execute(
                    select(KnowledgeGraphTripleMention, KnowledgeGraphTriple)
                    .join(
                        KnowledgeGraphTriple,
                        KnowledgeGraphTriple.triple_id == KnowledgeGraphTripleMention.triple_id,
                    )
                    .where(
                        KnowledgeGraphTripleMention.kb_id == kb_id,
                        KnowledgeGraphTripleMention.chunk_id.in_(chunk_ids),
                    )
                    .order_by(
                        KnowledgeGraphTripleMention.chunk_id.asc(),
                        KnowledgeGraphTripleMention.triple_id.asc(),
                    )
                )
            ).all()

            endpoint_ids = {
                str(entity_id)
                for _mention, triple in triple_rows
                for entity_id in (triple.source_entity_id, triple.target_entity_id)
            }
            endpoint_entities = {}
            if endpoint_ids:
                endpoint_entities = {
                    str(entity.entity_id): entity
                    for entity in (
                        await session.scalars(
                            select(KnowledgeGraphEntity).where(
                                KnowledgeGraphEntity.kb_id == kb_id,
                                KnowledgeGraphEntity.entity_id.in_(endpoint_ids),
                            )
                        )
                    ).all()
                }

        entity_rows_by_chunk: dict[str, list[tuple[Any, Any]]] = {}
        for mention, entity in entity_rows:
            entity_rows_by_chunk.setdefault(str(mention.chunk_id), []).append((mention, entity))
        triple_rows_by_chunk: dict[str, list[tuple[Any, Any]]] = {}
        for mention, triple in triple_rows:
            triple_rows_by_chunk.setdefault(str(mention.chunk_id), []).append((mention, triple))

        return [
            self._build_snapshot(
                chunk,
                entity_rows_by_chunk.get(str(chunk.chunk_id), []),
                triple_rows_by_chunk.get(str(chunk.chunk_id), []),
                endpoint_entities,
            )
            for chunk in chunks
        ]

    @classmethod
    def _build_snapshot(
        cls,
        chunk: Any,
        entity_rows: list[tuple[Any, Any]],
        triple_rows: list[tuple[Any, Any]],
        endpoint_entities: dict[str, Any],
    ) -> AuthoritativeProjectionSnapshot:
        selected_mentions: dict[str, tuple[Any, Any]] = {}
        review_priority = {"accepted": 0, "disputed": 1, "pending": 2, "superseded": 3, "rejected": 4}
        for mention, entity in entity_rows:
            entity_id = str(entity.entity_id)
            candidate_key = (
                review_priority.get(str(mention.review_status), 9),
                mention.start_char is None,
                int(mention.start_char or 0),
                int(mention.id or 0),
            )
            current = selected_mentions.get(entity_id)
            if current is None:
                selected_mentions[entity_id] = (mention, entity)
                continue
            current_mention = current[0]
            current_key = (
                review_priority.get(str(current_mention.review_status), 9),
                current_mention.start_char is None,
                int(current_mention.start_char or 0),
                int(current_mention.id or 0),
            )
            if candidate_key < current_key:
                selected_mentions[entity_id] = (mention, entity)

        required_endpoint_ids = {
            str(entity_id)
            for _mention, triple in triple_rows
            for entity_id in (triple.source_entity_id, triple.target_entity_id)
        }
        ordered_entity_ids = sorted(set(selected_mentions) | required_endpoint_ids)
        local_id_by_entity_id = {entity_id: f"entity_{index}" for index, entity_id in enumerate(ordered_entity_ids)}
        graph_entities = []
        entity_records = []
        for entity_id in ordered_entity_ids:
            selected = selected_mentions.get(entity_id)
            mention = selected[0] if selected else None
            entity = selected[1] if selected else endpoint_entities.get(entity_id)
            if entity is None:
                raise ValueError(f"权威关系端点实体不存在: {entity_id}")
            attributes = entity.attributes or []
            graph_entities.append(
                {
                    "id": local_id_by_entity_id[entity_id],
                    "text": str(mention.mention_text or entity.name) if mention is not None else str(entity.name),
                    "label": str(entity.label),
                    "attributes": attributes,
                }
            )
            entity_records.append(
                {
                    "entity_id": entity_id,
                    "kb_id": str(entity.kb_id),
                    "normalized_name": str(entity.normalized_name),
                    "label": str(entity.label),
                    "name": str(entity.name),
                    "attributes": attributes,
                    "lifecycle_status": str(entity.lifecycle_status or "active"),
                    "superseded_by_entity_id": entity.superseded_by_entity_id,
                    "entity_version": int(entity.entity_version or 1),
                    "mention_text": mention.mention_text if mention is not None else None,
                    "start_char": mention.start_char if mention is not None else None,
                    "end_char": mention.end_char if mention is not None else None,
                    "confidence": mention.confidence if mention is not None else None,
                    "model_version": mention.model_version if mention is not None else None,
                    "ontology_version": mention.ontology_version if mention is not None else None,
                    "review_status": str(mention.review_status or "pending") if mention is not None else "pending",
                    "has_mention": mention is not None,
                }
            )

        graph_relations = []
        triple_records = []
        for mention, triple in triple_rows:
            source_id = str(triple.source_entity_id)
            target_id = str(triple.target_entity_id)
            graph_relations.append(
                {
                    "triple_id": str(triple.triple_id),
                    "source": local_id_by_entity_id[source_id],
                    "target": local_id_by_entity_id[target_id],
                    "text": str(mention.text or triple.relation_type),
                    "label": str(triple.relation_type),
                    "extractor_type": str(mention.extractor_type or "authoritative_rebuild"),
                    "claim_level": str(mention.claim_level or "Inference"),
                    "confidence": float(mention.confidence or 0.0),
                    "evidence_quote": str(mention.evidence_quote or ""),
                    "evidence_spans": list(mention.evidence_spans or []),
                    "reasoning_basis": str(mention.reasoning_basis or ""),
                    "applicable_conditions": list(mention.applicable_conditions or []),
                    "secondary_review": getattr(mention, "secondary_review", None),
                    "uncertainty": str(mention.uncertainty or ""),
                    "expert_review_required": bool(mention.expert_review_required),
                }
            )
            triple_records.append(
                {
                    "triple_id": str(triple.triple_id),
                    "kb_id": str(triple.kb_id),
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "relation_type": str(triple.relation_type),
                    "content": str(triple.content),
                    "text": mention.text,
                    "extractor_type": mention.extractor_type,
                    "claim_level": mention.claim_level,
                    "confidence": float(mention.confidence or 0.0),
                    "evidence_quote": str(mention.evidence_quote or ""),
                    "evidence_spans": list(mention.evidence_spans or []),
                    "reasoning_basis": str(mention.reasoning_basis or ""),
                    "applicable_conditions": list(mention.applicable_conditions or []),
                    "secondary_review": getattr(mention, "secondary_review", None),
                    "uncertainty": str(mention.uncertainty or ""),
                    "expert_review_required": bool(mention.expert_review_required),
                    "review_status": str(mention.review_status or "pending"),
                    "model_version": mention.model_version,
                    "ontology_version": mention.ontology_version,
                    "pipeline_revision": mention.pipeline_revision,
                    "lifecycle_status": str(triple.lifecycle_status or "active"),
                    "superseded_by_triple_id": triple.superseded_by_triple_id,
                    "relation_version": int(triple.relation_version or 1),
                }
            )

        graph_payload = {
            "entities": graph_entities,
            "relations": graph_relations,
            "metadata": {
                "extractor_type": "authoritative_rebuild",
                "pipeline_revision": "postgres-authoritative-rebuild-v1",
            },
        }
        return AuthoritativeProjectionSnapshot(
            chunk={
                "id": int(chunk.id),
                "chunk_id": str(chunk.chunk_id),
                "file_id": str(chunk.file_id),
                "chunk_index": int(chunk.chunk_index),
                "content_preview": str(chunk.content or "")[:300],
                "start_char_pos": chunk.start_char_pos,
                "end_char_pos": chunk.end_char_pos,
                "document_version": int(chunk.document_version or 1),
                "page_number": chunk.page_number,
                "block_type": chunk.block_type,
                "heading_path": list(chunk.heading_path or []),
                "bbox": chunk.bbox,
                "parser_name": chunk.parser_name,
                "parser_version": chunk.parser_version,
            },
            graph_payload=graph_payload,
            entity_records=entity_records,
            triple_records=triple_records,
        )
