"""证据约束技术方案生成的应用服务。"""

from __future__ import annotations

from typing import Any

from platform_core.knowledge.graphs.evidence_grounded_solution import (
    SOLUTION_GENERATION_VERSION,
    GeneratorFactory,
    generate_grounded_solution,
)
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.graphs.solution_assessment import assess_grounded_solution
from platform_core.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from platform_core.repositories.knowledge_graph_evolution_repository import KnowledgeGraphEvolutionRepository
from platform_core.services.knowledge_graph_retrieval_adapter import retrieve_graph_mix_chunks

MAX_SOLUTION_EVIDENCE_CHUNKS = 12
MAX_SOLUTION_EVIDENCE_CHARS = 3000


class KnowledgeGraphSolutionService:
    """只以已接受图路径和 PostgreSQL 原文 Chunk 驱动方案生成。"""

    def __init__(
        self,
        *,
        graph_service: MilvusGraphService | None = None,
        chunk_repository: KnowledgeChunkRepository | None = None,
        revision_repository: KnowledgeGraphEvolutionRepository | None = None,
        generator_factory: GeneratorFactory | None = None,
    ):
        self.graph_service = graph_service or MilvusGraphService(chunk_retriever=retrieve_graph_mix_chunks)
        self.chunk_repository = chunk_repository or KnowledgeChunkRepository()
        self.revision_repository = revision_repository or KnowledgeGraphEvolutionRepository()
        self.generator_factory = generator_factory

    async def generate(
        self,
        *,
        kb_id: str,
        query: str,
        discovery_mode: str,
        llm_enabled: bool,
        model_spec: str | None,
        max_hops: int = 5,
        max_paths: int = 5,
        retrieval_mode: str = "mix",
        evidence_scope: str = "any",
        query_enhancement: dict[str, Any] | None = None,
        path_reranking: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """显式启用模型后生成可追溯技术假设；不持久化为图谱事实。"""
        if not llm_enabled:
            raise ValueError("技术方案生成默认关闭，必须显式启用 LLM")
        if not str(model_spec or "").strip():
            raise ValueError("显式启用 LLM 后必须选择 model_spec")
        path_mode = {
            "top_down": "requirement_driven",
            "bottom_up": "entity_expansion",
        }.get(discovery_mode)
        if path_mode is None:
            raise ValueError("discovery_mode 必须是 top_down 或 bottom_up")
        if evidence_scope not in {"any", "cross_document"}:
            raise ValueError("evidence_scope 必须是 any 或 cross_document")

        discovery_path_limit = max_paths
        if evidence_scope == "cross_document":
            discovery_path_limit = min(max_paths * 3, 30)

        path_result = await self.graph_service.discover_paths(
            kb_id,
            query=query,
            mode=path_mode,
            max_hops=max_hops,
            max_paths=discovery_path_limit,
            include_combinations=False,
            retrieval_mode=retrieval_mode,
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
        )
        trusted_paths = [path for path in path_result.get("paths") or [] if _is_trusted_path(path)]
        if evidence_scope == "cross_document":
            trusted_paths = [path for path in trusted_paths if _is_cross_document_path(path)]
        trusted_paths = trusted_paths[:max_paths]
        if not trusted_paths:
            if evidence_scope == "cross_document":
                raise ValueError("没有覆盖至少两个来源文件的 Fact/Inference 图路径，拒绝生成技术方案")
            raise ValueError("没有可用的 Fact/Inference 图路径，拒绝生成技术方案")

        chunk_ids = list(
            dict.fromkeys(
                str(chunk_id)
                for path in trusted_paths
                for chunk_id in (path.get("evidence") or {}).get("chunk_ids") or []
                if chunk_id
            )
        )[:MAX_SOLUTION_EVIDENCE_CHUNKS]
        chunks = await self.chunk_repository.list_by_chunk_ids(chunk_ids)
        evidence = _build_evidence(kb_id, chunks)
        if not evidence:
            raise ValueError("图路径没有可回切的 PostgreSQL 原文证据，拒绝生成技术方案")

        public_paths = [_public_path(path) for path in trusted_paths]
        entities = _unique_entities(trusted_paths)
        solution = await generate_grounded_solution(
            query=query,
            query_analysis=path_result.get("query_analysis") or {},
            paths=public_paths,
            evidence=evidence,
            model_spec=str(model_spec),
            discovery_mode=discovery_mode,
            generator_factory=self.generator_factory,
        )
        graph_revision = await self.revision_repository.latest_revision(kb_id)
        assessment = assess_grounded_solution(
            query=query,
            solution=solution,
            entities=entities,
            paths=public_paths,
            evidence=evidence,
            graph_revision=graph_revision,
        )
        source_file_ids = list(dict.fromkeys(file_id for path in trusted_paths for file_id in _path_file_ids(path)))
        return {
            "query": query,
            "query_analysis": path_result.get("query_analysis") or {},
            "query_plan": path_result.get("query_plan") or {},
            "path_reranking": path_result.get("path_reranking") or {},
            "retrieval_summary": path_result.get("summary") or {},
            "entities": entities,
            "path": public_paths,
            "evidence": evidence,
            "applicable_conditions": list(
                dict.fromkeys(
                    condition
                    for path in public_paths
                    for relation in path.get("relations") or []
                    for condition in relation.get("applicable_conditions") or []
                )
            ),
            **solution,
            **assessment,
            "generation_version": SOLUTION_GENERATION_VERSION,
            "model_spec": str(model_spec),
            "graph_revision": graph_revision,
            "evidence_scope": evidence_scope,
            "source_document_count": len(source_file_ids),
            "cross_document_path_count": sum(_is_cross_document_path(path) for path in trusted_paths),
            "persisted": False,
            "expert_review_required": True,
        }


def _is_trusted_path(path: dict[str, Any]) -> bool:
    if path.get("claim_level") not in {"Fact", "Inference"}:
        return False
    relations = path.get("relations") or []
    if not relations:
        return False
    return all(
        str((relation.get("properties") or {}).get("review_status") or "pending").lower() in {"accepted", "pending"}
        and str((relation.get("properties") or {}).get("claim_level") or "Inference").title() != "Hypothesis"
        for relation in relations
    )


def _path_file_ids(path: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(file_id) for file_id in (path.get("evidence") or {}).get("file_ids") or [] if str(file_id).strip()
        )
    )


