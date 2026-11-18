"""知识图谱动态维护与技术演化分析应用服务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from platform_core.knowledge.graphs.evolution_analysis import analyze_technology_evolution
from platform_core.repositories.knowledge_graph_evolution_repository import KnowledgeGraphEvolutionRepository


class KnowledgeGraphEvolutionService:
    """封装实体版本治理、历史追溯和可复现趋势快照。"""

    def __init__(self, repository: KnowledgeGraphEvolutionRepository | None = None):
        self.repository = repository or KnowledgeGraphEvolutionRepository()

    async def analyze_entity(
        self,
        *,
        kb_id: str,
        entity_id: str,
        as_of: datetime | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """根据已接受来源记录计算实体技术演化指标。"""
        observations = await self.repository.build_entity_observations(kb_id=kb_id, entity_id=entity_id)
        effective_as_of = as_of or datetime.now(UTC)
        analysis = analyze_technology_evolution(observations, as_of=effective_as_of)
        evidence = {
            "accepted_observation_periods": len(observations),
            "document_count": sum(item["document_count"] for item in observations),
            "source": "accepted_entity_mentions",
        }
        if persist:
            return await self.repository.save_trend_snapshot(
                kb_id=kb_id,
                entity_id=entity_id,
                analysis=analysis,
                evidence=evidence,
            )
        return {**analysis, "entity_id": entity_id, "evidence": evidence}

    async def list_snapshots(self, *, kb_id: str, entity_id: str, limit: int = 24) -> list[dict[str, Any]]:
        """读取实体演化快照。"""
        return await self.repository.list_trend_snapshots(kb_id=kb_id, entity_id=entity_id, limit=limit)

    async def redirect_entity(
        self,
        *,
        kb_id: str,
        source_entity_id: str,
        target_entity_ids: list[str],
        operation: str,
        reason: str,
        created_by: str,
    ) -> dict[str, Any]:
        """执行保留原实体的 merge/split redirect。"""
        return await self.repository.redirect_entity(
            kb_id=kb_id,
            source_entity_id=source_entity_id,
            target_entity_ids=target_entity_ids,
            operation=operation,
            reason=reason,
            created_by=created_by,
        )

    async def entity_history(self, *, kb_id: str, entity_id: str) -> dict[str, Any]:
        """读取实体生命周期和变更事件。"""
        return await self.repository.entity_history(kb_id=kb_id, entity_id=entity_id)

    async def update_relation_lifecycle(
        self,
        *,
        kb_id: str,
        triple_id: str,
        lifecycle_status: str,
        superseded_by_triple_id: str | None,
        reason: str,
        created_by: str,
    ) -> dict[str, Any]:
        """失效或替代一条关系，并保留完整变更谱系。"""
        return await self.repository.update_relation_lifecycle(
            kb_id=kb_id,
            triple_id=triple_id,
            lifecycle_status=lifecycle_status,
            superseded_by_triple_id=superseded_by_triple_id,
            reason=reason,
            created_by=created_by,
        )
