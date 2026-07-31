"""Build a stratified relation-quality A/B review sample from Phase 4 SQLite.

The script only creates a review manifest. It does not call an LLM, modify the
database, or calculate accuracy without human labels.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(EXPERIMENT_ROOT))

from schema import RELATION_TYPES  # noqa: E402


DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_phase4_entity_resolution_v0"
    / "entity_resolution.sqlite"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "relation_quality_ab" / "sample_manifest.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "manual-review" / "relation_quality_ab_sample_plan.md"
DEFAULT_RELATION_TYPES = [
    "enables",
    "supports",
    "applies_to",
    "implements",
    "addresses",
    "constrains",
    "evolves_to",
    "impacts",
]


@dataclass(frozen=True)
class CandidateRow:
    assertion_id: str
    relation_type: str
    confidence: float
    confidence_bin: str
    content_type: str
    document_title: str
    chunk_id: str
    source: str
    source_type: str
    target: str
    target_type: str
    claim_text: str
    evidence_quote: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    relation_types = parse_relation_types(args.relation_types)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        candidates = fetch_candidates(conn, relation_types)
    finally:
        conn.close()
    sample = stratified_sample(
        candidates,
        sample_size=args.sample_size,
        min_per_relation=args.min_per_relation,
    )
    write_jsonl(output_path, (row.to_dict() for row in sample))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(sample, candidates, db_path, output_path),
        encoding="utf-8",
    )
    print(f"wrote {output_path}")
    print(f"wrote {report_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create relation quality A/B sample manifest.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--min-per-relation", type=int, default=20)
    parser.add_argument(
        "--relation-types",
        default=",".join(DEFAULT_RELATION_TYPES),
        help="Comma-separated relation types to sample. Use 'all' for all schema relation types.",
    )
    return parser.parse_args()


def parse_relation_types(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return sorted(RELATION_TYPES)
    return [item.strip() for item in value.split(",") if item.strip()]


def confidence_bin(confidence: float) -> str:
    if confidence >= 0.9:
        return "high"
    if confidence >= 0.7:
        return "mid"
    return "low"


def fetch_candidates(
    conn: sqlite3.Connection,
    relation_types: list[str],
) -> list[CandidateRow]:
    placeholders = ",".join("?" for _ in relation_types)
    rows = conn.execute(
        f"""
        SELECT
            ra.assertion_id,
            ra.relation_type,
            ra.confidence,
            c.content_type,
            d.title AS document_title,
            c.chunk_id,
            src_re.canonical_name AS source,
            src_re.canonical_type AS source_type,
            tgt_re.canonical_name AS target,
            tgt_re.canonical_type AS target_type,
            GROUP_CONCAT(DISTINCT sc.text) AS claim_text,
            GROUP_CONCAT(DISTINCT es.quote) AS evidence_quote
        FROM relation_assertions ra
        JOIN chunks c ON ra.chunk_id = c.chunk_id
        JOIN documents d ON c.document_id = d.document_id
        JOIN entity_mentions src ON ra.source_mention_id = src.mention_id
        JOIN resolved_entities src_re ON src.resolved_entity_id = src_re.resolved_entity_id
        JOIN entity_mentions tgt ON ra.target_mention_id = tgt.mention_id
        JOIN resolved_entities tgt_re ON tgt.resolved_entity_id = tgt_re.resolved_entity_id
        LEFT JOIN relation_claim_links rcl ON ra.assertion_id = rcl.assertion_id
        LEFT JOIN source_claims sc ON rcl.claim_id = sc.claim_id
        LEFT JOIN evidence_claim_links ecl ON sc.claim_id = ecl.claim_id
        LEFT JOIN evidence_spans es ON ecl.evidence_span_id = es.evidence_span_id
        WHERE ra.relation_type IN ({placeholders})
          AND src.resolution_status = 'resolved'
          AND tgt.resolution_status = 'resolved'
          AND src_re.entity_status = 'active'
          AND tgt_re.entity_status = 'active'
        GROUP BY ra.assertion_id
        ORDER BY ra.relation_type, ra.confidence DESC, d.title, c.chunk_id, ra.assertion_id
        """,
        relation_types,
    ).fetchall()
    return [
        CandidateRow(
            assertion_id=str(row["assertion_id"]),
            relation_type=str(row["relation_type"]),
            confidence=float(row["confidence"] or 0.0),
            confidence_bin=confidence_bin(float(row["confidence"] or 0.0)),
            content_type=str(row["content_type"] or ""),
            document_title=str(row["document_title"] or ""),
            chunk_id=str(row["chunk_id"] or ""),
            source=str(row["source"] or ""),
            source_type=str(row["source_type"] or ""),
            target=str(row["target"] or ""),
            target_type=str(row["target_type"] or ""),
            claim_text=str(row["claim_text"] or ""),
            evidence_quote=str(row["evidence_quote"] or ""),
        )
        for row in rows
    ]


def stratified_sample(
    candidates: list[CandidateRow],
    sample_size: int,
    min_per_relation: int,
) -> list[CandidateRow]:
    picked: list[CandidateRow] = []
    picked_ids: set[str] = set()
    relation_types = sorted({row.relation_type for row in candidates})
    for relation_type in relation_types:
        relation_rows = [row for row in candidates if row.relation_type == relation_type]
        target = min(min_per_relation, len(relation_rows), max(0, sample_size - len(picked)))
        for row in balanced_pick(relation_rows, target, key_fields=("confidence_bin", "content_type", "document_title")):
            if row.assertion_id not in picked_ids:
                picked.append(row)
                picked_ids.add(row.assertion_id)
    if len(picked) >= sample_size:
        return picked[:sample_size]

    remaining = [row for row in candidates if row.assertion_id not in picked_ids]
    for row in round_robin_relation_pick(remaining, sample_size - len(picked)):
        if row.assertion_id not in picked_ids:
            picked.append(row)
            picked_ids.add(row.assertion_id)
    return picked


def round_robin_relation_pick(rows: list[CandidateRow], limit: int) -> list[CandidateRow]:
    if limit <= 0 or not rows:
        return []
    by_relation: dict[str, list[CandidateRow]] = {}
    for row in rows:
        by_relation.setdefault(row.relation_type, []).append(row)
    for relation_type, relation_rows in list(by_relation.items()):
        by_relation[relation_type] = balanced_pick(
            relation_rows,
            len(relation_rows),
            key_fields=("confidence_bin", "content_type", "document_title"),
        )

    selected: list[CandidateRow] = []
    relation_types = sorted(by_relation)
    cursor = 0
    while len(selected) < limit:
        made_progress = False
        for relation_type in relation_types:
            relation_rows = by_relation[relation_type]
            if cursor < len(relation_rows):
                selected.append(relation_rows[cursor])
                made_progress = True
                if len(selected) >= limit:
                    break
        if not made_progress:
            break
        cursor += 1
    return selected


def balanced_pick(
    rows: list[CandidateRow],
    limit: int,
    key_fields: tuple[str, ...],
) -> list[CandidateRow]:
    if limit <= 0 or not rows:
        return []
    buckets: dict[tuple[str, ...], list[CandidateRow]] = {}
    for row in rows:
        key = tuple(str(getattr(row, field)) for field in key_fields)
        buckets.setdefault(key, []).append(row)
    for bucket_rows in buckets.values():
        bucket_rows.sort(key=lambda row: (-row.confidence, row.document_title, row.chunk_id, row.assertion_id))
    selected: list[CandidateRow] = []
    keys = sorted(buckets)
    cursor = 0
    while len(selected) < limit:
        made_progress = False
        for key in keys:
            bucket_rows = buckets[key]
            if cursor < len(bucket_rows):
                selected.append(bucket_rows[cursor])
                made_progress = True
                if len(selected) >= limit:
                    break
        if not made_progress:
            break
        cursor += 1
    return selected


def build_report(
    sample: list[CandidateRow],
    candidates: list[CandidateRow],
    db_path: Path,
    output_path: Path,
) -> str:
    lines = [
        "# Relation Quality A/B Sample Plan",
        "",
        "日期：2026-05-25",
        "",
        "## 范围",
        "",
        f"- 数据库：`{db_path}`",
        f"- 样本清单：`{output_path}`",
        f"- 候选数：`{len(candidates)}`",
        f"- 样本数：`{len(sample)}`",
        "",
        "该清单用于 Prompt v1/v2 A/B 和人工方向/类型审核。它不调用 LLM，不写数据库，也不计算未标注准确率。",
        "",
        "## 样本分布",
        "",
        table(["dimension", "value", "count"], distribution_rows(sample)),
        "",
        "## 人工标注字段建议",
        "",
        "后续标注文件应至少包含：",
        "",
        "```text",
        "assertion_id",
        "label: correct | reversed | wrong_relation | ambiguous",
        "path_safe_label: true | false | needs_review",
        "note",
        "```",
        "",
    ]
    return "\n".join(lines)


def distribution_rows(rows: list[CandidateRow]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for dimension in ["relation_type", "confidence_bin", "content_type", "document_title"]:
        counts: dict[str, int] = {}
        for row in rows:
            value = str(getattr(row, dimension))
            counts[value] = counts.get(value, 0) + 1
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            output.append({"dimension": dimension, "value": value, "count": count})
    return output


def table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    return "\n".join(output)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
