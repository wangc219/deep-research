"""需求 Query 生成 Durable Task：使用模型设置中的聊天模型。"""

from __future__ import annotations

from uuid import uuid4
from typing import Any

from platform_core.config import get_int_env
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_equipment import EquipmentQuery, EquipmentQueryRevision
from platform_core.utils.datetime_utils import utc_now_naive
from platform_core.utils.logging_config import logger

EQUIPMENT_QUERY_TASK_TYPE = "equipment_query_generation"
EQUIPMENT_QUERY_MAX_RUNNING = get_int_env("EQUIPMENT_QUERY_MAX_RUNNING", 4)


async def run_equipment_query_generation(context) -> dict[str, Any]:
    payload = dict(context.payload or {})
    generation_id = str(payload.get("generation_id") or "").strip()
    if not generation_id:
        raise ValueError("equipment_query_generation payload 缺少 generation_id")
    async with pg_manager.get_async_session_context() as session:
        repo = EquipmentResearchRepository(session)
        job = await repo.get_generation(generation_id)
        if job is None:
            raise RuntimeError(f"Query 生成任务不存在: {generation_id}")
        if job.status == "cancelled":
            return {"status": "cancelled", "generation_id": generation_id, "query_ids": []}
        job.status = "running"
        job.updated_at = utc_now_naive()
        job_payload = dict(job.payload or {})
        model_spec = str(job_payload.get("model_spec") or "")
        topic = job.topic
        supplemental = str(job_payload.get("supplemental_information") or "")
        reference_urls = tuple(str(item) for item in job_payload.get("reference_urls") or [])
        count = int(job_payload.get("count") or 6)
        owner_uid = job.owner_uid
        project_id = job.project_id
        existing = [
            item.query_text for item in await repo.list_queries(owner_uid, project_id=project_id, limit=200)
        ]
    await context.raise_if_cancelled()
    from platform_core.services.equipment_model_adapter import (
        create_equipment_provider,
        resolve_managed_equipment_model,
    )
    from equipment_deep_research.query_library.generator import ModelQueryGenerator

    try:
        runtime = resolve_managed_equipment_model(model_spec)
        provider = create_equipment_provider(runtime, isolation_key=f"query-gen-{generation_id}")
        generator = ModelQueryGenerator(
            provider,
            provider_snapshot={
                "provider": runtime["provider"],
                "model": runtime["model"],
                "model_spec": runtime["model_spec"],
            },
            model_options={"reasoning_effort": "high"},
        )
        result = await generator.generate(
            topic=topic,
            supplemental_information=supplemental,
            reference_urls=reference_urls,
            count=max(1, min(count, 20)),
            existing_queries=existing,
        )
        await context.raise_if_cancelled()
    except Exception as exc:
        logger.exception("equipment_query_generation failed: %s", generation_id)
        async with pg_manager.get_async_session_context() as session:
            repo = EquipmentResearchRepository(session)
            job = await repo.get_generation(generation_id)
            if job is not None:
                job.status = "failed"
                job.payload = {**(job.payload or {}), "error": str(exc)}
                job.updated_at = utc_now_naive()
        raise

    query_ids: list[str] = []
    import hashlib

    def _new_id(prefix: str) -> str:
        return f"{prefix}-{uuid4()}"

    async with pg_manager.get_async_session_context() as session:
        repo = EquipmentResearchRepository(session)
        job = await repo.get_generation(generation_id)
        if job is None:
            return {"status": "missing", "generation_id": generation_id}
        for candidate in result.candidates:
            text = str(getattr(candidate, "query", "") or "").strip()
            if not text:
                continue
            fingerprint = hashlib.sha256(f"{job.owner_uid}:{text}".encode()).hexdigest()
            if await repo.get_query_by_fingerprint(fingerprint) is not None:
                continue
            query = EquipmentQuery(
                id=_new_id("query"),
                project_id=project_id,
                owner_uid=owner_uid,
                query_text=text,
                query_fingerprint=fingerprint,
                supplemental_information=str(getattr(candidate, "supplemental_information", "") or ""),
                status="draft",
                source_type="agent",
                payload={
                    "generation_id": generation_id,
                    "model_spec": runtime["model_spec"],
                    "coverage_slot": str(getattr(candidate, "coverage_slot", "") or ""),
                    "generation_rationale": str(getattr(candidate, "generation_rationale", "") or ""),
                    "demand_chain": dict(getattr(candidate, "demand_chain", {}) or {}),
                    "quality_review": dict(getattr(candidate, "quality_review", {}) or {}),
                    "source_references": [
                        item.to_dict() for item in getattr(candidate, "source_references", ())
                    ],
                    # This is only the default scope for a later research
                    # launch. Query generation itself does not retrieve from
                    # or constrain itself to these knowledge bases.
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
            query_ids.append(query.id)
        job.status = "completed"
        job.payload = {
            **(job.payload or {}),
            "query_ids": query_ids,
            "model_spec": runtime["model_spec"],
            "stage": "completed",
            "provider_snapshot": dict(getattr(result, "provider_snapshot", {}) or {}),
            "search_queries": list(getattr(result, "search_queries", ()) or ()),
            "source_references": [
                item.to_dict() for item in getattr(result, "source_references", ())
            ],
            "error": "",
        }
        job.updated_at = utc_now_naive()
    return {"status": "completed", "generation_id": generation_id, "query_ids": query_ids}


async def fail_equipment_query_generation(session, record, error: str) -> None:
    generation_id = str((record.payload or {}).get("generation_id") or "")
    if not generation_id:
        return
    repo = EquipmentResearchRepository(session)
    job = await repo.get_generation(generation_id)
    if job is None or job.status in {"completed", "cancelled"}:
        return
    job.status = "cancelled" if error == "任务已取消" else "failed"
    job.payload = {
        **(job.payload or {}),
        "stage": "cancelled" if error == "任务已取消" else "failed",
        "error": error,
    }
    job.updated_at = utc_now_naive()
