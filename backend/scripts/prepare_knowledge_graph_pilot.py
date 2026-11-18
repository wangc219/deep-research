"""扫描本地论文/专利语料并生成可复现的 Pilot 来源与金标抽样清单。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.pilot_manifest import scan_pilot_corpus, select_gold_documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-root", action="append", default=[], help="论文 PDF 根目录，可重复")
    parser.add_argument("--patent-root", action="append", default=[], help="专利 PDF 根目录，可重复")
    parser.add_argument(
        "--acceptance-language",
        action="append",
        default=[],
        help="本次 Pilot 验收语种，可重复；默认要求 zh 与 en。",
    )
    parser.add_argument("--output-dir", required=True, help="输出 manifest 和报告的目录")
    parser.add_argument("--select-gold", action="store_true", help="同时生成 300 篇金标文档选择清单")
    parser.add_argument(
        "--allow-incomplete-gold-selection",
        action="store_true",
        help="仅供探索演练；允许覆盖不足时生成不可用于正式活动的选择清单",
    )
    parser.add_argument("--require-ready", action="store_true", help="来源配额或覆盖不足时以非零状态退出")
    args = parser.parse_args()

    acceptance_languages = args.acceptance_language or None
    manifest, report = scan_pilot_corpus(
        paper_roots=args.paper_root,
        patent_roots=args.patent_root,
        acceptance_languages=acceptance_languages,
    )
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "pilot-source-manifest.jsonl", manifest)
    (output_dir / "pilot-inventory-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.select_gold:
        _write_jsonl(
            output_dir / "gold-selection-manifest.jsonl",
            select_gold_documents(
                manifest,
                allow_incomplete_coverage=args.allow_incomplete_gold_selection,
                acceptance_languages=acceptance_languages,
            ),
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_ready and not report["ready"]:
        raise SystemExit(2)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
