#!/usr/bin/env python3
"""评估 LightRAG 受约束路径重排相对确定性排序的真实增益。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.lightrag_path_reranking_evaluation import evaluate_path_reranking


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="脱敏成对路径排序与人工判断 JSON")
    parser.add_argument("--output", required=True, help="脱敏评测报告 JSON")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = evaluate_path_reranking(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "passed": report["passed"]}, ensure_ascii=False))
    return 2 if args.require_pass and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
