from unittest.mock import AsyncMock

import pytest

from platform_core.services import knowledge_graph_retrieval_adapter


@pytest.mark.asyncio
async def test_mix_chunk_adapter_disables_recursive_graph_and_reranker(monkeypatch):
    query = AsyncMock(return_value=[{"metadata": {"chunk_id": "chunk-1"}}])
    monkeypatch.setattr(knowledge_graph_retrieval_adapter.knowledge_base, "aquery", query)

    result = await knowledge_graph_retrieval_adapter.retrieve_graph_mix_chunks(
        kb_id="kb-test",
        query="复杂电磁环境",
        top_k=6,
    )

    assert result == [{"metadata": {"chunk_id": "chunk-1"}}]
    query.assert_awaited_once_with(
        "复杂电磁环境",
        kb_id="kb-test",
        search_mode="hybrid",
        final_top_k=6,
        recall_top_k=12,
        similarity_threshold=0.0,
        use_graph_retrieval=False,
        use_reranker=False,
    )
