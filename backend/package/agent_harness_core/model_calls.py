"""与业务无关的长模型调用监督器。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Literal, TypeVar


T = TypeVar("T")
ModelCallEventKind = Literal["started", "waiting", "attempt_timeout", "retrying", "completed"]
ModelCallFactory = Callable[[int], Awaitable[T]]
ModelCallObserver = Callable[["ModelCallEvent"], Awaitable[None]]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelCallPolicy:
    """单次逻辑模型调用的供应商无关存活策略。"""

    total_timeout_seconds: float
    attempt_timeout_seconds: float
    max_attempts: int = 2
    feedback_interval_seconds: float = 30

    def __post_init__(self) -> None:
        if self.total_timeout_seconds <= 0:
            raise ValueError("total_timeout_seconds must be positive")
        if self.attempt_timeout_seconds <= 0:
            raise ValueError("attempt_timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.feedback_interval_seconds <= 0:
            raise ValueError("feedback_interval_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ModelCallEvent:
    """可投影到对话、指标或持久事件流的类型化事件。"""

    kind: ModelCallEventKind
    attempt: int
    max_attempts: int
    elapsed_seconds: float
    attempt_elapsed_seconds: float


class ModelCallTimeoutError(TimeoutError):
    def __init__(self, *, total_timeout_seconds: float, attempts: int) -> None:
        self.total_timeout_seconds = total_timeout_seconds
        self.attempts = attempts
        super().__init__(
            f"model call did not complete within {total_timeout_seconds:g} seconds across {attempts} attempt(s)"
        )


class ModelCallSupervisor[T]:
    """以协作取消、类型化反馈和总时限执行逻辑模型请求。"""

    def __init__(self, policy: ModelCallPolicy) -> None:
        self.policy = policy

    async def run(
        self,
        factory: ModelCallFactory[T],
        *,
        observer: ModelCallObserver | None = None,
    ) -> T:
        loop = asyncio.get_running_loop()
        started = loop.time()
        attempts_started = 0

        for attempt in range(1, self.policy.max_attempts + 1):
            total_remaining = self.policy.total_timeout_seconds - (loop.time() - started)
            if total_remaining <= 0:
                break
            attempts_started = attempt
            attempt_timeout = min(self.policy.attempt_timeout_seconds, total_remaining)
            attempt_started = loop.time()
            await self._emit(observer, "started", attempt, started, attempt_started)
            call = asyncio.create_task(factory(attempt))
            try:
                while True:
                    attempt_elapsed = loop.time() - attempt_started
                    wait_seconds = min(
                        self.policy.feedback_interval_seconds,
                        max(0.0, attempt_timeout - attempt_elapsed),
                    )
                    if wait_seconds <= 0:
                        raise TimeoutError
                    done, _pending = await asyncio.wait({call}, timeout=wait_seconds)
                    if done:
                        result = await call
                        await self._emit(observer, "completed", attempt, started, attempt_started)
                        return result
                    await self._emit(observer, "waiting", attempt, started, attempt_started)
            except TimeoutError:
                call.cancel()
                await asyncio.gather(call, return_exceptions=True)
                await self._emit(observer, "attempt_timeout", attempt, started, attempt_started)
                if attempt < self.policy.max_attempts:
                    await self._emit(observer, "retrying", attempt, started, attempt_started)
            except asyncio.CancelledError:
                call.cancel()
                await asyncio.gather(call, return_exceptions=True)
                raise
            except BaseException:
                call.cancel()
                await asyncio.gather(call, return_exceptions=True)
                raise

        raise ModelCallTimeoutError(
            total_timeout_seconds=self.policy.total_timeout_seconds,
            attempts=attempts_started,
        )

    async def _emit(
        self,
        observer: ModelCallObserver | None,
        kind: ModelCallEventKind,
        attempt: int,
        started: float,
        attempt_started: float,
    ) -> None:
        if observer is None:
            return
        loop = asyncio.get_running_loop()
        event = ModelCallEvent(
            kind=kind,
            attempt=attempt,
            max_attempts=self.policy.max_attempts,
            elapsed_seconds=max(0.0, loop.time() - started),
            attempt_elapsed_seconds=max(0.0, loop.time() - attempt_started),
        )
        try:
            await observer(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Model-call observer failed for event %s", kind)


__all__ = [
    "ModelCallEvent",
    "ModelCallEventKind",
    "ModelCallPolicy",
    "ModelCallSupervisor",
    "ModelCallTimeoutError",
]
