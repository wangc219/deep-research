"""Unified, secret-safe model profile registry.

Profiles describe providers and model ids, while credentials remain external
environment variables.  The module is intentionally independent from the
provider registry so shell launchers, the API and the CLI can share it without
introducing an import cycle.
"""

from __future__ import annotations

import os
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import yaml


PROFILE_ENV = "EQUIPMENT_DR_PROFILE"
SWARM_OVERRIDES_ENV = "EQUIPMENT_DR_SWARM_PROFILE_OVERRIDES_JSON"
DEFAULT_PROFILE_PATH = Path("configs/equipment_deep_research/model-profiles.yaml")

# Keep renamed profiles readable for persisted runs and older browser state.
# Aliases are deliberately one-way and are never included in the public
# profile catalog.
LEGACY_PROFILE_ALIASES = {
    "deepseek-openlux": "codex-deepseek",
    # Kimi was the previous UI label for this slot. Keep persisted tasks and
    # old .env.local selections readable while the canonical profile becomes
    # Queen (Qwen).
    "codex-kimi": "codex-queen",
    "kimi": "codex-queen",
} 


def normalize_profile_id(profile_id: str | None) -> str:
    """Return the canonical id for a profile or a persisted legacy alias."""

    selected = str(profile_id or "").strip()
    return LEGACY_PROFILE_ALIASES.get(selected, selected)


def profile_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    project_root = Path(os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", Path.cwd()))
    return (project_root / DEFAULT_PROFILE_PATH).resolve()


def load_profile_config(path: str | Path | None = None) -> dict[str, Any]:
    target = profile_path(path)
    if not target.is_file():
        return {"version": 1, "default_profile": "", "profiles": {}, "swarm_overrides": {}}
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise ValueError("model-profiles.yaml must contain a mapping")
    profiles = payload.get("profiles", {})
    if not isinstance(profiles, Mapping):
        raise ValueError("model-profiles.yaml profiles must be a mapping")
    normalized: dict[str, dict[str, Any]] = {}
    for name, raw in profiles.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"model profile {name} must be a mapping")
        normalized[str(name)] = dict(raw)
    swarm_overrides = dict(payload.get("swarm_overrides", {}) or {})
    raw_overrides = os.environ.get(SWARM_OVERRIDES_ENV, "").strip()
    if raw_overrides:
        try:
            env_overrides = yaml.safe_load(raw_overrides)
        except yaml.YAMLError:
            env_overrides = None
        if isinstance(env_overrides, Mapping):
            swarm_overrides.update({str(key): value for key, value in env_overrides.items()})
    return {
        "version": int(payload.get("version", 1)),
        "default_profile": str(payload.get("default_profile", "")).strip(),
        "profiles": normalized,
        "swarm_overrides": swarm_overrides,
    }


def profile_ids(path: str | Path | None = None) -> list[str]:
    return list(load_profile_config(path)["profiles"])


def active_profile_id(path: str | Path | None = None) -> str:
    config = load_profile_config(path)
    requested = normalize_profile_id(os.environ.get(PROFILE_ENV, ""))
    if requested and requested in config["profiles"]:
        return requested
    default = normalize_profile_id(str(config.get("default_profile", "")).strip())
    return default if default in config["profiles"] else ""


def get_profile(profile_id: str | None = None, path: str | Path | None = None) -> tuple[str, dict[str, Any]]:
    config = load_profile_config(path)
    selected = normalize_profile_id(
        str(profile_id or os.environ.get(PROFILE_ENV, "") or config.get("default_profile", ""))
    )
    if selected not in config["profiles"]:
        raise KeyError(f"unknown model profile: {selected or '(empty)'}")
    return selected, dict(config["profiles"][selected])


def _env_name(value: object) -> str:
    return str(value or "").strip()


def _model_from_env(profile: Mapping[str, Any]) -> str:
    """Resolve a profile's model exclusively from deployment environment.

    Model ids vary by gateway and must not be frozen in source-controlled
    profile metadata. ``model_env`` is the preferred explicit mapping; the
    provider-based fallback keeps older local profile files working while
    still sourcing the actual id from the environment.
    """

    model_env = _env_name(profile.get("model_env"))
    if not model_env:
        provider = _env_name(profile.get("provider"))
        model_env = {
            "codex": "EQUIPMENT_DR_MODEL",
            "deepseek": "EQUIPMENT_DR_DEEPSEEK_MODEL",
            "queen": "EQUIPMENT_DR_QUEEN_MODEL",
        }.get(provider, "")
    return os.environ.get(model_env, "").strip() if model_env else ""


