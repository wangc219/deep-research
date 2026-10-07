"""旧工作台深研账本导入 PostgreSQL 的兼容性测试。"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from platform_core.services import equipment_workbench_sync as service
from platform_core.storage.postgres.models_equipment import (
    EquipmentDeepBranch,
    EquipmentDeepJob,
    EquipmentDeepMessage,
    EquipmentDeepSession,
    EquipmentDeepSteer,
    EquipmentLegacyImportBatch,
    EquipmentQuery,
    EquipmentResearchRun,
)


def _create_legacy_deep_db(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO runs VALUES (?, ?)",
            (
                "run-1",
                json.dumps(
                    {
                        "topic": "有效 Query",
                        "status": "completed",
                        "workspace_id": "owner",
                    }
                ),
            ),
        )
        conn.execute(
            """
            CREATE TABLE deep_sessions (
                session_id TEXT PRIMARY KEY, parent_run_id TEXT, title TEXT,
                scope_json TEXT, query_snapshot_json TEXT, working_memory_json TEXT,
                status TEXT, created_at TEXT, updated_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO deep_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "session-1",
                    "run-1",
                    "旧深研",
                    '{"workspace_id":"owner"}',
                    '{"query":"有效 Query"}',
                    '{"current_objective":"验证"}',
                    "active",
                    "2025-01-01T00:00:00Z",
                    "2025-01-02T00:00:00Z",
                ),
                (
                    "session-orphan-run",
                    "missing-run",
                    "孤儿会话",
                    "{}",
                    "{}",
                    "{}",
                    "active",
                    "2025-01-01T00:00:00Z",
                    "2025-01-02T00:00:00Z",
                ),
            ],
        )
        conn.execute(
            """
            CREATE TABLE deep_messages (
                message_id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
                sequence INTEGER, artifact_refs_json TEXT, version_refs_json TEXT,
                metadata_json TEXT, created_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO deep_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "message-1",
                    "session-1",
                    "user",
                    "问题",
                    1,
                    '[{"artifact_id":"a-1"}]',
                    '["v-1"]',
                    '{"visible":true}',
                    "2025-01-01T00:01:00Z",
                ),
                (
                    "message-orphan",
                    "missing-session",
                    "assistant",
                    "孤儿",
                    2,
                    "[]",
                    "[]",
                    "{}",
                    "2025-01-01T00:02:00Z",
                ),
            ],
        )
        conn.execute(
            """
            CREATE TABLE deep_jobs (
                job_id TEXT PRIMARY KEY, session_id TEXT, status TEXT, stage TEXT,
                payload_json TEXT, checkpoint_json TEXT, error TEXT,
                created_at TEXT, updated_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO deep_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "job-1",
                    "session-1",
                    "completed",
                    "synthesis",
                    '{"model_spec":"legacy-model"}',
                    '{"cursor":3}',
                    "",
                    "2025-01-01T00:01:00Z",
                    "2025-01-01T00:03:00Z",
                ),
                (
                    "job-orphan",
                    "missing-session",
                    "queued",
                    "queued",
                    "{}",
                    "{}",
                    "",
                    "2025-01-01T00:01:00Z",
                    "2025-01-01T00:03:00Z",
                ),
            ],
        )
        conn.execute(
            """
            CREATE TABLE deep_branches (
                branch_id TEXT PRIMARY KEY, session_id TEXT, title TEXT,
                status TEXT, created_at TEXT, updated_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO deep_branches VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "session-1:main",
                    "session-1",
                    "主线",
                    "active",
                    "2025-01-01T00:00:00Z",
                    "2025-01-01T00:00:00Z",
                ),
                (
                    "missing:main",
                    "missing-session",
                    "孤儿",
                    "active",
                    "2025-01-01T00:00:00Z",
                    "2025-01-01T00:00:00Z",
                ),
            ],
        )
        conn.execute(
            """
            CREATE TABLE deep_steers (
                steer_id TEXT PRIMARY KEY, session_id TEXT, job_id TEXT,
                mode TEXT, content TEXT, status TEXT, created_at TEXT, updated_at TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO deep_steers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "steer-1",
                    "session-1",
                    "job-1",
                    "next",
                    "继续",
                    "applied",
                    "2025-01-01T00:02:00Z",
                    "2025-01-01T00:03:00Z",
                ),
                (
                    "steer-orphan-job",
                    "session-1",
                    "missing-job",
                    "next",
                    "孤儿",
                    "pending",
                    "2025-01-01T00:02:00Z",
                    "2025-01-01T00:03:00Z",
                ),
            ],
        )


