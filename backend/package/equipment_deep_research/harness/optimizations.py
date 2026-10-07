"""Explicit, idempotent runtime defaults and lightweight timing metrics.

This module deliberately avoids monkey-patching authorization or scheduler
classes.  Security decisions remain local to each policy instance, and a
second CLI invocation in the same process cannot wrap core methods again.
"""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


_RUNTIME_DEFAULTS = {
    "EQUIPMENT_DR_MAXIMIZE_AGENT_PARALLELISM": "1",
    "EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY": "12",
    "EQUIPMENT_DR_EVIDENCE_PREWARM_CONCURRENCY": "8",
    "EQUIPMENT_DR_BASELINE_PREFETCH_WORKERS": "8",
}


@dataclass
class PerformanceMonitor:
    """Collect opt-in timing samples without changing application methods."""

    timings: dict[str, list[float]] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return os.environ.get("EQUIPMENT_DR_PERF_MONITOR", "0") == "1"

    def measure(self, label: str) -> AbstractContextManager[None]:
        return _TimingContext(self, label)

    def record(self, label: str, elapsed: float) -> None:
        if self.enabled:
            self.timings.setdefault(label, []).append(elapsed)

    def report(self) -> dict[str, dict[str, float]]:
        if not self.enabled:
            return {}
        return {
            label: {
                "count": float(len(samples)),
                "total": sum(samples),
                "mean": sum(samples) / len(samples),
                "min": min(samples),
                "max": max(samples),
            }
            for label, samples in self.timings.items()
            if samples
        }


class _TimingContext(AbstractContextManager[None]):
    def __init__(self, monitor: PerformanceMonitor, label: str) -> None:
        self.monitor = monitor
        self.label = label
        self.started_at = 0.0

    def __enter__(self) -> None:
        self.started_at = perf_counter()
        return None

    def __exit__(self, *exc_info: object) -> None:
        self.monitor.record(self.label, perf_counter() - self.started_at)


_PERFORMANCE_MONITOR = PerformanceMonitor()


def apply_env_optimizations(*, verbose: bool = True) -> list[str]:
    """Apply conservative defaults without overriding deployment choices."""

    applied: list[str] = []
    for key, value in _RUNTIME_DEFAULTS.items():
        if key not in os.environ:
            os.environ[key] = value
            applied.append(f"{key}={value}")
    if verbose and applied:
        print("Applied runtime defaults: " + ", ".join(applied))
    return applied


def apply_quick_optimizations(*, verbose: bool = True) -> dict[str, Any]:
    """Backward-compatible entry point for safe startup defaults."""

    applied = apply_env_optimizations(verbose=verbose)
    return {
        "env_optimizations": bool(applied),
        "applied_defaults": applied,
        "performance_monitor": _PERFORMANCE_MONITOR.enabled,
        "authorization_cache": False,
    }


def print_performance_report() -> None:
    report = _PERFORMANCE_MONITOR.report()
    if not report:
        return
    print("Runtime performance report:")
    for label, stats in sorted(report.items()):
        print(
            f"  {label}: count={int(stats['count'])} "
            f"total={stats['total']:.3f}s mean={stats['mean']:.3f}s"
        )


def get_authorization_cache_stats() -> dict[str, Any]:
    """Compatibility result: authorization caching was intentionally removed."""

    return {
        "enabled": False,
        "reason": "authorization is evaluated per policy instance and call",
    }


__all__ = [
    "PerformanceMonitor",
    "apply_env_optimizations",
    "apply_quick_optimizations",
    "get_authorization_cache_stats",
    "print_performance_report",
]
