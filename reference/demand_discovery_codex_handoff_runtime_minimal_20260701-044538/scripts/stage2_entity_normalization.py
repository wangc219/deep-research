"""Stage 2 entity normalization CLI.

The reusable implementation lives in
``knowledgegraph.material_governance.entity_normalization``. This script is kept
as a compatibility command-line entrypoint.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.entity_normalization import (  # noqa: E402
    normalize_extraction_sqlite,
)


DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "route_discovery_visible_v4_3_gold_guided"
    / "codex_gpt_5_5_visible_extractions.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "stage2_entity_normalization_v1"
    / "stage2_entity_normalization.sqlite"
)


def main() -> int:
    args = _parse_args()
    output_db = Path(args.output_db).expanduser().resolve()
    if output_db.exists() and not args.force:
        raise SystemExit(f"Output DB already exists; use --force to replace: {output_db}")
    summary = normalize_extraction_sqlite(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=output_db,
        overwrite=args.force,
    )
    print("stage2_entity_normalization_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize extracted entity mentions from a Stage 1 extraction SQLite DB.",
    )
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
