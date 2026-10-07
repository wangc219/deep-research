#!/usr/bin/env python3
"""Restore unmodified Yuxi v0.7.3 as the runtime base, then overlay equipment domain packages.

Current src/ and apps/web remain the legacy source of truth and are not deleted.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
YUXI = ROOT / "reference" / "Yuxi-main"
EXCLUDE = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"}


def copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in EXCLUDE or name.endswith(".pyc")}

    shutil.copytree(src, dest, ignore=ignore, symlinks=True)


def copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def main() -> None:
    if not YUXI.is_dir():
        raise SystemExit(f"missing Yuxi reference: {YUXI}")

    backend = ROOT / "backend"
    if backend.exists():
        shutil.rmtree(backend)
    copy_tree(YUXI / "backend", backend)

    copy_tree(ROOT / "src" / "equipment_deep_research", backend / "package" / "equipment_deep_research")
    if (ROOT / "src" / "knowledgegraph").exists():
        copy_tree(ROOT / "src" / "knowledgegraph", backend / "package" / "knowledgegraph")
    domain_tests = ROOT / "tests" / "equipment_deep_research"
    if domain_tests.exists():
        copy_tree(domain_tests, backend / "test" / "equipment_deep_research")

    copy_tree(YUXI / "docker", ROOT / "docker")
    copy_file(YUXI / "docker-compose.yml", ROOT / "compose.yaml")
    copy_file(YUXI / "docker-compose.prod.yml", ROOT / "compose.prod.yaml")
    copy_file(YUXI / ".env.template", ROOT / ".env.platform.example")
    copy_file(YUXI / ".dockerignore", ROOT / ".dockerignore")
    if (YUXI / "scripts" / "init.sh").is_file():
        copy_file(YUXI / "scripts" / "init.sh", ROOT / "scripts" / "init.sh")

    if (ROOT / "web").exists():
        shutil.rmtree(ROOT / "web")
    copy_tree(YUXI / "web", ROOT / "web")

    if (ROOT / "deploy").exists():
        shutil.rmtree(ROOT / "deploy")

    print("restored Yuxi backend/package/yuxi, docker/, web/, compose.yaml")
    print("overlayed equipment_deep_research and knowledgegraph under backend/package/")


if __name__ == "__main__":
    main()
