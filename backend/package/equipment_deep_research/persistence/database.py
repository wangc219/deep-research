from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def create_database_engine(url: str) -> Engine:
    if not url.startswith("sqlite:"):
        return create_engine(url, future=True)
    engine = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            # Docker Desktop bind-mounts on macOS break SQLite WAL; use DELETE there.
            journal_mode = "DELETE" if os.environ.get("RUNNING_IN_DOCKER") == "true" else "WAL"
            try:
                cursor.execute(f"PRAGMA journal_mode={journal_mode}")
            except Exception:
                # virtiofs 上 WAL↔DELETE 切换失败时仍继续读库，避免问题库整组 500。
                pass
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine
