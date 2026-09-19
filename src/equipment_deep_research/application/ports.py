"""Ports consumed by the run application service.

The application layer owns workflow decisions; persistence and queue adapters
only implement these small protocols.  This keeps tests, alternative storage
backends and worker processes interchangeable without importing concrete SQL
classes into the service.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from equipment_deep_research.application.dto import RunView


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


__all__ = ["RunRepository", "RunQueue"]
