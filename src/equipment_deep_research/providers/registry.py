"""Configuration-only provider registry with secret-safe snapshots."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from equipment_deep_research.providers.codex import CodexCliProvider
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.responses import ResponsesProvider


class ProviderConfigurationError(ValueError):
    pass


class ProviderRegistry:
    def __init__(
        self, profiles: Mapping[str, Mapping[str, Any]], default_provider: str
    ) -> None:
        self._profiles = {name: dict(profile) for name, profile in profiles.items()}
        self.default_provider = default_provider
        if default_provider not in self._profiles:
            raise ProviderConfigurationError(
                f"unknown default provider: {default_provider}"
            )

    @classmethod
    def load(cls, path: str | Path) -> "ProviderRegistry":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("providers"), Mapping
        ):
            raise ProviderConfigurationError(
                "providers configuration requires providers mapping"
            )
        profiles: dict[str, Mapping[str, Any]] = {}
        for name, raw in payload["providers"].items():
            if not isinstance(raw, Mapping):
                raise ProviderConfigurationError(
                    f"provider {name} configuration must be an object"
                )
            if any(
                key.lower() in {"api_key", "authorization", "headers"} for key in raw
            ):
                raise ProviderConfigurationError(
                    "provider credentials must be referenced by environment variable"
                )
            profiles[str(name)] = raw
        return cls(profiles, str(payload.get("default_provider", "responses")))

    def create(
        self,
        profile_name: str | None = None,
        *,
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        api_key: str | None = None,
        workspace_path: str | Path | None = None,
        isolation_key: str | None = None,
        include_default_skills: bool = True,
    ) -> object:
        name = profile_name or self.default_provider
        try:
            profile = self._profiles[name]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"unknown provider profile: {name}"
            ) from exc
        kind = str(profile.get("type", ""))
        if kind == "fake":
            provider = ScriptedFakeProvider([])
            provider.model = model or "fake"
            return provider
        if kind == "codex_cli":
            codex_key_env = (
                api_key_env or os.environ.get("EQUIPMENT_DR_CODEX_API_KEY_ENV", "")
            ).strip()
            if not api_key and not _valid_environment_name(codex_key_env):
                raise ProviderConfigurationError(
                    "Codex requires a custom API key environment variable; "
                    "local ChatGPT/Codex login inheritance is disabled"
                )
            codex_api_key = str(api_key or os.environ.get(codex_key_env, "")).strip()
            if not codex_api_key:
                raise ProviderConfigurationError(
                    f"missing required Codex credential: {codex_key_env}"
                )
            codex_base_url = str(
                base_url or os.environ.get("EQUIPMENT_DR_CODEX_BASE_URL") or ""
            ).strip()
            codex_base_url = _codex_provider_root_url(codex_base_url)
            parsed_codex_url = urlsplit(codex_base_url)
            if (
                parsed_codex_url.scheme != "https"
                or not parsed_codex_url.hostname
                or parsed_codex_url.username
                or parsed_codex_url.password
                or parsed_codex_url.query
                or parsed_codex_url.fragment
            ):
                raise ProviderConfigurationError(
                    "Codex requires a custom HTTPS base URL without credentials, "
                    "query, or fragment; local login fallback is disabled"
                )
            workspace = Path(workspace_path or Path.cwd()).resolve()
            configured_home = os.environ.get("EQUIPMENT_DR_CODEX_HOME")
            codex_home = Path(configured_home).expanduser() if configured_home else (
                workspace / "outputs" / "runtime" / "codex-homes"
            )
            if isolation_key:
                safe_key = "".join(
                    character
                    if character.isalnum() or character in {"-", "_"}
                    else "-"
                    for character in str(isolation_key)
                ).strip("-")[:64] or "agent"
                codex_home = codex_home / safe_key
            return CodexCliProvider(
                command=os.environ.get(
                    "EQUIPMENT_DR_CODEX_COMMAND",
                    str(profile.get("command", "codex")),
                ),
                model=model or str(profile.get("model", "")),
                workspace_path=workspace,
                codex_home=codex_home,
                source_codex_home=os.environ.get("EQUIPMENT_DR_CODEX_SOURCE_HOME")
                or None,
                inherit_user_config=False,
                api_key=codex_api_key,
                base_url=codex_base_url,
                timeout_seconds=int(
                    os.environ.get(
                        "EQUIPMENT_DR_CODEX_TIMEOUT_SECONDS",
                        profile.get("timeout_seconds", 900),
                    )
                ),
                sandbox_mode=str(profile.get("sandbox_mode", "read-only")),
                extra_args=_string_list(profile.get("extra_args", []), "extra_args"),
                search_extra_args=_string_list(
                    profile.get("search_extra_args", []),
                    "search_extra_args",
                ),
                retry_attempts=int(
                    os.environ.get(
                        "EQUIPMENT_DR_CODEX_RETRY_ATTEMPTS",
                        profile.get("retry_attempts", 1),
                    )
                ),
                isolation_id=str(isolation_key or "shared"),
                include_default_skills=include_default_skills,
            )
        if kind != "responses_http":
            raise ProviderConfigurationError(f"unsupported provider type: {kind}")
        key_env = api_key_env or str(profile.get("api_key_env", ""))
        if not api_key and not _valid_environment_name(key_env):
            raise ProviderConfigurationError(
                "API key environment variable name is invalid"
            )
        resolved_api_key = str(api_key or os.environ.get(key_env, "")).strip()
        if not resolved_api_key:
            raise ProviderConfigurationError(
                f"missing required provider credential: {key_env}"
            )
        resolved_base_url = base_url or os.environ.get(
            str(profile.get("base_url_env", "")),
            "https://api.openai.com/v1/responses",
        )
        parsed = urlsplit(resolved_base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProviderConfigurationError("Responses base URL must be an HTTPS URL")
        return ResponsesProvider(
            model=model or str(profile.get("model", "gpt-5.5")),
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            timeout_seconds=int(profile.get("timeout_seconds", 120)),
        )

    def profile_snapshot(
        self, profile_name: str | None = None, *, model: str | None = None
    ) -> dict[str, str]:
        name = profile_name or self.default_provider
        try:
            profile = self._profiles[name]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"unknown provider profile: {name}"
            ) from exc
        kind = str(profile.get("type", ""))
        if kind == "fake":
            return {"type": "fake", "model": model or "fake", "base_url_host": ""}
        if kind == "codex_cli":
            base_url = os.environ.get(
                "EQUIPMENT_DR_CODEX_BASE_URL",
                "https://api.openai.com/v1",
            )
            return {
                "type": "codex_cli",
                "model": model or str(profile.get("model", "")) or "(cli default)",
                "base_url_host": urlsplit(base_url).hostname or "",
                "command": str(profile.get("command", "codex")),
                "sandbox_mode": str(profile.get("sandbox_mode", "read-only")),
            }
        base_url = os.environ.get(
            str(profile.get("base_url_env", "")),
            "https://api.openai.com/v1/responses",
        )
        return {
            "type": "responses",
            "model": model or str(profile.get("model", "gpt-5.5")),
            "base_url_host": urlsplit(base_url).hostname or "",
        }

    def public_options(self) -> dict[str, Any]:
        profiles = []
        for name, profile in self._profiles.items():
            if name == "fake":
                continue
            kind = str(profile.get("type", ""))
            profiles.append(
                {
                    "id": name,
                    "label": "Codex Agent" if kind == "codex_cli" else "Responses API",
                    "type": kind,
                    "default_model": str(profile.get("model", "")),
                }
            )
        return {
            "default_provider": self.default_provider,
            "providers": profiles,
            "reasoning_efforts": ["low", "medium", "high", "xhigh"],
        }


def _codex_provider_root_url(value: str) -> str:
    """Accept either an API root or a full Responses endpoint for Codex CLI."""

    if not value:
        return value
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if path.endswith("/responses"):
        path = path[: -len("/responses")]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path or "/", parsed.query, parsed.fragment)
    ).rstrip("/")


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProviderConfigurationError(f"{field_name} must be a list of strings")
    return list(value)


def _valid_environment_name(value: str) -> bool:
    return (
        bool(value)
        and (value[0].isalpha() or value[0] == "_")
        and all(character.isalnum() or character == "_" for character in value)
    )
