"""Configuration-only provider registry with secret-safe snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
import os
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from equipment_deep_research.providers.codex import CodexCliProvider
from equipment_deep_research.providers.cli_agent import ExternalCliProvider
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.fallback import FallbackProvider
from equipment_deep_research.providers.responses import ResponsesProvider
from equipment_deep_research.providers.openai_compatible import OpenAICompatibleProvider
from equipment_deep_research.execution_model import resolve_model
from equipment_deep_research.model_profiles import credential_env_name, get_profile


class ProviderConfigurationError(ValueError):
    pass


logger = logging.getLogger(__name__)


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

    def supported_protocols(self) -> tuple[str, ...]:
        """Return configured wire protocols for capability discovery/UI."""
        return tuple(sorted({str(item.get("type", "")).strip() for item in self._profiles.values() if item.get("type")}))

    def provider_catalog(self) -> list[dict[str, Any]]:
        """Expose a secret-free catalog for future model adapters."""
        return [
            {"id": name, "type": str(profile.get("type", "")), "model": str(profile.get("model", ""))}
            for name, profile in sorted(self._profiles.items())
        ]

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
            provider_token = _provider_env_token(name)
            codex_key_env = (
                api_key_env
                or str(profile.get("api_key_env", ""))
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_API_KEY_ENV", "")
                or os.environ.get("EQUIPMENT_DR_CODEX_API_KEY_ENV", "")
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
                base_url
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_BASE_URL", "")
                or os.environ.get(str(profile.get("base_url_env", "")), "")
                # Dedicated profiles (DeepSeek / Queen) must never silently
                # inherit the deployment-wide GPT endpoint when their route
                # bridge has not been prepared.
                or (os.environ.get("EQUIPMENT_DR_CODEX_BASE_URL") if name == "codex" else "")
                or str(profile.get("base_url", ""))
                or ""
            ).strip()
            codex_base_url = _codex_provider_root_url(codex_base_url)
            parsed_codex_url = urlsplit(codex_base_url)
            if (
                parsed_codex_url.scheme not in {"https", "http"}
                or not parsed_codex_url.hostname
                or parsed_codex_url.username
                or parsed_codex_url.password
                or parsed_codex_url.query
                or parsed_codex_url.fragment
                or (parsed_codex_url.scheme == "http" and parsed_codex_url.hostname not in {"127.0.0.1", "localhost"})
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
            resolved_model = (
                _codex_model_name(model, profile, provider_name=name)
                if kind == "codex_cli"
                else resolve_model(
                    requested=model,
                    fallback=str(profile.get("model", "")),
                    provider=name,
                )
            )
            return CodexCliProvider(
                command=os.environ.get(
                    "EQUIPMENT_DR_CODEX_COMMAND",
                    str(profile.get("command", "codex")),
                ),
                model=resolved_model,
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
        if kind == "external_cli":
            command = str(profile.get("command", "")).strip()
            if not command:
                raise ProviderConfigurationError(
                    f"external CLI provider {name} requires command"
                )
            provider_token = _provider_env_token(name)
            key_env = str(
                api_key_env
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_API_KEY_ENV", "")
                or profile.get("api_key_env", "")
            ).strip()
            if key_env and not _valid_environment_name(key_env):
                raise ProviderConfigurationError(
                    f"external CLI provider {name} has invalid credential environment"
                )
            resolved_api_key = str(api_key or os.environ.get(key_env, "")).strip()
            url_env = str(profile.get("base_url_env", "")).strip()
            resolved_base_url = str(
                base_url
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_BASE_URL", "")
                or os.environ.get(url_env, profile.get("base_url", ""))
            ).strip()
            return ExternalCliProvider(
                provider_id=name,
                command=command,
                protocol=str(profile.get("protocol", "jsonl")),
                model=resolve_model(
                    requested=model,
                    fallback=str(profile.get("model", "")),
                    provider=name,
                ),
                workspace_path=workspace_path or Path.cwd(),
                runtime_home=(
                    Path(workspace_path or Path.cwd())
                    / "outputs"
                    / "runtime"
                    / "external-cli-homes"
                    / str(isolation_key or name)
                ),
                timeout_seconds=int(profile.get("timeout_seconds", 900)),
                retry_attempts=int(profile.get("retry_attempts", 1)),
                model_flag=str(profile.get("model_flag", "--model")),
                schema_flag=str(profile.get("schema_flag", "")),
                schema_mode=str(profile.get("schema_mode", "file")),
                base_args=_string_list(profile.get("base_args", []), "base_args"),
                extra_args=_string_list(profile.get("extra_args", []), "extra_args"),
                api_key=resolved_api_key,
                api_key_target_env=str(profile.get("api_key_target_env", "")),
                base_url=resolved_base_url,
                base_url_target_env=str(profile.get("base_url_target_env", "")),
                isolation_id=str(isolation_key or name),
                hosted_web_search=bool(profile.get("hosted_web_search", False)),
            )
        if kind in {"openai_compatible", "chat_completions"}:
            provider_token = _provider_env_token(name)
            key_env = str(
                api_key_env
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_API_KEY_ENV", "")
                or profile.get("api_key_env", "")
            ).strip()
            if not _valid_environment_name(key_env):
                raise ProviderConfigurationError(
                    f"provider {name} API key environment variable name is invalid"
                )
            resolved_api_key = str(api_key or os.environ.get(key_env, "")).strip()
            if not resolved_api_key:
                raise ProviderConfigurationError(f"missing required provider credential: {key_env}")
            resolved_base_url = str(
                base_url
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_BASE_URL", "")
                # ``deepseek`` was the public fallback id before the dedicated
                # Codex adapter was introduced.  Keep its old bridge endpoint
                # variable working when the canonical provider variable is
                # absent, so existing deployments and tests remain compatible.
                or (
                    os.environ.get("EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL", "")
                    if name == "deepseek"
                    else ""
                )
                or os.environ.get(str(profile.get("base_url_env", "")), profile.get("base_url", ""))
            ).strip()
            # A fallback provider must not inherit the deployment-wide Codex
            # model (for example gpt-5.5) when no explicit model was passed.
            # Prefer its provider-specific model env, then the profile default.
            # ``create_chain`` deliberately clears ``model`` for fallback
            # providers, so this branch is what selects the configured DeepSeek
            # model from
            # .env.codex-deepseek.
            resolved_model = str(
                str(model or "").strip()
                or os.environ.get(f"EQUIPMENT_DR_{provider_token}_MODEL", "").strip()
                or profile.get("model", "")
            ).strip()
            return OpenAICompatibleProvider(
                provider_id=name,
                model=resolved_model,
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                timeout_seconds=int(profile.get("timeout_seconds", 120)),
                structured_mode=str(profile.get("structured_mode", "json_schema")),
            )
        if kind != "responses_http":
            raise ProviderConfigurationError(f"unsupported provider type: {kind}")
        provider_token = _provider_env_token(name)
        key_env = str(
            api_key_env
            or os.environ.get(f"EQUIPMENT_DR_{provider_token}_API_KEY_ENV", "")
            or profile.get("api_key_env", "")
        )
        if not api_key and not _valid_environment_name(key_env):
            raise ProviderConfigurationError(
                "API key environment variable name is invalid"
            )
        resolved_api_key = str(api_key or os.environ.get(key_env, "")).strip()
        if not resolved_api_key:
            raise ProviderConfigurationError(
                f"missing required provider credential: {key_env}"
            )
        resolved_base_url = (
            base_url
            or os.environ.get(f"EQUIPMENT_DR_{provider_token}_BASE_URL", "")
            or os.environ.get(
                str(profile.get("base_url_env", "")),
                "https://api.openai.com/v1/responses",
            )
        )
        parsed = urlsplit(resolved_base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProviderConfigurationError("Responses base URL must be an HTTPS URL")
        return ResponsesProvider(
            model=resolve_model(
                requested=model,
                fallback=str(profile.get("model", "")),
                provider=name,
            ),
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            timeout_seconds=int(profile.get("timeout_seconds", 120)),
        )

    def profile(self, profile_name: str | None = None) -> dict[str, Any]:
        name = profile_name or self.default_provider
        try:
            return dict(self._profiles[name])
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"unknown provider profile: {name}"
            ) from exc

    def create_chain(
        self,
        profile_name: str | None = None,
        *,
        fallback_profiles: Sequence[str] = (),
        fallback_policy: str | None = None,
        **kwargs: Any,
    ) -> object:
        names = [str(profile_name or self.default_provider), *map(str, fallback_profiles)]
        unique_names = list(dict.fromkeys(names))
        providers = [self.create(unique_names[0], **kwargs)]
        fallback_kwargs = dict(kwargs)
        for key in ("model", "base_url", "api_key_env", "api_key"):
            fallback_kwargs[key] = None
        primary_profile = self._profiles[unique_names[0]]
        policy = str(
            fallback_policy
            or primary_profile.get("fallback_policy", "any")
        ).strip().lower()
        if policy not in {"any", "capacity_only"}:
            raise ProviderConfigurationError(
                "fallback policy must be 'any' or 'capacity_only'"
            )
        for configured_name in unique_names[1:]:
            # ``deepseek`` is the stable public fallback id.  During the
            # Codex migration it was backed by the dedicated Codex bridge;
            # retain that behavior for existing chains while direct
            # ``create('deepseek')`` continues to expose the HTTP adapter.
            name = (
                "codex_deepseek"
                if unique_names[0] == "codex"
                and configured_name == "deepseek"
                and "codex_deepseek" in self._profiles
                else configured_name
            )
            profile = self._profiles[name]
            if bool(profile.get("optional_fallback")) and _profile_credential_missing(
                name, profile
            ):
                logger.warning(
                    "Skipping optional fallback provider %s because its endpoint or credential is not configured",
                    name,
                )
                continue
            providers.append(self.create(name, **fallback_kwargs))
        return (
            providers[0]
            if len(providers) == 1
            else FallbackProvider(providers, fallback_policy=policy)
        )

    def create_model_profile(
        self,
        profile_id: str,
        *,
        workspace_path: str | Path | None = None,
        isolation_key: str | None = None,
    ) -> object:
        """Instantiate a unified model profile without exposing credentials.

        A model profile references a provider adapter by name and may override
        its model, endpoint and fallback chain. Existing provider YAML entries
        remain the adapter registry; adding another model on an existing
        protocol only requires a new model-profile entry.
        """

        _, profile = get_profile(profile_id)
        provider_name = str(profile.get("provider", "")).strip()
        if not provider_name:
            raise ProviderConfigurationError(f"model profile {profile_id} has no provider")
        fallback = profile.get("fallback", {})
        fallback_ids = list(fallback.get("profiles", []) or []) if isinstance(fallback, Mapping) else []
        # GPT capacity fallback prefers Queen, but deployments that have not
        # provisioned Queen credentials must retain DeepSeek as a usable
        # secondary route.
        if str(profile_id) == "codex-gpt" and "codex-queen" in fallback_ids:
            try:
                _, queen_profile = get_profile("codex-queen")
                if _profile_credential_missing("codex-queen", queen_profile):
                    fallback_ids = ["codex-deepseek" if item == "codex-queen" else item for item in fallback_ids]
            except KeyError:
                pass
        fallback_policy = (
            str(fallback.get("policy", "any")).strip().lower()
            if isinstance(fallback, Mapping)
            else "any"
        )
        # ``none`` is valid unified-profile metadata for a direct provider.
        # FallbackProvider itself only understands policies that actually own
        # a chain, so normalize the no-chain case before calling create_chain.
        if fallback_policy == "none":
            fallback_ids = []
            fallback_policy = "any"
        fallback_names: list[str] = []
        for fallback_id in fallback_ids:
            try:
                _, fallback_profile = get_profile(str(fallback_id))
                fallback_names.append(str(fallback_profile.get("provider", fallback_id)).strip())
            except KeyError:
                fallback_names.append(str(fallback_id))
        base_url_env = str(profile.get("base_url_env", "")).strip()
        api_key_env = credential_env_name(profile)
        base_url = os.environ.get(base_url_env, "").strip() if base_url_env else None
        model_env = str(profile.get("model_env", "")).strip()
        resolved_model = (
            (os.environ.get(model_env, "").strip() if model_env else "")
            or str(profile.get("model", "")).strip()
        )
        return self.create_chain(
            provider_name,
            fallback_profiles=fallback_names,
            fallback_policy=fallback_policy,
            model=resolved_model or None,
            base_url=base_url or None,
            api_key_env=api_key_env or None,
            workspace_path=workspace_path,
            isolation_key=isolation_key,
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
        if kind in {"codex_cli", "external_cli"}:
            base_url_env = (
                str(profile.get("base_url_env", ""))
                or ("EQUIPMENT_DR_CODEX_BASE_URL" if kind == "codex_cli" else "")
            )
            base_url = os.environ.get(
                base_url_env,
                str(
                    profile.get(
                        "base_url",
                        "https://api.openai.com/v1"
                        if kind == "codex_cli"
                        else "",
                    )
                ),
            )
            resolved_model = _codex_model_name(model, profile, provider_name=name)
            return {
                "type": kind,
                "model": resolved_model or "(cli default)",
                "base_url_host": urlsplit(base_url).hostname or "",
                "command": str(profile.get("command", "codex")),
                "sandbox_mode": str(profile.get("sandbox_mode", "read-only")),
                "driver": str(profile.get("protocol", "codex_jsonl")),
            }
        if kind in {"openai_compatible", "chat_completions"}:
            base_url = os.environ.get(
                str(profile.get("base_url_env", "")), str(profile.get("base_url", ""))
            )
            return {
                "type": kind,
                "model": resolve_model(requested=model, fallback=str(profile.get("model", "")), provider=name),
                "base_url_host": urlsplit(base_url).hostname or "",
                "driver": "chat_completions",
            }
        base_url = os.environ.get(
            str(profile.get("base_url_env", "")),
            "https://api.openai.com/v1/responses",
        )
        return {
            "type": "responses",
            "model": resolve_model(
                requested=model,
                fallback=str(profile.get("model", "")),
                provider=name,
            ),
            "base_url_host": urlsplit(base_url).hostname or "",
        }

    def public_options(self) -> dict[str, Any]:
        profiles = []
        for name, profile in self._profiles.items():
            if name == "fake":
                continue
            kind = str(profile.get("type", ""))
            default_model = (
                _codex_model_name(None, profile, provider_name=name)
                if kind == "codex_cli"
                else resolve_model(
                    fallback=str(profile.get("model", "")), provider=name
                )
                if kind == "external_cli"
                else resolve_model(
                    fallback=str(profile.get("model", "")), provider=name
                )
            )
            label = str(profile.get("label", "")) or (
                "Codex Agent" if kind == "codex_cli" else "External CLI Agent"
            )
            profiles.append(
                {
                    "id": name,
                    "label": label if kind != "responses_http" else "Responses API",
                    "type": kind,
                    "driver": str(profile.get("protocol", "")),
                    "default_model": default_model,
                    "capabilities": dict(profile.get("capabilities", {})),
                    "command": str(profile.get("command", "")),
                    "available": bool(shutil.which(str(profile.get("command", "")))),
                    "default_base_url": str(
                        os.environ.get(
                            str(
                                profile.get(
                                    "base_url_env",
                                    str(profile.get("base_url_env", ""))
                                    or ("EQUIPMENT_DR_CODEX_BASE_URL" if kind == "codex_cli" else ""),
                                )
                            ),
                            profile.get(
                                "base_url",
                                "https://api.openai.com/v1"
                                if kind == "codex_cli"
                                else "",
                            ),
                        )
                    ),
                    "default_api_key_env": str(
                        profile.get(
                            "api_key_env",
                            str(profile.get("api_key_env", ""))
                            or ("EQUIPMENT_DR_CODEX_API_KEY" if kind == "codex_cli" else ""),
                        )
                    ),
                }
            )
        return {
            "default_provider": self.default_provider,
            "providers": profiles,
            "reasoning_efforts": ["low", "medium", "high", "xhigh"],
        }


def _codex_model_name(
    model: str | None,
    profile: Mapping[str, Any],
    *,
    provider_name: str = "codex",
) -> str:
    """Resolve the Codex model without falling back to the CLI's built-in default."""

    # Dedicated Codex providers must not inherit the primary provider's model.
    # For example, a DeepSeek fallback must never receive the deployment-wide
    # GPT model id.
    if provider_name != "codex":
        provider_token = _provider_env_token(provider_name)
        return (
            str(model or "").strip()
            or os.environ.get(f"EQUIPMENT_DR_{provider_token}_MODEL", "").strip()
            or str(profile.get("model", "")).strip()
        )

    # A direct provider construction is an explicit caller choice (used by
    # tests and one-off API requests). Profile defaults only fill the gap when
    # no model was supplied; deployment-wide EQUIPMENT_DR_MODEL remains
    # authoritative for normal runs.
    if str(model or "").strip() and not os.environ.get("EQUIPMENT_DR_MODEL", "").strip():
        return str(model).strip()
    return resolve_model(
        requested=model,
        fallback=str(profile.get("model", "")),
        provider=provider_name,
    )


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


