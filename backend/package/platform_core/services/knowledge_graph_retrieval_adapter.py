"""将通用 Chunk 检索适配为 LightRAG mix 图路径的低耦合输入。"""

from __future__ import annotations

from typing import Any

from platform_core.knowledge.runtime import knowledge_base


async def retrieve_graph_mix_chunks(
    *,
    kb_id: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """执行不递归调用图检索的 Chunk dense/BM25 混合召回。"""
    return await knowledge_base.aquery(
        query,
        kb_id=kb_id,
        search_mode="hybrid",
        final_top_k=max(1, min(int(top_k), 20)),
        recall_top_k=max(2, min(int(top_k) * 2, 40)),
        similarity_threshold=0.0,
        use_graph_retrieval=False,
        use_reranker=False,
    )
