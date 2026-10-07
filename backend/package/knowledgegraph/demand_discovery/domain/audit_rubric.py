"""Structured audit rubric loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RubricItem:
    id: str
    question: str


@dataclass(frozen=True)
class AuditRubric:
    version: int
    veto_items: list[RubricItem]
    check_items: list[RubricItem]

    @property
    def item_ids(self) -> list[str]:
        return [item.id for item in [*self.veto_items, *self.check_items]]

    @property
    def veto_ids(self) -> set[str]:
        return {item.id for item in self.veto_items}


def load_rubric(path: str | Path) -> AuditRubric:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return rubric_from_dict(data)


def load_default_rubric() -> AuditRubric:
    repo_root = Path(__file__).resolve().parents[4]
    return load_rubric(repo_root / "configs" / "demand_discovery" / "audit_rubric.json")


def rubric_from_dict(data: dict[str, Any]) -> AuditRubric:
    return AuditRubric(
        version=int(data.get("version", 1)),
        veto_items=[
            RubricItem(id=str(item["id"]), question=str(item.get("question", "")))
            for item in data.get("veto_items", [])
        ],
        check_items=[
            RubricItem(id=str(item["id"]), question=str(item.get("question", "")))
            for item in data.get("check_items", [])
        ],
    )


def validate_scorecard(
    rubric: AuditRubric,
    scorecard: dict[str, Any],
    conclusion: str,
) -> str:
    for item_id in rubric.item_ids:
        if item_id not in scorecard:
            raise ValueError(f"missing rubric scorecard item: {item_id}")
        row = scorecard[item_id]
        if not isinstance(row, dict):
            raise ValueError(f"rubric scorecard item must be object: {item_id}")
        verdict = str(row.get("verdict", "")).strip().lower()
        if verdict not in {"pass", "doubt", "fail"}:
            raise ValueError(f"invalid rubric verdict for {item_id}: {verdict}")
        if not str(row.get("reason", "")).strip():
            raise ValueError(f"missing rubric reason for {item_id}")

    for item_id in rubric.veto_ids:
        row = scorecard[item_id]
        if str(row.get("verdict", "")).strip().lower() == "fail":
            return "rejected"
    return conclusion


load_rubric.from_dict = rubric_from_dict  # type: ignore[attr-defined]
