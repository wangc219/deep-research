"""验证旧接口的创建和编辑都只能绑定平台模型凭据。"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from equipment_deep_research.domain.platform_identity import PlatformIdentity
from platform_core.services import equipment_model_adapter
from server.utils.enterprise_middleware import EnterpriseMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method,field",
    [
        ("/api/v1/runs", "POST", "execution"),
        ("/api/v1/runs/owned", "PATCH", "execution"),
        ("/api/v1/query-library/generations", "POST", "model_config"),
    ],
)
async def test_platform_model_replaces_client_credentials(monkeypatch, path, method, field):
    """覆盖客户端密钥和地址，仅保存已验证的模型标识。"""

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr("server.utils.enterprise_middleware.pg_manager.get_async_session_context", session)
    resolver = Mock(return_value={})
    monkeypatch.setattr(equipment_model_adapter, "resolve_equipment_model", resolver)
    raw = json.dumps(
        {
            field: {
                "model_spec": "configured:model",
                "api_key": "client-secret",
                "base_url": "https://untrusted.invalid",
            },
            "workspace_id": "other",
        }
    ).encode()

    async def receive():
        return {"type": "http.request", "body": raw}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [(b"x-role", b"admin"), (b"x-workspace-id", b"other")],
    }
    request = Request(scope, receive)
    middleware = EnterpriseMiddleware(
        None,
        run_loader=lambda _: SimpleNamespace(workspace_id="owner", tenant_id="tenant"),
    )
    await middleware.prepare_legacy(request, scope, PlatformIdentity("owner", "tenant"))
    payload = json.loads((await request.receive())["body"])
    assert payload[field] == {"model_spec": "configured:model"}
    assert b"client-secret" not in (json.dumps(payload).encode())
    assert dict(scope["headers"])[b"x-workspace-id"] == b"owner"
    assert dict(scope["headers"])[b"x-role"] == b"analyst"
    resolver.assert_called_once_with("configured:model")
    if path == "/api/v1/runs":
        assert payload["workspace_id"] == "owner" and payload["tenant_id"] == "tenant"


@pytest.mark.asyncio
async def test_malformed_execution_is_validation_error():
    """错误模型配置不应触发服务器异常。"""

    async def receive():
        return {"type": "http.request", "body": b'{"execution": [1]}'}

    scope = {"type": "http", "method": "POST", "path": "/api/v1/runs", "query_string": b"", "headers": []}
    with pytest.raises(HTTPException) as error:
        await EnterpriseMiddleware(None).prepare_legacy(Request(scope, receive), scope, PlatformIdentity("u", "t"))
    assert error.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("execution", [{"model_spec": "chosen:nondefault"}, {"mode": "fake"}])
async def test_draft_edit_preserves_selected_execution(monkeypatch, execution):
    """仅修改研究内容时，继续使用任务原有模型而非平台默认模型。"""

    @asynccontextmanager
    async def session():
        yield object()

    monkeypatch.setattr("server.utils.enterprise_middleware.pg_manager.get_async_session_context", session)
    resolver = Mock(return_value={})
    monkeypatch.setattr(equipment_model_adapter, "resolve_equipment_model", resolver)

    async def receive():
        return {"type": "http.request", "body": b'{"topic": "updated"}'}

    scope = {"type": "http", "method": "PATCH", "path": "/api/v1/runs/owned", "query_string": b"", "headers": []}
    request = Request(scope, receive)
    middleware = EnterpriseMiddleware(
        None,
        run_loader=lambda _: SimpleNamespace(
            execution=execution,
            workspace_id="owner",
            tenant_id="tenant",
        ),
    )
    await middleware.prepare_legacy(request, scope, PlatformIdentity("owner", "tenant"))
    assert json.loads((await request.receive())["body"])["execution"] == execution
    if "model_spec" in execution:
        resolver.assert_called_once_with("chosen:nondefault")
    else:
        resolver.assert_not_called()


@pytest.mark.asyncio
async def test_edit_missing_run_returns_not_found():
    """不存在的草稿返回稳定的 404。"""

    async def receive():
        return {"type": "http.request", "body": b'{"topic": "updated"}'}

    scope = {"type": "http", "method": "PATCH", "path": "/api/v1/runs/missing", "query_string": b"", "headers": []}
    middleware = EnterpriseMiddleware(None, run_loader=Mock(side_effect=KeyError("missing")))
    with pytest.raises(HTTPException) as error:
        await middleware.prepare_legacy(Request(scope, receive), scope, PlatformIdentity("owner", "tenant"))
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_guessed_run_id_is_hidden_from_another_user():
    """旧 GET/SSE/产物路径在路由前统一隐藏其他用户任务。"""

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/runs/foreign/events",
        "query_string": b"",
        "headers": [],
    }
    middleware = EnterpriseMiddleware(
        None,
        run_loader=lambda _: SimpleNamespace(
            workspace_id="other-user",
            tenant_id="tenant",
        ),
    )
    with pytest.raises(HTTPException) as error:
        await middleware.prepare_legacy(
            Request(scope, receive),
            scope,
            PlatformIdentity("owner", "tenant"),
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_superadmin_can_read_and_mutate_foreign_run():
    """超级管理员保留跨用户全局读写改权限。"""

    async def receive():
        return {"type": "http.request", "body": b""}

    run = SimpleNamespace(
        workspace_id="other-user",
        tenant_id="other-tenant",
    )
    middleware = EnterpriseMiddleware(None, run_loader=lambda _: run)
    for method in ("GET", "DELETE"):
        scope = {
            "type": "http",
            "method": method,
            "path": "/api/v1/runs/foreign",
            "query_string": b"",
            "headers": [],
        }
        await middleware.prepare_legacy(
            Request(scope, receive),
            scope,
            PlatformIdentity("root", "admin-tenant", superadmin=True),
        )
