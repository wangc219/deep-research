from __future__ import annotations

from pathlib import Path

import pytest

from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.registry import ProviderConfigurationError, ProviderRegistry
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent, ProviderToolCall


PROVIDER_CONFIG = Path(__file__).parents[3] / "configs/equipment_deep_research/providers.yaml"


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
