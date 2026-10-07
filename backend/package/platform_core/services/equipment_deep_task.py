"""深研对话 Durable Task：使用模型设置中的聊天模型完成一轮回复。"""

from __future__ import annotations

from uuid import uuid4
from typing import Any

from equipment_deep_research.providers.base import ModelMessage
from platform_core.config import get_int_env
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_equipment import EquipmentDeepMessage
from platform_core.utils.datetime_utils import utc_now_naive
from platform_core.utils.logging_config import logger

EQUIPMENT_DEEP_TASK_TYPE = "equipment_deep_turn"
EQUIPMENT_DEEP_MAX_RUNNING = get_int_env("EQUIPMENT_DEEP_MAX_RUNNING", 8)

_SYSTEM_PROMPT = (
    "你是装备智能研究平台的深研对话助手。围绕装备需求、作战场景、技术路径、"
    "制胜机理与能力画像进行创造性研讨。不要输出可操作的武器制造或攻击指导。"
    "回答应结构化、可审计，必要时明确未知项。"
)


async def run_equipment_deep_turn(context) -> dict[str, Any]:
    payload = dict(context.payload or {})
    session_id = str(payload.get("session_id") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    if not session_id or not job_id:
        raise ValueError("equipment_deep_turn payload 缺少 session_id 或 job_id")
    async with pg_manager.get_async_session_context() as session:
        repo = EquipmentResearchRepository(session)
        deep_session = await repo.get_deep_session(session_id)
        job = await repo.get_deep_job(job_id)
        if deep_session is None or job is None:
            raise RuntimeError("深研对话会话或作业不存在")
        job.status = "running"
        job.updated_at = utc_now_naive()
        session_payload = dict(deep_session.payload or {})
        model_spec = str(dict(job.payload or {}).get("model_spec") or session_payload.get("model_spec") or "")
        topic = str(session_payload.get("topic") or "")
        messages = await repo.list_deep_messages(session_id)
        history = [(item.role, item.content) for item in messages]

    from platform_core.services.equipment_model_adapter import complete_equipment_chat, resolve_managed_equipment_model

    try:
        runtime = resolve_managed_equipment_model(model_spec)
        prompt_messages = [
            ModelMessage(role="system", content=_SYSTEM_PROMPT),
        ]
        if topic:
            prompt_messages.append(
                ModelMessage(role="system", content=f"当前研讨主题：{topic}")
            )
        for role, content in history:
            if role in {"user", "assistant"} and content.strip():
                prompt_messages.append(ModelMessage(role=role, content=content))
        text, metadata = await complete_equipment_chat(
            runtime,
            prompt_messages,
            {"max_output_tokens": 2400, "reasoning_effort": "medium"},
            isolation_key=f"deep-{job_id}",
        )
        if not text.strip():
            raise RuntimeError("模型未返回可见回复")
    except Exception as exc:
        logger.exception("equipment_deep_turn failed: %s", job_id)
        async with pg_manager.get_async_session_context() as session:
            repo = EquipmentResearchRepository(session)
            job = await repo.get_deep_job(job_id)
            if job is not None:
                job.status = "failed"
                job.payload = {**(job.payload or {}), "error": str(exc)}
                job.updated_at = utc_now_naive()
        raise

    async with pg_manager.get_async_session_context() as session:
        repo = EquipmentResearchRepository(session)
        deep_session = await repo.get_deep_session(session_id)
        job = await repo.get_deep_job(job_id)
        if deep_session is None or job is None:
            return {"status": "missing", "job_id": job_id}
        assistant = EquipmentDeepMessage(
            id=f"dmsg-{uuid4()}",
            session_id=session_id,
            role="assistant",
            content=text.strip(),
            payload={"model_spec": runtime["model_spec"], "usage": metadata.get("usage") or {}},
        )
        await repo.add_deep_message(assistant)
        job.status = "completed"
        job.payload = {**(job.payload or {}), "assistant_message_id": assistant.id, "error": ""}
        job.updated_at = utc_now_naive()
        deep_session.updated_at = utc_now_naive()
        session_payload = dict(deep_session.payload or {})
        session_payload["model_spec"] = runtime["model_spec"]
        deep_session.payload = session_payload
    return {"status": "completed", "job_id": job_id, "session_id": session_id}


async def fail_equipment_deep_turn(session, record, error: str) -> None:
    job_id = str((record.payload or {}).get("job_id") or "")
    if not job_id:
        return
    repo = EquipmentResearchRepository(session)
    job = await repo.get_deep_job(job_id)
    if job is None or job.status in {"completed", "cancelled"}:
        return
    job.status = "failed"
    job.payload = {**(job.payload or {}), "error": error}
    job.updated_at = utc_now_naive()
