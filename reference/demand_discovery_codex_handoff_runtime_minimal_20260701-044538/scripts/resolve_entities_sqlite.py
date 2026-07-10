"""Phase 4 Entity Resolution v0.5: rule and alias based SQLite resolution.

This script intentionally stays in the local experiment layer:
- no Neo4j
- no embedding or LLM normalization
- no canonical entity service
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PHASE3_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase3_structured"
    / "phase3_extractions.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase4_entity_resolution_v0"
    / "entity_resolution.sqlite"
)

RESOLUTION_RULESET_VERSION = "entity-resolution-rules-v0.5"

SEED_ALIAS_GROUPS = [
    {
        "canonical_name": "美国太空军",
        "canonical_type": "Source",
        "entity_status": "active",
        "aliases": [
            "美太空军",
            "美国太空军",
            "太空军",
            "Space Force",
            "United States Space Force",
            "US Space Force",
            "USSF",
        ],
    },
    {
        "canonical_name": "美国空军",
        "canonical_type": "Source",
        "entity_status": "active",
        "aliases": [
            "美空军",
            "美国空军",
            "US Air Force",
            "United States Air Force",
            "USAF",
        ],
    },
    {
        "canonical_name": "人工智能",
        "canonical_type": "Technology",
        "entity_status": "active",
        "aliases": [
            "人工智能",
            "AI",
            "artificial intelligence",
            "Artificial Intelligence",
            "military AI",
        ],
    },
    {
        "canonical_name": "协同作战飞机",
        "canonical_type": "EngineeringObject",
        "entity_status": "active",
        "aliases": [
            "协同作战飞机",
            "CCA",
            "Collaborative Combat Aircraft",
        ],
    },
    {
        "canonical_name": "GA-BP算法",
        "canonical_type": "Technology",
        "entity_status": "active",
        "aliases": [
            "GA-BP",
            "GA-BP算法",
            "GA-BP algorithm",
        ],
    },
]

NOISE_ALIASES = {
    "本文",
    "本文研究",
    "本研究",
    "该文",
    "文章",
    "全文",
    "作者",
    "该方案",
    "上述方法",
    "该系统",
    "此方案",
    "该技术",
    "该项目",
}


def main() -> int:
    args = _parse_args()
    output_db = Path(args.output_db).expanduser().resolve()
    if output_db.exists() and not args.force:
        raise SystemExit(f"Output DB already exists; use --force to replace: {output_db}")
    summary = resolve_phase3_entities(
        phase3_db=Path(args.phase3_db).expanduser().resolve(),
        output_db=output_db,
        overwrite=args.force,
    )
    print("entity_resolution_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def resolve_phase3_entities(
    phase3_db: Path,
    output_db: Path,
    overwrite: bool = True,
) -> dict[str, Any]:
    if not phase3_db.exists():
        raise FileNotFoundError(f"Phase 3 DB not found: {phase3_db}")
    if output_db.exists() and overwrite:
        output_db.unlink()
    output_db.parent.mkdir(parents=True, exist_ok=True)
    if phase3_db.resolve() != output_db.resolve():
        shutil.copy2(phase3_db, output_db)

    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        ensure_resolution_schema(conn)
        with conn:
            summary = _resolve_mentions(conn)
        summary.update(
            {
                "phase3_db": str(phase3_db),
                "output_db": str(output_db),
                "ruleset_version": RESOLUTION_RULESET_VERSION,
            }
        )
        return summary
    finally:
        conn.close()


def ensure_resolution_schema(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "entity_mentions", "resolved_entity_id", "TEXT")
    _add_column_if_missing(conn, "entity_mentions", "resolution_status", "TEXT")
    _add_column_if_missing(conn, "entity_mentions", "resolution_rule", "TEXT")
    _add_column_if_missing(conn, "entity_mentions", "resolution_note", "TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS resolved_entities (
            resolved_entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            canonical_type TEXT NOT NULL,
            entity_status TEXT NOT NULL,
            resolution_rule TEXT NOT NULL,
            alias_json TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            document_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entity_resolution_aliases (
            alias_id TEXT PRIMARY KEY,
            resolved_entity_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            alias_normalized TEXT NOT NULL,
            alias_source TEXT NOT NULL,
            mention_count INTEGER NOT NULL,
            FOREIGN KEY(resolved_entity_id) REFERENCES resolved_entities(resolved_entity_id)
        );

        CREATE INDEX IF NOT EXISTS idx_entity_mentions_resolved_entity_id
            ON entity_mentions(resolved_entity_id);
        CREATE INDEX IF NOT EXISTS idx_resolved_entities_name
            ON resolved_entities(canonical_name, canonical_type);
        CREATE INDEX IF NOT EXISTS idx_entity_resolution_aliases_normalized
            ON entity_resolution_aliases(alias_normalized);
        """
    )
    _create_index_if_table_exists(
        conn,
        "relation_assertions",
        "idx_relation_assertions_type_source",
        "relation_type, source_mention_id",
    )
    _create_index_if_table_exists(
        conn,
        "relation_assertions",
        "idx_relation_assertions_source_type",
        "source_mention_id, relation_type",
    )
    _create_index_if_table_exists(
        conn,
        "relation_assertions",
        "idx_relation_assertions_source",
        "source_mention_id",
    )
    _create_index_if_table_exists(
        conn,
        "relation_assertions",
        "idx_relation_assertions_target",
        "target_mention_id",
    )
    conn.commit()


