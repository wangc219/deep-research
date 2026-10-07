"""Resolve execution models from the server environment.

Model ids are deployment configuration, not part of a research task.  The
environment therefore has precedence over model ids persisted in a task or
embedded in the static agent registry.  The latter remain supported as a
backward-compatible fallback for offline tests and older installations.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Any

from equipment_deep_research.model_profiles import (
    active_profile_id,
    get_profile,
    load_profile_config,
    swarm_profile_id,
)


MODEL_ENV = "EQUIPMENT_DR_MODEL"
PROVIDER_ENV = "EQUIPMENT_DR_PROVIDER"
AGENT_MODELS_ENV = "EQUIPMENT_DR_AGENT_MODELS_JSON"
SWARM_MODELS_ENV = "EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON"


def _env_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", str(value)).strip("_").upper()


def _provider_model_from_profiles(provider: str) -> str:
    """Resolve a provider's deployment model from unified profile metadata.

    Dedicated Codex adapters intentionally use provider ids such as
    ``codex_deepseek`` and ``codex_queen`` while deployments expose the model
    through profile-owned variables such as ``EQUIPMENT_DR_DEEPSEEK_MODEL``.
    Looking up ``model_env`` here prevents an unrelated process-wide GPT model
    from leaking into an explicitly selected provider.
    """

    try:
        profiles = load_profile_config().get("profiles", {})
    except (OSError, ValueError):
        return ""
    for profile in profiles.values():
        if not isinstance(profile, Mapping):
            continue
        if str(profile.get("provider", "")).strip() != provider:
            continue
        model_env = str(profile.get("model_env", "")).strip()
        if model_env:
            value = os.environ.get(model_env, "").strip()
            if value:
                return value
    return ""


def configured_model(*, fallback: str = "", provider: str | None = None) -> str:
    """Return the deployment-wide model configured by the environment."""

    if provider:
        provider = str(provider).strip()
        token = _env_token(provider)
        if token:
            provider_value = os.environ.get(f"EQUIPMENT_DR_{token}_MODEL", "").strip()
            if provider_value:
                return provider_value
        profile_value = _provider_model_from_profiles(provider)
        if profile_value:
            return profile_value
        global_provider = configured_provider(fallback="")
        if global_provider and global_provider != provider:
            # Do not leak a global model selected for another provider into
            # this provider.  A run routed to DeepSeek must not inherit the
            # deployment-wide gpt-5.5 model when the active profile is
            # codex-gpt, and vice versa.
            return str(fallback).strip()
    explicit = os.environ.get(MODEL_ENV, "").strip()
    if explicit:
        return explicit
    try:
        _, profile = get_profile(active_profile_id())
        profile_provider = str(profile.get("provider", "")).strip()
        if (not fallback) and (not provider or not profile_provider or profile_provider == provider):
            # Profile metadata intentionally contains no model id. Models are
            # deployment settings loaded from .env.codex.
            profile_model = str(profile.get("model_env", "")).strip()
            if profile_model:
                configured = os.environ.get(profile_model, "").strip()
                if configured:
                    return configured
    except (KeyError, OSError, ValueError):
        pass
    return str(fallback).strip()


def configured_provider(*, fallback: str = "") -> str:
    """Return the deployment-wide provider profile from the environment."""

    explicit = os.environ.get(PROVIDER_ENV, "").strip()
    if explicit:
        return explicit
    try:
        _, profile = get_profile(active_profile_id())
        profile_provider = str(profile.get("provider", "")).strip()
        if profile_provider:
            return profile_provider
    except (KeyError, OSError, ValueError):
        pass
    return str(fallback).strip()


def configured_agent_models() -> dict[str, dict[str, Any]]:
    """Parse optional per-agent model profiles without exposing secrets."""

    raw = os.environ.get(AGENT_MODELS_ENV, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, Mapping):
        return {}
    profiles = {
        str(agent_id): dict(profile)
        for agent_id, profile in value.items()
        if isinstance(profile, Mapping)
    }
    # Simple env-only overrides avoid editing JSON for one-off deployments.
    prefix = "EQUIPMENT_DR_AGENT_"
    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue
        suffix_map = {
            "_MODEL": "model",
            "_PROVIDER": "provider",
            "_BASE_URL": "base_url",
            "_API_KEY_ENV": "api_key_env",
        }
        suffix = next((item for item in suffix_map if key.endswith(item)), None)
        if suffix is None:
            continue
        agent_id = key[len(prefix) : -len(suffix)].lower()
        if agent_id and str(raw_value).strip():
            profiles.setdefault(agent_id, {})[suffix_map[suffix]] = str(raw_value).strip()
    return profiles


def configured_swarm_models() -> dict[str, Any]:
    """Parse dynamic-swarm model routing by agent id or specialist archetype."""

    raw = os.environ.get(SWARM_MODELS_ENV, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def resolve_model(
    agent_id: str | None = None,
    *,
    requested: str | None = None,
    fallback: str = "",
    provider: str | None = None,
) -> str:
    """Resolve one model with environment configuration taking precedence."""

    if agent_id:
        profile = configured_agent_models().get(agent_id, {})
        per_agent = str(profile.get("model", "")).strip()
        if per_agent:
            return per_agent
        agent_env = os.environ.get(
            f"EQUIPMENT_DR_AGENT_{_env_token(agent_id)}_MODEL", ""
        ).strip()
        if agent_env:
            return agent_env
    return configured_model(
        fallback=str(requested or fallback),
        provider=provider,
    )


def resolve_agent_model_profiles(
    profiles: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Merge persisted/requested profiles with environment model overrides."""

    merged = {
        str(agent_id): dict(profile)
        for agent_id, profile in (profiles or {}).items()
    }
    env_profiles = configured_agent_models()
    global_provider = configured_provider()
    if global_provider:
        for agent_id, target in merged.items():
            env_provider = str(env_profiles.get(agent_id, {}).get("provider", "")).strip()
            declared = str(target.get("provider", "")).strip()
            if not env_provider and declared in {"", "default", "codex"}:
                target["provider"] = global_provider
    for agent_id, env_profile in env_profiles.items():
        target = merged.setdefault(agent_id, {})
        target.update(env_profile)
    global_model = configured_model()
    if global_model:
        # A deployment-wide model is only a fallback for agent profiles that
        # still have no model.  Task-level profiles (and explicit per-agent
        # environment overrides) are authoritative so different research
        # tasks can select different model profiles without being rewritten
        # to a global default.
        for agent_id, target in merged.items():
            if (
                not str(env_profiles.get(agent_id, {}).get("model", "")).strip()
                and not str(target.get("model", "")).strip()
            ):
                target["model"] = global_model
    return merged


