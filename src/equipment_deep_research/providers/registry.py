"""Configuration-only provider registry with secret-safe snapshots."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.responses import ResponsesProvider


class ProviderConfigurationError(ValueError):
    pass


class ProviderRegistry:
    def __init__(self, profiles: Mapping[str, Mapping[str, Any]], default_provider: str) -> None:
        self._profiles = {name: dict(profile) for name, profile in profiles.items()}
        self.default_provider = default_provider
        if default_provider not in self._profiles:
            raise ProviderConfigurationError(f"unknown default provider: {default_provider}")

    @classmethod
    def load(cls, path: str | Path) -> "ProviderRegistry":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(payload, Mapping) or not isinstance(payload.get("providers"), Mapping):
            raise ProviderConfigurationError("providers configuration requires providers mapping")
        profiles: dict[str, Mapping[str, Any]] = {}
        for name, raw in payload["providers"].items():
            if not isinstance(raw, Mapping):
                raise ProviderConfigurationError(f"provider {name} configuration must be an object")
            if any(key.lower() in {"api_key", "authorization", "headers"} for key in raw):
                raise ProviderConfigurationError("provider credentials must be referenced by environment variable")
            profiles[str(name)] = raw
        return cls(profiles, str(payload.get("default_provider", "responses")))

    def create(self, profile_name: str | None = None, *, model: str | None = None) -> object:
        name = profile_name or self.default_provider
        try:
            profile = self._profiles[name]
        except KeyError as exc:
            raise ProviderConfigurationError(f"unknown provider profile: {name}") from exc
        kind = str(profile.get("type", ""))
        if kind == "fake":
            provider = ScriptedFakeProvider([])
            provider.model = model or "fake"
            return provider
        if kind != "responses_http":
            raise ProviderConfigurationError(f"unsupported provider type: {kind}")
        key_env = str(profile.get("api_key_env", ""))
        api_key = os.environ.get(key_env)
        if not api_key:
            raise ProviderConfigurationError(f"missing required provider credential: {key_env}")
        base_url = os.environ.get(str(profile.get("base_url_env", "")), "https://api.openai.com/v1/responses")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProviderConfigurationError("Responses base URL must be an HTTPS URL")
        return ResponsesProvider(
            model=model or str(profile.get("model", "gpt-5.5")),
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=int(profile.get("timeout_seconds", 120)),
        )
