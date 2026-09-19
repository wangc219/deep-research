"""Versioned, evidence-safe incremental memory for business research agents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any, Iterator

from equipment_deep_research.domain.models import (
    BaselineFindingPacket,
    EvidenceCard,
    now_iso,
)
from equipment_deep_research.harness.context import (
    sanitize_handoff_summary,
    sanitize_handoff_value,
)


_INDEX_LOCK = RLock()


AGENT_MEMORY_FIELDS: dict[str, tuple[str, ...]] = {
    "international_situation": (
        "situation_assessment",
        "threat_assessment",
        "opponent_moves",
        "warning_indicators",
        "alternative_hypotheses",
        "scenario_drivers",
    ),
    "opponent_monitoring": (
        "change_baseline",
        "observed_moves",
        "formation_timeline",
        "warning_indicators",
    ),
    "combat_scenario": (
        "scenario_framework",
        "critical_timeline",
        "environment_constraints",
        "scenario_branches",
        "capability_pressure_points",
    ),
    "weapon_equipment": (
        "foreign_equipment_landscape",
        "equipment_profiles",
        "parameter_observations",
        "development_models",
        "technology_readiness",
        "system_dependencies",
        "capability_constraints",
    ),
    "system_confrontation": (
        "system_boundaries",
        "dependency_graph",
        "cascading_failures",
        "critical_vulnerabilities",
        "alternative_configs",
    ),
    "operational_employment": (
        "operational_constraints",
        "mission_chain",
        "force_coordination",
        "coa",
        "sustainment_resilience",
        "failure_modes",
        "lessons",
    ),
}


class AgentKnowledgeIndex:
    """Persist compact prior-run packets as navigation memory, never as evidence.

    Every recommendation explicitly carries a revalidation requirement.  The
    model may use it to narrow queries or detect deltas, but current-run claims
    still have to cite newly materialized EvidenceCards.
    """

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None

    def recommend(
        self,
        agent_id: str,
        topic: str,
        *,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        if self.path is None or limit < 1:
            return []
        with _INDEX_LOCK, _index_file_lock(self.path, exclusive=False):
            records = self._load().get("records", {})
        topic_terms = _terms(topic)
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for raw in records.values():
            if not isinstance(raw, Mapping) or raw.get("agent_id") != agent_id:
                continue
            relevance = _overlap(topic_terms, set(raw.get("topic_terms", [])))
            if topic_terms and relevance == 0:
                continue
            confidence = float(raw.get("confidence", 0.0) or 0.0)
            score = relevance * 20 + int(confidence * 10)
            candidates.append((score, str(raw.get("last_verified_at", "")), dict(raw)))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result: list[dict[str, Any]] = []
        for _, _, row in candidates[:limit]:
            last_verified = str(row.get("last_verified_at", ""))
            result.append(
                {
                    "memory_id": str(row.get("memory_id", "")),
                    "agent_id": agent_id,
                    "topic": str(row.get("topic", "")),
                    "handoff_summary": sanitize_handoff_summary(
                        row.get("handoff_summary", "")
                    ),
                    "payload_type": str(row.get("payload_type", "")),
                    "payload_projection": sanitize_handoff_value(
                        dict(row.get("payload_projection", {}))
                    ),
                    "source_urls": list(row.get("source_urls", []))[:12],
                    "confidence": float(row.get("confidence", 0.0) or 0.0),
                    "last_verified_at": last_verified,
                    "age_days": _age_days(last_verified),
                    "factual_authority": "contextual_only",
                    "revalidation_required": True,
                }
            )
        return result

    def record(
        self,
        *,
        packet: BaselineFindingPacket,
        evidence: Sequence[EvidenceCard],
    ) -> None:
        if self.path is None or packet.agent_id not in AGENT_MEMORY_FIELDS:
            return
        source_urls = list(
            dict.fromkeys(
                item.source_url
                for item in evidence
                if item.evidence_id in packet.evidence_ids
                and item.source_url.startswith("https://")
            )
        )
        projection = {
            field: packet.payload.get(field)
            for field in AGENT_MEMORY_FIELDS[packet.agent_id]
            if packet.payload.get(field) not in (None, "", [], {})
        }
        fingerprint_source = json.dumps(
            {
                "agent_id": packet.agent_id,
                "topic": packet.topic_focus,
                "payload": projection,
                "source_urls": source_urls,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = sha256(fingerprint_source.encode("utf-8")).hexdigest()
        memory_id = f"memory-{packet.agent_id}-{fingerprint[:16]}"
        row = {
            "memory_id": memory_id,
            "agent_id": packet.agent_id,
            "topic": packet.topic_focus,
            "topic_terms": sorted(_terms(packet.topic_focus)),
            "handoff_summary": sanitize_handoff_summary(
                packet.handoff_summary,
                fallback=(packet.findings[0] if packet.findings else ""),
            )[:1200],
            "payload_type": packet.payload_type,
            "payload_projection": sanitize_handoff_value(projection),
            "source_urls": source_urls,
            "confidence": packet.confidence,
            "last_verified_at": now_iso(),
            "fingerprint": fingerprint,
            "schema_version": "1.0",
        }
        with _INDEX_LOCK, _index_file_lock(self.path, exclusive=True):
            payload = self._load()
            records = payload.setdefault("records", {})
            records[memory_id] = row
            maximum = max(
                20,
                int(os.environ.get("EQUIPMENT_DR_AGENT_KNOWLEDGE_MAX_RECORDS", "300")),
            )
            ordered = sorted(
                records.values(),
                key=lambda item: str(item.get("last_verified_at", "")),
                reverse=True,
            )[:maximum]
            payload["records"] = {
                str(item["memory_id"]): item
                for item in ordered
                if item.get("memory_id")
            }
            payload["schema_version"] = "1.0"
            payload["updated_at"] = now_iso()
            self._write(payload)

    def _load(self) -> dict[str, Any]:
        if self.path is None:
            return {"schema_version": "1.0", "records": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": "1.0", "records": {}}
        return (
            payload
            if isinstance(payload, dict)
            else {"schema_version": "1.0", "records": {}}
        )

    def _write(self, payload: Mapping[str, Any]) -> None:
        assert self.path is not None
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
    """Serialize read-modify-write cycles across CLI/worker processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _terms(value: str) -> set[str]:
    normalized = "".join(
        character.lower() if character.isalnum() else " " for character in value
    )
    return {item for item in normalized.split() if len(item) >= 2}


def _overlap(left: set[str], right: set[str]) -> int:
    return len(left & right)


def _age_days(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - parsed).days)


__all__ = ["AGENT_MEMORY_FIELDS", "AgentKnowledgeIndex"]
