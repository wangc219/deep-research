"""Thin CLI for Stage 3 route model governance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.route_governance import model_review  # noqa: E402


def main() -> int:
    args = _parse_args()
    reviewer_factory = model_review.build_reviewer_factory(args)
    summary = model_review.govern_stage3_routes(
        db_path=Path(args.db).expanduser().resolve(),
        reviewer_factory=reviewer_factory,
        max_routes=args.max_routes,
        max_gap_candidates=args.max_gap_candidates,
        max_cluster_candidates=args.max_cluster_candidates,
        batch_size=args.batch_size,
        workers=args.workers,
        force=args.force,
        retry_failed_routes=args.retry_failed_routes,
        route_review_only=args.route_review_only,
        min_route_confidence=args.min_route_confidence,
        min_gap_confidence=args.min_gap_confidence,
        min_cluster_confidence=args.min_cluster_confidence,
        report_path=Path(args.report).expanduser().resolve() if args.report else None,
    )
    print("stage3_route_model_governance_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(model_review.DEFAULT_DB))
    parser.add_argument("--review-provider", choices=["llm", "codex"], default="codex")
    parser.add_argument("--max-routes", type=int, default=100)
    parser.add_argument("--max-gap-candidates", type=int, default=100)
    parser.add_argument("--max-cluster-candidates", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=model_review.DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=model_review.DEFAULT_WORKERS)
    parser.add_argument("--min-route-confidence", type=float, default=model_review.DEFAULT_MIN_ROUTE_CONFIDENCE)
    parser.add_argument("--min-gap-confidence", type=float, default=model_review.DEFAULT_MIN_GAP_CONFIDENCE)
    parser.add_argument("--min-cluster-confidence", type=float, default=model_review.DEFAULT_MIN_CLUSTER_CONFIDENCE)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--retry-failed-routes", action="store_true")
    parser.add_argument("--route-review-only", action="store_true")
    parser.add_argument("--report", default=str(model_review.DEFAULT_REPORT))
    parser.add_argument("--codex-home", default=str(model_review.DEFAULT_CODEX_HOME))
    parser.add_argument("--codex-model", default="gpt-5.5")
    parser.add_argument("--codex-reasoning-effort", default="high")
    parser.add_argument("--codex-timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be > 0")
    if args.workers <= 0:
        parser.error("--workers must be > 0")
    if args.codex_timeout_seconds <= 0:
        parser.error("--codex-timeout-seconds must be > 0")
    return args


if __name__ == "__main__":
    raise SystemExit(main())
