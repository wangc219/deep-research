"""装备深研创建上下文选项测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from platform_core.services import equipment_research_service as service
from platform_core.storage.postgres.models_equipment import EquipmentResearchRun


@pytest.mark.asyncio
async def test_owner_can_mutate_imported_historical_run() -> None:
    run = EquipmentResearchRun(
        id="historical-run",
        project_id="project-1",
        owner_uid="owner",
        topic="历史任务",
        research_route="auto",
        status="completed",
        payload={},
        legacy_source_id="legacy-run",
        readonly=1,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=run))
    user = SimpleNamespace(uid="owner", role="user")

    resolved = await service._require_run(
        db,
        user=user,
        run_id=run.id,
        mutation=True,
    )
    projected = service._run_payload_for_user(resolved, user)

    assert resolved is run
    assert projected["historical_snapshot"] is True
    assert projected["readonly"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("task_status", ["pending", "running"])
async def test_cancel_run_commits_business_state_before_cancelling_durable_task(monkeypatch, task_status) -> None:
    order: list[str] = []
    run = SimpleNamespace(
        id="run-1",
        owner_uid="owner",
        status="researching",
        updated_at=None,
        to_dict=lambda: {"id": "run-1", "status": run.status},
    )
    event = SimpleNamespace(to_dict=lambda: {"type": "run_cancelled"})
    repository = SimpleNamespace(append_event=AsyncMock(return_value=event))
    task = SimpleNamespace(id="task-1", status=task_status)
    tasker = SimpleNamespace(
        find_task_by_payload=AsyncMock(return_value=task),
        cancel_task=AsyncMock(side_effect=lambda _task_id: order.append("cancel_task")),
    )
    db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: order.append("commit")))

    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "Tasker", lambda: tasker)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", AsyncMock())
    publish = AsyncMock()
    monkeypatch.setattr(service, "_publish_stream", publish)

    result = await service.cancel_run(
        db=db,
        user=SimpleNamespace(uid="owner", role="user"),
        run_id=run.id,
    )

    assert result["status"] == "cancelled"
    assert order == ["commit", "cancel_task"]
    tasker.find_task_by_payload.assert_awaited_once_with(
        task_type=service.EQUIPMENT_RESEARCH_TASK_TYPE,
        payload_match={"run_id": run.id},
        statuses={"pending", "running"},
    )
    tasker.cancel_task.assert_awaited_once_with(task.id)
    publish.assert_awaited_once_with(run.id, event.to_dict())


@pytest.mark.asyncio
async def test_delete_run_falls_back_to_visible_legacy_draft(monkeypatch) -> None:
    missing = HTTPException(status_code=404, detail="研究任务不存在")
    delete_legacy = AsyncMock(
        return_value={
            "deleted": True,
            "run_id": "legacy-draft",
            "status": "draft",
            "workspace_id": "owner",
            "owner_uid": "owner",
        }
    )
    db = SimpleNamespace(commit=AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(service, "_require_run", AsyncMock(side_effect=missing))
    monkeypatch.setattr(service.asyncio, "to_thread", delete_legacy)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", audit)
    user = SimpleNamespace(uid="owner", role="user")

    result = await service.delete_run(db=db, user=user, run_id="legacy-draft")

    assert result == {"deleted": True, "run_id": "legacy-draft"}
    delete_legacy.assert_awaited_once()
    audit.assert_awaited_once_with(
        db,
        actor=user,
        action="delete",
        resource_type="research_run",
        resource_id="legacy-draft",
        owner_uid="owner",
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_run_keeps_non_draft_legacy_history_read_only(monkeypatch) -> None:
    missing = HTTPException(status_code=404, detail="研究任务不存在")
    monkeypatch.setattr(service, "_require_run", AsyncMock(side_effect=missing))
    monkeypatch.setattr(
        service.asyncio,
        "to_thread",
        AsyncMock(
            return_value={
                "deleted": False,
                "run_id": "legacy-completed",
                "status": "completed",
                "workspace_id": "owner",
                "owner_uid": "owner",
            }
        ),
    )

    with pytest.raises(HTTPException) as error:
        await service.delete_run(
            db=SimpleNamespace(),
            user=SimpleNamespace(uid="owner", role="user"),
            run_id="legacy-completed",
        )

    assert error.value.status_code == 409
    assert error.value.detail == "历史研究任务为只读数据"


@pytest.mark.asyncio
async def test_delete_run_preserves_legacy_not_found_contract(monkeypatch) -> None:
    missing = HTTPException(status_code=404, detail="研究任务不存在")
    monkeypatch.setattr(service, "_require_run", AsyncMock(side_effect=missing))
    monkeypatch.setattr(service.asyncio, "to_thread", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as error:
        await service.delete_run(
            db=SimpleNamespace(),
            user=SimpleNamespace(uid="other", role="user"),
            run_id="foreign-draft",
        )

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_run_keeps_platform_run_behavior(monkeypatch) -> None:
    run = SimpleNamespace(id="platform-draft", owner_uid="owner", status="draft")
    db = SimpleNamespace(delete=AsyncMock(), commit=AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", audit)

    result = await service.delete_run(
        db=db,
        user=SimpleNamespace(uid="owner", role="user"),
        run_id="platform-draft",
    )

    assert result == {"deleted": True, "run_id": "platform-draft"}
    db.delete.assert_awaited_once_with(run)
    db.commit.assert_awaited_once()


def test_apply_deep_parent_metadata_recovers_legacy_session_binding() -> None:
    session = SimpleNamespace(
        payload={
            "capability_card_key": "cap-formal-1",
            "capability_name": "正式原卡",
        }
    )

    result = service._apply_deep_parent_metadata(
        [{"session_id": "thinking-1", "name": "深研卡"}],
        {"thinking-1": session},
    )

    assert result[0]["parent_capability_id"] == "cap-formal-1"
    assert result[0]["parent_card_key"] == "cap-formal-1"
    assert result[0]["parent_capability_name"] == "正式原卡"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected_owner_uid"),
    [("user", "user-1"), ("admin", None), ("superadmin", None)],
)
async def test_list_favorites_uses_owner_scope_except_for_global_admins(monkeypatch, role, expected_owner_uid) -> None:
    repository = SimpleNamespace(list_favorites=AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    result = await service.list_favorites(
        db=object(),
        user=SimpleNamespace(uid="user-1", role=role),
    )

    assert result["items"] == []
    repository.list_favorites.assert_awaited_once_with(expected_owner_uid, limit=2000)


@pytest.mark.asyncio
async def test_report_reads_legacy_markdown_after_permission_check(monkeypatch, tmp_path) -> None:
    run_id = "legacy-run"
    run_root = tmp_path / run_id
    run_root.mkdir()
    (run_root / "report.md").write_text("# 旧版研究报告\n\n正文", encoding="utf-8")
    run = SimpleNamespace(id=run_id, owner_uid="owner", payload={})
    require_run = AsyncMock(return_value=run)
    monkeypatch.setattr(service, "_require_run", require_run)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))

    result = await service.get_report(db=object(), user=SimpleNamespace(uid="owner", role="user"), run_id=run_id)

    assert result == "# 旧版研究报告\n\n正文"
    require_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_report_prefers_postfix_and_rejects_symlink(monkeypatch, tmp_path) -> None:
    run_id = "legacy-run"
    run_root = tmp_path / run_id
    run_root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("不应读取", encoding="utf-8")
    (run_root / "report-postfix.md").symlink_to(outside)
    (run_root / "report.md").write_text("安全报告", encoding="utf-8")
    monkeypatch.setattr(
        service,
        "_require_run",
        AsyncMock(return_value=SimpleNamespace(id=run_id, owner_uid="owner", payload={})),
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))

    assert (
        await service.get_report(db=object(), user=SimpleNamespace(uid="owner", role="user"), run_id=run_id)
        == "安全报告"
    )


@pytest.mark.asyncio
async def test_report_missing_returns_404(monkeypatch, tmp_path) -> None:
    run_id = "missing-run"
    monkeypatch.setattr(
        service,
        "_require_run",
        AsyncMock(return_value=SimpleNamespace(id=run_id, owner_uid="owner", payload={})),
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))

    with pytest.raises(HTTPException) as error:
        await service.get_report(db=object(), user=SimpleNamespace(uid="owner", role="user"), run_id=run_id)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_list_capabilities_projects_legacy_s6_artifacts(monkeypatch, tmp_path) -> None:
    run_id = "legacy-s6-run"
    run_root = tmp_path / run_id
    run_root.mkdir()
    cards = [
        {
            "type": "CapabilityImageItem",
            "payload": {
                "capability_id": f"cap-{index}",
                "hypothesis_id": f"hyp-{index}",
                "name": f"历史能力画像 {index}",
            },
        }
        for index in range(1, 3)
    ]
    (run_root / "domain.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in cards),
        encoding="utf-8",
    )
    run = SimpleNamespace(
        id=run_id,
        project_id="project-1",
        owner_uid="owner",
        payload={},
        to_dict=lambda: {"artifact_counts": {"capabilities": 2}},
    )
    repository = SimpleNamespace(
        list_capability_versions=AsyncMock(return_value=[]),
        list_runs_for_user=AsyncMock(return_value=[run]),
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    result = await service.list_capabilities(db=object(), user=SimpleNamespace(uid="owner", role="user"))

    assert [item["name"] for item in result] == ["历史能力画像 1", "历史能力画像 2"]
    assert all(item["status"] == "formal" for item in result)
    assert all(item["source"] == "formal_s6" for item in result)
    assert len({item["version_id"] for item in result}) == 2


@pytest.mark.asyncio
async def test_capability_version_endpoint_falls_back_to_legacy_artifact(monkeypatch, tmp_path) -> None:
    run_id = "legacy-capability-version-run"
    run_root = tmp_path / run_id
    run_root.mkdir()
    (run_root / "capability_images.json").write_text(
        json.dumps(
            [
                {
                    "capability_id": "cap-legacy",
                    "name": "旧任务正式能力画像",
                    "capability_portrait_modules": {"overview": "历史正文"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run = SimpleNamespace(
        id=run_id,
        project_id="project-1",
        owner_uid="owner",
        payload={},
    )
    repository = SimpleNamespace(
        list_capability_versions_for_run=AsyncMock(return_value=[]),
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    result = await service.list_capability_versions_for_run(
        db=object(), user=SimpleNamespace(uid="owner", role="user"), run_id=run_id
    )

    assert result["run_id"] == run_id
    assert len(result["versions"]) == 1
    assert result["versions"][0]["name"] == "旧任务正式能力画像"
    assert result["versions"][0]["snapshot"]["status"] == "formal"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("viewer_uid", "role", "thread_owner", "allowed"),
    [
        ("owner", "user", "owner", True),
        ("root", "superadmin", "owner", True),
        ("stranger", "user", "owner", False),
        ("root", "superadmin", "unrelated", False),
    ],
)
async def test_native_deep_session_reads_use_verified_owner(monkeypatch, viewer_uid, role, thread_owner, allowed):
    """全局管理员可查看他人终态，普通用户隔离且错绑线程始终拒绝。"""
    from fastapi import HTTPException
    from platform_core.repositories import agent_run_repository, conversation_repository
    from platform_core.services import equipment_deep_integration_service

    session = SimpleNamespace(
        id="session-1",
        owner_uid="owner",
        import_batch_id=None,
        payload={"runtime": "agent", "thread_id": "thread-1"},
        to_dict=lambda: {"session_id": "session-1"},
    )
    repo = SimpleNamespace(
        get_deep_session=AsyncMock(return_value=session),
        list_deep_jobs=AsyncMock(return_value=[]),
        list_deep_branches=AsyncMock(return_value=[]),
    )
    conversation = SimpleNamespace(
        get_conversation_by_thread_id=AsyncMock(return_value=SimpleNamespace(id=1, uid=thread_owner)),
        get_messages=AsyncMock(return_value=[]),
    )
    run = SimpleNamespace(
        id="run-1",
        request_id="request-1",
        status="completed",
        input_payload={},
        error_message=None,
        source="equipment_deep_research",
        to_dict=lambda: {"created_at": "2026-09-24", "updated_at": "2026-09-24"},
    )
    runs = SimpleNamespace(list_top_level_runs_by_origin=AsyncMock(return_value=[run]))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda db: repo)
    monkeypatch.setattr(conversation_repository, "ConversationRepository", lambda db: conversation)
    monkeypatch.setattr(agent_run_repository, "AgentRunRepository", lambda db: runs)
    monkeypatch.setattr(equipment_deep_integration_service, "get_session_research_context", AsyncMock(return_value={}))
    user = SimpleNamespace(uid=viewer_uid, role=role)
    if not allowed:
        with pytest.raises(HTTPException) as error:
            await service.get_deep_session(db=object(), user=user, session_id="session-1")
        assert error.value.status_code == 404
        runs.list_top_level_runs_by_origin.assert_not_called()
        return
    result = await service.get_deep_session(db=object(), user=user, session_id="session-1")
    assert result["jobs"][0]["status"] == "completed"
    runs.list_top_level_runs_by_origin.assert_awaited_once_with(
        uid="owner",
        source="equipment_deep_research",
        external_id="session-1",
        limit=50,
    )


@pytest.mark.asyncio
async def test_legacy_deep_session_projects_imported_branches(monkeypatch) -> None:
    """旧 SQLite 分支导入 PostgreSQL 后必须随会话详情返回。"""

    session = SimpleNamespace(
        id="legacy-session",
        owner_uid="owner",
        import_batch_id="workbench-user-sync",
        payload={"runtime": "legacy"},
        to_dict=lambda: {"session_id": "legacy-session"},
    )
    branch = SimpleNamespace(to_dict=lambda: {"branch_id": "legacy-session:main"})
    repository = SimpleNamespace(
        get_deep_session=AsyncMock(return_value=session),
        list_deep_messages=AsyncMock(return_value=[]),
        list_deep_jobs=AsyncMock(return_value=[]),
        list_deep_branches=AsyncMock(return_value=[branch]),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    result = await service.get_deep_session(
        db=object(),
        user=SimpleNamespace(uid="owner", role="user"),
        session_id="legacy-session",
    )

    assert result["branches"] == [{"branch_id": "legacy-session:main"}]
    repository.list_deep_branches.assert_awaited_once_with("legacy-session")


@pytest.mark.asyncio
async def test_deep_context_options_projects_cards_and_only_reference_candidates(monkeypatch, tmp_path) -> None:
    """正式能力画像留在主体选项，未成卡候选才进入参考武器。"""
    run_id = "run-context-options"
    run_root = tmp_path / run_id
    run_root.mkdir()
    events = [
        {
            "type": "TraceEvent",
            "payload": {
                "event_type": "winning_candidate_branch_created",
                "payload": {
                    "event_type": "winning_candidate_branch_created",
                    "hypothesis_id": "hyp-formal",
                    "title": "正式装备",
                    "primary_equipment_identity": "正式装备",
                    "concise_winning_summary": "已形成正式能力画像。",
                    "score": 0.8,
                },
            },
        },
        {
            "type": "TraceEvent",
            "payload": {
                "event_type": "winning_candidate_branch_created",
                "payload": {
                    "event_type": "winning_candidate_branch_created",
                    "hypothesis_id": "hyp-reference",
                    "title": "参考武器",
                    "primary_equipment_identity": "参考武器",
                    "equipment_form": ["区域拦截弹"],
                    "concise_winning_summary": "用于与正式装备进行横向比较。",
                    "score": 0.3,
                },
            },
        },
    ]
    (run_root / "trace.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events),
        encoding="utf-8",
    )
    run = SimpleNamespace(
        id=run_id,
        project_id="project-1",
        owner_uid="user-1",
        topic="体系研究",
        status="completed",
        payload={},
    )
    version = SimpleNamespace(
        id="version-1",
        run_id=run_id,
        snapshot={
            "name": "正式装备",
            "card_binding_id": "card-1",
            "hypothesis_id": "hyp-formal",
            "deep_capability_portrait": "概述：正式装备画像。",
        },
    )

    class Repository:
        def __init__(self, db):
            del db

        async def list_capability_versions_for_run(self, **kwargs):
            assert kwargs == {"owner_uid": "user-1", "run_id": run_id, "limit": 100}
            return [version]

    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setattr(service, "EquipmentResearchRepository", Repository)
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))

    result = await service.get_deep_context_options(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        run_id=run_id,
    )

    assert result["capability_cards"][0]["card_key"] == "card-1"
    assert result["selected_weapons"] == result["capability_cards"]
    assert result["reference_weapons"] == [
        {
            "hypothesis_id": "hyp-reference",
            "title": "参考武器",
            "primary_equipment_identity": "参考武器",
            "equipment_forms": ["区域拦截弹"],
            "overview": "用于与正式装备进行横向比较。",
            "score": 0.3,
        }
    ]


@pytest.mark.asyncio
async def test_create_favorite_resolves_server_card_and_persists_complete_snapshot(monkeypatch) -> None:
    """收藏正文只能来自当前用户可读 Run 的 PostgreSQL 能力版本。"""

    run = SimpleNamespace(
        id="run-1",
        project_id="project-1",
        owner_uid="user-1",
        topic="体系突防研究",
        status="completed",
    )
    version = SimpleNamespace(
        id="baseline-card-1",
        run_id="run-1",
        snapshot={
            "status": "formal",
            "card_binding_id": "card-1",
            "name": "裂棱散射眩扰弹",
            "capability_portrait_modules": {
                "overview": "概述正文",
                "technology_implementation": "技术正文",
                "operational_process": "流程正文",
                "capability_effects": "效果正文",
                "winning_logic": "机理正文",
            },
        },
        to_dict=lambda: {"version_id": "baseline-card-1", "run_id": "run-1"},
    )
    repository = SimpleNamespace(
        list_capability_versions_for_run=AsyncMock(return_value=[version]),
        find_favorite=AsyncMock(return_value=None),
        add_favorite=AsyncMock(),
        get_run=AsyncMock(return_value=run),
    )
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    audit = AsyncMock()
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", audit)

    result = await service.create_favorite(
        db=db,
        user=SimpleNamespace(uid="user-1", role="user"),
        run_id="run-1",
        card_identifiers={"card_key": "card-1", "capability_name": "客户端不能提交正文"},
    )

    saved = repository.add_favorite.await_args.args[0]
    assert saved.owner_uid == "user-1"
    assert saved.card_key == "card-1"
    assert saved.snapshot["name"] == "裂棱散射眩扰弹"
    assert saved.snapshot["source_topic"] == "体系突防研究"
    assert saved.snapshot["favorite_snapshot_version"] == "platform-v1"
    assert "客户端不能提交正文" not in str(saved.snapshot)
    assert result["created"] is True
    db.commit.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_favorite_keeps_snapshot_immutable_and_normalizes_tags(monkeypatch) -> None:
    snapshot = {"name": "不可变能力画像", "capability_portrait_modules": {"overview": "正文"}}
    item = SimpleNamespace(
        id="favorite-1",
        owner_uid="user-1",
        run_id=None,
        snapshot=snapshot,
        display_name="旧名称",
        note="",
        tags=[],
        updated_at=None,
    )
    repository = SimpleNamespace(get_run=AsyncMock(return_value=None))
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(service, "_require_favorite", AsyncMock(return_value=item))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", AsyncMock())
    monkeypatch.setattr(
        service,
        "_favorite_payload",
        AsyncMock(return_value={"favorite_id": "favorite-1", "snapshot": snapshot}),
    )

    await service.update_favorite(
        db=db,
        user=SimpleNamespace(uid="user-1", role="user"),
        favorite_id="favorite-1",
        changes={"display_name": "  新 名称  ", "tags": ["重点", "重点", "  待复核 "]},
    )

    assert item.snapshot is snapshot
    assert item.display_name == "新 名称"
    assert item.tags == ["重点", "待复核"]
    db.commit.assert_awaited_once()


def _artifact_test_run(run_id: str, *, payload=None, artifact_relpath: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        project_id="project-1",
        owner_uid="user-1",
        topic="复杂体系装备研究",
        research_route="new_winning_mechanism",
        status="completed",
        error="",
        payload=payload or {},
        artifact_relpath=artifact_relpath,
    )


@pytest.mark.asyncio
async def test_run_projection_endpoints_read_legacy_artifacts_and_remove_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    run_id = "run-legacy-projection"
    run_root = tmp_path / run_id
    run_root.mkdir()
    trace_rows = [
        {
            "type": "TraceEvent",
            "payload": {
                "event_id": "event-start",
                "event_type": "run_started",
                "actor": "orchestrator",
                "created_at": "2026-09-24T00:00:00Z",
                "summary": "研究启动",
                "payload": {
                    "agent_ids": ["weapon_equipment"],
                    "agent_models": {
                        "weapon_equipment": {
                            "model": "model-a",
                            "api_key": "must-not-leak",
                        }
                    },
                },
            },
        },
        {
            "type": "TraceEvent",
            "payload": {
                "event_id": "event-graph",
                "event_type": "winning_mission_graph_planned",
                "actor": "winning_swarm_controller",
                "summary": "动态任务图已规划",
                "payload": {
                    "graph": {
                        "agent_instances": [
                            {
                                "instance_id": "winning-agent-1",
                                "display_name": "弱信号侦察 Agent",
                                "mission_node": "S3",
                                "wave": 1,
                            }
                        ]
                    }
                },
            },
        },
        {
            "type": "TraceEvent",
            "payload": {
                "event_id": "event-agent-done",
                "event_type": "winning_agent_session_completed",
                "actor": "winning-agent-1",
                "summary": "动态 Agent 完成",
                "payload": {
                    "agent_instance_id": "winning-agent-1",
                    "mission_node": "S3",
                },
            },
        },
    ]
    (run_root / "trace.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in trace_rows) + "\n{bad-json}\n",
        encoding="utf-8",
    )
    domain_rows = [
        {
            "type": "EvidenceCard",
            "payload": {
                "evidence_id": "ev-1",
                "claim": "公开证据",
                "credentials": {"password": "must-not-leak"},
            },
        },
        {
            "type": "WinningMechanismInput",
            "payload": {"input_id": "input-1", "problem_frame": {"objective": "目标"}},
        },
        {
            "type": "WinningReasoningNode",
            "payload": {"reasoning_node_id": "node-1", "step": 1, "summary": "S1 完成"},
        },
        {
            "type": "WinningMechanismStageOutput",
            "payload": {"stage_id": "stage-1", "layer": "L1", "gate_passed": True},
        },
        {
            "type": "CapabilityImageItem",
            "payload": {
                "capability_id": "capability-1",
                "hypothesis_id": "hypothesis-1",
                "name": "正式能力画像",
            },
        },
    ]
    (run_root / "domain.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in domain_rows),
        encoding="utf-8",
    )
    (run_root / "round_summary.json").write_text(
        json.dumps(
            {
                "selected_agent_ids": ["weapon_equipment"],
                "discovery_blueprint": {"primary_branch": "A"},
                "winning_swarm": {"stop_reason": "quality_gate_passed"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run = _artifact_test_run(run_id)
    require_run = AsyncMock(return_value=run)
    monkeypatch.setattr(service, "_require_run", require_run)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))
    user = SimpleNamespace(uid="user-1", role="user")

    interactions = await service.get_run_interactions(db=object(), user=user, run_id=run_id, compact=False)
    evidence = await service.list_run_evidence(db=object(), user=user, run_id=run_id)
    winning = await service.get_run_winning_mechanism(db=object(), user=user, run_id=run_id)

    assert interactions["counts"]["events"] == 3
    assert interactions["workflow"]["discovery"]["primary_branch"] == "A"
    assert interactions["workflow"]["dynamic_agents"][0]["status"] == "completed"
    assert "must-not-leak" not in json.dumps(interactions, ensure_ascii=False)
    assert evidence == [{"evidence_id": "ev-1", "claim": "公开证据"}]
    assert "must-not-leak" not in json.dumps(evidence, ensure_ascii=False)
    assert winning["inputs"][0]["input_id"] == "input-1"
    assert winning["reasoning_nodes"][0]["step"] == 1
    assert winning["stages"][0]["gate_passed"] is True
    assert winning["swarm"]["stop_reason"] == "quality_gate_passed"
    assert winning["swarm"]["final_equipment_portfolio"][0]["name"] == "正式能力画像"
    assert require_run.await_count == 3


@pytest.mark.asyncio
async def test_run_evidence_uses_postgres_artifact_relpath_inside_project_workdir(
    monkeypatch,
    tmp_path,
) -> None:
    from platform_core.workspace import paths as workspace_paths

    run_id = "run-project-artifact"
    host_dir = tmp_path / "user-workdir"
    artifact_root = host_dir / "custom" / run_id
    artifact_root.mkdir(parents=True)
    (artifact_root / "domain.jsonl").write_text(
        json.dumps(
            {"type": "EvidenceCard", "payload": {"evidence_id": "project-ev", "claim": "项目产物"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    run = _artifact_test_run(
        run_id,
        payload={"workdir_path": "projects/research"},
        artifact_relpath=f"custom/{run_id}",
    )
    require_run = AsyncMock(return_value=run)
    monkeypatch.setattr(service, "_require_run", require_run)
    monkeypatch.setattr(workspace_paths, "user_workdir_host_dir", lambda uid, workdir: host_dir)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "missing-legacy"))

    result = await service.list_run_evidence(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        run_id=run_id,
    )

    assert result == [{"evidence_id": "project-ev", "claim": "项目产物"}]
    require_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_interactions_fall_back_to_postgres_events(monkeypatch, tmp_path) -> None:
    run_id = "run-postgres-events"
    run = _artifact_test_run(run_id, payload={"selected_agent_ids": ["combat_scenario"]})
    require_run = AsyncMock(return_value=run)
    repository = SimpleNamespace(
        list_events=AsyncMock(
            return_value=[
                SimpleNamespace(
                    sequence=7,
                    to_dict=lambda: {
                        "run_id": run_id,
                        "sequence": 7,
                        "event_type": "run_started",
                        "payload": {
                            "actor": "orchestrator",
                            "status": "researching",
                            "authorization": "Bearer must-not-leak",
                        },
                        "created_at": "2026-09-24T00:00:00Z",
                    },
                )
            ]
        )
    )
    monkeypatch.setattr(service, "_require_run", require_run)
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda db: repository)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path))

    result = await service.get_run_interactions(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        run_id=run_id,
        compact=False,
    )

    assert result["events"][0]["sequence"] == 7
    assert result["events"][0]["details"] == {"actor": "orchestrator", "status": "researching"}
    assert result["workflow"]["status"] == "completed"
    repository.list_events.assert_awaited_once_with(run_id, after_seq=0, limit=200)
    require_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_artifact_endpoints_authorize_before_reading(monkeypatch) -> None:
    denied = AsyncMock(side_effect=HTTPException(status_code=404, detail="研究任务不存在"))
    monkeypatch.setattr(service, "_require_run", denied)
    monkeypatch.setattr(
        service,
        "_load_run_trace_and_summary",
        lambda run: pytest.fail("权限校验前不得读取产物"),
    )
    monkeypatch.setattr(
        service,
        "_load_run_jsonl",
        lambda run, filename: pytest.fail("权限校验前不得读取产物"),
    )
    monkeypatch.setattr(
        service,
        "_load_run_domain_trace_and_summary",
        lambda run: pytest.fail("权限校验前不得读取产物"),
    )
    user = SimpleNamespace(uid="stranger", role="user")

    for call in (
        service.get_run_interactions(db=object(), user=user, run_id="run-secret"),
        service.list_run_evidence(db=object(), user=user, run_id="run-secret"),
        service.get_run_winning_mechanism(db=object(), user=user, run_id="run-secret"),
    ):
        with pytest.raises(HTTPException) as error:
            await call
        assert error.value.status_code == 404
    assert denied.await_count == 3


@pytest.mark.asyncio
async def test_run_evidence_rejects_symlink_and_artifact_path_escape(monkeypatch, tmp_path) -> None:
    from platform_core.workspace import paths as workspace_paths

    run_id = "run-artifact-escape"
    host_dir = tmp_path / "host"
    conventional_root = host_dir / "outputs" / "equipment-research" / run_id
    conventional_root.mkdir(parents=True)
    outside = tmp_path / "outside-domain.jsonl"
    outside.write_text(
        json.dumps({"type": "EvidenceCard", "payload": {"evidence_id": "outside"}}),
        encoding="utf-8",
    )
    (conventional_root / "domain.jsonl").symlink_to(outside)
    run = _artifact_test_run(
        run_id,
        payload={"workdir_path": "projects/research"},
        artifact_relpath="../outside",
    )
    monkeypatch.setattr(service, "_require_run", AsyncMock(return_value=run))
    monkeypatch.setattr(workspace_paths, "user_workdir_host_dir", lambda uid, workdir: host_dir)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "missing-legacy"))

    result = await service.list_run_evidence(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        run_id=run_id,
    )

    assert result == []


def _deep_session(*, runtime: str = "agent", status: str = "active") -> SimpleNamespace:
    session = SimpleNamespace(
        id="thinking-1",
        project_id="project-1",
        owner_uid="owner",
        run_id="run-1",
        import_batch_id=None,
        payload={
            "runtime": runtime,
            "thread_id": "thread-1" if runtime == "agent" else "",
            "title": "原标题",
            "status": status,
            "model_spec": "provider:model",
            "untouched": {"nested": True},
        },
        updated_at=None,
    )
    session.to_dict = lambda: {
        "session_id": session.id,
        "title": session.payload["title"],
        "status": session.payload["status"],
        "payload": dict(session.payload),
    }
    return session


@pytest.mark.asyncio
async def test_list_deep_sessions_reads_two_hundred_rows(monkeypatch) -> None:
    repository = SimpleNamespace(list_deep_sessions=AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    assert (
        await service.list_deep_sessions(
            db=object(),
            user=SimpleNamespace(uid="owner", role="user"),
        )
        == []
    )
    repository.list_deep_sessions.assert_awaited_once_with(
        "owner",
        limit=200,
        include_legacy=True,
    )


@pytest.mark.asyncio
async def test_create_deep_session_snapshots_parent_query(monkeypatch) -> None:
    project = SimpleNamespace(id="project-1", uid="owner", status="active")
    run = SimpleNamespace(
        id="run-1",
        project_id=project.id,
        owner_uid="owner",
        topic="母任务 Query",
        payload={"supplemental_information": "背景与约束"},
    )
    feedback = SimpleNamespace(
        id="feedback-1",
        run_id=run.id,
        owner_uid="owner",
        feedback={
            "status": "active",
            "capability_id": "capability-1",
            "capability_name": "低空拦截装备",
            "comment": "技术实现缺少抗干扰闭环",
            "verdict": "needs_revision",
            "expert_weighted_score": 0.76,
            "rubric_feedback": {"feasibility": "补充工程成熟度分级"},
        },
    )
    repository = SimpleNamespace(
        add_deep_session=AsyncMock(),
        get_expert_feedback=AsyncMock(return_value=feedback),
    )
    conversations = SimpleNamespace(add_conversation=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    owner = SimpleNamespace(uid="owner", role="user")

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
    resolve_agent = AsyncMock(
        return_value=SimpleNamespace(
            slug="weapon-equipment-scheme",
            name="武器装备研究方案",
        )
    )
    monkeypatch.setattr(
        "platform_core.services.equipment_deep_integration_service.resolve_deep_agent",
        resolve_agent,
    )

    await service.create_deep_session(
        db=db,
        user=owner,
        project_id=project.id,
        run_id=run.id,
        source_feedback_id=feedback.id,
        research_section="装备与技术实现",
    )

    created = repository.add_deep_session.await_args.args[0]
    assert created.payload["query_snapshot"] == ["母任务 Query", "背景与约束"]
    assert created.payload["topic"] == "母任务 Query"
    assert created.payload["source_feedback_id"] == feedback.id
    assert created.payload["source_feedback_snapshot"]["comment"] == "技术实现缺少抗干扰闭环"
    assert created.payload["agent_slug"] == "weapon-equipment-scheme"
    resolve_agent.assert_awaited_once_with(
        db=db,
        user=owner,
        requested_slug="weapon-equipment-scheme",
    )


@pytest.mark.asyncio
async def test_create_new_weapon_session_defaults_to_capability_portrait_agent(monkeypatch) -> None:
    project = SimpleNamespace(id="project-1", uid="owner", status="active")
    repository = SimpleNamespace(add_deep_session=AsyncMock())
    conversations = SimpleNamespace(add_conversation=AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    owner = SimpleNamespace(uid="owner", role="user")

    monkeypatch.setattr(service, "_require_project", AsyncMock(return_value=project))
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
    resolve_agent = AsyncMock(
        return_value=SimpleNamespace(
            slug="equipment-capability-portrait",
            name="武器装备能力画像",
        )
    )
    monkeypatch.setattr(
        "platform_core.services.equipment_deep_integration_service.resolve_deep_agent",
        resolve_agent,
    )

    await service.create_deep_session(
        db=db,
        user=owner,
        project_id=project.id,
        topic="发散新的低空防御装备并形成能力画像",
        research_mode="new_weapon_diverge",
    )

    created = repository.add_deep_session.await_args.args[0]
    assert created.payload["research_mode"] == "new_weapon_diverge"
    assert created.payload["agent_slug"] == "equipment-capability-portrait"
    assert created.payload["agent_name"] == "武器装备能力画像"
    resolve_agent.assert_awaited_once_with(
        db=db,
        user=owner,
        requested_slug="equipment-capability-portrait",
    )


@pytest.mark.asyncio
async def test_update_deep_session_locks_and_syncs_native_conversation(monkeypatch) -> None:
    session = _deep_session()
    conversation = SimpleNamespace(uid="owner", title="原标题", status="active", updated_at=None)
    repository = SimpleNamespace(lock_deep_session=AsyncMock(return_value=session))
    conversations = SimpleNamespace(lock_conversation_by_thread_id=AsyncMock(return_value=conversation))
    db = SimpleNamespace(commit=AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(
        "platform_core.repositories.conversation_repository.ConversationRepository",
        lambda _db: conversations,
    )
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", audit)

    result = await service.update_deep_session(
        db=db,
        user=SimpleNamespace(uid="owner", role="user"),
        session_id=session.id,
        changes={"title": "  新标题  ", "archived": True},
    )

    assert result["session"]["title"] == "新标题"
    assert result["session"]["status"] == "archived"
    assert session.payload["untouched"] == {"nested": True}
    assert conversation.title == "新标题"
    assert conversation.status == "archived"
    repository.lock_deep_session.assert_awaited_once_with(session.id)
    conversations.lock_conversation_by_thread_id.assert_awaited_once_with("thread-1")
    db.commit.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_deep_session_rejects_mismatched_conversation_owner(monkeypatch) -> None:
    session = _deep_session()
    repository = SimpleNamespace(lock_deep_session=AsyncMock(return_value=session))
    conversations = SimpleNamespace(
        lock_conversation_by_thread_id=AsyncMock(return_value=SimpleNamespace(uid="another-user"))
    )
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(
        "platform_core.repositories.conversation_repository.ConversationRepository",
        lambda _db: conversations,
    )

    with pytest.raises(HTTPException) as error:
        await service.update_deep_session(
            db=db,
            user=SimpleNamespace(uid="owner", role="user"),
            session_id=session.id,
            changes={"title": "新标题"},
        )

    assert error.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_archived_deep_session_rejects_send_and_fork(monkeypatch) -> None:
    session = _deep_session(status="archived")
    require = AsyncMock(return_value=session)
    execute_as = AsyncMock()
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: SimpleNamespace())
    monkeypatch.setattr(service, "_require_deep_session", require)
    monkeypatch.setattr(service, "_deep_execution_user", execute_as)

    with pytest.raises(HTTPException) as send_error:
        await service.send_deep_message(
            db=object(),
            user=SimpleNamespace(uid="owner", role="user"),
            session_id=session.id,
            content="继续研究",
        )
    with pytest.raises(HTTPException) as fork_error:
        await service.fork_deep_session(
            db=object(),
            user=SimpleNamespace(uid="owner", role="user"),
            session_id=session.id,
        )

    assert send_error.value.status_code == 409
    assert fork_error.value.status_code == 409
    assert require.await_count == 2
    execute_as.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_deep_session_rejects_active_equipment_job(monkeypatch) -> None:
    session = _deep_session(runtime="legacy")
    job = SimpleNamespace(payload={}, status="running")
    repository = SimpleNamespace(
        lock_deep_session=AsyncMock(return_value=session),
        list_nonterminal_deep_jobs=AsyncMock(return_value=[job]),
        delete_deep_session=AsyncMock(),
    )
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    with pytest.raises(HTTPException) as error:
        await service.delete_deep_session(
            db=db,
            user=SimpleNamespace(uid="owner", role="user"),
            session_id=session.id,
        )

    assert error.value.status_code == 409
    repository.delete_deep_session.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_deep_session_rejects_active_native_run(monkeypatch) -> None:
    from platform_core.repositories import agent_run_repository

    session = _deep_session()
    conversation = SimpleNamespace(uid="owner", status="active", updated_at=None)
    repository = SimpleNamespace(
        lock_deep_session=AsyncMock(return_value=session),
        list_nonterminal_deep_jobs=AsyncMock(return_value=[]),
        delete_deep_session=AsyncMock(),
    )
    conversations = SimpleNamespace(lock_conversation_by_thread_id=AsyncMock(return_value=conversation))
    native_run = SimpleNamespace(
        id="agent-run-1",
        request_id="request-1",
        status="running",
        runtime_cleanup_pending=False,
    )
    runs = SimpleNamespace(list_top_level_runs_by_origin=AsyncMock(return_value=[native_run]))
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(
        "platform_core.repositories.conversation_repository.ConversationRepository",
        lambda _db: conversations,
    )
    monkeypatch.setattr(agent_run_repository, "AgentRunRepository", lambda _db: runs)

    with pytest.raises(HTTPException) as error:
        await service.delete_deep_session(
            db=db,
            user=SimpleNamespace(uid="owner", role="user"),
            session_id=session.id,
        )

    assert error.value.status_code == 409
    repository.delete_deep_session.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_deep_session_soft_deletes_conversation_in_one_transaction(monkeypatch) -> None:
    from platform_core.repositories import agent_run_repository

    session = _deep_session()
    conversation = SimpleNamespace(uid="owner", status="active", updated_at=None)
    stale_native_job = SimpleNamespace(
        payload={"runtime": "agent", "request_id": "request-1"},
        status="queued",
    )
    repository = SimpleNamespace(
        lock_deep_session=AsyncMock(return_value=session),
        list_nonterminal_deep_jobs=AsyncMock(return_value=[stale_native_job]),
        delete_deep_session=AsyncMock(),
    )
    conversations = SimpleNamespace(lock_conversation_by_thread_id=AsyncMock(return_value=conversation))
    native_run = SimpleNamespace(
        id="agent-run-1",
        request_id="request-1",
        status="completed",
        runtime_cleanup_pending=False,
    )
    runs = SimpleNamespace(list_top_level_runs_by_origin=AsyncMock(return_value=[native_run]))
    db = SimpleNamespace(commit=AsyncMock())
    audit = AsyncMock()
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(
        "platform_core.repositories.conversation_repository.ConversationRepository",
        lambda _db: conversations,
    )
    monkeypatch.setattr(agent_run_repository, "AgentRunRepository", lambda _db: runs)
    monkeypatch.setattr(service, "audit_superadmin_personal_resource_write", audit)

    result = await service.delete_deep_session(
        db=db,
        user=SimpleNamespace(uid="owner", role="user"),
        session_id=session.id,
    )

    assert result == {"deleted": True, "session_id": session.id}
    assert conversation.status == "deleted"
    repository.delete_deep_session.assert_awaited_once_with(session.id)
    db.commit.assert_awaited_once()
    audit.assert_awaited_once()