def _profile_credential_missing(
    provider_name: str, profile: Mapping[str, Any]
) -> bool:
    """Return whether an optional fallback lacks a usable endpoint or key.

    Optional Codex fallbacks are commonly provisioned with an API key in the
    shared environment while their gateway URL is intentionally omitted (for
    example when DeepSeek is disabled in a GPT/Queen-only deployment). Treating
    the key alone as sufficient made ``create_chain('codex')`` instantiate an
    invalid fallback and fail the whole primary run before the first model
    call.  An optional lane is usable only when every explicitly configured
    credential/endpoint input it needs is present.
    """

    if str(profile.get("type", "")).strip() == "fake":
        return False
    provider_token = _provider_env_token(provider_name)
    key_env = str(
        os.environ.get(f"EQUIPMENT_DR_{provider_token}_API_KEY_ENV", "")
        or profile.get("api_key_env", "")
    ).strip()
    if not _valid_environment_name(key_env):
        return True
    if not os.environ.get(key_env, "").strip():
        return True
    base_url_env = str(profile.get("base_url_env", "")).strip()
    if provider_name == "codex_deepseek" and not os.environ.get(
        base_url_env, ""
    ).strip():
        base_url_env = "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL"
    configured_base_url = os.environ.get(base_url_env, "").strip()
    if provider_name == "deepseek" and not configured_base_url:
        configured_base_url = os.environ.get(
            "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL", ""
        ).strip()
    if base_url_env and not configured_base_url:
        # A literal profile base_url is a valid fallback endpoint even when no
        # environment override is set.
        if not str(profile.get("base_url", "")).strip():
            return True
    return False


def _provider_env_token(value: str) -> str:
    return "".join(
        character if character.isalnum() else "_" for character in str(value)
    ).strip("_").upper()
