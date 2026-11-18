"""多跳检索与证据约束 LLM 撰述的应用服务。"""

from __future__ import annotations

from typing import Any

from platform_core.knowledge.graphs.lightrag_multihop_synthesis import LightRAGMultiHopSynthesizer
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService


class KnowledgeGraphMultiHopService:
    """组合双向多跳检索和详细结论撰述，不生成创新候选。"""

    def __init__(self, graph_service: MilvusGraphService, synthesizer_factory: Any | None = None):
        self.graph_service = graph_service
        self.synthesizer_factory = synthesizer_factory or LightRAGMultiHopSynthesizer

    async def discover(
        self,
        *,
        kb_id: str,
        query: str,
        discovery_mode: str,
        max_hops: int = 5,
        max_paths: int = 10,
        include_combinations: bool = False,
        retrieval_mode: str = "mix",
        query_enhancement: dict[str, Any] | None = None,
        path_reranking: dict[str, Any] | None = None,
        narrative: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """返回自上而下或自下而上的路径及独立 LLM 结论。"""
        path_mode = {
            "top_down": "requirement_driven",
            "requirement_driven": "requirement_driven",
            "bottom_up": "entity_expansion",
            "entity_expansion": "entity_expansion",
            "auto": "auto",
        }.get(discovery_mode)
        if path_mode is None:
            raise ValueError("discovery_mode 必须是 top_down、bottom_up 或 auto")

        result = await self.graph_service.discover_paths(
            kb_id,
            query=query,
            mode=path_mode,
            max_hops=max_hops,
            max_paths=max_paths,
            include_combinations=include_combinations,
            retrieval_mode=retrieval_mode,
            query_enhancement=query_enhancement,
            path_reranking=path_reranking,
        )
        resolved_mode = "top_down" if str(result.get("mode") or path_mode) == "requirement_driven" else "bottom_up"
        synthesizer = self.synthesizer_factory(narrative or {})
        try:
            synthesis = await synthesizer.synthesize(
                query=query,
                discovery_mode=resolved_mode,
                paths=result.get("paths") or [],
                query_plan=result.get("query_plan") or {},
                query_analysis=result.get("query_analysis") or {},
            )
        finally:
            await synthesizer.aclose()

        result["feature_kind"] = "multi_hop_retrieval"
        result["discovery_mode"] = resolved_mode
        result["narrative"] = synthesis["narrative"]
        result["narrative_provenance"] = synthesis["provenance"]
        result.setdefault("summary", {})["narrative_status"] = synthesis["provenance"]["status"]
        return result
