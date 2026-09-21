from __future__ import annotations

from types import SimpleNamespace

import pytest

from equipment_deep_research.agents.workflows.baseline_execution import (
    _provider_has_hosted_web_search,
)
from equipment_deep_research.agents.workflows.runtime import (
    _normalize_discovery_responses_url,
    build_discovery_provider,
)
from equipment_deep_research.providers.base import ProviderCapabilities


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (
            "https://api.deepseek.com/v1/chat/completions",
            "https://api.deepseek.com/v1/responses",
        ),
        (
            "https://gateway.example/v1/chat/completions/",
            "https://gateway.example/v1/responses",
        ),
        (
            "https://gateway.example/v1/responses",
            "https://gateway.example/v1/responses",
        ),
        (
            "https://gateway.example/v1/responses/?tenant=cn#route",
            "https://gateway.example/v1/responses?tenant=cn#route",
        ),
        (
            "https://gateway.example/v1",
            "https://gateway.example/v1/responses",
        ),
    ],
)
def test_discovery_responses_url_normalization(configured: str, expected: str) -> None:
    assert _normalize_discovery_responses_url(configured) == expected


def test_build_discovery_provider_replaces_chat_completions_suffix(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_VIA_RESPONSES", "1")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "test-discovery-model")
    monkeypatch.setenv(
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", "TEST_DISCOVERY_KEY")
    monkeypatch.setenv("TEST_DISCOVERY_KEY", "secret")
    host = SimpleNamespace(
        provider_kind="codex_cli",
        provider=SimpleNamespace(model="test-discovery-model"),
    )

    provider = build_discovery_provider(host)

    assert provider is not None
    assert provider.base_url == "https://api.deepseek.com/v1/responses"


def test_build_discovery_provider_prefers_route_resolved_http_bridge(monkeypatch) -> None:
    """A local Chat Completions bridge must not be advertised as Responses."""
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_VIA_RESPONSES", "1")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "bridge-model")
    monkeypatch.setenv(
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL",
        "https://relay.example.test/v1/chat/completions",
    )
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", "UPSTREAM_KEY")
    monkeypatch.setenv("UPSTREAM_KEY", "upstream-secret")
    # The routing script exports this resolved profile after starting the
    # bridge. It must win over the original upstream URL regardless of env
    # insertion order.
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_DEEPSEEK_MODEL", "bridge-model")
    monkeypatch.setenv(
        "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL", "http://127.0.0.1:8787/v1"
    )
    monkeypatch.setenv(
        "EQUIPMENT_DR_CODEX_DEEPSEEK_API_KEY_ENV", "BRIDGE_KEY"
    )
    monkeypatch.setenv("BRIDGE_KEY", "bridge-secret")
    host = SimpleNamespace(
        provider_kind="codex_cli",
        provider=SimpleNamespace(model="bridge-model"),
    )

    assert build_discovery_provider(host) is None


def test_build_discovery_provider_prefers_instantiated_provider_configuration(
    monkeypatch,
) -> None:
    """Embedded callers must not silently fall back to the global GPT route."""
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_VIA_RESPONSES", "1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://wrong.example/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "WRONG_KEY")
    monkeypatch.setenv("WRONG_KEY", "wrong-secret")
    host = SimpleNamespace(
        provider_kind="codex_cli",
        provider=SimpleNamespace(
            model="embedded-model",
            base_url="https://embedded.example/v1",
            api_key="embedded-secret",
        ),
    )

    provider = build_discovery_provider(host)

    assert provider is not None
    assert provider.model == "embedded-model"
    assert provider.base_url == "https://embedded.example/v1/responses"


class _CapabilityProvider:
    def __init__(self, hosted_web_search: bool) -> None:
        self._capabilities = ProviderCapabilities(hosted_web_search=hosted_web_search)

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities


def test_codex_cli_without_dedicated_discovery_provider_uses_anchor_route() -> None:
    provider = _CapabilityProvider(hosted_web_search=True)
    host = SimpleNamespace(
        provider_kind="codex_cli",
        discovery_provider=None,
        uses_hosted_web_search=True,
    )

    assert not _provider_has_hosted_web_search(provider, host=host)


def test_dedicated_discovery_provider_uses_declared_hosted_search_capability() -> None:
    provider = _CapabilityProvider(hosted_web_search=True)
    host = SimpleNamespace(
        provider_kind="codex_cli",
        discovery_provider=provider,
        uses_hosted_web_search=False,
    )

    assert _provider_has_hosted_web_search(provider, host=host)


def test_fake_provider_remains_hosted_search_compatible_for_offline_tests() -> None:
    provider = _CapabilityProvider(hosted_web_search=False)
    host = SimpleNamespace(
        provider_kind="fake",
        discovery_provider=None,
        uses_hosted_web_search=True,
    )

    assert _provider_has_hosted_web_search(provider, host=host)
