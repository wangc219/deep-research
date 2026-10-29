"""公众号共享账号池的角色授权边界。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from starlette.responses import Response

from server.routers import wechat_mp_router as router


def request(method: str) -> Request:
    """构造无需启动完整应用的最小请求。"""
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/api/wechat-mp/app/",
            "raw_path": b"/api/wechat-mp/app/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "api/auth/login"),
        ("GET", "api/auth/qrcode"),
        ("POST", "api/auth/manual"),
        ("DELETE", "api/account-pool/account-1"),
        ("POST", "api/account-pool/account-1/refresh"),
        ("GET", "api/account-pool/events"),
    ],
)
async def test_ordinary_user_cannot_manage_shared_accounts(method, path):
    """普通用户即使具备知识库写权限也不能改动平台共享凭据。"""
    user = SimpleNamespace(uid="ordinary", role="user")

    with pytest.raises(HTTPException) as error:
        await router.application(path, request(method), user)

    assert error.value.status_code == 403
    assert "仅允许管理员" in error.value.detail


@pytest.mark.parametrize("role", ["admin", "superadmin"])
async def test_platform_administrators_can_manage_shared_accounts(monkeypatch, role):
    """管理员请求继续转发到其私有 Worker，但 Worker 使用共享凭据文件。"""
    forwarded = {}

    async def forward(incoming, key, path):
        forwarded.update({"method": incoming.method, "key": key, "path": path})
        return Response(status_code=204)

    monkeypatch.setattr(router.service, "register_owner", lambda uid: "owner-key")
    monkeypatch.setattr(router, "forward", forward)

    response = await router.application(
        "api/account-pool/account-1/refresh",
        request("POST"),
        SimpleNamespace(uid="manager", role=role),
    )

    assert response.status_code == 204
    assert forwarded == {
        "method": "POST",
        "key": "owner-key",
        "path": "/api/account-pool/account-1/refresh",
    }


async def test_ordinary_user_can_read_shared_account_status(monkeypatch):
    """普通用户可查看脱敏状态并自动使用共享账号。"""
    monkeypatch.setattr(router.service, "register_owner", lambda uid: "owner-key")

    async def forward(incoming, key, path):
        return Response(content=f"{key}:{path}")

    monkeypatch.setattr(router, "forward", forward)
    response = await router.application(
        "api/account-pool",
        request("GET"),
        SimpleNamespace(uid="ordinary", role="user"),
    )

    assert response.body == b"owner-key:/api/account-pool"
