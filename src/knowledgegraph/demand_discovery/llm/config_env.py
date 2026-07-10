"""Environment and .env loading for demand discovery provider config."""

from __future__ import annotations

import os
from pathlib import Path
import re


_POWERSHELL_ENV_RE = re.compile(
    r"^\s*\$env:([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([\"'])(.*?)\2\s*$"
)


def load_powershell_dotenv(path: str | Path | None) -> dict[str, str]:
    """Load PowerShell-style ``$env:NAME=\"value\"`` lines from a .env file."""

    if path is None:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = _POWERSHELL_ENV_RE.match(line)
        if match:
            values[match.group(1)] = match.group(3)
    return values


def load_demand_discovery_dotenv(project_root: str | Path) -> dict[str, str]:
    """Load configured demand-discovery .env values.

    ``DEMAND_DISCOVERY_DOTENV`` can point tests or local runs at an alternate
    file. Otherwise the repository root ``.env`` is used.
    """

    override = os.getenv("DEMAND_DISCOVERY_DOTENV")
    path = Path(override) if override else Path(project_root) / ".env"
    return load_powershell_dotenv(path)


def env_value(
    name: str,
    dotenv: dict[str, str],
    default: str | None = None,
) -> str | None:
    """Return process env first, then .env fallback, then default."""

    return os.getenv(name) or dotenv.get(name) or default