def _endpoint_from_env(profile: Mapping[str, Any]) -> str:
    env_name = _env_name(profile.get("base_url_env"))
    if env_name:
        return os.environ.get(env_name, "").strip()
    return _env_name(profile.get("base_url"))


def _endpoint_host(url: str) -> str:
    return str(urlsplit(url).hostname or "")


def _credential_configured(profile: Mapping[str, Any]) -> bool:
    env_name = credential_env_name(profile)
    return bool(env_name and os.environ.get(env_name, "").strip())


def credential_env_name(profile: Mapping[str, Any]) -> str:
    """Resolve the actual secret variable, including Codex indirection."""

    provider = _env_name(profile.get("provider"))
    declared = _env_name(profile.get("api_key_env"))
    # Codex profiles that declare a non-default key env (for example Queen)
    # keep that mapping; only the default Codex key participates in aliasing.
    if provider in {"codex", "codex_deepseek"}:
        alias_name = (
            "EQUIPMENT_DR_CODEX_DEEPSEEK_API_KEY_ENV"
            if provider == "codex_deepseek"
            else "EQUIPMENT_DR_CODEX_API_KEY_ENV"
        )
        default_declared = (
            "DEEPSEEK_API_KEY"
            if provider == "codex_deepseek"
            else "EQUIPMENT_DR_CODEX_API_KEY"
        )
        alias = os.environ.get(alias_name, "").strip()
        if alias and (not declared or declared == default_declared):
            return alias
    return declared


def _model_ids_from_payload(data: object) -> set[str]:
    """Extract model ids from heterogeneous OpenAI-compatible /models bodies."""

    ids: set[str] = set()
    if not isinstance(data, Mapping):
        return ids
    items = data.get("data", data.get("models", []))
    if isinstance(items, Mapping):
        items = list(items.values()) if items else list(items.keys())
    if not isinstance(items, list):
        return ids
    for item in items:
        if isinstance(item, Mapping):
            for key in ("id", "model", "name"):
                value = str(item.get(key) or "").strip()
                if value:
                    ids.add(value)
                    break
        elif item is not None:
            value = str(item).strip()
            if value:
                ids.add(value)
    return ids


def _model_listed(model: str, ids: set[str]) -> bool:
    """Exact or relay-friendly match (prefix/suffix after '/' or ':')."""

    needle = str(model or "").strip()
    if not needle or not ids:
        return False
    if needle in ids:
        return True
    lowered = {item.lower(): item for item in ids}
    if needle.lower() in lowered:
        return True
    for item in ids:
        if item.endswith(f"/{needle}") or item.endswith(f":{needle}"):
            return True
        if needle.endswith(f"/{item}") or needle.endswith(f":{item}"):
            return True
    return False


