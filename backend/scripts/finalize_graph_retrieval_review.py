#!/usr/bin/env python3
"""校验已完成人工盲审的检索包并恢复正式评测输入。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.graph_retrieval_review import finalize_blinded_graph_retrieval_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, help="审核人完成的盲审 JSON")
    parser.add_argument("--key", required=True, help="评测负责人保存的方法映射 JSON")
    parser.add_argument("--output", required=True, help="GraphRetrievalQualityCase JSON")
    args = parser.parse_args()

    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    if not isinstance(review, dict) or not isinstance(key, dict):
        raise ValueError("review 与 key 必须是 JSON 对象")
    output = finalize_blinded_graph_retrieval_review(review, key)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(destination), "case_count": len(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
