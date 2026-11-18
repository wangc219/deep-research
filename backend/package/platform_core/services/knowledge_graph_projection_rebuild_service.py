"""从 PostgreSQL 权威当前状态安全重建 Neo4j/Milvus 投影。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.repositories.knowledge_graph_projection_repository import (
    KnowledgeGraphProjectionRepository,
)


class KnowledgeGraphProjectionRebuildService:
    """只管理可丢弃投影；绝不删除 PostgreSQL 权威实体、关系或证据。"""

    def __init__(
        self,
        *,
        graph_service: MilvusGraphService | None = None,
        repository: KnowledgeGraphProjectionRepository | None = None,
        batch_size: int = 100,
    ) -> None:
        self.graph_service = graph_service or MilvusGraphService()
        self.repository = repository or KnowledgeGraphProjectionRepository()
        self.batch_size = max(1, min(int(batch_size), 500))

    async def rebuild(self, *, kb_id: str, context: Any | None = None) -> dict[str, Any]:
        """按当前权威快照重建图结构，再把 active 向量标为待重建。"""
        # 先验证知识库和构建配置，失败时不得触碰现有投影。
        await self.graph_service.ensure_projection_target(kb_id)
        start_revision = await self.repository.latest_revision(kb_id)
        total_chunks = await self.repository.count_projectable_chunks(kb_id)
        if context is not None:
            await context.raise_if_cancelled()
            await context.set_progress(8.0, f"准备从 PostgreSQL 重建 {total_chunks} 个 Chunk 投影")

        # 该删除只作用于 Neo4j/Milvus；PostgreSQL 权威记录保持不变，可重复执行恢复。
        await asyncio.to_thread(self.graph_service.delete_graph, kb_id)

        projected_chunks = 0
        projected_entities = 0
        projected_relations = 0
        after_id = 0
        while True:
            if context is not None:
                await context.raise_if_cancelled()
            snapshots = await self.repository.list_chunk_snapshots(
                kb_id=kb_id,
                after_id=after_id,
                limit=self.batch_size,
            )
            if not snapshots:
                break
            for snapshot in snapshots:
                if context is not None:
                    await context.raise_if_cancelled()
                chunk = SimpleNamespace(**snapshot.chunk)
                await asyncio.to_thread(
                    self.graph_service.project_chunk_graph,
                    kb_id,
                    chunk,
                    snapshot.graph_payload,
                    snapshot.entity_records,
                    snapshot.triple_records,
                )
                projected_chunks += 1
                projected_entities += sum(
                    1 for record in snapshot.entity_records if bool(record.get("has_mention", True))
                )
                projected_relations += len(snapshot.triple_records)
                after_id = int(snapshot.chunk["id"])
            if context is not None:
                progress = 8.0 + (projected_chunks / max(total_chunks, 1) * 52.0)
                await context.set_progress(
                    min(progress, 60.0),
                    f"已重建图结构 {projected_chunks}/{total_chunks} 个 Chunk",
                )

        end_revision = await self.repository.latest_revision(kb_id)
        if end_revision != start_revision:
            raise RuntimeError("重建期间 PostgreSQL graph revision 发生变化；权威数据未受影响，请在变更结束后重试")

        vector_result = await self.graph_service.reconcile_vectors(kb_id, all_vectors=True)
        if context is not None:
            await context.raise_if_cancelled()
            await context.set_progress(65.0, "正在从 PostgreSQL 权威记录重建 Milvus 图向量")
        vector_projection = await self.graph_service.drain_pending_graph_vectors(
            kb_id,
            context=context,
        )
        return {
            "kb_id": kb_id,
            "graph_revision": start_revision,
            "projected_chunks": projected_chunks,
            "projected_entity_mentions": projected_entities,
            "projected_relation_mentions": projected_relations,
            "vector_reconcile": vector_result,
            "vector_projection": vector_projection,
        }
