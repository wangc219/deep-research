#!/usr/bin/env python3
"""验证 Web 构建目录或容器镜像中的静态资源引用闭包。"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote


TEXT_ASSET_SUFFIXES = {".css", ".html", ".js", ".json", ".mjs", ".svg"}
ASSET_REFERENCE_PATTERN = re.compile(
    r'''(?:^|["'`()=:\s])/?(assets(?:-[A-Za-z0-9._-]+)?/[A-Za-z0-9_@./%+?=&-]*)'''
)


def _referenced_assets(source: str) -> set[str]:
    references: set[str] = set()
    for match in ASSET_REFERENCE_PATTERN.finditer(source):
        reference = unquote(match.group(1).split("?", 1)[0].split("#", 1)[0])
        if reference:
            references.add(reference)
    return references


def verify_root(root: Path) -> int:
    """校验目录内所有静态资源引用都能解析到同一发布目录。"""
    root = root.resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError(f"缺少 index.html：{root}")

    missing: list[str] = []
    checked: set[str] = set()
    for source_file in root.rglob("*"):
        if not source_file.is_file() or source_file.name.endswith(".gz"):
            continue
        if source_file.suffix not in TEXT_ASSET_SUFFIXES:
            continue
        source = source_file.read_text(encoding="utf-8")
        for reference in _referenced_assets(source):
            target = (root / reference).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(f"非法静态资源路径：{reference}") from exc
            if not target.exists():
                missing.append(f"{source_file.relative_to(root)} -> {reference}")
            else:
                checked.add(reference)

    if missing:
        details = "\n".join(sorted(missing))
        raise RuntimeError(f"构建产物引用了不存在的静态资源：\n{details}")
    return len(checked)


def verify_image(image: str) -> int:
    """提取镜像的 Web 根目录并执行静态资源闭包与 Nginx 配置校验。"""
    if shutil.which("docker") is None:
        raise RuntimeError("未找到 docker 命令")

    subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "nginx", image, "-t"],
        check=True,
    )
    container_id = subprocess.run(
        ["docker", "create", image],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        with tempfile.TemporaryDirectory(prefix="deepquest-web-image-") as directory:
            root = Path(directory) / "html"
            root.mkdir()
            subprocess.run(
                ["docker", "cp", f"{container_id}:/usr/share/nginx/html/.", str(root)],
                check=True,
            )
            return verify_root(root)
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> None:
    """解析命令行参数并执行一种发布产物校验。"""
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--root", type=Path)
    target.add_argument("--image")
    args = parser.parse_args()

    checked = verify_root(args.root) if args.root else verify_image(args.image)
    print(f"静态资源完整性校验通过：{checked} 个唯一引用")


if __name__ == "__main__":
    main()
