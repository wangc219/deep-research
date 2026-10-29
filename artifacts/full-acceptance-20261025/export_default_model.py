"""向管道输出当前已授权模型配置；禁止将输出保存为验收产物或打印到终端。"""
import asyncio
import json

from platform_core.config.options import system_options
from platform_core.models.providers.service import get_model_provider_by_id, resolve_api_key
from platform_core.storage.postgres.manager import pg_manager


async def main():
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            spec = (await system_options.get(db))["default_model"]
            provider_id, model_id = spec.split(":", 1)
            provider = await get_model_provider_by_id(db, provider_id)
            assert provider and provider.provider_type == "openai"
            key = resolve_api_key(provider)
            assert key
            model = next(m for m in provider.enabled_models if m["id"] == model_id)
            print(json.dumps({"base_url": model.get("base_url_override") or provider.base_url,
                              "api_key": key, "model": model_id}))
    finally:
        await pg_manager.close()


asyncio.run(main())
