from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from equipment_deep_research.application.run_service import ResearchApplicationService


@dataclass(frozen=True)
class WorkerOutcome:
    run_id: str
    status: str
    error: str = ""


class ResearchWorker:
    def __init__(self, *, service: ResearchApplicationService, execute: Callable[[str], None]) -> None:
        self.service, self.execute = service, execute

    def run_once(self) -> WorkerOutcome | None:
        run_id = self.service.queue.claim()
        if run_id is None:
            return None
        self.service.set_status(run_id, "planning")
        try:
            self.service.set_status(run_id, "researching")
            self.execute(run_id)
            self.service.set_status(run_id, "completed")
            return WorkerOutcome(run_id, "completed")
        except Exception as exc:
            self.service.set_status(run_id, "failed")
            return WorkerOutcome(run_id, "failed", str(exc))