def test_load_workbench_snapshot_decodes_deep_ledger_and_filters_orphans(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    _create_legacy_deep_db(app_db)
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")
    monkeypatch.setenv("EQUIPMENT_DR_QUERY_LIBRARY_DB", f"sqlite:///{tmp_path / 'missing.db'}")
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))

    snapshot = service.load_workbench_snapshot()

    session = snapshot["deep_sessions"][0]
    assert session["scope"] == {"workspace_id": "owner"}
    assert session["query_snapshot"] == {"query": "有效 Query"}
    assert session["working_memory"] == {"current_objective": "验证"}
    assert snapshot["deep_messages"][0]["artifact_refs"] == [{"artifact_id": "a-1"}]
    assert snapshot["deep_messages"][0]["version_refs"] == ["v-1"]
    assert snapshot["deep_messages"][0]["metadata"] == {"visible": True}
    assert snapshot["deep_jobs"][0]["payload"] == {"model_spec": "legacy-model"}
    assert snapshot["deep_jobs"][0]["checkpoint"] == {"cursor": 3}
    assert {row["message_id"] for row in snapshot["deep_messages"]} == {"message-1"}
    assert {row["job_id"] for row in snapshot["deep_jobs"]} == {"job-1"}
    assert {row["branch_id"] for row in snapshot["deep_branches"]} == {"session-1:main"}
    assert {row["steer_id"] for row in snapshot["deep_steers"]} == {"steer-1"}

    visible = service.user_workbench_snapshot(snapshot, SimpleNamespace(uid="owner", role="user"))
    assert {row["session_id"] for row in visible["deep_sessions"]} == {"session-1"}
    assert {row["message_id"] for row in visible["deep_messages"]} == {"message-1"}


