"""Prepare a broad 100-document Markdown sample for extraction diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.diagnostic_sampling import (  # noqa: E402
    DEFAULT_JOURNALS,
    build_chunks_for_documents,
    discover_markdown_documents,
    select_probe_chunks,
    select_diagnostic_sample,
    write_sample_outputs,
)


DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
)


def main() -> int:
    args = parse_args()
    processed_root = Path(args.processed_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    documents = discover_markdown_documents(
        processed_root=processed_root,
        journals=args.journal,
    )
    selected, summary = select_diagnostic_sample(
        documents,
        target_count=args.target_count,
    )
    chunks = build_chunks_for_documents(selected, max_chars=args.max_chars)
    probe_chunks = select_probe_chunks(chunks, per_document=args.probe_chunks_per_doc)
    write_sample_outputs(
        documents=selected,
        chunks=chunks,
        output_dir=output_dir,
        summary=summary,
        probe_chunks=probe_chunks,
    )
    payload = {
        **summary,
        "processed_root": str(processed_root),
        "output_dir": str(output_dir),
        "chunk_count": len(chunks),
        "probe_chunk_count": len(probe_chunks),
        "chunks_path": str(output_dir / "chunks.jsonl"),
        "probe_chunks_path": str(output_dir / "chunks_probe_one_per_doc.jsonl"),
        "sample_manifest": str(output_dir / "sample_manifest_100.jsonl"),
    }
    print("literature_diagnostic_sample_summary=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if len(selected) < args.target_count:
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a broad Markdown diagnostic sample and standardized chunks.",
    )
    parser.add_argument("--processed-root", default=str(PROJECT_ROOT / "data" / "processed"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--target-count", type=int, default=100)
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--probe-chunks-per-doc", type=int, default=1)
    parser.add_argument(
        "--journal",
        action="append",
        default=list(DEFAULT_JOURNALS),
        help="Journal/source to include. Can be repeated.",
    )
    args = parser.parse_args()
    if args.target_count <= 0:
        parser.error("--target-count must be > 0")
    if args.max_chars <= 0:
        parser.error("--max-chars must be > 0")
    if args.probe_chunks_per_doc <= 0:
        parser.error("--probe-chunks-per-doc must be > 0")
    return args


if __name__ == "__main__":
    raise SystemExit(main())
