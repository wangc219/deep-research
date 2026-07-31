"""Cooperative cancellation primitives for long-running agent runs."""

from __future__ import annotations

import time


class RunCancelled(RuntimeError):
    """Raised at a cooperative checkpoint after a run token is cancelled."""


class CancelToken:
    """A small parent-propagating cancel token with optional deadline."""

    def __init__(
        self,
        parent: "CancelToken | None" = None,
        timeout_ms: int | None = None,
    ) -> None:
        self._parent = parent
        self._cancelled = False
        self._reason = ""
        self._deadline = (
            time.monotonic() + max(timeout_ms, 0) / 1000
            if timeout_ms is not None
            else None
        )

    def cancel(self, reason: str = "") -> None:
        if self._cancelled:
            return
        self._cancelled = True
        self._reason = reason or "cancelled"

    @property
    def cancelled(self) -> bool:
        return self.reason != ""

    @property
    def reason(self) -> str:
        if self._parent is not None and self._parent.cancelled:
            return self._parent.reason
        if self._cancelled:
            return self._reason or "cancelled"
        if self._deadline is not None and time.monotonic() >= self._deadline:
            return "timeout"
        return ""

    def raise_if_cancelled(self) -> None:
        reason = self.reason
        if reason:
            raise RunCancelled(reason)

    def derive(self, timeout_ms: int | None = None) -> "CancelToken":
        return CancelToken(parent=self, timeout_ms=timeout_ms)
