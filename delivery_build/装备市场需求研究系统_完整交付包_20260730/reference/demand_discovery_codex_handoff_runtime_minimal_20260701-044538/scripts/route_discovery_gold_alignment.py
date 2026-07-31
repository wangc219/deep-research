"""Manual gold-alignment helpers for route-discovery evaluation.

This module is evaluation-only. It must not be imported by candidate
generation, extraction, or route assembly scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_GOLD_ALIGNMENT = Path("data/benchmarks/route_discovery/gold_alignment_v0.jsonl")
REQUIRED_STATUS = "manual_reviewed"
SUPPORTED_TARGET_TYPES = {"endpoint_alias", "route_pattern_variant", "stage_policy"}


@dataclass(frozen=True)
class GoldAlignment:
    records: tuple[dict[str, Any], ...]
    endpoint_aliases: dict[tuple[str, str], tuple[str, ...]]
    route_variants: dict[tuple[str, str], tuple[dict[str, Any], ...]]
    stage_policies: dict[tuple[str, str], tuple[dict[str, Any], ...]]

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> "GoldAlignment":
        endpoint_aliases: dict[tuple[str, str], list[str]] = {}
        route_variants: dict[tuple[str, str], list[dict[str, Any]]] = {}
        stage_policies: dict[tuple[str, str], list[dict[str, Any]]] = {}
        cleaned_records: list[dict[str, Any]] = []
        for record in records:
            _validate_record(record)
            item = dict(record)
            cleaned_records.append(item)
            case_id = str(item["case_id"])
            target_type = str(item["target_type"])
            if target_type == "endpoint_alias":
                key = (case_id, str(item["slot_name"]))
                endpoint_aliases.setdefault(key, []).extend(str(alias) for alias in item["accepted_aliases"])
            elif target_type == "route_pattern_variant":
                key = (case_id, str(item["target_ref"]))
                route_variants.setdefault(key, []).append(item)
            elif target_type == "stage_policy":
                key = (case_id, str(item["target_ref"]))
                stage_policies.setdefault(key, []).append(item)
        return cls(
            records=tuple(cleaned_records),
            endpoint_aliases={
                key: tuple(_dedupe_nonempty(values))
                for key, values in endpoint_aliases.items()
            },
            route_variants={
                key: tuple(values)
                for key, values in route_variants.items()
            },
            stage_policies={
                key: tuple(values)
                for key, values in stage_policies.items()
            },
        )

    def aliases_for_slot(self, case_id: str, slot_name: str) -> list[str]:
        return list(self.endpoint_aliases.get((str(case_id), str(slot_name)), ()))

    def variants_for_route(self, case_id: str, route_id: str) -> list[dict[str, Any]]:
        return list(self.route_variants.get((str(case_id), str(route_id)), ()))

    def policies_for_edge(self, case_id: str, edge_id: str) -> list[dict[str, Any]]:
        return list(self.stage_policies.get((str(case_id), str(edge_id)), ()))


def load_gold_alignment(path: Path = DEFAULT_GOLD_ALIGNMENT) -> GoldAlignment:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return GoldAlignment.from_records(records)


def load_gold_alignment_if_exists(path: Path = DEFAULT_GOLD_ALIGNMENT) -> GoldAlignment | None:
    if not path.exists():
        return None
    return load_gold_alignment(path)


def _validate_record(record: dict[str, Any]) -> None:
    for field in ("alignment_id", "case_id", "target_type", "rationale", "status"):
        if not str(record.get(field, "")).strip():
            raise ValueError(f"Gold alignment record is missing {field}: {record!r}")
    if str(record["status"]) != REQUIRED_STATUS:
        raise ValueError(
            "Gold alignment records must be manually reviewed before use: "
            f"{record.get('alignment_id', '<unknown>')}"
        )
    target_type = str(record["target_type"])
    if target_type not in SUPPORTED_TARGET_TYPES:
        raise ValueError(f"Unsupported gold alignment target_type: {target_type}")
    if target_type == "endpoint_alias":
        if not str(record.get("slot_name", "")).strip():
            raise ValueError(f"Endpoint alias record is missing slot_name: {record!r}")
        aliases = record.get("accepted_aliases", [])
        if not isinstance(aliases, list) or not _dedupe_nonempty([str(alias) for alias in aliases]):
            raise ValueError(f"Endpoint alias record must include accepted_aliases: {record!r}")
    if target_type == "route_pattern_variant":
        if not str(record.get("target_ref", "")).strip():
            raise ValueError(f"Route variant record is missing target_ref: {record!r}")
        edge_refs = record.get("required_gold_edge_refs", [])
        if not isinstance(edge_refs, list) or not _dedupe_nonempty([str(edge) for edge in edge_refs]):
            raise ValueError(f"Route variant record must include required_gold_edge_refs: {record!r}")
    if target_type == "stage_policy" and not str(record.get("target_ref", "")).strip():
        raise ValueError(f"Stage policy record is missing target_ref: {record!r}")


def _dedupe_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result
