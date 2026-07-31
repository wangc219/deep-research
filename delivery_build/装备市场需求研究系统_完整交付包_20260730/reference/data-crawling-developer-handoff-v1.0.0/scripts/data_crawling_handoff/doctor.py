"""Environment diagnostics that never expose credential values."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Mapping


CONFIGURED_ENV_NAMES = (
    "DEMAND_DISCOVERY_API_KEY",
    "TAVILY_API_KEY",
    "MINERU_TOKEN",
    "EXTRACTION_LLM_API_KEY",
)
REQUIRED_IMPORTS = (
    ("requests", "requests"),
    ("beautifulsoup4", "bs4"),
    ("PyYAML", "yaml"),
    ("playwright", "playwright"),
    ("DrissionPage", "DrissionPage"),
)


def collect_checks(
    *,
    project_root: Path,
    data_root: Path,
    runtime_root: Path,
    env: Mapping[str, str] | None = None,
    containerized: bool | None = None,
) -> list[dict[str, object]]:
    environment = os.environ if env is None else env
    in_container = Path("/.dockerenv").exists() if containerized is None else containerized
    docker_available = shutil.which("docker") is not None
    imports = {
        label: _module_available(module_name)
        for label, module_name in REQUIRED_IMPORTS
    }
    configured = _configured_environment_names(Path(project_root), environment)
    browser_commands = [
        name
        for name in ("chromium", "chromium-browser", "google-chrome", "msedge")
        if shutil.which(name)
    ]
    return [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 11),
            "version": ".".join(str(item) for item in sys.version_info[:3]),
        },
        {
            "name": "project_root",
            "ok": Path(project_root).is_dir(),
            "path": str(Path(project_root).resolve()),
        },
        {
            "name": "python_imports",
            "ok": all(imports.values()),
            "available": sorted(name for name, present in imports.items() if present),
            "missing": sorted(name for name, present in imports.items() if not present),
        },
        {
            "name": "docker",
            "ok": docker_available or in_container,
            "command_available": docker_available,
            "containerized": in_container,
        },
        {
            "name": "browser_runtime",
            "ok": imports.get("playwright", False) or bool(browser_commands),
            "playwright_python": imports.get("playwright", False),
            "browser_commands": browser_commands,
        },
        {
            "name": "configured_environment",
            "ok": True,
            "configured": configured,
            "missing": sorted(set(CONFIGURED_ENV_NAMES) - set(configured)),
        },
        _writable_check("data_root", data_root),
        _writable_check("runtime_root", runtime_root),
    ]


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _configured_environment_names(
    project_root: Path,
    environment: Mapping[str, str],
) -> list[str]:
    configured = {
        name for name in CONFIGURED_ENV_NAMES if bool(environment.get(name))
    }
    env_path = Path(project_root) / ".env"
    if not env_path.exists():
        return sorted(configured)
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if name.startswith("$env:"):
            name = name[len("$env:") :]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            continue
        if name in CONFIGURED_ENV_NAMES and raw_value.strip().strip("\"'"):
            configured.add(name)
    return sorted(configured)


def _writable_check(name: str, path: Path) -> dict[str, object]:
    target = Path(path).expanduser().resolve()
    try:
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target, prefix=".doctor-", delete=True):
            pass
    except OSError as exc:
        return {
            "name": name,
            "ok": False,
            "path": str(target),
            "error_type": type(exc).__name__,
        }
    return {"name": name, "ok": True, "path": str(target)}
