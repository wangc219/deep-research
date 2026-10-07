"""Retention cleanup for demand discovery run artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

from knowledgegraph.demand_discovery.domain.store import DomainStore


@dataclass(frozen=True)
class RetentionConfig:
    mid_term_keep_days: int = 90
    short_term_keep_days: int = 14
    runtime_log_keep_days: int = 7


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    layer: str
    reason: str
    size_bytes: int


@dataclass(frozen=True)
class CleanupResult:
    to_delete: list[CleanupCandidate] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)
    protected_refs: set[str] = field(default_factory=set)

    @property
    def reclaimable_bytes(self) -> int:
        return sum(item.size_bytes for item in self.to_delete)


def cleanup_outputs(
    root: str | Path,
    config: RetentionConfig,
    *,
    now: datetime | None = None,
    apply: bool = False,
    domain_store: DomainStore | None = None,
) -> CleanupResult:
    base = Path(root)
    current = now or datetime.now(timezone.utc)
    protected_refs = _referenced_artifact_refs(domain_store)
    candidates: list[CleanupCandidate] = []

    for path in _iter_existing([base / "scheduled" / "runner.log"]):
        if _older_than(path, config.runtime_log_keep_days, current):
            candidates.append(_candidate(path, "runtime_log", "old runner log"))

    for path in base.glob("runs/*/inbox/processed/*"):
        if path.is_file() and _older_than(path, config.runtime_log_keep_days, current):
            candidates.append(_candidate(path, "runtime_log", "old processed inbox file"))

    for path in base.glob("runs/*/workers/*.jsonl"):
        if path.is_file() and _older_than(path, config.mid_term_keep_days, current):
            candidates.append(_candidate(path, "mid_term", "old worker session"))

    for path in base.glob("runs/*/progress.md"):
        if path.is_file() and _older_than(path, config.mid_term_keep_days, current):
            candidates.append(_candidate(path, "mid_term", "old progress snapshot"))

    for path in base.glob("runs/*/artifacts/*"):
        if not path.is_file():
            continue
        if _artifact_ref_for_path(path) in protected_refs:
            continue
        if _older_than(path, config.short_term_keep_days, current):
            candidates.append(_candidate(path, "short_term", "old unreferenced artifact"))

    deleted: list[Path] = []
    if apply:
        for item in candidates:
            try:
                item.path.unlink()
                deleted.append(item.path)
            except FileNotFoundError:
                continue
    return CleanupResult(
        to_delete=candidates,
        deleted=deleted,
        protected_refs=protected_refs,
    )


def _iter_existing(paths: Iterable[Path]) -> list[Path]:
    return [path for path in paths if path.exists() and path.is_file()]


def _candidate(path: Path, layer: str, reason: str) -> CleanupCandidate:
    return CleanupCandidate(
        path=path,
        layer=layer,
        reason=reason,
        size_bytes=path.stat().st_size,
    )


def _older_than(path: Path, keep_days: int, now: datetime) -> bool:
    if keep_days < 0:
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return (now - modified).days >= keep_days


def _referenced_artifact_refs(store: DomainStore | None) -> set[str]:
    if store is None:
        return set()
    refs: set[str] = set()
    pattern = re.compile(r"([a-z_]+:[A-Za-z0-9]+)")
    for evidence in store.evidence.values():
        match = pattern.search(evidence.source_location or "")
        if match:
            refs.add(match.group(1))
    return refs


def _artifact_ref_for_path(path: Path) -> str:
    stem = path.stem
    if stem.endswith(".meta"):
        stem = stem[:-5]
    if "-" not in stem:
        return ""
    kind, short = stem.split("-", 1)
    return f"{kind}:{short}"
