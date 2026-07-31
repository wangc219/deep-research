"""Thin CLI for Stage 2.9 reviewed relation projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.relation_governance.corrections import apply_relation_review_corrections  # noqa: E402


DEFAULT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "stage2_relation_enhanced_v2_research.sqlite"
)


def main() -> int:
    args = _parse_args()
    summary = apply_relation_review_corrections(
        db_path=Path(args.db).expanduser().resolve(),
        force=args.force,
    )
    print("stage2_relation_review_correction_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Stage 2.8 relation review corrections.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
