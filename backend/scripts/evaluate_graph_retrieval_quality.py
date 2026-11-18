#!/usr/bin/env python3
"""从人工判断 JSON 生成 LightRAG 图检索质量与协同增益报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.graph_retrieval_quality import (
    evaluate_graph_retrieval_quality,
    graph_retrieval_quality_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="GraphRetrievalQualityCase 数组 JSON")
    parser.add_argument("--output", required=True)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    source = Path(args.input)
    records = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("输入必须是 JSON 数组")
    report = evaluate_graph_retrieval_quality(records, k=args.k)
    report["gates"] = graph_retrieval_quality_gate(report)
    report["passed"] = all(item["passed"] for item in report["gates"])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "passed": report["passed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
