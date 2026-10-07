from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.auth_router import auth
from server.utils.auth_middleware import get_db, get_required_user
from platform_core.storage.postgres.models_business import Base, Department, User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


@pytest.fixture(autouse=True)
def cli_auth_security_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY_DERIVATION_SECRET", "test-api-key-derivation-secret-32-chars")
    monkeypatch.setenv("EQUIPMENT_ALLOW_SELF_REGISTRATION", "true")


@pytest_asyncio.fixture()
async def app_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        dept = Department(name="默认部门")
        db.add(dept)
        await db.flush()
        research_dept = Department(name="研发部门", parent_id=dept.id)
        user = User(
            username="Legacy Admin",
            uid="admin",
            password_hash="$argon2id$placeholder",
            role="superadmin",
            department=dept,
        )
        db.add_all([research_dept, user])
        await db.commit()
        await db.refresh(user)

        app = FastAPI()
        app.include_router(auth, prefix="/api")

        async def override_db():
            yield db

        async def override_user():
            return user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_required_user] = override_user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    await engine.dispose()


async def test_auth_router_cli_auth_create_approve_and_exchange(app_client):
    create_response = await app_client.post("/api/auth/cli/sessions", json={})
    assert create_response.status_code == 200, create_response.text
    session = create_response.json()
    assert session["verification_uri"] == "/auth/cli/authorize"

    pending_response = await app_client.post(
        "/api/auth/cli/sessions/token", json={"device_code": session["device_code"]}
    )
    assert pending_response.status_code == 400
    assert pending_response.json()["detail"]["error"] == "authorization_pending"

    read_response = await app_client.get(f"/api/auth/cli/sessions/{session['user_code']}")
    assert read_response.status_code == 200
    assert read_response.json()["status"] == "pending"

    approve_response = await app_client.post(f"/api/auth/cli/sessions/{session['user_code']}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    token_response = await app_client.post("/api/auth/cli/sessions/token", json={"device_code": session["device_code"]})
    assert token_response.status_code == 200, token_response.text
    token_data = token_response.json()
    assert token_data["secret"].startswith("yxkey_")
    assert token_data["user"]["uid"] == "admin"


async def test_public_registration_selects_department_and_creates_audited_user_session(app_client):
    config_response = await app_client.get("/api/auth/registration-config")
    assert config_response.status_code == 200
    config = config_response.json()
    assert config["enabled"] is True
    assert {item["name"] for item in config["departments"]} == {"默认部门", "研发部门"}
    research_department = next(item for item in config["departments"] if item["name"] == "研发部门")

    register_response = await app_client.post(
        "/api/auth/register",
        json={
            "username": "测试研究员",
            "password": "secure-password",
            "phone_number": "13800138000",
            "department_id": research_department["id"],
        },
    )
    assert register_response.status_code == 201, register_response.text
    payload = register_response.json()
    assert payload["role"] == "user"
    assert payload["department_name"] == "研发部门"
    assert payload["department_id"] == research_department["id"]
    assert payload["uid"]
    assert payload["access_token"]

    claims = AuthUtils.verify_access_token(payload["access_token"])
    assert claims["sub"] == str(payload["user_id"])

    missing_department = await app_client.post(
        "/api/auth/register",
        json={
            "username": "不存在部门用户",
            "password": "secure-password",
            "department_id": 999999,
        },
    )
    assert missing_department.status_code == 422
    assert missing_department.json()["detail"] == "所选部门不存在"


async def test_superadmin_can_change_own_uid(app_client):
    users_response = await app_client.get("/api/auth/users/page")
    assert users_response.status_code == 200
    superadmin = next(item for item in users_response.json()["items"] if item["role"] == "superadmin")

    update_response = await app_client.put(
        f"/api/auth/users/{superadmin['id']}",
        json={"uid": "renamed_admin", "username": superadmin["username"]},
    )

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["uid"] == "renamed_admin"

    invalid_response = await app_client.put(
        f"/api/auth/users/{superadmin['id']}",
        json={"uid": "invalid uid"},
    )
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"] == "用户ID只能包含字母、数字和下划线"
