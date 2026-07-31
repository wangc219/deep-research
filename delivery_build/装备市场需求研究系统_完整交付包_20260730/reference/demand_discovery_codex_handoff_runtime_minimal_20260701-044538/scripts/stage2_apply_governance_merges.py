"""Apply reviewed same-entity merge candidates from Stage 2.5.

This stage consumes a Stage 2.5 governance SQLite database and writes a new
SQLite database. It applies only ``same_entity`` alias candidate reviews; other
review decisions remain audit evidence and are not merged.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.governance.entity_path_policy import (  # noqa: E402
    POLICY_VERSION,
    classify_entity_path_policy,
)

DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "stage2_entity_normalization_v1"
    / "stage2_entity_model_governance.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "stage2_entity_normalization_v1"
    / "stage2_entity_merged.sqlite"
)

MERGE_RULE_VERSION = "stage2-apply-governance-merges-v1"


def main() -> int:
    args = _parse_args()
    summary = apply_governance_merges(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
    )
    print("stage2_apply_governance_merges_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def apply_governance_merges(
    input_db: Path,
    output_db: Path,
    overwrite: bool = True,
) -> dict[str, Any]:
    if not input_db.exists():
        raise FileNotFoundError(f"Input Stage 2.5 governance DB not found: {input_db}")
    if output_db.exists() and overwrite:
        output_db.unlink()
    if output_db.exists():
        raise FileExistsError(f"Output DB already exists; use --force to replace: {output_db}")
    output_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_db, output_db)

    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            ensure_merge_schema(conn)
            groups = _build_same_entity_groups(conn)
            summary = _apply_groups(conn, groups)
            _insert_run(conn, input_db, output_db, summary)
        summary.update(
            {
                "input_db": str(input_db),
                "output_db": str(output_db),
                "merge_rule_version": MERGE_RULE_VERSION,
            }
        )
        return summary
    finally:
        conn.close()


def ensure_merge_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_merge_groups (
            group_id TEXT PRIMARY KEY,
            representative_resolved_entity_id TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_type TEXT NOT NULL,
            canonical_layer TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            mention_count INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            document_count INTEGER NOT NULL,
            source_review_count INTEGER NOT NULL,
            apply_status TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entity_merge_group_members (
            group_id TEXT NOT NULL,
            member_resolved_entity_id TEXT NOT NULL,
            member_name TEXT NOT NULL,
            member_type TEXT NOT NULL,
            member_mention_count INTEGER NOT NULL,
            apply_status TEXT NOT NULL,
            PRIMARY KEY(group_id, member_resolved_entity_id),
            FOREIGN KEY(group_id) REFERENCES entity_merge_groups(group_id)
        );

        CREATE TABLE IF NOT EXISTS entity_merge_source_reviews (
            group_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            left_resolved_entity_id TEXT NOT NULL,
            right_resolved_entity_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            review_model TEXT NOT NULL,
            review_note TEXT NOT NULL,
            PRIMARY KEY(group_id, candidate_id),
            FOREIGN KEY(group_id) REFERENCES entity_merge_groups(group_id)
        );

        CREATE TABLE IF NOT EXISTS stage2_merge_apply_runs (
            run_id TEXT PRIMARY KEY,
            merge_rule_version TEXT NOT NULL,
            input_db TEXT NOT NULL,
            output_db TEXT NOT NULL,
            same_entity_review_count INTEGER NOT NULL,
            applied_merge_group_count INTEGER NOT NULL,
            skipped_merge_group_count INTEGER NOT NULL,
            merged_member_entity_count INTEGER NOT NULL,
            updated_mention_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_merge_members_member
            ON entity_merge_group_members(member_resolved_entity_id);

        CREATE TABLE IF NOT EXISTS entity_governance_annotations (
            resolved_entity_id TEXT PRIMARY KEY,
            path_eligibility TEXT NOT NULL,
            weight_multiplier REAL NOT NULL,
            granularity_label TEXT NOT NULL,
            governance_reason TEXT NOT NULL,
            governance_source TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_entity_governance_path
            ON entity_governance_annotations(path_eligibility);
        """
    )


def _build_same_entity_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    entities = {
        row["resolved_entity_id"]: dict(row)
        for row in conn.execute(
            """
            SELECT resolved_entity_id, canonical_name, canonical_type, canonical_layer,
                   entity_status, alias_json, mention_count, chunk_count, document_count
            FROM resolved_entities
            """
        )
    }
    parents = {entity_id: entity_id for entity_id in entities}

    def find(entity_id: str) -> str:
        parents.setdefault(entity_id, entity_id)
        while parents[entity_id] != entity_id:
            parents[entity_id] = parents[parents[entity_id]]
            entity_id = parents[entity_id]
        return entity_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    reviews = [dict(row) for row in conn.execute(
        """
        SELECT c.candidate_id, c.left_resolved_entity_id, c.right_resolved_entity_id,
               r.decision, r.review_model, r.review_note
        FROM entity_alias_candidates c
        JOIN entity_alias_candidate_reviews r ON c.candidate_id = r.candidate_id
        WHERE r.decision = 'same_entity'
        ORDER BY c.candidate_id
        """
    )]
    for review in reviews:
        left = str(review["left_resolved_entity_id"])
        right = str(review["right_resolved_entity_id"])
        if left in entities and right in entities:
            union(left, right)

    members_by_root: dict[str, set[str]] = defaultdict(set)
    for entity_id in entities:
        members_by_root[find(entity_id)].add(entity_id)

    reviews_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        left = str(review["left_resolved_entity_id"])
        if left in entities:
            reviews_by_group[find(left)].append(review)

    groups = []
    for root, members in members_by_root.items():
        if len(members) <= 1:
            continue
        group_entities = [entities[member] for member in sorted(members)]
        groups.append(
            {
                "root": root,
                "members": group_entities,
                "reviews": reviews_by_group.get(root, []),
            }
        )
    return groups


