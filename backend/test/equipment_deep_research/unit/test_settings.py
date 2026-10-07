from __future__ import annotations

from pathlib import Path

from equipment_deep_research.config import ProjectPaths, Settings, load_settings


def test_settings_are_deterministic_for_an_explicit_environment(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "EQUIPMENT_DR_PROJECT_ROOT": str(tmp_path),
            "EQUIPMENT_DR_OUTPUT_ROOT": "var/output",
            "EQUIPMENT_DR_MODE": "real",
            "EQUIPMENT_DR_PROVIDER": "codex",
            "EQUIPMENT_DR_WEB_PORT": "bad",
            "EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY": "0",
            "EQUIPMENT_DR_REQUIRE_TRUSTED_IDENTITY": "yes",
        }
    )

    assert isinstance(settings, Settings)
    assert settings.paths == ProjectPaths(
        root=tmp_path.resolve(),
        output=(tmp_path / "var/output").resolve(),
        runs=(tmp_path / "var/output/runs").resolve(),
        runtime=(tmp_path / "var/output/runtime").resolve(),
        config=tmp_path / "configs/equipment_deep_research",
    )
    assert settings.database_url == f"sqlite:///{tmp_path.resolve() / 'var/output/application.db'}"
    assert settings.mode == "real"
    assert settings.provider == "codex"
    assert settings.web_port == 5173
    assert settings.worker_concurrency == 1
    assert settings.require_trusted_identity is True


def test_public_settings_snapshot_contains_no_secret_values(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "EQUIPMENT_DR_PROJECT_ROOT": str(tmp_path),
            "EQUIPMENT_DR_CODEX_API_KEY": "must-not-be-returned",
        }
    )

    snapshot = settings.public_dict()
    assert "must-not-be-returned" not in repr(snapshot)
    assert snapshot["project_root"] == str(tmp_path.resolve())


def test_explicit_empty_environment_does_not_fall_back_to_process_state(tmp_path: Path) -> None:
    settings = load_settings({}, project_root=tmp_path)

    assert settings.mode == "fake"
    assert settings.provider == ""
    assert settings.paths.root == tmp_path.resolve()


def test_public_snapshot_redacts_credentials_embedded_in_database_urls(tmp_path: Path) -> None:
    settings = load_settings(
        {
            "EQUIPMENT_DR_PROJECT_ROOT": str(tmp_path),
            "EQUIPMENT_DR_APP_DB": "postgresql://alice:secret@example.test/research",
        }
    )

    assert settings.public_dict()["database_url"] == "postgresql://example.test/research"
