"""实体对齐后的 LightRAG 文档级关系增强应用服务。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable
from typing import Any

from defense_document_entity_contract import (
    DocumentEntityBlock,
    DocumentEntityOptions,
    DocumentEntityRequest,
    DocumentEntityType,
    DocumentKnownEntity,
)
from defense_document_re_contract import (
    DocumentREBlock,
    DocumentREEntity,
    DocumentREOptions,
    DocumentRERelationType,
    DocumentRERequest,
)
from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.knowledge.graphs.document_entity_type_governance import (
    propose_document_entity_type_redirects,
)
from platform_core.knowledge.graphs.entity_identity import new_entity_uuid
from platform_core.knowledge.graphs.graph_utils import normalize_entity_name, resolve_entity_naming
from platform_core.knowledge.graphs.lightrag_document_entity_enhancement import (
    LightRAGDocumentEntityEnhancer,
)
from platform_core.knowledge.graphs.lightrag_document_relation_enhancement import (
    LightRAGDocumentRelationEnhancer,
)
from platform_core.knowledge.graphs.lightrag_cross_document_relation_enhancement import (
    CrossDocumentRelation,
    CrossDocumentRelationOptions,
    LightRAGCrossDocumentRelationEnhancer,
    build_cross_document_relation_request,
    split_cross_document_relation_request,
)
from platform_core.knowledge.graphs.ontology_versioning import normalize_ontology_definition
from platform_core.repositories.knowledge_graph_document_enhancement_repository import (
    KnowledgeGraphDocumentEnhancementRepository,
)
from platform_core.repositories.knowledge_graph_evolution_repository import (
    KnowledgeGraphEvolutionRepository,
)


class KnowledgeGraphDocumentEnhancementService:
    """聚合 canonical entity、调用项目 LLM 并只写入待审核候选。"""

    def __init__(
        self,
        *,
        repository: KnowledgeGraphDocumentEnhancementRepository | None = None,
        client_factory: Callable[..., Any] | None = None,
        llm_enhancer_factory: Callable[..., Any] | None = None,
        entity_enhancer_factory: Callable[..., LightRAGDocumentEntityEnhancer] | None = None,
        cross_document_enhancer_factory: Callable[..., LightRAGCrossDocumentRelationEnhancer] | None = None,
        entity_aligner: Callable[..., Any] | None = None,
        evolution_repository: KnowledgeGraphEvolutionRepository | None = None,
    ) -> None:
        self.repository = repository or KnowledgeGraphDocumentEnhancementRepository()
        self.llm_enhancer_factory = llm_enhancer_factory or LightRAGDocumentRelationEnhancer
        self.entity_enhancer_factory = entity_enhancer_factory or LightRAGDocumentEntityEnhancer
        self.cross_document_enhancer_factory = cross_document_enhancer_factory or LightRAGCrossDocumentRelationEnhancer
        self.entity_aligner = entity_aligner
        self.evolution_repository = evolution_repository or KnowledgeGraphEvolutionRepository()

    async def run(
        self,
        *,
        kb_id: str,
        document_ids: list[str],
        options: dict[str, Any] | None,
        pipeline_revision: str,
        ontology_version: str,
        ontology_definition: dict[str, Any] | None = None,
        entity_alignment_options: dict[str, Any] | None = None,
        priority_document_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """执行可选的 LightRAG 离线增强。"""
        config = dict(options or {})
        priority_ids = {str(item) for item in priority_document_ids or set() if str(item)}
        if not config.get("enabled"):
            return {"status": "skipped", "reason": "disabled", "documents": 0, "relations": 0}
        llm_config = dict(config.get("llm_enhancement") or {})
        entity_config = dict(config.get("entity_enhancement") or {})
        cross_document_config = dict(config.get("cross_document_relation_enhancement") or {})
        llm_enhancer = None
        priority_llm_enhancer = None
        entity_enhancer = None
        cross_document_enhancer = None
        try:
            if llm_config.get("enabled"):
                llm_enhancer = self.llm_enhancer_factory(
                    {
                        **llm_config,
                        "concurrency_count": int(config.get("concurrency_count") or 2),
                    }
                )
                if priority_ids:
                    priority_llm_config = {
                        **llm_config,
                        "concurrency_count": int(config.get("concurrency_count") or 2),
                        "max_output_tokens": max(
                            int(llm_config.get("max_output_tokens") or 2048),
                            int(config.get("priority_llm_max_output_tokens") or 4096),
                        ),
                        "max_truncation_retries": max(
                            int(llm_config.get("max_truncation_retries") or 0),
                            int(config.get("priority_llm_max_truncation_retries") or 1),
                        ),
                    }
                    if priority_llm_config != llm_config:
                        priority_llm_enhancer = self.llm_enhancer_factory(priority_llm_config)
            if entity_config.get("enabled"):
                entity_enhancer = self.entity_enhancer_factory(
                    {
                        **entity_config,
                        "concurrency_count": int(config.get("concurrency_count") or 2),
                    }
                )
            if cross_document_config.get("enabled"):
                cross_document_enhancer = self.cross_document_enhancer_factory(cross_document_config)
            if (
                llm_enhancer is None
                and entity_enhancer is None
                and cross_document_enhancer is None
            ):
                return {
                    "status": "skipped",
                    "reason": "no_lightrag_enhancer",
                    "documents": 0,
                    "relations": 0,
                }

            ontology = normalize_ontology_definition(ontology_definition or ontology_payload())
            if ontology["version"] != ontology_version:
                raise ValueError("文档增强本体快照与 ontology_version 不一致")
            documents = await self.repository.load_documents(kb_id=kb_id, document_ids=document_ids)
            relation_types = _relation_types(ontology)
            relation_by_code = {str(item["code"]): item for item in ontology["relation_types"]}
            request_options = DocumentREOptions(
                relation_threshold=config.get("relation_threshold"),
                max_entities=int(config.get("max_entities") or 42),
                max_blocks=int(config.get("max_blocks") or 128),
                max_chars=int(config.get("max_chars") or 16_000),
                max_relations=64,
                max_candidate_pairs=int(config.get("max_candidate_pairs") or 256),
            )
            enhancement_semaphore = asyncio.Semaphore(int(config.get("concurrency_count") or 2))
            type_governance_lock = asyncio.Lock()
            total_relations = 0
            total_entities = 0
            total_entity_windows = 0
            total_entity_llm_calls = 0
            total_entity_gleaning_calls = 0
            total_entity_gleaning_windows = 0
            total_entity_gleaning_candidates = 0
            total_repair_proposals = 0
            total_windows = 0
            priority_documents = 0
            priority_entity_windows = 0
            priority_relation_windows = 0
            skipped_documents = 0
            cross_document_candidate_pairs = 0
            cross_document_relations = 0
            cross_document_source_documents = 0
            cross_document_scope_documents = 0
            cross_document_seed_documents = 0
            cross_document_batches = 0
            cross_document_degraded_batches = 0
            cross_document_concurrency_count = 0
            cross_document_status = "disabled"
            type_conflict_groups = 0
            type_conflict_groups_resolved = 0
            type_redirects = 0
            type_governance_reports = []
            warnings = []
            model_versions = {}
            if llm_enhancer is not None:
                model_versions["lightrag_document_relation"] = str(llm_config["model_spec"])
            if entity_enhancer is not None:
                model_versions["lightrag_document_entity"] = str(entity_config["model_spec"])
            if cross_document_enhancer is not None:
                model_versions["lightrag_cross_document_relation"] = str(cross_document_config["model_spec"])

            async def process_document(document):
                nonlocal total_relations, total_entities, total_entity_windows
                nonlocal total_entity_llm_calls, total_entity_gleaning_calls
                nonlocal total_entity_gleaning_windows, total_entity_gleaning_candidates
                nonlocal total_repair_proposals, total_windows, priority_documents
                nonlocal priority_entity_windows, priority_relation_windows, skipped_documents
                nonlocal type_conflict_groups, type_conflict_groups_resolved, type_redirects

                is_priority_document = str(document["document_id"]) in priority_ids
                if is_priority_document:
                    priority_documents += 1
                document_request_options = request_options
                if is_priority_document:
                    document_request_options = DocumentREOptions.model_validate(
                        {
                            **request_options.model_dump(),
                            "max_blocks": max(
                                request_options.max_blocks,
                                int(config.get("priority_max_blocks") or 192),
                            ),
                            "max_chars": max(
                                request_options.max_chars,
                                int(config.get("priority_max_chars") or 32_000),
                            ),
                            "max_entities": max(
                                request_options.max_entities,
                                int(config.get("priority_max_entities") or 64),
                            ),
                        }
                    )
                document_llm_request_options = DocumentREOptions.model_validate(
                    {
                        **document_request_options.model_dump(),
                        "max_relations": (
                            max(
                                int(llm_config.get("max_relations") or 12),
                                int(config.get("priority_llm_max_relations") or 24),
                            )
                            if is_priority_document
                            else int(llm_config.get("max_relations") or 12)
                        ),
                    }
                )
                if entity_enhancer is not None:
                    entity_options = DocumentEntityOptions(
                        max_blocks=(
                            max(
                                int(entity_config.get("max_blocks") or 48),
                                int(config.get("priority_entity_max_blocks") or 96),
                            )
                            if is_priority_document
                            else int(entity_config.get("max_blocks") or 48)
                        ),
                        max_chars=(
                            max(
                                int(entity_config.get("max_chars") or min(request_options.max_chars, 12_000)),
                                int(config.get("priority_entity_max_chars") or 24_000),
                            )
                            if is_priority_document
                            else int(entity_config.get("max_chars") or min(request_options.max_chars, 12_000))
                        ),
                        max_candidates=(
                            max(
                                int(entity_config.get("max_candidates") or 100),
                                int(config.get("priority_entity_max_candidates") or 200),
                            )
                            if is_priority_document
                            else int(entity_config.get("max_candidates") or 100)
                        ),
                    )
                    merged_candidates: dict[tuple[str, int, int, str], dict[str, Any]] = {}
                    entity_windows = _entity_windows(document, entity_options)
                    total_entity_windows += len(entity_windows)
                    priority_entity_windows += len(entity_windows) * int(is_priority_document)

                    async def enhance_entity_window(entity_window):
                        request = _document_entity_request(
                            document=document,
                            window=entity_window,
                            request_options=entity_options,
                            pipeline_revision=pipeline_revision,
                            ontology_version=ontology_version,
                            model_version=str(entity_config["model_spec"]),
                            ontology_definition=ontology,
                        )
                        try:
                            async with enhancement_semaphore:
                                response = await entity_enhancer.enhance(request)
                        except Exception as exc:
                            return entity_window, None, exc
                        return entity_window, response, None

                    entity_results = await asyncio.gather(
                        *(enhance_entity_window(entity_window) for entity_window in entity_windows)
                    )
                    for entity_window, response, error in entity_results:
                        if error is not None:
                            if entity_config.get("strict") is True:
                                raise error
                            warning = (
                                f"文档 {document['document_id']} 的 LightRAG 文档实体补抽降级: {type(error).__name__}"
                            )
                            if warning not in warnings:
                                warnings.append(warning)
                            continue
                        total_repair_proposals += len(response.repair_proposals)
                        gleaning = response.normalization.get("gleaning") or {}
                        entity_llm_calls = int(gleaning.get("llm_calls") or 0)
                        entity_gleaning_calls = int(gleaning.get("gleaning_calls") or 0)
                        total_entity_llm_calls += entity_llm_calls
                        total_entity_gleaning_calls += entity_gleaning_calls
                        total_entity_gleaning_candidates += int(gleaning.get("gleaning_candidate_count") or 0)
                        if entity_gleaning_calls:
                            total_entity_gleaning_windows += 1
                        for candidate in _translate_entity_candidates(response.entities, entity_window):
                            key = (
                                str(candidate["block_id"]),
                                int(candidate["start"]),
                                int(candidate["end"]),
                                str(candidate["type"]),
                            )
                            existing = merged_candidates.get(key)
                            if existing is None or float(candidate["confidence"]) > float(existing["confidence"]):
                                merged_candidates[key] = candidate
                    entity_records = _candidate_entity_records(
                        kb_id=kb_id,
                        candidates=list(merged_candidates.values()),
                        model_version=str(entity_config["model_spec"]),
                        ontology_version=ontology_version,
                    )
                    if entity_records:
                        if self.entity_aligner is not None:
                            await self.entity_aligner(
                                kb_id=kb_id,
                                entities=entity_records,
                                triples=[],
                                entity_alignment_options=dict(entity_alignment_options or {}),
                            )
                        else:
                            await self.repository.align_entity_records(kb_id=kb_id, entities=entity_records)
                        persisted_entities = await self.repository.persist_entity_mentions(
                            kb_id=kb_id,
                            document=document,
                            entities=entity_records,
                            ontology_version=ontology_version,
                            pipeline_revision=pipeline_revision,
                        )
                        total_entities += persisted_entities
                        _merge_document_entities(document, entity_records)
                windows = _document_windows(document, document_request_options)
                if not windows:
                    skipped_documents += 1
                    return
                merged_relations: dict[tuple[str, str, str], dict[str, Any]] = {}
                total_windows += len(windows)
                priority_relation_windows += len(windows) * int(is_priority_document)
                relation_jobs = []
                for window in windows:
                    enhancers = []
                    if llm_enhancer is not None:
                        enhancers.append(
                            (
                                "lightrag_document_relation",
                                str(llm_config["model_spec"]),
                                (
                                    priority_llm_enhancer
                                    if is_priority_document and priority_llm_enhancer is not None
                                    else llm_enhancer
                                ),
                                bool(llm_config.get("strict")),
                            )
                        )
                    for source, model_version, enhancer, strict in enhancers:
                        request = _document_request(
                            document=document,
                            window=window,
                            relation_types=relation_types,
                            request_options=document_llm_request_options,
                            pipeline_revision=pipeline_revision,
                            ontology_version=ontology_version,
                            model_version=model_version,
                        )
                        relation_jobs.append((window, source, model_version, enhancer, strict, request))

                async def enhance_relation_window(job):
                    window, source, model_version, enhancer, strict, request = job
                    try:
                        async with enhancement_semaphore:
                            response = await enhancer.enhance(request)
                    except Exception as exc:
                        return window, source, model_version, strict, None, exc
                    return window, source, model_version, strict, response, None

                relation_results = await asyncio.gather(*(enhance_relation_window(job) for job in relation_jobs))
                for window, source, model_version, strict, response, error in relation_results:
                    if error is not None:
                        if strict:
                            raise error
                        warning = f"文档 {document['document_id']} 的 LightRAG 文档补抽降级: {type(error).__name__}"
                        if warning not in warnings:
                            warnings.append(warning)
                        continue
                    for relation in response.relations:
                        if (
                            request_options.relation_threshold is not None
                            and relation.confidence_kind == "probability"
                            and relation.confidence < request_options.relation_threshold
                        ):
                            continue
                        key = (relation.type, relation.source_entity_id, relation.target_entity_id)
                        payload = _translate_relation_evidence(
                            relation.model_dump(mode="json"),
                            window,
                        )
                        relation_type = relation_by_code[relation.type]
                        payload.update(
                            {
                                "hypothesis_only": bool(relation_type.get("hypothesis_only")),
                                "model_sources": [source],
                                "model_versions": {source: model_version},
                            }
                        )
                        merged_relations[key] = _merge_relation_payload(merged_relations.get(key), payload)
                persisted = await self.repository.persist_relations(
                    kb_id=kb_id,
                    document=document,
                    relations=list(merged_relations.values()),
                    model_version=_document_relation_model_version(
                        llm_config=llm_config,
                    ),
                    ontology_version=ontology_version,
                    pipeline_revision=pipeline_revision,
                )
                total_relations += persisted
                if config.get("entity_type_governance_enabled", True) is True:
                    governance = propose_document_entity_type_redirects(
                        document=document,
                        relations=list(merged_relations.values()),
                        min_supporting_relations=int(config.get("entity_type_governance_min_relations") or 2),
                    )
                    type_conflict_groups += int(governance["conflict_group_count"])
                    type_conflict_groups_resolved += int(governance["resolved_group_count"])
                    applied_redirects = []
                    for decision in governance["decisions"]:
                        try:
                            async with type_governance_lock:
                                redirect = await self.evolution_repository.redirect_entity(
                                    kb_id=kb_id,
                                    source_entity_id=decision.source_entity_id,
                                    target_entity_ids=[decision.target_entity_id],
                                    operation="merge",
                                    reason=decision.reason,
                                    created_by="document_relation_type_governance",
                                )
                        except Exception as exc:
                            if config.get("entity_type_governance_strict") is True:
                                raise
                            warning = f"文档 {document['document_id']} 的关系一致性类型治理降级: {type(exc).__name__}"
                            if warning not in warnings:
                                warnings.append(warning)
                            continue
                        applied_redirects.append(
                            {
                                "source_entity_id": decision.source_entity_id,
                                "target_entity_id": decision.target_entity_id,
                                "source_label": decision.source_label,
                                "target_label": decision.target_label,
                                "graph_revision": redirect.get("graph_revision"),
                            }
                        )
                        type_redirects += 1
                    type_governance_reports.append(
                        {
                            "document_id": document["document_id"],
                            "version": governance["version"],
                            "conflict_group_count": governance["conflict_group_count"],
                            "resolved_group_count": governance["resolved_group_count"],
                            "skipped_group_count": governance["skipped_group_count"],
                            "proposed_redirect_count": governance["redirect_count"],
                            "applied_redirect_count": len(applied_redirects),
                            "resolved_groups": governance["resolved_groups"],
                            "skipped_groups": governance["skipped_groups"],
                            "applied_redirects": applied_redirects,
                        }
                    )

            document_concurrency_count = min(
                int(config.get("document_concurrency_count") or 2),
                len(documents),
            )
            if documents:
                for offset in range(0, len(documents), document_concurrency_count):
                    document_batch = documents[offset : offset + document_concurrency_count]
                    document_results = await asyncio.gather(
                        *(process_document(document) for document in document_batch),
                        return_exceptions=True,
                    )
                    for document_result in document_results:
                        if isinstance(document_result, asyncio.CancelledError):
                            raise document_result
                        if isinstance(document_result, Exception):
                            raise document_result
                document_order = {str(document["document_id"]): index for index, document in enumerate(documents)}
                type_governance_reports.sort(
                    key=lambda report: document_order.get(str(report["document_id"]), len(document_order))
                )
            if cross_document_enhancer is not None:
                cross_document_status = "no_candidates"
                cross_document_review_scope = str(cross_document_config.get("review_scope") or "accepted_only").strip()
                if cross_document_review_scope not in {"accepted_only", "pending_candidates"}:
                    raise ValueError("跨文档 review_scope 必须是 accepted_only 或 pending_candidates")
                try:
                    scope_loader = getattr(self.repository, "load_cross_document_scope", None)
                    if callable(scope_loader):
                        cross_documents = await scope_loader(
                            kb_id=kb_id,
                            seed_document_ids=document_ids,
                            accepted_mentions_only=cross_document_review_scope == "accepted_only",
                            max_documents=int(cross_document_config.get("max_scope_documents") or 128),
                        )
                    else:
                        cross_documents = await self.repository.load_documents(
                            kb_id=kb_id,
                            document_ids=document_ids,
                            accepted_mentions_only=cross_document_review_scope == "accepted_only",
                        )
                    cross_document_scope_documents = len(cross_documents)
                    cross_document_seed_documents = len({str(item) for item in document_ids if str(item)})
                    cross_options = CrossDocumentRelationOptions(
                        min_document_support=int(cross_document_config.get("min_document_support") or 2),
                        max_pairs=int(cross_document_config.get("max_pairs") or 24),
                        max_documents_per_pair=int(cross_document_config.get("max_documents_per_pair") or 3),
                        max_blocks=int(cross_document_config.get("max_blocks") or 64),
                        max_chars=int(cross_document_config.get("max_chars") or 30_000),
                        max_relations=int(cross_document_config.get("max_relations") or 24),
                        min_confidence=float(cross_document_config.get("min_confidence") or 0.85),
                        max_entities_per_document=int(cross_document_config.get("max_entities_per_document") or 96),
                        max_pairs_per_document=int(cross_document_config.get("max_pairs_per_document") or 512),
                        min_entity_confidence=float(cross_document_config.get("min_entity_confidence") or 0.0),
                    )
                    cross_request = build_cross_document_relation_request(
                        request_id=uuid.uuid4().hex,
                        kb_id=kb_id,
                        documents=cross_documents,
                        pipeline_revision=pipeline_revision,
                        ontology_version=ontology_version,
                        model_version=str(cross_document_config["model_spec"]),
                        options=cross_options,
                        ontology_definition=ontology,
                    )
                    if cross_request is not None:
                        cross_document_candidate_pairs = len(cross_request.candidate_pairs)
                        cross_batches = split_cross_document_relation_request(
                            cross_request,
                            pairs_per_batch=int(cross_document_config.get("pairs_per_batch") or 6),
                        )
                        cross_document_batches = len(cross_batches)
                        cross_document_concurrency_count = min(
                            int(cross_document_config.get("concurrency_count") or 2),
                            cross_document_batches,
                        )
                        cross_batch_semaphore = asyncio.Semaphore(cross_document_concurrency_count)

                        async def enhance_cross_batch(batch):
                            async with cross_batch_semaphore, enhancement_semaphore:
                                return await cross_document_enhancer.enhance(batch)

                        cross_results = await asyncio.gather(
                            *(enhance_cross_batch(batch) for batch in cross_batches),
                            return_exceptions=True,
                        )
                        cross_relations: dict[tuple[str, str, str], CrossDocumentRelation] = {}
                        cross_errors = []
                        for result in cross_results:
                            if isinstance(result, asyncio.CancelledError):
                                raise result
                            if isinstance(result, Exception):
                                cross_errors.append(result)
                                continue
                            for relation in result.relations:
                                key = (relation.type, relation.source_entity_id, relation.target_entity_id)
                                existing = cross_relations.get(key)
                                if existing is None or relation.confidence > existing.confidence:
                                    cross_relations[key] = relation
                        cross_document_degraded_batches = len(cross_errors)
                        if cross_errors and cross_document_config.get("strict") is True:
                            raise cross_errors[0]
                        if cross_errors and len(cross_errors) == cross_document_batches:
                            warnings.append(f"LightRAG 跨文档多源关系增强降级: {type(cross_errors[0]).__name__}")
                        elif cross_errors:
                            warnings.append(
                                f"LightRAG 跨文档批次部分降级: {len(cross_errors)}/{cross_document_batches}"
                            )
                        cross_payloads = [item.model_dump(mode="json") for item in cross_relations.values()]
                        if cross_payloads or not cross_errors:
                            cross_document_relations = await self.repository.persist_cross_document_relations(
                                kb_id=kb_id,
                                documents=cross_documents,
                                relations=cross_payloads,
                                model_version=str(cross_document_config["model_spec"]),
                                ontology_version=ontology_version,
                                pipeline_revision=pipeline_revision,
                                review_scope=cross_document_review_scope,
                            )
                            total_relations += cross_document_relations
                            cross_document_source_documents = len(
                                {
                                    span["document_id"]
                                    for relation in cross_payloads
                                    for span in relation["evidence_spans"]
                                }
                            )
                        if cross_errors and len(cross_errors) == cross_document_batches:
                            cross_document_status = "degraded"
                        elif cross_errors:
                            cross_document_status = "partially_degraded"
                        else:
                            cross_document_status = "completed"
                except Exception as exc:
                    if cross_document_config.get("strict") is True:
                        raise
                    cross_document_status = "degraded"
                    warnings.append(f"LightRAG 跨文档多源关系增强降级: {type(exc).__name__}")
            return {
                "status": "completed",
                "reason": "",
                "documents": len(documents),
                "concurrency_count": int(config.get("concurrency_count") or 2),
                "document_concurrency_count": document_concurrency_count,
                "windows": total_windows,
                "entity_windows": total_entity_windows,
                "entity_llm_calls": total_entity_llm_calls,
                "entity_gleaning_calls": total_entity_gleaning_calls,
                "entity_gleaning_windows": total_entity_gleaning_windows,
                "entity_gleaning_candidates": total_entity_gleaning_candidates,
                "entities": total_entities,
                "relations": total_relations,
                "repair_proposals": total_repair_proposals,
                "skipped_documents": skipped_documents,
                "priority_documents": priority_documents,
                "priority_entity_windows": priority_entity_windows,
                "priority_relation_windows": priority_relation_windows,
                "priority_llm_max_output_tokens": (
                    max(
                        int(llm_config.get("max_output_tokens") or 2048),
                        int(config.get("priority_llm_max_output_tokens") or 4096),
                    )
                    if priority_documents and llm_enhancer is not None
                    else None
                ),
                "priority_llm_max_truncation_retries": (
                    max(
                        int(llm_config.get("max_truncation_retries") or 0),
                        int(config.get("priority_llm_max_truncation_retries") or 1),
                    )
                    if priority_documents and llm_enhancer is not None
                    else None
                ),
                "cross_document_candidate_pairs": cross_document_candidate_pairs,
                "cross_document_relations": cross_document_relations,
                "cross_document_source_documents": cross_document_source_documents,
                "cross_document_scope_documents": cross_document_scope_documents,
                "cross_document_seed_documents": cross_document_seed_documents,
                "cross_document_batches": cross_document_batches,
                "cross_document_concurrency_count": cross_document_concurrency_count,
                "cross_document_degraded_batches": cross_document_degraded_batches,
                "cross_document_status": cross_document_status,
                "cross_document_review_scope": (
                    str(cross_document_config.get("review_scope") or "accepted_only")
                    if cross_document_enhancer is not None
                    else "disabled"
                ),
                "entity_type_governance": {
                    "enabled": config.get("entity_type_governance_enabled", True) is True,
                    "conflict_group_count": type_conflict_groups,
                    "resolved_group_count": type_conflict_groups_resolved,
                    "redirect_count": type_redirects,
                    "documents": type_governance_reports,
                },
                "model_version": str(llm_config.get("model_spec") or "") or None,
                "model_versions": model_versions,
                "warnings": warnings,
                "degraded": bool(warnings),
            }
        finally:
            if llm_enhancer is not None:
                await llm_enhancer.aclose()
            if priority_llm_enhancer is not None and priority_llm_enhancer is not llm_enhancer:
                await priority_llm_enhancer.aclose()
            if entity_enhancer is not None:
                await entity_enhancer.aclose()
            if cross_document_enhancer is not None:
                await cross_document_enhancer.aclose()


def _document_relation_model_version(
    *,
    llm_config: dict[str, Any],
) -> str:
    """为持久化记录选择实际参与关系抽取的模型版本。"""

    if llm_config.get("enabled"):
        return str(llm_config["model_spec"])
    return "document-entity-only"


def _document_entity_request(
    *,
    document: dict[str, Any],
    window: dict[str, Any],
    request_options: DocumentEntityOptions,
    pipeline_revision: str,
    ontology_version: str,
    model_version: str,
    ontology_definition: dict[str, Any],
) -> DocumentEntityRequest:
    public_blocks = [_public_block(item) for item in window["blocks"]]
    public_entities = [_public_entity(item) for item in window["entities"]]
    input_payload = {
        "stage_revision": "document-entity-enhancement-v8",
        "pipeline_revision": pipeline_revision,
        "ontology_version": ontology_version,
        "document_id": document["document_id"],
        "document_version": document["document_version"],
        "blocks": public_blocks,
        "known_entities": public_entities,
    }
    input_hash = hashlib.sha256(
        json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DocumentEntityRequest(
        request_id=uuid.uuid4().hex,
        stage_revision="document-entity-enhancement-v8",
        input_hash=input_hash,
        pipeline_revision=pipeline_revision,
        model_version=model_version,
        ontology_version=ontology_version,
        document_id=document["document_id"],
        document_version=document["document_version"],
        blocks=[DocumentEntityBlock.model_validate(item) for item in public_blocks],
        known_entities=[DocumentKnownEntity.model_validate(item) for item in public_entities],
        entity_types=[
            DocumentEntityType(
                code=str(item["code"]),
                name_zh=str(item.get("name_zh") or ""),
                description=str(item.get("description") or ""),
            )
            for item in ontology_definition["entity_types"]
        ],
        options=request_options,
    )


def _entity_windows(document: dict[str, Any], options: DocumentEntityOptions) -> list[dict[str, Any]]:
    """生成不依赖既有实体数量的文档窗口，避免漏抽阶段形成自举死角。"""
    blocks = _budgeted_blocks(list(document["blocks"]), options.max_chars)
    entity_by_id = {str(item["entity_id"]): item for item in document["entities"]}
    _attach_local_mentions(blocks, entity_by_id)
    windows = []
    cursor = 0
    while cursor < len(blocks):
        selected_blocks = []
        selected_chars = 0
        next_cursor = cursor
        while next_cursor < len(blocks) and len(selected_blocks) < options.max_blocks:
            block = blocks[next_cursor]
            if selected_blocks and selected_chars + len(str(block["text"])) > options.max_chars:
                break
            selected_blocks.append(block)
            selected_chars += len(str(block["text"]))
            next_cursor += 1
        selected_entities = []
        for entity_id, entity in entity_by_id.items():
            mentions = [
                mention for block in selected_blocks for mention in block["_entity_mentions"].get(entity_id, [])
            ]
            if mentions:
                selected_entities.append({**entity, "mentions": mentions})
        if selected_blocks:
            windows.append({"blocks": selected_blocks, "entities": selected_entities})
        if next_cursor >= len(blocks):
            break
        overlap = min(2, max(len(selected_blocks) - 1, 0))
        cursor = max(cursor + 1, next_cursor - overlap)
    return windows


def _translate_entity_candidates(candidates: list[Any], window: dict[str, Any]) -> list[dict[str, Any]]:
    """把请求片段内实体 Span 还原为 PostgreSQL 权威 Block 偏移。"""
    block_by_request_id = {str(item["block_id"]): item for item in window["blocks"]}
    translated = []
    for candidate in candidates:
        payload = candidate.model_dump(mode="json")
        block = block_by_request_id[str(payload["block_id"])]
        source_start = int(block["_source_start"])
        translated.append(
            {
                **payload,
                "block_id": str(block["_source_block_id"]),
                "start": int(payload["start"]) + source_start,
                "end": int(payload["end"]) + source_start,
            }
        )
    return translated


def _candidate_entity_records(
    *,
    kb_id: str,
    candidates: list[dict[str, Any]],
    model_version: str,
    ontology_version: str,
) -> list[dict[str, Any]]:
    """将文档 mention 转为可复用 canonical 对齐端口的权威实体记录。"""
    records = []
    for candidate in candidates:
        mention_text = str(candidate["text"])
        naming = resolve_entity_naming(
            mention_text,
            canonical_name=candidate.get("canonical_name"),
            aliases=candidate.get("aliases"),
            naming_rationale=candidate.get("naming_rationale"),
        )
        canonical_name = naming["canonical_name"]
        normalized_name = normalize_entity_name(canonical_name)
        records.append(
            {
                "entity_id": new_entity_uuid(kb_id, normalized_name, str(candidate["type"])),
                "kb_id": kb_id,
                "normalized_name": normalized_name,
                "label": str(candidate["type"]),
                "name": canonical_name,
                "attributes": candidate.get("attributes") or [],
                "content": normalized_name,
                "mention_text": mention_text,
                "aliases": naming["aliases"],
                "naming_rationale": naming["naming_rationale"],
                "block_id": str(candidate["block_id"]),
                "start_char": int(candidate["start"]),
                "end_char": int(candidate["end"]),
                "confidence": float(candidate["confidence"]),
                "model_version": model_version,
                "ontology_version": ontology_version,
                "review_status": "pending",
            }
        )
    return records


def _merge_document_entities(document: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """把已对齐的新 mention 合入当前内存文档，供随后 DocRE 窗口立即消费。"""
    by_id = {str(item["entity_id"]): item for item in document["entities"]}
    for record in records:
        entity_id = str(record["entity_id"])
        item = by_id.setdefault(
            entity_id,
            {
                "entity_id": entity_id,
                "type": str(record["label"]),
                "canonical_name": str(record["name"]),
                "mentions": [],
                "projection_record": {
                    "entity_id": entity_id,
                    "kb_id": str(record["kb_id"]),
                    "normalized_name": str(record["normalized_name"]),
                    "label": str(record["label"]),
                    "name": str(record["name"]),
                    "attributes": record.get("attributes") or [],
                    "lifecycle_status": "active",
                    "superseded_by_entity_id": None,
                    "entity_version": 1,
                    "review_status": "pending",
                    "has_mention": False,
                },
            },
        )
        key = (str(record["block_id"]), int(record["start_char"]), int(record["end_char"]))
        if any(
            (str(mention["block_id"]), int(mention["start"]), int(mention["end"])) == key
            for mention in item["mentions"]
        ):
            continue
        item["mentions"].append(
            {
                "block_id": key[0],
                "text": str(record["mention_text"]),
                "start": key[1],
                "end": key[2],
                "confidence": float(record.get("confidence") or 0.0),
            }
        )
    document["entities"] = list(by_id.values())


def _document_request(
    *,
    document: dict[str, Any],
    window: dict[str, Any],
    relation_types: list[DocumentRERelationType],
    request_options: DocumentREOptions,
    pipeline_revision: str,
    ontology_version: str,
    model_version: str,
) -> DocumentRERequest:
    return DocumentRERequest(
        request_id=uuid.uuid4().hex,
        pipeline_revision=pipeline_revision,
        model_version=model_version,
        ontology_version=ontology_version,
        document_id=document["document_id"],
        document_version=document["document_version"],
        blocks=[DocumentREBlock.model_validate(_public_block(item)) for item in window["blocks"]],
        entities=[DocumentREEntity.model_validate(_public_entity(item)) for item in window["entities"]],
        relation_types=relation_types,
        options=request_options,
    )


def _merge_relation_payload(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """按端点和关系合并模型来源、证据，并保留较高候选分数。"""
    if existing is None:
        return incoming
    preferred = incoming if float(incoming["confidence"]) > float(existing["confidence"]) else existing
    merged = {**preferred}
    merged["model_sources"] = list(
        dict.fromkeys([*(existing.get("model_sources") or []), *(incoming.get("model_sources") or [])])
    )
    merged["model_versions"] = {
        **(existing.get("model_versions") or {}),
        **(incoming.get("model_versions") or {}),
    }
    merged["model_consensus"] = len(merged["model_sources"]) >= 2
    spans = []
    seen = set()
    for item in [*(existing.get("evidence_spans") or []), *(incoming.get("evidence_spans") or [])]:
        key = (item["block_id"], item["start"], item["end"])
        if key not in seen:
            spans.append(item)
            seen.add(key)
    merged["evidence_spans"] = spans
    return merged


def _relation_types(ontology_definition: dict[str, Any] | None = None) -> list[DocumentRERelationType]:
    """DocRE 只复核可由文档证据支持的事实关系；创新假设由独立模块负责。"""
    ontology = normalize_ontology_definition(ontology_definition or ontology_payload())
    return [
        DocumentRERelationType(
            code=str(item["code"]),
            name_zh=str(item.get("name_zh") or ""),
            description=str(item.get("description") or ""),
            head_types=list(item["head_types"]),
            tail_types=list(item["tail_types"]),
            directed=bool(item.get("directed", True)),
            allow_self=bool(item.get("allow_self", False)),
            hypothesis_only=bool(item.get("hypothesis_only", False)),
        )
        for item in ontology["relation_types"]
        if not item.get("hypothesis_only")
    ]


def _document_windows(document: dict[str, Any], options: DocumentREOptions) -> list[dict[str, Any]]:
    """按 Block、实体和字符硬预算生成可回切原文的重叠窗口。"""
    blocks = _budgeted_blocks(list(document["blocks"]), options.max_chars)
    entity_by_id = {str(item["entity_id"]): item for item in document["entities"]}
    _attach_local_mentions(blocks, entity_by_id)

    windows = []
    cursor = 0
    while cursor < len(blocks):
        selected_blocks = []
        selected_entity_ids: set[str] = set()
        selected_chars = 0
        next_cursor = cursor
        while next_cursor < len(blocks) and len(selected_blocks) < options.max_blocks:
            block = blocks[next_cursor]
            proposed = selected_entity_ids | set(block["_entity_mentions"])
            if selected_blocks and len(proposed) > options.max_entities:
                break
            if selected_blocks and selected_chars + len(str(block["text"])) > options.max_chars:
                break
            selected_blocks.append(block)
            selected_entity_ids = proposed
            selected_chars += len(str(block["text"]))
            next_cursor += 1
        if len(selected_entity_ids) >= 2 and len(selected_entity_ids) <= options.max_entities:
            selected_entities = []
            for entity_id in sorted(selected_entity_ids):
                entity = entity_by_id[entity_id]
                mentions = [
                    mention for block in selected_blocks for mention in block["_entity_mentions"].get(entity_id, [])
                ]
                if mentions:
                    selected_entities.append({**entity, "mentions": mentions})
            if len(selected_entities) >= 2:
                windows.append({"blocks": selected_blocks, "entities": selected_entities})
        if next_cursor <= cursor:
            next_cursor = cursor + 1
        overlap = min(2, max(len(selected_blocks) - 1, 0))
        cursor = max(cursor + 1, next_cursor - overlap)
    return windows


def _budgeted_blocks(blocks: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """把异常长 Block 切成带原始偏移映射的请求片段，不修改权威 Chunk。"""
    overlap = min(256, max_chars // 8)
    step = max_chars - overlap
    budgeted = []
    for block in blocks:
        text = str(block["text"])
        if len(text) <= max_chars:
            budgeted.append(
                {
                    **block,
                    "_source_block_id": str(block["block_id"]),
                    "_source_start": 0,
                    "_source_end": len(text),
                }
            )
            continue
        for source_start in range(0, len(text), step):
            source_end = min(source_start + max_chars, len(text))
            source_block_id = str(block["block_id"])
            digest = hashlib.sha256(f"{source_block_id}:{source_start}:{source_end}".encode()).hexdigest()[:20]
            budgeted.append(
                {
                    **block,
                    "block_id": f"slice-{digest}",
                    "text": text[source_start:source_end],
                    "base_char_offset": int(block.get("base_char_offset") or 0) + source_start,
                    "_source_block_id": source_block_id,
                    "_source_start": source_start,
                    "_source_end": source_end,
                }
            )
            if source_end == len(text):
                break
    return budgeted


def _attach_local_mentions(
    blocks: list[dict[str, Any]],
    entity_by_id: dict[str, dict[str, Any]],
) -> None:
    """把原始 mention 映射为请求片段内偏移，供 DocRE 严格 Span 校验。"""
    for block in blocks:
        source_block_id = str(block["_source_block_id"])
        source_start = int(block["_source_start"])
        source_end = int(block["_source_end"])
        local_mentions: dict[str, list[dict[str, Any]]] = {}
        for entity_id, entity in entity_by_id.items():
            for mention in entity["mentions"]:
                start = int(mention["start"])
                end = int(mention["end"])
                if str(mention["block_id"]) != source_block_id or start < source_start or end > source_end:
                    continue
                local_mentions.setdefault(entity_id, []).append(
                    {
                        **mention,
                        "block_id": str(block["block_id"]),
                        "start": start - source_start,
                        "end": end - source_start,
                    }
                )
        block["_entity_mentions"] = local_mentions


def _translate_relation_evidence(
    relation: dict[str, Any],
    window: dict[str, Any],
) -> dict[str, Any]:
    """把模型对请求片段的证据偏移还原到 PostgreSQL 权威 Block。"""
    block_by_request_id = {str(item["block_id"]): item for item in window["blocks"]}
    evidence_spans = []
    for span in relation["evidence_spans"]:
        block = block_by_request_id[str(span["block_id"])]
        source_start = int(block["_source_start"])
        evidence_spans.append(
            {
                **span,
                "block_id": str(block["_source_block_id"]),
                "start": int(span["start"]) + source_start,
                "end": int(span["end"]) + source_start,
            }
        )
    return {**relation, "evidence_spans": evidence_spans}


def _public_block(block: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in block.items() if key != "chunk" and not key.startswith("_")}


def _public_entity(entity: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entity.items() if key != "projection_record"}
