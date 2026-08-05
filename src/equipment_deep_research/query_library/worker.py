from __future__ import annotations

import asyncio
from uuid import uuid4

from equipment_deep_research.query_library.service import QueryLibraryService


class QueryGenerationWorker:
    def __init__(
        self,
        service: QueryLibraryService,
        *,
        worker_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        max_idle_poll_interval_seconds: float = 10.0,
    ) -> None:
        self.service = service
        self.worker_id = worker_id or f"query-worker-{uuid4()}"
        self.poll_interval_seconds = max(0.1, poll_interval_seconds)
        self.max_idle_poll_interval_seconds = max(
            self.poll_interval_seconds,
            max_idle_poll_interval_seconds,
        )

    async def run_once(self) -> dict | None:
        job = await self.service.process_next(worker_id=self.worker_id)
        return None if job is None else job.to_dict()

    async def run_forever(self) -> None:
        idle_delay = self.poll_interval_seconds
        while True:
            result = await self.run_once()
            if result is None:
                await asyncio.sleep(idle_delay)
                idle_delay = min(
                    self.max_idle_poll_interval_seconds,
                    idle_delay * 1.5,
                )
            else:
                idle_delay = self.poll_interval_seconds
