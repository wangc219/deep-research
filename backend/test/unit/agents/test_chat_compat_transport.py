"""使用真实 OpenAI SDK 验证供应商扩展参数能实际发送。"""

import json

import httpx
import pytest

from platform_core.models.chat import ChatCompletionsAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("explicit", [None, False, True])
async def test_qwen_thinking_parameter_reaches_wire_through_sdk(stream, explicit):
    """流式和非流式都能发送思考参数，调用方显式设置优先。"""
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["enable_thinking"] is (stream if explicit is None else explicit)
        assert "extra_body" not in body
        base = {"id": "compat", "created": 1, "model": "qwen-test"}
        if body.get("stream"):
            event = {
                **base,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            }
            return httpx.Response(
                200,
                text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={
                **base,
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ChatCompletionsAdapter(
            model="qwen-test",
            api_key="test",
            base_url="https://example.test/v1",
            http_async_client=client,
            max_retries=0,
            provider_compat={
                "thinking_format": "enable_thinking",
                "thinking_always_send": True,
                "thinking_disable_on_non_stream": True,
            },
            extra_body={} if explicit is None else {"enable_thinking": explicit},
        )
        if stream:
            assert "".join([chunk.text async for chunk in model.astream("hello")]) == "ok"
        else:
            assert (await model.ainvoke("hello")).text == "ok"
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_siliconflow_output_budget_and_thinking_reach_wire():
    """输出预算不得被 LangChain 改成供应商不使用的字段。"""
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["max_tokens"] == 4096
        assert "max_completion_tokens" not in body
        assert body["enable_thinking"] is False
        return httpx.Response(
            200,
            json={
                "id": "sf-budget",
                "created": 1,
                "model": "deepseek-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ChatCompletionsAdapter(
            model="deepseek-test",
            api_key="test",
            base_url="https://example.test/v1",
            http_async_client=client,
            max_retries=0,
            max_tokens=4096,
            extra_body={"enable_thinking": False},
            provider_compat={"max_tokens_field": "max_tokens"},
        )
        assert (await model.ainvoke("extract")).text == "{}"
    assert len(requests) == 1