def _apply_groups(conn: sqlite3.Connection, groups: list[dict[str, Any]]) -> dict[str, Any]:
    same_entity_review_count = _count_same_entity_reviews(conn)
    applied = 0
    skipped = 0
    merged_members = 0
    updated_mentions = 0
    created_at = _now()
    for group in groups:
        members = list(group["members"])
        reviews = list(group["reviews"])
        member_ids = [str(member["resolved_entity_id"]) for member in members]
        types = {str(member["canonical_type"]) for member in members}
        if len(types) != 1:
            skipped += 1
            _record_group(
                conn,
                group,
                group_id=_group_id(member_ids),
                apply_status="skipped",
                reason="mixed canonical_type",
                created_at=created_at,
            )
            continue

        representative = _choose_representative(members)
        group_id = _group_id(member_ids)
        alias_values = _collect_aliases(members)
        mention_stats = _mention_stats(conn, member_ids)
        conn.execute(
            """
            INSERT OR REPLACE INTO resolved_entities (
                resolved_entity_id, canonical_name, canonical_type, canonical_layer,
                entity_status, resolution_rule, alias_json, mention_count,
                chunk_count, document_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id,
                representative["canonical_name"],
                representative["canonical_type"],
                representative["canonical_layer"],
                "active",
                "model_governance_same_entity_merge",
                json.dumps(alias_values, ensure_ascii=False, sort_keys=True),
                mention_stats["mention_count"],
                mention_stats["chunk_count"],
                mention_stats["document_count"],
                created_at,
            ),
        )
        conn.execute(
            f"""
            UPDATE entity_mentions
            SET resolved_entity_id = ?,
                resolution_status = 'resolved',
                resolution_rule = 'model_governance_same_entity_merge',
                resolution_note = ?
            WHERE resolved_entity_id IN ({",".join("?" for _ in member_ids)})
            """,
            (
                group_id,
                f"merged {len(member_ids)} entities from same_entity reviews",
                *member_ids,
            ),
        )
        conn.execute(
            f"""
            UPDATE resolved_entities
            SET entity_status = 'merged_into'
            WHERE resolved_entity_id IN ({",".join("?" for _ in member_ids)})
            """,
            member_ids,
        )
        for alias in alias_values:
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_aliases (
                    alias_id, resolved_entity_id, alias, alias_normalized, alias_type,
                    alias_source, status, mention_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _alias_id(group_id, alias),
                    group_id,
                    alias,
                    _normalize_name(alias),
                    "model_governance_same_entity_merge",
                    "stage2.5_same_entity_review",
                    "accepted",
                    _alias_mention_count(conn, alias, group_id),
                ),
            )
        _record_group(
            conn,
            group,
            group_id=group_id,
            apply_status="applied",
            reason="",
            created_at=created_at,
            stats=mention_stats,
        )
        for member in members:
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_merge_group_members (
                    group_id, member_resolved_entity_id, member_name, member_type,
                    member_mention_count, apply_status
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    member["resolved_entity_id"],
                    member["canonical_name"],
                    member["canonical_type"],
                    member["mention_count"],
                    "applied",
                ),
            )
        for review in reviews:
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_merge_source_reviews (
                    group_id, candidate_id, left_resolved_entity_id,
                    right_resolved_entity_id, decision, review_model, review_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    review["candidate_id"],
                    review["left_resolved_entity_id"],
                    review["right_resolved_entity_id"],
                    review["decision"],
                    review["review_model"],
                    review["review_note"],
                ),
            )
        applied += 1
        merged_members += len(member_ids)
        updated_mentions += int(mention_stats["mention_count"])
    annotation_summary = _refresh_entity_governance_annotations(conn, created_at)
    return {
        "same_entity_review_count": same_entity_review_count,
        "applied_merge_group_count": applied,
        "skipped_merge_group_count": skipped,
        "merged_member_entity_count": merged_members,
        "updated_mention_count": updated_mentions,
        **annotation_summary,
    }


def _refresh_entity_governance_annotations(conn: sqlite3.Connection, created_at: str) -> dict[str, int]:
    conn.execute("DELETE FROM entity_governance_annotations")
    rows = conn.execute(
        """
        SELECT resolved_entity_id, canonical_name, canonical_type, canonical_layer,
               entity_status, alias_json, mention_count, chunk_count, document_count
        FROM resolved_entities
        WHERE entity_status = 'active'
        """
    ).fetchall()
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        policy = classify_entity_path_policy(dict(row))
        counts[policy.path_eligibility] += 1
        conn.execute(
            """
            INSERT OR REPLACE INTO entity_governance_annotations (
                resolved_entity_id, path_eligibility, weight_multiplier,
                granularity_label, governance_reason, governance_source,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["resolved_entity_id"],
                policy.path_eligibility,
                policy.weight_multiplier,
                policy.granularity_label,
                policy.governance_reason,
                POLICY_VERSION,
                created_at,
            ),
        )
    return {
        "entity_governance_annotation_count": len(rows),
        "path_safe_entity_count": counts.get("path_safe", 0),
        "limited_entity_count": counts.get("limited", 0),
        "review_required_entity_count": counts.get("review_required", 0),
        "excluded_entity_count": counts.get("excluded", 0),
    }


