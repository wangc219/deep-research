"""只读预检 Pilot PDF 解析路由、指纹和后续批次工作量。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from platform_core.knowledge.training.pilot_parser_preflight import (
    load_source_manifest,
    run_parser_preflight,
    write_parser_preflight_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="pilot-source-manifest.jsonl 路径")
    parser.add_argument("--output-dir", required=True, help="预检结果输出目录")
    parser.add_argument("--sample-limit", type=int, default=12, help="每篇最多采样页数")
    parser.add_argument("--batch-size", type=int, default=25, help="后续解析计划的单批文档数")
    parser.add_argument("--resume", action="store_true", help="复用输出目录中指纹及参数完全一致的成功结果")
    parser.add_argument("--skip-content-sha256", action="store_true", help="仅调试使用；跳过逐文件内容 SHA-256 校验")
    parser.add_argument("--require-ready", action="store_true", help="任一文档预检失败时以非零状态退出")
    args = parser.parse_args()

    logging.disable(logging.WARNING)
    output_dir = Path(args.output_dir).expanduser().resolve()
    resume_path = output_dir / "parser-routing-preflight.jsonl"
    checkpoint_path = output_dir / "parser-routing-checkpoint.jsonl"
    resume_rows = []
    if args.resume:
        for candidate in (resume_path, checkpoint_path):
            if candidate.is_file():
                resume_rows.extend(load_source_manifest(candidate))
    else:
        checkpoint_path.unlink(missing_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_path.open("a", encoding="utf-8")
    processed = 0

    def checkpoint_result(row: dict) -> None:
        nonlocal processed
        checkpoint.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        checkpoint.flush()
        processed += 1
        if processed % 25 == 0:
            print(f"已新增预检 {processed} 篇", flush=True)

    manifest = load_source_manifest(args.manifest)
    try:
        rows, report, batches = run_parser_preflight(
            manifest,
            sample_limit=args.sample_limit,
            batch_size=args.batch_size,
            verify_content_sha256=not args.skip_content_sha256,
            resume_rows=resume_rows,
            on_result=checkpoint_result,
        )
    finally:
        checkpoint.close()
    paths = write_parser_preflight_outputs(output_dir, rows=rows, report=report, batches=batches)
    checkpoint_path.unlink(missing_ok=True)
    print(
        json.dumps(
            {**report, "outputs": {key: str(value) for key, value in paths.items()}},
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.require_ready and not report["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
