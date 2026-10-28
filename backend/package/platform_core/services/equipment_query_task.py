"""需求 Query 分批生成：所有领域写入受 Durable Task lease 保护。"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from uuid import uuid4

from platform_core.config import get_int_env
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.storage.postgres.models_equipment import EquipmentQuery, EquipmentQueryRevision
from platform_core.utils.datetime_utils import format_utc_datetime, utc_now_naive

EQUIPMENT_QUERY_TASK_TYPE = "equipment_query_generation"
EQUIPMENT_QUERY_MAX_RUNNING = get_int_env("EQUIPMENT_QUERY_MAX_RUNNING", 4)


async def run_equipment_query_generation(context) -> dict[str, Any]:
    """复用规划与已保存结果，只生成缺失维度并逐条提交。"""
    from equipment_deep_research.query_library.generator import ModelQueryGenerator
    from equipment_deep_research.query_library.models import (
        GeneratedCandidate,
        GenerationValidationError,
        SourceReference,
    )
    from platform_core.services.equipment_model_adapter import (
        create_equipment_provider,
        resolve_managed_equipment_model,
    )

    generation_id = str((context.payload or {}).get("generation_id") or "").strip()
    if not generation_id:
        raise ValueError("equipment_query_generation payload 缺少 generation_id")
    state: dict[str, Any] = {}

    async def owned(operation):
        async def guarded(session, record):
            if record.cancel_requested:
                raise asyncio.CancelledError("Task was cancelled")
            job = await EquipmentResearchRepository(session).lock_generation(generation_id)
            if job is None:
                raise RuntimeError("Query 生成任务不存在")
            if job.status == "cancelled":
                raise asyncio.CancelledError("Query generation was cancelled")
            await operation(session, job)

        await context.run_owned_transaction(guarded)

    async def begin(session, job):
        state.update(job.to_dict())
        state["payload"] = dict(job.payload or {})
        if job.status == "completed":
            return
        repo = EquipmentResearchRepository(session)
        # 复用已落库的生成结果，用户后来删除的结果不再自动重建。
        rows = []
        for query_id in state["query_ids"]:
            row = await repo.get_query(query_id)
            if row is not None:
                rows.append(row)
        state["accepted"] = [
            GeneratedCandidate(
                coverage_slot=str((row.payload or {}).get("coverage_slot") or ""),
                query=row.query_text,
                supplemental_information=row.supplemental_information,
                generation_rationale=str((row.payload or {}).get("generation_rationale") or ""),
                source_references=tuple(
                    SourceReference.from_dict(item) for item in (row.payload or {}).get("source_references", [])
                ),
                demand_chain=dict((row.payload or {}).get("demand_chain") or {}),
                quality_review=dict((row.payload or {}).get("quality_review") or {}),
            )
            for row in rows
        ]
        state["existing"] = [
            row.query_text
            for row in await repo.list_queries(job.owner_uid, limit=10000)
            if row.id not in state["query_ids"]
        ]
        job.status = "running"
        job.updated_at = utc_now_naive()

    await owned(begin)
    if state["status"] == "completed":
        return {"status": "completed", "generation_id": generation_id, "query_ids": state["query_ids"]}
    job_payload = state["payload"]

    async def stage(value):
        async def persist(_session, job):
            job.payload = {
                **(job.payload or {}),
                "stage": value,
                "stage_started_at": format_utc_datetime(utc_now_naive()),
            }
            job.updated_at = utc_now_naive()

        await owned(persist)

    async def checkpoint(value):
        async def persist(_session, job):
            job.payload = {**(job.payload or {}), "planning_checkpoint": value}
            job.updated_at = utc_now_naive()

        await owned(persist)

    async def batch_progress(value):
        async def persist(_session, job):
            job.payload = {**(job.payload or {}), "batch_progress": value}
            job.updated_at = utc_now_naive()

        await owned(persist)

    async def save_candidate(candidate):
        async def persist(session, job):
            repo = EquipmentResearchRepository(session)
            fingerprint = hashlib.sha256(f"{job.owner_uid}:{candidate.query}".encode()).hexdigest()
            if await repo.get_query_by_fingerprint(fingerprint) is not None:
                raise GenerationValidationError("生成内容已存在，请重试补齐剩余维度")
            query = EquipmentQuery(
                id=f"query-{uuid4()}",
                project_id=job.project_id,
                owner_uid=job.owner_uid,
                query_text=candidate.query,
                query_fingerprint=fingerprint,
                supplemental_information=candidate.supplemental_information,
                status="draft",
                source_type="agent",
                payload={
                    "generation_id": generation_id,
                    "model_spec": job_payload.get("model_spec", ""),
                    "coverage_slot": candidate.coverage_slot,
                    "generation_rationale": candidate.generation_rationale,
                    "demand_chain": candidate.demand_chain,
                    "quality_review": candidate.quality_review,
                    "source_references": [item.to_dict() for item in candidate.source_references],
                    "knowledge_enabled": job_payload.get("knowledge_enabled", True),
                    "knowledge_ids": job_payload.get("knowledge_ids"),
                },
            )
            await repo.add_query(query)
            await repo.add_query_revision(
                EquipmentQueryRevision(
                    query_id=query.id,
                    version=1,
                    change_type="generated",
                    snapshot=query.to_dict(),
                )
            )
            job.payload = {**(job.payload or {}), "query_ids": [*(job.payload or {}).get("query_ids", []), query.id]}
            job.updated_at = utc_now_naive()

        await owned(persist)

    try:
        runtime = resolve_managed_equipment_model(str(job_payload.get("model_spec") or ""))
        provider = create_equipment_provider(runtime, isolation_key=f"query-gen-{generation_id}")
        generator = ModelQueryGenerator(
            provider,
            provider_snapshot={
                "provider": runtime["provider"],
                "model": runtime["model"],
                "model_spec": runtime["model_spec"],
            },
            model_options={"reasoning_effort": "medium"},
            default_profile="efficient",
        )
        result = await generator.generate(
            topic=state["topic"],
            supplemental_information=job_payload.get("supplemental_information", ""),
            reference_urls=tuple(job_payload.get("reference_urls") or []),
            count=job_payload.get("count", 6),
            existing_queries=state["existing"],
            accepted_candidates=state["accepted"],
            checkpoint=job_payload.get("planning_checkpoint"),
            on_checkpoint=checkpoint,
            on_candidate=save_candidate,
            on_stage=stage,
            on_batch=batch_progress,
            batch_size=2,
            max_parallel=2,
            before_batch=context.raise_if_cancelled,
        )

        async def complete(_session, job):
            job.status = "completed"
            job.payload = {
                **(job.payload or {}),
                "stage": "completed",
                "error": "",
                "provider_snapshot": result.provider_snapshot,
                "search_queries": list(result.search_queries),
                "source_references": [item.to_dict() for item in result.source_references],
            }
            job.updated_at = utc_now_naive()
            state["query_ids"] = list(job.payload.get("query_ids") or [])

        await owned(complete)
    except Exception as exc:
        error_text = str(exc)[:2000]

        async def fail(_session, job):
            if job.status != "completed":
                job.status = "failed"
                job.payload = {**(job.payload or {}), "stage": "failed", "error": error_text}
                job.updated_at = utc_now_naive()

        await owned(fail)
        raise
    return {"status": "completed", "generation_id": generation_id, "query_ids": state["query_ids"]}


async def fail_equipment_query_generation(session, record, error: str) -> None:
    """由 Task 事务投影失败终态，保留已保存结果。"""
    generation_id = str((record.payload or {}).get("generation_id") or "")
    if not generation_id:
        return
    job = await EquipmentResearchRepository(session).lock_generation(generation_id)
    if job is None or job.status in {"completed", "cancelled"}:
        return
    job.status = "cancelled" if error == "任务已取消" else "failed"
    job.payload = {**(job.payload or {}), "stage": job.status, "error": error}
    job.updated_at = utc_now_naive()
