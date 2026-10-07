"""Fair, cancellable capacity control for Codex CLI turns.

The orchestration layer already has run-local budgets.  This gate is the
deployment-level boundary: all provider instances in one API process share a
queue for the same upstream model, so independent users cannot each expand a
new provider instance and overwhelm the gateway.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import errno
import hashlib
import heapq
import os
from pathlib import Path
import random
from threading import Lock
from time import monotonic
from typing import Any
from weakref import WeakKeyDictionary

try:  # POSIX deployments (including macOS/Linux) support cross-worker slots.
    import fcntl
except ImportError:  # pragma: no cover - Windows falls back to process-local gating.
    fcntl = None  # type: ignore[assignment]


_PRIORITY_RANK = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "background": 3,
}


def normalize_call_priority(value: object) -> str:
    normalized = str(value or "normal").strip().lower().replace("-", "_")
    if normalized in {"priority", "swarm", "s6", "quality_gate", "delivery"}:
        return "critical"
    if normalized in {"urgent", "latency_sensitive"}:
        return "high"
    if normalized in _PRIORITY_RANK:
        return normalized
    return "normal"


@dataclass
class CodexCallLease:
    """A permit returned by :class:`CodexCallGate`.

    Release is idempotent because provider cancellation can run through more
    than one cleanup path.  The gate is intentionally kept private so callers
    cannot alter its counters without going through the lease.
    """

    queue_wait_seconds: float
    active_calls: int
    concurrency_limit: int
    priority: str
    _gate: "CodexCallGate"
    _process_slot_fd: int | None = None
    _released: bool = False

    async def release(
        self,
        *,
        success: bool,
        elapsed_seconds: float = 0.0,
        capacity_failure: bool = False,
    ) -> None:
        if self._released:
            return
        self._released = True
        release_task = asyncio.create_task(
            self._gate.release(
                success=success,
                elapsed_seconds=elapsed_seconds,
                capacity_failure=capacity_failure,
                process_slot_fd=self._process_slot_fd,
            )
        )
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError:
            # A request can be cancelled at the exact moment a CLI process
            # exits. Finish the permit/file-slot release before propagating
            # cancellation, otherwise capacity silently leaks.
            await asyncio.shield(release_task)
            raise


class CodexCallGate:
    """Async FIFO-with-priority gate with conservative capacity backoff."""

    def __init__(
        self,
        *,
        key: str,
        maximum: int | None = None,
        minimum: int | None = None,
        lock_root: str | Path | None = None,
    ) -> None:
        configured = _positive_int(
            "EQUIPMENT_DR_CODEX_MAX_CONCURRENCY",
            _positive_int("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", 8),
        )
        requested = configured if maximum is None else int(maximum)
        self.key = str(key or "codex")[:240]
        self._lock_root = (
            Path(lock_root).expanduser().resolve()
            if lock_root is not None and fcntl is not None
            else None
        )
        self._lock_stem = hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:24]
        self.minimum = max(
            1,
            min(
                requested,
                _positive_int("EQUIPMENT_DR_CODEX_MIN_CONCURRENCY", 1)
                if minimum is None
                else int(minimum),
            ),
        )
        self.maximum = max(self.minimum, min(64, requested))
        self.limit = self.maximum
        self._active = 0
        self._sequence = 0
        self._queue: list[tuple[int, int, object, str]] = []
        # A single dynamic swarm can enqueue many same-priority calls. Keep a
        # small per-priority cursor so those calls yield to another run at the
        # same priority while preserving the intentional priority hierarchy.
        self._last_served_by_priority: dict[int, str] = {}
        self._condition = asyncio.Condition()
        self._cooldown_until = 0.0
        self._capacity_failures = 0
        self._recent: deque[tuple[float, bool, bool]] = deque(maxlen=12)
        self._base_backoff = _nonnegative_float(
            "EQUIPMENT_DR_CODEX_GATE_BACKOFF_SECONDS", 1.5
        )
        self._max_backoff = max(
            self._base_backoff,
            _nonnegative_float("EQUIPMENT_DR_CODEX_GATE_BACKOFF_MAX_SECONDS", 30.0),
        )
        self._jitter = _nonnegative_float(
            "EQUIPMENT_DR_CODEX_GATE_BACKOFF_JITTER_SECONDS", 0.4
        )

    async def acquire(
        self,
        *,
        priority: object = "normal",
        fairness_key: object = "",
        timeout_seconds: float | None = None,
    ) -> CodexCallLease:
        """Wait for a permit and remain cancellable while queued."""

        normalized = normalize_call_priority(priority)
        fair_key = " ".join(str(fairness_key or "").split()).strip()[:160]
        queued_at = monotonic()
        ticket = object()
        async with self._condition:
            self._sequence += 1
            entry = (_PRIORITY_RANK[normalized], self._sequence, ticket, fair_key)
            heapq.heappush(self._queue, entry)
            try:
                wait_coro = self._wait_for_turn(ticket, fair_key=fair_key)
                if timeout_seconds is None:
                    active_calls, limit = await wait_coro
                else:
                    active_calls, limit = await asyncio.wait_for(
                        wait_coro,
                        timeout=max(0.001, float(timeout_seconds)),
                    )
            except BaseException:
                self._remove_ticket(ticket)
                self._condition.notify_all()
                raise
        process_slot_fd: int | None = None
        try:
            process_slot_fd = await self._acquire_process_slot()
        except BaseException:
            await self._release_local()
            raise
        return CodexCallLease(
            queue_wait_seconds=round(monotonic() - queued_at, 3),
            active_calls=active_calls,
            concurrency_limit=limit,
            priority=normalized,
            _gate=self,
            _process_slot_fd=process_slot_fd,
        )

    def _fair_ticket(self, priority_rank: int) -> object | None:
        candidates = [
            entry
            for entry in self._queue
            if entry[0] == priority_rank
        ]
        if not candidates:
            return None
        last_key = self._last_served_by_priority.get(priority_rank, "")
        for entry in sorted(candidates, key=lambda item: item[1]):
            if entry[3] != last_key:
                return entry[2]
        return min(candidates, key=lambda item: item[1])[2]

    async def _wait_for_turn(self, ticket: object, *, fair_key: str) -> tuple[int, int]:
        while True:
            now = monotonic()
            priority_rank = min((entry[0] for entry in self._queue), default=None)
            head = self._fair_ticket(priority_rank) if priority_rank is not None else None
            cooldown = max(0.0, self._cooldown_until - now)
            if head is ticket and self._active < self.limit and cooldown <= 0:
                for index, entry in enumerate(self._queue):
                    if entry[2] is ticket:
                        self._queue[index] = self._queue[-1]
                        self._queue.pop()
                        if index < len(self._queue):
                            heapq.heapify(self._queue)
                        break
                self._active += 1
                self._last_served_by_priority[priority_rank] = fair_key
                return self._active, self.limit
            if cooldown > 0 and self._active < self.limit:
                try:
                    await asyncio.wait_for(self._condition.wait(), cooldown)
                except asyncio.TimeoutError:
                    pass
            else:
                await self._condition.wait()

    def _remove_ticket(self, ticket: object) -> None:
        for index, entry in enumerate(self._queue):
            if entry[2] is ticket:
                self._queue[index] = self._queue[-1]
                self._queue.pop()
                if index < len(self._queue):
                    heapq.heapify(self._queue)
                return

    async def _release_local(self) -> None:
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    async def _acquire_process_slot(self) -> int | None:
        if self._lock_root is None or fcntl is None:
            return None
        try:
            self._lock_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # The process-local async gate remains useful for read-only or
            # legacy workspaces where the runtime directory cannot be created.
            self._lock_root = None
            return None
        while True:
            for slot in range(max(1, self.maximum)):
                path = self._lock_root / f"{self._lock_stem}-{slot:02d}.lock"
                try:
                    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
                except OSError as exc:
                    if exc.errno == errno.EAGAIN:
                        continue
                    raise
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        os.close(fd)
                        continue
                    except OSError as exc:
                        os.close(fd)
                        if exc.errno in {errno.EACCES, errno.EAGAIN}:
                            continue
                        raise
                    return fd
                except BaseException:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    raise
            # A cancelled asyncio task exits this sleep immediately, so a
            # disconnected request cannot strand a local permit or file slot.
            await asyncio.sleep(0.05)

    async def release(
        self,
        *,
        success: bool,
        elapsed_seconds: float,
        capacity_failure: bool = False,
        process_slot_fd: int | None = None,
    ) -> None:
        if process_slot_fd is not None and fcntl is not None:
            try:
                fcntl.flock(process_slot_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(process_slot_fd)
            except OSError:
                pass
        async with self._condition:
            self._active = max(0, self._active - 1)
            duration = max(0.0, float(elapsed_seconds))
            self._recent.append((duration, bool(success), bool(capacity_failure)))
            if capacity_failure:
                self._capacity_failures += 1
                self.limit = max(self.minimum, self.limit - 1)
                delay = min(
                    self._max_backoff,
                    self._base_backoff
                    * (2 ** max(0, self._capacity_failures - 1)),
                )
                self._cooldown_until = max(
                    self._cooldown_until,
                    monotonic() + delay + random.uniform(0.0, self._jitter),
                )
            elif success:
                # Recover one slot only after a full clean window.  This keeps
                # a transient capacity response from causing an oscillation.
                recent = list(self._recent)
                if (
                    self.limit < self.maximum
                    and len(recent) >= 6
                    and not any(item[2] for item in recent[-6:])
                    and all(item[1] for item in recent[-6:])
                ):
                    self.limit += 1
                    self._capacity_failures = max(0, self._capacity_failures - 1)
                    self._recent.clear()
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "limit": self.limit,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "active": self._active,
            "queue_depth": len(self._queue),
            "capacity_failures": self._capacity_failures,
            "cooldown_seconds": round(max(0.0, self._cooldown_until - monotonic()), 3),
        }


_registry_lock = Lock()
_registry: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, CodexCallGate]] = (
    WeakKeyDictionary()
)


def shared_codex_call_gate(
    key: str,
    *,
    maximum: int | None = None,
    lock_root: str | Path | None = None,
) -> CodexCallGate:
    """Return one gate per event loop and upstream model identity."""

    loop = asyncio.get_running_loop()
    normalized_key = str(key or "codex")[:240]
    with _registry_lock:
        gates = _registry.setdefault(loop, {})
        gate = gates.get(normalized_key)
        if gate is None:
            gate = CodexCallGate(
                key=normalized_key,
                maximum=maximum,
                lock_root=lock_root,
            )
            gates[normalized_key] = gate
        elif maximum is not None:
            gate.maximum = max(gate.minimum, min(64, int(maximum)))
            gate.limit = min(gate.limit, gate.maximum)
        return gate


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _nonnegative_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(0.0, value)


__all__ = [
    "CodexCallGate",
    "CodexCallLease",
    "normalize_call_priority",
    "shared_codex_call_gate",
]
