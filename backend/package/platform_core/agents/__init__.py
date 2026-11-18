"""Agent 公共入口。

这里刻意使用惰性导出。Python 在导入 ``platform_core.agents.skills`` 等子包前会先
执行本模块；若在此处预加载工具、模型和 MCP 全栈，数据库迁移这类只需要 Skill
Repository 的进程也会被迫依赖 Web Search 等运行时模块，破坏独立部署边界。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from platform_core.agents.base import BaseAgent
    from platform_core.agents.context import BaseContext
    from platform_core.agents.mcp.service import get_enabled_mcp_tools
    from platform_core.agents.state import BaseState
    from platform_core.agents.toolkits.utils import get_tool_info
    from platform_core.models.chat import load_chat_model, resolve_chat_model_spec


_LAZY_EXPORTS = {
    "BaseAgent": ("platform_core.agents.base", "BaseAgent"),
    "BaseContext": ("platform_core.agents.context", "BaseContext"),
    "BaseState": ("platform_core.agents.state", "BaseState"),
    "load_chat_model": ("platform_core.models.chat", "load_chat_model"),
    "resolve_chat_model_spec": ("platform_core.models.chat", "resolve_chat_model_spec"),
    "get_tool_info": ("platform_core.agents.toolkits.utils", "get_tool_info"),
    "get_enabled_mcp_tools": ("platform_core.agents.mcp.service", "get_enabled_mcp_tools"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    # Base classes
    "BaseAgent",
    "BaseContext",
    "BaseState",
    # Model utilities
    "load_chat_model",
    "resolve_chat_model_spec",
    # Core tools
    "get_tool_info",
    # Core MCP
    "get_enabled_mcp_tools",
]
