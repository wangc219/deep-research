"""通过运行中的真实 HTTP API 验证 AMiner 配置与权限。"""

import os
import secrets
from uuid import uuid4
from copy import deepcopy

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.config.options import aminer_api_opts, get_option
from platform_core.storage.postgres.models_business import User, Department, OperationLog
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def aminer_http_users(test_client):
    """创建一次性本地账号并走真实登录，不依赖人工提供测试密码。"""
    engine = create_async_engine(os.environ["POSTGRES_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    identities = []
    try:
        async with factory.begin() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            for role in ("admin", "user"):
                uid = f"pytest_aminer_{uuid4().hex[:16]}"
                password = secrets.token_urlsafe(24)
                db.add(
                    User(
                        uid=uid,
                        username=uid,
                        password_hash=AuthUtils.hash_password(password),
                        role=role,
                        department_id=department_id,
                    )
                )
                identities.append((uid, password))
        headers = []
        for uid, password in identities:
            response = await test_client.post("/api/auth/token", data={"username": uid, "password": password})
            assert response.status_code == 200, response.text
            headers.append({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield headers
    finally:
        async with factory.begin() as db:
            users = select(User.id).where(User.uid.in_([uid for uid, _ in identities]))
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(users)))
            await db.execute(delete(User).where(User.id.in_(users)))
        await engine.dispose()


@pytest_asyncio.fixture
async def admin_headers(aminer_http_users):
    """使用临时管理员授权。"""
    return aminer_http_users[0]


@pytest_asyncio.fixture
async def standard_user(aminer_http_users):
    """使用临时普通账号授权。"""
    return {"headers": aminer_http_users[1]}


async def test_aminer_admin_configuration_and_draft_test_do_not_expose_or_save_keys(
    test_client, admin_headers, standard_user
):
    """普通用户不能维护；管理员留空保留、替换、清除且测试不保存。"""
    endpoint = "/api/system/config/options/aminer_api_opts"
    assert (await test_client.post("/api/system/aminer/test", json={})).status_code == 401
    assert (
        await test_client.post("/api/system/aminer/test", json={}, headers=standard_user["headers"])
    ).status_code == 403
    assert (
        await test_client.put(endpoint, json={"value": {"enabled": False}}, headers=standard_user["headers"])
    ).status_code == 403
    engine = create_async_engine(os.environ["POSTGRES_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        record = await get_option(db, aminer_api_opts.key)
        previous = deepcopy(record.value)
        previous_by = record.updated_by
        previous_at = record.updated_at
    try:
        response = await test_client.put(
            endpoint,
            json={
                "value": {
                    "enabled": False,
                    "user_id": "pytest-aminer-user",
                    "api_key": "pytest-first-secret",
                    "chat_budget_cents": 0,
                }
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["option"]["value"]["api_key"] == ""
        assert "pytest-first-secret" not in response.text
        for key in ["", "  ", "pytest-second-secret"]:
            response = await test_client.put(endpoint, json={"value": {"api_key": key}}, headers=admin_headers)
            assert response.status_code == 200, response.text
            async with factory() as db:
                value = (await aminer_api_opts.get(db))["api_key"]
            assert value == ("pytest-second-secret" if key == "pytest-second-secret" else "pytest-first-secret")
        # 空用户 ID 使免费测试在发送前返回，验证草稿不会覆盖保存的值。
        response = await test_client.post("/api/system/aminer/test", json={"user_id": ""}, headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "not_configured"
        async with factory() as db:
            assert (await aminer_api_opts.get(db))["user_id"] == "pytest-aminer-user"
        response = await test_client.post(
            "/api/system/aminer/test", json={"unexpected": "field"}, headers=admin_headers
        )
        assert response.status_code == 422
        response = await test_client.put(
            endpoint, json={"value": {"api_key": None, "enabled": False}}, headers=admin_headers
        )
        assert response.status_code == 200
        assert response.json()["option"]["sensitive_configured"]["api_key"] is False
        response = await test_client.post("/api/system/aminer/test", json={}, headers=admin_headers)
        assert response.json()["status"] == "not_configured"
        response = await test_client.put(endpoint, json={"value": {"enabled": True}}, headers=admin_headers)
        assert response.status_code == 400
    finally:
        async with factory.begin() as db:
            record = await get_option(db, aminer_api_opts.key)
            record.value = previous
            record.updated_by = previous_by
            record.updated_at = previous_at
        await engine.dispose()
