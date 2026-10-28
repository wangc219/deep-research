"""列表精简投影保留权限、计数和卡片正文。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest

from platform_core.services import equipment_research_service as service
from platform_core.storage.postgres.models_equipment import EquipmentResearchRun


@pytest.mark.asyncio
async def test_compact_runs_exclude_large_summary_without_mutating_detail(monkeypatch):
    """列表不下载研究正文，详情和列表的权限及统计保持一致。"""
    run = EquipmentResearchRun(
        id="run-1",
        project_id="project-1",
        owner_uid="owner",
        topic="研究任务",
        research_route="auto",
        status="completed",
        readonly=1,
        legacy_source_id="legacy-1",
        payload={
            "model_spec": "provider/model",
            "summary": {"body": "研究正文" * 10000},
            "artifact_counts": {"capabilities": 7, "sources": 9},
            "result": {"deep_session_count": 2, "report_available": True, "body": "正文" * 1000},
            "execution": {"mode": "real"},
            "supplemental_information": "背景约束",
        },
    )
    repository = SimpleNamespace(list_runs_for_user=AsyncMock(return_value=[run]))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    user = SimpleNamespace(uid="owner", role="user")
    full = (await service.list_runs(db=object(), user=user))[0]
    compact = (await service.list_runs(db=object(), user=user, compact=True))[0]
    for key in (
        "run_id",
        "status",
        "readonly",
        "historical_snapshot",
        "artifact_counts",
        "execution",
        "supplemental_information",
    ):
        assert compact[key] == full[key]
    assert compact["readonly"] is False
    assert compact["payload"] == {"model_spec": "provider/model"}
    assert compact["result"] == {"deep_session_count": 2, "report_available": True}
    assert len(json.dumps(compact)) < len(json.dumps(full)) / 10
    assert run.payload["summary"]["body"] == "研究正文" * 10000
    assert (
        service._run_payload_for_user(run, SimpleNamespace(uid="other", role="user"), compact=True)["readonly"] is True
    )


@pytest.mark.asyncio
async def test_compact_capabilities_merge_snapshot_fields_with_top_level_precedence(monkeypatch):
    """旧卡片正文仅传一次，同时保留快照独有字段和当前版本元数据。"""
    snapshot = {"name": "旧标题", "capability_image": "完整能力正文", "hypothesis_id": "hyp-1"}
    card = {"id": "card-1", "run_id": "run-1", "snapshot": snapshot, "name": "当前标题", "status": "formal"}
    repository = SimpleNamespace(
        list_capability_versions=AsyncMock(
            return_value=[SimpleNamespace(id="version-1", run_id="run-1", snapshot=card)]
        ),
        list_runs_for_user=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)
    monkeypatch.setattr(service, "_enrich_deep_parent_metadata", AsyncMock(side_effect=lambda _repo, rows: rows))
    user = SimpleNamespace(uid="owner", role="user")
    full = await service.list_capabilities(db=object(), user=user)
    compact = await service.list_capabilities(db=object(), user=user, compact=True)
    assert compact == [{key: value for key, value in (snapshot | full[0]).items() if key != "snapshot"}]
    assert compact[0]["name"] == "当前标题"
    assert compact[0]["capability_image"] == "完整能力正文"
    assert "snapshot" in full[0]
