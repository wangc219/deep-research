"""Candidate demand lifecycle state machine."""

from __future__ import annotations


STATUSES = {
    "raw_signal",
    "researchable_signal",
    "weak_signal",
    "discarded_signal",
    "candidate_demand",
    "demand_report",
    "human_reviewed",
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "raw_signal": {
        "researchable_signal",
        "weak_signal",
        "discarded_signal",
        "candidate_demand",
    },
    "researchable_signal": {
        "candidate_demand",
        "weak_signal",
        "discarded_signal",
    },
    "weak_signal": {"researchable_signal", "discarded_signal"},
    "candidate_demand": {
        "demand_report",
        "researchable_signal",
        "weak_signal",
        "discarded_signal",
    },
    "demand_report": {"human_reviewed", "candidate_demand"},
    "discarded_signal": set(),
    "human_reviewed": set(),
}

_STATUS_RANK = {
    "raw_signal": 0,
    "weak_signal": 1,
    "discarded_signal": 1,
    "researchable_signal": 2,
    "candidate_demand": 3,
    "demand_report": 4,
    "human_reviewed": 5,
}


class InvalidTransition(ValueError):
    """Raised when a candidate status transition is not allowed."""


def validate_status(status: str) -> None:
    if status not in STATUSES:
        raise InvalidTransition(f"unknown candidate status: {status}")


def validate_transition(old: str, new: str) -> None:
    validate_status(old)
    validate_status(new)
    if old == new:
        return
    if new not in ALLOWED_TRANSITIONS[old]:
        raise InvalidTransition(f"illegal candidate status transition: {old} -> {new}")


def validate_status_cap(status: str, cap: str) -> None:
    validate_status(status)
    validate_status(cap)
    if _STATUS_RANK[status] > _STATUS_RANK[cap]:
        raise ValueError(f"candidate status {status!r} exceeds source tier cap {cap!r}")


def status_rank(status: str) -> int:
    validate_status(status)
    return _STATUS_RANK[status]
