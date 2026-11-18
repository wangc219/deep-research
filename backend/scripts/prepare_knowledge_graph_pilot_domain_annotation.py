"""准备或回收 999 篇 Pilot 论文的六领域人工标注任务。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.pilot_domain_annotation import (
    apply_domain_annotations,
    build_domain_annotation_package,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="生成不含预标答案的分批任务")
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--batch-count", type=int, default=6)
    prepare.add_argument("--annotator-account", action="append", default=[])
    prepare.add_argument(
        "--parser-preflight",
        type=Path,
        help="可选的 parser-routing-preflight.jsonl；未通过来源会标记为 source_hold",
    )
    prepare.add_argument(
        "--reuse-tasks",
        type=Path,
        action="append",
        default=[],
        help="可重复传入旧任务 CSV；仅按内容 SHA-256 继承 completed 人工标注",
    )

    apply = subparsers.add_parser("apply", help="严格校验回收 CSV 并生成新 manifest")
    apply.add_argument("--manifest", type=Path, required=True)
    apply.add_argument("--tasks", type=Path, action="append", required=True)
    apply.add_argument("--output-manifest", type=Path, required=True)
    apply.add_argument("--output-report", type=Path, required=True)
    apply.add_argument("--allow-partial", action="store_true")
    apply.add_argument(
        "--annotation-kind",
        choices=("human", "ai_prelabel"),
        default="human",
        help="标注来源；AI 预标不能进入正式 Gold 选择",
    )

    args = parser.parse_args()
    if args.command == "prepare":
        result = build_domain_annotation_package(
            manifest_path=args.manifest,
            output_root=args.output,
            batch_count=args.batch_count,
            annotator_accounts=args.annotator_account,
            parser_preflight_path=args.parser_preflight,
            prior_task_paths=args.reuse_tasks,
        )
    else:
        result = apply_domain_annotations(
            manifest_path=args.manifest,
            task_paths=args.tasks,
            output_manifest_path=args.output_manifest,
            output_report_path=args.output_report,
            require_complete=not args.allow_partial,
            annotation_kind=args.annotation_kind,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
