"""聊天辅助调用、嵌入与重排共用的计量边界。"""

import asyncio
import logging
from collections.abc import Mapping
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from langchain_core.callbacks import AsyncCallbackHandler

native_usage_managed = ContextVar("native_usage_managed", default=False)


class ModelCallObservation:
    """保存一次请求的实际 usage，缺失数据保持未知。"""

    def __init__(self, model_spec, surface, *, call_id=None):
        self.model_spec = model_spec
        self.surface = surface
        self.call_id = call_id or str(uuid4())
        self.started = perf_counter()
        self.usage = {}

    def __enter__(self):
        return self

    async def __aenter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.finish(exc)

    async def __aexit__(self, exc_type, exc, tb):
        await asyncio.to_thread(self.finish, exc)

    def finish(self, error=None):
        """统计失败只记录日志，不替换模型返回或掩盖原错误。"""
        from platform_core.repositories.model_call_repository import record_model_call

        usage = self.usage if isinstance(self.usage, Mapping) else {}

        def count(*keys):
            for key in keys:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    return value
            return None

        inputs = count("input_tokens", "prompt_tokens")
        outputs = count("output_tokens", "completion_tokens")
        total = count("total_tokens")
        if total is None and inputs is not None and outputs is not None:
            total = inputs + outputs
        try:
            record_model_call(
                {
                    "id": self.call_id,
                    "model_spec": str(self.model_spec or "unknown")[:512],
                    "surface": self.surface,
                    "run_id": "",
                    "phase": "",
                    "status": "cancelled"
                    if isinstance(error, asyncio.CancelledError)
                    else "failed"
                    if error
                    else "completed",
                    "duration_ms": round((perf_counter() - self.started) * 1000, 2),
                    "input_tokens": inputs,
                    "output_tokens": outputs,
                    "total_tokens": total,
                    "error_type": type(error).__name__ if error else "",
                }
            )
        except Exception:
            logging.getLogger(__name__).exception("模型调用统计写入失败，call_id=%s", self.call_id)


class ChatUsageObserver(AsyncCallbackHandler):
    """覆盖直接使用平台聊天模型的辅助调用，原生 Agent 由其中间件计量。"""

    run_inline = True

    def __init__(self, model_spec):
        self.model_spec = model_spec
        self.pending = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        if not native_usage_managed.get():
            self.pending[run_id] = ModelCallObservation(self.model_spec, "辅助模型调用", call_id=str(run_id))

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        await self.on_chat_model_start(serialized, prompts, run_id=run_id, **kwargs)

    async def on_llm_end(self, response, *, run_id, **kwargs):
        observed = self.pending.pop(run_id, None)
        if observed is None:
            return
        for batch in response.generations:
            for generation in batch:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if usage:
                    observed.usage = dict(usage)
        if not observed.usage:
            output = response.llm_output or {}
            usage = output.get("token_usage") or output.get("usage") or {}
            observed.usage = dict(usage) if isinstance(usage, Mapping) else {}
        await asyncio.to_thread(observed.finish)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        observed = self.pending.pop(run_id, None)
        if observed is not None:
            await asyncio.to_thread(observed.finish, error)
