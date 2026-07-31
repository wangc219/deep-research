"""Run-level budget accounting for demand discovery harness runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


@dataclass
class RunBudget:
    """Mutable run budget charged at provider/tool boundaries."""

    max_tokens: int | None = None
    max_tool_calls: int | None = None
    max_wall_clock_ms: int | None = None
    spent_tokens: int = 0
    spent_tool_calls: int = 0
    started_at_monotonic: float = field(default_factory=time.monotonic)

    def charge_usage(self, usage: dict[str, Any]) -> None:
        """Charge non-cached input tokens plus output tokens.

        Providers may include cached tokens either as a top-level field or
        under ``input_token_details``. Cached input is not double-counted.
        """

        if not usage:
            return
        input_tokens = _int_value(usage, "input_tokens", "prompt_tokens")
        output_tokens = _int_value(usage, "output_tokens", "completion_tokens")
        cached_tokens = _int_value(usage, "cached_tokens")
        details = usage.get("input_token_details")
        if isinstance(details, dict):
            cached_tokens = max(cached_tokens, _int_value(details, "cached_tokens"))
        plural_details = usage.get("input_tokens_details")
        if isinstance(plural_details, dict):
            cached_tokens = max(
                cached_tokens,
                _int_value(plural_details, "cached_tokens"),
            )

        if input_tokens or output_tokens:
            self.spent_tokens += max(input_tokens - cached_tokens, 0) + output_tokens
            return

        self.spent_tokens += _int_value(usage, "total_tokens")

    def charge_tool_call(self) -> None:
        self.spent_tool_calls += 1

    def exhausted(self) -> str | None:
        if self.max_tokens is not None and self.spent_tokens >= self.max_tokens:
            return "tokens"
        if (
            self.max_tool_calls is not None
            and self.spent_tool_calls >= self.max_tool_calls
        ):
            return "tool_calls"
        if self.max_wall_clock_ms is not None:
            elapsed_ms = (time.monotonic() - self.started_at_monotonic) * 1000
            if elapsed_ms >= self.max_wall_clock_ms:
                return "wall_clock_ms"
        return None

    def remaining_summary(self) -> dict[str, Any]:
        elapsed_ms = int((time.monotonic() - self.started_at_monotonic) * 1000)
        return {
            "max_tokens": self.max_tokens,
            "spent_tokens": self.spent_tokens,
            "remaining_tokens": _remaining(self.max_tokens, self.spent_tokens),
            "max_tool_calls": self.max_tool_calls,
            "spent_tool_calls": self.spent_tool_calls,
            "remaining_tool_calls": _remaining(
                self.max_tool_calls, self.spent_tool_calls
            ),
            "max_wall_clock_ms": self.max_wall_clock_ms,
            "elapsed_wall_clock_ms": elapsed_ms,
            "remaining_wall_clock_ms": _remaining(
                self.max_wall_clock_ms, elapsed_ms
            ),
        }


def _int_value(data: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0


def _remaining(max_value: int | None, spent: int) -> int | None:
    if max_value is None:
        return None
    return max(max_value - spent, 0)
