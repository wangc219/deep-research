from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_application_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep API integration tests out of the developer's live task database."""

    monkeypatch.setenv(
        "EQUIPMENT_DR_APP_DB",
        f"sqlite:///{tmp_path / 'application.db'}",
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(tmp_path / "runs"))
