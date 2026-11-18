#!/usr/bin/env python3
"""从五种同源检索快照生成隐藏方法名称的人工评审包。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.graph_retrieval_review import prepare_blinded_graph_retrieval_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="检索运行快照 JSON 数组")
    parser.add_argument("--review-output", required=True, help="可分发给审核人的盲审 JSON")
    parser.add_argument("--key-output", required=True, help="仅由评测负责人保存的方法映射 JSON")
    args = parser.parse_args()

    records = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("输入必须是 JSON 数组")
    review, key = prepare_blinded_graph_retrieval_review(records)
    _write_json(Path(args.review_output), review)
    _write_json(Path(args.key_output), key)
    print(json.dumps({"review_output": args.review_output, "key_output": args.key_output}, ensure_ascii=False))
    return 0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
