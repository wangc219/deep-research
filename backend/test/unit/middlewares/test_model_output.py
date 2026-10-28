"""通过真实 Agent 图验证空正文恢复及有界失败。"""

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from platform_core.agents.middlewares.model_output import ModelOutputMiddleware


class ResponseSequenceModel(BaseChatModel):
    """按顺序提供供应商响应，保留实际 Agent 节点与路由。"""

    responses: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self):
        return "response-sequence"

    def bind_tools(self, tools, **kwargs):
        """测试模型不执行工具绑定。"""
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """每次调用返回独立消息，允许验证重试上限。"""
        response = self.responses[min(self.calls, len(self.responses) - 1)].model_copy(deep=True)
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_reasoning_only_response_recovers_via_a_new_model_turn(asynchronous):
    """推理保留原义，最终正文来自下一次真正模型调用。"""
    model = ResponseSequenceModel(
        responses=[AIMessage(content=[{"type": "reasoning", "reasoning": "blue"}]), AIMessage("blue")]
    )
    graph = create_agent(model, middleware=[ModelOutputMiddleware()])
    inputs = {"messages": [HumanMessage("Name the color")]}
    result = await graph.ainvoke(inputs) if asynchronous else graph.invoke(inputs)
    assert model.calls == 2
    assert result["messages"][-1].text == "blue"
    assert result["messages"][1].content[0]["type"] == "reasoning"
    assert result["messages"][2].additional_kwargs["model_output_recovery"] is True


@pytest.mark.asyncio
async def test_repeated_empty_provider_response_fails_with_bounded_calls():
    """三次空答复后必须失败，不能无限重试或生成伪造正文。"""
    model = ResponseSequenceModel(responses=[AIMessage(content=[])])
    graph = create_agent(model, middleware=[ModelOutputMiddleware()])
    with pytest.raises(RuntimeError, match="模型连续未返回最终正文"):
        await graph.ainvoke({"messages": [HumanMessage("Answer")]})
    assert model.calls == 3


def test_legitimate_tool_call_does_not_trigger_empty_output_recovery():
    """工具调用轮次允许没有正文。"""
    message = AIMessage("", tool_calls=[{"id": "call_read", "name": "read_file", "args": {}}])
    middleware = ModelOutputMiddleware()
    assert middleware.after_model({"messages": [message]}, None) is None


@pytest.mark.parametrize("has_image", [False, True])
@pytest.mark.parametrize("empty_responses", [1, 2])
def test_bounded_final_answer_recovery_removes_tool_schema(has_image, empty_responses):
    """普通任务首次恢复仍可调用工具，读图后或第二次恢复单独请求正文。"""
    messages = [HumanMessage(content_blocks=[{"type": "image", "base64": "abc", "mime_type": "image/png"}])]
    if not has_image:
        messages = [HumanMessage("Use evidence")]
    messages.append(HumanMessage("Complete answer", additional_kwargs={"model_output_recovery": True}))
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    request = ModelRequest(model=ResponseSequenceModel(responses=[]), messages=messages, tools=tools)
    seen = []
    middleware = ModelOutputMiddleware()
    middleware.empty_responses = empty_responses
    middleware.wrap_model_call(request, lambda prepared: seen.append(prepared))
    assert seen[0].tools == ([] if has_image or empty_responses == 2 else tools)
