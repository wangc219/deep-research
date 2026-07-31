"""Run seven-relation extraction chunks through the local Codex CLI.

This runner is intentionally narrow: it treats Codex as the LLM transport for
the existing seven-relation extraction prompt, then writes the same minimal
SQLite table used by ``run_all_chunks.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.extraction.adapters import LLMSevenRelationSchemaGuidedAdapter  # noqa: E402
from knowledgegraph.material_governance.extraction.codex_chunk_runner import (  # noqa: E402
    CodexInvocationConfig as MaterialCodexInvocationConfig,
    run_codex_chunk_extraction,
)


DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_3_gold_guided"
    / "chunks_visible_gold_guided.jsonl"
)
DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_3_gold_guided"
    / "codex_gpt_5_5_visible_extractions.sqlite"
)
DEFAULT_CODEX_HOME = Path(r"D:\tmp\codex-rag-labeling-no-mcp")
ADAPTER_NAME = "group_a_schema_guided_v4_codex"
PROMPT_VERSION = LLMSevenRelationSchemaGuidedAdapter.prompt_version


def main() -> int:
    args = _parse_args()
    config = MaterialCodexInvocationConfig(
        codex_home=Path(args.codex_home).expanduser().resolve(),
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        timeout_seconds=args.timeout_seconds,
    )
    summary = run_codex_chunk_extraction(
        input_chunks_path=Path(args.chunks).expanduser().resolve(),
        output_db_path=Path(args.db).expanduser().resolve(),
        project_root=PROJECT_ROOT,
        codex_config=config,
        limit=args.limit,
        worker_count=args.workers,
        force=args.force,
        retry_failed=args.retry_failed,
        max_new=args.max_new,
        batch_size=args.batch_size,
        chunk_ids=args.chunk_id,
        summary_only=args.summary_only,
    )
    print("codex_extraction_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run visible route-discovery chunks through local Codex CLI extraction.",
    )
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME))
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--chunk-id",
        action="append",
        default=[],
        help="Process only this chunk_id. Can be repeated. Applied before --limit.",
    )
    parser.add_argument("--max-new", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Submit at most this many Codex invocations per batch; 0 submits all pending chunks.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be > 0")
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.max_new < 0:
        parser.error("--max-new must be >= 0")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.batch_size < 0:
        parser.error("--batch-size must be >= 0")
    return args


if __name__ == "__main__":
    raise SystemExit(main())
