"""Stable runtime ports used by workflow services.

These protocols describe the smallest host surface required by swarm
execution. They are intentionally free of provider and orchestration imports
so multiple workflow implementations can share the same contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class ModelRuntime(Protocol):
    async def _run_core_json(
        self,
        agent_id: str,
        system: str,
        payload: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        max_output_tokens: int,
        *,
        phase: str = "structured_analysis",
        **options: Any,
    ) -> str: ...


class SwarmRuntime(ModelRuntime, Protocol):
    supports_agent_runtime: bool

    def _provider_for(
        self, agent_id: str, *, isolation_id: str, payload: Mapping[str, Any]
    ) -> Any: ...


class CardRuntime(ModelRuntime, Protocol):
    _s6_card_result_cache: dict[tuple[str, str], tuple[dict[str, Any], str]]


class BudgetRuntime(Protocol):
    def _optional_work_allowed(
        self, *, priority: str, minimum_remaining_seconds: float
    ) -> bool: ...


__all__ = ["BudgetRuntime", "CardRuntime", "ModelRuntime", "SwarmRuntime"]
