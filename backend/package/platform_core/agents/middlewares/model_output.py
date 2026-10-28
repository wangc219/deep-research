"""防止供应商只返回推理或空消息时将任务误判为完成。"""

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage


class ModelOutputMiddleware(AgentMiddleware[Any, Any, Any]):
    """保留每次模型调用的审计，最多两次请求补全最终正文。"""

    def __init__(self):
        self.empty_responses = 0

    def wrap_model_call(self, request, handler):
        """对缺少最终答案的响应应用有界恢复请求。"""
        return handler(self._prepare_request(request))

    async def awrap_model_call(self, request, handler):
        """异步调用使用同一正文补全规则。"""
        return await handler(self._prepare_request(request))

    def _prepare_request(self, request):
        """读图后或再次空答复时单独请求正文，避免供应商持续只输出推理。"""
        messages = request.messages
        recovering = bool(messages and messages[-1].additional_kwargs.get("model_output_recovery"))
        has_image = any(block.get("type") == "image" for message in messages for block in message.content_blocks)
        if recovering and (has_image or self.empty_responses >= 2):
            return request.override(tools=[], tool_choice=None)
        return request

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        """正文与工具调用都缺失时继续正常模型轮次，不把推理冒充答案。"""
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            return None
        if (
            message.tool_calls
            or message.text.strip()
            or any(block.get("type") in {"image", "audio", "video", "file"} for block in message.content_blocks)
        ):
            self.empty_responses = 0
            return None
        self.empty_responses += 1
        if self.empty_responses > 2:
            raise RuntimeError("模型连续未返回最终正文或工具调用，任务未完成，请重试或更换模型。")
        return {
            "messages": [
                HumanMessage(
                    content=(
                        "上一次响应没有可展示的最终答案。请基于已读取的资料完成当前用户请求，"
                        "把最终答复写入正文 content，不要只返回推理。已有工具读取结果时请直接作答；"
                        "无法完成时如实说明缺失项。"
                    ),
                    additional_kwargs={"model_output_recovery": True},
                )
            ],
            "jump_to": "model",
        }

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        """异步图复用同一有界恢复规则。"""
        return self.after_model(state, runtime)