def test_load_workbench_snapshot_tolerates_missing_optional_deep_tables(monkeypatch, tmp_path) -> None:
    app_db = tmp_path / "application.db"
    with sqlite3.connect(app_db) as conn:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO runs VALUES (?, ?)",
            ("run-1", json.dumps({"topic": "旧 Query", "workspace_id": "owner"})),
        )
        conn.execute(
            """
            CREATE TABLE deep_sessions (
                session_id TEXT PRIMARY KEY, parent_run_id TEXT, title TEXT,
                created_at TEXT, updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO deep_sessions VALUES (?, ?, ?, ?, ?)",
            (
                "session-1",
                "run-1",
                "旧会话",
                "2025-01-01T00:00:00Z",
                "2025-01-01T00:00:00Z",
            ),
        )
    monkeypatch.setenv("EQUIPMENT_DR_APP_DB", f"sqlite:///{app_db}")
    monkeypatch.setenv("EQUIPMENT_DR_QUERY_LIBRARY_DB", f"sqlite:///{tmp_path / 'missing.db'}")
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))

    snapshot = service.load_workbench_snapshot()

    assert [row["session_id"] for row in snapshot["deep_sessions"]] == ["session-1"]
    assert snapshot["deep_messages"] == []
    assert snapshot["deep_jobs"] == []
    assert snapshot["deep_branches"] == []
    assert snapshot["deep_steers"] == []


class _FakeDb:
    def __init__(self) -> None:
        self.rows: dict[tuple[type, str], object] = {}

    async def get(self, model, row_id):
        return self.rows.get((model, str(row_id)))

    def add(self, row) -> None:
        self.rows[(type(row), str(row.id))] = row

    async def flush(self) -> None:
        return None


class _FakeEquipmentRepository:
    def __init__(self, db: _FakeDb) -> None:
        self.db = db

    async def get_run(self, run_id):
        return await self.db.get(EquipmentResearchRun, run_id)

    async def add_run(self, row):
        self.db.add(row)
        return row

    async def get_query(self, query_id):
        return await self.db.get(EquipmentQuery, query_id)

    async def get_query_by_fingerprint(self, fingerprint):
        del fingerprint
        return None

    async def add_query(self, row):
        self.db.add(row)
        return row

    async def get_deep_session(self, session_id):
        return await self.db.get(EquipmentDeepSession, session_id)

    async def add_deep_session(self, row):
        self.db.add(row)
        return row


def _deep_snapshot(*, title: str, job_status: str) -> dict:
    return {
        "runs": [
            {
                "run_id": "run-1",
                "topic": "有效 Query",
                "status": "completed",
                "payload": {"workspace_id": "owner"},
            }
        ],
        "queries": [],
        "deep_sessions": [
            {
                "session_id": "session-1",
                "parent_run_id": "run-1",
                "title": title,
                "status": "active",
                "scope": {"workspace_id": "owner"},
            }
        ],
        "deep_messages": [
            {
                "message_id": "message-1",
                "session_id": "session-1",
                "role": "user",
                "content": "问题",
                "sequence": 1,
            },
            {
                "message_id": "message-orphan",
                "session_id": "missing-session",
                "role": "assistant",
                "content": "孤儿",
            },
        ],
        "deep_jobs": [
            {
                "job_id": "job-1",
                "session_id": "session-1",
                "status": job_status,
                "payload": {"model_spec": "legacy-model"},
            }
        ],
        "deep_branches": [
            {
                "branch_id": "session-1:main",
                "session_id": "session-1",
                "title": "主线",
            }
        ],
        "deep_steers": [
            {
                "steer_id": "steer-1",
                "session_id": "session-1",
                "job_id": "job-1",
                "content": "继续",
            }
        ],
        "favorites": [],
        "capability_versions": [],
    }


@pytest.mark.asyncio
async def test_deep_import_is_idempotent_preserves_pg_edits_and_tombstones_deletes(
    monkeypatch,
) -> None:
    db = _FakeDb()
    monkeypatch.setattr(
        service,
        "EquipmentResearchRepository",
        _FakeEquipmentRepository,
    )
    monkeypatch.setattr(
        service,
        "_ensure_sync_project",
        AsyncMock(return_value=SimpleNamespace(id="project-1")),
    )
    user = SimpleNamespace(uid="owner", role="user")

    await service.persist_workbench_snapshot(db, user, _deep_snapshot(title="旧标题", job_status="queued"))

    session = db.rows[(EquipmentDeepSession, "session-1")]
    job = db.rows[(EquipmentDeepJob, "job-1")]
    assert session.payload["scope"] == {"workspace_id": "owner"}
    assert job.payload["model_spec"] == "legacy-model"
    assert job.payload.get("status") is None
    assert (EquipmentDeepMessage, "message-orphan") not in db.rows
    assert (EquipmentDeepMessage, "message-1") in db.rows
    assert (EquipmentDeepBranch, "session-1:main") in db.rows
    assert (EquipmentDeepSteer, "steer-1") in db.rows

    session.payload = {**session.payload, "title": "用户改名", "status": "archived"}
    job.status = "completed"
    job.payload = {**job.payload, "user_note": "保留"}
    await service.persist_workbench_snapshot(db, user, _deep_snapshot(title="旧端再次改名", job_status="failed"))

    assert session.payload["title"] == "用户改名"
    assert session.payload["status"] == "archived"
    assert job.status == "completed"
    assert job.payload["user_note"] == "保留"

    for model, row_id in (
        (EquipmentDeepSession, "session-1"),
        (EquipmentDeepMessage, "message-1"),
        (EquipmentDeepJob, "job-1"),
        (EquipmentDeepBranch, "session-1:main"),
        (EquipmentDeepSteer, "steer-1"),
    ):
        db.rows.pop((model, row_id), None)

    await service.persist_workbench_snapshot(db, user, _deep_snapshot(title="不能复活", job_status="queued"))

    assert (EquipmentDeepSession, "session-1") not in db.rows
    assert (EquipmentDeepMessage, "message-1") not in db.rows
    ledger = next(row for (model, _), row in db.rows.items() if model is EquipmentLegacyImportBatch)
    assert ledger.report["seen_deep_session_ids"] == ["session-1"]
