"""Retry helpers."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import TypeVar


T = TypeVar("T")


def call_with_retries(
    callback: Callable[[], T],
    *,
    label: str,
    max_retries: int = 3,
    sleep_seconds: float = 2.0,
) -> T:
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    attempts = max_retries + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return callback()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    assert last_exc is not None
    raise last_exc
