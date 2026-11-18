"""为经人工确认的页树根缺失 PDF 生成不覆盖原件的本地候选副本。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from platform_core.knowledge.training.pilot_pdf_repair import repair_missing_pages_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--pages-root-object", required=True, type=int)
    parser.add_argument("--page-object-ids", required=True, help="逗号分隔的 Page 对象编号")
    args = parser.parse_args()

    logging.disable(logging.WARNING)
    report_path = Path(args.report).expanduser().resolve()
    if report_path.exists():
        raise SystemExit(f"修复报告已存在，拒绝覆盖: {report_path}")
    page_object_ids = [int(value.strip()) for value in args.page_object_ids.split(",") if value.strip()]
    result = repair_missing_pages_root(
        args.source,
        args.output,
        expected_source_sha256=args.expected_source_sha256,
        pages_root_object_id=args.pages_root_object,
        page_object_ids=page_object_ids,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
