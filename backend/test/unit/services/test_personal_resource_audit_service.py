"""全局管理员个人资源写入审计测试。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.services import personal_resource_audit_service as service


@pytest.mark.asyncio
async def test_superadmin_audit_records_actor_target_owner_and_cross_user(monkeypatch):
    writer = AsyncMock()
    db = object()
    monkeypatch.setattr(service, "log_operation", writer)

    await service.audit_superadmin_personal_resource_write(
        db,
        actor=SimpleNamespace(id=7, uid="root", role="superadmin"),
        action="publish",
        resource_type="query",
        resource_id="query-1",
        owner_uid="owner",
    )

    details = json.loads(writer.await_args.args[3])
    assert writer.await_args.args[:3] == (db, 7, "全局管理员管理个人资源")
    assert details == {
        "action": "publish",
        "actor_uid": "root",
        "actor_role": "superadmin",
        "audit_stage": "success",
        "cross_user": True,
        "owner_uid": "owner",
        "resource_id": "query-1",
        "resource_type": "query",
    }


@pytest.mark.asyncio
async def test_admin_write_creates_global_admin_audit(monkeypatch):
    writer = AsyncMock()
    monkeypatch.setattr(service, "log_operation", writer)

    await service.audit_superadmin_personal_resource_write(
        object(),
        actor=SimpleNamespace(id=9, uid="admin", role="admin"),
        action="update",
        resource_type="research_run",
        resource_id="run-1",
        owner_uid="owner",
    )

    assert writer.await_count == 1
    assert json.loads(writer.await_args.args[3])["actor_role"] == "admin"


@pytest.mark.asyncio
async def test_normal_user_write_does_not_create_global_admin_audit(monkeypatch):
    writer = AsyncMock()
    monkeypatch.setattr(service, "log_operation", writer)

    await service.audit_superadmin_personal_resource_write(
        object(),
        actor=SimpleNamespace(id=8, uid="owner", role="user"),
        action="update",
        resource_type="research_run",
        resource_id="run-1",
        owner_uid="owner",
    )

    writer.assert_not_awaited()
