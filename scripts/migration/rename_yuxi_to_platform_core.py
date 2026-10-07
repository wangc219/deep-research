#!/usr/bin/env python3
"""Rename the reused Yuxi package to platform_core without changing Compose topology."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "backend" / "package"
YUXI_DIR = PACKAGE / "yuxi"
CORE_DIR = PACKAGE / "platform_core"
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".in",
    ".sh",
    ".js",
    ".vue",
    ".json",
    ".css",
    ".html",
}


def rewrite_text(text: str) -> str:
    replacements = (
        ("from yuxi import", "from platform_core import"),
        ("from yuxi.", "from platform_core."),
        ("import yuxi as", "import platform_core as"),
        ("import yuxi.", "import platform_core."),
        ("import yuxi\n", "import platform_core\n"),
        ('"yuxi.', '"platform_core.'),
        ("'yuxi.", "'platform_core."),
        ("yuxi.services", "platform_core.services"),
        ("yuxi.repositories", "platform_core.repositories"),
        ("yuxi.storage", "platform_core.storage"),
        ("yuxi.agents", "platform_core.agents"),
        ("yuxi.knowledge", "platform_core.knowledge"),
        ("yuxi.models", "platform_core.models"),
        ("yuxi.config", "platform_core.config"),
        ("yuxi.utils", "platform_core.utils"),
        ("yuxi.workspace", "platform_core.workspace"),
        ("yuxi.permissions", "platform_core.permissions"),
        ("yuxi.storage_migration", "platform_core.storage_migration"),
        ("yuxi.storage_migrations", "platform_core.storage_migrations"),
        ("yuxi.main", "platform_core.main"),
        ('version("yuxi")', 'version("platform-core")'),
        ('name = "yuxi"', 'name = "platform-core"'),
        ('include = ["yuxi*"]', 'include = ["platform_core*", "equipment_deep_research*", "knowledgegraph*"]'),
        ("recursive-include yuxi/", "recursive-include platform_core/"),
        ("graft yuxi/", "graft platform_core/"),
        ('"yuxi",', '"platform-core",'),
        ("yuxi = { path = \"package\"", "platform-core = { path = \"package\""),
        ("ruff check package", "ruff check package"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def rewrite_tree(root: Path) -> int:
    changed = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "api.Dockerfile", "MANIFEST.in"}:
            continue
        if "node_modules" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = rewrite_text(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return changed


def main() -> None:
    if YUXI_DIR.is_dir() and not CORE_DIR.exists():
        shutil.move(str(YUXI_DIR), str(CORE_DIR))
    elif not CORE_DIR.is_dir():
        raise SystemExit("neither yuxi nor platform_core package directory exists")

    changed = 0
    changed += rewrite_tree(ROOT / "backend")
    print(f"renamed package to platform_core; rewrote {changed} files")


if __name__ == "__main__":
    main()
