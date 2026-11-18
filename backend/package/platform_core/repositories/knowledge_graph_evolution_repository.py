"""创新假设、实体版本与技术演化快照的 PostgreSQL 仓储。"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from platform_core.knowledge.graphs.graph_utils import normalize_entity_name
from platform_core.knowledge.graphs.projection_contract import (
    build_entity_redirect_projection_event,
    build_relation_lifecycle_projection_event,
)
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeGraphChangeEvent,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityAlias,
    KnowledgeGraphEntityMention,
    KnowledgeGraphEntityRedirect,
    KnowledgeGraphHypothesis,
    KnowledgeGraphProjectionOutbox,
    KnowledgeGraphRevision,
    KnowledgeGraphTrendSnapshot,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
)
from platform_core.utils import hashstr

HYPOTHESIS_REVIEW_STATUSES = {"pending", "accepted", "rejected", "disputed", "superseded"}


class KnowledgeGraphEvolutionRepository:
    """集中维护不应耦合到 Neo4j 查询实现的治理事实。"""

    async def latest_revision(self, kb_id: str) -> str | None:
        """读取知识库最新权威图谱 revision。"""
        async with pg_manager.get_async_session_context() as session:
            return await session.scalar(
                select(KnowledgeGraphRevision.revision_id)
                .where(KnowledgeGraphRevision.kb_id == kb_id)
                .order_by(KnowledgeGraphRevision.created_at.desc())
                .limit(1)
            )

    async def save_hypotheses(self, kb_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """幂等保存算法发现的 Hypothesis，禁止改写为 Fact。"""
        if not candidates:
            return []
        entity_ids = {
            entity_id
            for candidate in candidates
            for entity_id in (
                candidate["source"]["entity_id"],
                candidate["target"]["entity_id"],
            )
        }
        async with pg_manager.get_async_session_context() as session:
            known_ids = set(
                (
                    await session.scalars(
                        select(KnowledgeGraphEntity.entity_id).where(
                            KnowledgeGraphEntity.kb_id == kb_id,
                            KnowledgeGraphEntity.entity_id.in_(entity_ids),
                        )
                    )
                ).all()
            )
            if known_ids != entity_ids:
                missing = sorted(entity_ids - known_ids)
                raise ValueError(f"创新候选引用了不存在的实体: {', '.join(missing)}")

            for candidate in candidates:
                values = _hypothesis_values(kb_id, candidate)
                statement = insert(KnowledgeGraphHypothesis).values(**values)
                await session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_kg_hypothesis_identity",
                        set_={
                            "score": statement.excluded.score,
                            "evidence_path": statement.excluded.evidence_path,
                            "mechanism_hypothesis": statement.excluded.mechanism_hypothesis,
                            "feasibility_basis": statement.excluded.feasibility_basis,
                            "expected_effects": statement.excluded.expected_effects,
                            "applicable_conditions": statement.excluded.applicable_conditions,
                            "uncertainties": statement.excluded.uncertainties,
                            "updated_at": func.now(),
                        },
                    )
                )
        return await self.list_hypotheses(kb_id=kb_id, limit=len(candidates))

    async def list_hypotheses(
        self,
        *,
        kb_id: str,
        status: str = "pending",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """按分数读取创新关联候选及其证据路径。"""
        if status not in HYPOTHESIS_REVIEW_STATUSES:
            raise ValueError(f"不支持的假设状态: {status}")
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeGraphHypothesis)
                    .where(
                        KnowledgeGraphHypothesis.kb_id == kb_id,
                        KnowledgeGraphHypothesis.review_status == status,
                    )
                    .order_by(KnowledgeGraphHypothesis.score.desc(), KnowledgeGraphHypothesis.created_at.desc())
                    .limit(max(1, min(limit, 500)))
                    .offset(max(offset, 0))
                )
            ).all()
        return [_hypothesis_payload(row) for row in rows]

    async def review_hypothesis(
        self,
        *,
        kb_id: str,
        hypothesis_id: str,
        decision: str,
        reviewer_uid: str,
        reason: str,
    ) -> dict[str, Any]:
        """审核预测关联；接受后仍保持 Hypothesis，需独立证据才能晋升事实。"""
        if decision not in HYPOTHESIS_REVIEW_STATUSES - {"pending"}:
            raise ValueError(f"不支持的假设审核决定: {decision}")
        async with pg_manager.get_async_session_context() as session:
            row = await session.scalar(
                select(KnowledgeGraphHypothesis)
                .where(
                    KnowledgeGraphHypothesis.kb_id == kb_id,
                    KnowledgeGraphHypothesis.hypothesis_id == hypothesis_id,
                )
                .with_for_update()
            )
            if row is None:
                raise LookupError("创新假设不存在")
            before = {"review_status": row.review_status, "review_reason": row.review_reason}
            row.review_status = decision
            row.reviewed_by = reviewer_uid
            row.reviewed_at = datetime.now(UTC)
            row.review_reason = reason
            revision_id = uuid.uuid4().hex
            session.add(
                KnowledgeGraphRevision(
                    revision_id=revision_id,
                    kb_id=kb_id,
                    ontology_version="defense-kg-1.0",
                    reason="innovation_hypothesis_review",
                    summary={"hypothesis_id": hypothesis_id, "decision": decision},
                    created_by=reviewer_uid,
                )
            )
            session.add(
                KnowledgeGraphChangeEvent(
                    event_id=uuid.uuid4().hex,
                    kb_id=kb_id,
                    graph_revision=revision_id,
                    event_type="hypothesis_reviewed",
                    target_type="hypothesis",
                    target_id=hypothesis_id,
                    before_payload=before,
                    after_payload={"review_status": decision, "claim_level": "Hypothesis"},
                    reason=reason,
                    created_by=reviewer_uid,
                )
            )
        return {
            "hypothesis_id": hypothesis_id,
            "review_status": decision,
            "claim_level": "Hypothesis",
            "graph_revision": revision_id,
        }

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
        """记录实体合并或拆分 redirect，保留原实体和完整变更原因。"""
        if operation not in {"merge", "split"}:
            raise ValueError("operation 必须是 merge 或 split")
        targets = list(dict.fromkeys(target_entity_ids))
        if not targets or source_entity_id in targets:
            raise ValueError("redirect 目标不能为空且不能包含源实体")
        if operation == "merge" and len(targets) != 1:
            raise ValueError("merge 必须且只能指定一个目标实体")
        if operation == "split" and len(targets) < 2:
            raise ValueError("split 至少需要两个目标实体")

        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeGraphEntity)
                    .where(
                        KnowledgeGraphEntity.kb_id == kb_id,
                        KnowledgeGraphEntity.entity_id.in_([source_entity_id, *targets]),
                    )
                    .with_for_update()
                )
            ).all()
            entities = {row.entity_id: row for row in rows}
            missing = sorted({source_entity_id, *targets} - entities.keys())
            if missing:
                raise LookupError(f"实体不存在: {', '.join(missing)}")
            source = entities[source_entity_id]
            existing = await session.scalar(
                select(KnowledgeGraphEntityRedirect).where(
                    KnowledgeGraphEntityRedirect.kb_id == kb_id,
                    KnowledgeGraphEntityRedirect.source_entity_id == source_entity_id,
                )
            )
            if existing is not None:
                existing_targets = (existing.redirect_metadata or {}).get("target_entity_ids")
                if existing.operation == operation and existing_targets == targets:
                    return _redirect_payload(existing)
                raise ValueError("源实体已存在不同 redirect，需先进行冲突裁决")

            now = datetime.now(UTC)
            primary_target = targets[0]
            before = _entity_state(source)
            source.lifecycle_status = "redirected" if operation == "merge" else "split"
            source.superseded_by_entity_id = primary_target
            source.valid_to = now
            source.entity_version = int(source.entity_version or 1) + 1
            redirect = KnowledgeGraphEntityRedirect(
                redirect_id=uuid.uuid4().hex,
                kb_id=kb_id,
                source_entity_id=source_entity_id,
                target_entity_id=primary_target,
                operation=operation,
                reason=reason,
                redirect_metadata={"target_entity_ids": targets},
                created_by=created_by,
            )
            session.add(redirect)
            target = entities[primary_target]
            alias_statement = insert(KnowledgeGraphEntityAlias).values(
                entity_id=primary_target,
                alias=source.name,
                normalized_alias=normalize_entity_name(source.name),
                language="unknown",
                source=f"entity_{operation}",
                confidence=1.0,
            )
            await session.execute(
                alias_statement.on_conflict_do_nothing(index_elements=["entity_id", "normalized_alias", "language"])
            )
            revision_id = uuid.uuid4().hex
            session.add(
                KnowledgeGraphRevision(
                    revision_id=revision_id,
                    kb_id=kb_id,
                    ontology_version="defense-kg-1.0",
                    reason=f"entity_{operation}",
                    summary={
                        "source_entity_id": source_entity_id,
                        "target_entity_ids": targets,
                        "target_name": target.name,
                    },
                    created_by=created_by,
                )
            )
            session.add(
                KnowledgeGraphChangeEvent(
                    event_id=uuid.uuid4().hex,
                    kb_id=kb_id,
                    graph_revision=revision_id,
                    event_type=f"entity_{operation}",
                    target_type="entity",
                    target_id=source_entity_id,
                    before_payload=before,
                    after_payload=_entity_state(source),
                    reason=reason,
                    source_ref={"target_entity_ids": targets},
                    created_by=created_by,
                )
            )
            chunk_id = await session.scalar(
                select(KnowledgeGraphEntityMention.chunk_id)
                .where(
                    KnowledgeGraphEntityMention.kb_id == kb_id,
                    KnowledgeGraphEntityMention.entity_id == source_entity_id,
                )
                .order_by(KnowledgeGraphEntityMention.id.asc())
                .limit(1)
            )
            projection_event_id = None
            if chunk_id:
                projection_event = build_entity_redirect_projection_event(
                    kb_id=kb_id,
                    source_entity_id=source_entity_id,
                    target_entity_ids=targets,
                    operation=operation,
                    redirect_id=redirect.redirect_id,
                    reason=reason,
                    graph_revision=revision_id,
                )
                projection_event_id = projection_event["event_id"]
                session.add(
                    KnowledgeGraphProjectionOutbox(
                        event_id=projection_event_id,
                        kb_id=kb_id,
                        chunk_id=chunk_id,
                        graph_revision=revision_id,
                        payload=projection_event["payload"],
                        status="pending",
                    )
                )
            await session.flush()
            payload = _redirect_payload(redirect)
            payload["graph_revision"] = revision_id
            payload["projection_event_id"] = projection_event_id
            return payload

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
        """失效或替代关系，并在同一事务写入 revision、事件和投影 Outbox。"""
        if lifecycle_status not in {"invalid", "superseded"}:
            raise ValueError("关系生命周期只能更新为 invalid 或 superseded")
        reason = reason.strip()
        if not reason:
            raise ValueError("关系生命周期变更必须填写原因")
        replacement_id = str(superseded_by_triple_id or "").strip() or None
        if lifecycle_status == "superseded" and not replacement_id:
            raise ValueError("superseded 关系必须指定替代关系")
        if lifecycle_status == "invalid" and replacement_id:
            raise ValueError("invalid 关系不能指定替代关系")
        if replacement_id == triple_id:
            raise ValueError("关系不能替代自身")

        async with pg_manager.get_async_session_context() as session:
            relation = await session.scalar(
                select(KnowledgeGraphTriple)
                .where(
                    KnowledgeGraphTriple.kb_id == kb_id,
                    KnowledgeGraphTriple.triple_id == triple_id,
                )
                .with_for_update()
            )
            if relation is None:
                raise LookupError("关系不存在")
            if relation.lifecycle_status != "active":
                raise ValueError("只有 active 关系可以失效或被替代")

            replacement = None
            if replacement_id:
                replacement = await session.scalar(
                    select(KnowledgeGraphTriple).where(
                        KnowledgeGraphTriple.kb_id == kb_id,
                        KnowledgeGraphTriple.triple_id == replacement_id,
                        KnowledgeGraphTriple.lifecycle_status == "active",
                    )
                )
                if replacement is None:
                    raise LookupError("替代关系不存在或不是 active 状态")

            now = datetime.now(UTC)
            before = _relation_state(relation)
            relation.lifecycle_status = lifecycle_status
            relation.superseded_by_triple_id = replacement_id
            relation.valid_to = now
            relation.relation_version = int(relation.relation_version or 1) + 1
            relation.vector_status = "disabled"
            relation.vector_next_retry_at = None
            relation.vector_locked_until = None
            relation.vector_lock_token = None

            parent_revision_id = await session.scalar(
                select(KnowledgeGraphRevision.revision_id)
                .where(KnowledgeGraphRevision.kb_id == kb_id)
                .order_by(KnowledgeGraphRevision.created_at.desc())
                .limit(1)
            )
            ontology_version = await session.scalar(
                select(KnowledgeGraphTripleMention.ontology_version)
                .where(
                    KnowledgeGraphTripleMention.kb_id == kb_id,
                    KnowledgeGraphTripleMention.triple_id == triple_id,
                    KnowledgeGraphTripleMention.ontology_version.is_not(None),
                )
                .order_by(KnowledgeGraphTripleMention.created_at.desc())
                .limit(1)
            )
            chunk_id = await session.scalar(
                select(KnowledgeGraphTripleMention.chunk_id)
                .where(
                    KnowledgeGraphTripleMention.kb_id == kb_id,
                    KnowledgeGraphTripleMention.triple_id == triple_id,
                )
                .order_by(KnowledgeGraphTripleMention.created_at.asc())
                .limit(1)
            )
            if not chunk_id:
                raise ValueError("关系缺少可定位 mention，不能生成可重放投影")

            revision_id = uuid.uuid4().hex
            after = _relation_state(relation)
            session.add(
                KnowledgeGraphRevision(
                    revision_id=revision_id,
                    kb_id=kb_id,
                    parent_revision_id=parent_revision_id,
                    ontology_version=str(ontology_version or "legacy-unversioned"),
                    reason="relation_lifecycle_changed",
                    summary={
                        "triple_id": triple_id,
                        "lifecycle_status": lifecycle_status,
                        "superseded_by_triple_id": replacement_id,
                    },
                    created_by=created_by,
                )
            )
            session.add(
                KnowledgeGraphChangeEvent(
                    event_id=uuid.uuid4().hex,
                    kb_id=kb_id,
                    graph_revision=revision_id,
                    event_type="relation_lifecycle_changed",
                    target_type="relation",
                    target_id=triple_id,
                    before_payload=before,
                    after_payload=after,
                    reason=reason,
                    source_ref={"superseded_by_triple_id": replacement_id},
                    created_by=created_by,
                )
            )
            projection_event = build_relation_lifecycle_projection_event(
                kb_id=kb_id,
                triple_id=triple_id,
                lifecycle_status=lifecycle_status,
                superseded_by_triple_id=replacement_id,
                relation_version=relation.relation_version,
                valid_to=now.isoformat(),
                reason=reason,
                graph_revision=revision_id,
            )
            session.add(
                KnowledgeGraphProjectionOutbox(
                    event_id=projection_event["event_id"],
                    kb_id=kb_id,
                    chunk_id=chunk_id,
                    graph_revision=revision_id,
                    payload=projection_event["payload"],
                    status="pending",
                )
            )
            await session.flush()
            return {
                **after,
                "graph_revision": revision_id,
                "projection_event_id": projection_event["event_id"],
            }

    async def entity_history(self, *, kb_id: str, entity_id: str) -> dict[str, Any]:
        """读取实体当前状态、redirect 与不可变变更历史。"""
        async with pg_manager.get_async_session_context() as session:
            entity = await session.scalar(
                select(KnowledgeGraphEntity).where(
                    KnowledgeGraphEntity.kb_id == kb_id,
                    KnowledgeGraphEntity.entity_id == entity_id,
                )
            )
            if entity is None:
                raise LookupError("实体不存在")
            redirects = (
                await session.scalars(
                    select(KnowledgeGraphEntityRedirect)
                    .where(
                        KnowledgeGraphEntityRedirect.kb_id == kb_id,
                        (
                            (KnowledgeGraphEntityRedirect.source_entity_id == entity_id)
                            | (KnowledgeGraphEntityRedirect.target_entity_id == entity_id)
                        ),
                    )
                    .order_by(KnowledgeGraphEntityRedirect.created_at.asc())
                )
            ).all()
            events = (
                await session.scalars(
                    select(KnowledgeGraphChangeEvent)
                    .where(
                        KnowledgeGraphChangeEvent.kb_id == kb_id,
                        KnowledgeGraphChangeEvent.target_type == "entity",
                        KnowledgeGraphChangeEvent.target_id == entity_id,
                    )
                    .order_by(KnowledgeGraphChangeEvent.created_at.asc())
                )
            ).all()
        return {
            "entity": _entity_state(entity),
            "redirects": [_redirect_payload(row) for row in redirects],
            "events": [_change_payload(row) for row in events],
        }

    async def build_entity_observations(self, *, kb_id: str, entity_id: str) -> list[dict[str, Any]]:
        """从已接受 mention 和来源元数据构建月度演化观测。"""
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(
                        KnowledgeGraphEntityMention.file_id,
                        KnowledgeGraphEntityMention.confidence,
                        KnowledgeGraphEntityMention.created_at,
                        KnowledgeFile.file_type,
                        KnowledgeFile.created_at,
                        KnowledgeChunk.source_metadata,
                    )
                    .join(KnowledgeFile, KnowledgeFile.file_id == KnowledgeGraphEntityMention.file_id)
                    .join(KnowledgeChunk, KnowledgeChunk.chunk_id == KnowledgeGraphEntityMention.chunk_id)
                    .where(
                        KnowledgeGraphEntityMention.kb_id == kb_id,
                        KnowledgeGraphEntityMention.entity_id == entity_id,
                        KnowledgeGraphEntityMention.review_status == "accepted",
                    )
                )
            ).all()
        buckets: dict[str, dict[str, Any]] = defaultdict(_empty_observation_bucket)
        for file_id, confidence, mention_created_at, file_type, file_created_at, metadata in rows:
            metadata = metadata if isinstance(metadata, dict) else {}
            observed_at = _source_datetime(metadata) or file_created_at or mention_created_at
            period = observed_at.astimezone(UTC).strftime("%Y-%m")
            bucket = buckets[period]
            bucket["file_ids"].add(str(file_id))
            bucket["citation_count"] += max(int(metadata.get("citation_count") or 0), 0)
            family_id = str(metadata.get("patent_family_id") or "").strip()
            if family_id:
                bucket["patent_family_ids"].add(family_id)
            if metadata.get("validation_status") or str(file_type or "").lower() in {"test", "prototype", "trial"}:
                bucket["validation_count"] += 1
            bucket["domains"].update(str(value) for value in metadata.get("domains") or [] if str(value))
            if confidence is not None:
                bucket["qualities"].append(max(0.0, min(float(confidence), 1.0)))
        observations = []
        for period, bucket in sorted(buckets.items()):
            observations.append(
                {
                    "period": period,
                    "document_count": len(bucket["file_ids"]),
                    "citation_count": bucket["citation_count"],
                    "patent_family_count": len(bucket["patent_family_ids"]),
                    "validation_count": bucket["validation_count"],
                    "domains": sorted(bucket["domains"]),
                    "evidence_quality": (
                        sum(bucket["qualities"]) / len(bucket["qualities"]) if bucket["qualities"] else 0.0
                    ),
                }
            )
        return observations

    async def save_trend_snapshot(
        self,
        *,
        kb_id: str,
        entity_id: str,
        analysis: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """幂等保存同一算法和统计时点的演化快照。"""
        as_of = datetime.fromisoformat(str(analysis["as_of"]).replace("Z", "+00:00"))
        snapshot_id = hashstr(
            f"{kb_id}:{entity_id}:{analysis['algorithm_version']}:{as_of.isoformat()}",
            length=32,
        )
        values = {
            "snapshot_id": snapshot_id,
            "kb_id": kb_id,
            "entity_id": entity_id,
            "as_of": as_of,
            "algorithm_version": analysis["algorithm_version"],
            "frontier_score": analysis["frontier_score"],
            "maturity_stage": analysis["maturity_stage"],
            "burst_level": analysis["burst_level"],
            "component_scores": analysis["component_scores"],
            "time_series": analysis["time_series"],
            "evidence": evidence,
        }
        async with pg_manager.get_async_session_context() as session:
            statement = insert(KnowledgeGraphTrendSnapshot).values(**values)
            await session.execute(statement.on_conflict_do_nothing(constraint="uq_kg_trend_snapshot"))
        return {**analysis, "snapshot_id": snapshot_id, "entity_id": entity_id, "evidence": evidence}

    async def list_trend_snapshots(
        self,
        *,
        kb_id: str,
        entity_id: str,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """读取实体最近的演化评分历史。"""
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeGraphTrendSnapshot)
                    .where(
                        KnowledgeGraphTrendSnapshot.kb_id == kb_id,
                        KnowledgeGraphTrendSnapshot.entity_id == entity_id,
                    )
                    .order_by(KnowledgeGraphTrendSnapshot.as_of.desc())
                    .limit(max(1, min(limit, 120)))
                )
            ).all()
        return [
            {
                "snapshot_id": row.snapshot_id,
                "entity_id": row.entity_id,
                "as_of": row.as_of.isoformat(),
                "algorithm_version": row.algorithm_version,
                "frontier_score": row.frontier_score,
                "maturity_stage": row.maturity_stage,
                "burst_level": row.burst_level,
                "component_scores": row.component_scores,
                "time_series": row.time_series,
                "evidence": row.evidence,
            }
            for row in rows
        ]


def _hypothesis_values(kb_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
    if candidate.get("claim_level") != "Hypothesis":
        raise ValueError("创新预测只允许保存为 Hypothesis")
    return {
        "hypothesis_id": candidate["hypothesis_id"],
        "kb_id": kb_id,
        "source_entity_id": candidate["source"]["entity_id"],
        "target_entity_id": candidate["target"]["entity_id"],
        "relation_type": candidate["relation_type"],
        "discovery_mode": candidate["discovery_mode"],
        "claim_level": "Hypothesis",
        "score": candidate["score"],
        "evidence_path": candidate["evidence_path"],
        "mechanism_hypothesis": candidate["mechanism_hypothesis"],
        "feasibility_basis": candidate["feasibility_basis"],
        "expected_effects": candidate["expected_effects"],
        "applicable_conditions": candidate.get("applicable_conditions") or [],
        "uncertainties": candidate["uncertainties"],
        "algorithm_version": candidate["algorithm_version"],
        "review_status": "pending",
    }


def _hypothesis_payload(row: KnowledgeGraphHypothesis) -> dict[str, Any]:
    return {
        "hypothesis_id": row.hypothesis_id,
        "kb_id": row.kb_id,
        "source_entity_id": row.source_entity_id,
        "target_entity_id": row.target_entity_id,
        "relation_type": row.relation_type,
        "discovery_mode": row.discovery_mode,
        "claim_level": "Hypothesis",
        "score": row.score,
        "evidence_path": row.evidence_path,
        "mechanism_hypothesis": row.mechanism_hypothesis,
        "feasibility_basis": row.feasibility_basis,
        "expected_effects": row.expected_effects,
        "applicable_conditions": row.applicable_conditions,
        "uncertainties": row.uncertainties,
        "algorithm_version": row.algorithm_version,
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_reason": row.review_reason,
        "created_at": row.created_at.isoformat(),
    }


def _entity_state(entity: KnowledgeGraphEntity) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "normalized_name": entity.normalized_name,
        "type": entity.label,
        "attributes": entity.attributes or {},
        "lifecycle_status": entity.lifecycle_status,
        "superseded_by_entity_id": entity.superseded_by_entity_id,
        "valid_from": entity.valid_from.isoformat() if entity.valid_from else None,
        "valid_to": entity.valid_to.isoformat() if entity.valid_to else None,
        "entity_version": entity.entity_version,
    }


def _relation_state(relation: KnowledgeGraphTriple) -> dict[str, Any]:
    """序列化权威关系生命周期状态。"""
    return {
        "triple_id": relation.triple_id,
        "source_entity_id": relation.source_entity_id,
        "target_entity_id": relation.target_entity_id,
        "relation_type": relation.relation_type,
        "lifecycle_status": relation.lifecycle_status,
        "superseded_by_triple_id": relation.superseded_by_triple_id,
        "valid_from": relation.valid_from.isoformat() if relation.valid_from else None,
        "valid_to": relation.valid_to.isoformat() if relation.valid_to else None,
        "relation_version": relation.relation_version,
    }


def _redirect_payload(row: KnowledgeGraphEntityRedirect) -> dict[str, Any]:
    return {
        "redirect_id": row.redirect_id,
        "kb_id": row.kb_id,
        "source_entity_id": row.source_entity_id,
        "target_entity_id": row.target_entity_id,
        "target_entity_ids": (row.redirect_metadata or {}).get("target_entity_ids") or [row.target_entity_id],
        "operation": row.operation,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _change_payload(row: KnowledgeGraphChangeEvent) -> dict[str, Any]:
    return {
        "event_id": row.event_id,
        "graph_revision": row.graph_revision,
        "event_type": row.event_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "before": row.before_payload,
        "after": row.after_payload,
        "reason": row.reason,
        "source_ref": row.source_ref,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def _empty_observation_bucket() -> dict[str, Any]:
    return {
        "file_ids": set(),
        "citation_count": 0,
        "patent_family_ids": set(),
        "validation_count": 0,
        "domains": set(),
        "qualities": [],
    }


def _source_datetime(metadata: dict[str, Any]) -> datetime | None:
    value = metadata.get("publication_date") or metadata.get("published_at") or metadata.get("filing_date")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
