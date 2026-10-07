"""验证租户共享和历史快照的个人数据边界。"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from equipment_deep_research.domain.platform_identity import PlatformIdentity
from platform_core.permissions import ResourcePermission, resolve_personal_resource_permission
from platform_core.permissions.resource_permission import normalize_permission_config, scope_matches
from platform_core.repositories.equipment_research_repository import _visible_clause
from platform_core.services.equipment_workbench_sync import user_workbench_snapshot
from platform_core.storage.postgres.models_equipment import EquipmentResearchRun


def test_tenant_scope_and_manage_subset():
    scope = {"access_level": "tenant", "tenant_ids": ["a"]}
    assert scope_matches({"tenant_id": "a"}, scope)
    assert not scope_matches({"tenant_id": "b"}, scope)
    with pytest.raises(ValueError):
        normalize_permission_config(
            {"version": 2, "read_scope": scope, "manage_scope": {"access_level": "tenant", "tenant_ids": ["b"]}},
            strict=True,
        )


def test_legacy_marker_grants_shared_read_visibility():
    clause = str(
        _visible_clause(EquipmentResearchRun, "alice", include_legacy=True).compile(dialect=postgresql.dialect())
    )
    assert "owner_uid" in clause
    assert "legacy_source_id IS NOT NULL" in clause
    assert "import_batch_id" in clause


def test_portal_counts_and_history_do_not_leak():
    snapshot = {
        "runs": [
            {"run_id": "a", "payload": {"workspace_id": "alice"}, "status": "completed", "capability_count": 2},
            {"run_id": "b", "payload": {"workspace_id": "bob"}, "capability_count": 100},
            {"run_id": "legacy", "payload": {}},
        ],
        "queries": [
            {"query_id": "a", "owner_uid": "alice"},
            {"query_id": "b", "owner_uid": "bob"},
            {"query_id": "legacy", "owner_uid": ""},
        ],
        "deep_sessions": [{"parent_run_id": "a"}, {"parent_run_id": "b"}],
        "favorites": [{"owner_id": "alice"}, {"owner_id": "workspace"}],
    }
    result = user_workbench_snapshot(snapshot, SimpleNamespace(uid="alice", role="user"))
    assert [r["run_id"] for r in result["runs"]] == ["a", "legacy"]
    assert [q["query_id"] for q in result["queries"]] == ["a", "legacy"]
    assert result["stats"] == {"runs": 2, "queries": 2, "completed_runs": 1, "deep_sessions": 1, "capabilities": 2}
    assert len(result["favorites"]) == 1
    assert user_workbench_snapshot(snapshot, SimpleNamespace(uid="admin", role="admin")) is snapshot
    assert user_workbench_snapshot(snapshot, SimpleNamespace(uid="root", role="superadmin")) is snapshot


def test_personal_resources_are_owner_only_except_for_global_admins():
    owner = SimpleNamespace(uid="alice", role="user")
    tenant_admin = SimpleNamespace(uid="admin", role="admin")
    root = SimpleNamespace(uid="root", role="superadmin")

    assert resolve_personal_resource_permission(owner, "alice") == ResourcePermission.MANAGE
    assert (
        resolve_personal_resource_permission(owner, "legacy-owner", shared_legacy=True)
        == ResourcePermission.READ
    )
    assert resolve_personal_resource_permission(tenant_admin, "alice") == ResourcePermission.MANAGE
    assert resolve_personal_resource_permission(root, "alice") == ResourcePermission.MANAGE

    run = SimpleNamespace(workspace_id="alice", tenant_id="tenant-a")
    assert PlatformIdentity("bob", "tenant-a").can_mutate_run(run) is False
    assert PlatformIdentity("root", "other", True).can_mutate_run(run) is True
    assert PlatformIdentity("root", "other", True).can_mutate_owner("alice") is True
