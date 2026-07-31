"""Export Phase 1-style SQLite extraction rows to standard ExtractionResult JSONL."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(EXPERIMENT_ROOT))

from evaluator import evaluate_group, write_evaluation_summary  # noqa: E402
from models import ExtractionResult, load_chunks, load_results  # noqa: E402


DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr_llm_v3_all_chunks"
    / "v3_all_chunks.sqlite"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr_llm_v3_all_chunks"
    / "group_a_schema_guided"
    / "extraction_results.jsonl"
)
DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr"
    / "chunks.jsonl"
)


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    chunks_path = Path(args.chunks).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    summary = export_results_from_db(db_path=db_path, output_path=output_path)
    print("export_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if args.write_evaluation:
        results = load_results(output_path)
        chunks = load_chunks(chunks_path)
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        evaluation = evaluate_group("group_a_schema_guided", results, chunks_by_id)
        summary_dir = output_path.parents[1]
        write_evaluation_summary(summary_dir, [evaluation], skipped_groups=[])
        print(f"wrote {summary_dir / 'evaluation_summary.json'}")
        print(f"wrote {summary_dir / 'evaluation_summary.md'}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Phase 1 SQLite payload_json rows to ExtractionResult JSONL.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument(
        "--no-write-evaluation",
        dest="write_evaluation",
        action="store_false",
        help="Only export JSONL; do not write evaluation_summary files.",
    )
    parser.set_defaults(write_evaluation=True)
    return parser.parse_args()


def export_results_from_db(db_path: Path, output_path: Path) -> dict[str, Any]:
    rows = _read_rows(db_path)
    exported: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    skipped_reasons: Counter[str] = Counter()

    for row in rows:
        status = str(row["status"])
        status_counts[status] += 1
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            skipped_reasons["invalid_json_payload"] += 1
            continue
        if not _is_extraction_result_payload(payload):
            skipped_reasons["non_extraction_payload"] += 1
            continue
        result = ExtractionResult.from_dict(payload)
        exported.append(result.to_dict())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for payload in exported:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return {
        "db_path": str(db_path),
        "output_path": str(output_path),
        "rows_seen": len(rows),
        "rows_exported": len(exported),
        "rows_skipped": len(rows) - len(exported),
        "status_counts": dict(sorted(status_counts.items())),
        "skipped_reasons": dict(sorted(skipped_reasons.items())),
    }


def _read_rows(db_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(
            conn.execute(
                """
                SELECT id, chunk_id, payload_json, status
                FROM extractions
                ORDER BY id
                """
            ).fetchall()
        )
    finally:
        conn.close()


def _is_extraction_result_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    required = {"task_id", "adapter_name", "document_id", "chunk_id"}
    return required.issubset(payload)


if __name__ == "__main__":
    raise SystemExit(main())
