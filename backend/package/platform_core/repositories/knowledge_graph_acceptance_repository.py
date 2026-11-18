"""图谱来源版本、构建运行和验收报告的 PostgreSQL 仓储。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from platform_core.repositories.knowledge_graph_source_repository import KnowledgeGraphSourceRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeChunk,
    KnowledgeGraphBuildRun,
    KnowledgeGraphBuildStageRun,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphEvaluationRun,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
    KnowledgeSourceDocument,
)


class KnowledgeGraphAcceptanceRepository:
    """维护可复现构建谱系和 Pilot 规模统计。"""

    async def start_build_run(
        self,
        *,
        kb_id: str,
        pipeline_revision: str,
        ontology_version: str,
        model_versions: dict[str, Any],
        rule_version: str,
        scope: str,
        started_by: str | None = None,
        max_chunks: int | None = None,
    ) -> dict[str, Any]:
        """登记来源版本并启动一次图谱构建运行。"""
        if scope not in {"pending", "failed"}:
            raise ValueError("构建 scope 必须是 pending 或 failed")
        if max_chunks is not None and max_chunks <= 0:
            raise ValueError("构建 max_chunks 必须大于 0")
        async with pg_manager.get_async_session_context() as session:
            selected_conditions = [
                KnowledgeChunk.kb_id == kb_id,
                KnowledgeChunk.graph_indexed.is_not(True),
                KnowledgeChunk.graph_excluded.is_not(True),
            ]
            if scope == "failed":
                extraction_status = KnowledgeChunk.graph_extraction_details["status"].as_string()
                selected_conditions.append(extraction_status == "failed")
            selected_chunk_ids: list[str] | None = None
            if max_chunks is None:
                selected_file_ids = set(
                    await session.scalars(select(KnowledgeChunk.file_id).where(*selected_conditions).distinct())
                )
            else:
                selected_rows = (
                    await session.execute(
                        select(KnowledgeChunk.file_id, KnowledgeChunk.chunk_id)
                        .where(*selected_conditions)
                        .order_by(KnowledgeChunk.id.asc())
                        .limit(max_chunks)
                    )
                ).all()
                selected_file_ids = {str(file_id) for file_id, _ in selected_rows}
                selected_chunk_ids = [str(chunk_id) for _, chunk_id in selected_rows]
            registered = await KnowledgeGraphSourceRepository().register_in_session(session, kb_id=kb_id)
            manifest = [
                {key: value for key, value in item.items() if key != "file_id"}
                for item in registered
                if item["file_id"] in selected_file_ids
            ]

            run_id = uuid.uuid4().hex
            input_hash = _canonical_sha256(
                {
                    "kb_id": kb_id,
                    "pipeline_revision": pipeline_revision,
                    "ontology_version": ontology_version,
                    "model_versions": model_versions,
                    "rule_version": rule_version,
                    "scope": scope,
                    "chunk_ids": selected_chunk_ids,
                    "documents": manifest,
                }
            )
            session.add(
                KnowledgeGraphBuildRun(
                    run_id=run_id,
                    kb_id=kb_id,
                    pipeline_revision=pipeline_revision,
                    ontology_version=ontology_version,
                    model_versions=model_versions,
                    input_hash=input_hash,
                    status="processing",
                    scope=scope,
                    document_ids=[item["document_id"] for item in manifest],
                    rule_version=rule_version,
                    started_by=started_by,
                    metrics={"source_document_count": len(manifest)},
                )
            )
            return {
                "run_id": run_id,
                "input_hash": input_hash,
                "document_ids": [item["document_id"] for item in manifest],
                "chunk_ids": selected_chunk_ids,
            }

    async def finish_build_run(
        self,
        *,
        run_id: str,
        status: str,
        metrics: dict[str, Any],
        error: str = "",
    ) -> bool:
        """以终态和输出哈希完成构建运行。"""
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("构建终态必须是 completed、failed 或 cancelled")
        output_hash = _canonical_sha256({"status": status, "metrics": metrics, "error": error})
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                update(KnowledgeGraphBuildRun)
                .where(
                    KnowledgeGraphBuildRun.run_id == run_id,
                    KnowledgeGraphBuildRun.status == "processing",
                )
                .values(
                    status=status,
                    metrics=metrics,
                    output_hash=output_hash,
                    error=error[:4000],
                    finished_at=datetime.now(UTC),
                )
            )
            return bool(result.rowcount)

    async def start_stage(
        self,
        *,
        run_id: str,
        stage_code: str,
        stage_order: int,
        input_payload: Any,
        model_versions: dict[str, Any],
        ontology_version: str,
        rule_version: str,
        attempt_count: int = 1,
    ) -> dict[str, Any]:
        """在运行仍处于 processing 时登记一次阶段尝试。"""
        if stage_order < 0:
            raise ValueError("阶段顺序不能为负数")
        if attempt_count < 1:
            raise ValueError("阶段尝试次数必须大于等于 1")
        stage_run_id = uuid.uuid4().hex
        input_hash = _canonical_sha256(input_payload)
        async with pg_manager.get_async_session_context() as session:
            build_run = await session.scalar(
                select(KnowledgeGraphBuildRun).where(KnowledgeGraphBuildRun.run_id == run_id).with_for_update()
            )
            if build_run is None:
                raise LookupError("图谱构建运行不存在")
            if build_run.status != "processing":
                raise ValueError("只有 processing 构建运行可以启动阶段")
            session.add(
                KnowledgeGraphBuildStageRun(
                    stage_run_id=stage_run_id,
                    run_id=run_id,
                    kb_id=build_run.kb_id,
                    stage_code=stage_code,
                    stage_order=stage_order,
                    status="processing",
                    input_hash=input_hash,
                    model_versions=model_versions,
                    ontology_version=ontology_version,
                    rule_version=rule_version,
                    attempt_count=attempt_count,
                )
            )
        return {"stage_run_id": stage_run_id, "input_hash": input_hash}

    async def finish_stage(
        self,
        *,
        stage_run_id: str,
        status: str,
        metrics: dict[str, Any],
        output_payload: Any | None = None,
        error: str = "",
    ) -> bool:
        """以不可逆终态完成一个阶段并记录规范化输出哈希。"""
        if status not in {"completed", "failed", "cancelled", "skipped"}:
            raise ValueError("阶段终态必须是 completed、failed、cancelled 或 skipped")
        output_hash = _canonical_sha256(
            output_payload if output_payload is not None else {"status": status, "metrics": metrics, "error": error}
        )
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                update(KnowledgeGraphBuildStageRun)
                .where(
                    KnowledgeGraphBuildStageRun.stage_run_id == stage_run_id,
                    KnowledgeGraphBuildStageRun.status == "processing",
                )
                .values(
                    status=status,
                    metrics=metrics,
                    output_hash=output_hash,
                    error=error[:4000],
                    finished_at=datetime.now(UTC),
                )
            )
            return bool(result.rowcount)

    async def list_build_runs(self, *, kb_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """按开始时间倒序返回构建运行摘要。"""
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeGraphBuildRun)
                    .where(KnowledgeGraphBuildRun.kb_id == kb_id)
                    .order_by(KnowledgeGraphBuildRun.started_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return [_serialize_build_run(row) for row in rows]

    async def get_build_run_with_stages(self, *, kb_id: str, run_id: str) -> dict[str, Any] | None:
        """读取单次运行及其全部阶段尝试。"""
        async with pg_manager.get_async_session_context() as session:
            build_run = await session.scalar(
                select(KnowledgeGraphBuildRun).where(
                    KnowledgeGraphBuildRun.kb_id == kb_id,
                    KnowledgeGraphBuildRun.run_id == run_id,
                )
            )
            if build_run is None:
                return None
            stages = (
                await session.scalars(
                    select(KnowledgeGraphBuildStageRun)
                    .where(KnowledgeGraphBuildStageRun.run_id == run_id)
                    .order_by(
                        KnowledgeGraphBuildStageRun.stage_order.asc(),
                        KnowledgeGraphBuildStageRun.attempt_count.asc(),
                    )
                )
            ).all()
        return {**_serialize_build_run(build_run), "stages": [_serialize_stage_run(stage) for stage in stages]}

    async def collect_pilot_stats(self, kb_id: str) -> dict[str, Any]:
        """从权威数据计算关系去重且排除未审核 Hypothesis 的规模统计。"""
        async with pg_manager.get_async_session_context() as session:
            source_rows = (
                await session.execute(
                    select(KnowledgeSourceDocument.source_type, func.count())
                    .where(KnowledgeSourceDocument.kb_id == kb_id)
                    .group_by(KnowledgeSourceDocument.source_type)
                )
            ).all()
            source_counts = {str(source_type): int(count or 0) for source_type, count in source_rows}
            document_lists = (
                await session.scalars(
                    select(KnowledgeGraphBuildRun.document_ids).where(
                        KnowledgeGraphBuildRun.kb_id == kb_id,
                        KnowledgeGraphBuildRun.status == "completed",
                    )
                )
            ).all()
            built_documents = {
                str(document_id) for document_ids in document_lists for document_id in (document_ids or [])
            }
            accepted_entities = await session.scalar(
                select(func.count(func.distinct(KnowledgeGraphEntity.entity_id)))
                .join(
                    KnowledgeGraphEntityMention,
                    KnowledgeGraphEntityMention.entity_id == KnowledgeGraphEntity.entity_id,
                )
                .where(
                    KnowledgeGraphEntity.kb_id == kb_id,
                    KnowledgeGraphEntity.lifecycle_status == "active",
                    KnowledgeGraphEntityMention.review_status == "accepted",
                    KnowledgeGraphEntityMention.start_char.is_not(None),
                    KnowledgeGraphEntityMention.end_char.is_not(None),
                    KnowledgeGraphEntityMention.end_char > KnowledgeGraphEntityMention.start_char,
                )
            )
            accepted_relations = await session.scalar(
                select(func.count(func.distinct(KnowledgeGraphTriple.triple_id)))
                .join(
                    KnowledgeGraphTripleMention,
                    KnowledgeGraphTripleMention.triple_id == KnowledgeGraphTriple.triple_id,
                )
                .where(
                    KnowledgeGraphTriple.kb_id == kb_id,
                    KnowledgeGraphTriple.lifecycle_status == "active",
                    KnowledgeGraphTripleMention.review_status == "accepted",
                    KnowledgeGraphTripleMention.claim_level.in_(["Fact", "Inference"]),
                    KnowledgeGraphTripleMention.evidence_spans.is_not(None),
                    func.jsonb_typeof(KnowledgeGraphTripleMention.evidence_spans) == "array",
                    func.jsonb_array_length(KnowledgeGraphTripleMention.evidence_spans) > 0,
                )
            )
            source_documents = sum(source_counts.values())
            return {
                "source_documents": source_documents,
                "paper_documents": source_counts.get("paper", 0),
                "patent_documents": source_counts.get("patent", 0),
                "documents_with_build_runs": len(built_documents),
                "accepted_entities": int(accepted_entities or 0),
                "accepted_relations": int(accepted_relations or 0),
                "duplicate_relation_mentions_excluded": True,
                "unreviewed_hypotheses_excluded": True,
            }

    async def record_evaluation(
        self,
        *,
        kb_id: str,
        pipeline_revision: str,
        gold_manifest_sha256: str,
        prediction_sha256: str,
        report: dict[str, Any],
        created_by: str | None,
    ) -> str:
        """按输入哈希幂等登记一次验收报告。"""
        evaluation_id = hashlib.sha256(
            f"{kb_id}:{pipeline_revision}:{gold_manifest_sha256}:{prediction_sha256}".encode()
        ).hexdigest()[:32]
        status = "passed" if report.get("passed") is True else "failed"
        async with pg_manager.get_async_session_context() as session:
            statement = insert(KnowledgeGraphEvaluationRun).values(
                evaluation_id=evaluation_id,
                kb_id=kb_id,
                pipeline_revision=pipeline_revision,
                gold_manifest_sha256=gold_manifest_sha256,
                prediction_sha256=prediction_sha256,
                report=report,
                status=status,
                created_by=created_by,
            )
            await session.execute(statement.on_conflict_do_nothing(index_elements=["evaluation_id"]))
        return evaluation_id

    async def get_latest_evaluation(self, kb_id: str) -> dict[str, Any] | None:
        """读取最近一次不可变验收报告。"""
        async with pg_manager.get_async_session_context() as session:
            evaluation = await session.scalar(
                select(KnowledgeGraphEvaluationRun)
                .where(KnowledgeGraphEvaluationRun.kb_id == kb_id)
                .order_by(KnowledgeGraphEvaluationRun.created_at.desc())
                .limit(1)
            )
            if evaluation is None:
                return None
            return {
                "evaluation_id": evaluation.evaluation_id,
                "pipeline_revision": evaluation.pipeline_revision,
                "gold_manifest_sha256": evaluation.gold_manifest_sha256,
                "prediction_sha256": evaluation.prediction_sha256,
                "report": evaluation.report,
                "status": evaluation.status,
                "created_by": evaluation.created_by,
                "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None,
            }

    async def get_build_run_summary(self, kb_id: str) -> dict[str, int]:
        """按终态汇总可追溯构建运行。"""
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(KnowledgeGraphBuildRun.status, func.count())
                    .where(KnowledgeGraphBuildRun.kb_id == kb_id)
                    .group_by(KnowledgeGraphBuildRun.status)
                )
            ).all()
        counts = {"processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
        counts.update({str(status): int(count or 0) for status, count in rows})
        return counts


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _serialize_build_run(run: KnowledgeGraphBuildRun) -> dict[str, Any]:
    """把构建运行转为稳定的 HTTP 友好结构。"""
    return {
        "run_id": run.run_id,
        "kb_id": run.kb_id,
        "pipeline_revision": run.pipeline_revision,
        "ontology_version": run.ontology_version,
        "model_versions": run.model_versions or {},
        "input_hash": run.input_hash,
        "output_hash": run.output_hash,
        "status": run.status,
        "scope": run.scope,
        "document_ids": run.document_ids or [],
        "rule_version": run.rule_version,
        "started_by": run.started_by,
        "attempt_count": run.attempt_count,
        "metrics": run.metrics or {},
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _serialize_stage_run(stage: KnowledgeGraphBuildStageRun) -> dict[str, Any]:
    """把阶段运行转为稳定的 HTTP 友好结构。"""
    return {
        "stage_run_id": stage.stage_run_id,
        "stage_code": stage.stage_code,
        "stage_order": stage.stage_order,
        "status": stage.status,
        "input_hash": stage.input_hash,
        "output_hash": stage.output_hash,
        "model_versions": stage.model_versions or {},
        "ontology_version": stage.ontology_version,
        "rule_version": stage.rule_version,
        "metrics": stage.metrics or {},
        "error": stage.error,
        "attempt_count": stage.attempt_count,
        "started_at": stage.started_at.isoformat() if stage.started_at else None,
        "finished_at": stage.finished_at.isoformat() if stage.finished_at else None,
    }
