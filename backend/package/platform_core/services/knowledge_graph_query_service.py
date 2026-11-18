"""实体、关系、证据与图谱版本的只读知识服务。"""

from __future__ import annotations

from typing import Any

from platform_core.repositories.knowledge_graph_query_repository import KnowledgeGraphQueryRepository


class KnowledgeGraphQueryService:
    """为 HTTP 和平台模块提供不依赖 Neo4j 投影的权威详情查询。"""

    def __init__(self, repository: KnowledgeGraphQueryRepository | None = None):
        self.repository = repository or KnowledgeGraphQueryRepository()

    async def get_entity_detail(
        self,
        *,
        kb_id: str,
        entity_id: str,
        evidence_limit: int = 100,
    ) -> dict[str, Any]:
        """读取具有已接受原文证据的标准实体详情。"""
        return await self.repository.get_entity_detail(
            kb_id=kb_id,
            entity_id=entity_id,
            evidence_limit=evidence_limit,
        )

    async def get_relation_detail(
        self,
        *,
        kb_id: str,
        triple_id: str,
        evidence_limit: int = 100,
    ) -> dict[str, Any]:
        """读取具有已接受 Fact/Inference 证据的标准关系详情。"""
        return await self.repository.get_relation_detail(
            kb_id=kb_id,
            triple_id=triple_id,
            evidence_limit=evidence_limit,
        )

    async def list_revisions(self, *, kb_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """读取图谱 revision 历史。"""
        return await self.repository.list_revisions(kb_id=kb_id, limit=limit, offset=offset)

    async def list_changes(
        self,
        *,
        kb_id: str,
        graph_revision: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按 revision 或知识目标读取不可变变更事件。"""
        return await self.repository.list_changes(
            kb_id=kb_id,
            graph_revision=graph_revision,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            offset=offset,
        )
