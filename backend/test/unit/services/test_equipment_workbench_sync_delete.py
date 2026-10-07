"""旧工作台草稿删除兼容层测试。"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from platform_core.services import equipment_workbench_sync as service


def _create_runs(path, rows: list[tuple[str, dict]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO runs VALUES (?, ?)",
            [(run_id, json.dumps(payload)) for run_id, payload in rows],
        )


def _exists(path, run_id: str) -> bool:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone() is not None


def test_owner_can_delete_legacy_draft(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    _create_runs(
        app_db,
        [("draft-1", {"status": "draft", "workspace_id": "owner"})],
    )
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")
    monkeypatch.setenv(
        "EQUIPMENT_DR_QUERY_LIBRARY_DB", f"sqlite:///{tmp_path / 'missing-query.db'}"
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))

    result = service.delete_workbench_draft(
        "draft-1", SimpleNamespace(uid="owner", role="user")
    )

    assert result == {
        "deleted": True,
        "run_id": "draft-1",
        "status": "draft",
        "workspace_id": "owner",
        "owner_uid": "owner",
    }
    assert not _exists(app_db, "draft-1")
    assert service.load_workbench_snapshot()["runs"] == []


def test_foreign_user_cannot_discover_or_delete_legacy_draft(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    _create_runs(
        app_db,
        [("draft-1", {"status": "draft", "workspace_id": "owner"})],
    )
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")

    result = service.delete_workbench_draft(
        "draft-1", SimpleNamespace(uid="other", role="user")
    )

    assert result is None
    assert _exists(app_db, "draft-1")


def test_global_admin_can_delete_legacy_draft(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    _create_runs(
        app_db,
        [("draft-1", {"status": "draft", "workspace_id": "owner"})],
    )
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")

    result = service.delete_workbench_draft(
        "draft-1", SimpleNamespace(uid="admin", role="superadmin")
    )

    assert result is not None and result["deleted"] is True
    assert result["owner_uid"] == "owner"
    assert not _exists(app_db, "draft-1")


def test_completed_legacy_run_remains_read_only(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    _create_runs(
        app_db,
        [("completed-1", {"status": "completed", "workspace_id": "owner"})],
    )
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")

    result = service.delete_workbench_draft(
        "completed-1", SimpleNamespace(uid="owner", role="user")
    )

    assert result is not None and result["deleted"] is False
    assert result["status"] == "completed"
    assert _exists(app_db, "completed-1")


def test_missing_legacy_runs_table_behaves_as_not_found(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    sqlite3.connect(app_db).close()
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")

    assert (
        service.delete_workbench_draft(
            "missing", SimpleNamespace(uid="owner", role="user")
        )
        is None
    )
