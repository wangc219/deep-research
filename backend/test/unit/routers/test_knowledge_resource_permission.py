from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from server.routers import knowledge_router
from server.utils.knowledge_response import serialize_knowledge_base
from platform_core.knowledge.read_models import KnowledgeBaseSummary


def test_serialize_knowledge_base_redacts_credentials_from_compatibility_fields():
    database = KnowledgeBaseSummary(
        kb_id="kb-1",
        name="知识库",
        description=None,
        kb_type="dify",
        embedding_model_spec=None,
        llm_model_spec=None,
        query_params={},
        additional_params={"dify_token": "secret", "chunk_size": 100},
        share_config={"version": 2, "read_scope": None, "manage_scope": None},
        created_by=None,
        created_at=None,
    )

    response = serialize_knowledge_base(database, redact_secrets=True)

    assert response["additional_params"]["chunk_size"] == 100
    assert response["metadata"]["chunk_size"] == 100
    assert "dify_token" not in response["additional_params"]
    assert "dify_token" not in response["metadata"]


@pytest.mark.parametrize(
    ("uid", "role", "can_read", "can_manage"),
    [("admin-1", "admin", True, True), ("other-user", "user", True, False)],
)
@pytest.mark.asyncio
async def test_global_admin_can_manage_and_global_reader_cannot(monkeypatch, uid, role, can_read, can_manage):
    database = {
        "created_by": "owner",
        "share_config": {
            "version": 2,
            "read_scope": {"access_level": "global"},
            "manage_scope": None,
        },
    }

    async def fake_get_database_info(_kb_id):
        return database

    monkeypatch.setattr(knowledge_router.knowledge_base, "get_database_info", fake_get_database_info)
    user = SimpleNamespace(uid=uid, role=role, department_id=2)

    if can_read:
        assert await knowledge_router.require_knowledge_base_read("kb-1", user) is user

    if can_manage:
        assert await knowledge_router.require_knowledge_base_manage("kb-1", user) is user
    else:
        with pytest.raises(HTTPException) as exc_info:
            await knowledge_router.require_knowledge_base_manage("kb-1", user)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_query_parameter_routes_apply_knowledge_base_acl(monkeypatch):
    database = {
        "created_by": "owner",
        "share_config": {
            "version": 2,
            "read_scope": {"access_level": "user", "user_uids": ["admin-1"]},
            "manage_scope": None,
        },
    }

    async def fake_get_database_info(_kb_id):
        return database

    monkeypatch.setattr(knowledge_router.knowledge_base, "get_database_info", fake_get_database_info)
    readonly_admin = SimpleNamespace(uid="admin-1", role="admin", department_id=2)

    assert await knowledge_router.require_knowledge_base_read("kb-1", readonly_admin) is readonly_admin

    global_admin = SimpleNamespace(uid="admin-2", role="admin", department_id=2)
    assert await knowledge_router.require_knowledge_base_read("kb-1", global_admin) is global_admin

    with pytest.raises(HTTPException) as exc_info:
        await knowledge_router.require_knowledge_base_read(
            "kb-1", SimpleNamespace(uid="user-2", role="user", department_id=2)
        )
    assert exc_info.value.status_code == 403


def test_standard_user_create_scope_is_always_private():
    user = SimpleNamespace(uid="user-1", role="user", department_id=2)

    assert knowledge_router._knowledge_create_share_config(user, None) == {
        "version": 2,
        "read_scope": None,
        "manage_scope": None,
    }

    with pytest.raises(HTTPException) as exc_info:
        knowledge_router._knowledge_create_share_config(
            user,
            {
                "version": 2,
                "read_scope": {"access_level": "global"},
                "manage_scope": None,
            },
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_standard_user_cannot_change_knowledge_share_scope(monkeypatch):
    private = {"version": 2, "read_scope": None, "manage_scope": None}
    database = SimpleNamespace(created_by="user-1", share_config=private)
    monkeypatch.setattr(
        knowledge_router.knowledge_base,
        "get_database_info",
        AsyncMock(return_value=database),
    )
    user = SimpleNamespace(uid="user-1", role="user", department_id=2)

    assert await knowledge_router._knowledge_update_share_config(user, "kb-1", private) == private
    with pytest.raises(HTTPException) as exc_info:
        await knowledge_router._knowledge_update_share_config(
            user,
            "kb-1",
            {
                "version": 2,
                "read_scope": {"access_level": "global"},
                "manage_scope": None,
            },
        )
    assert exc_info.value.status_code == 403
