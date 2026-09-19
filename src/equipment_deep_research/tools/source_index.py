"""Persistent, evidence-safe source recommendations shared across research runs."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any, Iterator
from urllib.parse import urlsplit

from equipment_deep_research.domain.models import EvidenceCard, now_iso


_INDEX_LOCK = RLock()


class SourcePriorityIndex:
    """Learn which public sources are both useful and locally materializable.

    The index stores source metadata only. It never promotes historical claims to
    current evidence; every run must inspect and materialize the source again.
    """

    def __init__(
        self,
        path: str | Path | None,
        *,
        seed_path: str | Path | None = None,
    ) -> None:
        self.path = Path(path) if path else None
        self.seed_path = Path(seed_path) if seed_path else _default_seed_path()

    def recommend(
        self,
        agent_id: str,
        topic: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        seeds = self._seed_rows(agent_id)
        learned = self._learned_rows(agent_id, topic)
        bad_urls = self._unhealthy_urls()
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in [*learned, *seeds]:
            url = str(row.get("url", "")).strip()
            if not url or url in seen or url in bad_urls:
                continue
            seen.add(url)
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows

    def _unhealthy_urls(self) -> set[str]:
        """URLs recently rejected by materialization/network safety."""

        if self.path is None:
            return set()
        with _INDEX_LOCK, _index_file_lock(self.path, exclusive=False):
            sources = self._load_index().get("sources", {})
        if not isinstance(sources, Mapping):
            return set()
        bad_statuses = {
            "fetch_failed",
            "network_safety_rejected",
            "reader_error",
            "materialization_failed",
        }
        return {
            str(url)
            for url, row in sources.items()
            if isinstance(row, Mapping)
            and str(row.get("last_status", "")).strip().lower() in bad_statuses
        }

    def recommend_shared(
        self,
        agent_ids: list[str],
        topic: str,
        *,
        limit: int = 18,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        by_url: dict[str, dict[str, Any]] = {}
        for agent_id in agent_ids:
            for raw in self.recommend(agent_id, topic, limit=limit):
                url = str(raw.get("url", "")).strip()
                if not url:
                    continue
                current = by_url.setdefault(
                    url,
                    {**raw, "recommended_for": []},
                )
                current["recommended_for"] = list(
                    dict.fromkeys([*current.get("recommended_for", []), agent_id])
                )
                current["priority"] = max(
                    int(current.get("priority", 0)),
                    int(raw.get("priority", 0)),
                )
        rows.extend(
            sorted(
                (
                    row
                    for row in by_url.values()
                    if len(row.get("recommended_for", [])) >= 2
                ),
                key=lambda row: (
                    len(row.get("recommended_for", [])),
                    int(row.get("priority", 0)),
                ),
                reverse=True,
            )[:limit]
        )
        return rows

    def record(
        self,
        *,
        agent_id: str,
        topic: str,
        evidence: EvidenceCard,
        material: Mapping[str, Any],
        assessment: object,
    ) -> None:
        url = evidence.source_url.strip()
        if self.path is None:
            return
        try:
            parsed = urlsplit(url)
        except ValueError:
            return
        if parsed.scheme != "https" or not parsed.hostname:
            return
        formal_allowed = bool(material.get("formal_evidence_allowed", True))
        decision = str(getattr(assessment, "decision", ""))
        accepted = formal_allowed and decision == "accepted"
        status = str(material.get("status", "unknown"))
        with _INDEX_LOCK, _index_file_lock(self.path, exclusive=True):
            payload = self._load_index()
            sources = payload.setdefault("sources", {})
            current = dict(sources.get(url, {}))
            agent_ids = list(dict.fromkeys([*current.get("agent_ids", []), agent_id]))
            topics = list(dict.fromkeys([*current.get("topics", []), topic]))[-5:]
            success_count = int(current.get("success_count", 0))
            failure_count = int(current.get("failure_count", 0))
            accepted_count = int(current.get("accepted_count", 0))
            if formal_allowed:
                success_count += 1
            else:
                failure_count += 1
            if accepted:
                accepted_count += 1
            sources[url] = {
                "url": url,
                "domain": parsed.hostname.lower(),
                "title": evidence.source_title[:300],
                "agent_ids": agent_ids,
                "topics": topics,
                "success_count": success_count,
                "accepted_count": accepted_count,
                "failure_count": failure_count,
                "last_status": status,
                "last_decision": decision,
                "last_seen_at": now_iso(),
            }
            payload["schema_version"] = "1.0"
            payload["updated_at"] = now_iso()
            self._write_index(payload)

    def _seed_rows(self, agent_id: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.seed_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_rows = payload.get("agents", {}).get(agent_id, [])
        return [
            {
                "url": str(row.get("url", "")),
                "domain": urlsplit(str(row.get("url", ""))).hostname or "",
                "source_type": str(row.get("source_type", "curated")),
                "search_focus": list(row.get("search_focus", [])),
                "priority": int(row.get("priority", 50)),
                "learned": False,
            }
            for row in raw_rows
            if isinstance(row, Mapping)
        ]

    def _learned_rows(self, agent_id: str, topic: str) -> list[dict[str, Any]]:
        if self.path is None:
            sources: Mapping[str, Any] = {}
        else:
            with _INDEX_LOCK, _index_file_lock(self.path, exclusive=False):
                sources = self._load_index().get("sources", {})
        rows: list[dict[str, Any]] = []
        topic_terms = _terms(topic)
        for raw in sources.values():
            if not isinstance(raw, Mapping) or agent_id not in raw.get("agent_ids", []):
                continue
            accepted_count = int(raw.get("accepted_count", 0))
            success_count = int(raw.get("success_count", 0))
            failure_count = int(raw.get("failure_count", 0))
            # A previously useful URL can become blocked or unavailable. Do
            # not keep promoting a known-bad endpoint ahead of healthy
            # sources in provider-neutral (Chat Completions) runs; seed rows
            # and other learned domains remain available as alternatives.
            last_status = str(raw.get("last_status", "")).strip().lower()
            if last_status in {
                "fetch_failed",
                "network_safety_rejected",
                "reader_error",
                "materialization_failed",
            }:
                continue
            if accepted_count < 1 or success_count <= failure_count:
                continue
            relevance = max(
                (
                    _overlap(topic_terms, _terms(str(item)))
                    for item in raw.get("topics", [])
                ),
                default=0,
            )
            rows.append(
                {
                    "url": str(raw.get("url", "")),
                    "domain": str(raw.get("domain", "")),
                    "source_type": "previously_materialized",
                    "search_focus": [],
                    "priority": 100 + accepted_count * 5 + relevance - failure_count,
                    "learned": True,
                    "last_seen_at": str(raw.get("last_seen_at", "")),
                    "accepted_count": accepted_count,
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                int(row.get("priority", 0)),
                str(row.get("last_seen_at", "")),
            ),
            reverse=True,
        )

    def _load_index(self) -> dict[str, Any]:
        if self.path is None:
            return {"schema_version": "1.0", "sources": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": "1.0", "sources": {}}
        return (
            payload
            if isinstance(payload, dict)
            else {"schema_version": "1.0", "sources": {}}
        )

    def _write_index(self, payload: Mapping[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


@contextmanager
def _index_file_lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _default_seed_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "configs"
        / "equipment_deep_research"
        / "codex_skills"
        / "js-equipment-agent-runtime"
        / "references"
        / "source-priorities.json"
    )


def _terms(value: str) -> set[str]:
    normalized = "".join(
        character.lower() if character.isalnum() else " " for character in value
    )
    return {item for item in normalized.split() if len(item) >= 2}


def _overlap(left: set[str], right: set[str]) -> int:
    return len(left & right)


__all__ = ["SourcePriorityIndex"]
