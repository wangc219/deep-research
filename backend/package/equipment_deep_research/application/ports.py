"""Ports consumed by the run application service.

The application layer owns workflow decisions; persistence and queue adapters
only implement these small protocols.  This keeps tests, alternative storage
backends and worker processes interchangeable without importing concrete SQL
classes into the service.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from equipment_deep_research.application.dto import RunView
from equipment_deep_research.contracts.tools import ToolDefinition


class RunRepository(Protocol):
    """Durable run and event operations required by the application service."""

    def get(self, run_id: str) -> RunView: ...

    def list(self) -> list[RunView]: ...

    def save(self, view: RunView) -> None: ...

    def append_event(self, run_id: str, event_type: str, payload: dict) -> None: ...


class RunQueue(Protocol):
    """Minimal queue contract shared by in-process and SQL workers."""

    def enqueue(self, run_id: str, *, allow_claimed: bool = False) -> None: ...

    def pending_run_ids(self) -> Sequence[str]: ...

    def remove(self, run_id: str) -> None: ...


class ResearchKnowledgeToolFactory(Protocol):
    """宿主按任务 owner 绑定知识工具，但不在任务启动时执行检索。"""

    def __call__(
        self,
        run: RunView,
        event_sink: Callable[[str, dict], None] | None = None,
    ) -> Sequence[ToolDefinition]: ...


__all__ = ["ResearchKnowledgeToolFactory", "RunRepository", "RunQueue"]
