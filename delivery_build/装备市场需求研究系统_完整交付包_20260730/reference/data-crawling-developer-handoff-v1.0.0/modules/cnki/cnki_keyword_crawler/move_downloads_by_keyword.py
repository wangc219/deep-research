# -*- coding: utf-8 -*-
"""
按 data/raw/cnki/logs/spider_dp.log 中的搜索关键词筛选下载记录，并将对应 PDF 统一迁移到目标目录。

默认行为：
- 从 data/raw/cnki/logs/spider_dp.log 读取运行日志
- 仅处理“搜索关键词 = 诊疗指南”的成功下载记录
- 将文件从记录的输出目录迁移到 data/raw/cnki/archived_downloads 目录

示例：
    python move_downloads_by_keyword.py
    python move_downloads_by_keyword.py --keyword "诊疗指南" --dest-dir "archived_downloads"
"""

import argparse
import os
import re
import shutil
from pathlib import Path

try:
    from cnki_keyword_downloader import build_storage_paths
except ImportError:  # 允许作为包导入
    from .cnki_keyword_downloader import build_storage_paths


KEYWORD_RE = re.compile(r"搜索关键词\s*[:：]\s*(.+?)\s*$")
OUTPUT_DIR_RE = re.compile(r"输出目录\s*[:：]\s*(.+?)\s*$")
SAVED_FILE_RE = re.compile(r"\[成功\]\s*已保存\s*[:：]\s*(.+?)\s*$")


def safe_target_path(dest_dir: Path, file_name: str) -> Path:
    """若目标文件名冲突，自动追加序号后缀。"""
    candidate = dest_dir / file_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    idx = 1
    while True:
        alt = dest_dir / f"{stem}_{idx}{suffix}"
        if not alt.exists():
            return alt
        idx += 1


def normalize_path(raw_path: str) -> str:
    """清理日志中路径字段可能携带的首尾空白和引号。"""
    return raw_path.strip().strip('"').strip("'")


def collect_files_from_log(log_path: Path, target_keyword: str, default_source_dir: Path):
    """按关键词收集需要迁移的文件完整路径。"""
    collected = []
    current_keyword = None
    current_output_dir = default_source_dir

    with log_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            keyword_match = KEYWORD_RE.search(line)
            if keyword_match:
                current_keyword = keyword_match.group(1).strip()
                continue

            output_match = OUTPUT_DIR_RE.search(line)
            if output_match:
                parsed = normalize_path(output_match.group(1))
                if parsed:
                    current_output_dir = Path(parsed)
                continue

            saved_match = SAVED_FILE_RE.search(line)
            if not saved_match:
                continue

            if current_keyword != target_keyword:
                continue

            file_name = saved_match.group(1).strip()
            if not file_name:
                continue

            collected.append(current_output_dir / file_name)

    return collected


def main():
    default_paths = build_storage_paths()
    parser = argparse.ArgumentParser(description="按关键词归档下载文件")
    parser.add_argument("--log", default=str(default_paths.log_path),
                        help="日志文件路径（默认：data/raw/cnki/logs/spider_dp.log）")
    parser.add_argument("--keyword", default="诊疗指南", help="目标搜索关键词（默认：诊疗指南）")
    parser.add_argument("--source-dir", default=str(default_paths.output_dir),
                        help="默认下载源目录（默认：data/raw/cnki/papers）")
    parser.add_argument("--dest-dir", default=str(default_paths.raw_dir / "archived_downloads"),
                        help="目标目录（默认：data/raw/cnki/archived_downloads）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际移动文件")
    args = parser.parse_args()

    base_dir = Path.cwd()
    log_path = (base_dir / args.log).resolve()
    default_source_dir = (base_dir / args.source_dir).resolve()
    dest_dir = (base_dir / args.dest_dir).resolve()

    if not log_path.exists():
        print(f"[错误] 日志文件不存在: {log_path}")
        raise SystemExit(1)

    files_to_move = collect_files_from_log(log_path, args.keyword, default_source_dir)
    if not files_to_move:
        print(f"[完成] 日志中未找到关键词“{args.keyword}”对应的成功下载记录。")
        return

    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    missing = 0

    for src in files_to_move:
        if not src.exists():
            print(f"[缺失] 文件不存在，跳过: {src}")
            missing += 1
            continue

        target = safe_target_path(dest_dir, src.name)
        if args.dry_run:
            print(f"[预览] {src} -> {target}")
            continue

        shutil.move(str(src), str(target))
        print(f"[已移动] {src} -> {target}")
        moved += 1

    if args.dry_run:
        print(f"[完成] 共匹配 {len(files_to_move)} 条记录（预览模式，未移动文件）。")
    else:
        print(f"[完成] 共匹配 {len(files_to_move)} 条，成功移动 {moved} 个，缺失 {missing} 个。")
        print(f"[目录] 目标目录: {dest_dir}")


if __name__ == "__main__":
    main()
