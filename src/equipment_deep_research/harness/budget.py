from __future__ import annotations

from collections.abc import Callable, Mapping
import math
from threading import RLock
import time
from typing import Any


BUDGET_KEYS = frozenset(
    {"max_turns", "max_tool_calls", "max_seconds", "max_tokens"}
)


class BudgetExceededError(RuntimeError):
    pass


class Budget:
    """Thread-safe execution budget with atomic consumption records."""

    def __init__(
        self,
        limits: Mapping[str, int | float] | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if limits is None:
            limits = {}
        if not isinstance(limits, Mapping):
            raise TypeError("budget must be an object")
        unknown = sorted(str(key) for key in set(limits) - BUDGET_KEYS)
        if unknown:
            raise ValueError(f"unknown budget keys: {unknown}")

        normalized: dict[str, int | float | None] = {}
        for key in BUDGET_KEYS:
            value = limits.get(key)
            if value is None:
                normalized[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"budget {key} must be a non-negative number")
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"budget {key} must be a finite non-negative number")
            if key != "max_seconds" and not isinstance(value, int):
                raise TypeError(f"budget {key} must be a non-negative integer")
            normalized[key] = float(value) if key == "max_seconds" else int(value)

        self._limits = normalized
        self._monotonic = monotonic
        self._started_at = float(monotonic())
        self._turns = 0
        self._tool_calls = 0
        self._tokens = 0
        self._lock = RLock()

    @property
    def max_seconds(self) -> float | None:
        value = self._limits["max_seconds"]
        return None if value is None else float(value)

    @property
    def max_turns(self) -> int | None:
        value = self._limits["max_turns"]
        return None if value is None else int(value)

    def try_start_turn(self) -> bool:
        with self._lock:
            exhausted_key = self._exhausted_key_locked(include_turn=True)
            if exhausted_key is not None:
                return False
            self._turns += 1
            return True

    def record_turn(self) -> None:
        if not self.try_start_turn():
            raise BudgetExceededError(self._exhausted_message())

    def record_tool_call(self) -> None:
        with self._lock:
            exhausted_key = self._exhausted_key_locked(
                include_turn=False,
                include_tokens=False,
            )
            if exhausted_key is not None:
                raise BudgetExceededError(f"budget exhausted: {exhausted_key}")
            self._tool_calls += 1

    def record_tokens(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("token count must be a non-negative integer")
        if count < 0:
            raise ValueError("token count must be a non-negative integer")
        with self._lock:
            self._tokens += count

    def is_exhausted(self) -> bool:
        with self._lock:
            return self._exhausted_key_locked(include_turn=True) is not None

    def remaining(self) -> dict[str, int | float | None]:
        with self._lock:
            elapsed = max(0.0, float(self._monotonic()) - self._started_at)
            return {
                "max_turns": _remaining_int(self._limits["max_turns"], self._turns),
                "max_tool_calls": _remaining_int(
                    self._limits["max_tool_calls"], self._tool_calls
                ),
                "max_seconds": _remaining_seconds(
                    self._limits["max_seconds"], elapsed
                ),
                "max_tokens": _remaining_int(self._limits["max_tokens"], self._tokens),
            }

    def remaining_seconds(self) -> float | None:
        return self.remaining()["max_seconds"]  # type: ignore[return-value]

    def to_plain(self) -> dict[str, Any]:
        with self._lock:
            return {
                "limits": dict(self._limits),
                "consumed": {
                    "turns": self._turns,
                    "tool_calls": self._tool_calls,
                    "tokens": self._tokens,
                },
                "remaining": self.remaining(),
            }

    def _exhausted_key_locked(
        self,
        *,
        include_turn: bool,
        include_tokens: bool = True,
    ) -> str | None:
        max_seconds = self._limits["max_seconds"]
        if max_seconds is not None:
            elapsed = max(0.0, float(self._monotonic()) - self._started_at)
            if elapsed >= float(max_seconds):
                return "max_seconds"
        max_tool_calls = self._limits["max_tool_calls"]
        if max_tool_calls is not None and self._tool_calls >= int(max_tool_calls):
            return "max_tool_calls"
        if include_tokens:
            max_tokens = self._limits["max_tokens"]
            if max_tokens is not None and self._tokens >= int(max_tokens):
                return "max_tokens"
        if include_turn:
            max_turns = self._limits["max_turns"]
            if max_turns is not None and self._turns >= int(max_turns):
                return "max_turns"
        return None

    def _exhausted_message(self) -> str:
        with self._lock:
            key = self._exhausted_key_locked(include_turn=True) or "unknown"
        return f"budget exhausted: {key}"


def _remaining_int(limit: int | float | None, consumed: int) -> int | None:
    if limit is None:
        return None
    return max(0, int(limit) - consumed)


def _remaining_seconds(limit: int | float | None, elapsed: float) -> float | None:
    if limit is None:
        return None
    return max(0.0, round(float(limit) - elapsed, 6))


__all__ = ["BUDGET_KEYS", "Budget", "BudgetExceededError"]