def normalize_entity_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name or "").strip().lower()
    normalized = re.sub(r"[\s\u3000_·\-—–/\\]+", "", normalized)
    normalized = normalized.strip("\"'“”‘’《》()（）[]【】")
    return normalized


def fetch_resolved_entity_bundle(
    conn: sqlite3.Connection,
    resolved_entity_id: str,
) -> dict[str, Any]:
    return {
        "resolved_entity": _one(
            conn,
            "SELECT * FROM resolved_entities WHERE resolved_entity_id = ?",
            (resolved_entity_id,),
        ),
        "aliases": _many(
            conn,
            """
            SELECT * FROM entity_resolution_aliases
            WHERE resolved_entity_id = ?
            ORDER BY mention_count DESC, alias
            """,
            (resolved_entity_id,),
        ),
        "mentions": _many(
            conn,
            """
            SELECT mention_id, chunk_id, name, entity_type, confidence,
                   resolution_status, resolution_rule
            FROM entity_mentions
            WHERE resolved_entity_id = ?
            ORDER BY chunk_id, mention_id
            """,
            (resolved_entity_id,),
        ),
    }


def _resolve_mentions(conn: sqlite3.Connection) -> dict[str, Any]:
    mentions = [
        dict(row)
        for row in conn.execute(
            """
            SELECT mention_id, chunk_id, name, entity_type
            FROM entity_mentions
            ORDER BY mention_id
            """
        ).fetchall()
    ]
    alias_lookup = _build_seed_alias_lookup()
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    assignments: dict[str, dict[str, str]] = {}

    for mention in mentions:
        name = str(mention["name"] or "")
        entity_type = str(mention["entity_type"] or "")
        normalized = normalize_entity_name(name)
        if normalized in _normalized_noise_aliases():
            key = ("noise", "Noise", "文本自指噪声")
            grouped[key].append(mention)
            assignments[str(mention["mention_id"])] = {
                "key": _key_to_text(key),
                "resolution_status": "excluded",
                "resolution_rule": "noise_alias",
                "resolution_note": "text self-reference alias",
            }
        elif normalized in alias_lookup:
            group = alias_lookup[normalized]
            key = (
                "alias_seed",
                str(group["canonical_type"]),
                str(group["canonical_name"]),
            )
            grouped[key].append(mention)
            assignments[str(mention["mention_id"])] = {
                "key": _key_to_text(key),
                "resolution_status": "resolved",
                "resolution_rule": "alias_seed",
                "resolution_note": f"matched alias: {name}",
            }
        else:
            key = ("exact_normalized", entity_type, normalized or name)
            grouped[key].append(mention)
            assignments[str(mention["mention_id"])] = {
                "key": _key_to_text(key),
                "resolution_status": "resolved",
                "resolution_rule": "exact_normalized",
                "resolution_note": "",
            }

    resolved_by_key: dict[str, dict[str, str]] = {}
    created_at = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM entity_resolution_aliases")
    conn.execute("DELETE FROM resolved_entities")
    for key, group_mentions in grouped.items():
        key_text = _key_to_text(key)
        entity = _build_resolved_entity(key, group_mentions, alias_lookup)
        resolved_entity_id = _resolved_entity_id(
            entity["canonical_type"],
            entity["canonical_name"],
            entity["entity_status"],
        )
        resolved_by_key[key_text] = {
            "resolved_entity_id": resolved_entity_id,
            "canonical_name": entity["canonical_name"],
            "canonical_type": entity["canonical_type"],
            "entity_status": entity["entity_status"],
        }
        aliases = _aliases_for_group(entity, group_mentions)
        document_count = _document_count(conn, [str(item["chunk_id"]) for item in group_mentions])
        conn.execute(
            """
            INSERT INTO resolved_entities (
                resolved_entity_id, canonical_name, canonical_type, entity_status,
                resolution_rule, alias_json, mention_count, chunk_count,
                document_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_entity_id,
                entity["canonical_name"],
                entity["canonical_type"],
                entity["entity_status"],
                entity["resolution_rule"],
                json.dumps(aliases, ensure_ascii=False, sort_keys=True),
                len(group_mentions),
                len({item["chunk_id"] for item in group_mentions}),
                document_count,
                created_at,
            ),
        )
        alias_counts = Counter(str(item["name"] or "") for item in group_mentions)
        for alias in aliases:
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_resolution_aliases (
                    alias_id, resolved_entity_id, alias, alias_normalized,
                    alias_source, mention_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _alias_id(resolved_entity_id, alias),
                    resolved_entity_id,
                    alias,
                    normalize_entity_name(alias),
                    entity["resolution_rule"],
                    alias_counts.get(alias, 0),
                ),
            )

    for mention_id, assignment in assignments.items():
        resolved = resolved_by_key[assignment["key"]]
        conn.execute(
            """
            UPDATE entity_mentions
            SET resolved_entity_id = ?,
                resolution_status = ?,
                resolution_rule = ?,
                resolution_note = ?
            WHERE mention_id = ?
            """,
            (
                resolved["resolved_entity_id"],
                assignment["resolution_status"],
                assignment["resolution_rule"],
                assignment["resolution_note"],
                mention_id,
            ),
        )

    return summarize_resolution(conn)


def summarize_resolution(conn: sqlite3.Connection) -> dict[str, Any]:
    mentions = conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]
    resolved_mentions = conn.execute(
        """
        SELECT COUNT(*)
        FROM entity_mentions
        WHERE resolved_entity_id IS NOT NULL AND resolved_entity_id != ''
        """
    ).fetchone()[0]
    resolved_entities = conn.execute("SELECT COUNT(*) FROM resolved_entities").fetchone()[0]
    singleton_entities = conn.execute(
        "SELECT COUNT(*) FROM resolved_entities WHERE mention_count = 1"
    ).fetchone()[0]
    merged_entities = conn.execute(
        "SELECT COUNT(*) FROM resolved_entities WHERE mention_count > 1"
    ).fetchone()[0]
    mentions_in_merged_entities = conn.execute(
        "SELECT COALESCE(SUM(mention_count), 0) FROM resolved_entities WHERE mention_count > 1"
    ).fetchone()[0]
    active_entities = conn.execute(
        "SELECT COUNT(*) FROM resolved_entities WHERE entity_status = 'active'"
    ).fetchone()[0]
    noise_entities = conn.execute(
        "SELECT COUNT(*) FROM resolved_entities WHERE entity_status = 'noise'"
    ).fetchone()[0]
    status_counts = dict(
        conn.execute(
            """
            SELECT resolution_status, COUNT(*)
            FROM entity_mentions
            GROUP BY resolution_status
            ORDER BY resolution_status
            """
        ).fetchall()
    )
    rule_counts = dict(
        conn.execute(
            """
            SELECT resolution_rule, COUNT(*)
            FROM entity_mentions
            GROUP BY resolution_rule
            ORDER BY resolution_rule
            """
        ).fetchall()
    )
    return {
        "mentions": mentions,
        "resolved_mentions": resolved_mentions,
        "coverage": round(resolved_mentions / mentions, 4) if mentions else 0.0,
        "resolved_entities": resolved_entities,
        "singleton_entities": singleton_entities,
        "singleton_entity_rate": round(singleton_entities / resolved_entities, 4)
        if resolved_entities
        else 0.0,
        "merged_entities": merged_entities,
        "mentions_in_merged_entities": mentions_in_merged_entities,
        "true_merge_mention_rate": round(mentions_in_merged_entities / mentions, 4)
        if mentions
        else 0.0,
        "active_entities": active_entities,
        "noise_entities": noise_entities,
        "status_counts": status_counts,
        "rule_counts": rule_counts,
    }


def _build_seed_alias_lookup() -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for group in SEED_ALIAS_GROUPS:
        for alias in group["aliases"]:
            lookup[normalize_entity_name(str(alias))] = {
                "canonical_name": str(group["canonical_name"]),
                "canonical_type": str(group["canonical_type"]),
                "entity_status": str(group["entity_status"]),
            }
    return lookup


def _normalized_noise_aliases() -> set[str]:
    return {normalize_entity_name(alias) for alias in NOISE_ALIASES}


def _build_resolved_entity(
    key: tuple[str, str, str],
    mentions: list[dict[str, Any]],
    alias_lookup: dict[str, dict[str, str]],
) -> dict[str, str]:
    rule, canonical_type, value = key
    if rule == "noise":
        return {
            "canonical_name": "文本自指噪声",
            "canonical_type": "Noise",
            "entity_status": "noise",
            "resolution_rule": "noise_alias",
        }
    if rule == "alias_seed":
        return {
            "canonical_name": value,
            "canonical_type": canonical_type,
            "entity_status": "active",
            "resolution_rule": "alias_seed",
        }
    canonical_name = _choose_canonical_name(mentions)
    return {
        "canonical_name": canonical_name,
        "canonical_type": canonical_type,
        "entity_status": "active",
        "resolution_rule": "exact_normalized",
    }


def _choose_canonical_name(mentions: list[dict[str, Any]]) -> str:
    counts = Counter(str(item["name"] or "").strip() for item in mentions)
    return sorted(counts, key=lambda name: (-counts[name], -len(name), name))[0]


def _aliases_for_group(
    entity: dict[str, str],
    mentions: list[dict[str, Any]],
) -> list[str]:
    aliases = {str(item["name"] or "").strip() for item in mentions if str(item["name"] or "").strip()}
    aliases.add(entity["canonical_name"])
    return sorted(aliases, key=lambda value: (normalize_entity_name(value), value))


def _document_count(conn: sqlite3.Connection, chunk_ids: list[str]) -> int:
    if not _table_exists(conn, "chunks"):
        return 0
    unique_chunk_ids = sorted(set(chunk_ids))
    if not unique_chunk_ids:
        return 0
    placeholders = ",".join("?" for _ in unique_chunk_ids)
    return conn.execute(
        f"SELECT COUNT(DISTINCT document_id) FROM chunks WHERE chunk_id IN ({placeholders})",
        unique_chunk_ids,
    ).fetchone()[0]


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()[0]
        > 0
    )


def _create_index_if_table_exists(
    conn: sqlite3.Connection,
    table: str,
    index_name: str,
    columns: str,
) -> None:
    if _table_exists(conn, table):
        conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({columns})")


def _resolved_entity_id(canonical_type: str, canonical_name: str, entity_status: str) -> str:
    digest = hashlib.sha1(
        f"{entity_status}\0{canonical_type}\0{normalize_entity_name(canonical_name)}".encode("utf-8")
    ).hexdigest()[:16]
    return f"resolved-entity-{digest}"


def _alias_id(resolved_entity_id: str, alias: str) -> str:
    digest = hashlib.sha1(
        f"{resolved_entity_id}\0{normalize_entity_name(alias)}".encode("utf-8")
    ).hexdigest()[:16]
    return f"entity-alias-{digest}"


def _key_to_text(key: tuple[str, str, str]) -> str:
    return "\0".join(key)


def _one(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> dict[str, Any]:
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {}
    finally:
        conn.row_factory = original_row_factory


def _many(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    original_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.row_factory = original_row_factory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve Phase 3 entity mentions into v0 canonical entities in SQLite.",
    )
    parser.add_argument("--phase3-db", default=str(DEFAULT_PHASE3_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
