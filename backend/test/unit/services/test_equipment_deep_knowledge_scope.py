from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.services import equipment_research_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_ids", "expected_ids"),
    [
        (None, ["kb-run-a", "kb-run-b"]),
        ([" kb-run-b ", "kb-outside", "kb-run-b"], ["kb-run-b"]),
        ([], []),
    ],
)
async def test_deep_session_inherits_or_narrows_run_knowledge_scope(
    monkeypatch: pytest.MonkeyPatch,
    requested_ids: list[str] | None,
    expected_ids: list[str],
) -> None:
    project = SimpleNamespace(id="project-1", uid="owner", status="active")
    run = SimpleNamespace(
        id="run-1",
        project_id=project.id,
        owner_uid=project.uid,
        topic="装备体系研究",
        payload={"knowledge_ids": ["kb-run-a", "kb-run-b"]},
    )
    owner = SimpleNamespace(uid="owner", role="user")
    repository = SimpleNamespace(add_deep_session=AsyncMock())
    conversations = SimpleNamespace(add_conversation=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "_deep_execution_user", AsyncMock(return_value=owner))
    monkeypatch.setattr(
        service,
        "_resolve_requested_model",
        AsyncMock(return_value={"model_spec": "provider:model"}),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", AsyncMock())
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
        user=owner,
        project_id=project.id,
        run_id=run.id,
        knowledge_ids=requested_ids,
    )

    created = repository.add_deep_session.await_args.args[0]
    assert created.payload["knowledge_ids"] == expected_ids
    assert result["payload"]["knowledge_ids"] == expected_ids
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_deep_session_cannot_reenable_parent_disabled_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = SimpleNamespace(id="project-1", uid="owner", status="active")
    run = SimpleNamespace(
        id="run-1",
        project_id=project.id,
        owner_uid=project.uid,
        topic="装备体系研究",
        payload={"knowledge_enabled": False, "knowledge_ids": []},
    )
    owner = SimpleNamespace(uid="owner", role="user")
    repository = SimpleNamespace(add_deep_session=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "_deep_execution_user", AsyncMock(return_value=owner))
    monkeypatch.setattr(
        service,
        "_resolve_requested_model",
        AsyncMock(return_value={"model_spec": "provider:model"}),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", AsyncMock())
    monkeypatch.setattr(
        "platform_core.repositories.conversation_repository.ConversationRepository",
        lambda _db: SimpleNamespace(add_conversation=AsyncMock()),
    )
    monkeypatch.setattr(
        "platform_core.services.equipment_deep_integration_service.resolve_deep_agent",
        AsyncMock(return_value=SimpleNamespace(slug="deep-research", name="深度研究")),
    )

    await service.create_deep_session(
        db=db,
        user=owner,
        project_id=project.id,
        run_id=run.id,
        knowledge_enabled=True,
        knowledge_ids=["kb-outside"],
    )

    created = repository.add_deep_session.await_args.args[0]
    assert created.payload["knowledge_enabled"] is False
    assert created.payload["knowledge_ids"] == []
