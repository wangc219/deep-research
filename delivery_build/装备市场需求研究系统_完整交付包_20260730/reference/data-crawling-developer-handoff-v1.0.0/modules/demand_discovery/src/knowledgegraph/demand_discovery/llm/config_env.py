"""Environment and .env loading for demand discovery provider config."""

from __future__ import annotations

import os
from pathlib import Path

from knowledgegraph.runtime.provider_config import (
    env_value,
    load_dotenv,
)



def load_powershell_dotenv(path: str | Path | None) -> dict[str, str]:
    """Backward-compatible alias for the shared dotenv loader."""

    return load_dotenv(path)


def load_demand_discovery_dotenv(project_root: str | Path) -> dict[str, str]:
    """Load configured demand-discovery .env values.

    ``DEMAND_DISCOVERY_DOTENV`` can point tests or local runs at an alternate
    file. Otherwise the repository root ``.env`` is used.
    """

    override = os.getenv("DEMAND_DISCOVERY_DOTENV")
    path = Path(override) if override else Path(project_root) / ".env"
    return load_dotenv(path)
