"""SQLite helper functions."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Unsafe SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})")]


def count_rows(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}").fetchone()
    return int(row[0]) if row else 0


def count_where(conn: sqlite3.Connection, table_name: str, where_sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} WHERE {where_sql}", params).fetchone()
    return int(row[0]) if row else 0


def group_counts(conn: sqlite3.Connection, table_name: str, column_name: str) -> dict[str, int]:
    rows = conn.execute(
        f"""
        SELECT {_quote_identifier(column_name)} AS key, COUNT(*) AS count
        FROM {_quote_identifier(table_name)}
        GROUP BY {_quote_identifier(column_name)}
        """
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | bytes | None) -> Any:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)
