"""把工作台 SQLite 记录同步进 PostgreSQL，供知识门户与后续统一存储使用。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.permissions import has_global_business_access
from platform_core.repositories.equipment_research_repository import EquipmentResearchRepository
from platform_core.repositories.project_repository import ProjectRepository
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_equipment import (
    EQUIPMENT_RUN_STATUSES,
    EquipmentCapabilityVersion,
    EquipmentDeepBranch,
    EquipmentDeepJob,
    EquipmentDeepMessage,
    EquipmentDeepSession,
    EquipmentDeepSteer,
    EquipmentFavorite,
    EquipmentLegacyImportBatch,
    EquipmentQuery,
    EquipmentResearchRun,
)
from platform_core.utils.datetime_utils import utc_now_naive

logger = logging.getLogger(__name__)

SYNC_PROJECT_KEY = "equipment-workbench-legacy"
_ALLOWED_STATUSES = set(EQUIPMENT_RUN_STATUSES)
_last_persist_at = 0.0
_PERSIST_INTERVAL_SECONDS = 20.0
_DEEP_IMPORT_LEDGER_KIND = "workbench-deep-import-state"
_DEEP_TABLES = (
    "deep_sessions",
    "deep_messages",
    "deep_jobs",
    "deep_branches",
    "deep_steers",
)


def _sqlite_path(url: str, fallback: Path) -> Path:
    text = str(url or "").strip()
    if text.startswith("sqlite:///"):
        return Path(text.removeprefix("sqlite:///")).expanduser()
    return fallback


_SQLITE_MAGIC = b"SQLite format 3\x00"


def _connect(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    try:
        header = path.read_bytes()[:16]
    except OSError as exc:
        logger.warning("无法读取工作台 SQLite %s：%s", path, exc)
        return None
    if header != _SQLITE_MAGIC:
        logger.warning("工作台 SQLite 文件头损坏，跳过 %s", path)
        return None
    try:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("SELECT 1")
        return conn
    except sqlite3.Error as exc:
        logger.warning("无法打开工作台 SQLite %s：%s", path, exc)
        return None


def _parse_json(value: Any) -> Any:
    if value is None or value == "":
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"raw": str(value)}


def _optional_rows(conn: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    """Read one known additive ledger table without breaking older databases."""

    if table_name not in _DEEP_TABLES and table_name not in {
        "favorites",
        "capability_versions",
    }:
        raise ValueError(f"unsupported workbench table: {table_name}")
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if exists is None:
        return []
    try:
        return [dict(row) for row in conn.execute(f'SELECT * FROM "{table_name}"')]
    except sqlite3.Error as exc:
        logger.warning("读取工作台表 %s 失败：%s", table_name, exc)
        return []


def _decoded_row(
    row: dict[str, Any],
    json_columns: dict[str, tuple[str, Any]],
) -> dict[str, Any]:
    """Promote legacy ``*_json`` strings to their public payload names."""

    result = dict(row)
    for source, (target, default) in json_columns.items():
        if source not in result:
            result.setdefault(target, default)
            continue
        parsed = _parse_json(result.pop(source))
        result[target] = parsed if parsed != {} or default == {} else default
    return result


def _normalize_deep_snapshot(
    *,
    sessions: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    branches: list[dict[str, Any]],
    steers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Decode old ledger JSON and discard child rows with missing parents."""

    normalized_sessions = [
        _decoded_row(
            row,
            {
                "scope_json": ("scope", {}),
                "query_snapshot_json": ("query_snapshot", {}),
                "working_memory_json": ("working_memory", {}),
            },
        )
        for row in sessions
        if str(row.get("session_id") or "").strip()
    ]
    session_ids = {str(row.get("session_id") or "").strip() for row in normalized_sessions}
    normalized_messages = [
        _decoded_row(
            row,
            {
                "artifact_refs_json": ("artifact_refs", []),
                "version_refs_json": ("version_refs", []),
                "metadata_json": ("metadata", {}),
            },
        )
        for row in messages
        if str(row.get("session_id") or "").strip() in session_ids and str(row.get("message_id") or "").strip()
    ]
    normalized_jobs = [
        _decoded_row(
            row,
            {
                "payload_json": ("payload", {}),
                "checkpoint_json": ("checkpoint", {}),
            },
        )
        for row in jobs
        if str(row.get("session_id") or "").strip() in session_ids and str(row.get("job_id") or "").strip()
    ]
    job_ids = {str(row.get("job_id") or "").strip() for row in normalized_jobs}
    normalized_branches = [
        dict(row)
        for row in branches
        if str(row.get("session_id") or "").strip() in session_ids and str(row.get("branch_id") or "").strip()
    ]
    normalized_steers = [
        dict(row)
        for row in steers
        if str(row.get("session_id") or "").strip() in session_ids
        and str(row.get("job_id") or "").strip() in job_ids
        and str(row.get("steer_id") or "").strip()
    ]
    return {
        "deep_sessions": normalized_sessions,
        "deep_messages": normalized_messages,
        "deep_jobs": normalized_jobs,
        "deep_branches": normalized_branches,
        "deep_steers": normalized_steers,
    }


