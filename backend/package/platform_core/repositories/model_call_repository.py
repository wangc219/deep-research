"""统一模型调用账本的数据访问；与具体研究领域和模型供应商解耦。"""

import json
import logging
import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)
OUTBOX_ENV = "PLATFORM_MODEL_CALL_OUTBOX_PATH"
OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_model_calls (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


@lru_cache(maxsize=1)
def model_usage_engine():
    """同步调用线程复用有界连接池，避免占用业务异步事务。"""
    return create_engine(
        make_url(os.environ["POSTGRES_URL"]).set(drivername="postgresql+psycopg"),
        pool_size=2,
        max_overflow=3,
        pool_timeout=5,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )


def _outbox_path() -> Path | None:
    value = str(os.getenv(OUTBOX_ENV) or "").strip()
    return Path(value) if value else None


def _open_outbox(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(OUTBOX_SCHEMA)
    return connection


def _enqueue_model_call(path: Path, row: dict[str, Any]) -> None:
    payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with _open_outbox(path) as connection:
        connection.execute(
            "INSERT INTO pending_model_calls(id, payload) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
            (str(row["id"]), payload),
        )


def _insert_model_calls(rows: list[dict[str, Any]]) -> None:
    """同一事务幂等写入一批调用，并在写入时解析原生运行入口。"""
    with model_usage_engine().begin() as connection:
        for source in rows:
            row = dict(source)
            if row["surface"] == "智能对话" and row["run_id"]:
                agent = (
                    connection.execute(
                        text("SELECT source, run_type FROM agent_runs WHERE id=:run_id"),
                        {"run_id": row["run_id"]},
                    )
                    .mappings()
                    .first()
                )
                if agent:
                    if agent["source"] == "equipment_deep_research":
                        row["surface"] = "深研对话"
                    elif agent["run_type"] == "subagent":
                        row["surface"] = "Subagent"
            connection.execute(
                text("""INSERT INTO platform_model_calls
                (id, model_spec, surface, run_id, phase, status, duration_ms,
                 input_tokens, output_tokens, total_tokens, error_type, created_at)
                VALUES (:id, :model_spec, :surface, :run_id, :phase, :status, :duration_ms,
                 :input_tokens, :output_tokens, :total_tokens, :error_type,
                 (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))
                ON CONFLICT (id) DO NOTHING"""),
                row,
            )


def flush_pending_model_calls(*, limit: int = 200) -> dict[str, int | str]:
    """补写本地持久队列；PostgreSQL 不可用时保留记录并返回状态。"""
    path = _outbox_path()
    if path is None or not path.exists():
        return {"flushed": 0, "pending": 0}

    with _open_outbox(path) as connection:
        queued = connection.execute(
            "SELECT id, payload FROM pending_model_calls ORDER BY created_at, id LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    if not queued:
        return {"flushed": 0, "pending": 0}

    try:
        rows = [json.loads(payload) for _, payload in queued]
        _insert_model_calls(rows)
    except Exception as exc:  # 计量补写不能阻断模型或总览业务
        logger.warning("模型调用账本补写暂缓，pending=%s: %s", len(queued), type(exc).__name__)
        return {"flushed": 0, "pending": _pending_count(path), "error": type(exc).__name__}

    ids = [item[0] for item in queued]
    with _open_outbox(path) as connection:
        connection.executemany("DELETE FROM pending_model_calls WHERE id=?", [(item,) for item in ids])
    return {"flushed": len(ids), "pending": _pending_count(path)}


def _pending_count(path: Path) -> int:
    with _open_outbox(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM pending_model_calls").fetchone()[0])


def record_model_call(row: dict[str, Any]) -> None:
    """先持久排队再幂等入账，数据库短暂故障不会丢失已完成调用。"""
    path = _outbox_path()
    if path is None:
        _insert_model_calls([row])
        return

    try:
        _enqueue_model_call(path, row)
    except Exception:
        logger.exception("模型调用本地持久队列写入失败，改为直接入账，call_id=%s", row.get("id"))
        _insert_model_calls([row])
        return
    flush_pending_model_calls()
