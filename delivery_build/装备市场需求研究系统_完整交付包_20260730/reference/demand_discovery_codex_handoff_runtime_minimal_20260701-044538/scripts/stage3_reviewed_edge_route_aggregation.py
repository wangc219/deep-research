"""Thin CLI for Stage 3 reviewed-edge route aggregation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.route_governance.reviewed_edge_aggregation import (  # noqa: E402
    DEFAULT_INPUT_DB,
    DEFAULT_OUTPUT_DB,
    DEFAULT_REPORT,
    generate_routes_from_reviewed_edges,
)


def main() -> int:
    args = _parse_args()
    summary = generate_routes_from_reviewed_edges(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
        max_routes=args.max_routes,
        report_path=Path(args.report).expanduser().resolve() if args.report else None,
    )
    print("stage3_reviewed_edge_route_aggregation_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-routes", type=int, default=50000)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
