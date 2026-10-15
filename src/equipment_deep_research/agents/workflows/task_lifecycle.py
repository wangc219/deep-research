"""Own workflow tasks and isolate failures without swallowing cancellation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar

from equipment_deep_research.contracts.runtime import ModelBudgetExhausted

T = TypeVar("T")


class WorkflowTaskScope(AbstractAsyncContextManager):
    """Drain every owned task on completion, cancellation or scheduler failure."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Future[Any]] = []

    async def __aenter__(self) -> WorkflowTaskScope:
        return self

    def create_task(self, coroutine: Awaitable[T]) -> asyncio.Future[T]:
        task = asyncio.ensure_future(coroutine)
        self.tasks.append(task)
        return task

    async def __aexit__(self, *exc: object) -> None:
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


async def gather_isolated(*awaitables: Awaitable[T]) -> list[T | Exception]:
    """Collect ordinary failures; propagate cancellation and drain siblings."""

    async with WorkflowTaskScope() as scope:
        tasks = [scope.create_task(item) for item in awaitables]
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    raise asyncio.CancelledError()
                error = task.exception()
                if error is not None and not isinstance(error, Exception):
                    raise error
        results: list[T | Exception] = []
        for task in tasks:
            try:
                results.append(task.result())
            except Exception as error:
                results.append(error)
        return results


def is_budget_exhausted(error: BaseException) -> bool:
    """Recognize runtime budget failures even through a card/spine wrapper."""

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, ModelBudgetExhausted):
            return True
        seen.add(id(current))
        current = current.__cause__
    return False