def _is_cross_document_path(path: dict[str, Any]) -> bool:
    return len(_path_file_ids(path)) >= 2


def _build_evidence(kb_id: str, chunks: list[Any]) -> list[dict[str, Any]]:
    evidence = []
    for chunk in chunks:
        content = str(getattr(chunk, "content", "") or "").strip()
        if getattr(chunk, "kb_id", None) != kb_id or not content:
            continue
        evidence.append(
            {
                "evidence_id": f"E{len(evidence) + 1:03d}",
                "chunk_id": str(chunk.chunk_id),
                "file_id": str(chunk.file_id),
                "page": getattr(chunk, "page_number", None),
                "heading_path": list(getattr(chunk, "heading_path", None) or []),
                "start_char": getattr(chunk, "start_char_pos", None),
                "end_char": getattr(chunk, "end_char_pos", None),
                "parser": getattr(chunk, "parser_name", None),
                "parser_version": getattr(chunk, "parser_version", None),
                "text": content[:MAX_SOLUTION_EVIDENCE_CHARS],
            }
        )
    return evidence


def _public_path(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "path_id": path.get("path_id"),
        "claim_level": path.get("claim_level"),
        "route_kind": path.get("route_kind"),
        "nodes": [
            {
                "entity_id": (node.get("properties") or {}).get("entity_id"),
                "name": node.get("name"),
                "type": node.get("type"),
                "semantic_role": node.get("semantic_role"),
            }
            for node in path.get("nodes") or []
        ],
        "relations": [
            {
                "relation_id": relation.get("id"),
                "type": relation.get("type"),
                "source_id": relation.get("source_id"),
                "target_id": relation.get("target_id"),
                "applicable_conditions": list((relation.get("properties") or {}).get("applicable_conditions") or []),
            }
            for relation in path.get("relations") or []
        ],
        "evidence": path.get("evidence") or {},
        "evidence_gaps": list(path.get("evidence_gaps") or []),
    }


def _unique_entities(paths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for path in paths:
        for node in path.get("nodes") or []:
            entity_id = str((node.get("properties") or {}).get("entity_id") or "")
            if entity_id:
                entities.setdefault(
                    entity_id,
                    {
                        "entity_id": entity_id,
                        "name": node.get("name"),
                        "type": node.get("type"),
                        "semantic_role": node.get("semantic_role"),
                    },
                )
    return list(entities.values())
