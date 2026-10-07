"""Backward-compatible facade for agent execution providers.

The executable implementation lives under :mod:`agents.workflows`; this
module intentionally remains small so callers keep their historical import
path while agent designs and workflows can evolve independently.
"""

from __future__ import annotations

import sys
from types import ModuleType

from equipment_deep_research.agents.execution_contracts import (
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSelectionRequest,
    AgentSelectionResult,
)
from equipment_deep_research.agents.workflows import coordinator as _implementation
from equipment_deep_research.agents.workflows import reporting_support as _reporting_support
from equipment_deep_research.agents.workflows import s6_quality as _s6_quality

FakeAgentProvider = _implementation.FakeAgentProvider
RealAgentProvider = _implementation.RealAgentProvider
ResponsesAgentProvider = _implementation.ResponsesAgentProvider
S6QualityError = _implementation.S6QualityError


class _CompatibilityModule(ModuleType):
    """Mirror patched legacy-private names into the implementation module.

    A number of existing tests replace private helpers through the historical
    ``agents.provider`` path.  Mirroring assignments keeps that transition
    behavior while new code imports helpers from their owning workflow.
    """

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name != "_implementation" and hasattr(_implementation, name):
            setattr(_implementation, name, value)
        for module_name in (
            "equipment_deep_research.agents.workflows.winning",
            "equipment_deep_research.agents.workflows.s6_quality",
            "equipment_deep_research.agents.workflows.reporting_support",
            "equipment_deep_research.agents.workflows.reporter",
            "equipment_deep_research.agents.workflows.runtime",
            "equipment_deep_research.agents.workflows.baseline_execution",
            "equipment_deep_research.agents.workflows.orchestrator",
        ):
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, name):
                setattr(module, name, value)


for _source_module in (_implementation, _s6_quality, _reporting_support):
    for _name in dir(_source_module):
        if _name.startswith("__"):
            continue
        globals().setdefault(_name, getattr(_source_module, _name))

sys.modules[__name__].__class__ = _CompatibilityModule

__all__ = [
    "AgentProvider",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentSelectionRequest",
    "AgentSelectionResult",
    "FakeAgentProvider",
    "RealAgentProvider",
    "ResponsesAgentProvider",
    "S6QualityError",
]
