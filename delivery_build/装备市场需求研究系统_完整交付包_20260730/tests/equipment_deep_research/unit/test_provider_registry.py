from __future__ import annotations

from pathlib import Path

import pytest

from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.registry import ProviderConfigurationError, ProviderRegistry
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent, ProviderToolCall


PROVIDER_CONFIG = Path(__file__).parents[3] / "configs/equipment_deep_research/providers.yaml"


def test_provider_registry_defaults_to_codex_cli() -> None:
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    assert registry.default_provider == "codex"
    assert registry.profile_snapshot()["type"] == "codex_cli"
    assert registry.profile_snapshot()["base_url_host"] == "api.openai.com"


def test_codex_registry_can_disable_global_config_inheritance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-key")
    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "codex",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
    )

    assert provider.inherit_user_config is False


def test_codex_registry_rejects_local_login_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_BASE_URL", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", raising=False)

    with pytest.raises(
        ProviderConfigurationError,
        match="local ChatGPT/Codex login inheritance is disabled",
    ):
        ProviderRegistry.load(PROVIDER_CONFIG).create(
            "codex",
            workspace_path=tmp_path,
        )


def test_codex_registry_reads_configured_api_key_environment_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-codex-key")
    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "codex",
        model="codex-model",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
    )

    assert provider.model == "codex-model"
    assert provider.base_url == "https://codex.example.test/v1"
    assert provider.snapshot()["base_url_host"] == "codex.example.test"
    assert "test-project-codex-key" not in repr(provider)
    assert "test-project-codex-key" not in str(provider.snapshot())


def test_codex_registry_accepts_full_responses_endpoint_as_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-codex-key")

    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "codex",
        base_url="https://codex.example.test/v1/responses",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
    )

    assert provider.base_url == "https://codex.example.test/v1"


def test_codex_registry_isolates_each_agent_context_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-codex-key")
    registry = ProviderRegistry.load(PROVIDER_CONFIG)

    situation = registry.create(
        "codex",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
        isolation_key="international_situation",
    )
    equipment = registry.create(
        "codex",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
        isolation_key="weapon_equipment",
    )

    assert situation.codex_home != equipment.codex_home
    assert situation.codex_home.name == "international_situation"
    assert equipment.codex_home.name == "weapon_equipment"
    assert situation.snapshot()["context_isolation"] == "international_situation"
    assert equipment.snapshot()["context_isolation"] == "weapon_equipment"


def test_codex_registry_rejects_missing_configured_api_key_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.delenv("MISSING_CODEX_KEY", raising=False)

    with pytest.raises(ProviderConfigurationError, match="MISSING_CODEX_KEY"):
        ProviderRegistry.load(PROVIDER_CONFIG).create(
            "codex",
            api_key_env="MISSING_CODEX_KEY",
            workspace_path=tmp_path,
        )


def test_provider_registry_builds_default_gpt55_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "test-key")
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    provider = registry.create("responses")
    assert provider.model == "gpt-5.5"
    assert "test-key" not in repr(provider)
    assert provider.snapshot()["base_url_host"] == "api.openai.com"


def test_real_provider_requires_its_environment_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    with pytest.raises(ProviderConfigurationError, match="EQUIPMENT_DR_API_KEY"):
        registry.create("responses")


def test_scripted_fake_provider_can_emit_tool_then_final_text() -> None:
    provider = ScriptedFakeProvider([
        [ProviderStreamEvent.tool_call_event(ProviderToolCall("call-1", "search_sources", {"query": "test"}))],
        [ProviderStreamEvent.final(ProviderFinalTurn(text="done"))],
    ])
    assert provider.remaining_steps == 2
