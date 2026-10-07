"""把平台 Model Spec 映射为装备研究运行时凭证，领域包不直接依赖 platform_core。

聊天模型、API Key 与 Base URL 的来源是前端「模型设置」，不是 ``.env``。
DeepResearchRunner 只接受 mode=fake|real。平台聊天模型走 providers.yaml 的
``platform``（OpenAI Chat Completions）。Worker 仅在单次执行内临时覆盖
``EQUIPMENT_DR_*``，密钥不写入 run.payload。
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Any

from platform_core.config.options import system_options
from platform_core.models.providers.cache import ModelInfo, model_cache
from platform_core.utils import get_docker_safe_url

_ENV_LOCK = Lock()
PLATFORM_PROVIDER_NAME = "platform"
PLATFORM_PROFILE_ID = "platform-chat"
API_KEY_ENV = "EQUIPMENT_DR_API_KEY"
BASE_URL_ENV = "EQUIPMENT_DR_BASE_URL"
MODEL_ENV = "EQUIPMENT_DR_MODEL"
PROVIDER_ENV = "EQUIPMENT_DR_PROVIDER"
PROFILE_ENV = "EQUIPMENT_DR_PROFILE"

EQUIPMENT_MODEL_ENV_KEYS = (
    MODEL_ENV,
    BASE_URL_ENV,
    API_KEY_ENV,
    PROVIDER_ENV,
    PROFILE_ENV,
    "EQUIPMENT_DR_PLATFORM_MODEL",
    "EQUIPMENT_DR_PLATFORM_BASE_URL",
    "EQUIPMENT_DR_PLATFORM_API_KEY_ENV",
)


def is_fake_execution(payload: dict[str, Any] | None) -> bool:
    execution = dict((payload or {}).get("execution") or {})
    return str(execution.get("mode") or "").strip() == "fake"


def runtime_from_model_info(info: ModelInfo) -> dict[str, Any]:
    """把平台聊天模型投影为装备研究 runner 可消费的执行合同。"""
    from equipment_deep_research.providers.platform_access import configure_model_observer
    from platform_core.services.equipment_model_usage import create_equipment_call_observer

    configure_model_observer(create_equipment_call_observer)
    base_url = str(get_docker_safe_url(info.base_url) or info.base_url or "").strip()
    execution = {
        "mode": "real",
        "provider": PLATFORM_PROVIDER_NAME,
        "model": info.model_id,
        "base_url": base_url,
        "api_key_env": API_KEY_ENV,
        "model_spec": info.spec,
        "model_profile_id": PLATFORM_PROFILE_ID,
    }
    return {
        "model_spec": info.spec,
        "model_id": info.model_id,
        "provider_id": info.provider_id,
        "provider_type": info.provider_type,
        "mode": "real",
        "provider": PLATFORM_PROVIDER_NAME,
        "model": info.model_id,
        "base_url": base_url,
        "api_key_env": API_KEY_ENV,
        "execution": execution,
        "env": {
            MODEL_ENV: info.model_id,
            BASE_URL_ENV: base_url,
            API_KEY_ENV: info.api_key,
            PROVIDER_ENV: PLATFORM_PROVIDER_NAME,
            PROFILE_ENV: PLATFORM_PROFILE_ID,
            "EQUIPMENT_DR_PLATFORM_MODEL": info.model_id,
            "EQUIPMENT_DR_PLATFORM_BASE_URL": base_url,
            "EQUIPMENT_DR_PLATFORM_API_KEY_ENV": API_KEY_ENV,
        },
    }


def runner_call_from_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    """DeepResearchRunner.run() 的 provider 参数；mode 只能是 fake 或 real。"""
    return {
        "mode": "real",
        "provider_name": runtime["provider"],
        "provider_model": runtime["model"],
        "provider_base_url": runtime["base_url"],
        "provider_api_key_env": runtime["api_key_env"],
        "provider_api_key": str((runtime.get("env") or {}).get(API_KEY_ENV) or "") or None,
    }


def resolve_equipment_model(model_spec: str | None, *, default_spec: str = "") -> dict[str, Any]:
    """解析装备研究使用的平台模型；找不到时给出明确错误。"""
    spec = str(model_spec or default_spec or "").strip()
    if not spec:
        raise RuntimeError("未配置装备研究模型，请在模型设置中启用聊天模型并指定系统默认模型")
    info = model_cache.get_model_info(spec)
    if info is None:
        raise RuntimeError(f"未找到可用聊天模型: {spec}。请在模型设置中配置供应商与模型")
    if info.model_type != "chat":
        raise RuntimeError(f"{spec} 不是聊天模型")
    if not info.api_key:
        raise RuntimeError(f"{spec} 缺少 API Key，请在模型设置中补齐凭证")
    if not str(info.base_url or "").strip():
        raise RuntimeError(f"{spec} 缺少接口地址，请在模型设置中补齐供应商 Base URL")
    return runtime_from_model_info(info)


def resolve_managed_equipment_model(model_spec: str) -> dict[str, Any]:
    """历史任务缺少模型标识时读取平台默认值，禁止退回旧模型环境变量。"""
    if model_spec.strip():
        return resolve_equipment_model(model_spec)
    from sqlalchemy import create_engine, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    from platform_core.storage.postgres.models_business import ConfigOption

    url = make_url(os.environ["POSTGRES_URL"]).set(drivername="postgresql+psycopg")
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            stored = connection.execute(
                select(ConfigOption.value).where(ConfigOption.key == "system_options")
            ).scalar_one_or_none()
        spec = str(system_options.resolve(dict(stored or {})).get("default_model") or "")
        return resolve_equipment_model(spec)
    finally:
        engine.dispose()


def equipment_model_profiles() -> dict[str, Any]:
    """向原工作台投影平台模型目录，深研每轮可选择同一套模型。"""
    return {
        "managed": True,
        "version": 1,
        "active_profile": "",
        "default_profile": "",
        "swarm_overrides": {},
        "profiles": [
            {
                "id": info.spec,
                "label": info.display_name or info.model_id,
                "model": info.model_id,
                "provider": info.provider_id,
                "credential_configured": bool(info.api_key),
                "deprecated": False,
            }
            for info in model_cache.get_all_specs("chat")
        ],
    }


def bind_equipment_execution(payload: dict[str, Any] | None) -> dict[str, Any]:
    """把 run.payload 绑到一次领域执行：fake 跳过模型，其余一律走平台模型设置。"""
    payload = dict(payload or {})
    if is_fake_execution(payload):
        return {
            "mode": "fake",
            "overlay": {},
            "runner": {
                "mode": "fake",
                "provider_name": None,
                "provider_model": None,
                "provider_base_url": None,
                "provider_api_key_env": None,
                "provider_api_key": None,
            },
            "execution": {"mode": "fake"},
            "model_spec": str(payload.get("model_spec") or ""),
        }
    runtime = resolve_managed_equipment_model(
        str(payload.get("model_spec") or "") or str((payload.get("execution") or {}).get("model_spec") or "")
    )
    return {
        "mode": "real",
        "overlay": dict(runtime["env"]),
        "runner": runner_call_from_runtime(runtime),
        "execution": dict(runtime["execution"]),
        "model_spec": runtime["model_spec"],
    }


async def default_chat_model_spec(db) -> str:
    options = await system_options.get(db)
    return str(options.get("default_model") or "").strip()


def providers_yaml_path():
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[4]
    if not (project_root / "configs" / "equipment_deep_research").exists():
        project_root = Path("/app")
    return project_root / "configs/equipment_deep_research/providers.yaml"


def create_equipment_provider(runtime: dict[str, Any], *, isolation_key: str = "platform-model"):
    """用平台模型设置实例化装备研究 Chat Completions 通道，不把密钥写入 payload。"""
    from equipment_deep_research.providers.registry import ProviderRegistry

    registry = ProviderRegistry.load(providers_yaml_path())
    api_key = str((runtime.get("env") or {}).get(API_KEY_ENV) or "")
    return registry.create(
        str(runtime["provider"]),
        model=str(runtime["model"]),
        base_url=str(runtime["base_url"]),
        api_key=api_key,
        isolation_key=isolation_key,
    )


async def complete_equipment_chat(
    runtime: dict[str, Any],
    messages,
    options: dict[str, Any] | None = None,
    *,
    isolation_key: str = "platform-model",
) -> tuple[str, dict[str, Any]]:
    """一次同步聊天补全，供 Query 生成与深研对话复用。"""
    from equipment_deep_research.query_library.generator import _collect_stream

    provider = create_equipment_provider(runtime, isolation_key=isolation_key)
    return await _collect_stream(provider, messages, dict(options or {}))


def apply_equipment_model_env(overlay: dict[str, str]):
    """在当前进程内临时覆盖装备研究凭证，避免并发任务互相覆盖。"""

    class _Guard:
        def __enter__(self):
            _ENV_LOCK.acquire()
            self._previous = {key: os.environ.get(key) for key in overlay}
            for key, value in overlay.items():
                if value:
                    os.environ[key] = value
            return self

        def __exit__(self, exc_type, exc, tb):
            for key, previous in self._previous.items():
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous
            _ENV_LOCK.release()
            return False

    return _Guard()
