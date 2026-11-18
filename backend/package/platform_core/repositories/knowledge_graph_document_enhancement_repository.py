"""文档级关系增强所需的 canonical entity 读取与候选权威写入。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, tuple_

from platform_core.knowledge.graphs.entity_identity import relation_uuid
from platform_core.knowledge.graphs.projection_contract import build_projection_event
from platform_core.repositories.knowledge_graph_repository import KnowledgeGraphRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeSourceDocument,
)


class KnowledgeGraphDocumentEnhancementRepository:
    """隔离文档聚合查询，不让增强适配器依赖 PostgreSQL 模型。"""

    def __init__(self, graph_repository: KnowledgeGraphRepository | None = None) -> None:
        self.graph_repository = graph_repository or KnowledgeGraphRepository()

    async def load_documents(
        self,
        *,
        kb_id: str,
        document_ids: list[str],
        accepted_mentions_only: bool = False,
    ) -> list[dict[str, Any]]:
        """按当前不可变文档版本加载 Block 与已对齐 canonical entity mention。"""
        requested = list(dict.fromkeys(str(item) for item in document_ids if item))
        if not requested:
            return []
        async with pg_manager.get_async_session_context() as session:
            sources = list(
                (
                    await session.scalars(
                        select(KnowledgeSourceDocument)
                        .where(
                            KnowledgeSourceDocument.kb_id == kb_id,
                            KnowledgeSourceDocument.document_id.in_(requested),
                        )
                        .order_by(KnowledgeSourceDocument.document_id.asc())
                    )
                ).all()
            )
            version_keys = [(str(source.file_id), int(source.current_version or 1)) for source in sources]
            if not version_keys:
                return []
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
            chunk_ids = [str(chunk.chunk_id) for chunk in chunks]
            mention_rows = []
            if chunk_ids:
                review_filter = (
                    KnowledgeGraphEntityMention.review_status == "accepted"
                    if accepted_mentions_only
                    else KnowledgeGraphEntityMention.review_status.notin_(["rejected", "superseded"])
                )
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
                            KnowledgeGraphEntityMention.start_char.is_not(None),
                            KnowledgeGraphEntityMention.end_char.is_not(None),
                            review_filter,
                            KnowledgeGraphEntity.lifecycle_status == "active",
                        )
                        .order_by(
                            KnowledgeGraphEntityMention.chunk_id.asc(),
                            KnowledgeGraphEntityMention.start_char.asc(),
                            KnowledgeGraphEntityMention.id.asc(),
                        )
                    )
                ).all()

        source_by_file_version = {(str(source.file_id), int(source.current_version or 1)): source for source in sources}
        chunks_by_document: dict[str, list[Any]] = {}
        chunk_by_id = {}
        document_id_by_chunk = {}
        for chunk in chunks:
            source = source_by_file_version.get((str(chunk.file_id), int(chunk.document_version or 1)))
            if source is None or not str(chunk.content or ""):
                continue
            document_id = str(source.document_id)
            chunks_by_document.setdefault(document_id, []).append(chunk)
            chunk_by_id[str(chunk.chunk_id)] = chunk
            document_id_by_chunk[str(chunk.chunk_id)] = document_id

        entities_by_document: dict[str, dict[str, dict[str, Any]]] = {}
        for mention, entity in mention_rows:
            chunk = chunk_by_id.get(str(mention.chunk_id))
            document_id = document_id_by_chunk.get(str(mention.chunk_id))
            if chunk is None or document_id is None:
                continue
            start = int(mention.start_char)
            end = int(mention.end_char)
            text = str(chunk.content or "")
            if end <= start or end > len(text):
                raise ValueError(f"实体 mention Span 无法回切原文: {entity.entity_id}/{chunk.chunk_id}")
            entity_map = entities_by_document.setdefault(document_id, {})
            item = entity_map.setdefault(
                str(entity.entity_id),
                {
                    "entity_id": str(entity.entity_id),
                    "type": str(entity.label),
                    "canonical_name": str(entity.name),
                    "mentions": [],
                    "mention_review_statuses": [],
                    "projection_record": {
                        "entity_id": str(entity.entity_id),
                        "kb_id": kb_id,
                        "normalized_name": str(entity.normalized_name),
                        "label": str(entity.label),
                        "name": str(entity.name),
                        "attributes": entity.attributes or [],
                        "lifecycle_status": str(entity.lifecycle_status or "active"),
                        "superseded_by_entity_id": entity.superseded_by_entity_id,
                        "entity_version": int(entity.entity_version or 1),
                        "review_status": "pending",
                        "has_mention": False,
                    },
                },
            )
            item["mentions"].append(
                {
                    "block_id": str(chunk.chunk_id),
                    "text": text[start:end],
                    "start": start,
                    "end": end,
                    "confidence": float(mention.confidence or 0.0),
                }
            )
            item["mention_review_statuses"].append(str(mention.review_status or "pending"))

        documents = []
        source_by_document = {str(source.document_id): source for source in sources}
        for document_id in requested:
            source = source_by_document.get(document_id)
            document_chunks = chunks_by_document.get(document_id) or []
            entities = list((entities_by_document.get(document_id) or {}).values())
            if source is None or not document_chunks:
                continue
            documents.append(
                {
                    "document_id": document_id,
                    "document_version": int(source.current_version or 1),
                    "blocks": [
                        {
                            "block_id": str(chunk.chunk_id),
                            "text": str(chunk.content),
                            "block_index": int(chunk.chunk_index),
                            "page": chunk.page_number,
                            "base_char_offset": int(chunk.start_char_pos or 0),
                            "heading_path": list(chunk.heading_path or []),
                            "chunk": chunk,
                        }
                        for chunk in document_chunks
                    ],
                    "entities": entities,
                }
            )
        return documents

    async def load_cross_document_scope(
        self,
        *,
        kb_id: str,
        seed_document_ids: list[str],
        accepted_mentions_only: bool = False,
        max_documents: int = 128,
    ) -> list[dict[str, Any]]:
        """加载本批文档及知识库中共享 canonical entity 的历史文档。"""
        requested = list(dict.fromkeys(str(item) for item in seed_document_ids if item))
        if not requested:
            return []
        if max_documents < 2:
            raise ValueError("跨文档候选范围至少允许 2 篇文档")

        seed_documents = await self.load_documents(
            kb_id=kb_id,
            document_ids=requested,
            accepted_mentions_only=accepted_mentions_only,
        )
        remaining = max_documents - len(seed_documents)
        shared_entity_ids = {
            str(entity["entity_id"])
            for document in seed_documents
            for entity in document["entities"]
            if entity.get("entity_id")
        }
        if remaining <= 0 or not shared_entity_ids:
            return seed_documents

        review_filter = (
            KnowledgeGraphEntityMention.review_status == "accepted"
            if accepted_mentions_only
            else KnowledgeGraphEntityMention.review_status.notin_(["rejected", "superseded"])
        )
        overlap_count = func.count(func.distinct(KnowledgeGraphEntityMention.entity_id)).label("overlap_count")
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(KnowledgeSourceDocument.document_id, overlap_count)
                    .select_from(KnowledgeGraphEntityMention)
                    .join(
                        KnowledgeGraphEntity,
                        KnowledgeGraphEntity.entity_id == KnowledgeGraphEntityMention.entity_id,
                    )
                    .join(
                        KnowledgeChunk,
                        KnowledgeChunk.chunk_id == KnowledgeGraphEntityMention.chunk_id,
                    )
                    .join(
                        KnowledgeSourceDocument,
                        (KnowledgeSourceDocument.kb_id == KnowledgeChunk.kb_id)
                        & (KnowledgeSourceDocument.file_id == KnowledgeChunk.file_id)
                        & (KnowledgeSourceDocument.current_version == KnowledgeChunk.document_version),
                    )
                    .where(
                        KnowledgeGraphEntityMention.kb_id == kb_id,
                        KnowledgeGraphEntityMention.entity_id.in_(shared_entity_ids),
                        KnowledgeGraphEntityMention.start_char.is_not(None),
                        KnowledgeGraphEntityMention.end_char.is_not(None),
                        review_filter,
                        KnowledgeGraphEntity.lifecycle_status == "active",
                        KnowledgeSourceDocument.document_id.notin_(requested),
                    )
                    .group_by(KnowledgeSourceDocument.document_id)
                    .order_by(overlap_count.desc(), KnowledgeSourceDocument.document_id.asc())
                    .limit(remaining)
                )
            ).all()

        related_ids = [str(document_id) for document_id, _ in rows]
        if not related_ids:
            return seed_documents
        related_documents = await self.load_documents(
            kb_id=kb_id,
            document_ids=related_ids,
            accepted_mentions_only=accepted_mentions_only,
        )
        return [*seed_documents, *related_documents]

    async def align_entity_records(self, *, kb_id: str, entities: list[dict[str, Any]]) -> None:
        """无向量运行时仍复用精确别名对齐和 PostgreSQL 原子 UUID 分配。"""
        if not entities:
            return
        alignment = await self.graph_repository.align_graph_records(
            kb_id=kb_id,
            entities=entities,
            triples=[],
        )
        unresolved = set(alignment.get("unresolved_entity_ids") or [])
        if unresolved:
            await self.graph_repository.allocate_entity_ids(
                kb_id=kb_id,
                entities=entities,
                triples=[],
                provisional_entity_ids=unresolved,
            )
        await self.graph_repository.align_graph_records(
            kb_id=kb_id,
            entities=entities,
            triples=[],
        )

    async def persist_entity_mentions(
        self,
        *,
        kb_id: str,
        document: dict[str, Any],
        entities: list[dict[str, Any]],
        ontology_version: str,
        pipeline_revision: str,
    ) -> int:
        """按权威 Block 原子写入待审核 mention，并为 Neo4j/Milvus 登记 Outbox。"""
        if not entities:
            return 0
        block_by_id = {str(item["block_id"]): item for item in document["blocks"]}
        records_by_block: dict[str, list[dict[str, Any]]] = {}
        seen = set()
        for entity in entities:
            block_id = str(entity["block_id"])
            block = block_by_id.get(block_id)
            start = int(entity["start_char"])
            end = int(entity["end_char"])
            text = str(block["text"]) if block is not None else ""
            if block is None or end <= start or end > len(text) or text[start:end] != entity["mention_text"]:
                raise ValueError(f"文档实体增强 Span 无法回切原文: {entity['entity_id']}/{block_id}")
            key = (str(entity["entity_id"]), block_id, start, end)
            if key in seen:
                continue
            seen.add(key)
            records_by_block.setdefault(block_id, []).append(entity)

        persisted = 0
        for block_id, block_records in records_by_block.items():
            block = block_by_id[block_id]
            graph_payload = {
                "entities": [
                    {
                        "id": f"document-entity-{index}",
                        "text": str(record["mention_text"]),
                        "label": str(record["label"]),
                        "start": int(record["start_char"]),
                        "end": int(record["end_char"]),
                        "confidence": float(record.get("confidence") or 0.0),
                        "attributes": record.get("attributes") or [],
                    }
                    for index, record in enumerate(block_records, start=1)
                ],
                "relations": [],
                "metadata": {
                    "extractor_type": "lightrag_document_entity",
                    "model_version": str(block_records[0].get("model_version") or "unknown"),
                    "ontology_version": ontology_version,
                    "pipeline_revision": pipeline_revision,
                    "document_id": document["document_id"],
                    "document_version": document["document_version"],
                    "stage_revision": "document-entity-enhancement-v8",
                },
            }
            projection_event = build_projection_event(
                kb_id=kb_id,
                chunk=block["chunk"],
                graph_payload=graph_payload,
                entity_records=block_records,
                triple_records=[],
            )
            projection_event["reason"] = "document_entity_enhancement"
            projection_event["summary"].update(
                {
                    "document_id": document["document_id"],
                    "document_version": document["document_version"],
                    "entity_count": len(block_records),
                }
            )
            await self.graph_repository.upsert_chunk_graph(
                kb_id=kb_id,
                file_id=str(block["chunk"].file_id),
                chunk_id=block_id,
                entities=block_records,
                triples=[],
                projection_event=projection_event,
                preserve_reviewed_mentions=True,
            )
            persisted += len(block_records)
        return persisted

    async def persist_cross_document_relations(
        self,
        *,
        kb_id: str,
        documents: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        model_version: str,
        ontology_version: str,
        pipeline_revision: str,
        review_scope: str = "accepted_only",
    ) -> int:
        """把至少两个独立来源支持的跨文档关系写为待审核 Inference。"""
        if not relations:
            return 0
        if review_scope not in {"accepted_only", "pending_candidates"}:
            raise ValueError("跨文档 review_scope 非法")

        block_by_id: dict[str, dict[str, Any]] = {}
        document_by_id = {str(document["document_id"]): document for document in documents}
        entity_by_id: dict[str, dict[str, Any]] = {}
        for document in documents:
            for block in document["blocks"]:
                block_id = str(block["block_id"])
                existing = block_by_id.get(block_id)
                if existing is not None and existing is not block:
                    raise ValueError(f"跨文档 block_id 不唯一: {block_id}")
                block_by_id[block_id] = block
            for entity in document["entities"]:
                entity_by_id.setdefault(str(entity["entity_id"]), entity)

        persisted = 0
        for relation in relations:
            source = entity_by_id.get(str(relation["source_entity_id"]))
            target = entity_by_id.get(str(relation["target_entity_id"]))
            if source is None or target is None:
                raise ValueError("跨文档关系端点不在可用 canonical entity 集合")

            evidence_spans = []
            quotes = []
            source_documents = set()
            for raw_span in relation["evidence_spans"]:
                document_id = str(raw_span["document_id"])
                block_id = str(raw_span["block_id"])
                block = block_by_id.get(block_id)
                document = document_by_id.get(document_id)
                start = int(raw_span["start"])
                end = int(raw_span["end"])
                if (
                    block is None
                    or document is None
                    or block not in document["blocks"]
                    or end <= start
                    or end > len(str(block["text"]))
                ):
                    raise ValueError("跨文档关系证据 Span 无法回切权威原文")
                source_documents.add(document_id)
                evidence_spans.append(
                    {
                        "document_id": document_id,
                        "document_version": int(document["document_version"]),
                        "block_id": block_id,
                        "start": start,
                        "end": end,
                        "page": block.get("page"),
                        "base_char_offset": int(block.get("base_char_offset") or 0),
                    }
                )
                quotes.append(f"[{document_id}/{block_id}] {str(block['text'])[start:end]}")
            if len(source_documents) < 2:
                raise ValueError("跨文档关系必须至少由两个独立来源支持")
            for document_id in source_documents:
                document_spans = [item for item in evidence_spans if item["document_id"] == document_id]
                document = document_by_id[document_id]
                if not _spans_cover_entity(document_spans, str(source["entity_id"]), document_id, document):
                    raise ValueError("跨文档关系每个来源必须覆盖源实体 mention")
                if not _spans_cover_entity(document_spans, str(target["entity_id"]), document_id, document):
                    raise ValueError("跨文档关系每个来源必须覆盖目标实体 mention")

            evidence_spans.sort(key=lambda item: (item["document_id"], item["block_id"], item["start"], item["end"]))
            anchor = block_by_id[evidence_spans[0]["block_id"]]
            relation_type = str(relation["type"])
            triple_id = relation_uuid(
                kb_id,
                str(source["entity_id"]),
                relation_type,
                str(target["entity_id"]),
            )
            relation_text = f"{source['canonical_name']} → {relation_type} → {target['canonical_name']}"
            triple_record = {
                "triple_id": triple_id,
                "kb_id": kb_id,
                "source_entity_id": str(source["entity_id"]),
                "target_entity_id": str(target["entity_id"]),
                "relation_type": relation_type,
                "content": relation_text,
                "text": relation_text,
                "extractor_type": "lightrag_cross_document_relation",
                "claim_level": "Inference",
                "confidence": float(relation["confidence"]),
                "evidence_quote": "\n".join(quotes),
                "evidence_spans": evidence_spans,
                "reasoning_basis": (
                    f"{len(source_documents)} 个独立文档中的 canonical mentions 共同支持该关系候选；"
                    f"候选范围={review_scope}；"
                    + (
                        "平台将模型已引用的同 Block 单端 Span 确定性扩展为覆盖两端的紧凑原文 Span"
                        if relation.get("evidence_normalized_by_platform")
                        else "模型证据 Span 已直接通过多源端点完整性校验"
                    )
                ),
                "applicable_conditions": list(relation.get("applicable_conditions") or []),
                "uncertainty": (
                    "跨文档多源 LLM 关系增强候选，证据 Span 经平台确定性规范化，尚未经人工确认"
                    if relation.get("evidence_normalized_by_platform")
                    else "跨文档多源 LLM 关系增强候选，尚未经人工确认"
                ),
                "expert_review_required": True,
                "review_status": "pending",
                "model_version": model_version,
                "ontology_version": ontology_version,
                "pipeline_revision": pipeline_revision,
            }
            graph_payload = {
                "entities": [
                    {
                        "id": "source",
                        "text": source["canonical_name"],
                        "label": source["type"],
                        "attributes": source["projection_record"].get("attributes") or [],
                    },
                    {
                        "id": "target",
                        "text": target["canonical_name"],
                        "label": target["type"],
                        "attributes": target["projection_record"].get("attributes") or [],
                    },
                ],
                "relations": [
                    {
                        "triple_id": triple_id,
                        "source": "source",
                        "target": "target",
                        "text": relation_text,
                        "label": relation_type,
                        **{
                            key: triple_record[key]
                            for key in (
                                "extractor_type",
                                "claim_level",
                                "confidence",
                                "evidence_quote",
                                "evidence_spans",
                                "reasoning_basis",
                                "applicable_conditions",
                                "uncertainty",
                                "expert_review_required",
                            )
                        },
                    }
                ],
                "metadata": {
                    "extractor_type": "lightrag_cross_document_relation",
                    "model_version": model_version,
                    "ontology_version": ontology_version,
                    "pipeline_revision": pipeline_revision,
                    "support_level": "multi_source",
                    "source_document_count": len(source_documents),
                    "source_document_ids": sorted(source_documents),
                    "review_scope": review_scope,
                },
            }
            projection_event = build_projection_event(
                kb_id=kb_id,
                chunk=anchor["chunk"],
                graph_payload=graph_payload,
                entity_records=[source["projection_record"], target["projection_record"]],
                triple_records=[triple_record],
            )
            projection_event["reason"] = "cross_document_relation_enhancement"
            projection_event["summary"].update(
                {
                    "relation_type": relation_type,
                    "support_level": "multi_source",
                    "source_document_count": len(source_documents),
                    "source_document_ids": sorted(source_documents),
                    "review_scope": review_scope,
                }
            )
            await self.graph_repository.upsert_chunk_graph(
                kb_id=kb_id,
                file_id=str(anchor["chunk"].file_id),
                chunk_id=str(anchor["block_id"]),
                entities=[],
                triples=[triple_record],
                projection_event=projection_event,
                preserve_reviewed_mentions=True,
            )
            persisted += 1
        return persisted

    async def persist_relations(
        self,
        *,
        kb_id: str,
        document: dict[str, Any],
        relations: list[dict[str, Any]],
        model_version: str,
        ontology_version: str,
        pipeline_revision: str,
    ) -> int:
        """把文档级候选作为待审核 Inference/Hypothesis 原子写入并登记 Outbox。"""
        if not relations:
            return 0
        block_by_id = {str(item["block_id"]): item for item in document["blocks"]}
        entity_by_id = {str(item["entity_id"]): item for item in document["entities"]}
        persisted = 0
        for relation in relations:
            source = entity_by_id[str(relation["source_entity_id"])]
            target = entity_by_id[str(relation["target_entity_id"])]
            evidence_spans = []
            quotes = []
            for span in relation["evidence_spans"]:
                block = block_by_id[str(span["block_id"])]
                start = int(span["start"])
                end = int(span["end"])
                quote = str(block["text"])[start:end]
                evidence_spans.append(
                    {
                        "block_id": str(block["block_id"]),
                        "start": start,
                        "end": end,
                        "page": block.get("page"),
                        "base_char_offset": int(block.get("base_char_offset") or 0),
                    }
                )
                quotes.append(f"[{block['block_id']}] {quote}")
            anchor = block_by_id[evidence_spans[0]["block_id"]]
            relation_type = str(relation["type"])
            model_sources = list(relation.get("model_sources") or ["lightrag_document_relation"])
            model_versions = dict(relation.get("model_versions") or {})
            extractor_type = "document_relation_ensemble" if len(model_sources) > 1 else model_sources[0]
            relation_model_version = (
                ",".join(f"{source}={model_versions[source]}" for source in model_sources if source in model_versions)
                or model_version
            )
            triple_id = relation_uuid(
                kb_id,
                str(source["entity_id"]),
                relation_type,
                str(target["entity_id"]),
            )
            claim_level = "Hypothesis" if relation.get("hypothesis_only") else "Inference"
            relation_text = f"{source['canonical_name']} → {relation_type} → {target['canonical_name']}"
            triple_record = {
                "triple_id": triple_id,
                "kb_id": kb_id,
                "source_entity_id": str(source["entity_id"]),
                "target_entity_id": str(target["entity_id"]),
                "relation_type": relation_type,
                "content": relation_text,
                "text": relation_text,
                "extractor_type": extractor_type,
                "claim_level": claim_level,
                "confidence": float(relation["confidence"]),
                "evidence_quote": "\n".join(quotes),
                "evidence_spans": evidence_spans,
                "reasoning_basis": (
                    "LightRAG 文档级增强对已对齐实体关系形成一致证据"
                    if relation.get("model_consensus")
                    else f"{model_sources[0]} 基于已对齐实体簇生成的跨 Block 候选"
                ),
                "applicable_conditions": list(relation.get("applicable_conditions") or []),
                "uncertainty": (
                    "文档级模型包含 hard label，未提供统一校准概率；必须人工复核"
                    if relation.get("confidence_kind") == "hard_label"
                    else "文档级监督模型候选，必须人工复核"
                ),
                "expert_review_required": True,
                "review_status": "pending",
                "model_version": relation_model_version,
                "ontology_version": ontology_version,
                "pipeline_revision": pipeline_revision,
            }
            graph_payload = {
                "entities": [
                    {
                        "id": "source",
                        "text": source["canonical_name"],
                        "label": source["type"],
                        "attributes": source["projection_record"].get("attributes") or [],
                    },
                    {
                        "id": "target",
                        "text": target["canonical_name"],
                        "label": target["type"],
                        "attributes": target["projection_record"].get("attributes") or [],
                    },
                ],
                "relations": [
                    {
                        "triple_id": triple_id,
                        "source": "source",
                        "target": "target",
                        "text": relation_text,
                        "label": relation_type,
                        **{
                            key: triple_record[key]
                            for key in (
                                "extractor_type",
                                "claim_level",
                                "confidence",
                                "evidence_quote",
                                "evidence_spans",
                                "reasoning_basis",
                                "applicable_conditions",
                                "uncertainty",
                                "expert_review_required",
                            )
                        },
                    }
                ],
                "metadata": {
                    "extractor_type": extractor_type,
                    "model_version": relation_model_version,
                    "model_sources": model_sources,
                    "model_versions": model_versions,
                    "ontology_version": ontology_version,
                    "pipeline_revision": pipeline_revision,
                    "document_id": document["document_id"],
                    "document_version": document["document_version"],
                },
            }
            projection_event = build_projection_event(
                kb_id=kb_id,
                chunk=anchor["chunk"],
                graph_payload=graph_payload,
                entity_records=[source["projection_record"], target["projection_record"]],
                triple_records=[triple_record],
            )
            projection_event["reason"] = "document_relation_enhancement"
            projection_event["summary"].update(
                {
                    "document_id": document["document_id"],
                    "document_version": document["document_version"],
                    "relation_type": relation_type,
                }
            )
            await self.graph_repository.upsert_chunk_graph(
                kb_id=kb_id,
                file_id=str(anchor["chunk"].file_id),
                chunk_id=str(anchor["block_id"]),
                entities=[],
                triples=[triple_record],
                projection_event=projection_event,
                preserve_reviewed_mentions=True,
            )
            persisted += 1
        return persisted


def _spans_cover_entity(
    spans: list[dict[str, Any]],
    entity_id: str,
    document_id: str,
    document: dict[str, Any],
) -> bool:
    """确认某来源证据至少与该 canonical entity 的 accepted mention 相交。"""
    block_ids = {str(block["block_id"]) for block in document["blocks"]}
    entity = next(
        (item for item in document["entities"] if str(item["entity_id"]) == entity_id),
        None,
    )
    if entity is None:
        return False
    return any(
        span["block_id"] == str(mention["block_id"])
        and span["start"] < int(mention["end"])
        and span["end"] > int(mention["start"])
        for span in spans
        for mention in entity.get("mentions") or []
        if span["document_id"] == document_id and str(mention["block_id"]) in block_ids
    )
