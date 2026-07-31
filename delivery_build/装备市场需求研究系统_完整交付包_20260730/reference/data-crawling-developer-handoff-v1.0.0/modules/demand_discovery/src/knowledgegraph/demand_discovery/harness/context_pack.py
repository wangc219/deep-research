"""Context pack builder and trace compaction projection.

``ContextPack`` is the model-facing view of current run state. It intentionally
summarizes domain objects instead of copying full store records, and represents
large documents by artifact references plus short excerpts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
import json
from typing import Any


@dataclass
class ContextPack:
    """A role-specific, token-budgeted context snapshot."""

    agent_role: str
    task_brief: str
    sections: dict[str, Any]
    token_budget: int
    estimated_tokens: int = 0

    def render(self) -> str:
        return json.dumps(
            {
                "agent_role": self.agent_role,
                "task_brief": self.task_brief,
                "sections": self.sections,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_role": self.agent_role,
            "task_brief": self.task_brief,
            "sections": dict(self.sections),
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
        }


@dataclass
class ContextSummary:
    """Compacted trace segment summary for future context rebuilds."""

    evidence_ids: list[str] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    excluded_directions: list[str] = field(default_factory=list)
    summary_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_ids": list(self.evidence_ids),
            "candidate_ids": list(self.candidate_ids),
            "open_questions": list(self.open_questions),
            "excluded_directions": list(self.excluded_directions),
            "summary_text": self.summary_text,
        }


class ContextPackBuilder:
    """Build role-specific projections from current run state."""

    def build(
        self,
        agent_role: str,
        task_brief: str,
        run_state: dict[str, Any],
        token_budget: int,
    ) -> ContextPack:
        sections: dict[str, Any] = {
            "task": {"brief": task_brief},
        }

        sources = self._summarize_sources(run_state.get("sources", []))
        evidence = self._summarize_evidence(run_state.get("evidence", []))
        candidates = self._summarize_candidates(run_state.get("candidates", []))
        documents = self._summarize_documents(run_state.get("documents", []))
        research_state = self._summarize_research_state(run_state)
        trace_summary = self.compact_trace_segment(
            list(run_state.get("trace_events", []) or []),
            policy={},
        )
        worker_self_checks = self._summarize_worker_self_checks(
            list(run_state.get("worker_self_checks", []) or [])
        )
        follow_up_instructions = self._summarize_follow_up_instructions(
            list(run_state.get("follow_up_instructions", []) or [])
        )

        if agent_role == "horizon_scanner":
            sections["sources"] = sources
            sections["excluded_directions"] = list(
                run_state.get("excluded_directions", [])
            )
        elif agent_role == "reading_worker":
            sections["sources"] = sources
            sections["documents"] = documents
            sections["research_state"] = research_state
            sections["evidence_index"] = evidence
            sections["trace_summary"] = trace_summary.to_dict()
            if worker_self_checks:
                sections["worker_self_checks"] = worker_self_checks
            if follow_up_instructions:
                sections["worker_follow_up_instructions"] = follow_up_instructions
        elif agent_role == "audit_worker":
            sections["candidate_index"] = candidates
            sections["evidence_index"] = evidence
            sections["research_state"] = research_state
            sections["trace_summary"] = trace_summary.to_dict()
            if worker_self_checks:
                sections["worker_self_checks"] = worker_self_checks
            if follow_up_instructions:
                sections["worker_follow_up_instructions"] = follow_up_instructions
            sections["open_questions"] = list(run_state.get("open_questions", []))
            sections["excluded_directions"] = list(
                run_state.get("excluded_directions", [])
            )
            if "audit_scorecard" in run_state:
                sections["audit_scorecard"] = dict(run_state["audit_scorecard"])
        else:
            sections["sources"] = sources
            sections["documents"] = documents
            sections["candidate_index"] = candidates
            sections["evidence_index"] = evidence
            sections["research_state"] = research_state
            sections["trace_summary"] = trace_summary.to_dict()
            if worker_self_checks:
                sections["worker_self_checks"] = worker_self_checks
            if follow_up_instructions:
                sections["worker_follow_up_instructions"] = follow_up_instructions
            sections["open_questions"] = list(run_state.get("open_questions", []))
            sections["excluded_directions"] = list(
                run_state.get("excluded_directions", [])
            )

        pack = ContextPack(
            agent_role=agent_role,
            task_brief=task_brief,
            sections=sections,
            token_budget=token_budget,
        )
        pack.estimated_tokens = self._estimate_tokens(pack.render())
        return pack

    def compact_trace_segment(
        self,
        events: list[Any],
        policy: dict[str, Any],
    ) -> ContextSummary:
        evidence_ids: list[str] = []
        candidate_ids: list[str] = []
        open_questions: list[str] = []
        excluded_directions: list[str] = []
        summaries: list[str] = []

        for event in events:
            target_type = str(_get(event, "target_type", ""))
            target_id = str(_get(event, "target_id", ""))
            output_refs = list(_get(event, "output_refs", []) or [])
            payload = dict(_get(event, "payload", {}) or {})
            summary = str(_get(event, "summary", "") or "")
            if summary:
                summaries.append(summary)

            if target_type == "EvidenceCard" and target_id:
                _append_unique(evidence_ids, target_id)
            if target_type == "CandidateDemand" and target_id:
                _append_unique(candidate_ids, target_id)
            for ref in output_refs:
                if str(ref).startswith("ev-"):
                    _append_unique(evidence_ids, str(ref))
                if str(ref).startswith("cand-"):
                    _append_unique(candidate_ids, str(ref))

            for question in payload.get("open_questions", []):
                _append_unique(open_questions, str(question))
            for direction in payload.get("excluded_directions", []):
                _append_unique(excluded_directions, str(direction))

        max_summary_chars = int(policy.get("max_summary_chars", 600))
        summary_text = "; ".join(summaries)[:max_summary_chars]
        return ContextSummary(
            evidence_ids=evidence_ids,
            candidate_ids=candidate_ids,
            open_questions=open_questions,
            excluded_directions=excluded_directions,
            summary_text=summary_text,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return ceil(len(text) / 4)

    @staticmethod
    def _summarize_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source.get("source_id", ""),
                "title": source.get("title", ""),
                "source_tier": source.get("source_tier", ""),
                "summary": source.get("summary_text", ""),
            }
            for source in sources
        ]

    @staticmethod
    def _summarize_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "evidence_id": card.get("evidence_id", ""),
                "source_id": card.get("source_id", ""),
                "claim": card.get("claim", ""),
                "summary": card.get("evidence_summary", ""),
                "excerpt": _excerpt(str(card.get("excerpt", "")), 220),
            }
            for card in evidence
        ]

    @staticmethod
    def _summarize_candidates(
        candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "candidate_id": candidate.get("candidate_id", ""),
                "title": candidate.get("title", ""),
                "demand_statement": candidate.get("demand_statement", ""),
                "status": candidate.get("status", ""),
                "evidence_ids": list(candidate.get("evidence_ids", [])),
                "open_questions": list(candidate.get("open_questions", [])),
                "solution_signals": list(candidate.get("solution_signals", [])),
            }
            for candidate in candidates
        ]

    @staticmethod
    def _summarize_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "artifact_ref": document.get("artifact_ref", ""),
                "title": document.get("title", ""),
                "excerpt": _safe_external_snippet(str(document.get("text", ""))),
            }
            for document in documents
        ]

    @staticmethod
    def _summarize_research_state(run_state: dict[str, Any]) -> dict[str, Any]:
        leads = {
            str(lead.get("lead_id", "")): lead
            for lead in run_state.get("research_leads", [])
            if lead.get("lead_id")
        }
        queues_by_round: dict[str, dict[str, Any]] = {
            str(queue.get("round_id", "")): queue
            for queue in run_state.get("reading_queues", [])
            if queue.get("round_id")
        }
        rounds = sorted(
            list(run_state.get("research_rounds", [])),
            key=lambda item: int(item.get("index", 0)),
            reverse=True,
        )[:2]
        return {
            "recent_rounds": [
                _round_summary(research_round, queues_by_round, leads)
                for research_round in reversed(rounds)
            ],
            "web_research_sessions": _summarize_web_research_sessions(
                list(run_state.get("web_research_sessions", []) or [])
            ),
        }

    @staticmethod
    def _summarize_worker_self_checks(
        checks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "check_id": item.get("check_id", ""),
                "assignment_id": item.get("assignment_id", ""),
                "round_id": item.get("round_id", ""),
                "topic_alignment": item.get("topic_alignment", ""),
                "body_evidence_count": item.get("body_evidence_count", 0),
                "direct_evidence_count": item.get("direct_evidence_count", 0),
                "partial_evidence_count": item.get("partial_evidence_count", 0),
                "follow_up_required": item.get("follow_up_required", False),
                "follow_up_reason": item.get("follow_up_reason", ""),
                "remaining_blind_spots": list(
                    item.get("remaining_blind_spots", [])
                )[:5],
                "discarded_findings": list(item.get("discarded_findings", []))[:5],
            }
            for item in checks[-5:]
        ]

    @staticmethod
    def _summarize_follow_up_instructions(
        instructions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "instruction_id": item.get("instruction_id", ""),
                "assignment_id": item.get("assignment_id", ""),
                "trigger_check_id": item.get("trigger_check_id", ""),
                "reason": item.get("reason", ""),
                "allowed_tools": list(item.get("allowed_tools", [])),
                "target_source_id": item.get("target_source_id", ""),
                "query_revisions": list(item.get("query_revisions", []))[:3],
                "route_revisions": list(item.get("route_revisions", []))[:5],
                "expected_outputs": list(item.get("expected_outputs", []))[:5],
            }
            for item in instructions[-5:]
        ]


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _round_summary(
    research_round: dict[str, Any],
    queues_by_round: dict[str, dict[str, Any]],
    leads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    round_id = str(research_round.get("round_id", ""))
    queue = queues_by_round.get(round_id, {})
    return {
        "round_id": round_id,
        "index": research_round.get("index", 0),
        "status": research_round.get("status", ""),
        "topic": research_round.get("topic", ""),
        "hypothesis": _excerpt(str(research_round.get("hypothesis", "")), 180),
        "worker_report_ids": list(research_round.get("worker_report_ids", [])),
        "judgement_id": research_round.get("judgement_id"),
        "next_round_plan": dict(research_round.get("next_round_plan", {})),
        "stop_reason": research_round.get("stop_reason"),
        "selected_leads": _lead_summaries(queue.get("selected_lead_ids", []), leads),
        "skipped_leads": _lead_summaries(queue.get("skipped_lead_ids", []), leads),
        "failed_leads": _lead_summaries(queue.get("failed_lead_ids", []), leads),
    }


def _lead_summaries(
    lead_ids: list[str],
    leads: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for lead_id in lead_ids[:10]:
        lead = leads.get(str(lead_id))
        if not lead:
            summaries.append({"lead_id": str(lead_id), "missing": True})
            continue
        summaries.append(
            {
                "lead_id": lead.get("lead_id", ""),
                "source_name": lead.get("source_name", ""),
                "source_tier": lead.get("source_tier", ""),
                "url": lead.get("url", ""),
                "title": lead.get("title", ""),
                "page_type": lead.get("page_type", ""),
                "status": lead.get("status", ""),
                "snippet": _safe_external_snippet(str(lead.get("snippet", ""))),
                "selection_reason": lead.get("selection_reason", ""),
                "skip_reason": lead.get("skip_reason", ""),
                "artifact_refs": list(lead.get("artifact_refs", [])),
            }
        )
    return summaries


def _safe_external_snippet(text: str) -> str:
    lower = text.lower()
    if "<html" in lower or "<body" in lower or "</" in lower:
        return ""
    return _excerpt(text, 220)


def _summarize_web_research_sessions(
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not sessions:
        return []
    running = [item for item in sessions if item.get("status") == "running"]
    selected = (running[-1:] or sessions[-1:])
    return [_compact_web_research_session(item) for item in selected]


def _compact_web_research_session(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session.get("session_id", ""),
        "assignment_id": session.get("assignment_id", ""),
        "round_id": session.get("round_id", ""),
        "runtime_ref": session.get("runtime_ref", ""),
        "topic_snapshot": _safe_external_snippet(str(session.get("topic_snapshot", ""))),
        "status": session.get("status", ""),
        "active_acceptance_criteria": list(
            session.get("active_acceptance_criteria", [])
        ),
        "allowed_source_refs": list(session.get("allowed_source_refs", [])),
        "recent_refs": [_compact_ref(item) for item in session.get("recent_refs", [])][-10:],
        "compact_summaries": [
            _safe_external_snippet(str(item))
            for item in list(session.get("compact_summaries", []))[-5:]
        ],
        "attempted_routes": [
            _compact_route(item) for item in list(session.get("attempted_routes", []))[-10:]
        ],
        "open_questions": list(session.get("open_questions", []))[-5:],
        "last_self_check_ref": session.get("last_self_check_ref", ""),
        "follow_up_refs": list(session.get("follow_up_refs", [])),
        "blocked_reasons": list(session.get("blocked_reasons", [])),
    }


def _compact_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_external_snippet(str(value)) if isinstance(value, str) else value
        for key, value in dict(item).items()
        if key not in {"html", "text", "content"}
    }


def _compact_route(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_external_snippet(str(value)) if isinstance(value, str) else value
        for key, value in dict(item).items()
        if key not in {"html", "text", "content"}
    }


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
