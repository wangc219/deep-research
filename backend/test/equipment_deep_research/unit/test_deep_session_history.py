from __future__ import annotations

import json
from pathlib import Path

from equipment_deep_research.application.dto import RunView
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunRepository


def _repo(tmp_path: Path) -> SqlRunRepository:
    return SqlRunRepository(create_database_engine(f"sqlite:///{tmp_path / 'history.db'}"))


def test_list_deep_sessions_history_groups_by_query_snapshot(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for run_id, topic in (("run-a", "低空突防"), ("run-b", "远海拒止")):
        repo.save(
            RunView(
                run_id=run_id,
                topic=topic,
                research_route="winning",
                selected_agent_ids=[],
                max_rounds=1,
                created_by="analyst",
            )
        )
    repo.create_deep_session(
        session_id="session-a1",
        parent_run_id="run-a",
        kind="capability-followup",
        title="低空突防追问",
        card_binding_id="bind-a",
        hypothesis_id="hyp-a",
        query_snapshot={"query": "低空突防", "context": {"capability_name": "穿梭无人机"}},
    )
    repo.create_deep_session(
        session_id="session-a2",
        parent_run_id="run-a",
        kind="reference-research",
        title="参考武器深研",
        card_binding_id="bind-a2",
        hypothesis_id="hyp-a2",
        query_snapshot={"query": "低空突防", "context": {"capability_name": "参考拦截弹"}},
    )
    repo.create_deep_session(
        session_id="session-b1",
        parent_run_id="run-b",
        kind="deep-thinking",
        title="远海拒止发散",
        query_snapshot={"query": "远海拒止", "context": {"capability_name": "无人艇群"}},
    )

    rows = repo.list_deep_sessions_history(limit=50)
    assert len(rows) == 3
    by_id = {item["session_id"]: item for item in rows}
    assert by_id["session-a1"]["query"] == "低空突防"
    assert by_id["session-a1"]["run_topic"] == "低空突防"
    assert by_id["session-a1"]["capability_name"] == "穿梭无人机"
    assert by_id["session-b1"]["parent_run_id"] == "run-b"
    assert by_id["session-a1"]["query_group_key"] == by_id["session-a2"]["query_group_key"]
    assert by_id["session-a1"]["query_group_key"] != by_id["session-b1"]["query_group_key"]


def test_history_filters_scope_before_limit_and_empty_scope_is_not_wildcard(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    for session_id, scope in (
        ("session-unscoped", {}),
        ("session-tenant-a", {"tenant_id": "tenant-a", "workspace_id": "workspace-a"}),
        ("session-tenant-b", {"tenant_id": "tenant-b", "workspace_id": "workspace-b"}),
    ):
        repo.create_deep_session(
            session_id=session_id,
            parent_run_id=f"run-{session_id}",
            kind="deep-thinking",
            scope=scope,
        )

    # tenant-b is newest and would consume the SQL limit if filtering happened
    # after pagination. The tenant-a row must still be returned.
    tenant_a = repo.list_deep_sessions_history(
        limit=1,
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    )
    assert [item["session_id"] for item in tenant_a] == ["session-tenant-a"]

    # A scoped request cannot inherit an old unscoped row, and an empty scope
    # can only read legacy/unscoped history rather than all tenants.
    assert [
        item["session_id"]
        for item in repo.list_deep_sessions_history(limit=10, tenant_id="tenant-a")
    ] == ["session-tenant-a"]
    assert [
        item["session_id"]
        for item in repo.list_deep_sessions_history(limit=10)
    ] == ["session-unscoped"]