def _record_group(
    conn: sqlite3.Connection,
    group: dict[str, Any],
    group_id: str,
    apply_status: str,
    reason: str,
    created_at: str,
    stats: dict[str, int] | None = None,
) -> None:
    members = list(group["members"])
    representative = _choose_representative(members)
    member_ids = [str(member["resolved_entity_id"]) for member in members]
    if stats is None:
        stats = _mention_stats(conn, member_ids)
    conn.execute(
        """
        INSERT OR REPLACE INTO entity_merge_groups (
            group_id, representative_resolved_entity_id, canonical_name,
            canonical_type, canonical_layer, member_count, mention_count,
            chunk_count, document_count, source_review_count, apply_status,
            reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            group_id,
            representative["resolved_entity_id"],
            representative["canonical_name"],
            representative["canonical_type"],
            representative["canonical_layer"],
            len(member_ids),
            stats["mention_count"],
            stats["chunk_count"],
            stats["document_count"],
            len(group.get("reviews", [])),
            apply_status,
            reason,
            created_at,
        ),
    )


def _insert_run(
    conn: sqlite3.Connection,
    input_db: Path,
    output_db: Path,
    summary: dict[str, Any],
) -> None:
    created_at = _now()
    run_id = "stage2-merge-run-" + _sha1(f"{input_db}\0{output_db}\0{created_at}")[:16]
    conn.execute(
        """
        INSERT INTO stage2_merge_apply_runs (
            run_id, merge_rule_version, input_db, output_db,
            same_entity_review_count, applied_merge_group_count,
            skipped_merge_group_count, merged_member_entity_count,
            updated_mention_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            MERGE_RULE_VERSION,
            str(input_db),
            str(output_db),
            summary["same_entity_review_count"],
            summary["applied_merge_group_count"],
            summary["skipped_merge_group_count"],
            summary["merged_member_entity_count"],
            summary["updated_mention_count"],
            created_at,
        ),
    )


def _count_same_entity_reviews(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM entity_alias_candidate_reviews WHERE decision = 'same_entity'"
        ).fetchone()[0]
    )


def _choose_representative(members: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        members,
        key=lambda item: (
            -int(item["document_count"] or 0),
            -int(item["mention_count"] or 0),
            len(str(item["canonical_name"] or "")),
            str(item["canonical_name"] or ""),
        ),
    )[0]


def _collect_aliases(members: list[dict[str, Any]]) -> list[str]:
    aliases: set[str] = set()
    for member in members:
        aliases.add(str(member["canonical_name"]))
        try:
            aliases.update(str(alias) for alias in json.loads(member["alias_json"] or "[]"))
        except json.JSONDecodeError:
            pass
    return sorted(alias for alias in aliases if alias.strip())


def _mention_stats(conn: sqlite3.Connection, member_ids: list[str]) -> dict[str, int]:
    if not member_ids:
        return {"mention_count": 0, "chunk_count": 0, "document_count": 0}
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS mention_count,
               COUNT(DISTINCT chunk_id) AS chunk_count,
               COUNT(DISTINCT document_id) AS document_count
        FROM entity_mentions
        WHERE resolved_entity_id IN ({",".join("?" for _ in member_ids)})
        """,
        member_ids,
    ).fetchone()
    return {
        "mention_count": int(row["mention_count"] or 0),
        "chunk_count": int(row["chunk_count"] or 0),
        "document_count": int(row["document_count"] or 0),
    }


def _alias_mention_count(conn: sqlite3.Connection, alias: str, group_id: str) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM entity_mentions
            WHERE resolved_entity_id = ? AND name = ?
            """,
            (group_id, alias),
        ).fetchone()[0]
    )


def _group_id(member_ids: list[str]) -> str:
    digest = _sha1("\0".join(sorted(member_ids)))[:16]
    return f"merged-entity-{digest}"


def _alias_id(resolved_entity_id: str, alias: str) -> str:
    digest = _sha1(f"{resolved_entity_id}\0{_normalize_name(alias)}")[:16]
    return f"entity-alias-{digest}"


def _normalize_name(value: str) -> str:
    return "".join(str(value).strip().lower().split())


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Stage 2.5 same_entity merge reviews to a new SQLite DB.")
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
