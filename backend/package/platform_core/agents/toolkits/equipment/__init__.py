"""装备研究启动工具。"""

from __future__ import annotations

from typing import Any

from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field
from sqlalchemy import select

from platform_core.agents.toolkits.registry import tool
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User


class StartEquipmentResearchInput(BaseModel):
    project_id: str = Field(description="当前用户可访问的 Project ID")
    topic: str = Field(description="澄清后的装备研究主题")
    research_route: str = Field(
        default="auto",
        description="研究路线：auto / new_winning_mechanism / traditional_gap / war_case_learning",
    )
    model_spec: str = Field(
        default="",
        description="平台聊天模型 spec，格式 provider_id:model_id；空则使用系统默认模型",
    )
    start: bool = Field(default=True, description="创建后是否立即排队执行")


class EquipmentDeepContextInput(BaseModel):
    include_artifacts: bool = Field(default=True, description="是否返回关联研究产物索引")


class SaveEquipmentCapabilityDraftInput(BaseModel):
    name: str = Field(description="能力画像名称")
    capability_image: str = Field(
        description=(
            "正式 S6 五栏能力画像正文。必须按概述、装备与技术实现、关键作战流程、"
            "形成能力与作战效果、制胜逻辑机理的顺序和精确栏名书写；每栏以 360–400 个"
            "有效中文字为常规目标，禁止缺栏、重复栏、栏名后缀或额外栏目"
        )
    )
    rationale: str = Field(default="", description="从证据到能力判断的形成依据")
    evidence_refs: list[str] = Field(default_factory=list, description="知识库、文档、URL 或研究产物引用")
    structured_fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "结构化字段；成卡时必须同时提供 capability_portrait_modules 与 capability_card_draft，"
            "两者使用 overview、technology_implementation、operational_process、"
            "capability_effects、winning_logic 五个键"
        ),
    )


@tool(category="equipment", tags=["装备研究"], display_name="启动装备研究任务", args_schema=StartEquipmentResearchInput)
async def start_equipment_research(
    project_id: str,
    topic: str,
    research_route: str = "auto",
    model_spec: str = "",
    start: bool = True,
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """把澄清后的装备研究问题转为正式研究任务，并返回任务与成果入口。"""
    from platform_core.services import equipment_research_service as svc

    context = getattr(runtime, "context", None)
    uid = str(getattr(context, "uid", "") or "")
    if not uid:
        return {"ok": False, "error": "缺少当前用户身份"}
    async with pg_manager.get_async_session_context() as session:
        user = await session.scalar(select(User).where(User.uid == uid, User.is_deleted == 0))
        if user is None:
            return {"ok": False, "error": "当前用户不存在"}
        created = await svc.create_run(
            db=session,
            user=user,
            project_id=project_id,
            topic=topic,
            research_route=research_route,
            model_spec=model_spec or None,
        )
        if start:
            created = await svc.start_run(db=session, user=user, run_id=created["run_id"])
    return {
        "ok": True,
        "run": created,
        "task_url": f"/equipment/runs/{created['run_id']}",
        "portal_url": "/knowledge",
    }


@tool(
    category="equipment",
    tags=["装备研究", "深研对话"],
    display_name="读取装备深研上下文",
    args_schema=EquipmentDeepContextInput,
)
async def equipment_deep_context(
    include_artifacts: bool = True,
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """读取当前平台原生深研会话关联的研究任务、能力版本、产物与分支上下文。"""
    identity = _equipment_deep_identity(runtime)
    if identity.get("error"):
        return {"ok": False, **identity}

    from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
    from platform_core.services.equipment_deep_integration_service import get_session_research_context

    async with pg_manager.get_async_session_context() as session:
        user = await session.scalar(select(User).where(User.uid == identity["uid"], User.is_deleted == 0))
        deep_session = await EquipmentResearchRepository(session).get_deep_session(identity["session_id"])
        if user is None or deep_session is None:
            return {"ok": False, "error": "深研会话不存在"}
        context = await get_session_research_context(db=session, user=user, session=deep_session)
    if not include_artifacts:
        context["artifacts"] = []
    return {"ok": True, "context": context}


@tool(
    category="equipment",
    tags=["装备研究", "能力画像"],
    display_name="保存能力画像草案",
    args_schema=SaveEquipmentCapabilityDraftInput,
)
async def save_equipment_capability_draft(
    name: str,
    capability_image: str,
    rationale: str = "",
    evidence_refs: list[str] | None = None,
    structured_fields: dict[str, Any] | None = None,
    runtime: ToolRuntime = None,
) -> dict[str, Any]:
    """校验正式 S6 五栏合同后新增待核验能力画像版本，不改写原始正式版本。"""
    identity = _equipment_deep_identity(runtime)
    if identity.get("error"):
        return {"ok": False, **identity}

    from fastapi import HTTPException
    from platform_core.services.equipment_deep_integration_service import save_capability_draft

    async with pg_manager.get_async_session_context() as session:
        user = await session.scalar(select(User).where(User.uid == identity["uid"], User.is_deleted == 0))
        if user is None:
            return {"ok": False, "error": "当前用户不存在"}
        try:
            version = await save_capability_draft(
                db=session,
                user=user,
                session_id=identity["session_id"],
                name=name,
                capability_image=capability_image,
                rationale=rationale,
                evidence_refs=evidence_refs or [],
                structured_fields=structured_fields or {},
            )
        except HTTPException as exc:
            return {"ok": False, "error": str(exc.detail)}
    return {
        "ok": True,
        "version": version,
        "status": "pending_verification",
        "capabilities_url": "/equipment/capabilities",
    }


def _equipment_deep_identity(runtime: ToolRuntime | None) -> dict[str, str]:
    context = getattr(runtime, "context", None)
    uid = str(getattr(context, "uid", "") or "").strip()
    source = str(getattr(context, "run_source", "") or "").strip()
    session_id = str(getattr(context, "run_external_id", "") or "").strip()
    if not uid:
        return {"error": "当前运行时缺少用户身份"}
    if source != "equipment_deep_research" or not session_id:
        return {"error": "该工具只能在 equipment deep research 深研会话中使用"}
    return {"uid": uid, "session_id": session_id}
