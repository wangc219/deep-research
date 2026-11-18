"""双向 GraphRAG 创新关联发现的应用服务。"""

from __future__ import annotations

from typing import Any

from platform_core.knowledge.graphs.innovation_discovery import (
    build_innovation_feedback_loop,
    discover_innovation_hypotheses,
    innovation_response,
)
from platform_core.knowledge.graphs.lightrag_innovation_enhancement import LightRAGInnovationEnhancer
from platform_core.knowledge.graphs.milvus_graph_service import (
    GRAPH_REVIEW_SCOPE_ALL,
    MilvusGraphService,
)
from platform_core.knowledge.graphs.requirement_analysis import analyze_requirement_query
from platform_core.repositories.knowledge_graph_evolution_repository import KnowledgeGraphEvolutionRepository
from platform_core.services.knowledge_graph_retrieval_adapter import retrieve_graph_mix_chunks


class KnowledgeGraphInnovationService:
    """组合图检索、候选边推导和 PostgreSQL 假设治理。"""

    def __init__(
        self,
        graph_service: MilvusGraphService | None = None,
        repository: KnowledgeGraphEvolutionRepository | None = None,
        innovation_enhancer_factory: Any | None = None,
    ):
        self.graph_service = graph_service or MilvusGraphService(chunk_retriever=retrieve_graph_mix_chunks)
        self.repository = repository or KnowledgeGraphEvolutionRepository()
        self.innovation_enhancer_factory = innovation_enhancer_factory or LightRAGInnovationEnhancer

    async def discover(
        self,
        *,
        kb_id: str,
        query: str,
        discovery_mode: str,
        max_hops: int = 5,
        max_candidates: int = 10,
        persist: bool = True,
        retrieval_mode: str = "mix",
        query_enhancement: dict[str, Any] | None = None,
        path_reranking: dict[str, Any] | None = None,
        llm_enhancement: dict[str, Any] | None = None,
        evidence_scope: str = "any",
    ) -> dict[str, Any]:
        """发现缺失关联；所有输出固定为待审核 Hypothesis。"""
        path_mode = {
            "top_down": "requirement_driven",
            "requirement_driven": "requirement_driven",
            "bottom_up": "entity_expansion",
            "entity_expansion": "entity_expansion",
        }.get(discovery_mode)
        if path_mode is None:
            raise ValueError("discovery_mode 必须是 top_down 或 bottom_up")
        review_scope = GRAPH_REVIEW_SCOPE_ALL
        path_result = await self.graph_service.discover_paths(
            kb_id,
            query=query,
            mode=path_mode,
            max_hops=max_hops,
            max_paths=max_candidates,
            include_combinations=False,
            retrieval_mode=retrieval_mode,
            review_scope=review_scope,
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
        )
        trusted_paths = [
            path for path in path_result.get("paths") or [] if path.get("claim_level") in {"Fact", "Inference", None}
        ]
        path_result["paths"] = trusted_paths
        path_result.setdefault("summary", {})["returned_path_count"] = len(trusted_paths)
        candidates = discover_innovation_hypotheses(
            kb_id=kb_id,
            path_result=path_result,
            discovery_mode=discovery_mode,
            max_candidates=max_candidates,
            evidence_scope=evidence_scope,
        )
        enhancer = self.innovation_enhancer_factory(llm_enhancement or {})
        try:
            enhancement = await enhancer.enhance(
                query=query,
                discovery_mode=discovery_mode,
                query_analysis=path_result.get("query_analysis") or {},
                path_result=path_result,
                candidates=candidates,
            )
        finally:
            await enhancer.aclose()
        candidates = enhancement["candidates"]
        if persist and candidates:
            await self.repository.save_hypotheses(kb_id, candidates)
        graph_revision = await self.repository.latest_revision(kb_id)
        query_analysis = path_result.get("query_analysis") or analyze_requirement_query(
            query, path_result, discovery_mode=discovery_mode
        )
        response = innovation_response(
            query=query,
            discovery_mode=discovery_mode,
            candidates=candidates,
            graph_revision=graph_revision,
            query_analysis=query_analysis,
        )
        response["retrieval_summary"] = path_result.get("summary") or {}
        response["query_plan"] = path_result.get("query_plan") or {}
        response["path_reranking"] = path_result.get("path_reranking") or {}
        response["pipeline_trace"] = path_result.get("pipeline_trace") or {}
        response["innovation_enhancement"] = enhancement["report"]
        response["feedback_loop"] = build_innovation_feedback_loop(path_result, candidates)
        response["evidence_scope"] = evidence_scope
        response["cross_document_candidate_count"] = sum(
            bool((item.get("evidence_path") or {}).get("cross_document")) for item in candidates
        )
        response["persisted"] = bool(persist and candidates)
        response["preview_mode"] = not persist
        response["review_scope"] = review_scope
        response["pending_evidence"] = any(bool(item.get("pending_evidence")) for item in candidates)
        response["expert_review_required"] = True
        response["feature_kind"] = "innovation_hypothesis_generation"
        response["discovery_mode"] = discovery_mode
        return response

    async def list_candidates(
        self,
        *,
        kb_id: str,
        status: str = "pending",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """读取已持久化的创新关联候选。"""
        return await self.repository.list_hypotheses(
            kb_id=kb_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def review_candidate(
        self,
        *,
        kb_id: str,
        hypothesis_id: str,
        decision: str,
        reviewer_uid: str,
        reason: str,
    ) -> dict[str, Any]:
        """审核候选但不把预测关联自动晋升为 Fact。"""
        return await self.repository.review_hypothesis(
            kb_id=kb_id,
            hypothesis_id=hypothesis_id,
            decision=decision,
            reviewer_uid=reviewer_uid,
            reason=reason,
        )
