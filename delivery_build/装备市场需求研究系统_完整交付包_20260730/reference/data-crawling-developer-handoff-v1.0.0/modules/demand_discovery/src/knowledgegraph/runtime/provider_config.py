"""Provider configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path
import re


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    name, raw_value = stripped.split("=", 1)
    name = name.strip()
    if name.startswith("$env:"):
        name = name[len("$env:") :]
    if not _ENV_NAME_RE.fullmatch(name):
        return None
    value = raw_value.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {'"', "'"}
    ):
        value = value[1:-1]
    return name, value


def load_dotenv(path: str | Path | None = None) -> dict[str, str]:
    env_path = Path(path) if path is not None else Path.cwd() / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        parsed = parse_env_line(line)
        if parsed is not None:
            values[parsed[0]] = parsed[1]
    return values


def load_powershell_dotenv(path: str | Path | None = None) -> dict[str, str]:
    """Backward-compatible alias for the cross-platform dotenv loader."""

    return load_dotenv(path)


def env_value(name: str, dotenv: dict[str, str], default: str | None = None) -> str | None:
    return os.getenv(name) or dotenv.get(name) or default


def first_env_value(names: list[str], dotenv: dict[str, str], default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name) or dotenv.get(name)
        if value:
            return value
    return default


def env_bool(name: str, default: bool, dotenv: dict[str, str]) -> bool:
    value = env_value(name, dotenv)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
