import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "scripts" / "migration" / "import_legacy_sqlite.py").is_file()
)
sys.path.insert(0, str(ROOT / "scripts" / "migration"))

import import_legacy_sqlite as migration  # noqa: E402
from import_legacy_sqlite import _connect, inventory  # noqa: E402


def test_legacy_sqlite_inventory_uses_real_query_tables() -> None:
    report = inventory(
        ROOT / "outputs" / "application.db",
        ROOT / "outputs" / "query-library.db",
        ROOT / "outputs" / "runs",
    )
    assert report["runs"] == report["sqlite_runs"] + report["output_only_runs"]
    assert report["sqlite_runs"] >= 1
    assert report["output_only_runs"] >= 1
    assert report["events"] >= 1
    assert report["queries"] >= 1
    assert report["query_revisions"] >= 1
    assert report["query_generation_jobs"] >= 1
    assert report["capability_versions"] >= 1
    assert "worker_heartbeats" in report["skipped_tables"]


def test_inventory_imports_output_only_history_and_tolerates_older_schema(tmp_path: Path) -> None:
    app_db = tmp_path / "application.db"
    query_db = tmp_path / "query-library.db"
    with sqlite3.connect(app_db) as conn:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO runs VALUES (?, ?)",
            ("sqlite-run", json.dumps({"topic": "库内任务", "status": "unknown-old-status"})),
        )
    with sqlite3.connect(query_db) as conn:
        conn.execute("CREATE TABLE query_library_items (query_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO query_library_items VALUES ('query-1')")
    run_root = tmp_path / "runs" / "artifact-only"
    run_root.mkdir(parents=True)
    (run_root / "round_summary.json").write_text(
        json.dumps({"problem": {"topic": "仅产物任务"}, "resolved_route": "dynamic"}),
        encoding="utf-8",
    )
    (run_root / "report.md").write_text("# 历史报告", encoding="utf-8")

    report = inventory(app_db, query_db, tmp_path / "runs")

    assert report["runs"] == 2
    assert report["sqlite_runs"] == 1
    assert report["output_only_runs"] == 1
    assert report["queries"] == 1
    assert report["deep_sessions"] == 0
    assert report["artifact_files"] == 2


def test_corrupt_sqlite_is_rejected_without_writes(tmp_path: Path) -> None:
    broken = tmp_path / "application.db"
    broken.write_bytes(b"not-a-sqlite-database")

    with pytest.raises(sqlite3.DatabaseError):
        _connect(broken)


def test_import_is_idempotent_and_copies_reports_for_output_only_runs(
    monkeypatch, tmp_path: Path
) -> None:
    app_db = tmp_path / "application.db"
    query_db = tmp_path / "query-library.db"
    with sqlite3.connect(app_db) as conn:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO runs VALUES (?, ?)",
            ("sqlite-run", json.dumps({"topic": "库内任务", "status": "retired"})),
        )
    with sqlite3.connect(query_db) as conn:
        conn.execute("CREATE TABLE legacy_metadata (key TEXT PRIMARY KEY, value TEXT)")
    artifact_run = tmp_path / "runs" / "artifact-only"
    artifact_run.mkdir(parents=True)
    (artifact_run / "round_summary.json").write_text(
        json.dumps({"problem": {"topic": "仅产物任务"}}), encoding="utf-8"
    )
    (artifact_run / "report.md").write_text("# 可读取旧报告", encoding="utf-8")

    run_ids: set[str] = set()
    statuses: dict[str, str] = {}
    artifact_refs: set[tuple[str, str]] = set()

    def fake_pg(sql: str, params=()):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT workdir_path FROM projects"):
            return [("owner/project",)]
        if normalized.startswith("SELECT id FROM equipment_research_runs WHERE legacy_source_id"):
            return [(params[0],)] if params[0] in run_ids else []
        if normalized.startswith("INSERT INTO equipment_research_runs"):
            run_ids.add(str(params[0]))
            statuses[str(params[0])] = str(params[5])
            return []
        if normalized.startswith("INSERT INTO equipment_artifact_refs"):
            artifact_refs.add((str(params[1]), str(params[2])))
            return []
        return []

    monkeypatch.setattr(migration, "_run_pg", fake_pg)
    kwargs = {
        "app_db": app_db,
        "query_db": query_db,
        "runs_dir": tmp_path / "runs",
        "owner_uid": "owner",
        "project_id": "project",
        "artifact_root": tmp_path / "workspace",
    }

    first = migration._import_legacy(batch_id="batch-1", **kwargs)
    second = migration._import_legacy(batch_id="batch-2", **kwargs)

    assert first["runs"] == 2
    assert second["runs"] == 0
    assert run_ids == {"sqlite-run", "artifact-only"}
    assert statuses["sqlite-run"] == "completed"
    assert ("artifact-only", "outputs/equipment-research/artifact-only/report.md") in artifact_refs
    assert (
        tmp_path
        / "workspace"
        / "outputs"
        / "equipment-research"
        / "artifact-only"
        / "report.md"
    ).read_text(encoding="utf-8") == "# 可读取旧报告"