def _as_naive(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return fallback
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _normalize_status(value: str) -> str:
    status = str(value or "").strip() or "completed"
    return status if status in _ALLOWED_STATUSES else "completed"


def _count_capability_cards(run_root: Path) -> int:
    path = run_root / "capability_images.json"
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        rows = payload.get("capability_images") or payload.get("items") or payload.get("cards") or []
        return len(rows) if isinstance(rows, list) else 0
    return 0


def _has_report(run_root: Path) -> bool:
    if (run_root / "report-postfix.md").is_file() or (run_root / "report.md").is_file():
        return True
    return False


def delete_workbench_draft(run_id: str, user: User) -> dict[str, Any] | None:
    """Delete one user-visible draft from the legacy workbench ledger.

    The compatibility database remains read-only for every non-draft record.
    Returning ``None`` for both a missing row and a foreign workspace keeps the
    same non-disclosure contract as the platform repository.
    """

    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return None
    root = Path(os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", "/app")).expanduser()
    app_db = _sqlite_path(
        os.environ.get("EQUIPMENT_DR_APP_DB", ""),
        root / "outputs" / "application.db",
    )
    conn = _connect(app_db)
    if conn is None:
        return None
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("runs",),
        ).fetchone()
        if table_exists is None:
            return None
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT payload FROM runs WHERE run_id = ?",
            (normalized_run_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        payload = _parse_json(row["payload"])
        if not isinstance(payload, dict):
            conn.rollback()
            return None
        workspace_id = str(payload.get("workspace_id") or "").strip()
        if not has_global_business_access(user) and workspace_id != str(user.uid):
            conn.rollback()
            return None
        status = _normalize_status(str(payload.get("status") or "completed"))
        result = {
            "deleted": False,
            "run_id": normalized_run_id,
            "status": status,
            "workspace_id": workspace_id,
            "owner_uid": workspace_id or str(payload.get("owner_uid") or "").strip(),
        }
        if status != "draft":
            conn.rollback()
            return result
        cursor = conn.execute(
            "DELETE FROM runs WHERE run_id = ?",
            (normalized_run_id,),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        result["deleted"] = True
        return result
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_workbench_snapshot() -> dict[str, Any]:
    """只读工作台 SQLite：历史任务 + 之后在工作台新产生的记录。"""
    root = Path(os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", "/app")).expanduser()
    output_root = Path(os.environ.get("EQUIPMENT_DR_OUTPUT_ROOT", str(root / "outputs" / "runs"))).expanduser()
    app_db = _sqlite_path(os.environ.get("EQUIPMENT_DR_APP_DB", ""), root / "outputs" / "application.db")
    query_db = _sqlite_path(
        os.environ.get("EQUIPMENT_DR_QUERY_LIBRARY_DB", ""),
        root / "outputs" / "query-library.db",
    )
    now = utc_now_naive()
    runs: list[dict[str, Any]] = []
    deep_sessions: list[dict[str, Any]] = []
    deep_messages: list[dict[str, Any]] = []
    deep_jobs: list[dict[str, Any]] = []
    deep_branches: list[dict[str, Any]] = []
    deep_steers: list[dict[str, Any]] = []
    favorites: list[dict[str, Any]] = []
    capability_versions: list[dict[str, Any]] = []
    capability_total = 0
    completed_reports = 0
    conn = _connect(app_db)
    if conn is not None:
        try:
            try:
                for row in conn.execute("SELECT run_id, payload FROM runs"):
                    payload = _parse_json(row["payload"])
                    if not isinstance(payload, dict):
                        continue
                    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
                    if str(execution.get("parent_run_id") or "").strip():
                        continue
                    run_id = str(row["run_id"] or payload.get("run_id") or "").strip()
                    if not run_id:
                        continue
                    status = _normalize_status(str(payload.get("status") or "completed"))
                    run_root = output_root / run_id
                    cards = _count_capability_cards(run_root)
                    capability_total += cards
                    has_report = _has_report(run_root)
                    if status == "completed":
                        completed_reports += 1
                    runs.append(
                        {
                            "run_id": run_id,
                            "topic": str(payload.get("topic") or payload.get("query") or run_id),
                            "status": status,
                            "research_route": str(payload.get("research_route") or "auto"),
                            "payload": payload,
                            "error": str(payload.get("error") or ""),
                            "capability_count": cards,
                            "has_report": has_report,
                            "created_at": payload.get("created_at") or payload.get("updated_at") or now.isoformat(),
                            "updated_at": payload.get("updated_at") or payload.get("created_at") or now.isoformat(),
                        }
                    )
            except sqlite3.Error as exc:
                logger.warning("读取工作台 application.db 失败：%s", exc)
            deep_snapshot = _normalize_deep_snapshot(
                sessions=_optional_rows(conn, "deep_sessions"),
                messages=_optional_rows(conn, "deep_messages"),
                jobs=_optional_rows(conn, "deep_jobs"),
                branches=_optional_rows(conn, "deep_branches"),
                steers=_optional_rows(conn, "deep_steers"),
            )
            deep_sessions = deep_snapshot["deep_sessions"]
            deep_messages = deep_snapshot["deep_messages"]
            deep_jobs = deep_snapshot["deep_jobs"]
            deep_branches = deep_snapshot["deep_branches"]
            deep_steers = deep_snapshot["deep_steers"]
            favorites = _optional_rows(conn, "favorites")
            capability_versions = _optional_rows(conn, "capability_versions")
        finally:
            conn.close()

    known_ids = {item["run_id"] for item in runs}
    if output_root.is_dir():
        for child in output_root.iterdir():
            if not child.is_dir() or child.name in known_ids or child.name.startswith("."):
                continue
            summary_path = child / "round_summary.json"
            if not summary_path.is_file():
                continue
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(summary, dict):
                continue
            problem = summary.get("problem") if isinstance(summary.get("problem"), dict) else {}
            run_id = child.name
            cards = _count_capability_cards(child)
            capability_total += cards
            has_report = _has_report(child)
            completed_reports += 1
            stamp = str(problem.get("created_at") or "") or now.isoformat()
            runs.append(
                {
                    "run_id": run_id,
                    "topic": str(problem.get("topic") or run_id),
                    "status": "completed",
                    "research_route": str(summary.get("resolved_route") or problem.get("research_route") or "auto"),
                    "payload": {"historical_artifact": True, "summary": summary},
                    "error": "",
                    "capability_count": cards,
                    "has_report": has_report,
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            )
            known_ids.add(run_id)
    if not capability_total:
        capability_total = len(capability_versions)

    queries: list[dict[str, Any]] = []
    conn = _connect(query_db)
    if conn is not None:
        try:
            for row in conn.execute("SELECT * FROM query_library_items"):
                queries.append(dict(row))
        except sqlite3.Error as exc:
            logger.warning("读取工作台 query-library.db 失败：%s", exc)
        finally:
            conn.close()

    runs.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    queries.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    visible_queries = [item for item in queries if str(item.get("status") or "") != "archived"]
    visible_runs = [item for item in runs if item.get("status") != "archived"]
    visible_sessions = [item for item in deep_sessions if str(item.get("status") or "") != "archived"]
    return {
        "runs": runs,
        "queries": queries,
        "deep_sessions": deep_sessions,
        "deep_messages": deep_messages,
        "deep_jobs": deep_jobs,
        "deep_branches": deep_branches,
        "deep_steers": deep_steers,
        "favorites": favorites,
        "capability_versions": capability_versions,
        "stats": {
            "runs": len(visible_runs),
            "completed_runs": completed_reports,
            "queries": len(visible_queries),
            "deep_sessions": len(visible_sessions),
            "capabilities": capability_total,
        },
    }


def user_workbench_snapshot(snapshot: dict[str, Any], user: User) -> dict[str, Any]:
    """普通用户可读融合前的公共历史快照，新数据仍按持久化作者隔离。"""
    if has_global_business_access(user):
        return snapshot
    uid = str(user.uid)
    runs = [
        row
        for row in snapshot.get("runs", [])
        if not str((row.get("payload") or {}).get("workspace_id") or "").strip()
        or (row.get("payload") or {}).get("workspace_id") == uid
    ]
    run_ids = {row["run_id"] for row in runs}
    queries = [
        row
        for row in snapshot.get("queries", [])
        if not str(row.get("owner_uid") or "").strip() or row.get("owner_uid") == uid
    ]
    sessions = [row for row in snapshot.get("deep_sessions", []) if row.get("parent_run_id") in run_ids]
    session_ids = {
        str(row.get("session_id") or "").strip() for row in sessions if str(row.get("session_id") or "").strip()
    }
    messages = [
        row for row in snapshot.get("deep_messages", []) if str(row.get("session_id") or "").strip() in session_ids
    ]
    jobs = [row for row in snapshot.get("deep_jobs", []) if str(row.get("session_id") or "").strip() in session_ids]
    job_ids = {str(row.get("job_id") or "").strip() for row in jobs if str(row.get("job_id") or "").strip()}
    branches = [
        row for row in snapshot.get("deep_branches", []) if str(row.get("session_id") or "").strip() in session_ids
    ]
    steers = [
        row
        for row in snapshot.get("deep_steers", [])
        if str(row.get("session_id") or "").strip() in session_ids and str(row.get("job_id") or "").strip() in job_ids
    ]
    versions = [
        row for row in snapshot.get("capability_versions", []) if row.get("parent_run_id", row.get("run_id")) in run_ids
    ]
    favorites = [row for row in snapshot.get("favorites", []) if row.get("owner_id") == uid]
    return {
        "runs": runs,
        "queries": queries,
        "deep_sessions": sessions,
        "deep_messages": messages,
        "deep_jobs": jobs,
        "deep_branches": branches,
        "deep_steers": steers,
        "favorites": favorites,
        "capability_versions": versions,
        "stats": {
            "runs": sum(row.get("status") != "archived" for row in runs),
            "completed_runs": sum(row.get("status") == "completed" for row in runs),
            "queries": sum(row.get("status") != "archived" for row in queries),
            "deep_sessions": len(sessions),
            "capabilities": sum(row.get("capability_count", 0) for row in runs),
        },
    }


async def _ensure_sync_project(db: AsyncSession, user: User):
    repo = ProjectRepository(db)
    existing = await repo.get_by_idempotency_key(SYNC_PROJECT_KEY, str(user.uid))
    if existing is not None and existing.status == "active":
        return existing
    from platform_core.services.project_service import create_project_record

    try:
        return await create_project_record(
            uid=str(user.uid),
            name="装备研究工作台",
            directory_mode="managed",
            selection_status="selectable",
            db=db,
            idempotency_key=SYNC_PROJECT_KEY,
        )
    except IntegrityError:
        await db.rollback()
        replay = await repo.get_by_idempotency_key(SYNC_PROJECT_KEY, str(user.uid))
        if replay is None:
            raise
        return replay


def _deep_import_ledger_id(owner_uid: str, project_id: str) -> str:
    digest = hashlib.sha256(f"{_DEEP_IMPORT_LEDGER_KIND}:{owner_uid}:{project_id}".encode()).hexdigest()
    return f"deep-sync-{digest[:40]}"


async def _load_deep_import_ledger(
    db: AsyncSession,
    *,
    user: User,
    project_id: str,
    now: datetime,
) -> tuple[EquipmentLegacyImportBatch, set[str]]:
    """Return the durable seen-set used as a deletion tombstone fence."""

    ledger_id = _deep_import_ledger_id(str(user.uid), project_id)
    ledger = await db.get(EquipmentLegacyImportBatch, ledger_id)
    if ledger is None:
        ledger = EquipmentLegacyImportBatch(
            id=ledger_id,
            owner_uid=str(user.uid),
            project_id=project_id,
            status="imported",
            report={"kind": _DEEP_IMPORT_LEDGER_KIND, "seen_deep_session_ids": []},
            created_at=now,
        )
        db.add(ledger)
    report = dict(ledger.report or {})
    seen = {str(value).strip() for value in report.get("seen_deep_session_ids", []) if str(value).strip()}
    return ledger, seen


def _session_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"session_id", "parent_run_id", "created_at", "updated_at"}
    }


def _message_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"message_id", "session_id", "role", "content", "created_at"}
    }


def _job_payload(item: dict[str, Any]) -> dict[str, Any]:
    raw_payload = item.get("payload")
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {"legacy_payload": raw_payload}
    for key, value in item.items():
        if key not in {
            "job_id",
            "session_id",
            "status",
            "payload",
            "created_at",
            "updated_at",
        }:
            payload[key] = value
    return payload


def _branch_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in item.items() if key not in {"branch_id", "session_id", "created_at", "updated_at"}
    }


