from dataclasses import dataclass, field

from platform_core.agents.context import BaseContext
from platform_core.research_policy import RESEARCH_BUDGET_STANDARD, ResearchBudgetMode


@dataclass(kw_only=True)
class SubAgentContext(BaseContext):
    agent_slug: str = field(default="", metadata={"configurable": False, "hide": True})
    research_budget_mode: ResearchBudgetMode = field(
        default=RESEARCH_BUDGET_STANDARD,
        metadata={"configurable": False, "hide": True},
    )

    parent_thread_id: str | None = field(
        default=None,
        metadata={"name": "父线程ID", "configurable": False, "hide": True},
    )
    is_subagent_runtime: bool = field(
        default=False,
        metadata={"name": "子智能体运行态", "configurable": False, "hide": True},
    )
