"""Explicit, private configuration for the local document research process."""

import json
import os
import secrets
import stat
from pathlib import Path


def validate_data_dir(value: str | Path) -> Path:
    """拒绝相对路径、源码目录及原平台运行目录。"""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("data-dir 必须是绝对路径。")
    path = path.resolve()
    repository = Path(__file__).resolve().parent.parent
    if path == repository or path.is_relative_to(repository):
        raise ValueError("data-dir 必须位于源码仓库之外，不能使用平台数据目录。")
    # Prevent common shared runtime locations even when their checkout is elsewhere.
    if {"backend", "outputs", "workspaces", "projects"}.intersection(path.parts):
        raise ValueError("data-dir 不能复用 backend/outputs/workspaces/projects 目录。")
    return path


def load_config(data_dir: str | Path) -> dict:
    """每次读取当前独立配置，令牌与知识库授权撤销可立即生效。"""
    path = validate_data_dir(data_dir) / "config.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("缺少独立 config.json；请先使用 --init 初始化。")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("config.json 必须仅当前用户可读写（chmod 600）。")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("独立配置文件过大。")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("独立配置文件无法读取或格式错误。") from exc
    if not isinstance(config, dict) or not isinstance(config.get("tokens"), dict):
        raise ValueError("config.json 必须包含 tokens 对象。")  # noqa: TRY004 -- Invalid JSON configuration, not a programming type error.
    token_values = []
    for owner, token in config["tokens"].items():
        if not isinstance(owner, str) or not owner or len(owner) > 100:
            raise ValueError("独立配置的用户名无效。")
        if not isinstance(token, str) or not 24 <= len(token) <= 512:
            raise ValueError("独立访问令牌必须为 24 到 512 个字符。")
        token_values.append(token)
    if len(set(token_values)) != len(token_values):
        raise ValueError("独立访问令牌不得重复。")
    return config


def init_config(data_dir: str | Path) -> Path:
    """独占创建最小权限配置；不覆盖已有文件，也不打印令牌。"""
    directory = validate_data_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / "config.json"
    config = {
        "tokens": {"local": secrets.token_urlsafe(32)},
        "settings_admins": ["local"],
        "model": {"base_url": "", "api_key": "", "model": ""},
        "zhipu": {"api_key": "", "libraries": {"local": []}},
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return path