def _steer_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in item.items() if key not in {"steer_id", "session_id", "created_at", "updated_at"}
    }


async def persist_workbench_snapshot(
    db: AsyncSession, user: User, snapshot: dict[str, Any] | None = None
) -> dict[str, Any]:
    """把工作台快照幂等写入 PostgreSQL。已有行只更新状态/正文，不改归属。"""
    live = user_workbench_snapshot(snapshot or load_workbench_snapshot(), user)
    if has_global_business_access(user):
        return live
    project = await _ensure_sync_project(db, user)
    repo = EquipmentResearchRepository(db)
    now = utc_now_naive()
    run_ids: set[str] = set()
    for item in live.get("runs") or []:
        run_id = str(item.get("run_id") or "")
        if not run_id:
            continue
        created = _as_naive(item.get("created_at"), now)
        updated = _as_naive(item.get("updated_at"), created)
        row = await repo.get_run(run_id)
        payload = dict(item.get("payload") or {})
        payload["knowledge_enabled"] = bool(item.get("knowledge_enabled", True))
        payload["knowledge_ids"] = item.get("knowledge_ids")
        payload["capability_count"] = item.get("capability_count") or 0
        payload["has_report"] = bool(item.get("has_report"))
        if row is None:
            row = EquipmentResearchRun(
                id=run_id,
                project_id=project.id,
                owner_uid=str(user.uid),
                topic=str(item.get("topic") or run_id),
                research_route=str(item.get("research_route") or "auto"),
                status=_normalize_status(str(item.get("status") or "completed")),
                payload=payload,
                error=str(item.get("error") or ""),
                legacy_source_id=run_id,
                import_batch_id="workbench-user-sync",
                readonly=1,
                created_at=created,
                updated_at=updated,
            )
            await repo.add_run(row)
        else:
            row.topic = str(item.get("topic") or row.topic)
            row.status = _normalize_status(str(item.get("status") or row.status))
            row.payload = payload
            row.error = str(item.get("error") or "")
            row.legacy_source_id = row.legacy_source_id or run_id
            row.updated_at = updated
        run_ids.add(run_id)

    for item in live.get("queries") or []:
        query_id = str(item.get("query_id") or "")
        query_text = str(item.get("query") or "").strip()
        if not query_id or not query_text:
            continue
        fingerprint = (
            str(item.get("query_fingerprint") or "").strip()
            or hashlib.sha256(f"{user.uid}:{query_text}".encode()).hexdigest()
        )
        created = _as_naive(item.get("created_at"), now)
        updated = _as_naive(item.get("updated_at"), created)
        query_payload = {
            "generation_id": item.get("generation_id"),
            "generation_rationale": item.get("generation_rationale"),
            "source_references": _parse_json(item.get("source_references")),
            "knowledge_enabled": bool(item.get("knowledge_enabled", True)),
            "knowledge_ids": item.get("knowledge_ids"),
        }
        row = await repo.get_query(query_id)
        if row is None:
            by_fp = await repo.get_query_by_fingerprint(fingerprint)
            if by_fp is not None:
                continue
            await repo.add_query(
                EquipmentQuery(
                    id=query_id,
                    project_id=project.id,
                    owner_uid=str(user.uid),
                    query_text=query_text,
                    query_fingerprint=fingerprint[:64],
                    supplemental_information=str(item.get("supplemental_information") or ""),
                    status=str(item.get("status") or "draft"),
                    source_type=str(item.get("source_type") or "imported"),
                    version=int(item.get("version") or 1),
                    payload=query_payload,
                    legacy_source_id=query_id,
                    import_batch_id="workbench-user-sync",
                    created_at=created,
                    updated_at=updated,
                )
            )
        else:
            row.query_text = query_text
            row.status = str(item.get("status") or row.status)
            row.supplemental_information = str(item.get("supplemental_information") or "")
            row.payload = {**dict(row.payload or {}), **query_payload}
            row.legacy_source_id = row.legacy_source_id or query_id
            row.updated_at = updated

    deep_ledger, seen_deep_session_ids = await _load_deep_import_ledger(
        db,
        user=user,
        project_id=project.id,
        now=now,
    )
    persisted_deep_session_ids: set[str] = set()
    for item in live.get("deep_sessions") or []:
        session_id = str(item.get("session_id") or "")
        if not session_id:
            continue
        parent_id = str(item.get("parent_run_id") or "") or None
        if parent_id and parent_id not in run_ids and await repo.get_run(parent_id) is None:
            continue
        created = _as_naive(item.get("created_at"), now)
        updated = _as_naive(item.get("updated_at"), created)
        row = await repo.get_deep_session(session_id)
        if row is not None:
            if str(row.owner_uid) == str(user.uid):
                persisted_deep_session_ids.add(session_id)
            seen_deep_session_ids.add(session_id)
            continue
        if session_id in seen_deep_session_ids:
            # This source id existed in PostgreSQL during an earlier import and
            # is now absent. Treat the absence as a durable user deletion.
            continue
        await repo.add_deep_session(
            EquipmentDeepSession(
                id=session_id,
                project_id=project.id,
                owner_uid=str(user.uid),
                run_id=parent_id,
                payload=_session_payload(item),
                legacy_source_id=session_id,
                import_batch_id="workbench-user-sync",
                created_at=created,
                updated_at=updated,
            )
        )
        seen_deep_session_ids.add(session_id)
        persisted_deep_session_ids.add(session_id)

    deep_ledger.report = {
        **dict(deep_ledger.report or {}),
        "kind": _DEEP_IMPORT_LEDGER_KIND,
        "seen_deep_session_ids": sorted(seen_deep_session_ids),
        "updated_at": now.isoformat(),
    }

    for item in live.get("deep_messages") or []:
        session_id = str(item.get("session_id") or "").strip()
        message_id = str(item.get("message_id") or "").strip()
        if session_id not in persisted_deep_session_ids or not message_id:
            continue
        if await db.get(EquipmentDeepMessage, message_id) is not None:
            continue
        db.add(
            EquipmentDeepMessage(
                id=message_id[:128],
                session_id=session_id,
                role=str(item.get("role") or "assistant")[:32],
                content=str(item.get("content") or ""),
                payload=_message_payload(item),
                created_at=_as_naive(item.get("created_at"), now),
            )
        )

    persisted_deep_job_ids: set[str] = set()
    for item in live.get("deep_jobs") or []:
        session_id = str(item.get("session_id") or "").strip()
        job_id = str(item.get("job_id") or "").strip()
        if session_id not in persisted_deep_session_ids or not job_id:
            continue
        existing = await db.get(EquipmentDeepJob, job_id)
        if existing is not None:
            if str(existing.session_id) == session_id:
                persisted_deep_job_ids.add(job_id)
            continue
        db.add(
            EquipmentDeepJob(
                id=job_id[:128],
                session_id=session_id,
                status=str(item.get("status") or "queued")[:32],
                payload=_job_payload(item),
                created_at=_as_naive(item.get("created_at"), now),
                updated_at=_as_naive(item.get("updated_at"), now),
            )
        )
        persisted_deep_job_ids.add(job_id)

    for item in live.get("deep_branches") or []:
        session_id = str(item.get("session_id") or "").strip()
        branch_id = str(item.get("branch_id") or "").strip()
        if session_id not in persisted_deep_session_ids or not branch_id:
            continue
        if await db.get(EquipmentDeepBranch, branch_id) is not None:
            continue
        db.add(
            EquipmentDeepBranch(
                id=branch_id[:128],
                session_id=session_id,
                payload=_branch_payload(item),
                created_at=_as_naive(item.get("created_at"), now),
            )
        )

    for item in live.get("deep_steers") or []:
        session_id = str(item.get("session_id") or "").strip()
        steer_id = str(item.get("steer_id") or "").strip()
        job_id = str(item.get("job_id") or "").strip()
        if session_id not in persisted_deep_session_ids or job_id not in persisted_deep_job_ids or not steer_id:
            continue
        if await db.get(EquipmentDeepSteer, steer_id) is not None:
            continue
        db.add(
            EquipmentDeepSteer(
                id=steer_id[:128],
                session_id=session_id,
                payload=_steer_payload(item),
                created_at=_as_naive(item.get("created_at"), now),
            )
        )

    for item in live.get("favorites") or []:
        favorite_id = str(item.get("favorite_id") or "")
        run_id = str(item.get("run_id") or "")
        if not favorite_id:
            continue
        existing = await db.get(EquipmentFavorite, favorite_id)
        if existing is not None:
            continue
        source_run = await repo.get_run(run_id) if run_id else None
        raw_snapshot = _parse_json(item.get("snapshot_json"))
        snapshot = dict(raw_snapshot) if isinstance(raw_snapshot, dict) else {"legacy_snapshot": raw_snapshot}
        snapshot.setdefault("source_run_id", run_id)
        snapshot.setdefault("run_id", run_id)
        snapshot.setdefault("source_topic", str(item.get("source_topic") or ""))
        snapshot.setdefault("source_status", str(item.get("source_status") or ""))
        snapshot.setdefault("source_deleted", bool(item.get("source_deleted")) or source_run is None)
        raw_tags = _parse_json(item.get("tags_json") if "tags_json" in item else item.get("tags"))
        tags = [str(tag).strip()[:80] for tag in raw_tags if str(tag).strip()] if isinstance(raw_tags, list) else []
        card_key = str(
            item.get("card_key")
            or snapshot.get("favorite_card_key")
            or snapshot.get("card_binding_id")
            or snapshot.get("capability_id")
            or snapshot.get("version_id")
            or favorite_id
        )[:512]
        db.add(
            EquipmentFavorite(
                id=favorite_id,
                project_id=project.id,
                owner_uid=str(user.uid),
                run_id=run_id if source_run is not None else None,
                card_key=card_key,
                snapshot=snapshot,
                display_name=str(item.get("display_name") or ""),
                note=str(item.get("note") or ""),
                tags=tags[:20],
                created_at=_as_naive(item.get("created_at"), now),
                updated_at=_as_naive(item.get("updated_at"), now),
            )
        )

    for item in live.get("capability_versions") or []:
        version_id = str(item.get("version_id") or "")
        if not version_id:
            continue
        existing = await db.get(EquipmentCapabilityVersion, version_id)
        if existing is not None:
            continue
        parent_id = str(item.get("parent_run_id") or "") or None
        if parent_id and await repo.get_run(parent_id) is None:
            parent_id = None
        db.add(
            EquipmentCapabilityVersion(
                id=version_id,
                project_id=project.id,
                owner_uid=str(user.uid),
                run_id=parent_id,
                snapshot=_parse_json(item.get("snapshot_json")),
                legacy_source_id=version_id,
                import_batch_id="workbench-user-sync",
                created_at=_as_naive(item.get("created_at"), now),
            )
        )
    await db.flush()
    return live


async def ensure_workbench_synced(db: AsyncSession, user: User) -> dict[str, Any]:
    """读取工作台快照；节流写入 PostgreSQL，失败不影响门户展示。"""
    global _last_persist_at
    live = user_workbench_snapshot(load_workbench_snapshot(), user)
    now = time.monotonic()
    if now - _last_persist_at < _PERSIST_INTERVAL_SECONDS:
        return live
    try:
        await persist_workbench_snapshot(db, user, live)
        await db.commit()
        _last_persist_at = now
    except Exception:
        logger.exception("工作台记录写入 PostgreSQL 失败，门户仍使用实时工作台数据")
        await db.rollback()
    return live
