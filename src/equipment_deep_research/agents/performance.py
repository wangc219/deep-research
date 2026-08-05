"""Quality-preserving runtime controls for concurrent Codex agent calls."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
from threading import Condition
from time import monotonic
from typing import Any, Iterator


@dataclass(frozen=True)
class CallLease:
    queue_wait_seconds: float
    concurrency_limit: int
    active_calls: int
    priority: str = "normal"


class AdaptiveCallGate:
    """Bound model-call concurrency and react conservatively to gateway latency."""

    def __init__(self) -> None:
        configured = max(
            1,
            int(os.environ.get("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "3")),
        )
        self.minimum = max(
            1,
            min(
                configured,
                int(os.environ.get("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "1")),
            ),
        )
        self.maximum = max(
            configured,
            int(os.environ.get("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "4")),
        )
        self.limit = min(self.maximum, max(self.minimum, configured))
        self.reserved_priority_slots = max(
            0,
            min(
                self.limit - 1,
                int(
                    os.environ.get(
                        "EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS",
                        "2",
                    )
                ),
            ),
        )
        self.slow_seconds = max(
            10.0,
            float(os.environ.get("EQUIPMENT_DR_CODEX_SLOW_CALL_SECONDS", "180")),
        )
        self.fast_seconds = max(
            1.0,
            float(os.environ.get("EQUIPMENT_DR_CODEX_FAST_CALL_SECONDS", "75")),
        )
        self.latency_downshift_enabled = (
            os.environ.get("EQUIPMENT_DR_CODEX_LATENCY_DOWNSHIFT", "0")
            .strip()
            .lower()
            in {"1", "true", "yes"}
        )
        self._condition = Condition()
        self._active = 0
        self._priority_waiters = 0
        self._recent: deque[tuple[float, bool]] = deque(maxlen=8)

    @contextmanager
    def lease(self, *, priority: str = "normal") -> Iterator[CallLease]:
        lease = self.acquire(priority=priority)
        started_at = monotonic()
        success = False
        try:
            yield lease
            success = True
        finally:
            self.release(monotonic() - started_at, success=success)

    def acquire(self, *, priority: str = "normal") -> CallLease:
        queued_at = monotonic()
        normalized_priority = _normalize_priority(priority)
        with self._condition:
            if normalized_priority == "critical":
                self._priority_waiters += 1
            try:
                while not self._can_acquire(normalized_priority):
                    self._condition.wait()
                self._active += 1
                return CallLease(
                    queue_wait_seconds=round(monotonic() - queued_at, 3),
                    concurrency_limit=self.limit,
                    active_calls=self._active,
                    priority=normalized_priority,
                )
            finally:
                if normalized_priority == "critical":
                    self._priority_waiters = max(0, self._priority_waiters - 1)

    def try_acquire(self, *, priority: str = "normal") -> CallLease | None:
        normalized_priority = _normalize_priority(priority)
        with self._condition:
            if not self._can_acquire(normalized_priority):
                return None
            self._active += 1
            return CallLease(
                queue_wait_seconds=0.0,
                concurrency_limit=self.limit,
                active_calls=self._active,
                priority=normalized_priority,
            )

    def release(self, elapsed: float, *, success: bool) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._recent.append((elapsed, success))
            self._retune()
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "limit": self.limit,
                "minimum": self.minimum,
                "maximum": self.maximum,
                "active": self._active,
                "reserved_priority_slots": self.reserved_priority_slots,
                "priority_waiters": self._priority_waiters,
                "recent_calls": len(self._recent),
                "latency_downshift_enabled": self.latency_downshift_enabled,
            }

    def cap_concurrency(self, maximum: int) -> None:
        """Apply a per-run upper bound without increasing deployment limits."""
        bounded = max(1, int(maximum))
        with self._condition:
            self.maximum = min(self.maximum, bounded)
            self.minimum = min(self.minimum, self.maximum)
            self.limit = min(self.limit, self.maximum)
            self.reserved_priority_slots = min(
                self.reserved_priority_slots,
                max(0, self.limit - 1),
            )
            self._condition.notify_all()

    def _can_acquire(self, priority: str) -> bool:
        if self._active >= self.limit:
            return False
        if priority == "critical":
            return True
        background_limit = max(1, self.limit - self.reserved_priority_slots)
        return self._priority_waiters == 0 and self._active < background_limit

    def _retune(self) -> None:
        if len(self._recent) < 4:
            return
        failures = sum(1 for _, success in self._recent if not success)
        durations = [elapsed for elapsed, success in self._recent if success]
        # Long, successful reasoning calls are normal for the quality profile and
        # do not by themselves indicate gateway overload. Treating one long call
        # as congestion caused the shared gate to collapse toward its minimum and
        # serialized later agents. Failure-based downshift stays enabled; latency
        # downshift is an explicit deployment choice for rate-limited gateways.
        latency_overloaded = (
            self.latency_downshift_enabled
            and len(durations) >= 4
            and sum(elapsed >= self.slow_seconds for elapsed in durations) >= 3
        )
        if failures >= 2 or latency_overloaded:
            self.limit = max(self.minimum, self.limit - 1)
            return
        if (
            self.limit < self.maximum
            and len(durations) >= 4
            and sum(durations[-4:]) / 4 <= self.fast_seconds
        ):
            self.limit += 1


def _normalize_priority(value: str) -> str:
    # Core swarm, quality-gate, and delivery phases are intentionally named at
    # their call sites.  Treat them as critical gate traffic so the reserved
    # slots remain available to those phases instead of accidentally reducing
    # a six-way winning-swarm profile to four effective calls.
    return (
        "critical"
        if str(value).strip().lower()
        in {"critical", "priority", "swarm", "quality_gate", "delivery"}
        else "normal"
    )


def role_card_id(agent_id: str, phase: str, profile: Mapping[str, Any]) -> str:
    import hashlib
    import json

    content = json.dumps(
        {"agent_id": agent_id, "phase": phase, "profile": profile},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "role-card:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


__all__ = ["AdaptiveCallGate", "CallLease", "role_card_id"]
