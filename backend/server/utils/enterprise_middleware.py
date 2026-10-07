"""为两个研究接口统一验证平台身份、功能授权与调用计量。"""

import hashlib
import json
import logging
import time

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import text

from equipment_deep_research.domain.platform_identity import PlatformIdentity, platform_identity
from platform_core.permissions import has_global_business_access
from platform_core.services.enterprise_service import feature_access
from platform_core.services.operation_log_service import log_operation
from platform_core.storage.postgres.manager import pg_manager
from server.utils.auth_middleware import get_current_user, get_required_user

logger = logging.getLogger(__name__)


def request_feature(path: str) -> str | None:
    """将实际 API 路径映射到企业功能开关。"""
    if path.startswith("/api/knowledge/"):
        return "knowledge"
    if path == "/api/agent" or path.startswith(
        ("/api/agent/", "/api/agent-invocation/", "/api/chat/", "/api/scheduled-tasks")
    ):
        return "agents"
    if not path.startswith(("/api/v1/", "/api/equipment/")):
        return None
    if "query" in path or "/queries" in path:
        return "queries"
    if "/favorites" in path:
        return "favorites"
    if "/deep-" in path:
        return "deep-thinking"
    if "/capabilit" in path:
        return "capabilities"
    if any(part in path for part in ("/report", "/deliverables", "/artifacts", "/manifest")):
        return "reports"
    return "research"


