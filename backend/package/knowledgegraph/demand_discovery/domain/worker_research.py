"""Worker self-check and follow-up state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


TopicAlignment = Literal["direct", "partial", "adjacent", "weak"]

VALID_TOPIC_ALIGNMENTS = {"direct", "partial", "adjacent", "weak"}
VALID_FOLLOW_UP_REASONS = {
    "",
    "body_evidence_missing",
    "direct_evidence_missing",
    "topic_alignment_weak",
    "strong_finding_unreferenced",
    "unverified_claims_remaining",
    "listing_or_search_only",
    "no_new_body_artifact",
    "budget_exhausted",
    "source_blocked",
    "needs_cross_source_or_open_search",
}


@dataclass
class WorkerSelfCheck(SerializableDataclass):
    check_id: str
    assignment_id: str
    round_id: str
    topic_alignment: TopicAlignment
    body_evidence_count: int
    direct_evidence_count: int
    partial_evidence_count: int
    adjacent_evidence_count: int
    source_diversity: int
    article_body_read_count: int
    downloaded_document_read_count: int
    listing_or_search_only_count: int
    queries_used: list[str] = field(default_factory=list)
    routes_used: list[str] = field(default_factory=list)
    browser_actions_used: list[str] = field(default_factory=list)
    javascript_actions_used: list[str] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)
    discarded_findings: list[str] = field(default_factory=list)
    contradiction_candidates: list[str] = field(default_factory=list)
    follow_up_required: bool = False
    follow_up_reason: str = ""
    follow_up_actions_taken: list[str] = field(default_factory=list)
    remaining_blind_spots: list[str] = field(default_factory=list)
    allowed_to_finish: bool = False

    def __post_init__(self) -> None:
        if self.topic_alignment not in VALID_TOPIC_ALIGNMENTS:
            raise ValueError(f"unknown topic_alignment: {self.topic_alignment}")
        if self.follow_up_reason not in VALID_FOLLOW_UP_REASONS:
            raise ValueError(f"unknown follow_up_reason: {self.follow_up_reason}")


@dataclass
class FollowUpInstruction(SerializableDataclass):
    instruction_id: str
    assignment_id: str
    round_id: str
    trigger_check_id: str
    reason: str
    allowed_tools: list[str]
    target_source_id: str = ""
    query_revisions: list[dict[str, str]] = field(default_factory=list)
    route_revisions: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    stop_after: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason not in VALID_FOLLOW_UP_REASONS - {""}:
            raise ValueError(f"unknown follow_up reason: {self.reason}")
        if not self.allowed_tools:
            raise ValueError("FollowUpInstruction requires allowed_tools")

    def to_prompt(self) -> str:
        queries = "\n".join(
            f"- {item.get('language', 'auto')}: {item.get('query', '')}"
            for item in self.query_revisions
        )
        routes = "\n".join(f"- {item}" for item in self.route_revisions)
        outputs = "\n".join(f"- {item}" for item in self.expected_outputs)
        return (
            f"Worker self-check failed: {self.reason}\n"
            f"Assignment: {self.assignment_id}\n"
            f"Target source: {self.target_source_id}\n"
            f"Allowed tools: {', '.join(self.allowed_tools)}\n"
            f"Query revisions:\n{queries}\n"
            f"Route revisions:\n{routes}\n"
            f"Expected outputs:\n{outputs}\n"
            "Continue researching with your own choice of query, route, browser, "
            "JavaScript, download, or blocked-source judgement. Do not create "
            "strong evidence from listing/search/home pages. If evidence remains "
            "insufficient, explain remaining blind spots."
        )


def evaluate_worker_self_check(
    *,
    assignment_id: str,
    round_id: str,
    topic_alignment: TopicAlignment,
    body_evidence_count: int,
    direct_evidence_count: int,
    partial_evidence_count: int,
    adjacent_evidence_count: int,
    article_body_read_count: int,
    downloaded_document_read_count: int,
    listing_or_search_only_count: int,
    unverified_claims: list[str],
    strong_finding_count: int,
    strong_finding_evidence_ref_count: int,
    queries_used: list[str],
    routes_used: list[str],
    source_diversity: int = 1,
    browser_actions_used: list[str] | None = None,
    javascript_actions_used: list[str] | None = None,
    discarded_findings: list[str] | None = None,
    contradiction_candidates: list[str] | None = None,
) -> WorkerSelfCheck:
    reason = ""
    blind_spots: list[str] = []

    if body_evidence_count <= 0:
        reason = "body_evidence_missing"
        blind_spots.append("只读取到 listing/search/home 页面")
    elif topic_alignment == "weak":
        reason = "topic_alignment_weak"
    elif strong_finding_count > strong_finding_evidence_ref_count:
        reason = "strong_finding_unreferenced"
    elif direct_evidence_count <= 0 and partial_evidence_count < 2:
        reason = "direct_evidence_missing"
    elif unverified_claims:
        reason = "unverified_claims_remaining"

    blind_spots.extend(unverified_claims)
    allowed = reason == ""
    return WorkerSelfCheck(
        check_id=f"selfcheck-{uuid4().hex}",
        assignment_id=assignment_id,
        round_id=round_id,
        topic_alignment=topic_alignment,
        body_evidence_count=body_evidence_count,
        direct_evidence_count=direct_evidence_count,
        partial_evidence_count=partial_evidence_count,
        adjacent_evidence_count=adjacent_evidence_count,
        source_diversity=source_diversity,
        article_body_read_count=article_body_read_count,
        downloaded_document_read_count=downloaded_document_read_count,
        listing_or_search_only_count=listing_or_search_only_count,
        queries_used=list(queries_used),
        routes_used=list(routes_used),
        browser_actions_used=list(browser_actions_used or []),
        javascript_actions_used=list(javascript_actions_used or []),
        unverified_claims=list(unverified_claims),
        discarded_findings=list(discarded_findings or []),
        contradiction_candidates=list(contradiction_candidates or []),
        follow_up_required=not allowed,
        follow_up_reason=reason,
        follow_up_actions_taken=[],
        remaining_blind_spots=blind_spots,
        allowed_to_finish=allowed,
    )


def worker_self_check_from_dict(data: dict[str, Any]) -> WorkerSelfCheck:
    return WorkerSelfCheck(
        check_id=str(data["check_id"]),
        assignment_id=str(data.get("assignment_id", "")),
        round_id=str(data.get("round_id", "")),
        topic_alignment=str(data.get("topic_alignment", "weak")),  # type: ignore[arg-type]
        body_evidence_count=int(data.get("body_evidence_count", 0)),
        direct_evidence_count=int(data.get("direct_evidence_count", 0)),
        partial_evidence_count=int(data.get("partial_evidence_count", 0)),
        adjacent_evidence_count=int(data.get("adjacent_evidence_count", 0)),
        source_diversity=int(data.get("source_diversity", 0)),
        article_body_read_count=int(data.get("article_body_read_count", 0)),
        downloaded_document_read_count=int(
            data.get("downloaded_document_read_count", 0)
        ),
        listing_or_search_only_count=int(data.get("listing_or_search_only_count", 0)),
        queries_used=[str(item) for item in data.get("queries_used", [])],
        routes_used=[str(item) for item in data.get("routes_used", [])],
        browser_actions_used=[
            str(item) for item in data.get("browser_actions_used", [])
        ],
        javascript_actions_used=[
            str(item) for item in data.get("javascript_actions_used", [])
        ],
        unverified_claims=[str(item) for item in data.get("unverified_claims", [])],
        discarded_findings=[
            str(item) for item in data.get("discarded_findings", [])
        ],
        contradiction_candidates=[
            str(item) for item in data.get("contradiction_candidates", [])
        ],
        follow_up_required=bool(data.get("follow_up_required", False)),
        follow_up_reason=str(data.get("follow_up_reason", "")),
        follow_up_actions_taken=[
            str(item) for item in data.get("follow_up_actions_taken", [])
        ],
        remaining_blind_spots=[
            str(item) for item in data.get("remaining_blind_spots", [])
        ],
        allowed_to_finish=bool(data.get("allowed_to_finish", False)),
    )


def follow_up_instruction_from_dict(data: dict[str, Any]) -> FollowUpInstruction:
    return FollowUpInstruction(
        instruction_id=str(data["instruction_id"]),
        assignment_id=str(data.get("assignment_id", "")),
        round_id=str(data.get("round_id", "")),
        trigger_check_id=str(data.get("trigger_check_id", "")),
        reason=str(data.get("reason", "")),
        allowed_tools=[str(item) for item in data.get("allowed_tools", [])],
        target_source_id=str(data.get("target_source_id", "")),
        query_revisions=[dict(item) for item in data.get("query_revisions", [])],
        route_revisions=[str(item) for item in data.get("route_revisions", [])],
        expected_outputs=[str(item) for item in data.get("expected_outputs", [])],
        stop_after={
            str(key): int(value)
            for key, value in dict(data.get("stop_after", {})).items()
        },
    )
