"""Thin CLI for Stage 2.8 canonical relation review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.relation_governance import review as relation_review  # noqa: E402


DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "stage2_relation_enhanced_v2_research.sqlite"
)
DEFAULT_CHUNKS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "chunks_research.jsonl"
)


def main() -> int:
    args = _parse_args()
    reviewer_factory = relation_review.build_reviewer_factory(args.review_provider, args)
    summary = relation_review.review_canonical_relations(
        db_path=Path(args.db).expanduser().resolve(),
        chunks_path=Path(args.chunks).expanduser().resolve(),
        reviewer_factory=reviewer_factory,
        priority_tier=args.priority_tier,
        relation_types=args.relation_type,
        max_edges=None if args.max_edges <= 0 else args.max_edges,
        batch_size=args.batch_size,
        workers=args.workers,
        review_provider=args.review_provider,
        force=args.force_review,
    )
    print("stage2_canonical_relation_review_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Stage 2.8 canonical relation review queue.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--chunks", default=str(DEFAULT_CHUNKS))
    parser.add_argument("--review-provider", choices=["codex", "llm", "fake"], default="codex")
    parser.add_argument("--codex-home", default=str(relation_review.DEFAULT_CODEX_HOME))
    parser.add_argument("--codex-model", default=relation_review.DEFAULT_CODEX_MODEL)
    parser.add_argument("--codex-reasoning-effort", default=relation_review.DEFAULT_CODEX_REASONING_EFFORT)
    parser.add_argument("--codex-timeout-seconds", type=int, default=relation_review.DEFAULT_CODEX_TIMEOUT_SECONDS)
    parser.add_argument("--priority-tier", choices=["P0", "P1", "P2"], default="P0")
    parser.add_argument(
        "--relation-type",
        action="append",
        choices=sorted(relation_review.RELATION_TYPES),
        help="Filter queue to one relation type. Repeat to include multiple types.",
    )
    parser.add_argument("--max-edges", type=int, default=20, help="Maximum edges to review; use 0 for all matching pending edges.")
    parser.add_argument("--batch-size", type=int, default=relation_review.DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=relation_review.DEFAULT_WORKERS)
    parser.add_argument("--force-review", action="store_true")
    args = parser.parse_args()
    if int(args.batch_size) <= 0:
        parser.error("--batch-size must be > 0")
    if int(args.workers) <= 0:
        parser.error("--workers must be > 0")
    if int(args.codex_timeout_seconds) <= 0:
        parser.error("--codex-timeout-seconds must be > 0")
    return args


if __name__ == "__main__":
    raise SystemExit(main())
