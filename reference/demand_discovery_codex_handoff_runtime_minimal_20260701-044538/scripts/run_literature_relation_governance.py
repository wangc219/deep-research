"""Run the material literature relation-governance pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.material_governance.pipeline import (  # noqa: E402
    MaterialGovernancePipelineConfig,
    run_material_governance_pipeline,
    selected_stage_names,
)


DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "pipelines" / "literature_100_doc_diagnostic_v1.json"


def main() -> int:
    args = _parse_args()
    config = MaterialGovernancePipelineConfig.from_json(args.config)
    if args.dry_run:
        for stage_name in selected_stage_names(config, from_stage=args.from_stage, to_stage=args.to_stage):
            print(stage_name)
        return 0
    manifest = run_material_governance_pipeline(
        config,
        from_stage=args.from_stage,
        to_stage=args.to_stage,
        skip_existing=args.skip_existing,
        force_stages=set(args.force_stage or []),
    )
    print("material_governance_pipeline_manifest=" + json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--from-stage")
    parser.add_argument("--to-stage")
    parser.add_argument("--skip-existing", dest="skip_existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    parser.add_argument("--force-stage", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
