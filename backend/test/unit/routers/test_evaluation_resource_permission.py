from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.routers import knowledge_eval_router
from server.utils.auth_middleware import get_required_user
from server.utils import knowledge_permissions
from platform_core.permissions import ResourcePermission


@pytest.mark.asyncio
async def test_dataset_only_manage_route_checks_the_dataset_knowledge_base(monkeypatch):
    calls = []

    async def fake_get_dataset(_repository, _dataset_id):
        return SimpleNamespace(kb_id="kb-1")

    async def fake_ensure_permission(kb_id, current_user, required):
        calls.append((kb_id, current_user, required))
        return {}

    monkeypatch.setattr(knowledge_eval_router.EvaluationRepository, "get_dataset", fake_get_dataset)
    monkeypatch.setattr(knowledge_eval_router, "ensure_knowledge_base_permission", fake_ensure_permission)
    admin = SimpleNamespace(uid="admin-1", role="admin", department_id=1)

    result = await knowledge_eval_router.require_evaluation_dataset_manage("dataset-1", admin)

    assert result is admin
    assert calls == [("kb-1", admin, ResourcePermission.MANAGE)]


@pytest.mark.asyncio
async def test_dataset_manage_route_rejects_user_without_manage_permission(monkeypatch):
    async def fake_get_dataset(_repository, _dataset_id):
        return SimpleNamespace(kb_id="kb-1")

    async def fake_get_database_info(_kb_id):
        return {
            "created_by": "owner",
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "global"},
                "manage_scope": None,
            },
        }

    monkeypatch.setattr(knowledge_eval_router.EvaluationRepository, "get_dataset", fake_get_dataset)
    monkeypatch.setattr(knowledge_permissions.knowledge_base, "get_database_info", fake_get_database_info)
    user = SimpleNamespace(uid="other-user", role="user", department_id=1)

    with pytest.raises(HTTPException) as exc_info:
        await knowledge_eval_router.require_evaluation_dataset_manage("dataset-1", user)

    assert exc_info.value.status_code == 403


def test_evaluation_routes_use_resource_permission_for_regular_users(monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_eval_router.evaluation)

    async def fake_required_user():
        return SimpleNamespace(uid="user-1", role="user", department_id=1)

    async def fake_get_database_info(_kb_id):
        return {
            "created_by": "owner",
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "global"},
                "manage_scope": None,
            },
        }

    async def fake_list_datasets(_self, kb_id):
        assert kb_id == "kb-1"
        return []

    app.dependency_overrides[get_required_user] = fake_required_user
    monkeypatch.setattr(knowledge_permissions.knowledge_base, "get_database_info", fake_get_database_info)
    monkeypatch.setattr(knowledge_eval_router.EvaluationService, "list_datasets", fake_list_datasets)

    response = TestClient(app).get("/evaluation/databases/kb-1/datasets")

    assert response.status_code == 200
    assert response.json() == {"message": "success", "data": []}


def test_personal_knowledge_owner_can_download_evaluation_dataset(monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_eval_router.evaluation)

    async def fake_required_user():
        return SimpleNamespace(uid="owner", role="user", department_id=1)

    async def fake_get_dataset(_repository, dataset_id):
        assert dataset_id == "dataset-1"
        return SimpleNamespace(kb_id="kb-1")

    async def fake_get_database_info(_kb_id):
        return {
            "created_by": "owner",
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "user", "user_uids": ["owner"]},
                "manage_scope": {"access_level": "user", "user_uids": ["owner"]},
            },
        }

    async def fake_export_dataset_jsonl(_self, dataset_id):
        assert dataset_id == "dataset-1"
        return {"filename": "benchmark.jsonl", "content": '{"query":"test"}\n'}

    app.dependency_overrides[get_required_user] = fake_required_user
    monkeypatch.setattr(knowledge_eval_router.EvaluationRepository, "get_dataset", fake_get_dataset)
    monkeypatch.setattr(knowledge_permissions.knowledge_base, "get_database_info", fake_get_database_info)
    monkeypatch.setattr(
        knowledge_eval_router.EvaluationService,
        "export_dataset_jsonl",
        fake_export_dataset_jsonl,
    )

    response = TestClient(app).get("/evaluation/datasets/dataset-1/download")

    assert response.status_code == 200
    assert response.content == b'{"query":"test"}\n'
