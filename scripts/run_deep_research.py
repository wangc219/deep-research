from __future__ import annotations

import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _assign_dotenv_line(line: str, *, skip_existing: bool = True) -> str | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    if not key:
        return None
    if skip_existing and key in os.environ:
        return key
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    os.environ[key] = value
    return key


def _load_dotenv_defaults() -> None:
    """Load unified `.env` (+ optional legacy overlay); existing env wins."""

    preexisting = set(os.environ)
    env_file = os.environ.get("EQUIPMENT_DR_ENV_FILE", "")
    candidates = (
        [Path(env_file)]
        if env_file
        else [PROJECT_ROOT / ".env", PROJECT_ROOT / ".env.codex"]
    )
    for dotenv in candidates:
        if not dotenv.is_absolute():
            dotenv = PROJECT_ROOT / dotenv
        if not dotenv.is_file():
            continue
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            _assign_dotenv_line(line, skip_existing=True)
        if env_file:
            break

    local_env = PROJECT_ROOT / ".env.local"
    if local_env.is_file():
        for line in local_env.read_text(encoding="utf-8").splitlines():
            # Activation layer may override profile selection keys.
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in preexisting:
                continue
            _assign_dotenv_line(line, skip_existing=False)

    fallback_file = os.environ.get("EQUIPMENT_DR_DEEPSEEK_ENV_FILE", "")
    if not fallback_file:
        return
    fallback_path = Path(fallback_file)
    if not fallback_path.is_absolute():
        fallback_path = PROJECT_ROOT / fallback_path
    if not fallback_path.is_file():
        return
    values: dict[str, str] = {}
    for line in fallback_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    fallback_keys = {
        "EQUIPMENT_DR_DEEPSEEK_MODEL",
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL",
        "EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV",
    }
    key_env = values.get("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", "DEEPSEEK_API_KEY")
    if key_env and key_env.replace("_", "").isalnum() and not key_env[0].isdigit():
        fallback_keys.add(key_env)
    for key in fallback_keys:
        if key in values and key not in preexisting:
            os.environ[key] = values[key]


_load_dotenv_defaults()

from equipment_deep_research.interfaces.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
