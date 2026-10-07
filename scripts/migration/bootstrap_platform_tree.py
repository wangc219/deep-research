#!/usr/bin/env python3
"""Copy Yuxi v0.7.3 into the unified platform layout and snapshot the current baseline.

This script is idempotent for the copied tree: it replaces backend/server,
backend/src/platform_core, web, and deploy from the Yuxi reference snapshot,
then rewrites Python/JS imports from `yuxi` to `platform_core`.
It never deletes src/, apps/web, outputs/, or .env.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
YUXI = ROOT / "reference" / "Yuxi-main"
BACKUP = ROOT / ".migration-backup" / "pre-platform-fusion-20260922"
YUXI_COMMIT = "9b67368c6baeb731f89e1076da8a1b68ff52178a"
YUXI_VERSION = "0.7.3"

EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    ".vite",
}


def copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name in EXCLUDE_DIR_NAMES}
        ignored.update(name for name in names if name.endswith(".pyc"))
        return ignored

    shutil.copytree(src, dest, ignore=ignore, symlinks=True)


def sqlite_counts(db_path: Path, queries: dict[str, str]) -> dict[str, object]:
    if not db_path.is_file():
        return {"missing": True, "path": str(db_path)}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    result: dict[str, object] = {"path": str(db_path), "size_bytes": db_path.stat().st_size}
    try:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")
        ]
        result["tables"] = tables
        for key, sql in queries.items():
            try:
                rows = conn.execute(sql).fetchall()
                if len(rows) == 1 and len(rows[0]) == 1:
                    result[key] = rows[0][0]
                else:
                    result[key] = [dict(row) for row in rows]
            except sqlite3.Error as exc:
                result[key] = f"error: {exc}"
    finally:
        conn.close()
    return result


def snapshot_baseline() -> dict[str, object]:
    BACKUP.mkdir(parents=True, exist_ok=True)
    for rel in (
        "src",
        "apps/web/src",
        "configs",
        "docs",
        "scripts",
        "tests",
    ):
        src = ROOT / rel
        if src.exists():
            copy_tree(src, BACKUP / rel)

    for name in (
        "docker-compose.yml",
        "Dockerfile.api",
        "Makefile",
        "requirements.txt",
        "pyproject.toml",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        ".gitignore",
        ".env.example",
        "apps/web/package.json",
        "apps/web/vite.config.js",
    ):
        src = ROOT / name
        if src.is_file():
            dest = BACKUP / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    data_dir = BACKUP / "data"
    data_dir.mkdir(exist_ok=True)
    for name in ("application.db", "query-library.db"):
        src = ROOT / "outputs" / name
        if src.is_file():
            shutil.copy2(src, data_dir / name)

    app_db = ROOT / "outputs" / "application.db"
    query_db = ROOT / "outputs" / "query-library.db"
    inventory = {
        "created_at": "2026-09-22",
        "source_project": "Yuxi",
        "source_version": YUXI_VERSION,
        "source_commit": YUXI_COMMIT,
        "application": sqlite_counts(
            app_db,
            {
                "runs": "SELECT COUNT(*) FROM runs",
                "run_status": "SELECT json_extract(payload, '$.status') AS status, COUNT(*) AS n FROM runs GROUP BY 1 ORDER BY n DESC",
                "events": "SELECT COUNT(*) FROM runtime_events",
                "favorites": "SELECT COUNT(*) FROM favorites",
                "capability_versions": "SELECT COUNT(*) FROM capability_versions",
                "deep_sessions": "SELECT COUNT(*) FROM deep_sessions",
                "deep_messages": "SELECT COUNT(*) FROM deep_messages",
                "deep_jobs": "SELECT COUNT(*) FROM deep_jobs",
                "deep_branches": "SELECT COUNT(*) FROM deep_branches",
                "deep_steers": "SELECT COUNT(*) FROM deep_steers",
            },
        ),
        "query_library": sqlite_counts(
            query_db,
            {
                "queries": "SELECT COUNT(*) FROM query_items",
                "query_status": "SELECT status, COUNT(*) AS n FROM query_items GROUP BY 1 ORDER BY n DESC",
                "revisions": "SELECT COUNT(*) FROM query_revisions",
                "generation_jobs": "SELECT COUNT(*) FROM generation_jobs",
            },
        ),
    }
    outputs = ROOT / "outputs"
    if outputs.is_dir():
        artifact_bytes = 0
        artifact_files = 0
        for path in outputs.rglob("*"):
            if path.is_file():
                artifact_files += 1
                artifact_bytes += path.stat().st_size
        inventory["outputs"] = {
            "files": artifact_files,
            "bytes": artifact_bytes,
            "megabytes": round(artifact_bytes / (1024 * 1024), 1),
        }
    return inventory


def rewrite_platform_imports(root: Path) -> int:
    changed = 0
    suffixes = {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".in", ".sh", ".js", ".vue", ".json", ".css"}
    replacements = (
        ("from yuxi.", "from platform_core."),
        ("import yuxi.", "import platform_core."),
        ("import yuxi\n", "import platform_core\n"),
        ('"yuxi.', '"platform_core.'),
        ("'yuxi.", "'platform_core."),
        ("yuxi.services.", "platform_core.services."),
        ("yuxi.repositories.", "platform_core.repositories."),
        ("yuxi.storage.", "platform_core.storage."),
        ("yuxi.agents.", "platform_core.agents."),
        ("yuxi.knowledge.", "platform_core.knowledge."),
        ("yuxi.models.", "platform_core.models."),
        ("yuxi.config", "platform_core.config"),
        ("yuxi.utils", "platform_core.utils"),
        ("yuxi.workspace", "platform_core.workspace"),
        ("yuxi.permissions", "platform_core.permissions"),
        ("yuxi.storage_migration", "platform_core.storage_migration"),
        ("yuxi.storage_migrations", "platform_core.storage_migrations"),
        ("yuxi.main", "platform_core.main"),
        ('version("yuxi")', 'version("platform-core")'),
        ("name = \"yuxi\"", "name = \"platform-core\""),
        ('include = ["yuxi*"]', 'include = ["platform_core*", "equipment_deep_research*", "knowledgegraph*"]'),
        ("yuxi-workspace", "equipment-platform-workspace"),
        ('"yuxi",', '"platform-core",'),
        ("yuxi = { path = \"package\"", "platform-core = { path = \"src\""),
        ("pythonpath = [\".\", \"package\"]", "pythonpath = [\".\", \"src\"]"),
        ("ruff check package", "ruff check src"),
        ("ruff format package", "ruff format src"),
        ("COPY backend/package /app/package", "COPY backend/src /app/src"),
        ("./backend/package:/app/package", "./backend/src:/app/src"),
        ("./backend/package", "./backend/src"),
        ("/app/package", "/app/src"),
        ("yuxi-entrypoint", "platform-entrypoint"),
        ("groupadd --gid 1000 yuxi", "groupadd --gid 1000 platform"),
        ("useradd --uid 1000 --gid 1000 --create-home yuxi", "useradd --uid 1000 --gid 1000 --create-home platform"),
        ("HOME=/home/yuxi", "HOME=/home/platform"),
        ("/home/yuxi", "/home/platform"),
        ("RAPIDOCR_MODEL_DIR: /home/yuxi/.cache/rapidocr/models", "RAPIDOCR_MODEL_DIR: /home/platform/.cache/rapidocr/models"),
        ("testpaths = [\"test/unit\", \"test/integration\", \"test/e2e\"]", "testpaths = [\"tests/unit\", \"tests/integration\", \"tests/e2e\"]"),
        ("./backend/test:/app/test", "./backend/tests:/app/test"),
        ("docker compose exec api uv run --group test pytest test/", "docker compose exec api uv run --group test pytest tests/"),
    )
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        original = text
        for old, new in replacements:
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def copy_platform_tree() -> None:
    copy_tree(YUXI / "backend" / "server", ROOT / "backend" / "server")
    copy_tree(YUXI / "backend" / "package" / "yuxi", ROOT / "backend" / "src" / "platform_core")
    copy_tree(YUXI / "backend" / "test", ROOT / "backend" / "tests")
    if (YUXI / "backend" / "scripts").exists():
        copy_tree(YUXI / "backend" / "scripts", ROOT / "backend" / "scripts")
    shutil.copy2(YUXI / "backend" / "pyproject.toml", ROOT / "backend" / "pyproject.toml")
    shutil.copy2(YUXI / "backend" / ".python-version", ROOT / "backend" / ".python-version")
    shutil.copy2(YUXI / "backend" / "uv.lock", ROOT / "backend" / "uv.lock")
    shutil.copy2(YUXI / "backend" / "package" / "pyproject.toml", ROOT / "backend" / "src" / "pyproject.toml")
    shutil.copy2(YUXI / "backend" / "package" / "MANIFEST.in", ROOT / "backend" / "src" / "MANIFEST.in")
    shutil.copy2(YUXI / "backend" / "package" / "README.md", ROOT / "backend" / "src" / "README.md")
    copy_tree(YUXI / "web", ROOT / "web")
    copy_tree(YUXI / "docker", ROOT / "deploy")
    for name in ("docker-compose.yml", "docker-compose.prod.yml", ".env.template", ".dockerignore", "Makefile"):
        src = YUXI / name
        if src.is_file():
            shutil.copy2(src, ROOT / "deploy" / name)
    shutil.copy2(YUXI / "docker-compose.yml", ROOT / "compose.yaml")
    shutil.copy2(YUXI / "docker-compose.prod.yml", ROOT / "compose.prod.yaml")
    if (YUXI / "scripts" / "init.sh").is_file():
        shutil.copy2(YUXI / "scripts" / "init.sh", ROOT / "scripts" / "init-platform.sh")
    copy_tree(ROOT / "src" / "equipment_deep_research", ROOT / "backend" / "src" / "equipment_deep_research")
    if (ROOT / "src" / "knowledgegraph").exists():
        copy_tree(ROOT / "src" / "knowledgegraph", ROOT / "backend" / "src" / "knowledgegraph")
    domain_tests = ROOT / "tests" / "equipment_deep_research"
    if domain_tests.exists():
        copy_tree(domain_tests, ROOT / "backend" / "tests" / "equipment_deep_research")


def main() -> int:
    if not YUXI.is_dir():
        print(f"missing Yuxi reference at {YUXI}", file=sys.stderr)
        return 1
    inventory = snapshot_baseline()
    inventory_path = ROOT / "docs" / "migration" / "BASELINE_INVENTORY.json"
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (BACKUP / "BASELINE_INVENTORY.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    copy_platform_tree()
    changed = rewrite_platform_imports(ROOT / "backend")
    changed += rewrite_platform_imports(ROOT / "web")
    changed += rewrite_platform_imports(ROOT / "deploy")
    compose_replacements = (
        ("./backend/package:/app/package", "./backend/src:/app/src"),
        ("./backend/package", "./backend/src"),
        ("/app/package", "/app/src"),
        ("dockerfile: docker/", "dockerfile: deploy/"),
        ("./docker/", "./deploy/"),
        ("image: ${COMPOSE_PROJECT_NAME:-yuxi}", "image: ${COMPOSE_PROJECT_NAME:-equipment-platform}"),
        ("POSTGRES_DB:-yuxi", "POSTGRES_DB:-equipment_platform"),
        ("volumes}/yuxi/", "volumes}/platform/"),
        ("yuxi-api", "equipment-platform-api"),
        ("yuxi-web", "equipment-platform-web"),
    )
    for extra in (ROOT / "compose.yaml", ROOT / "compose.prod.yaml", ROOT / "scripts" / "init-platform.sh"):
        if not extra.is_file():
            continue
        text = extra.read_text(encoding="utf-8")
        original = text
        for old, new in compose_replacements:
            text = text.replace(old, new)
        if text != original:
            extra.write_text(text, encoding="utf-8")
            changed += 1
    print(json.dumps({"backup": str(BACKUP), "inventory": str(inventory_path), "rewritten_files": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
