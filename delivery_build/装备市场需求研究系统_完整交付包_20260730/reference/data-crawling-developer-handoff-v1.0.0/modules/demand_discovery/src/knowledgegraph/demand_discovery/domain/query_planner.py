"""Contracts for model-owned query planning in demand discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_RESEARCH_SCOPES = {"whitelist", "open_web_after_whitelist_exhausted"}


@dataclass(frozen=True)
class QueryVariant:
    text: str
    language: str
    intent: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("query text is required")
        if not self.language.strip():
            raise ValueError("query language is required")
        if not self.intent.strip():
            raise ValueError("query intent is required")

    def to_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "language": self.language,
            "intent": self.intent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueryVariant":
        _reject_unknown_fields(data, {"text", "language", "intent"}, "query")
        return cls(
            text=_required_str(data, "text", "query text"),
            language=_required_str(data, "language", "query language"),
            intent=_required_str(data, "intent", "query intent"),
        )


@dataclass(frozen=True)
class QueryBundle:
    queries: list[QueryVariant]

    def __post_init__(self) -> None:
        if not self.queries:
            raise ValueError("at least one query is required")

    def to_dict(self) -> dict[str, Any]:
        return {"queries": [item.to_dict() for item in self.queries]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueryBundle":
        _reject_unknown_fields(data, {"queries"}, "query_bundle")
        raw_queries = data.get("queries", [])
        if not isinstance(raw_queries, list):
            raise ValueError("query_bundle.queries must be a list")
        return cls(
            queries=[
                QueryVariant.from_dict(item)
                for item in _object_rows(raw_queries, "query_bundle.queries")
            ]
        )


@dataclass(frozen=True)
class ResearchDirection:
    direction_id: str
    goal: str
    query_bundle: QueryBundle

    def __post_init__(self) -> None:
        if not self.direction_id.strip():
            raise ValueError("direction_id is required")
        if not self.goal.strip():
            raise ValueError("direction goal is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction_id": self.direction_id,
            "goal": self.goal,
            "query_bundle": self.query_bundle.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchDirection":
        _reject_unknown_fields(
            data,
            {"direction_id", "goal", "query_bundle"},
            "research_direction",
        )
        query_bundle = data.get("query_bundle")
        if not isinstance(query_bundle, dict):
            raise ValueError("research_direction query_bundle is required")
        return cls(
            direction_id=_required_str(
                data,
                "direction_id",
                "direction_id",
            ),
            goal=_required_str(data, "goal", "direction goal"),
            query_bundle=QueryBundle.from_dict(query_bundle),
        )


@dataclass(frozen=True)
class WorkerAssignment:
    assignment_id: str
    direction_id: str
    source_names: list[str]
    query_bundle: QueryBundle
    brief: str
    allowed_scope: str
    round_id: str = ""

    def __post_init__(self) -> None:
        if not self.assignment_id.strip():
            raise ValueError("assignment_id is required")
        if not self.direction_id.strip():
            raise ValueError("assignment direction_id is required")
        if not self.brief.strip():
            raise ValueError("assignment brief is required")
        if self.allowed_scope not in ALLOWED_RESEARCH_SCOPES:
            allowed = ", ".join(sorted(ALLOWED_RESEARCH_SCOPES))
            raise ValueError(f"allowed_scope must be one of: {allowed}")

    def to_dict(self) -> dict[str, Any]:
        row = {
            "assignment_id": self.assignment_id,
            "direction_id": self.direction_id,
            "source_names": list(self.source_names),
            "query_bundle": self.query_bundle.to_dict(),
            "brief": self.brief,
            "allowed_scope": self.allowed_scope,
        }
        if self.round_id:
            row["round_id"] = self.round_id
        return row

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerAssignment":
        _reject_unknown_fields(
            data,
            {
                "assignment_id",
                "round_id",
                "direction_id",
                "source_names",
                "query_bundle",
                "brief",
                "allowed_scope",
            },
            "worker_assignment",
        )
        query_bundle = data.get("query_bundle")
        if not isinstance(query_bundle, dict):
            raise ValueError("worker_assignment query_bundle is required")
        return cls(
            assignment_id=_required_str(
                data,
                "assignment_id",
                "assignment_id",
            ),
            round_id=str(data.get("round_id", "")).strip(),
            direction_id=_required_str(
                data,
                "direction_id",
                "assignment direction_id",
            ),
            source_names=_string_list(data.get("source_names", []), "source_names"),
            query_bundle=QueryBundle.from_dict(query_bundle),
            brief=_required_str(data, "brief", "assignment brief"),
            allowed_scope=_required_str(data, "allowed_scope", "allowed_scope"),
        )


@dataclass(frozen=True)
class ResearchPlan:
    plan_id: str
    topic: str
    research_directions: list[ResearchDirection]
    worker_assignments: list[WorkerAssignment]
    round_id: str = ""
    planner_rationale: str = ""

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id is required")
        if not self.research_directions:
            raise ValueError("at least one research_direction is required")
        if not self.worker_assignments:
            raise ValueError("at least one worker_assignment is required")
        direction_ids = {item.direction_id for item in self.research_directions}
        for assignment in self.worker_assignments:
            if assignment.direction_id not in direction_ids:
                raise ValueError(
                    f"unknown direction_id for worker_assignment "
                    f"{assignment.assignment_id}: {assignment.direction_id}"
                )

    def to_dict(self) -> dict[str, Any]:
        row = {
            "plan_id": self.plan_id,
            "topic": self.topic,
            "research_directions": [
                item.to_dict() for item in self.research_directions
            ],
            "worker_assignments": [
                item.to_dict() for item in self.worker_assignments
            ],
            "planner_rationale": self.planner_rationale,
        }
        if self.round_id:
            row["round_id"] = self.round_id
        return row

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchPlan":
        return validate_research_plan(data)


def validate_research_plan(data: dict[str, Any]) -> ResearchPlan:
    _reject_unknown_fields(
        data,
        {
            "plan_id",
            "topic",
            "round_id",
            "research_directions",
            "worker_assignments",
            "planner_rationale",
        },
        "research_plan",
    )
    directions_raw = data.get("research_directions", [])
    assignments_raw = data.get("worker_assignments", [])
    if not isinstance(directions_raw, list):
        raise ValueError("research_directions must be a list")
    if not isinstance(assignments_raw, list):
        raise ValueError("worker_assignments must be a list")
    plan_id = _required_str(data, "plan_id", "plan_id")
    if not directions_raw:
        raise ValueError("at least one research_direction is required")
    if not assignments_raw:
        raise ValueError("at least one worker_assignment is required")
    return ResearchPlan(
        plan_id=plan_id,
        topic=str(data.get("topic", "")).strip(),
        round_id=str(data.get("round_id", "")).strip(),
        research_directions=[
            ResearchDirection.from_dict(item)
            for item in _object_rows(directions_raw, "research_directions")
        ],
        worker_assignments=[
            WorkerAssignment.from_dict(item)
            for item in _object_rows(assignments_raw, "worker_assignments")
        ],
        planner_rationale=str(data.get("planner_rationale", "")).strip(),
    )


def _required_str(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _object_rows(rows: list[Any], label: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        objects.append(item)
    return objects


def _reject_unknown_fields(
    data: dict[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise ValueError(f"{label} has unknown field(s): {', '.join(extra)}")
