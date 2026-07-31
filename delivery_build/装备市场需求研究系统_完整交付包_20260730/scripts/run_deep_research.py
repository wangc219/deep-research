from __future__ import annotations

import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _load_dotenv_defaults() -> None:
    """Load .env.codex (fallback .env) like start-local.sh; existing env wins."""
    env_file = os.environ.get("EQUIPMENT_DR_ENV_FILE", "")
    candidates = (
        [Path(env_file)]
        if env_file
        else [PROJECT_ROOT / ".env.codex", PROJECT_ROOT / ".env"]
    )
    for dotenv in candidates:
        if not dotenv.is_absolute():
            dotenv = PROJECT_ROOT / dotenv
        if not dotenv.is_file():
            continue
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value
        break


_load_dotenv_defaults()

from equipment_deep_research.interfaces.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
