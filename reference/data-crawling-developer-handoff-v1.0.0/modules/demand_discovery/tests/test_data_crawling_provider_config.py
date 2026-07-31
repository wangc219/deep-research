from __future__ import annotations

from pathlib import Path
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.runtime import provider_config  # noqa: E402
from knowledgegraph.demand_discovery.llm.config_env import (  # noqa: E402
    load_demand_discovery_dotenv,
)


def test_load_dotenv_accepts_standard_powershell_and_export_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "STANDARD_KEY=standard\n"
            '$env:POWERSHELL_KEY="powershell"\n'
            "export EXPORTED_KEY='exported'\n"
            "# ignored comment\n",
            encoding="utf-8",
        )

        values = provider_config.load_dotenv(env_path)

    assert values == {
        "STANDARD_KEY": "standard",
        "POWERSHELL_KEY": "powershell",
        "EXPORTED_KEY": "exported",
    }


def test_load_powershell_dotenv_remains_a_compatibility_alias() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text("STANDARD_KEY=standard\n", encoding="utf-8")

        values = provider_config.load_powershell_dotenv(env_path)

    assert values == {"STANDARD_KEY": "standard"}


def test_load_dotenv_ignores_invalid_names_and_blank_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            "\n"
            "1INVALID=value\n"
            "INVALID-NAME=value\n"
            "VALID_NAME=value\n",
            encoding="utf-8",
        )

        values = provider_config.load_dotenv(env_path)

    assert values == {"VALID_NAME": "value"}


def test_demand_discovery_loader_accepts_standard_dotenv(
    monkeypatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project_root = Path(tmp)
        env_path = project_root / ".env"
        env_path.write_text(
            "DEMAND_DISCOVERY_MODEL=portable-model\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("DEMAND_DISCOVERY_DOTENV", raising=False)

        values = load_demand_discovery_dotenv(project_root)

    assert values["DEMAND_DISCOVERY_MODEL"] == "portable-model"
