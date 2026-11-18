#!/usr/bin/env python3
"""合并 AutoDL train/dev 响应与本地密封 test，生成 1000 篇统一弱监督预标。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.military_corpus_prelabel import (
    assemble_military_corpus_prelabels,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu-responses", type=Path, required=True)
    parser.add_argument("--local-test", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = assemble_military_corpus_prelabels(
        args.gpu_responses.expanduser().resolve(),
        args.local_test.expanduser().resolve(),
        args.output.expanduser().resolve(),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
