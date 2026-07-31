"""File-backed declarative Champion/Challenger registry for benchmark evolution."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json

from equipment_deep_research.orchestration.execution_contracts import (
    optimized_v2_profile,
)
from .models import PAIRWISE_V1_DIMENSIONS, QueryResidual, read_jsonl, write_jsonl


ALLOWED_CHANGE_TYPES = frozenset(
    {"routing", "dependency", "prompt", "model_tier", "budget"}
)


class EvolutionRegistry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "profiles.json"
        if not self.path.exists():
            self._write(self._defaults())

    def snapshot(self) -> dict[str, Any]:
        payload = self._read()
        profiles = list(payload.get("profiles", []))
        return {
            "champion_profile_id": payload.get("champion_profile_id", "legacy_v1"),
            "profiles": sorted(profiles, key=lambda item: item.get("created_at", "")),
            "allowed_change_types": sorted(ALLOWED_CHANGE_TYPES),
            "promotion_policy": {
                "human_approval_required": True,
                "success_rate_minimum": 0.95,
                "claim_source_binding_minimum": 0.90,
                "pilot_p90_seconds_maximum": 900,
                "quality_gain_minimum": 0.05,
                "formal_test_training_forbidden": True,
            },
        }

    def create_challenger(
        self,
        *,
        profile_id: str,
        base_profile_id: str,
        hypothesis: str,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        if set(changes) - ALLOWED_CHANGE_TYPES:
            raise ValueError("challenger may only change routing/dependency/prompt/model_tier/budget")
        payload = self._read()
        if any(item.get("profile_id") == profile_id for item in payload["profiles"]):
            raise ValueError("profile_id already exists")
        if not any(item.get("profile_id") == base_profile_id for item in payload["profiles"]):
            raise ValueError("base profile does not exist")
        row = {
            "profile_id": profile_id,
            "base_profile_id": base_profile_id,
            "status": "challenger",
            "approved": False,
            "hypothesis": hypothesis,
            "changes": dict(changes),
            "source_code_change": False,
            "created_at": _now(),
        }
        row["config_hash"] = _hash(row)
        payload["profiles"].append(row)
        self._write(payload)
        return row

    def approve(self, profile_id: str, *, actor: str) -> dict[str, Any]:
        payload = self._read()
        row = _profile(payload, profile_id)
        if row.get("status") == "archived":
            raise ValueError("archived profile cannot be approved")
        row["approved"] = True
        row["approved_by"] = actor
        row["approved_at"] = _now()
        self._write(payload)
        return row

    def activate(self, profile_id: str, *, actor: str) -> dict[str, Any]:
        payload = self._read()
        row = _profile(payload, profile_id)
        if not row.get("approved"):
            raise ValueError("human approval is required before activation")
        previous = str(payload.get("champion_profile_id", "legacy_v1"))
        for item in payload["profiles"]:
            if item.get("profile_id") == previous and previous != profile_id:
                item["status"] = "archived"
        row["status"] = "champion"
        row["activated_by"] = actor
        row["activated_at"] = _now()
        payload["champion_profile_id"] = profile_id
        payload["previous_champion_profile_id"] = previous
        self._write(payload)
        return {"champion_profile_id": profile_id, "previous_champion_profile_id": previous}

    def rollback(self, *, actor: str) -> dict[str, Any]:
        payload = self._read()
        previous = str(payload.get("previous_champion_profile_id", ""))
        if not previous:
            raise ValueError("no previous champion is available")
        current = str(payload.get("champion_profile_id", ""))
        current_row = _profile(payload, current)
        previous_row = _profile(payload, previous)
        current_row["status"] = "archived"
        previous_row["status"] = "champion"
        previous_row["rollback_activated_by"] = actor
        previous_row["rollback_activated_at"] = _now()
        payload["champion_profile_id"] = previous
        payload["previous_champion_profile_id"] = current
        self._write(payload)
        return {"champion_profile_id": previous, "rolled_back_from": current}

    def _defaults(self) -> dict[str, Any]:
        optimized = optimized_v2_profile().to_dict()
        created_at = _now()
        return {
            "champion_profile_id": "legacy_v1",
            "previous_champion_profile_id": "",
            "profiles": [
                {
                    "profile_id": "legacy_v1",
                    "base_profile_id": "",
                    "status": "champion",
                    "approved": True,
                    "hypothesis": "production-compatible legacy behavior",
                    "changes": {},
                    "source_code_change": False,
                    "created_at": created_at,
                    "config_hash": "legacy-v1",
                },
                {
                    "profile_id": "optimized_v2",
                    "base_profile_id": "legacy_v1",
                    "status": "challenger",
                    "approved": False,
                    "hypothesis": "branch contracts, physical cohorts and residual-only backtracking improve quality per latency",
                    "changes": {
                        "routing": "A-H branch contracts",
                        "dependency": "hard barriers and physical cohorts",
                        "prompt": optimized["prompt_versions"],
                        "model_tier": optimized["model_tiers"],
                        "budget": optimized["budgets"],
                    },
                    "execution_profile": optimized,
                    "source_code_change": False,
                    "created_at": created_at,
                    "config_hash": optimized["config_hash"],
                },
            ],
        }

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def build_query_residuals(
    *,
    eval_id: str,
    eval_root: str | Path,
    queries_path: str | Path,
    baselines: list[str],
    execution_profile_id: str,
    exploratory_only: bool,
) -> list[QueryResidual]:
    root = Path(eval_root)
    queries = {str(row["query_id"]): row for row in read_jsonl(queries_path)}
    accumulators: dict[str, dict[str, Any]] = {}
    for baseline in baselines:
        mapping_path = root / "pairs" / baseline / "pairs.admin.jsonl"
        judgments_path = root / f"judgments.{baseline}.jsonl"
        if not mapping_path.is_file() or not judgments_path.is_file():
            continue
        mappings = {str(row["pair_id"]): row for row in read_jsonl(mapping_path)}
        for judgment in read_jsonl(judgments_path):
            mapping = mappings.get(str(judgment.get("pair_id", "")))
            if not mapping:
                continue
            query_id = str(mapping["query_id"])
            acc = accumulators.setdefault(
                query_id,
                {
                    "votes": {dimension: [0, 0, 0] for dimension in PAIRWISE_V1_DIMENSIONS},
                    "missing": [],
                    "citation": [],
                    "gate": [],
                    "failures": [],
                },
            )
            system_a = str(mapping["system_a"])
            system_b = str(mapping["system_b"])
            for dimension, winner in dict(judgment.get("dimensions", {})).items():
                if dimension not in PAIRWISE_V1_DIMENSIONS:
                    continue
                winning_system = system_a if winner == "A" else system_b if winner == "B" else "tie"
                slot = 0 if winning_system == "full_method" else 1 if winning_system == baseline else 2
                acc["votes"][dimension][slot] += 1
            route_check = judgment.get("route_deliverable_check", {})
            if isinstance(route_check, Mapping):
                for key, value in route_check.items():
                    if value in (False, "missing", "failed", 0):
                        acc["missing"].append(str(key))
            acc["citation"].extend(str(item) for item in judgment.get("citation_issues", []))
            acc["failures"].extend(str(item) for item in judgment.get("hard_failures", []))
            if judgment.get("adjudication_required"):
                acc["gate"].extend(str(item) for item in judgment.get("adjudication_reasons", []))
    residuals: list[QueryResidual] = []
    for query_id, acc in sorted(accumulators.items()):
        gaps = {}
        for dimension, (ours, baseline, ties) in acc["votes"].items():
            total = max(1, ours + baseline + ties)
            gaps[dimension] = round((baseline - ours) / total, 6)
        query = queries.get(query_id, {})
        residuals.append(
            QueryResidual(
                residual_id=f"residual-{eval_id}-{query_id}",
                eval_id=eval_id,
                query_id=query_id,
                execution_profile_id=execution_profile_id,
                split=str(query.get("split", "")),
                nine_dimension_gaps=gaps,
                missing_branch_products=sorted(set(acc["missing"])),
                citation_issues=sorted(set(acc["citation"])),
                gate_issues=sorted(set(acc["gate"])),
                failure_reasons=sorted(set(acc["failures"])),
                exploratory_only=exploratory_only or str(query.get("split")) == "test",
            )
        )
    write_jsonl(root / "query_residuals.jsonl", [item.to_dict() for item in residuals])
    return residuals


def _profile(payload: dict[str, Any], profile_id: str) -> dict[str, Any]:
    for item in payload.get("profiles", []):
        if item.get("profile_id") == profile_id:
            return item
    raise ValueError("profile does not exist")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["EvolutionRegistry", "ALLOWED_CHANGE_TYPES", "build_query_residuals"]
