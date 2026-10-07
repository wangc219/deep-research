"""超级管理员代管个人研究资源时保持资源所有者运行域。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from platform_core.services import equipment_research_service as service


def _actor():
    return SimpleNamespace(uid="root", role="superadmin")


def _project():
    return SimpleNamespace(
        id="project-1",
        uid="owner",
        status="active",
        workdir_path="owner/project-1",
        directory_mode="managed",
    )


@pytest.fixture(autouse=True)
def _audit(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", audit)
    return audit


@pytest.mark.asyncio
async def test_foreign_run_is_hidden_from_normal_users_but_visible_to_superadmin(monkeypatch):
    run = SimpleNamespace(id="run-1", owner_uid="owner", import_batch_id=None)
    repo = SimpleNamespace(get_run=AsyncMock(return_value=run))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)

    with pytest.raises(HTTPException) as error:
        await service._require_run(
            object(),
            user=SimpleNamespace(uid="stranger", role="user"),
            run_id=run.id,
        )
    assert error.value.status_code == 404

    assert await service._require_run(object(), user=_actor(), run_id=run.id) is run


@pytest.mark.asyncio
async def test_foreign_query_is_hidden_from_normal_users_but_visible_to_superadmin(monkeypatch):
    query = SimpleNamespace(id="query-1", owner_uid="owner", import_batch_id=None)
    repo = SimpleNamespace(get_query=AsyncMock(return_value=query))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)

    with pytest.raises(HTTPException) as error:
        await service._require_query(
            object(),
            user=SimpleNamespace(uid="stranger", role="user"),
            query_id=query.id,
        )
    assert error.value.status_code == 404

    assert await service._require_query(object(), user=_actor(), query_id=query.id) is query


@pytest.mark.asyncio
async def test_superadmin_created_run_belongs_to_target_project_owner(monkeypatch, _audit):
    project = _project()
    event = SimpleNamespace(to_dict=lambda: {"event_type": "run_created"})
    repo = SimpleNamespace(add_run=AsyncMock(), append_event=AsyncMock(return_value=event))
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(service, "_publish_stream", AsyncMock())
    monkeypatch.setattr(
        "platform_core.services.equipment_model_adapter.default_chat_model_spec",
        AsyncMock(return_value=""),
    )

    result = await service.create_run(
        db=db,
        user=_actor(),
        project_id=project.id,
        topic="代管研究任务",
        payload={"knowledge_ids": [" kb-owner ", "kb-owner", "kb-shared"]},
    )

    assert result["owner_uid"] == "owner"
    assert result["knowledge_enabled"] is True
    assert result["knowledge_ids"] == ["kb-owner", "kb-shared"]
    assert repo.add_run.await_args.args[0].owner_uid == "owner"
    assert _audit.await_args.kwargs == {
        "actor": _actor(),
        "action": "create",
        "resource_type": "research_run",
        "resource_id": result["run_id"],
        "owner_uid": "owner",
    }


@pytest.mark.asyncio
async def test_superadmin_audit_failure_prevents_run_commit(monkeypatch, _audit):
    project = _project()
    event = SimpleNamespace(to_dict=lambda: {"event_type": "run_created"})
    repo = SimpleNamespace(add_run=AsyncMock(), append_event=AsyncMock(return_value=event))
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(service, "_publish_stream", AsyncMock())
    monkeypatch.setattr(
        "platform_core.services.equipment_model_adapter.default_chat_model_spec",
        AsyncMock(return_value=""),
    )
    _audit.side_effect = RuntimeError("audit unavailable")

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.create_run(
            db=db,
            user=_actor(),
            project_id=project.id,
            topic="必须审计的代管任务",
        )

    db.commit.assert_not_awaited()
    service._publish_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_superadmin_created_query_and_generation_belong_to_project_owner(monkeypatch):
    project = _project()
    query_repo = SimpleNamespace(
        add_query=AsyncMock(),
        add_query_revision=AsyncMock(),
        get_query_by_fingerprint=AsyncMock(return_value=None),
    )
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: query_repo)

    query = await service.create_query(
        db=db,
        user=_actor(),
        project_id=project.id,
        query_text="目标用户的研究问题",
        knowledge_ids=[" kb-owner ", "kb-owner"],
    )
    assert query["owner_uid"] == "owner"
    assert query["knowledge_enabled"] is True
    assert query["knowledge_ids"] == ["kb-owner"]
    assert query_repo.add_query.await_args.args[0].owner_uid == "owner"
    assert query_repo.add_query_revision.await_args.args[0].snapshot["knowledge_ids"] == ["kb-owner"]

    generation_repo = SimpleNamespace(add_generation=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: generation_repo)
    monkeypatch.setattr(service, "_resolve_requested_model", AsyncMock(return_value={"model_spec": "provider:model"}))
    monkeypatch.setattr(service, "_enqueue_typed", AsyncMock())

    generation = await service.submit_query_generation(
        db=db,
        user=_actor(),
        project_id=project.id,
        topic="生成目标用户 Query",
        knowledge_enabled=False,
        knowledge_ids=[],
    )
    assert generation["owner_uid"] == "owner"
    assert generation["knowledge_enabled"] is False
    assert generation["knowledge_ids"] == []
    assert generation_repo.add_generation.await_args.args[0].owner_uid == "owner"


@pytest.mark.asyncio
async def test_superadmin_run_inherits_published_query_scope_without_taking_ownership(monkeypatch, _audit):
    project = _project()
    source_query = SimpleNamespace(
        id="query-1",
        project_id=project.id,
        owner_uid="owner",
        status="published",
        source_type="manual",
        version=3,
        payload={"knowledge_enabled": True, "knowledge_ids": []},
        import_batch_id=None,
    )
    event = SimpleNamespace(to_dict=lambda: {"event_type": "run_created"})
    repo = SimpleNamespace(
        get_query=AsyncMock(return_value=source_query),
        add_run=AsyncMock(),
        append_event=AsyncMock(return_value=event),
    )
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(service, "_publish_stream", AsyncMock())
    monkeypatch.setattr(
        "platform_core.services.equipment_model_adapter.default_chat_model_spec",
        AsyncMock(return_value=""),
    )

    inherited = await service.create_run(
        db=db,
        user=_actor(),
        project_id=project.id,
        topic="从 Query 启动",
        source_query_id=source_query.id,
        source_query_version=3,
    )
    assert inherited["owner_uid"] == "owner"
    assert inherited["knowledge_ids"] == []
    assert inherited["source_query_id"] == "query-1"
    assert inherited["source_query_version"] == 3

    # Explicit null is not collapsed into the inherited empty list: it means
    # all knowledge bases currently visible to the same target owner.
    all_owner_visible = await service.create_run(
        db=db,
        user=_actor(),
        project_id=project.id,
        topic="覆盖 Query 默认范围",
        payload={"knowledge_ids": None},
        source_query_id=source_query.id,
        source_query_version=3,
    )
    assert all_owner_visible["owner_uid"] == "owner"
    assert all_owner_visible["knowledge_ids"] is None


@pytest.mark.asyncio
async def test_superadmin_updates_run_scope_without_changing_owner(monkeypatch, _audit):
    run = SimpleNamespace(
        id="run-1",
        owner_uid="owner",
        import_batch_id=None,
        readonly=0,
        status="draft",
        topic="研究任务",
        research_route="auto",
        payload={"knowledge_enabled": True, "knowledge_ids": ["kb-owner"]},
        updated_at=None,
        to_dict=lambda: {
            "run_id": run.id,
            "owner_uid": run.owner_uid,
            "knowledge_enabled": run.payload["knowledge_enabled"],
            "knowledge_ids": run.payload["knowledge_ids"],
        },
    )
    event = SimpleNamespace(to_dict=lambda: {"event_type": "run_updated"})
    repo = SimpleNamespace(
        lock_run=AsyncMock(return_value=run),
        append_event=AsyncMock(return_value=event),
    )
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(service, "_publish_stream", AsyncMock())

    all_visible = await service.update_run(
        db=db,
        user=_actor(),
        run_id=run.id,
        patch={"knowledge_ids": None},
    )
    assert all_visible == {
        "run_id": "run-1",
        "owner_uid": "owner",
        "knowledge_enabled": True,
        "knowledge_ids": None,
    }

    none_visible = await service.update_run(
        db=db,
        user=_actor(),
        run_id=run.id,
        patch={"knowledge_ids": [], "knowledge_enabled": False},
    )
    assert none_visible["owner_uid"] == "owner"
    assert none_visible["knowledge_enabled"] is False
    assert none_visible["knowledge_ids"] == []


@pytest.mark.asyncio
async def test_superadmin_created_native_deep_session_keeps_owner_domain(monkeypatch):
    project = _project()
    parent_run = SimpleNamespace(
        id="run-1",
        project_id=project.id,
        owner_uid="owner",
        topic="目标研究",
    )
    repo = SimpleNamespace(add_deep_session=AsyncMock())
    conversations = SimpleNamespace(add_conversation=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=parent_run))
    monkeypatch.setattr(
        service,
        "_deep_execution_user",
        AsyncMock(return_value=SimpleNamespace(uid="owner", role="user")),
    )
    monkeypatch.setattr(service, "_resolve_requested_model", AsyncMock(return_value={"model_spec": "provider:model"}))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repo)
    monkeypatch.setattr(
        "platform_core.repositories.conversation_repository.ConversationRepository",
        lambda _db: conversations,
    )
    monkeypatch.setattr(
        "platform_core.services.equipment_deep_integration_service.resolve_deep_agent",
        AsyncMock(return_value=SimpleNamespace(slug="deep-research", name="深度研究")),
    )

    result = await service.create_deep_session(
        db=db,
        user=_actor(),
        project_id=project.id,
        run_id=parent_run.id,
    )

    assert result["owner_uid"] == "owner"
    assert repo.add_deep_session.await_args.args[0].owner_uid == "owner"
    assert conversations.add_conversation.await_args.kwargs["uid"] == "owner"


@pytest.mark.asyncio
async def test_superadmin_message_executes_as_owner_and_preserves_actor(monkeypatch):
    session = SimpleNamespace(
        id="thinking-1",
        owner_uid="owner",
        payload={"runtime": "agent", "thread_id": "thread-1", "model_spec": "provider:model"},
    )
    owner = SimpleNamespace(uid="owner", role="user")
    delegated = AsyncMock(return_value={"accepted": True})

    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: SimpleNamespace())
    monkeypatch.setattr(service, "_require_deep_session", AsyncMock(return_value=session))
    monkeypatch.setattr(service, "_deep_execution_user", AsyncMock(return_value=owner))
    monkeypatch.setattr(service, "_resolve_requested_model", AsyncMock(return_value={"model_spec": "provider:model"}))
    monkeypatch.setattr(service, "_send_agent_deep_message", delegated)

    result = await service.send_deep_message(
        db=object(),
        user=_actor(),
        session_id=session.id,
        content="继续核验",
    )

    assert result == {"accepted": True}
    assert delegated.await_args.kwargs["user"] is owner
    assert delegated.await_args.kwargs["actor_uid"] == "root"