def resolve_swarm_model(
    agent_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    fallback: str = "",
) -> str:
    """Resolve a dynamic swarm model by exact id, archetype, then run model.

    ``fallback`` is the task's already-resolved provider model (from the
    selected model profile). It wins over the deployment-wide
    ``EQUIPMENT_DR_MODEL`` so a DeepSeek / Kimi task is not rewritten to the
    GPT gateway model id. Explicit per-agent and swarm JSON overrides remain
    the escape hatch for intentional canaries.
    """

    exact = configured_agent_models().get(agent_id, {}).get("model")
    if str(exact or "").strip():
        return str(exact).strip()

    candidates = [str(agent_id).strip()]
    if str(agent_id).startswith("winning_swarm_"):
        candidates.append(str(agent_id)[len("winning_swarm_") :])
    payload_candidates: list[Mapping[str, Any]] = []
    pending = [payload] if isinstance(payload, Mapping) else []
    while pending:
        item = pending.pop()
        payload_candidates.append(item)
        for key in ("input", "task_input"):
            child = item.get(key)
            if isinstance(child, Mapping):
                pending.append(child)
    for item in payload_candidates:
        task = item.get("specialist_task")
        if isinstance(task, Mapping):
            archetype = str(task.get("archetype", "")).strip()
            if archetype:
                candidates.extend((archetype, f"winning_swarm_{archetype}"))
        dynamic_spec = item.get("dynamic_agent_spec")
        if isinstance(dynamic_spec, Mapping):
            archetype = str(dynamic_spec.get("archetype", "")).strip()
            if archetype:
                candidates.extend((archetype, f"winning_swarm_{archetype}"))

    configured = configured_swarm_models()
    for candidate in dict.fromkeys(candidates):
        value = configured.get(candidate)
        if isinstance(value, Mapping):
            value = value.get("model")
        if str(value or "").strip():
            return str(value).strip()
    wildcard = configured.get("*")
    if isinstance(wildcard, Mapping):
        wildcard = wildcard.get("model")
    if str(wildcard or "").strip():
        return str(wildcard).strip()
    profile_id = swarm_profile_id(agent_id, payload)
    if profile_id:
        try:
            _, profile = get_profile(profile_id)
            model_env = str(profile.get("model_env", "")).strip()
            profile_model = os.environ.get(model_env, "").strip() if model_env else ""
            if profile_model:
                return profile_model
        except (KeyError, OSError, ValueError):
            pass
    if str(fallback or "").strip():
        return str(fallback).strip()
    return configured_model(fallback="")


__all__ = [
    "AGENT_MODELS_ENV",
    "MODEL_ENV",
    "PROVIDER_ENV",
    "SWARM_MODELS_ENV",
    "configured_agent_models",
    "configured_swarm_models",
    "configured_model",
    "configured_provider",
    "resolve_agent_model_profiles",
    "resolve_model",
    "resolve_swarm_model",
]
