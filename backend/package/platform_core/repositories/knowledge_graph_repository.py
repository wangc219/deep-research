from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from platform_core.knowledge.graphs.entity_semantic_profile import build_entity_semantic_profile
from platform_core.knowledge.graphs.relation_semantic_profile import build_relation_semantic_profile
from platform_core.storage.postgres.manager import pg_manager
from platform_core.knowledge.graphs.entity_identity import relation_uuid
from platform_core.knowledge.graphs.graph_utils import canonical_entity_display_name, normalize_entity_name
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityAlias,
    KnowledgeGraphEntityMention,
    KnowledgeGraphProjectionOutbox,
    KnowledgeGraphRevision,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
)


class KnowledgeGraphRepository:
    VECTOR_MAX_ATTEMPTS = 3
    PROJECTION_MAX_ATTEMPTS = 5
    VECTOR_EVIDENCE_QUERY_LIMIT_PER_ENTITY = 128

    async def count_by_kb_id(self, kb_id: str) -> tuple[int, int]:
        async with pg_manager.get_async_session_context() as session:
            entity_count = await session.scalar(
                select(func.count()).select_from(KnowledgeGraphEntity).where(KnowledgeGraphEntity.kb_id == kb_id)
            )
            triple_count = await session.scalar(
                select(func.count()).select_from(KnowledgeGraphTriple).where(KnowledgeGraphTriple.kb_id == kb_id)
            )
            return int(entity_count or 0), int(triple_count or 0)

    async def count_vector_statuses_by_kb_id(self, kb_id: str) -> dict[str, int]:
        counts = {"pending": 0, "processing": 0, "indexed": 0, "failed": 0}
        async with pg_manager.get_async_session_context() as session:
            for model in (KnowledgeGraphEntity, KnowledgeGraphTriple):
                conditions = [model.kb_id == kb_id]
                if model is KnowledgeGraphEntity:
                    conditions.append(KnowledgeGraphEntity.lifecycle_status == "active")
                else:
                    conditions.append(KnowledgeGraphTriple.lifecycle_status == "active")
                rows = (
                    await session.execute(
                        select(model.vector_status, func.count()).where(*conditions).group_by(model.vector_status)
                    )
                ).all()
                for status, count in rows:
                    counts[str(status)] = counts.get(str(status), 0) + int(count or 0)
        return counts

    async def list_accepted_entity_ids_by_chunk_ids(
        self,
        *,
        kb_id: str,
        chunk_ids: list[str],
        limit_per_chunk: int = 24,
    ) -> dict[str, list[str]]:
        """按 Chunk 返回已接受 mention 对应的实体 ID，供 mix 检索安全扩展。"""
        return await self.list_entity_ids_by_chunk_ids(
            kb_id=kb_id,
            chunk_ids=chunk_ids,
            review_statuses=("accepted",),
            limit_per_chunk=limit_per_chunk,
        )

    async def list_entity_ids_by_chunk_ids(
        self,
        *,
        kb_id: str,
        chunk_ids: list[str],
        review_statuses: tuple[str, ...],
        limit_per_chunk: int = 24,
    ) -> dict[str, list[str]]:
        """按关系连通度、审核状态和置信度返回有界 Chunk 实体锚点。"""
        ordered_chunk_ids = list(dict.fromkeys(str(item) for item in chunk_ids if item))
        if not ordered_chunk_ids:
            return {}
        bounded_limit = max(1, min(int(limit_per_chunk), 64))
        statuses = tuple(dict.fromkeys(str(item).strip().lower() for item in review_statuses if str(item).strip()))
        if not statuses or set(statuses) - {"accepted", "pending"}:
            raise ValueError("review_statuses 只允许 accepted 或 pending")
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeGraphEntityMention.chunk_id,
                        KnowledgeGraphEntityMention.entity_id,
                        KnowledgeGraphEntityMention.review_status,
                        KnowledgeGraphEntityMention.confidence,
                        KnowledgeGraphEntityMention.id,
                    )
                    .join(
                        KnowledgeGraphEntity,
                        KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityMention.entity_id,
                    )
                    .where(
                        KnowledgeGraphEntityMention.kb_id == kb_id,
                        KnowledgeGraphEntityMention.chunk_id.in_(ordered_chunk_ids),
                        KnowledgeGraphEntityMention.review_status.in_(statuses),
                        KnowledgeGraphEntity.lifecycle_status == "active",
                    )
                )
            ).all()
            entity_ids = list(dict.fromkeys(str(row.entity_id) for row in rows))
            relation_rows = []
            if entity_ids:
                relation_rows = (
                    await session.execute(
                        select(
                            KnowledgeGraphTriple.source_entity_id,
                            KnowledgeGraphTriple.target_entity_id,
                        ).where(
                            KnowledgeGraphTriple.kb_id == kb_id,
                            KnowledgeGraphTriple.lifecycle_status == "active",
                            or_(
                                KnowledgeGraphTriple.source_entity_id.in_(entity_ids),
                                KnowledgeGraphTriple.target_entity_id.in_(entity_ids),
                            ),
                        )
                    )
                ).all()

        degrees = {entity_id: 0 for entity_id in entity_ids}
        for source_id, target_id in relation_rows:
            source = str(source_id)
            target = str(target_id)
            if source in degrees:
                degrees[source] += 1
            if target in degrees:
                degrees[target] += 1

        candidates_by_chunk: dict[str, dict[str, tuple[int, float, int]]] = {
            chunk_id: {} for chunk_id in ordered_chunk_ids
        }
        for chunk_id, entity_id, review_status, confidence, mention_id in rows:
            normalized_chunk_id = str(chunk_id)
            normalized_entity_id = str(entity_id)
            candidate = (
                0 if str(review_status) == "accepted" else 1,
                -float(confidence or 0.0),
                int(mention_id),
            )
            current = candidates_by_chunk.setdefault(normalized_chunk_id, {}).get(normalized_entity_id)
            if current is None or candidate < current:
                candidates_by_chunk[normalized_chunk_id][normalized_entity_id] = candidate

        by_chunk_id: dict[str, list[str]] = {}
        for chunk_id in ordered_chunk_ids:
            candidates = candidates_by_chunk.get(chunk_id) or {}
            by_chunk_id[chunk_id] = sorted(
                candidates,
                key=lambda entity_id: (
                    -degrees.get(entity_id, 0),
                    *candidates[entity_id],
                    entity_id,
                ),
            )[:bounded_limit]
        return by_chunk_id

    async def claim_vector_records(
        self,
        *,
        kb_id: str,
        record_type: str,
        limit: int,
        lease_seconds: int,
        include_evidence_rows: bool = False,
    ) -> tuple[str, list[dict[str, Any]]]:
        model, _ = self._vector_model(record_type)
        now = datetime.now(UTC)
        claimable = or_(
            (
                (model.vector_status == "pending")
                & or_(model.vector_next_retry_at.is_(None), model.vector_next_retry_at <= now)
            ),
            ((model.vector_status == "processing") & (model.vector_locked_until < now)),
        )
        conditions = [model.kb_id == kb_id, claimable]
        if record_type == "entity":
            conditions.append(KnowledgeGraphEntity.lifecycle_status == "active")
        else:
            conditions.append(KnowledgeGraphTriple.lifecycle_status == "active")
        token = uuid.uuid4().hex
        async with pg_manager.get_async_session_context() as session:
            records = list(
                (
                    await session.execute(
                        select(model)
                        .where(*conditions)
                        .order_by(model.id.asc())
                        .limit(max(limit, 1))
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            for record in records:
                record.vector_status = "processing"
                record.vector_attempt_count = int(record.vector_attempt_count or 0) + 1
                record.vector_locked_until = now + timedelta(seconds=lease_seconds)
                record.vector_lock_token = token
                record.vector_last_error = None
            if record_type == "entity":
                payloads = await self._entity_vector_payloads(
                    session,
                    kb_id=kb_id,
                    records=records,
                    include_evidence_rows=include_evidence_rows,
                )
            else:
                payloads = await self._triple_vector_payloads(
                    session,
                    kb_id=kb_id,
                    records=records,
                    include_evidence_rows=include_evidence_rows,
                )
        return token, payloads

    async def mark_vector_records_indexed(
        self,
        *,
        record_type: str,
        record_ids: list[str],
        lock_token: str,
    ) -> list[str]:
        if not record_ids:
            return []
        model, id_field = self._vector_model(record_type)
        conditions = [id_field.in_(record_ids), model.vector_lock_token == lock_token]
        if record_type == "entity":
            conditions.append(KnowledgeGraphEntity.lifecycle_status == "active")
        else:
            conditions.append(KnowledgeGraphTriple.lifecycle_status == "active")
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                update(model)
                .where(*conditions)
                .values(
                    vector_status="indexed",
                    vector_last_error=None,
                    vector_next_retry_at=None,
                    vector_locked_until=None,
                    vector_lock_token=None,
                )
                .returning(id_field)
            )
            return [str(record_id) for record_id in result.scalars().all()]

    async def mark_vector_records_failed(
        self,
        *,
        record_type: str,
        record_ids: list[str],
        lock_token: str,
        error: str,
    ) -> None:
        if not record_ids:
            return
        model, id_field = self._vector_model(record_type)
        conditions = [id_field.in_(record_ids), model.vector_lock_token == lock_token]
        if record_type == "entity":
            conditions.append(KnowledgeGraphEntity.lifecycle_status == "active")
        else:
            conditions.append(KnowledgeGraphTriple.lifecycle_status == "active")
        now = datetime.now(UTC)
        async with pg_manager.get_async_session_context() as session:
            await session.execute(
                update(model)
                .where(*conditions)
                .values(
                    vector_status=case(
                        (model.vector_attempt_count >= self.VECTOR_MAX_ATTEMPTS, "failed"),
                        else_="pending",
                    ),
                    vector_last_error=error[:4000],
                    vector_next_retry_at=case(
                        (model.vector_attempt_count == 1, now + timedelta(seconds=5)),
                        (model.vector_attempt_count == 2, now + timedelta(seconds=30)),
                        else_=None,
                    ),
                    vector_locked_until=None,
                    vector_lock_token=None,
                )
            )

    async def finalize_graph_indexed_chunks(self, kb_id: str) -> int:
        entity_not_indexed = exists().where(
            KnowledgeGraphEntityMention.chunk_id == KnowledgeChunk.chunk_id,
            KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityMention.entity_id,
            KnowledgeGraphEntity.lifecycle_status == "active",
            KnowledgeGraphEntity.vector_status != "indexed",
        )
        triple_not_indexed = exists().where(
            KnowledgeGraphTripleMention.chunk_id == KnowledgeChunk.chunk_id,
            KnowledgeGraphTriple.triple_id == KnowledgeGraphTripleMention.triple_id,
            KnowledgeGraphTriple.lifecycle_status == "active",
            KnowledgeGraphTriple.vector_status != "indexed",
        )
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                update(KnowledgeChunk)
                .where(
                    KnowledgeChunk.kb_id == kb_id,
                    KnowledgeChunk.graph_structure_indexed.is_(True),
                    KnowledgeChunk.graph_indexed.is_not(True),
                    ~entity_not_indexed,
                    ~triple_not_indexed,
                )
                .values(graph_indexed=True)
            )
            return int(result.rowcount or 0)

    async def reconcile_vector_records(self, kb_id: str, *, all_vectors: bool) -> int:
        now = datetime.now(UTC)
        total = 0
        async with pg_manager.get_async_session_context() as session:
            for model in (KnowledgeGraphEntity, KnowledgeGraphTriple):
                condition = model.kb_id == kb_id
                if model is KnowledgeGraphEntity:
                    condition = condition & (KnowledgeGraphEntity.lifecycle_status == "active")
                else:
                    condition = condition & (KnowledgeGraphTriple.lifecycle_status == "active")
                if not all_vectors:
                    condition = condition & or_(
                        model.vector_status == "failed",
                        ((model.vector_status == "processing") & (model.vector_locked_until < now)),
                    )
                result = await session.execute(
                    update(model)
                    .where(condition)
                    .values(
                        vector_status="pending",
                        vector_attempt_count=0,
                        vector_last_error=None,
                        vector_next_retry_at=None,
                        vector_locked_until=None,
                        vector_lock_token=None,
                    )
                )
                total += int(result.rowcount or 0)
            for model in (KnowledgeGraphEntity, KnowledgeGraphTriple):
                await session.execute(
                    update(model)
                    .where(
                        model.kb_id == kb_id,
                        model.lifecycle_status != "active",
                    )
                    .values(
                        vector_status="disabled",
                        vector_last_error=None,
                        vector_next_retry_at=None,
                        vector_locked_until=None,
                        vector_lock_token=None,
                    )
                )
            if all_vectors:
                await session.execute(
                    update(KnowledgeChunk).where(KnowledgeChunk.kb_id == kb_id).values(graph_indexed=False)
                )
        return total

    @staticmethod
    def _vector_model(record_type: str):
        if record_type == "entity":
            return KnowledgeGraphEntity, KnowledgeGraphEntity.entity_id
        if record_type == "triple":
            return KnowledgeGraphTriple, KnowledgeGraphTriple.triple_id
        raise ValueError(f"Unsupported graph vector record type: {record_type}")

    @staticmethod
    async def _entity_vector_payloads(
        session,
        *,
        kb_id: str,
        records: list[Any],
        include_evidence_rows: bool,
    ) -> list[dict[str, Any]]:
        """聚合已审核别名与关系邻域，避免 pending 候选污染实体向量。"""
        entity_ids = [str(record.entity_id) for record in records]
        if not entity_ids:
            return []
        mention_rows = (
            await session.execute(
                select(
                    KnowledgeGraphEntityMention.id,
                    KnowledgeGraphEntityMention.entity_id,
                    KnowledgeGraphEntityMention.mention_text,
                ).where(
                    KnowledgeGraphEntityMention.kb_id == kb_id,
                    KnowledgeGraphEntityMention.entity_id.in_(entity_ids),
                    KnowledgeGraphEntityMention.review_status == "accepted",
                    KnowledgeGraphEntityMention.mention_text.is_not(None),
                )
            )
        ).all()
        alias_rows = (
            await session.execute(
                select(
                    KnowledgeGraphEntityAlias.entity_id,
                    KnowledgeGraphEntityAlias.alias,
                    KnowledgeGraphEntityAlias.source,
                ).where(KnowledgeGraphEntityAlias.entity_id.in_(entity_ids))
            )
        ).all()
        source_entity = aliased(KnowledgeGraphEntity)
        target_entity = aliased(KnowledgeGraphEntity)
        relation_rows = (
            await session.execute(
                select(
                    KnowledgeGraphTriple.triple_id,
                    KnowledgeGraphTriple.source_entity_id,
                    KnowledgeGraphTriple.target_entity_id,
                    KnowledgeGraphTriple.relation_type,
                    source_entity.name,
                    source_entity.label,
                    target_entity.name,
                    target_entity.label,
                )
                .join(source_entity, source_entity.entity_id == KnowledgeGraphTriple.source_entity_id)
                .join(target_entity, target_entity.entity_id == KnowledgeGraphTriple.target_entity_id)
                .where(
                    KnowledgeGraphTriple.kb_id == kb_id,
                    KnowledgeGraphTriple.lifecycle_status == "active",
                    source_entity.lifecycle_status == "active",
                    target_entity.lifecycle_status == "active",
                    or_(
                        KnowledgeGraphTriple.source_entity_id.in_(entity_ids),
                        KnowledgeGraphTriple.target_entity_id.in_(entity_ids),
                    ),
                    exists(
                        select(KnowledgeGraphTripleMention.id).where(
                            KnowledgeGraphTripleMention.triple_id == KnowledgeGraphTriple.triple_id,
                            KnowledgeGraphTripleMention.review_status == "accepted",
                            KnowledgeGraphTripleMention.claim_level.in_(["Fact", "Inference"]),
                        )
                    ),
                )
            )
        ).all()

        relation_evidence_rows = []
        if include_evidence_rows:
            relation_evidence_rows = (
                await session.execute(
                    select(
                        KnowledgeGraphTripleMention.id,
                        KnowledgeGraphTriple.source_entity_id,
                        KnowledgeGraphTriple.target_entity_id,
                        KnowledgeGraphTripleMention.evidence_quote,
                        KnowledgeGraphTripleMention.text,
                    )
                    .join(
                        KnowledgeGraphTriple,
                        KnowledgeGraphTriple.triple_id == KnowledgeGraphTripleMention.triple_id,
                    )
                    .where(
                        KnowledgeGraphTripleMention.kb_id == kb_id,
                        KnowledgeGraphTripleMention.review_status == "accepted",
                        KnowledgeGraphTripleMention.claim_level.in_(["Fact", "Inference"]),
                        KnowledgeGraphTriple.lifecycle_status == "active",
                        or_(
                            KnowledgeGraphTriple.source_entity_id.in_(entity_ids),
                            KnowledgeGraphTriple.target_entity_id.in_(entity_ids),
                        ),
                    )
                    .order_by(KnowledgeGraphTripleMention.id.asc())
                    .limit(
                        max(
                            len(entity_ids) * KnowledgeGraphRepository.VECTOR_EVIDENCE_QUERY_LIMIT_PER_ENTITY,
                            KnowledgeGraphRepository.VECTOR_EVIDENCE_QUERY_LIMIT_PER_ENTITY,
                        )
                    )
                )
            ).all()

        mentions_by_id: dict[str, list[str]] = {entity_id: [] for entity_id in entity_ids}
        evidence_rows_by_id: dict[str, list[dict[str, str]]] = {entity_id: [] for entity_id in entity_ids}
        for mention_id, entity_id, mention_text in mention_rows:
            mentions_by_id.setdefault(str(entity_id), []).append(str(mention_text))
            if include_evidence_rows:
                evidence_rows_by_id.setdefault(str(entity_id), []).append(
                    {
                        "evidence_id": f"entity-mention:{mention_id}",
                        "kind": "entity_mention",
                        "text": str(mention_text),
                    }
                )
        accepted_alias_keys = {
            entity_id: {" ".join(value.split()).casefold() for value in values}
            for entity_id, values in mentions_by_id.items()
        }
        trusted_aliases_by_id: dict[str, list[str]] = {entity_id: [] for entity_id in entity_ids}
        for entity_id, alias, source in alias_rows:
            normalized_id = str(entity_id)
            alias_text = str(alias or "").strip()
            alias_key = " ".join(alias_text.split()).casefold()
            if str(source or "") != "extraction" or alias_key in accepted_alias_keys.get(normalized_id, set()):
                trusted_aliases_by_id.setdefault(normalized_id, []).append(alias_text)

        relations_by_id: dict[str, list[dict[str, Any]]] = {entity_id: [] for entity_id in entity_ids}
        for (
            triple_id,
            source_id,
            target_id,
            relation_type,
            source_name,
            source_label,
            target_name,
            target_label,
        ) in relation_rows:
            relation = {
                "triple_id": str(triple_id),
                "source_entity_id": str(source_id),
                "target_entity_id": str(target_id),
                "relation_type": str(relation_type),
                "source_name": str(source_name),
                "source_label": str(source_label),
                "target_name": str(target_name),
                "target_label": str(target_label),
            }
            if str(source_id) in relations_by_id:
                relations_by_id[str(source_id)].append(relation)
            if str(target_id) in relations_by_id:
                relations_by_id[str(target_id)].append(relation)

        for mention_id, source_id, target_id, evidence_quote, mention_text in relation_evidence_rows:
            text = str(evidence_quote or mention_text or "").strip()
            if not text:
                continue
            row = {
                "evidence_id": f"relation-mention:{mention_id}",
                "kind": "relation_evidence",
                "text": text,
            }
            if str(source_id) in evidence_rows_by_id:
                evidence_rows_by_id[str(source_id)].append(row)
            if str(target_id) in evidence_rows_by_id:
                evidence_rows_by_id[str(target_id)].append(row)

        return [
            {
                "id": str(record.entity_id),
                "content": build_entity_semantic_profile(
                    entity_id=str(record.entity_id),
                    name=str(record.name or ""),
                    normalized_name=str(record.normalized_name or ""),
                    label=str(record.label or ""),
                    accepted_mentions=mentions_by_id.get(str(record.entity_id), []),
                    trusted_aliases=trusted_aliases_by_id.get(str(record.entity_id), []),
                    accepted_relations=relations_by_id.get(str(record.entity_id), []),
                ),
                **(
                    {"evidence_rows": evidence_rows_by_id.get(str(record.entity_id), [])}
                    if include_evidence_rows
                    else {}
                ),
            }
            for record in records
        ]

    @staticmethod
    async def _triple_vector_payloads(
        session,
        *,
        kb_id: str,
        records: list[Any],
        include_evidence_rows: bool,
    ) -> list[dict[str, Any]]:
        """聚合 active 关系的跨文档证据，统一生成 LightRAG 关系向量。"""

        triple_ids = [str(record.triple_id) for record in records]
        if not triple_ids:
            return []
        entity_ids = {
            str(entity_id) for record in records for entity_id in (record.source_entity_id, record.target_entity_id)
        }
        entity_rows = list(
            (
                await session.execute(
                    select(KnowledgeGraphEntity).where(
                        KnowledgeGraphEntity.kb_id == kb_id,
                        KnowledgeGraphEntity.entity_id.in_(entity_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        entity_by_id = {str(entity.entity_id): entity for entity in entity_rows}
        mention_rows = (
            await session.execute(
                select(
                    KnowledgeGraphTripleMention.id,
                    KnowledgeGraphTripleMention.triple_id,
                    KnowledgeGraphTripleMention.file_id,
                    KnowledgeGraphTripleMention.claim_level,
                    KnowledgeGraphTripleMention.evidence_quote,
                    KnowledgeGraphTripleMention.text,
                    KnowledgeGraphTripleMention.reasoning_basis,
                    KnowledgeGraphTripleMention.applicable_conditions,
                    KnowledgeGraphTripleMention.review_status,
                )
                .where(
                    KnowledgeGraphTripleMention.kb_id == kb_id,
                    KnowledgeGraphTripleMention.triple_id.in_(triple_ids),
                    KnowledgeGraphTripleMention.review_status.in_(["accepted", "pending"]),
                )
                .order_by(KnowledgeGraphTripleMention.triple_id.asc(), KnowledgeGraphTripleMention.id.asc())
                .limit(
                    max(
                        len(triple_ids) * KnowledgeGraphRepository.VECTOR_EVIDENCE_QUERY_LIMIT_PER_ENTITY,
                        KnowledgeGraphRepository.VECTOR_EVIDENCE_QUERY_LIMIT_PER_ENTITY,
                    )
                )
            )
        ).all()
        mentions_by_id: dict[str, list[dict[str, Any]]] = {triple_id: [] for triple_id in triple_ids}
        for (
            mention_id,
            triple_id,
            file_id,
            claim_level,
            evidence_quote,
            text,
            reasoning_basis,
            conditions,
            review_status,
        ) in mention_rows:
            mentions_by_id.setdefault(str(triple_id), []).append(
                {
                    "mention_id": int(mention_id),
                    "file_id": str(file_id),
                    "claim_level": str(claim_level),
                    "evidence_quote": str(evidence_quote or text or ""),
                    "reasoning_basis": str(reasoning_basis or ""),
                    "applicable_conditions": list(conditions or []),
                    "review_status": str(review_status or "pending"),
                }
            )

        payloads = []
        for record in records:
            source = entity_by_id.get(str(record.source_entity_id))
            target = entity_by_id.get(str(record.target_entity_id))
            relation_mentions = mentions_by_id.get(str(record.triple_id), [])
            payload = {
                "id": str(record.triple_id),
                "content": build_relation_semantic_profile(
                    relation_type=str(record.relation_type),
                    source_name=str(source.name if source is not None else record.source_entity_id),
                    source_label=str(source.label if source is not None else ""),
                    target_name=str(target.name if target is not None else record.target_entity_id),
                    target_label=str(target.label if target is not None else ""),
                    base_content=str(record.content or ""),
                    relation_mentions=relation_mentions,
                ),
                "source_id": str(record.source_entity_id),
                "target_id": str(record.target_entity_id),
            }
            if include_evidence_rows:
                payload["evidence_rows"] = [
                    {
                        "evidence_id": f"relation-mention:{item['mention_id']}",
                        "kind": "relation_evidence",
                        "text": str(item["evidence_quote"]),
                    }
                    for item in relation_mentions
                    if item["evidence_quote"]
                ]
            payloads.append(payload)
        return payloads

    async def align_graph_records(
        self,
        *,
        kb_id: str,
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """按标准名和别名对齐，并返回需继续语义消歧的候选。"""
        if not entities:
            return {"unresolved_entity_ids": [], "ambiguous_candidates": {}}
        identity_keys = {(str(item["normalized_name"]), str(item["label"])) for item in entities}
        conditions = [
            and_(KnowledgeGraphEntity.normalized_name == name, KnowledgeGraphEntity.label == label)
            for name, label in identity_keys
        ]
        alias_conditions = [
            and_(KnowledgeGraphEntityAlias.normalized_alias == name, KnowledgeGraphEntity.label == label)
            for name, label in identity_keys
        ]
        async with pg_manager.get_async_session_context() as session:
            exact_rows = (
                await session.execute(
                    select(
                        KnowledgeGraphEntity.normalized_name,
                        KnowledgeGraphEntity.label,
                        KnowledgeGraphEntity.entity_id,
                        KnowledgeGraphEntity.name,
                    ).where(KnowledgeGraphEntity.kb_id == kb_id, or_(*conditions))
                )
            ).all()
            alias_rows = (
                await session.execute(
                    select(
                        KnowledgeGraphEntityAlias.normalized_alias,
                        KnowledgeGraphEntity.label,
                        KnowledgeGraphEntityAlias.entity_id,
                        KnowledgeGraphEntity.name,
                        KnowledgeGraphEntity.normalized_name,
                    )
                    .join(
                        KnowledgeGraphEntity,
                        KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityAlias.entity_id,
                    )
                    .where(KnowledgeGraphEntity.kb_id == kb_id, or_(*alias_conditions))
                )
            ).all()

            resolved = {
                (str(name), str(label)): {
                    "entity_id": str(entity_id),
                    "name": str(canonical_name),
                    "normalized_name": str(name),
                    "label": str(label),
                }
                for name, label, entity_id, canonical_name in exact_rows
            }
            alias_candidates: dict[tuple[str, str], set[str]] = {}
            alias_profiles = {}
            for name, label, entity_id, canonical_name, canonical_normalized_name in alias_rows:
                alias_candidates.setdefault((str(name), str(label)), set()).add(str(entity_id))
                alias_profiles[str(entity_id)] = {
                    "entity_id": str(entity_id),
                    "name": str(canonical_name),
                    "normalized_name": str(canonical_normalized_name),
                    "label": str(label),
                }
            for key, candidates in alias_candidates.items():
                if key not in resolved and len(candidates) == 1:
                    resolved[key] = alias_profiles[next(iter(candidates))]

            id_redirect = {}
            unresolved_entity_ids = []
            ambiguous_candidates = {}
            for entity in entities:
                incoming_id = str(entity["entity_id"])
                key = (str(entity["normalized_name"]), str(entity["label"]))
                stable_profile = resolved.get(key)
                if stable_profile is None:
                    unresolved_entity_ids.append(incoming_id)
                    candidates = sorted(alias_candidates.get(key, set()))
                    if len(candidates) > 1:
                        ambiguous_candidates[incoming_id] = candidates
                    continue
                stable_id = stable_profile["entity_id"]
                id_redirect[incoming_id] = stable_id
                entity["entity_id"] = stable_id
                entity["name"] = stable_profile["name"]
                entity["normalized_name"] = stable_profile["normalized_name"]
                entity["label"] = stable_profile["label"]
            for triple in triples:
                triple["source_entity_id"] = id_redirect.get(
                    str(triple["source_entity_id"]),
                    str(triple["source_entity_id"]),
                )
                triple["target_entity_id"] = id_redirect.get(
                    str(triple["target_entity_id"]),
                    str(triple["target_entity_id"]),
                )

            if not triples:
                return {
                    "unresolved_entity_ids": unresolved_entity_ids,
                    "ambiguous_candidates": ambiguous_candidates,
                }
            triple_keys = {
                (
                    str(item["source_entity_id"]),
                    str(item["relation_type"]),
                    str(item["target_entity_id"]),
                )
                for item in triples
            }
            triple_conditions = [
                and_(
                    KnowledgeGraphTriple.source_entity_id == source_id,
                    KnowledgeGraphTriple.relation_type == relation_type,
                    KnowledgeGraphTriple.target_entity_id == target_id,
                )
                for source_id, relation_type, target_id in triple_keys
            ]
            existing_triples = (
                await session.execute(
                    select(
                        KnowledgeGraphTriple.source_entity_id,
                        KnowledgeGraphTriple.relation_type,
                        KnowledgeGraphTriple.target_entity_id,
                        KnowledgeGraphTriple.triple_id,
                    ).where(KnowledgeGraphTriple.kb_id == kb_id, or_(*triple_conditions))
                )
            ).all()
            triple_id_by_key = {
                (str(source_id), str(relation_type), str(target_id)): str(triple_id)
                for source_id, relation_type, target_id, triple_id in existing_triples
            }
            for triple in triples:
                key = (
                    str(triple["source_entity_id"]),
                    str(triple["relation_type"]),
                    str(triple["target_entity_id"]),
                )
                triple["triple_id"] = triple_id_by_key.get(key) or relation_uuid(kb_id, *key)
            return {
                "unresolved_entity_ids": unresolved_entity_ids,
                "ambiguous_candidates": ambiguous_candidates,
            }

    async def load_entity_alignment_profiles(
        self,
        *,
        kb_id: str,
        entity_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """批量读取语义对齐所需的实体类型、别名、属性和关系邻域。"""
        unique_ids = list(dict.fromkeys(str(entity_id) for entity_id in entity_ids if entity_id))
        if not unique_ids:
            return {}
        async with pg_manager.get_async_session_context() as session:
            entities = list(
                (
                    await session.execute(
                        select(KnowledgeGraphEntity).where(
                            KnowledgeGraphEntity.kb_id == kb_id,
                            KnowledgeGraphEntity.entity_id.in_(unique_ids),
                            KnowledgeGraphEntity.lifecycle_status == "active",
                        )
                    )
                )
                .scalars()
                .all()
            )
            found_ids = [str(entity.entity_id) for entity in entities]
            alias_rows = []
            triple_rows = []
            if found_ids:
                alias_rows = (
                    await session.execute(
                        select(KnowledgeGraphEntityAlias.entity_id, KnowledgeGraphEntityAlias.alias).where(
                            KnowledgeGraphEntityAlias.entity_id.in_(found_ids)
                        )
                    )
                ).all()
                triple_rows = (
                    await session.execute(
                        select(
                            KnowledgeGraphTriple.source_entity_id,
                            KnowledgeGraphTriple.target_entity_id,
                        ).where(
                            KnowledgeGraphTriple.kb_id == kb_id,
                            KnowledgeGraphTriple.lifecycle_status == "active",
                            or_(
                                KnowledgeGraphTriple.source_entity_id.in_(found_ids),
                                KnowledgeGraphTriple.target_entity_id.in_(found_ids),
                            ),
                            exists(
                                select(KnowledgeGraphTripleMention.id).where(
                                    KnowledgeGraphTripleMention.kb_id == kb_id,
                                    KnowledgeGraphTripleMention.triple_id == KnowledgeGraphTriple.triple_id,
                                    KnowledgeGraphTripleMention.review_status == "accepted",
                                    KnowledgeGraphTripleMention.claim_level.in_(["Fact", "Inference"]),
                                )
                            ),
                        )
                    )
                ).all()
            neighbor_ids = {
                str(entity_id)
                for source_id, target_id in triple_rows
                for entity_id in (source_id, target_id)
                if str(entity_id) not in found_ids
            }
            neighbor_rows = []
            if neighbor_ids:
                neighbor_rows = (
                    await session.execute(
                        select(
                            KnowledgeGraphEntity.entity_id,
                            KnowledgeGraphEntity.name,
                            KnowledgeGraphEntity.label,
                        ).where(
                            KnowledgeGraphEntity.kb_id == kb_id,
                            KnowledgeGraphEntity.entity_id.in_(neighbor_ids),
                        )
                    )
                ).all()

        aliases_by_id: dict[str, list[str]] = {}
        for entity_id, alias in alias_rows:
            aliases_by_id.setdefault(str(entity_id), []).append(str(alias))
        neighbor_name_by_id = {str(entity_id): f"{name} [{label}]" for entity_id, name, label in neighbor_rows}
        neighbors_by_id: dict[str, list[str]] = {entity_id: [] for entity_id in found_ids}
        for source_id, target_id in triple_rows:
            source = str(source_id)
            target = str(target_id)
            if source in neighbors_by_id and target in neighbor_name_by_id:
                neighbors_by_id[source].append(neighbor_name_by_id[target])
            if target in neighbors_by_id and source in neighbor_name_by_id:
                neighbors_by_id[target].append(neighbor_name_by_id[source])
        return {
            str(entity.entity_id): {
                "entity_id": str(entity.entity_id),
                "normalized_name": entity.normalized_name,
                "name": entity.name,
                "label": entity.label,
                "attributes": entity.attributes,
                "aliases": aliases_by_id.get(str(entity.entity_id), []),
                "neighbors": neighbors_by_id.get(str(entity.entity_id), []),
            }
            for entity in entities
        }

    async def load_entity_type_conflict_profiles(
        self,
        *,
        kb_id: str,
        normalized_names: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """读取同名跨类型实体及其 mention 证据统计，供封闭判型使用。"""

        names = list(dict.fromkeys(str(item).strip() for item in normalized_names if str(item).strip()))
        if not names:
            return {}
        async with pg_manager.get_async_session_context() as session:
            entities = list(
                (
                    await session.scalars(
                        select(KnowledgeGraphEntity).where(
                            KnowledgeGraphEntity.kb_id == kb_id,
                            KnowledgeGraphEntity.normalized_name.in_(names),
                            KnowledgeGraphEntity.lifecycle_status == "active",
                        )
                    )
                ).all()
            )
            entity_ids = [str(entity.entity_id) for entity in entities]
            mentions = []
            if entity_ids:
                mentions = list(
                    (
                        await session.scalars(
                            select(KnowledgeGraphEntityMention).where(
                                KnowledgeGraphEntityMention.kb_id == kb_id,
                                KnowledgeGraphEntityMention.entity_id.in_(entity_ids),
                                KnowledgeGraphEntityMention.review_status.notin_(["rejected", "superseded"]),
                            )
                        )
                    ).all()
                )

        mentions_by_id: dict[str, list[Any]] = {}
        for mention in mentions:
            mentions_by_id.setdefault(str(mention.entity_id), []).append(mention)
        profiles: dict[str, list[dict[str, Any]]] = {}
        for entity in entities:
            entity_id = str(entity.entity_id)
            entity_mentions = mentions_by_id.get(entity_id, [])
            confidences = [float(mention.confidence) for mention in entity_mentions if mention.confidence is not None]
            profiles.setdefault(str(entity.normalized_name), []).append(
                {
                    "entity_id": entity_id,
                    "normalized_name": str(entity.normalized_name),
                    "name": str(entity.name),
                    "label": str(entity.label),
                    "attributes": entity.attributes or [],
                    "mention_count": len(entity_mentions),
                    "accepted_mention_count": sum(
                        str(mention.review_status) == "accepted" for mention in entity_mentions
                    ),
                    "source_file_count": len({str(mention.file_id) for mention in entity_mentions}),
                    "average_confidence": (round(sum(confidences) / len(confidences), 4) if confidences else None),
                    "model_versions": sorted(
                        {
                            str(mention.model_version)
                            for mention in entity_mentions
                            if str(mention.model_version or "").strip()
                        }
                    ),
                }
            )
        for candidates in profiles.values():
            candidates.sort(
                key=lambda item: (
                    -int(item["accepted_mention_count"]),
                    -int(item["source_file_count"]),
                    -int(item["mention_count"]),
                    str(item["label"]),
                    str(item["entity_id"]),
                )
            )
        return profiles

    async def allocate_entity_ids(
        self,
        *,
        kb_id: str,
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
        provisional_entity_ids: set[str],
    ) -> dict[str, str]:
        """按身份唯一键原子分配随机 UUID，并在并发冲突时复用既有 ID。"""
        selected = [entity for entity in entities if str(entity["entity_id"]) in provisional_entity_ids]
        if not selected:
            return {}
        redirects = {}
        async with pg_manager.get_async_session_context() as session:
            for entity in selected:
                provisional_id = str(entity["entity_id"])
                statement = insert(KnowledgeGraphEntity).values(
                    entity_id=provisional_id,
                    kb_id=kb_id,
                    normalized_name=entity["normalized_name"],
                    label=entity["label"],
                    name=entity["name"],
                    attributes=entity.get("attributes"),
                )
                allocated_id = await session.scalar(
                    statement.on_conflict_do_update(
                        index_elements=["kb_id", "normalized_name", "label"],
                        set_={"updated_at": func.now()},
                    ).returning(KnowledgeGraphEntity.entity_id)
                )
                if allocated_id is None:
                    raise RuntimeError("PostgreSQL 未返回已分配的实体 UUID")
                actual_id = str(allocated_id)
                redirects[provisional_id] = actual_id
                entity["entity_id"] = actual_id
        for triple in triples:
            triple["source_entity_id"] = redirects.get(
                str(triple["source_entity_id"]),
                str(triple["source_entity_id"]),
            )
            triple["target_entity_id"] = redirects.get(
                str(triple["target_entity_id"]),
                str(triple["target_entity_id"]),
            )
        return redirects

    async def hydrate_triple_lifecycle(self, *, kb_id: str, triples: list[dict[str, Any]]) -> None:
        """把既有权威关系生命周期带入新投影，避免重抽取复活失效关系。"""
        triple_ids = [str(item["triple_id"]) for item in triples if item.get("triple_id")]
        if not triple_ids:
            return
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeGraphTriple.triple_id,
                        KnowledgeGraphTriple.lifecycle_status,
                        KnowledgeGraphTriple.superseded_by_triple_id,
                        KnowledgeGraphTriple.relation_version,
                    ).where(
                        KnowledgeGraphTriple.kb_id == kb_id,
                        KnowledgeGraphTriple.triple_id.in_(triple_ids),
                    )
                )
            ).all()
        lifecycle_by_id = {
            str(triple_id): {
                "lifecycle_status": lifecycle_status,
                "superseded_by_triple_id": superseded_by_triple_id,
                "relation_version": int(relation_version or 1),
            }
            for triple_id, lifecycle_status, superseded_by_triple_id, relation_version in rows
        }
        for triple in triples:
            triple.update(
                lifecycle_by_id.get(
                    str(triple["triple_id"]),
                    {
                        "lifecycle_status": "active",
                        "superseded_by_triple_id": None,
                        "relation_version": 1,
                    },
                )
            )

    async def upsert_chunk_graph(
        self,
        *,
        kb_id: str,
        file_id: str,
        chunk_id: str,
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
        projection_event: dict[str, Any] | None = None,
        preserve_reviewed_mentions: bool = False,
    ) -> str | None:
        """原子写入权威知识和可重放投影事件。"""
        entity_mention_fields = {
            "mention_text",
            "start_char",
            "end_char",
            "confidence",
            "model_version",
            "ontology_version",
            "review_status",
        }
        triple_mention_fields = {
            "text",
            "extractor_type",
            "claim_level",
            "confidence",
            "evidence_quote",
            "evidence_spans",
            "reasoning_basis",
            "applicable_conditions",
            "secondary_review",
            "uncertainty",
            "expert_review_required",
            "review_status",
            "model_version",
            "ontology_version",
            "pipeline_revision",
        }
        async with pg_manager.get_async_session_context() as session:
            if entities:
                entity_rows_by_id = {}
                for entity in entities:
                    entity_rows_by_id.setdefault(
                        str(entity["entity_id"]),
                        {
                            key: value
                            for key, value in entity.items()
                            if key not in {"content", "block_id", "aliases", "naming_rationale"}
                            and key not in entity_mention_fields
                        },
                    )
                entity_rows = list(entity_rows_by_id.values())
                entity_stmt = insert(KnowledgeGraphEntity).values(entity_rows)
                await session.execute(
                    entity_stmt.on_conflict_do_update(
                        index_elements=["entity_id"],
                        set_={
                            "updated_at": func.now(),
                        },
                    )
                )
                alias_rows_by_key = {}
                for entity in entities:
                    extra_aliases = entity.get("aliases")
                    if not isinstance(extra_aliases, list):
                        extra_aliases = []
                    alias_values = [entity.get("mention_text") or entity["name"], *extra_aliases[:16]]
                    for alias_value in alias_values:
                        alias = canonical_entity_display_name(str(alias_value or ""))
                        normalized_alias = normalize_entity_name(alias)
                        if not alias or len(alias) > 512 or not normalized_alias:
                            continue
                        alias_row = {
                            "entity_id": entity["entity_id"],
                            "alias": alias,
                            "normalized_alias": normalized_alias,
                            "language": "unknown",
                            "source": "extraction",
                            "confidence": entity.get("confidence"),
                        }
                        alias_rows_by_key.setdefault(
                            (
                                str(alias_row["entity_id"]),
                                str(alias_row["normalized_alias"]),
                                str(alias_row["language"]),
                            ),
                            alias_row,
                        )
                alias_rows = list(alias_rows_by_key.values())
                alias_stmt = insert(KnowledgeGraphEntityAlias).values(alias_rows)
                await session.execute(
                    alias_stmt.on_conflict_do_nothing(index_elements=["entity_id", "normalized_alias", "language"])
                )
                entity_mentions_by_key = {}
                for entity in entities:
                    row = {
                        "entity_id": entity["entity_id"],
                        "kb_id": kb_id,
                        "file_id": file_id,
                        "chunk_id": chunk_id,
                        **{field: entity.get(field) for field in entity_mention_fields},
                        "review_status": entity.get("review_status") or "pending",
                    }
                    has_span = row.get("start_char") is not None and row.get("end_char") is not None
                    key = (
                        str(row["entity_id"]),
                        chunk_id,
                        row.get("start_char") if has_span else None,
                        row.get("end_char") if has_span else None,
                    )
                    current = entity_mentions_by_key.get(key)
                    if current is None or float(row.get("confidence") or 0) > float(current.get("confidence") or 0):
                        entity_mentions_by_key[key] = row
                spanned_rows = []
                unspanned_rows = []
                for row in entity_mentions_by_key.values():
                    target = (
                        spanned_rows
                        if row.get("start_char") is not None and row.get("end_char") is not None
                        else unspanned_rows
                    )
                    target.append(row)

                if spanned_rows:
                    entity_mention_stmt = insert(KnowledgeGraphEntityMention).values(spanned_rows)
                    entity_mention_updates = {
                        field: getattr(entity_mention_stmt.excluded, field) for field in entity_mention_fields
                    }
                    if preserve_reviewed_mentions:
                        entity_mention_updates["review_status"] = case(
                            (
                                KnowledgeGraphEntityMention.review_status != "pending",
                                KnowledgeGraphEntityMention.review_status,
                            ),
                            else_=entity_mention_stmt.excluded.review_status,
                        )
                    await session.execute(
                        entity_mention_stmt.on_conflict_do_update(
                            index_elements=["entity_id", "chunk_id", "start_char", "end_char"],
                            index_where=(
                                KnowledgeGraphEntityMention.start_char.is_not(None)
                                & KnowledgeGraphEntityMention.end_char.is_not(None)
                            ),
                            set_=entity_mention_updates,
                        )
                    )
                if unspanned_rows:
                    entity_mention_stmt = insert(KnowledgeGraphEntityMention).values(unspanned_rows)
                    entity_mention_updates = {
                        field: getattr(entity_mention_stmt.excluded, field) for field in entity_mention_fields
                    }
                    if preserve_reviewed_mentions:
                        entity_mention_updates["review_status"] = case(
                            (
                                KnowledgeGraphEntityMention.review_status != "pending",
                                KnowledgeGraphEntityMention.review_status,
                            ),
                            else_=entity_mention_stmt.excluded.review_status,
                        )
                    await session.execute(
                        entity_mention_stmt.on_conflict_do_update(
                            index_elements=["entity_id", "chunk_id"],
                            index_where=(
                                KnowledgeGraphEntityMention.start_char.is_(None)
                                | KnowledgeGraphEntityMention.end_char.is_(None)
                            ),
                            set_=entity_mention_updates,
                        )
                    )

            if triples:
                triples_by_id = {}
                for triple in triples:
                    triples_by_id.setdefault(str(triple["triple_id"]), triple)
                unique_triples = list(triples_by_id.values())
                triple_rows = [
                    {key: value for key, value in triple.items() if key not in triple_mention_fields}
                    for triple in unique_triples
                ]
                triple_stmt = insert(KnowledgeGraphTriple).values(triple_rows)
                await session.execute(
                    triple_stmt.on_conflict_do_update(
                        index_elements=["triple_id"],
                        set_={
                            "content": triple_stmt.excluded.content,
                            "relation_type": triple_stmt.excluded.relation_type,
                            "updated_at": func.now(),
                        },
                    )
                )
                triple_mention_stmt = insert(KnowledgeGraphTripleMention).values(
                    [
                        {
                            "triple_id": triple["triple_id"],
                            "kb_id": kb_id,
                            "file_id": file_id,
                            "chunk_id": chunk_id,
                            **{field: triple.get(field) for field in triple_mention_fields},
                            "expert_review_required": (
                                True
                                if triple.get("expert_review_required") is None
                                else bool(triple["expert_review_required"])
                            ),
                            "review_status": triple.get("review_status") or "pending",
                        }
                        for triple in unique_triples
                    ]
                )
                mention_updates = {
                    field: getattr(triple_mention_stmt.excluded, field) for field in triple_mention_fields
                }
                if preserve_reviewed_mentions:
                    mention_updates["review_status"] = case(
                        (
                            KnowledgeGraphTripleMention.review_status != "pending",
                            KnowledgeGraphTripleMention.review_status,
                        ),
                        else_=triple_mention_stmt.excluded.review_status,
                    )
                await session.execute(
                    triple_mention_stmt.on_conflict_do_update(
                        index_elements=["triple_id", "chunk_id"],
                        set_=mention_updates,
                    )
                )

            if projection_event is None:
                return None

            revision_stmt = insert(KnowledgeGraphRevision).values(
                revision_id=projection_event["graph_revision"],
                kb_id=kb_id,
                ontology_version=projection_event["ontology_version"],
                reason=projection_event.get("reason") or "chunk_graph_upsert",
                summary=projection_event.get("summary") or {},
            )
            await session.execute(revision_stmt.on_conflict_do_nothing(index_elements=["revision_id"]))
            outbox_stmt = insert(KnowledgeGraphProjectionOutbox).values(
                event_id=projection_event["event_id"],
                kb_id=kb_id,
                chunk_id=chunk_id,
                graph_revision=projection_event["graph_revision"],
                payload=projection_event["payload"],
                status="pending",
            )
            await session.execute(outbox_stmt.on_conflict_do_nothing(index_elements=["chunk_id", "graph_revision"]))
            return str(projection_event["event_id"])

    async def claim_projection_events(
        self,
        *,
        kb_id: str | None,
        limit: int,
        lease_seconds: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        """以 SKIP LOCKED 领取待投影事件；空知识库范围用于后台全局消费。"""
        now = datetime.now(UTC)
        claimable = or_(
            (
                (KnowledgeGraphProjectionOutbox.status == "pending")
                & or_(
                    KnowledgeGraphProjectionOutbox.next_retry_at.is_(None),
                    KnowledgeGraphProjectionOutbox.next_retry_at <= now,
                )
            ),
            (
                (KnowledgeGraphProjectionOutbox.status == "processing")
                & (KnowledgeGraphProjectionOutbox.locked_until < now)
            ),
        )
        token = uuid.uuid4().hex
        conditions = [claimable]
        if kb_id is not None:
            conditions.insert(0, KnowledgeGraphProjectionOutbox.kb_id == kb_id)
        async with pg_manager.get_async_session_context() as session:
            records = list(
                (
                    await session.execute(
                        select(KnowledgeGraphProjectionOutbox)
                        .where(*conditions)
                        .order_by(KnowledgeGraphProjectionOutbox.created_at.asc())
                        .limit(max(limit, 1))
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )
            for record in records:
                record.status = "processing"
                record.attempt_count = int(record.attempt_count or 0) + 1
                record.locked_until = now + timedelta(seconds=lease_seconds)
                record.lock_token = token
                record.last_error = None
            return token, [
                {
                    "event_id": record.event_id,
                    "kb_id": record.kb_id,
                    "graph_revision": record.graph_revision,
                    "payload": record.payload,
                }
                for record in records
            ]

    async def mark_projection_event_completed(self, *, event_id: str, lock_token: str | None = None) -> bool:
        """完成仍由当前租约持有的投影事件。"""
        conditions = [KnowledgeGraphProjectionOutbox.event_id == event_id]
        if lock_token is not None:
            conditions.append(KnowledgeGraphProjectionOutbox.lock_token == lock_token)
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                update(KnowledgeGraphProjectionOutbox)
                .where(*conditions)
                .values(
                    status="completed",
                    last_error=None,
                    next_retry_at=None,
                    locked_until=None,
                    lock_token=None,
                    updated_at=func.now(),
                )
            )
            return bool(result.rowcount)

    async def mark_projection_event_failed(self, *, event_id: str, lock_token: str, error: str) -> bool:
        """记录投影失败并按次数退避，达到上限后进入失败队列。"""
        now = datetime.now(UTC)
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                update(KnowledgeGraphProjectionOutbox)
                .where(
                    KnowledgeGraphProjectionOutbox.event_id == event_id,
                    KnowledgeGraphProjectionOutbox.lock_token == lock_token,
                )
                .values(
                    status=case(
                        (
                            KnowledgeGraphProjectionOutbox.attempt_count >= self.PROJECTION_MAX_ATTEMPTS,
                            "failed",
                        ),
                        else_="pending",
                    ),
                    last_error=error[:4000],
                    next_retry_at=case(
                        (KnowledgeGraphProjectionOutbox.attempt_count == 1, now + timedelta(seconds=5)),
                        (KnowledgeGraphProjectionOutbox.attempt_count == 2, now + timedelta(seconds=30)),
                        (KnowledgeGraphProjectionOutbox.attempt_count == 3, now + timedelta(seconds=120)),
                        (KnowledgeGraphProjectionOutbox.attempt_count == 4, now + timedelta(seconds=300)),
                        else_=None,
                    ),
                    locked_until=None,
                    lock_token=None,
                    updated_at=func.now(),
                )
            )
            return bool(result.rowcount)

    async def count_projection_statuses(self, kb_id: str) -> dict[str, int]:
        """返回投影 outbox 状态汇总。"""
        counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(KnowledgeGraphProjectionOutbox.status, func.count())
                    .where(KnowledgeGraphProjectionOutbox.kb_id == kb_id)
                    .group_by(KnowledgeGraphProjectionOutbox.status)
                )
            ).all()
        for status, count in rows:
            counts[str(status)] = int(count or 0)
        return counts

    async def delete_file_references(self, file_id: str) -> tuple[list[str], list[str]]:
        async with pg_manager.get_async_session_context() as session:
            affected_entity_ids = list(
                (
                    await session.execute(
                        select(KnowledgeGraphEntityMention.entity_id)
                        .where(KnowledgeGraphEntityMention.file_id == file_id)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            affected_triple_ids = list(
                (
                    await session.execute(
                        select(KnowledgeGraphTripleMention.triple_id)
                        .where(KnowledgeGraphTripleMention.file_id == file_id)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )

            await session.execute(
                delete(KnowledgeGraphTripleMention).where(KnowledgeGraphTripleMention.file_id == file_id)
            )
            await session.execute(
                delete(KnowledgeGraphEntityMention).where(KnowledgeGraphEntityMention.file_id == file_id)
            )

            orphan_triple_ids: list[str] = []
            if affected_triple_ids:
                triple_has_mentions = exists().where(
                    KnowledgeGraphTripleMention.triple_id == KnowledgeGraphTriple.triple_id
                )
                orphan_triple_ids = list(
                    (
                        await session.execute(
                            select(KnowledgeGraphTriple.triple_id).where(
                                KnowledgeGraphTriple.triple_id.in_(affected_triple_ids),
                                ~triple_has_mentions,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if orphan_triple_ids:
                    await session.execute(
                        delete(KnowledgeGraphTriple).where(KnowledgeGraphTriple.triple_id.in_(orphan_triple_ids))
                    )

            orphan_entity_ids: list[str] = []
            if affected_entity_ids:
                entity_has_mentions = exists().where(
                    KnowledgeGraphEntityMention.entity_id == KnowledgeGraphEntity.entity_id
                )
                entity_has_triples = exists().where(
                    or_(
                        KnowledgeGraphTriple.source_entity_id == KnowledgeGraphEntity.entity_id,
                        KnowledgeGraphTriple.target_entity_id == KnowledgeGraphEntity.entity_id,
                    )
                )
                orphan_entity_ids = list(
                    (
                        await session.execute(
                            select(KnowledgeGraphEntity.entity_id).where(
                                KnowledgeGraphEntity.entity_id.in_(affected_entity_ids),
                                ~entity_has_mentions,
                                ~entity_has_triples,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if orphan_entity_ids:
                    await session.execute(
                        delete(KnowledgeGraphEntity).where(KnowledgeGraphEntity.entity_id.in_(orphan_entity_ids))
                    )

            return orphan_entity_ids, orphan_triple_ids

    async def delete_by_kb_id(self, kb_id: str) -> None:
        async with pg_manager.get_async_session_context() as session:
            await session.execute(delete(KnowledgeGraphTripleMention).where(KnowledgeGraphTripleMention.kb_id == kb_id))
            await session.execute(delete(KnowledgeGraphEntityMention).where(KnowledgeGraphEntityMention.kb_id == kb_id))
            await session.execute(delete(KnowledgeGraphTriple).where(KnowledgeGraphTriple.kb_id == kb_id))
            await session.execute(delete(KnowledgeGraphEntity).where(KnowledgeGraphEntity.kb_id == kb_id))
