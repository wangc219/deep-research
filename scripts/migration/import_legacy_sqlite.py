#!/usr/bin/env python3
"""把历史 SQLite 装备研究数据幂等迁入 PostgreSQL。

用法：
  python scripts/migration/import_legacy_sqlite.py dry-run
  python scripts/migration/import_legacy_sqlite.py import --owner-uid UID --project-id PROJECT_ID
  python scripts/migration/import_legacy_sqlite.py validate --batch-id BATCH
  python scripts/migration/import_legacy_sqlite.py rollback --batch-id BATCH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP_DB = ROOT / "outputs" / "application.db"
DEFAULT_QUERY_DB = ROOT / "outputs" / "query-library.db"
DEFAULT_RUNS_DIR = ROOT / "outputs" / "runs"
SKIP_TABLES = {"worker_heartbeats", "run_queue", "gateway_deliveries", "message_bus", "deep_idempotency"}


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as stream:
        header = stream.read(16)
    if header != b"SQLite format 3\x00":
        raise sqlite3.DatabaseError(f"不是有效的 SQLite 数据库: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _parse_json(value: Any) -> Any:
    if value is None or value == "":
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"raw": str(value)}


def _count(conn: sqlite3.Connection, table: str) -> int:
    if table not in _table_names(conn):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if table not in _table_names(conn):
        return []
    return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')]


def _row_value(row: dict[str, Any] | sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _output_only_runs(runs_dir: Path, known_ids: set[str]) -> list[dict[str, Any]]:
    """发现早期版本只落盘、尚未写入 application.db 的研究任务。"""

    found: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        return found
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in known_ids:
            continue
        summary_path = child / "round_summary.json"
        if not summary_path.is_file() or summary_path.is_symlink():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict):
            continue
        problem = summary.get("problem") if isinstance(summary.get("problem"), dict) else {}
        stamp = str(problem.get("created_at") or summary.get("created_at") or "")
        found.append(
            {
                "run_id": child.name,
                "payload": {
                    "historical_artifact": True,
                    "topic": str(problem.get("topic") or summary.get("topic") or child.name),
                    "status": "completed",
                    "research_route": str(
                        summary.get("resolved_route") or problem.get("research_route") or "auto"
                    ),
                    "created_at": stamp,
                    "updated_at": stamp,
                    "summary": summary,
                },
            }
        )
    return found


def _legacy_runs(app: sqlite3.Connection, runs_dir: Path) -> list[dict[str, Any]]:
    rows = _rows(app, "runs")
    normalized = [
        {"run_id": str(row.get("run_id") or ""), "payload": _parse_json(row.get("payload"))}
        for row in rows
        if str(row.get("run_id") or "").strip()
    ]
    known_ids = {row["run_id"] for row in normalized}
    return normalized + _output_only_runs(runs_dir, known_ids)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(app_db: Path, query_db: Path, runs_dir: Path) -> dict[str, Any]:
    app = _connect(app_db)
    query = _connect(query_db)
    run_payloads = _legacy_runs(app, runs_dir)
    statuses: dict[str, int] = {}
    for row in run_payloads:
        payload = _parse_json(row["payload"])
        status = str(payload.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    artifact_files = 0
    artifact_bytes = 0
    if runs_dir.exists():
        for path in runs_dir.rglob("*"):
            if path.is_file() and "codex-home" not in path.parts and path.name not in {"auth.json"}:
                artifact_files += 1
                artifact_bytes += path.stat().st_size
    report = {
        "application_db": str(app_db),
        "query_db": str(query_db),
        "runs": len(run_payloads),
        "sqlite_runs": _count(app, "runs"),
        "output_only_runs": max(0, len(run_payloads) - _count(app, "runs")),
        "run_status": statuses,
        "events": _count(app, "runtime_events"),
        "favorites": _count(app, "favorites"),
        "capability_versions": _count(app, "capability_versions"),
        "deep_sessions": _count(app, "deep_sessions"),
        "deep_messages": _count(app, "deep_messages"),
        "deep_jobs": _count(app, "deep_jobs"),
        "deep_branches": _count(app, "deep_branches"),
        "deep_steers": _count(app, "deep_steers"),
        "queries": _count(query, "query_library_items"),
        "query_revisions": _count(query, "query_library_revisions"),
        "query_generation_jobs": _count(query, "query_generation_jobs"),
        "artifact_files": artifact_files,
        "artifact_bytes": artifact_bytes,
        "skipped_tables": sorted(SKIP_TABLES),
    }
    app.close()
    query.close()
    return report


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _run_pg(sql: str, params: tuple[Any, ...] = ()) -> list[tuple]:
    import psycopg

    url = os.environ.get("POSTGRES_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if not url:
        raise RuntimeError("缺少 POSTGRES_URL")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = []
            if cur.description:
                rows = list(cur.fetchall())
        conn.commit()
        return rows


def import_legacy(
    *,
    app_db: Path,
    query_db: Path,
    runs_dir: Path,
    owner_uid: str,
    project_id: str,
    artifact_root: Path | None,
) -> dict[str, Any]:
    """执行可重放迁移，并把中途失败明确记录在导入批次中。"""

    batch_id = f"import-{uuid4()}"
    try:
        return _import_legacy(
            batch_id=batch_id,
            app_db=app_db,
            query_db=query_db,
            runs_dir=runs_dir,
            owner_uid=owner_uid,
            project_id=project_id,
            artifact_root=artifact_root,
        )
    except Exception as exc:
        try:
            _run_pg(
                """
                UPDATE equipment_legacy_import_batches
                SET status = 'failed', report = report || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps({"error": str(exc)}, ensure_ascii=False), batch_id),
            )
        except Exception:  # noqa: BLE001, S110 - 批次标记是尽力而为
            pass
        raise


def _import_legacy(
    *,
    batch_id: str,
    app_db: Path,
    query_db: Path,
    runs_dir: Path,
    owner_uid: str,
    project_id: str,
    artifact_root: Path | None,
) -> dict[str, Any]:
    report = inventory(app_db, query_db, runs_dir)
    app = _connect(app_db)
    query = _connect(query_db)
    project_rows = _run_pg(
        "SELECT workdir_path FROM projects WHERE id = %s AND uid = %s AND status = 'active'",
        (project_id, owner_uid),
    )
    if not project_rows:
        raise RuntimeError("目标项目不存在、已停用或不属于指定 owner")
    workdir_path = str(project_rows[0][0] or "")
    imported = {
        "batch_id": batch_id,
        "runs": 0,
        "events": 0,
        "queries": 0,
        "query_revisions": 0,
        "query_generation_jobs": 0,
        "capability_versions": 0,
        "favorites": 0,
        "deep_sessions": 0,
        "deep_messages": 0,
        "deep_jobs": 0,
        "deep_branches": 0,
        "deep_steers": 0,
        "artifacts": 0,
    }
    now = _utcnow()
    _run_pg(
        """
        INSERT INTO equipment_legacy_import_batches (id, owner_uid, project_id, status, report, created_at)
        VALUES (%s, %s, %s, 'importing', %s::jsonb, %s)
        """,
        (batch_id, owner_uid, project_id, json.dumps(report, ensure_ascii=False), now),
    )
    for row in _legacy_runs(app, runs_dir):
        payload = _parse_json(row["payload"])
        if not isinstance(payload, dict):
            payload = {"legacy_payload": payload}
        if workdir_path:
            payload["workdir_path"] = workdir_path
        existing = _run_pg(
            "SELECT id FROM equipment_research_runs WHERE legacy_source_id = %s",
            (row["run_id"],),
        )
        if existing:
            continue
        run_id = str(row["run_id"])
        topic = str(payload.get("topic") or payload.get("query") or run_id)
        status = str(payload.get("status") or "completed")
        if status not in {
            "draft",
            "queued",
            "planning",
            "researching",
            "recalling",
            "synthesizing",
            "reviewing",
            "reporting",
            "completed",
            "failed",
            "cancelled",
            "paused",
            "pause_requested",
            "archived",
        }:
            status = "completed"
        _run_pg(
            """
            INSERT INTO equipment_research_runs (
                id, project_id, owner_uid, topic, research_route, status, payload, error,
                legacy_source_id, import_batch_id, artifact_relpath, artifact_sha256, readonly, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, 1, %s, %s)
            """,
            (
                run_id,
                project_id,
                owner_uid,
                topic,
                str(payload.get("research_route") or "auto"),
                status,
                json.dumps(payload, ensure_ascii=False),
                str(payload.get("error") or ""),
                run_id,
                batch_id,
                "",
                "",
                payload.get("created_at") or now,
                payload.get("updated_at") or now,
            ),
        )
        imported["runs"] += 1
        src_dir = runs_dir / run_id
        if artifact_root and src_dir.exists():
            dest = artifact_root / "outputs" / "equipment-research" / run_id
            dest.mkdir(parents=True, exist_ok=True)
            preferred_report: tuple[str, str] | None = None
            for src in src_dir.rglob("*"):
                if (
                    not src.is_file()
                    or src.is_symlink()
                    or "codex-home" in src.parts
                    or src.name == "auth.json"
                ):
                    continue
                rel = src.relative_to(src_dir)
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(src, target)
                digest = _sha256_file(target)
                _run_pg(
                    """
                    INSERT INTO equipment_artifact_refs (id, run_id, relative_path, sha256, byte_size, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        f"art-{uuid4()}",
                        run_id,
                        str(Path("outputs/equipment-research") / run_id / rel),
                        digest,
                        target.stat().st_size,
                        now,
                    ),
                )
                imported["artifacts"] += 1
                if rel.as_posix() in {"report-postfix.md", "report.md"} and (
                    preferred_report is None or rel.name == "report-postfix.md"
                ):
                    preferred_report = (
                        str(Path("outputs/equipment-research") / run_id / rel),
                        digest,
                    )
            if preferred_report is not None:
                _run_pg(
                    """
                    UPDATE equipment_research_runs
                    SET artifact_relpath = %s, artifact_sha256 = %s
                    WHERE id = %s AND owner_uid = %s
                    """,
                    (preferred_report[0], preferred_report[1], run_id, owner_uid),
                )
    for row in sorted(
        _rows(app, "runtime_events"),
        key=lambda item: (str(item.get("run_id") or ""), int(item.get("sequence") or 0)),
    ):
        exists = _run_pg(
            "SELECT 1 FROM equipment_research_events WHERE run_id = %s AND sequence = %s",
            (row["run_id"], row["sequence"]),
        )
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_research_events (run_id, sequence, event_type, payload, created_at)
            VALUES (%s, %s, %s, %s::jsonb, %s)
            """,
            (
                row["run_id"],
                row["sequence"],
                row["event_type"],
                json.dumps(_parse_json(row["payload"]), ensure_ascii=False),
                now,
            ),
        )
        imported["events"] += 1
    for row in _rows(query, "query_library_items"):
        exists = _run_pg("SELECT id FROM equipment_queries WHERE legacy_source_id = %s", (row["query_id"],))
        if exists:
            continue
        fingerprint = row["query_fingerprint"] or hashlib.sha256(str(row["query"]).encode("utf-8")).hexdigest()
        _run_pg(
            """
            INSERT INTO equipment_queries (
                id, project_id, owner_uid, query_text, query_fingerprint, supplemental_information,
                status, source_type, version, payload, legacy_source_id, import_batch_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (query_fingerprint) DO NOTHING
            """,
            (
                row["query_id"],
                project_id,
                owner_uid,
                row["query"],
                fingerprint,
                row["supplemental_information"] or "",
                row["status"] or "draft",
                row["source_type"] or "imported",
                row["version"] or 1,
                json.dumps(
                    {
                        "generation_id": row["generation_id"],
                        "generation_rationale": row["generation_rationale"],
                        "source_references": _parse_json(row["source_references"]),
                    },
                    ensure_ascii=False,
                ),
                row["query_id"],
                batch_id,
                row["created_at"] or now,
                row["updated_at"] or now,
            ),
        )
        imported["queries"] += 1
    for row in _rows(query, "query_library_revisions"):
        exists = _run_pg(
            """
            SELECT 1 FROM equipment_query_revisions
            WHERE query_id = %s AND version = %s AND change_type = %s
            """,
            (row["query_id"], row["version"], row["change_type"]),
        )
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_query_revisions (query_id, version, change_type, snapshot, changed_at)
            SELECT %s, %s, %s, %s::jsonb, %s
            WHERE EXISTS (SELECT 1 FROM equipment_queries WHERE id = %s)
            """,
            (
                row["query_id"],
                row["version"],
                row["change_type"],
                json.dumps(_parse_json(row["snapshot"]), ensure_ascii=False),
                row["changed_at"] or now,
                row["query_id"],
            ),
        )
        imported["query_revisions"] += 1
    for row in _rows(query, "query_generation_jobs"):
        exists = _run_pg("SELECT id FROM equipment_query_generations WHERE legacy_source_id = %s", (row["generation_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_query_generations (
                id, project_id, owner_uid, topic, status, payload, legacy_source_id, import_batch_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                row["generation_id"],
                project_id,
                owner_uid,
                row["topic"] or "",
                row["status"] or "completed",
                json.dumps(dict(row), default=str, ensure_ascii=False),
                row["generation_id"],
                batch_id,
                row["created_at"] or now,
                row["updated_at"] or now,
            ),
        )
        imported["query_generation_jobs"] += 1
    for row in _rows(app, "capability_versions"):
        exists = _run_pg("SELECT id FROM equipment_capability_versions WHERE legacy_source_id = %s", (row["version_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_capability_versions (
                id, project_id, owner_uid, run_id, snapshot, legacy_source_id, import_batch_id, created_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                row["version_id"],
                project_id,
                owner_uid,
                row["parent_run_id"],
                json.dumps(_parse_json(row["snapshot_json"]), ensure_ascii=False),
                row["version_id"],
                batch_id,
                row["created_at"] or now,
            ),
        )
        imported["capability_versions"] += 1
    for row in _rows(app, "favorites"):
        exists = _run_pg("SELECT id FROM equipment_favorites WHERE id = %s", (row["favorite_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_favorites (
                id, project_id, owner_uid, run_id, card_key, snapshot, display_name, note, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                row["favorite_id"],
                project_id,
                owner_uid,
                row["run_id"],
                row["card_key"],
                json.dumps(_parse_json(row["snapshot_json"]), ensure_ascii=False),
                row["display_name"] or "",
                row["note"] or "",
                row["created_at"] or now,
                row["updated_at"] or now,
            ),
        )
        imported["favorites"] += 1
    for row in _rows(app, "deep_sessions"):
        exists = _run_pg("SELECT id FROM equipment_deep_sessions WHERE legacy_source_id = %s", (row["session_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_deep_sessions (
                id, project_id, owner_uid, run_id, payload, legacy_source_id, import_batch_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                row["session_id"],
                project_id,
                owner_uid,
                row["parent_run_id"],
                json.dumps(dict(row), default=str, ensure_ascii=False),
                row["session_id"],
                batch_id,
                row["created_at"] or now,
                row["updated_at"] or now,
            ),
        )
        imported["deep_sessions"] += 1
    for row in _rows(app, "deep_messages"):
        exists = _run_pg("SELECT id FROM equipment_deep_messages WHERE id = %s", (row["message_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_deep_messages (id, session_id, role, content, payload, created_at)
            SELECT %s, %s, %s, %s, %s::jsonb, %s
            WHERE EXISTS (SELECT 1 FROM equipment_deep_sessions WHERE id = %s)
            """,
            (
                row["message_id"],
                row["session_id"],
                row["role"] or "assistant",
                row["content"] or "",
                json.dumps(_parse_json(row["metadata_json"]), ensure_ascii=False),
                row["created_at"] or now,
                row["session_id"],
            ),
        )
        imported["deep_messages"] += 1
    for row in _rows(app, "deep_jobs"):
        exists = _run_pg("SELECT id FROM equipment_deep_jobs WHERE id = %s", (row["job_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_deep_jobs (id, session_id, status, payload, created_at, updated_at)
            SELECT %s, %s, %s, %s::jsonb, %s, %s
            WHERE EXISTS (SELECT 1 FROM equipment_deep_sessions WHERE id = %s)
            """,
            (
                row["job_id"],
                row["session_id"],
                row["status"] or "completed",
                json.dumps(dict(row), default=str, ensure_ascii=False),
                row["created_at"] or now,
                row["updated_at"] or now,
                row["session_id"],
            ),
        )
        imported["deep_jobs"] += 1
    for row in _rows(app, "deep_branches"):
        exists = _run_pg("SELECT id FROM equipment_deep_branches WHERE id = %s", (row["branch_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_deep_branches (id, session_id, payload, created_at)
            SELECT %s, %s, %s::jsonb, %s
            WHERE EXISTS (SELECT 1 FROM equipment_deep_sessions WHERE id = %s)
            """,
            (
                row["branch_id"],
                row["session_id"],
                json.dumps(dict(row), default=str, ensure_ascii=False),
                row["created_at"] or now,
                row["session_id"],
            ),
        )
        imported["deep_branches"] += 1
    for row in _rows(app, "deep_steers"):
        exists = _run_pg("SELECT id FROM equipment_deep_steers WHERE id = %s", (row["steer_id"],))
        if exists:
            continue
        _run_pg(
            """
            INSERT INTO equipment_deep_steers (id, session_id, payload, created_at)
            SELECT %s, %s, %s::jsonb, %s
            WHERE EXISTS (SELECT 1 FROM equipment_deep_sessions WHERE id = %s)
            """,
            (
                row["steer_id"],
                row["session_id"],
                json.dumps(dict(row), default=str, ensure_ascii=False),
                row["created_at"] or now,
                row["session_id"],
            ),
        )
        imported["deep_steers"] += 1
    app.close()
    query.close()
    _run_pg(
        "UPDATE equipment_legacy_import_batches SET status = 'imported', report = %s::jsonb WHERE id = %s",
        (json.dumps({"source": report, "imported": imported}, ensure_ascii=False), batch_id),
    )
    return imported


def validate(batch_id: str, source: dict[str, Any]) -> dict[str, Any]:
    counts = {
        "runs": _run_pg(
            "SELECT COUNT(*) FROM equipment_research_runs WHERE import_batch_id = %s", (batch_id,)
        )[0][0],
        "queries": _run_pg("SELECT COUNT(*) FROM equipment_queries WHERE import_batch_id = %s", (batch_id,))[0][0],
        "capability_versions": _run_pg(
            "SELECT COUNT(*) FROM equipment_capability_versions WHERE import_batch_id = %s", (batch_id,)
        )[0][0],
        "deep_sessions": _run_pg(
            "SELECT COUNT(*) FROM equipment_deep_sessions WHERE import_batch_id = %s", (batch_id,)
        )[0][0],
    }
    diffs = {
        "runs": source["runs"] - int(counts["runs"]),
        "queries": source["queries"] - int(counts["queries"]),
        "capability_versions": source["capability_versions"] - int(counts["capability_versions"]),
        "deep_sessions": source["deep_sessions"] - int(counts["deep_sessions"]),
    }
    ok = all(value == 0 for value in diffs.values())
    return {"ok": ok, "counts": counts, "diffs": diffs}


def rollback(batch_id: str) -> dict[str, Any]:
    tables = [
        "equipment_artifact_refs",
        "equipment_research_events",
        "equipment_query_revisions",
        "equipment_query_generations",
        "equipment_deep_steers",
        "equipment_deep_jobs",
        "equipment_deep_branches",
        "equipment_deep_messages",
        "equipment_deep_sessions",
        "equipment_favorites",
        "equipment_expert_feedback",
        "equipment_capability_versions",
        "equipment_queries",
        "equipment_research_runs",
    ]
    deleted: dict[str, int] = {}
    for table in tables:
        if table in {
            "equipment_artifact_refs",
            "equipment_research_events",
            "equipment_query_revisions",
            "equipment_deep_steers",
            "equipment_deep_jobs",
            "equipment_deep_branches",
            "equipment_deep_messages",
            "equipment_favorites",
            "equipment_expert_feedback",
        }:
            continue
        result = _run_pg(f"DELETE FROM {table} WHERE import_batch_id = %s RETURNING id", (batch_id,))
        deleted[table] = len(result)
    _run_pg(
        "UPDATE equipment_legacy_import_batches SET status = 'rolled_back', rolled_back_at = %s WHERE id = %s",
        (_utcnow(), batch_id),
    )
    return {"batch_id": batch_id, "deleted": deleted}


def main() -> int:
    parser = argparse.ArgumentParser(description="历史 SQLite 装备研究数据迁移")
    parser.add_argument("command", choices=["dry-run", "import", "validate", "rollback"])
    parser.add_argument("--app-db", type=Path, default=DEFAULT_APP_DB)
    parser.add_argument("--query-db", type=Path, default=DEFAULT_QUERY_DB)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--owner-uid")
    parser.add_argument("--project-id")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--batch-id")
    args = parser.parse_args()
    if args.command == "dry-run":
        print(json.dumps(inventory(args.app_db, args.query_db, args.runs_dir), ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "import":
        if not args.owner_uid or not args.project_id:
            parser.error("import 需要 --owner-uid 和 --project-id")
        result = import_legacy(
            app_db=args.app_db,
            query_db=args.query_db,
            runs_dir=args.runs_dir,
            owner_uid=args.owner_uid,
            project_id=args.project_id,
            artifact_root=args.artifact_root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "validate":
        if not args.batch_id:
            parser.error("validate 需要 --batch-id")
        source = inventory(args.app_db, args.query_db, args.runs_dir)
        result = validate(args.batch_id, source)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["ok"] else 2
    if args.command == "rollback":
        if not args.batch_id:
            parser.error("rollback 需要 --batch-id")
        print(json.dumps(rollback(args.batch_id), ensure_ascii=False, indent=2, default=str))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
