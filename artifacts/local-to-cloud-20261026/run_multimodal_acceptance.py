"""用同一已授权供应商临时启用视觉测试与推理参数，完成后恢复模型配置。"""

import asyncio
import copy
import os
import subprocess
import sys
import time

from platform_core.models.providers.cache import model_cache
from platform_core.models.providers.service import get_all_model_providers, get_model_provider_by_id
from platform_core.storage.postgres.manager import pg_manager

original = configured = None


async def configure(restore=False):
    """只改变模型选择与推理选项，保留原有供应商凭据。"""
    global original, configured
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            provider = await get_model_provider_by_id(db, 'siliconflow-cn')
            if restore:
                if provider.enabled_models != configured:
                    raise RuntimeError('测试期间模型列表被其他操作者修改，请人工合并恢复')
                provider.enabled_models = original
            else:
                original = copy.deepcopy(provider.enabled_models)
                configured = copy.deepcopy(original)
                for model in configured:
                    if model['id'] == 'deepseek-ai/DeepSeek-V4-Flash':
                        model['request_body_overrides'] = {
                            **model.get('request_body_overrides', {}), 'enable_thinking': True}
                vision = 'Qwen/Qwen3-VL-32B-Instruct'
                if not any(model['id'] == vision for model in configured):
                    configured.append({'id': vision, 'type': 'chat', 'source': 'manual',
                                       'display_name': '真实视觉验收（临时）',
                                       'request_body_overrides': {'enable_thinking': False}})
                thinking = 'Qwen/Qwen3-VL-8B-Thinking'
                if not any(model['id'] == thinking for model in configured):
                    configured.append({'id': thinking, 'type': 'chat', 'source': 'manual',
                                       'display_name': '真实推理验收（临时）'})
                provider.enabled_models = configured
            await db.commit()
            model_cache.rebuild(await get_all_model_providers(db))
    finally:
        await pg_manager.close()


asyncio.run(configure())
try:
    # 模型运行时本地缓存有效期为 5 秒，等待各进程自动刷新后再启动真实调用。
    time.sleep(6)
    env = dict(os.environ,
               E2E_VISION_MODEL='siliconflow-cn:Qwen/Qwen3-VL-32B-Instruct',
               E2E_NON_VISION_MODEL='siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash',
               DEEP_RESEARCH_REASONING_E2E_MODEL='siliconflow-cn:Qwen/Qwen3-VL-8B-Thinking')
    result = subprocess.run([sys.executable, '/tmp/run_live_tests.py',
                             'test/e2e/test_provider_reasoning_e2e.py',
                             'test/e2e/test_read_file_multimodal_e2e.py',
                             '-s', '-q', '--tb=short', '-o', 'cache_dir=/tmp/acceptance-multimodal-final',
                             '--junitxml=/app/outputs/migration-20261026-multimodal.xml'], env=env)
finally:
    asyncio.run(configure(restore=True))
raise SystemExit(result.returncode)