class EnterpriseMiddleware:
    """不缓存用户权限；每次请求读取平台权威用户与授权记录。"""

    def __init__(self, app, run_loader=None):
        self.app = app
        self.run_loader = run_loader

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        feature = request_feature(path)
        if feature is None:
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        started = time.monotonic()
        try:
            async with pg_manager.get_async_session_context() as db:
                user = await get_current_user(request.headers.get("authorization"), db)
                user = await get_required_user(user)
                access = await feature_access(db, user, feature)
                write = scope["method"] not in {"GET", "HEAD"}
                if feature == "knowledge" and path.endswith(("/query", "/query-test")):
                    write = False
                identity = PlatformIdentity(user.uid, user.tenant_id, has_global_business_access(user))
                if identity.superadmin and write:
                    await log_operation(
                        db,
                        user.id,
                        "全局管理员调用企业功能写接口（尝试）",
                        json.dumps(
                            {
                                "audit_stage": "attempt",
                                "actor_uid": str(user.uid),
                                "actor_role": str(user.role),
                                "feature": feature,
                                "method": scope["method"],
                                "path": path,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    )
                    await db.commit()
        except HTTPException as exc:
            return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(
                scope, receive, send
            )

        token = platform_identity.set(identity)
        status_code = 500
        try:
            if not access["can_write" if write else "can_read"]:
                raise HTTPException(403, "当前用户没有此功能的写入权限" if write else "当前用户没有此功能的读取权限")
            if path.startswith("/api/v1/"):
                await self.prepare_legacy(request, scope, identity)
                receive = request.receive

            async def measured_send(message):
                """记录响应状态，同时保持 SSE 与文件响应流式发送。"""
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                await send(message)

            await self.app(scope, receive, measured_send)
        except HTTPException as exc:
            status_code = exc.status_code
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
        finally:
            platform_identity.reset(token)
            try:
                async with pg_manager.get_async_session_context() as db:
                    await db.execute(
                        text("""INSERT INTO platform_request_metrics
                        (tenant_id,uid,feature,method,status_code,duration_ms)
                        VALUES (:tenant,:uid,:feature,:method,:status,:duration)"""),
                        {
                            "tenant": identity.tenant_id,
                            "uid": identity.uid,
                            "feature": feature,
                            "method": scope["method"],
                            "status": status_code,
                            "duration": (time.monotonic() - started) * 1000,
                        },
                    )
                    await db.commit()
            except Exception:
                logger.exception("企业调用指标写入失败")

    async def prepare_legacy(self, request, scope, identity):
        """移除浏览器身份声明，验证路径和请求体中的跨资源引用。"""
        path = scope["path"]
        allowed = (
            "/api/v1/runs",
            "/api/v1/query-library/",
            "/api/v1/favorites",
            "/api/v1/deep-thinking/",
            "/api/v1/deep-sessions/",
            "/api/v1/catalog",
            "/api/v1/model-profiles",
            "/api/v1/agent-selection-preview",
            "/api/v1/health",
        )
        if not identity.superadmin and not path.startswith(allowed):
            raise HTTPException(403, "此全局管理接口需要超级管理员权限")
        if (
            not identity.superadmin
            and scope["method"] not in {"GET", "HEAD"}
            and (path.startswith("/api/v1/model-profiles") or path.startswith("/api/v1/deep-thinking/plugins"))
        ):
            raise HTTPException(403, "此操作需要超级管理员权限")

        headers = []
        protected = {
            b"x-role",
            b"x-user-id",
            b"x-tenant-id",
            b"x-workspace-id",
            b"x-project-id",
            b"x-profile-id",
            b"x-evolution-cross-scope",
            b"x-tenant-cross-scope",
            b"x-evolution-stage-scope",
            b"x-research-route",
        }
        for key, value in scope.get("headers", []):
            lower = key.lower()
            if lower in protected or lower.startswith((b"x-auth", b"x-principal")):
                continue
            if lower == b"idempotency-key":
                value = hashlib.sha256(identity.uid.encode() + b":" + value).hexdigest().encode()
            headers.append((key, value))
        headers += [(b"x-role", b"admin" if identity.superadmin else b"analyst"), (b"x-user-id", identity.uid.encode())]
        if not identity.superadmin:
            headers += [(b"x-tenant-id", identity.tenant_id.encode()), (b"x-workspace-id", identity.uid.encode())]
        else:
            headers.append((b"x-evolution-cross-scope", b"true"))
        scope["headers"] = headers
        run_ids = set()
        parts = path.split("/")
        if len(parts) > 4 and parts[3] == "runs" and parts[4] != "permanent-delete":
            run_ids.add(parts[4])
        current_run = request.query_params.get("current_run_id")
        if current_run:
            run_ids.add(current_run)
        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise HTTPException(422, "请求体必须为 JSON") from exc
                if isinstance(body, dict):
                    for key in ("run_id", "parent_run_id", "source_run_id"):
                        if body.get(key):
                            run_ids.add(str(body[key]))
                    if not isinstance(body.get("run_ids", []), list):
                        raise HTTPException(422, "run_ids 必须为数组")
                    for value in body.get("run_ids", []):
                        run_ids.add(str(value))
                    if path == "/api/v1/runs" and scope["method"] == "POST":
                        body.update(
                            tenant_id=identity.tenant_id, workspace_id=identity.uid, project_id="", profile_id=""
                        )
                    is_run_edit = len(parts) == 5 and parts[3] == "runs" and scope["method"] == "PATCH"
                    model_field = "execution" if path == "/api/v1/runs" or is_run_edit else "model_config"
                    is_launch = (path == "/api/v1/runs" or path == "/api/v1/query-library/generations") and scope[
                        "method"
                    ] == "POST"
                    model_config = body.get(model_field, {})
                    if is_run_edit and model_field not in body:
                        if self.run_loader is None:
                            raise HTTPException(503, "研究权限校验不可用")
                        try:
                            existing = await run_in_threadpool(self.run_loader, parts[4])
                        except KeyError as exc:
                            raise HTTPException(404, "研究任务不存在") from exc
                        model_config = dict(existing.execution)
                        body[model_field] = model_config
                    if (is_launch or is_run_edit) and not isinstance(model_config, dict):
                        raise HTTPException(422, f"{model_field} 必须为对象")
                    if (is_launch or is_run_edit) and model_config.get("mode") != "fake":
                        from platform_core.services.equipment_model_adapter import (
                            default_chat_model_spec,
                            resolve_equipment_model,
                        )

                        async with pg_manager.get_async_session_context() as db:
                            spec = str(model_config.get("model_spec") or await default_chat_model_spec(db))
                        try:
                            await run_in_threadpool(resolve_equipment_model, spec)
                        except RuntimeError as exc:
                            raise HTTPException(422, str(exc)) from exc
                        body[model_field] = {"model_spec": spec}
                        if model_field == "execution":
                            body["model_profile_id"] = ""
                    raw = json.dumps(body, ensure_ascii=False).encode()
                scope["headers"] = [(k, v) for k, v in headers if k.lower() != b"content-length"] + [
                    (b"content-length", str(len(raw)).encode())
                ]
            original_receive = request.receive
            consumed = False

            async def replay():
                """重放已验证的请求体，后续断线通知仍交给 ASGI。"""
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": raw, "more_body": False}
                return await original_receive()

            request._receive = replay
        for run_id in run_ids:
            if self.run_loader is None:
                raise HTTPException(503, "研究权限校验不可用")
            try:
                run = await run_in_threadpool(self.run_loader, run_id)
                if scope["method"] in {"GET", "HEAD"} and not identity.owns_run(run):
                    # Opaque 404 prevents guessed IDs from revealing that
                    # another user's task exists.  The mounted legacy app
                    # performs the same check; keeping it at this gateway
                    # boundary also protects future handlers that use an
                    # unscoped loader directly.
                    raise HTTPException(404, "研究任务不存在")
                if scope["method"] not in {"GET", "HEAD"} and not identity.can_mutate_run(run):
                    raise HTTPException(403, "无权修改该研究任务")
            except (KeyError,) as exc:
                raise HTTPException(404, "研究任务不存在") from exc
