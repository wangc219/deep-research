"""Thin CLI for Stage 2.7 relation read model generation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.relation_governance.read_model import enhance_relation_data  # noqa: E402


DEFAULT_INPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "stage2_entity_governance_v2_research.sqlite"
)
DEFAULT_OUTPUT_DB = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "literature_100_doc_diagnostic_v1"
    / "stage2_relation_enhanced_v2_research.sqlite"
)


def main() -> int:
    args = _parse_args()
    summary = enhance_relation_data(
        input_db=Path(args.input_db).expanduser().resolve(),
        output_db=Path(args.output_db).expanduser().resolve(),
        overwrite=args.force,
    )
    print("stage2_relation_data_enhancement_summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage 2.7 relation governance and canonical relation edges.")
    parser.add_argument("--input-db", default=str(DEFAULT_INPUT_DB))
    parser.add_argument("--output-db", default=str(DEFAULT_OUTPUT_DB))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
