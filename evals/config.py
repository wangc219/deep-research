from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
import json
import os
import shutil
import subprocess

import yaml


REQUIRED_BASELINE_SYSTEMS = {
    "generic_deep_research",
    "generic_agent",
    "bare_llm",
    "zhipu_llm",
}
REQUIRED_PROVIDERS = {"dashscope", "openai", "zhipu"}
EXPECTED_ADAPTERS = {
    "generic_deep_research": "dashscope_deep_research",
    "generic_agent": "codex_cli",
    "bare_llm": "compatible_llm",
    "zhipu_llm": "compatible_llm",
}
EXPECTED_PROVIDERS = {
    "generic_deep_research": "dashscope",
    "generic_agent": "openai",
    "bare_llm": "openai",
    "zhipu_llm": "zhipu",
}
ALLOWED_REASONING = {"none", "low", "medium", "high", "xhigh", "max"}


def load_eval_config(path: str | Path, *, project_root: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("eval configuration must be an object")
    project_root = Path(project_root).resolve()
    for value in payload.get("dotenv_files", ["evals/.env"]):
        dotenv_path = Path(str(value))
        if not dotenv_path.is_absolute():
            dotenv_path = project_root / dotenv_path
        _load_dotenv(dotenv_path)
    validate_eval_config(payload)
    payload["_config_path"] = str(config_path)
    return payload


def validate_eval_config(payload: dict[str, Any]) -> None:
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("eval config requires providers")
    missing_providers = sorted(REQUIRED_PROVIDERS - set(providers))
    if missing_providers:
        raise ValueError(f"eval config is missing providers: {', '.join(missing_providers)}")
    for provider_id in REQUIRED_PROVIDERS:
        provider = providers[provider_id]
        if not isinstance(provider, dict):
            raise ValueError(f"provider {provider_id} must be an object")
        for field in ("base_url_env", "api_key_env"):
            if not str(provider.get(field, "")).strip():
                raise ValueError(f"providers.{provider_id}.{field} is required")

    systems = payload.get("systems")
    if not isinstance(systems, dict):
        raise ValueError("eval config requires systems")
    missing = sorted(REQUIRED_BASELINE_SYSTEMS - set(systems))
    if missing:
        raise ValueError(f"eval config is missing systems: {', '.join(missing)}")
    for system_id in REQUIRED_BASELINE_SYSTEMS:
        row = systems[system_id]
        if not isinstance(row, dict):
            raise ValueError(f"system {system_id} must be an object")
        if row.get("adapter") != EXPECTED_ADAPTERS[system_id]:
            raise ValueError(f"system {system_id} must use the {EXPECTED_ADAPTERS[system_id]} adapter")
        if row.get("provider") != EXPECTED_PROVIDERS[system_id]:
            raise ValueError(f"system {system_id} must use provider {EXPECTED_PROVIDERS[system_id]}")
        if not str(row.get("model", "")).strip():
            raise ValueError(f"system {system_id} requires a model")

    for system_id in {"generic_agent", "bare_llm", "zhipu_llm"}:
        effort = str(systems[system_id].get("reasoning_effort", ""))
        if effort not in ALLOWED_REASONING:
            raise ValueError(f"system {system_id} has invalid reasoning_effort")
    if systems["generic_deep_research"].get("output_format") not in {
        "model_detailed_report",
        "model_summary_report",
    }:
        raise ValueError("generic_deep_research has invalid output_format")
    if systems["generic_agent"].get("sandbox") != "read-only":
        raise ValueError("generic_agent must use the read-only sandbox")
    if not str(systems["generic_agent"].get("command", "")).strip():
        raise ValueError("generic_agent requires a Codex command")
    if systems["generic_agent"].get("auth_mode") != "eval_api_key":
        raise ValueError("generic_agent must use explicit API URL/key authentication")

    for system_id in {"generic_agent", "bare_llm", "zhipu_llm"}:
        web = systems[system_id].get("web_search", {})
        if not isinstance(web, dict):
            raise ValueError(f"system {system_id}.web_search must be an object")
    if not bool(systems["generic_agent"]["web_search"].get("enabled")):
        raise ValueError("generic_agent must enable web search")
    if bool(systems["bare_llm"]["web_search"].get("enabled")):
        raise ValueError("bare_llm must not enable web search")
    if bool(systems["zhipu_llm"]["web_search"].get("enabled")):
        raise ValueError("zhipu_llm must not enable web search")
    for system_id in {"bare_llm", "zhipu_llm"}:
        if systems[system_id].get("api_protocol", "responses") not in {
            "responses",
            "chat_completions",
        }:
            raise ValueError(f"{system_id} has invalid api_protocol")
    if systems["zhipu_llm"].get("api_protocol") != "chat_completions":
        raise ValueError("zhipu_llm must use chat_completions")


def config_status(
    payload: dict[str, Any],
    *,
    selected_systems: list[str] | None = None,
) -> dict[str, Any]:
    providers = dict(payload["providers"])
    provider_status: dict[str, Any] = {}
    for provider_id, provider in providers.items():
        base_url_env = str(provider["base_url_env"])
        api_key_env = str(provider["api_key_env"])
        base_url = os.environ.get(base_url_env, "")
        api_key_present = bool(os.environ.get(api_key_env))
        provider_ready = bool(base_url and api_key_present)
        provider_status[provider_id] = {
            "base_url_env": base_url_env,
            "base_url_present": bool(base_url),
            "base_url_host": urlsplit(base_url).hostname or "" if base_url else "",
            "api_key_env": api_key_env,
            "api_key_present": api_key_present,
            "ready": provider_ready,
        }

    systems = dict(payload["systems"])
    codex = _codex_status(str(systems["generic_agent"].get("command", "codex")))
    codex_auth_path = Path.home() / ".codex" / "auth.json"
    codex_auth_present = codex_auth_path.is_file()
    codex_auth_mode = _codex_auth_mode(codex_auth_path)
    selected = selected_systems or sorted(REQUIRED_BASELINE_SYSTEMS)
    readiness: dict[str, bool] = {}
    for system_id in selected:
        if system_id == "full_method":
            readiness[system_id] = bool(codex["present"] and codex_auth_present)
        elif system_id == "generic_agent":
            readiness[system_id] = bool(codex["present"] and provider_status["openai"]["ready"])
        elif system_id == "generic_deep_research":
            readiness[system_id] = bool(provider_status["dashscope"]["ready"])
        elif system_id == "bare_llm":
            readiness[system_id] = bool(provider_status["openai"]["ready"])
        elif system_id == "zhipu_llm":
            readiness[system_id] = bool(provider_status["zhipu"]["ready"])
        else:
            readiness[system_id] = True
    return {
        "config_path": str(payload.get("_config_path", "")),
        "providers": provider_status,
        "codex_cli": {**codex, "auth_present": codex_auth_present, "auth_mode": codex_auth_mode},
        "selected_systems": selected,
        "system_readiness": readiness,
        "systems": {
            system_id: {
                "adapter": row.get("adapter"),
                "api_protocol": row.get("api_protocol", ""),
                "auth_mode": row.get("auth_mode", ""),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "reasoning_effort": row.get("reasoning_effort"),
                "background": bool(row.get("background")),
                "web_search": bool((row.get("web_search") or {}).get("enabled")),
                "max_tool_calls": row.get("max_tool_calls", 0),
                "max_output_tokens": row.get("max_output_tokens", 0),
                "output_format": row.get("output_format", ""),
            }
            for system_id, row in systems.items()
        },
        "ready": bool(readiness and all(readiness.values())),
    }


def resolved_system_config(payload: dict[str, Any], system_id: str) -> dict[str, Any]:
    if system_id not in payload.get("systems", {}):
        raise KeyError(f"system is not configured: {system_id}")
    row = dict(payload["systems"][system_id])
    provider_id = str(row["provider"])
    provider = dict(payload["providers"][provider_id])
    base_url_env = str(row.get("base_url_env") or provider["base_url_env"])
    api_key_env = str(row.get("api_key_env") or provider["api_key_env"])
    row["base_url_env"] = base_url_env
    row["base_url"] = os.environ.get(base_url_env, "")
    row["api_key_env"] = api_key_env
    row["api_key"] = os.environ.get(api_key_env, "")
    return row


def _codex_auth_mode(path: Path) -> str:
    if not path.is_file():
        return "none"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unknown"
    mode = str(payload.get("auth_mode") or "").strip().lower()
    return mode or "unknown"


def _codex_status(command: str) -> dict[str, Any]:
    executable = shutil.which(command)
    version = ""
    if executable:
        try:
            process = subprocess.run(
                [executable, "--version"],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            version = (process.stdout or process.stderr).strip().splitlines()[-1]
        except Exception:
            version = ""
    return {
        "command": command,
        "present": bool(executable),
        "path": executable or "",
        "version": version,
    }


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
