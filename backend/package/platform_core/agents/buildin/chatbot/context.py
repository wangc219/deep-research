from dataclasses import dataclass, field

from platform_core.agents.context import BaseContext


@dataclass(kw_only=True)
class ChatBotContext(BaseContext):
    subagents_enabled: bool = field(
        default=True,
        metadata={
            "name": "启用子智能体",
            "description": "关闭后本次运行不装配任何 Subagent 生命周期工具。",
            "type": "boolean",
        },
    )

    subagents: list[str] | None = field(
        default=None,
        metadata={
            "name": "子智能体",
            "options": [],
            "description": "可选子智能体列表，为空表示启用当前用户可见的全部子智能体。",
            "type": "list",
            "kind": "subagents",
        },
    )
