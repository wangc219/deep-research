"""知识图谱本体与人工审核应用服务。"""

from __future__ import annotations

from typing import Any

from platform_core.knowledge.graphs.defense_ontology import DEFENSE_ONTOLOGY_V1, ontology_payload
from platform_core.knowledge.graphs.ontology_versioning import (
    build_ontology_change_set,
    normalize_ontology_definition,
)
from platform_core.repositories.knowledge_graph_governance_repository import KnowledgeGraphGovernanceRepository


class KnowledgeGraphGovernanceService:
    """为 HTTP、worker 与本地工具提供一致的治理用例。"""

    def __init__(self, repository: KnowledgeGraphGovernanceRepository | None = None):
        self.repository = repository or KnowledgeGraphGovernanceRepository()

    async def ensure_default_ontology(self, *, created_by: str | None = None) -> dict[str, Any]:
        """注册并返回平台默认军事领域本体。"""
        definition = normalize_ontology_definition(ontology_payload())
        await self.repository.register_ontology(
            definition,
            created_by=created_by,
            change_reason="初始军事武器装备技术本体",
        )
        return definition

    async def register_ontology_version(
        self,
        *,
        definition: dict[str, Any],
        previous_version: str | None,
        change_reason: str,
        created_by: str,
    ) -> dict[str, Any]:
        """校验并注册一个可扩展、不可静默覆盖的本体版本。"""
        normalized = normalize_ontology_definition(definition)
        normalized_reason = change_reason.strip()
        if not normalized_reason:
            raise ValueError("本体版本变更原因不能为空")
        if normalized["version"] == DEFENSE_ONTOLOGY_V1.version and previous_version is not None:
            raise ValueError("默认初始本体不能声明前序版本")
        previous = None
        if previous_version is not None:
            previous = await self.repository.get_ontology(previous_version)
            if previous is None:
                raise LookupError(f"前序本体版本不存在: {previous_version}")
        await self.repository.register_ontology(
            normalized,
            created_by=created_by,
            previous_version=previous_version,
            change_reason=normalized_reason,
        )
        record = await self.repository.get_ontology_version(normalized["version"])
        if record is None:
            raise RuntimeError(f"本体版本注册后无法读取: {normalized['version']}")
        record["change_set"] = build_ontology_change_set(previous, normalized)
        return record

    async def get_ontology(self, version: str | None = None) -> dict[str, Any]:
        """读取指定本体；默认版本未落库时返回代码内不可变定义。"""
        requested = version or DEFENSE_ONTOLOGY_V1.version
        stored = await self.repository.get_ontology(requested)
        if stored is not None:
            return stored
        if requested == DEFENSE_ONTOLOGY_V1.version:
            return ontology_payload()
        raise LookupError(f"本体版本不存在: {requested}")

    async def get_ontology_version(self, version: str) -> dict[str, Any]:
        """读取版本治理元数据和相对前序快照的变更映射。"""
        record = await self.repository.get_ontology_version(version)
        if record is None:
            raise LookupError(f"本体版本不存在: {version}")
        previous = None
        if record["previous_version"] is not None:
            previous = await self.repository.get_ontology(record["previous_version"])
            if previous is None:
                raise RuntimeError(f"本体版本 {version} 的前序快照缺失")
        record["change_set"] = build_ontology_change_set(previous, record["definition"])
        return record

    async def list_ontology_versions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """列出已登记的本体版本元数据。"""
        return await self.repository.list_ontology_versions(limit=limit, offset=offset)

    async def list_review_queue(
        self,
        *,
        kb_id: str,
        status: str = "pending",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """读取等待人工复核的实体和关系 mention。"""
        return await self.repository.list_review_queue(
            kb_id=kb_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def decide(
        self,
        *,
        kb_id: str,
        target_type: str,
        target_id: str,
        decision: str,
        reviewer_uid: str,
        reason: str = "",
        decided_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """提交一条不可变审核决定。"""
        return await self.repository.decide(
            kb_id=kb_id,
            target_type=target_type,
            target_id=target_id,
            decision=decision,
            reviewer_uid=reviewer_uid,
            reason=reason,
            decided_payload=decided_payload,
        )

    async def register_conflict(
        self,
        *,
        kb_id: str,
        conflict_type: str,
        left_target_type: str,
        left_target_id: str,
        right_target_type: str | None,
        right_target_id: str | None,
        severity: str,
        summary: str,
        details: dict[str, Any] | None,
        detected_by: str,
    ) -> dict[str, Any]:
        """登记人工或规则发现的知识冲突。"""
        return await self.repository.register_conflict(
            kb_id=kb_id,
            conflict_type=conflict_type,
            left_target_type=left_target_type,
            left_target_id=left_target_id,
            right_target_type=right_target_type,
            right_target_id=right_target_id,
            severity=severity,
            summary=summary,
            details=details,
            detected_by=detected_by,
        )

    async def list_conflicts(
        self,
        *,
        kb_id: str,
        status: str = "open",
        severity: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """读取冲突治理队列。"""
        return await self.repository.list_conflicts(
            kb_id=kb_id,
            status=status,
            severity=severity,
            limit=limit,
            offset=offset,
        )

    async def resolve_conflict(
        self,
        *,
        kb_id: str,
        conflict_id: str,
        status: str,
        resolution: str,
        resolved_by: str,
    ) -> dict[str, Any]:
        """裁决并关闭一个知识冲突。"""
        return await self.repository.resolve_conflict(
            kb_id=kb_id,
            conflict_id=conflict_id,
            status=status,
            resolution=resolution,
            resolved_by=resolved_by,
        )
