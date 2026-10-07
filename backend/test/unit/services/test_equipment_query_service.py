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
async def test_query_list_returns_server_pagination_and_filters(monkeypatch):
    row = _query()
    repository = SimpleNamespace(
        list_queries=AsyncMock(return_value=[row]),
        count_queries=AsyncMock(return_value=23),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    result = await service.list_queries(
        db=object(),
        user=_user(),
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
        "owner",
        project_id="project-1",
        status="draft",
        source_type="manual",
        search="研究",
        limit=10,
        offset=20,
        include_legacy=True,
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
async def test_historical_query_rejects_every_mutation(monkeypatch):
    row = _query(legacy_source_id="legacy-query-1", import_batch_id="legacy-batch")
    repository = SimpleNamespace(lock_query=AsyncMock(return_value=row))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    with pytest.raises(HTTPException) as error:
        await service.publish_query(
            db=object(),
            user=_user(),
            query_id=row.id,
            expected_version=1,
        )

    assert error.value.status_code == 409
    assert "只读" in str(error.value.detail)


@pytest.mark.asyncio
async def test_historical_query_is_readable_by_other_users_but_future_query_is_not(monkeypatch):
    historical = _query(owner_uid="legacy-owner", legacy_source_id="legacy-query-1")
    repository = SimpleNamespace(get_query=AsyncMock(return_value=historical))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    visible = await service.get_query(
        db=object(),
        user=_user(),
        query_id=historical.id,
        include_revisions=False,
    )
    assert visible["query_id"] == historical.id
    assert visible["readonly"] is True

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
