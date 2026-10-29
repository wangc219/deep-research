"""统一 Query 平台服务的分页、版本与历史只读契约。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from platform_core.services import equipment_research_service as service
from platform_core.storage.postgres.models_equipment import EquipmentQuery


def _user():
    return SimpleNamespace(uid="owner", role="user")


def _query(**overrides):
    values = {
        "id": "query-1",
        "project_id": "project-1",
        "owner_uid": "owner",
        "query_text": "原始研究问题",
        "query_fingerprint": "fingerprint",
        "supplemental_information": "原始补充",
        "status": "draft",
        "source_type": "manual",
        "version": 1,
        "payload": {"generation_rationale": "原始理由"},
        "legacy_source_id": None,
        "import_batch_id": None,
    }
    values.update(overrides)
    return EquipmentQuery(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "admin", "superadmin"])
async def test_query_list_returns_server_pagination_and_filters(monkeypatch, role):
    row = _query()
    repository = SimpleNamespace(
        list_queries=AsyncMock(return_value=[row]),
        count_queries=AsyncMock(return_value=23),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    result = await service.list_queries(
        db=object(),
        user=SimpleNamespace(uid="owner", role=role),
        project_id="project-1",
        status="draft",
        source_type="manual",
        search="研究",
        limit=10,
        offset=20,
    )

    assert result["items"][0]["query_id"] == "query-1"
    assert result | {"items": []} == {"items": [], "total": 23, "limit": 10, "offset": 20}
    repository.list_queries.assert_awaited_once_with(
        "owner" if role == "user" else None,
        project_id="project-1",
        status="draft",
        source_type="manual",
        search="研究",
        limit=10,
        offset=20,
        include_legacy=role == "superadmin",
    )


@pytest.mark.asyncio
async def test_query_update_uses_optimistic_version_and_revision(monkeypatch):
    row = _query()
    repository = SimpleNamespace(
        lock_query=AsyncMock(return_value=row),
        get_query_by_fingerprint=AsyncMock(return_value=None),
        add_query_revision=AsyncMock(),
    )
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", AsyncMock())

    result = await service.update_query(
        db=db,
        user=_user(),
        query_id=row.id,
        changes={
            "expected_version": 1,
            "query": "更新后的研究问题",
            "generation_rationale": "更新理由",
        },
    )

    assert result["query"] == "更新后的研究问题"
    assert result["version"] == 2
    assert result["generation_rationale"] == "更新理由"
    revision = repository.add_query_revision.await_args.args[0]
    assert revision.version == 2
    assert revision.snapshot["version"] == 2
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "admin", "superadmin"])
async def test_only_superadmin_can_change_historical_query_without_transferring_owner(monkeypatch, role):
    row = _query(owner_uid="legacy-owner", legacy_source_id="legacy-query-1", import_batch_id="workbench-sync")
    repository = SimpleNamespace(lock_query=AsyncMock(return_value=row), add_query_revision=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock(), add=lambda _row: None, flush=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", AsyncMock())
    user = SimpleNamespace(uid="other-user", id=1, role=role)
    if role != "superadmin":
        with pytest.raises(HTTPException) as error:
            await service.publish_query(db=db, user=user, query_id=row.id, expected_version=1)
        assert error.value.status_code == 404
        repository.add_query_revision.assert_not_awaited()
        db.commit.assert_not_awaited()
        assert row.status == "draft" and row.version == 1
        return
    result = await service.publish_query(db=db, user=user, query_id=row.id, expected_version=1)
    assert result["version"] == 2
    assert result["owner_uid"] == "legacy-owner"
    assert result["payload"]["original_snapshot"]["status"] == "draft"
    assert result["last_modified_by"] == "other-user"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "admin", "superadmin"])
async def test_historical_query_is_superadmin_only_and_native_query_stays_private(monkeypatch, role):
    historical = _query(owner_uid="legacy-owner", legacy_source_id="legacy-query-1")
    repository = SimpleNamespace(get_query=AsyncMock(return_value=historical))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    user = SimpleNamespace(uid="owner", role=role)
    if role == "superadmin":
        visible = await service.get_query(
            db=object(), user=user, query_id=historical.id, include_revisions=False
        )
        assert visible["query_id"] == historical.id
    else:
        with pytest.raises(HTTPException) as error:
            await service.get_query(db=object(), user=user, query_id=historical.id, include_revisions=False)
        assert error.value.status_code == 404

    future = _query(owner_uid="another-user")
    repository.get_query.return_value = future
    with pytest.raises(HTTPException) as error:
        await service.get_query(
            db=object(),
            user=_user(),
            query_id=future.id,
            include_revisions=False,
        )
    assert error.value.status_code == 404