def public_profile(profile_id: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    fallback = profile.get("fallback", {})
    if not isinstance(fallback, Mapping):
        fallback = {}
    endpoint = _endpoint_from_env(profile)
    return {
        "id": profile_id,
        "label": _env_name(profile.get("label")) or profile_id,
        "provider": _env_name(profile.get("provider")),
        "protocol": _env_name(profile.get("protocol")) or "unknown",
        "model": _model_from_env(profile),
        "endpoint_host": _endpoint_host(endpoint),
        "api_key_env": credential_env_name(profile),
        "credential_configured": _credential_configured(profile),
        "fallback_policy": _env_name(fallback.get("policy")) or "none",
        "fallback_profiles": [str(item) for item in fallback.get("profiles", []) or []],
        "deprecated": bool(profile.get("deprecated", False)),
    }


def public_profiles(path: str | Path | None = None) -> dict[str, Any]:
    config = load_profile_config(path)
    active = active_profile_id(path)
    profiles = [public_profile(name, profile) for name, profile in config["profiles"].items()]
    return {
        "version": config.get("version", 1),
        "default_profile": normalize_profile_id(config.get("default_profile", "")),
        "active_profile": active,
        "profiles": profiles,
        "swarm_overrides": {
            str(role): normalize_profile_id(str(profile_id))
            for role, profile_id in dict(config.get("swarm_overrides", {})).items()
        },
    }


def swarm_profile_id(agent_id: str, payload: Mapping[str, Any] | None = None, path: str | Path | None = None) -> str:
    config = load_profile_config(path)
    overrides = config.get("swarm_overrides", {})
    if not isinstance(overrides, Mapping):
        return ""
    candidates = [str(agent_id)]
    if str(agent_id).startswith("winning_swarm_"):
        candidates.append(str(agent_id)[len("winning_swarm_") :])
    if isinstance(payload, Mapping):
        mission_node = str(payload.get("mission_node", "")).strip()
        if mission_node:
            candidates.extend((mission_node, mission_node.upper(), f"winning_{mission_node.lower()}"))
        task = payload.get("specialist_task")
        if isinstance(task, Mapping):
            archetype = str(task.get("archetype", "")).strip()
            if archetype:
                candidates.extend((archetype, f"winning_swarm_{archetype}"))
    for candidate in candidates:
        value = overrides.get(candidate)
        if isinstance(value, Mapping):
            value = value.get("profile")
        if str(value or "").strip():
            return normalize_profile_id(str(value).strip())
    return ""


def profile_environment(profile_id: str, path: str | Path | None = None) -> dict[str, str]:
    """Return safe environment assignments for a launcher.

    Values are metadata from the profile; secret values are never returned.
    Endpoint and key values are read from the referenced environment names so
    the legacy .env.codex* files remain the source of credentials.
    """

    _, profile = get_profile(profile_id, path)
    provider = _env_name(profile.get("provider"))
    assignments: dict[str, str] = {}
    if provider:
        assignments["EQUIPMENT_DR_PROVIDER"] = provider
    base_env = _env_name(profile.get("base_url_env"))
    key_env = credential_env_name(profile)
    provider_token = re.sub(r"[^A-Za-z0-9]", "_", provider).strip("_").upper()
    if provider_token and base_env:
        assignments[f"EQUIPMENT_DR_{provider_token}_BASE_URL"] = os.environ.get(base_env, "").strip()
    if provider_token and key_env:
        assignments[f"EQUIPMENT_DR_{provider_token}_API_KEY_ENV"] = key_env
    if provider == "deepseek":
        if base_env:
            assignments["EQUIPMENT_DR_DEEPSEEK_BASE_URL"] = os.environ.get(base_env, "").strip()
        if key_env:
            assignments["EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV"] = key_env
    elif provider == "codex":
        if base_env:
            assignments["EQUIPMENT_DR_CODEX_BASE_URL"] = os.environ.get(base_env, "").strip()
        if key_env:
            assignments["EQUIPMENT_DR_CODEX_API_KEY_ENV"] = key_env
    elif provider:
        if base_env:
            assignments["EQUIPMENT_DR_BASE_URL"] = os.environ.get(base_env, "").strip()
        if key_env:
            assignments["EQUIPMENT_DR_API_KEY_ENV"] = key_env
    fallback = profile.get("fallback", {})
    if isinstance(fallback, Mapping):
        fallback_profiles = []
        for item in fallback.get("profiles", []) or []:
            fallback_id = str(item).strip()
            if not fallback_id:
                continue
            try:
                _, fallback_profile = get_profile(fallback_id, path)
                fallback_profiles.append(_env_name(fallback_profile.get("provider")) or fallback_id)
            except KeyError:
                fallback_profiles.append(fallback_id)
        if fallback_profiles:
            assignments["EQUIPMENT_DR_FALLBACK_PROFILES"] = ",".join(fallback_profiles)
            assignments["EQUIPMENT_DR_FALLBACK_POLICY"] = _env_name(fallback.get("policy")) or "any"
    return assignments


def profile_execution(profile_id: str, path: str | Path | None = None) -> dict[str, str]:
    """Return the safe execution tuple for a profile without mutating globals.

    Unlike :func:`profile_environment`, this is not a launcher payload. It is
    the per-run contract consumed by the API when a research task pins a model
    profile: provider, model, endpoint and credential environment name are all
    resolved from the profile registry. Secrets are never included.
    """

    selected, profile = get_profile(profile_id, path)
    return {
        "profile_id": selected,
        "provider": _env_name(profile.get("provider")),
        "model": _model_from_env(profile),
        "base_url": _endpoint_from_env(profile),
        "api_key_env": credential_env_name(profile),
    }


def activate_profile(profile_id: str, *, path: str | Path | None = None, env_file: str | Path | None = None) -> dict[str, Any]:
    """Persist only the selected profile id in a controlled local env file."""

    selected, profile = get_profile(profile_id, path)
    target = Path(env_file or (profile_path(path).parents[2] / ".env.local")).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    # Replace the complete activation tuple, not only the profile id.  Older
    # versions appended provider/model assignments on every UI click; that
    # left a misleading stack of stale values in .env.local and made the
    # effective profile depend on whichever duplicate happened to be last.
    activation_names = {"EQUIPMENT_DR_PROFILE"}
    # The activation file selects the profile only. Provider and model values
    # remain deployment-owned settings in .env.codex and are never copied into
    # .env.local by the UI.
    replacement_lines = [f"EQUIPMENT_DR_PROFILE={selected}"]
    replaced = False
    output: list[str] = []
    for line in lines:
        assignment_name = line.split("=", 1)[0].strip() if "=" in line else ""
        if assignment_name in activation_names:
            if not replaced:
                output.extend(replacement_lines)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.extend(replacement_lines)
    target.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return {"profile_id": selected, "env_file": str(target), "restart_required": True}


def activate_swarm_overrides(
    overrides: Mapping[str, str],
    *,
    path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    config = load_profile_config(path)
    normalized: dict[str, str] = {}
    for role, profile_id in overrides.items():
        role_name = str(role).strip()
        selected = normalize_profile_id(str(profile_id).strip())
        if not role_name or not selected:
            continue
        if selected not in config["profiles"]:
            raise KeyError(f"unknown model profile: {selected}")
        normalized[role_name] = selected
    target = Path(env_file or (profile_path(path).parents[2] / ".env.local")).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    # Quote as a shell assignment so dotenv sourcing preserves JSON quotes.
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    assignment = f'{SWARM_OVERRIDES_ENV}="{encoded}"'
    pattern = re.compile(rf"^\s*{re.escape(SWARM_OVERRIDES_ENV)}\s*=")
    output: list[str] = []
    replaced = False
    for line in lines:
        if pattern.match(line):
            if not replaced:
                output.append(assignment)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(assignment)
    target.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return {"swarm_overrides": normalized, "env_file": str(target), "restart_required": True}


def doctor_profile(profile_id: str, path: str | Path | None = None) -> dict[str, Any]:
    selected, profile = get_profile(profile_id, path)
    endpoint = _endpoint_from_env(profile)
    key_env = credential_env_name(profile)
    model = _model_from_env(profile)
    model_env = _env_name(profile.get("model_env")) or {
        "codex": "EQUIPMENT_DR_MODEL",
        "deepseek": "EQUIPMENT_DR_DEEPSEEK_MODEL",
        "queen": "EQUIPMENT_DR_QUEEN_MODEL",
    }.get(_env_name(profile.get("provider")), "")
    result: dict[str, Any] = {
        "profile_id": selected,
        "provider": _env_name(profile.get("provider")),
        "model": model,
        "model_env": model_env,
        "endpoint_host": _endpoint_host(endpoint),
        "credential_configured": bool(key_env and os.environ.get(key_env, "").strip()),
        "reachable": False,
        "model_available": None,
        "models_listed": 0,
        "errors": [],
    }
    if not endpoint:
        result["errors"].append("base URL is not configured")
        return result
    if not result["credential_configured"]:
        result["errors"].append(f"missing environment credential: {key_env or '(unset)'}")
        return result
    if not model:
        result["errors"].append(
            f"model id is not configured ({model_env or 'model_env'} in .env)"
        )
        return result
    headers = {"Authorization": f"Bearer {os.environ.get(key_env, '').strip()}"}
    models_url = _models_url(endpoint)
    result["models_url_host"] = _endpoint_host(models_url)
    try:
        request = urllib.request.Request(models_url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=8) as response:
            result["reachable"] = 200 <= int(response.status) < 300
            body = response.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = yaml.safe_load(body) if body else {}
            ids = _model_ids_from_payload(data)
            result["models_listed"] = len(ids)
            if not ids:
                # Many relays return 200 with an empty or non-standard body while
                # still serving chat/completions. Leave availability unknown.
                result["model_available"] = None
            else:
                result["model_available"] = _model_listed(model, ids)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        result["errors"].append(str(exc))
    return result


def _models_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    elif path.endswith("/responses"):
        path = path[: -len("/responses")]
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/models", "", ""))


__all__ = [
    "DEFAULT_PROFILE_PATH",
    "PROFILE_ENV",
    "SWARM_OVERRIDES_ENV",
    "activate_profile",
    "activate_swarm_overrides",
    "active_profile_id",
    "doctor_profile",
    "get_profile",
    "load_profile_config",
    "normalize_profile_id",
    "profile_environment",
    "profile_execution",
    "profile_ids",
    "profile_path",
    "public_profile",
    "public_profiles",
    "credential_env_name",
    "swarm_profile_id",
]
