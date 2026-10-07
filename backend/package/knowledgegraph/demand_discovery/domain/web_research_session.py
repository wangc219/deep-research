"""Worker-local web research working memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


WEB_RESEARCH_SESSION_STATUSES = {"running", "blocked", "completed"}


@dataclass
class WebResearchSession(SerializableDataclass):
    """Compact, worker-local state for one continuous research assignment."""

    session_id: str
    assignment_id: str
    round_id: str
    runtime_ref: str
    topic_snapshot: str
    status: str
    active_acceptance_criteria: list[str] = field(default_factory=list)
    allowed_source_refs: list[str] = field(default_factory=list)
    recent_refs: list[dict[str, Any]] = field(default_factory=list)
    compact_summaries: list[str] = field(default_factory=list)
    attempted_routes: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    last_self_check_ref: str = ""
    follow_up_refs: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in WEB_RESEARCH_SESSION_STATUSES:
            raise ValueError(f"unknown WebResearchSession status: {self.status}")
        for item in self.recent_refs:
            if not item.get("type") or not item.get("id"):
                raise ValueError("recent_refs item requires type and id")
            _reject_full_body(item.get("summary"))
            _reject_full_body(item.get("text"))
            _reject_full_body(item.get("html"))
        for summary in self.compact_summaries:
            _reject_full_body(summary)
        for route in self.attempted_routes:
            _reject_full_body(route.get("summary"))
            _reject_full_body(route.get("html"))
            _reject_full_body(route.get("text"))


def web_research_session_from_dict(data: dict[str, Any]) -> WebResearchSession:
    return WebResearchSession(
        session_id=str(data["session_id"]),
        assignment_id=str(data.get("assignment_id", "")),
        round_id=str(data.get("round_id", "")),
        runtime_ref=str(data.get("runtime_ref", "")),
        topic_snapshot=str(data.get("topic_snapshot", "")),
        status=str(data.get("status", "running")),
        active_acceptance_criteria=[
            str(item) for item in data.get("active_acceptance_criteria", [])
        ],
        allowed_source_refs=[str(item) for item in data.get("allowed_source_refs", [])],
        recent_refs=[dict(item) for item in data.get("recent_refs", [])],
        compact_summaries=[str(item) for item in data.get("compact_summaries", [])],
        attempted_routes=[dict(item) for item in data.get("attempted_routes", [])],
        open_questions=[str(item) for item in data.get("open_questions", [])],
        last_self_check_ref=str(data.get("last_self_check_ref", "")),
        follow_up_refs=[str(item) for item in data.get("follow_up_refs", [])],
        blocked_reasons=[str(item) for item in data.get("blocked_reasons", [])],
    )


def _reject_full_body(value: Any) -> None:
    if not isinstance(value, str):
        return
    lower = value.lower()
    if "<html" in lower or "<body" in lower or "</html" in lower:
        raise ValueError("WebResearchSession must not store full HTML or body text")
    if len(value) > 2000:
        raise ValueError("WebResearchSession compact text is too long")
