"""Map handoff module names to their existing collector CLIs."""

from __future__ import annotations

import os
from pathlib import Path
import sys


MODULES = {"journal", "cnki", "wechat", "mineru", "demand"}
_PACKAGE_MODULE_DIRS = {
    "journal": "journal",
    "cnki": "cnki",
    "wechat": "wechat",
    "mineru": "mineru",
    "demand": "demand_discovery",
}
_WECHAT_COLLECTION_COMMANDS = {"collect", "collect-by-fakeid", "collect-many"}


def resolve_data_root(value: str | Path | None) -> Path:
    candidate = value or os.getenv("CRAWLER_DATA_ROOT") or Path.cwd() / "data"
    return Path(candidate).expanduser().resolve()


def build_module_command(
    module: str,
    project_root: Path,
    data_root: Path,
    passthrough: list[str],
) -> list[str]:
    if module not in MODULES:
        raise ValueError(f"unknown module: {module}")

    project_root = Path(project_root).resolve()
    data_root = Path(data_root).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    module_root = _module_root(project_root, module)
    args = list(passthrough)

    if module == "journal":
        return [
            sys.executable,
            str(module_root / "scripts" / "journal" / "download_all_journals.py"),
            "--output-root",
            str(data_root / "raw"),
            "--manifest",
            str(data_root / "raw" / "journal_batch_manifest.jsonl"),
            *args,
        ]
    if module == "cnki":
        return [
            sys.executable,
            str(module_root / "cnki_keyword_crawler" / "cnki_keyword_downloader.py"),
            "--raw-dir",
            str(data_root / "raw" / "cnki"),
            *args,
        ]
    if module == "wechat":
        command = [
            sys.executable,
            str(module_root / "wechat_mp_collector" / "collect.py"),
            *args,
        ]
        subcommand = next(
            (item for item in args if item in _WECHAT_COLLECTION_COMMANDS),
            "",
        )
        if subcommand and not _has_option(args, "--output"):
            command.extend(["--output", str(data_root / "raw" / "wechat")])
        return command
    if module == "mineru":
        return [
            sys.executable,
            str(module_root / "scripts" / "extraction_experiment" / "prepare_chunks.py"),
            "--work-root",
            str(data_root / "processed" / "extraction_experiments"),
            "--artifact-root",
            str(data_root / "processed" / "mineru_artifacts"),
            *args,
        ]
    return [
        sys.executable,
        str(module_root / "scripts" / "demand_discovery_autonomous_research.py"),
        "--output-root",
        str(data_root / "demand_discovery"),
        *args,
    ]


def _module_root(project_root: Path, module: str) -> Path:
    package_root = project_root / "modules" / _PACKAGE_MODULE_DIRS[module]
    return package_root if package_root.exists() else project_root


def _has_option(args: list[str], option: str) -> bool:
    return any(item == option or item.startswith(f"{option}=") for item in args)

