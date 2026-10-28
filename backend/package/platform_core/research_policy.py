"""模型选择的研究深度执行策略。"""

from __future__ import annotations

from typing import Literal


RESEARCH_BUDGET_STANDARD = "standard"
RESEARCH_BUDGET_ADAPTIVE_LONG_RUNNING = "adaptive_long_running"
ResearchBudgetMode = Literal["standard", "adaptive_long_running"]


def normalize_research_budget_mode(value: object) -> ResearchBudgetMode:
    """在模型输出和持久化执行边界校验研究模式。"""
    normalized = str(value or RESEARCH_BUDGET_STANDARD).strip().casefold()
    if normalized not in {RESEARCH_BUDGET_STANDARD, RESEARCH_BUDGET_ADAPTIVE_LONG_RUNNING}:
        raise ValueError(f"不支持的研究预算模式：{value}")
    return normalized  # type: ignore[return-value]
