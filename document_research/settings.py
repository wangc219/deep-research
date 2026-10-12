"""独立模型配置的授权、脱敏与原子持久化。"""

import fcntl
import json
import os
import secrets
import tempfile
from contextlib import contextmanager

from .config import load_config
from .providers import ProviderConfigurationError, model_configured, web_search_settings


def require_admin(config, owner, token):
    """只有显式管理员或兼容旧配置的 local 用户可修改设置。"""
    admins = config.get("settings_admins", ["local"])
    if (
        not isinstance(admins, list)
        or not all(isinstance(item, str) for item in admins)
        or owner not in admins
        or not secrets.compare_digest(
            token.encode(), config["tokens"].get(owner, "").encode()
        )
    ):
        raise PermissionError("settings access denied")


def public_settings(config):
    """不向浏览器返回任何已存储密钥。"""
    model = config.get("model", {})
    if not isinstance(model, dict):
        model = {}
    valid_url = model_configured(
        {"model": model | {"model": "validation", "api_key": "validation"}}
    )
    try:
        search = web_search_settings(config)
    except ProviderConfigurationError:
        search = {
            "provider": "open-websearch",
            "base_url": "",
            "engines": ["bing", "duckduckgo"],
        }
    return {
        "base_url": model.get("base_url", "") if valid_url else "",
        "model": model.get("model", ""),
        "reasoning_effort": model.get("reasoning_effort", ""),
        "has_api_key": bool(model.get("api_key")),
        "model_configured": model_configured(config),
        "web_search": search,
    }


@contextmanager
def settings_lock(directory):
    """串行化配置更新，重新读取授权后才写入。"""
    fd = os.open(
        directory / "settings.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def save_settings(directory, owner, token, values):
    """保留空输入的密钥，并以同目录原子替换配置。"""
    with settings_lock(directory):
        config = load_config(directory)
        require_admin(config, owner, token)
        previous = config.get("model", {})
        if not isinstance(previous, dict):
            previous = {}
        api_key = (
            ""
            if values["clear_api_key"]
            else values["api_key"] or previous.get("api_key", "")
        )
        model = {
            "base_url": values["base_url"].strip().rstrip("/"),
            "model": values["model"].strip(),
            "api_key": api_key,
        }
        if values["reasoning_effort"]:
            model["reasoning_effort"] = values["reasoning_effort"]
        # 验证端点，即使管理员正在清空密钥也不接受不安全地址。
        if not model_configured({"model": model | {"api_key": "validation-only"}}):
            raise ValueError(
                "模型地址须为 HTTPS 或本机 HTTP，不得含凭据、查询或片段；模型名称不能为空。"
            )
        config["model"] = model
        if values.get("web_search") is not None:
            try:
                config["web_search"] = web_search_settings(
                    {"web_search": values["web_search"]}
                )
            except ProviderConfigurationError as exc:
                raise ValueError(str(exc)) from None
        fd, temporary = tempfile.mkstemp(prefix=".config-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(config, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, directory / "config.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return public_settings(config)
