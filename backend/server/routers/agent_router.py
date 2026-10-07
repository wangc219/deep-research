from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from platform_core.agents.buildin import AgentBackendNotFoundError, get_agent_backend, list_agent_backend_info
from platform_core.agents.context import filter_declared_config
from platform_core.repositories.agent_repository import (
    AgentRepository,
    is_builtin_agent,
    user_can_access_agent,
    user_can_manage_agent,
)
from platform_core.repositories.agent_run_repository import AgentRunRepository
from platform_core.repositories.agent_run_request_repository import AgentRunRequestRepository
from platform_core.repositories.conversation_repository import ConversationRepository
from platform_core.permissions import has_global_business_access
from platform_core.services.agent_request_queue_service import (
    cancel_queued_request as cancel_queued_request_svc,
    continue_thread_queue,
    finalize_dispatch,
    get_request as get_request_svc,
    get_thread_queue_snapshot,
    steer_queued_request,
    stream_request_events,
)
from platform_core.services.agent_config_service import prepare_agent_config_write
from platform_core.services.agent_run_service import (
    cancel_agent_run_view,
    create_resume_run_view,
    get_active_run_by_thread,
    get_agent_run_langfuse_link,
    get_agent_run_result,
    get_agent_run_view,
    stream_agent_run_events,
)
from platform_core.services.input_message_service import build_chat_input_message
from platform_core.services.agent_request_service import RunOrigin, AgentRequestInput, submit_agent_request
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User

from server.utils.auth_middleware import get_admin_user, get_db, get_required_user, get_superadmin_user

agent_router = APIRouter(prefix="/agent", tags=["agent"])


async def _thread_owner_uid(*, thread_id: str, actor: User, db: AsyncSession) -> str:
    """解析当前操作人可见线程的真实所有者。"""

    conversation = await ConversationRepository(db).get_conversation_by_thread_id(thread_id)
    if (
        conversation is None
        or conversation.status == "deleted"
        or (conversation.uid != str(actor.uid) and not has_global_business_access(actor))
    ):
        raise HTTPException(status_code=404, detail="对话线程不存在")
    return str(conversation.uid)


async def _request_owner_uid(*, request_id: str, actor: User, db: AsyncSession) -> str:
    """解析当前操作人可见请求的真实所有者。"""

    request = await AgentRunRequestRepository(db).get_by_request_id(request_id)
    if request is None or (request.uid != str(actor.uid) and not has_global_business_access(actor)):
        raise HTTPException(status_code=404, detail="请求不存在")
    return str(request.uid)


async def _run_owner_uid(*, run_id: str, actor: User, db: AsyncSession) -> str:
    """解析当前操作人可见 Run 的真实所有者。"""

    run = await AgentRunRepository(db).get_run(run_id)
    if run is None or (run.uid != str(actor.uid) and not has_global_business_access(actor)):
        raise HTTPException(status_code=404, detail="运行任务不存在")
    return str(run.uid)


class AgentCreate(BaseModel):
    name: str
    backend_id: str = "ChatbotAgent"
    slug: str | None = None
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    config_json: dict | None = None
    share_config: dict | None = None
    is_subagent: bool | None = None
    set_default: bool = False


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    config_json: dict | None = None
    share_config: dict | None = None
    is_subagent: bool | None = None


class AgentRunCreate(BaseModel):
    query: str | None = Field(None, description="用户输入的问题")
    agent_slug: str = Field(..., description="智能体 slug")
    thread_id: str = Field(..., description="会话线程 ID")
    meta: dict = Field(default_factory=dict, description="可选，请求追踪信息，例如 request_id")
    image_content: str | None = Field(None, description="可选，base64 图片内容")
    model_spec: str | None = Field(None, description="可选，对话级模型覆盖，优先级高于智能体配置")
    tool_approval_mode: str | None = Field(None, description="可选，本次运行的工具审批模式覆盖")
    knowledge_ids: list[str] | None = Field(
        default=None,
        max_length=64,
        description="可选，本次运行由 @知识库 mention 绑定的知识库 ID；不提供时沿用智能体配置",
    )
    resume: Any | None = Field(None, description="可选，恢复时传给 LangGraph 的输入载荷，非布尔值")
    created_by_run_id: str | None = Field(None, description="可选，创建本 run 的父 run ID；resume 时为被恢复的 run ID")
    queue_policy: str = Field(
        "enqueue",
        description="排队策略：enqueue（默认排队）、reject（运行中拒绝）或 steer（优先接替）",
    )


