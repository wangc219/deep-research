"""Filter non-research documents from a prepared literature diagnostic sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.document_filtering import (  # noqa: E402
    build_filter_summary,
    filter_chunk_rows_by_manifest,
    filter_manifest_rows,
    kept_chunk_ids,
)
from knowledgegraph.extraction.models import read_jsonl, write_jsonl  # noqa: E402


DEFAULT_DATASET_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
)


def main() -> int:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    chunks_path = Path(args.chunks).expanduser().resolve()
    probe_chunks_path = Path(args.probe_chunks).expanduser().resolve()
    output_manifest_path = Path(args.output_manifest).expanduser().resolve()
    output_chunks_path = Path(args.output_chunks).expanduser().resolve()
    output_probe_chunks_path = Path(args.output_probe_chunks).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()

    manifest_rows = read_jsonl(manifest_path)
    chunk_rows = read_jsonl(chunks_path)
    probe_chunk_rows = read_jsonl(probe_chunks_path) if probe_chunks_path.exists() else []

    kept_manifest_rows, excluded_manifest_rows = filter_manifest_rows(manifest_rows)
    kept_chunk_rows = filter_chunk_rows_by_manifest(chunk_rows, kept_manifest_rows)
    kept_probe_chunk_rows = filter_chunk_rows_by_manifest(probe_chunk_rows, kept_manifest_rows)

    write_jsonl(output_manifest_path, kept_manifest_rows)
    write_jsonl(output_chunks_path, kept_chunk_rows)
    if probe_chunk_rows:
        write_jsonl(output_probe_chunks_path, kept_probe_chunk_rows)

    summary = build_filter_summary(
        manifest_rows=manifest_rows,
        kept_manifest_rows=kept_manifest_rows,
        excluded_manifest_rows=excluded_manifest_rows,
        chunk_rows=chunk_rows,
        kept_chunk_rows=kept_chunk_rows,
        probe_chunk_rows=probe_chunk_rows,
        kept_probe_chunk_rows=kept_probe_chunk_rows,
    )
    summary.update(
        {
            "dataset_dir": str(dataset_dir),
            "manifest_path": str(manifest_path),
            "chunks_path": str(chunks_path),
            "probe_chunks_path": str(probe_chunks_path),
            "output_manifest_path": str(output_manifest_path),
            "output_chunks_path": str(output_chunks_path),
            "output_probe_chunks_path": str(output_probe_chunks_path),
            "report_path": str(report_path),
        }
    )

    source_db = Path(args.source_db).expanduser().resolve() if args.source_db else None
    filtered_db = Path(args.filtered_db).expanduser().resolve() if args.filtered_db else None
    if source_db and filtered_db:
        db_summary = copy_filtered_extractions_db(
            source_db=source_db,
            filtered_db=filtered_db,
            chunk_ids=kept_chunk_ids(kept_chunk_rows),
        )
        summary.update(db_summary)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print("document_filter_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def copy_filtered_extractions_db(
    source_db: Path,
    filtered_db: Path,
    chunk_ids: set[str],
) -> dict[str, Any]:
    if not source_db.exists():
        raise FileNotFoundError(f"source SQLite not found: {source_db}")
    filtered_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_db) as source_conn, sqlite3.connect(filtered_db) as target_conn:
        schema_row = source_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='extractions'"
        ).fetchone()
        if schema_row is None or not schema_row[0]:
            raise ValueError(f"source SQLite has no extractions table: {source_db}")
        columns = [
            str(row[1])
            for row in source_conn.execute("PRAGMA table_info(extractions)").fetchall()
        ]
        if "chunk_id" not in columns:
            raise ValueError("source extractions table has no chunk_id column")
        target_conn.execute("DROP TABLE IF EXISTS extractions")
        target_conn.execute(str(schema_row[0]))
        source_total = int(source_conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0])
        copied = 0
        if chunk_ids:
            ordered_ids = sorted(chunk_ids)
            column_sql = ", ".join(columns)
            placeholders = ", ".join("?" for _ in columns)
            for start in range(0, len(ordered_ids), 900):
                batch = ordered_ids[start : start + 900]
                id_placeholders = ", ".join("?" for _ in batch)
                rows = source_conn.execute(
                    f"SELECT {column_sql} FROM extractions WHERE chunk_id IN ({id_placeholders})",
                    batch,
                ).fetchall()
                if rows:
                    target_conn.executemany(
                        f"INSERT INTO extractions ({column_sql}) VALUES ({placeholders})",
                        rows,
                    )
                    copied += len(rows)
        target_conn.commit()
    return {
        "source_db_path": str(source_db),
        "filtered_db_path": str(filtered_db),
        "source_db_row_count": source_total,
        "filtered_db_row_count": copied,
        "excluded_db_row_count": source_total - copied,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter explicit non-research documents from the 100-doc diagnostic sample.",
    )
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_DATASET_DIR / "sample_manifest_100.jsonl"),
    )
    parser.add_argument("--chunks", default=str(DEFAULT_DATASET_DIR / "chunks.jsonl"))
    parser.add_argument(
        "--probe-chunks",
        default=str(DEFAULT_DATASET_DIR / "chunks_probe_one_per_doc.jsonl"),
    )
    parser.add_argument(
        "--output-manifest",
        default=str(DEFAULT_DATASET_DIR / "sample_manifest_research.jsonl"),
    )
    parser.add_argument(
        "--output-chunks",
        default=str(DEFAULT_DATASET_DIR / "chunks_research.jsonl"),
    )
    parser.add_argument(
        "--output-probe-chunks",
        default=str(DEFAULT_DATASET_DIR / "chunks_probe_one_per_doc_research.jsonl"),
    )
    parser.add_argument(
        "--source-db",
        default=str(DEFAULT_DATASET_DIR / "codex_gpt_5_5_full_chunks.sqlite"),
    )
    parser.add_argument(
        "--filtered-db",
        default=str(DEFAULT_DATASET_DIR / "codex_gpt_5_5_full_chunks_research.sqlite"),
    )
    parser.add_argument(
        "--report",
        default=str(DEFAULT_DATASET_DIR / "sample_filter_report.json"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
