"""辅助聊天与原生中间件不会重复计量，未知用量不填零。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from platform_core.models.usage_observer import ChatUsageObserver, ModelCallObservation, native_usage_managed


@pytest.mark.asyncio
async def test_auxiliary_callback_reports_once_and_skips_native(model_usage_records):
    observer = ChatUsageObserver("configured:model")
    call = uuid4()
    await observer.on_chat_model_start({}, [], run_id=call)
    response = SimpleNamespace(generations=[], llm_output={"token_usage": {"prompt_tokens": 4, "completion_tokens": 2}})
    await observer.on_llm_end(response, run_id=call)
    await observer.on_llm_end(response, run_id=call)
    token = native_usage_managed.set(True)
    try:
        native = uuid4()
        await observer.on_chat_model_start({}, [], run_id=native)
        await observer.on_llm_end(response, run_id=native)
    finally:
        native_usage_managed.reset(token)
    assert len(model_usage_records) == 1
    assert model_usage_records[0]["total_tokens"] == 6
    assert model_usage_records[0]["surface"] == "辅助模型调用"


@pytest.mark.asyncio
async def test_embedding_failure_and_missing_usage_remain_observable(model_usage_records):
    with pytest.raises(ValueError):
        async with ModelCallObservation("configured:embed", "知识库嵌入"):
            raise ValueError("unavailable")
    with ModelCallObservation("configured:rerank", "知识库重排"):
        pass
    assert [r["status"] for r in model_usage_records] == ["failed", "completed"]
    assert all(r["total_tokens"] is None for r in model_usage_records)


def test_malformed_usage_does_not_override_model_result(model_usage_records):
    """供应商异常 usage 只标记缺失，不能把正常响应变成业务错误。"""
    with ModelCallObservation("configured:embed", "知识库嵌入") as observed:
        observed.usage = "unsupported"
    assert model_usage_records[0]["status"] == "completed"
    assert model_usage_records[0]["total_tokens"] is None