def _filter_agent_config_json(backend_id: str, config_json: dict | None) -> dict:
    backend = get_agent_backend(backend_id)
    context_schema = backend.context_schema
    return filter_declared_config(config_json or {}, context_schema=context_schema)


async def _serialize_agent(
    repo: AgentRepository,
    item,
    user: User,
    *,
    include_configurable_items: bool = False,
    backend_info_cache: dict[tuple[str, bool, str], dict] | None = None,
) -> dict:
    try:
        data = await repo.serialize(
            item,
            user=user,
            include_configurable_items=include_configurable_items,
            backend_info_cache=backend_info_cache,
        )
        data["config_json"] = _filter_agent_config_json(item.backend_id, data.get("config_json"))
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return data


@agent_router.get("/backends")
async def list_agent_backends(current_user: User = Depends(get_required_user)):
    infos = await list_agent_backend_info()
    return {"backends": [{**info, "type": "agent_backend"} for info in infos]}


@agent_router.get("/backends/{backend_id}")
async def get_agent_backend_detail(
    backend_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        backend = get_agent_backend(backend_id)
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    info = await backend.get_info(user_role=current_user.role, db=db, user=current_user)
    return {**info, "backend_id": backend_id, "type": "agent_backend"}


@agent_router.get("")
async def list_agents(
    include_subagents: bool = Query(False),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentRepository(db)
    await repo.ensure_default_agent()
    items = await repo.list_visible(user=current_user, include_subagent_definitions=include_subagents)
    backend_info_cache: dict[tuple[str, bool, str], dict] = {}
    agents = [await _serialize_agent(repo, item, current_user, backend_info_cache=backend_info_cache) for item in items]
    return {"agents": agents}


@agent_router.get("/default")
async def get_default_agent(current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    repo = AgentRepository(db)
    item = await repo.ensure_default_agent()
    if not item or not user_can_access_agent(current_user, item):
        raise HTTPException(status_code=404, detail="默认智能体不可访问")
    return {"agent": await _serialize_agent(repo, item, current_user, include_configurable_items=True)}


@agent_router.post("")
async def create_agent(
    payload: AgentCreate, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    try:
        backend = get_agent_backend(payload.backend_id)
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if payload.set_default:
        raise HTTPException(status_code=422, detail="默认智能体已固定为内置智能助手")

    repo = AgentRepository(db)
    try:
        config_json, config_resource_access = await prepare_agent_config_write(
            payload.config_json or {},
            context_schema=backend.context_schema,
            db=db,
            user=current_user,
        )
        item = await repo.create(
            name=payload.name,
            slug=payload.slug,
            backend_id=payload.backend_id,
            description=payload.description,
            icon=payload.icon,
            pics=payload.pics,
            config_json=config_json,
            config_resource_access=config_resource_access,
            share_config=payload.share_config,
            is_default=payload.set_default,
            is_subagent=payload.is_subagent,
            created_by=str(current_user.uid),
            creator=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"agent": await _serialize_agent(repo, item, current_user, include_configurable_items=True)}


@agent_router.get("/{agent_id}")
async def get_agent(agent_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)):
    repo = AgentRepository(db)
    agent_slug = agent_id  # 兼容既有路径参数名；这里实际是 Agent.slug。
    item = await repo.get_visible_by_slug(slug=agent_slug, user=current_user, kind="any")
    if not item:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return {"agent": await _serialize_agent(repo, item, current_user, include_configurable_items=True)}


@agent_router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentRepository(db)
    agent_slug = agent_id  # 兼容既有路径参数名；这里实际是 Agent.slug。
    item = await repo.get_visible_by_slug(slug=agent_slug, user=current_user, kind="any")
    if not item:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if not user_can_manage_agent(current_user, item):
        raise HTTPException(status_code=403, detail="不能编辑非自己创建的智能体")

    try:
        backend = get_agent_backend(item.backend_id)
        fields_set = payload.model_fields_set
        if "description" in fields_set and payload.description is None:
            item.description = None
        if "icon" in fields_set and payload.icon is None:
            item.icon = None

        config_json = None
        config_resource_access = None
        if payload.config_json is not None:
            config_json, config_resource_access = await prepare_agent_config_write(
                payload.config_json,
                context_schema=backend.context_schema,
                db=db,
                user=current_user,
            )

        updated = await repo.update(
            item,
            name=payload.name,
            description=payload.description,
            icon=payload.icon,
            pics=payload.pics,
            config_json=config_json,
            config_resource_access=config_resource_access,
            share_config=payload.share_config,
            is_subagent=payload.is_subagent,
            updated_by=str(current_user.uid),
            updater=current_user,
        )
    except AgentBackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"agent": await _serialize_agent(repo, updated, current_user, include_configurable_items=True)}


@agent_router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    repo = AgentRepository(db)
    agent_slug = agent_id  # 兼容既有路径参数名；这里实际是 Agent.slug。
    item = await repo.get_visible_by_slug(slug=agent_slug, user=current_user, kind="any")
    if not item:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if not user_can_manage_agent(current_user, item):
        raise HTTPException(status_code=403, detail="不能删除非自己创建的智能体")
    if is_builtin_agent(item):
        raise HTTPException(status_code=409, detail="内置智能体不能删除")
    await repo.delete(agent=item)
    return {"success": True}


@agent_router.post("/{agent_id}/set_default")
async def set_agent_default(
    agent_id: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentRepository(db)
    agent_slug = agent_id  # 兼容既有路径参数名；这里实际是 Agent.slug。
    item = await repo.get_by_slug(agent_slug)
    if not item:
        raise HTTPException(status_code=404, detail="智能体不存在")
    try:
        updated = await repo.set_default(agent=item, updated_by=str(current_user.uid))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"agent": await _serialize_agent(repo, updated, current_user, include_configurable_items=True)}


@agent_router.post("/runs")
async def create_agent_run(
    payload: AgentRunCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    # resume 路径：恢复已有 LangGraph 状态，跳过 request 入队与派发，直接新建 run。
    if payload.resume is not None:
        if payload.queue_policy != "enqueue":
            raise HTTPException(status_code=422, detail="queue_policy 仅支持普通 Chat 请求")
        owner_uid = await _thread_owner_uid(thread_id=payload.thread_id, actor=current_user, db=db)
        return await create_resume_run_view(
            agent_slug=payload.agent_slug,
            thread_id=payload.thread_id,
            meta=dict(payload.meta or {}),
            current_uid=owner_uid,
            db=db,
            resume=payload.resume,
            created_by_run_id=payload.created_by_run_id,
        )

    # 普通 chat 路径：写入 request + message，立即派发或入队等待。
    meta = dict(payload.meta or {})
    request_id = meta.get("request_id") or str(uuid.uuid4())
    meta["request_id"] = request_id

    input_message = build_chat_input_message(payload.query or "", payload.image_content)
    runtime_context_overrides: dict[str, Any] = {}
    if payload.knowledge_ids is not None:
        runtime_context_overrides = {
            "context": {
                "knowledges": list(
                    dict.fromkeys(
                        knowledge_id.strip()
                        for knowledge_id in payload.knowledge_ids
                        if knowledge_id.strip()
                    )
                )
            }
        }

    return await submit_agent_request(
        request_input=AgentRequestInput(
            agent_slug=payload.agent_slug,
            thread_id=payload.thread_id,
            request_id=request_id,
            input_message=input_message,
            origin=RunOrigin(source="chat", channel="web"),
            request_metadata={**meta, "tool_approval_mode": payload.tool_approval_mode},
            runtime_context_overrides=runtime_context_overrides,
            model_spec=payload.model_spec,
            tool_approval_mode=payload.tool_approval_mode,
            queue_policy=payload.queue_policy,
        ),
        current_user=current_user,
        db=db,
    )


@agent_router.get("/requests/{request_id}")
async def get_request(
    request_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    owner_uid = await _request_owner_uid(request_id=request_id, actor=current_user, db=db)
    result = await get_request_svc(db=db, request_id=request_id, uid=owner_uid)
    if not result:
        raise HTTPException(status_code=404, detail="请求不存在")
    return {"request": result}


@agent_router.get("/thread/{thread_id}/requests")
async def list_thread_requests(
    thread_id: str,
    current_user: User = Depends(get_required_user),
    agent_slug: str = Query(..., description="智能体 slug"),
    db: AsyncSession = Depends(get_db),
):
    owner_uid = await _thread_owner_uid(thread_id=thread_id, actor=current_user, db=db)
    return await get_thread_queue_snapshot(
        db=db,
        uid=owner_uid,
        agent_slug=agent_slug,
        thread_id=thread_id,
    )


@agent_router.post("/thread/{thread_id}/requests/continue")
async def continue_thread_requests(
    thread_id: str,
    current_user: User = Depends(get_required_user),
    agent_slug: str = Query(..., description="智能体 slug"),
    db: AsyncSession = Depends(get_db),
):
    owner_uid = await _thread_owner_uid(thread_id=thread_id, actor=current_user, db=db)
    dispatch = await continue_thread_queue(
        db=db,
        uid=owner_uid,
        agent_slug=agent_slug,
        thread_id=thread_id,
    )
    await finalize_dispatch(db=db, dispatch=dispatch)
    return {"status": "dispatched", "request_id": dispatch.request_id, "run_id": dispatch.run_id}


@agent_router.post("/requests/{request_id}/cancel")
async def cancel_request(
    request_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    owner_uid = await _request_owner_uid(request_id=request_id, actor=current_user, db=db)
    status = await cancel_queued_request_svc(request_id=request_id, current_uid=owner_uid, db=db)
    await db.commit()
    return {"request_id": request_id, "status": status}


@agent_router.post("/requests/{request_id}/steer")
async def steer_request(
    request_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    owner_uid = await _request_owner_uid(request_id=request_id, actor=current_user, db=db)
    result = await steer_queued_request(request_id=request_id, current_uid=owner_uid, db=db)
    await db.commit()
    return result


@agent_router.get("/requests/{request_id}/events")
async def stream_request_events_route(
    request_id: str,
    current_user: User = Depends(get_required_user),
):
    async with pg_manager.get_async_session_context() as auth_db:
        owner_uid = await _request_owner_uid(request_id=request_id, actor=current_user, db=auth_db)
    return StreamingResponse(
        stream_request_events(
            request_id=request_id,
            uid=owner_uid,
            db_session_factory=pg_manager.get_async_session_context,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@agent_router.get("/runs/{run_id}")
async def get_agent_run(
    run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    owner_uid = await _run_owner_uid(run_id=run_id, actor=current_user, db=db)
    return await get_agent_run_view(run_id=run_id, current_uid=owner_uid, db=db)


@agent_router.get("/runs/{run_id}/result")
async def get_agent_run_result_route(
    run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    owner_uid = await _run_owner_uid(run_id=run_id, actor=current_user, db=db)
    return await get_agent_run_result(run_id=run_id, current_uid=owner_uid, db=db)


@agent_router.get("/runs/{run_id}/langfuse")
async def get_agent_run_langfuse_link_route(
    run_id: str, current_user: User = Depends(get_superadmin_user), db: AsyncSession = Depends(get_db)
):
    owner_uid = await _run_owner_uid(run_id=run_id, actor=current_user, db=db)
    return await get_agent_run_langfuse_link(run_id=run_id, current_uid=owner_uid, db=db)


@agent_router.post("/runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    owner_uid = await _run_owner_uid(run_id=run_id, actor=current_user, db=db)
    return await cancel_agent_run_view(run_id=run_id, current_uid=owner_uid, db=db)


@agent_router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_seq: str = "0-0",
    verbose: bool = Query(default=True, description="是否返回完整事件载荷；false 时仅返回 UI/客户端消费所需字段"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    current_user: User = Depends(get_required_user),
):
    cursor = last_event_id or after_seq
    async with pg_manager.get_async_session_context() as auth_db:
        owner_uid = await _run_owner_uid(run_id=run_id, actor=current_user, db=auth_db)
    return StreamingResponse(
        stream_agent_run_events(run_id=run_id, after_seq=cursor, current_uid=owner_uid, verbose=verbose),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@agent_router.get("/thread/{thread_id}/active_run")
async def get_thread_active_run(
    thread_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    owner_uid = await _thread_owner_uid(thread_id=thread_id, actor=current_user, db=db)
    return await get_active_run_by_thread(thread_id=thread_id, current_uid=owner_uid, db=db)
