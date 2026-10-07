"""Worker report extraction for scheduler-managed sub harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.worker_research import WorkerSelfCheck
from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.types import AgentMessage


@dataclass
class StoreSnapshot:
    sources: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    leads: set[str] = field(default_factory=set)
    candidates: dict[str, str] = field(default_factory=dict)


@dataclass
class WorkerReport:
    agent_run_id: str
    role: str
    status: str
    report_id: str = ""
    task_brief: str = ""
    partial_findings: list[str] = field(default_factory=list)
    new_evidence_cards: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    lead_refs: list[str] = field(default_factory=list)
    new_registry_entries: list[str] = field(default_factory=list)
    candidate_updates: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    need_more_sources: bool = False
    risk_or_conflict: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    session_path: str = ""
    error: str = ""
    assignment_id: str = ""
    source_id: str = ""
    queries_used: list[str] = field(default_factory=list)
    routes_used: list[str] = field(default_factory=list)
    self_check: WorkerSelfCheck | None = None
    follow_up_instructions: list[str] = field(default_factory=list)
    follow_up_attempt_count: int = 0
    browser_attempts: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    discarded_findings: list[str] = field(default_factory=list)
    evidence_quality_notes: list[str] = field(default_factory=list)
    blocked_reason: str = ""
    next_round_suggestions: list[str] = field(default_factory=list)
    evidence_ready_for_judge: bool | None = None
    stop_reason: str = ""
    remaining_gaps: list[str] = field(default_factory=list)

    def to_digest(self, limit_chars: int = 2000) -> str:
        lines = [
            f"Worker {self.agent_run_id} ({self.role}) {self.status}",
        ]
        if self.evidence_ready_for_judge is not None:
            value = "true" if self.evidence_ready_for_judge else "false"
            lines.append(f"evidence_ready_for_judge: {value}")
        if self.stop_reason:
            lines.append(f"stop_reason: {self.stop_reason}")
        if self.partial_findings:
            lines.append("findings:")
            lines.extend(f"- {item}" for item in self.partial_findings)
        if self.new_evidence_cards:
            lines.append("new_evidence_cards: " + ", ".join(self.new_evidence_cards))
        if self.new_registry_entries:
            lines.append(
                "new_registry_entries: " + ", ".join(self.new_registry_entries)
            )
        if self.candidate_updates:
            lines.append("candidate_updates: " + ", ".join(self.candidate_updates))
        if self.open_questions:
            lines.append("open_questions:")
            lines.extend(f"- {item}" for item in self.open_questions)
        if self.need_more_sources:
            lines.append("need_more_sources: true")
        if self.risk_or_conflict:
            lines.append("risks:")
            lines.extend(f"- {item}" for item in self.risk_or_conflict)
        if self.discarded_findings:
            lines.append("discarded_findings:")
            lines.extend(f"- {item}" for item in self.discarded_findings)
        if self.remaining_gaps:
            lines.append("remaining_gaps:")
            lines.extend(f"- {item}" for item in self.remaining_gaps)
        if self.next_round_suggestions:
            lines.append("suggested_next_routes:")
            lines.extend(f"- {item}" for item in self.next_round_suggestions)
        blind_spots = (
            list(self.self_check.remaining_blind_spots) if self.self_check else []
        )
        if blind_spots:
            lines.append("remaining_blind_spots:")
            lines.extend(f"- {item}" for item in blind_spots)
        if self.blocked_reason:
            lines.append(f"blocked_reason: {self.blocked_reason}")
        if self.error:
            lines.append(f"error: {self.error}")
        text = "\n".join(lines)
        if len(text) <= limit_chars:
            return text
        return text[:limit_chars].rstrip() + "...<truncated>"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id,
            "role": self.role,
            "status": self.status,
            "report_id": self.report_id or self.agent_run_id,
            "task_brief": self.task_brief,
            "partial_findings": list(self.partial_findings),
            "new_evidence_cards": list(self.new_evidence_cards),
            "evidence_refs": list(self.evidence_refs or self.new_evidence_cards),
            "lead_refs": list(self.lead_refs),
            "new_registry_entries": list(self.new_registry_entries),
            "candidate_updates": list(self.candidate_updates),
            "open_questions": list(self.open_questions),
            "need_more_sources": self.need_more_sources,
            "risk_or_conflict": list(self.risk_or_conflict),
            "usage": dict(self.usage),
            "session_path": self.session_path,
            "error": self.error,
            "assignment_id": self.assignment_id,
            "source_id": self.source_id,
            "queries_used": list(self.queries_used),
            "routes_used": list(self.routes_used),
            "self_check": self.self_check.to_dict() if self.self_check else None,
            "follow_up_instructions": list(self.follow_up_instructions),
            "follow_up_attempt_count": self.follow_up_attempt_count,
            "browser_attempts": list(self.browser_attempts),
            "artifact_refs": list(self.artifact_refs),
            "discarded_findings": list(self.discarded_findings),
            "evidence_quality_notes": list(self.evidence_quality_notes),
            "blocked_reason": self.blocked_reason,
            "next_round_suggestions": list(self.next_round_suggestions),
            "evidence_ready_for_judge": self.evidence_ready_for_judge,
            "stop_reason": self.stop_reason,
            "remaining_gaps": list(self.remaining_gaps),
        }


def snapshot_store(store: DomainStore) -> StoreSnapshot:
    return StoreSnapshot(
        sources=set(store.sources),
        evidence=set(store.evidence),
        leads=set(store.research_leads),
        candidates={
            candidate_id: candidate.status
            for candidate_id, candidate in store.candidates.items()
        },
    )


def build_worker_report(
    *,
    agent_run_id: str,
    role: str,
    task_brief: str,
    status: str,
    before: StoreSnapshot,
    after_store: DomainStore,
    final_message: AgentMessage | None,
    budget: RunBudget | None,
    session_path: str,
    error: str = "",
) -> WorkerReport:
    after_candidates = {
        candidate_id: candidate.status
        for candidate_id, candidate in after_store.candidates.items()
    }
    parsed = parse_worker_text(_message_text(final_message))
    new_candidates = sorted(set(after_candidates) - set(before.candidates))
    changed_candidates = sorted(
        candidate_id
        for candidate_id, status_value in after_candidates.items()
        if candidate_id in before.candidates
        and before.candidates[candidate_id] != status_value
    )
    return normalize_worker_report_evidence_policy(
        WorkerReport(
            agent_run_id=agent_run_id,
            role=role,
            status=status,
            report_id=agent_run_id,
            task_brief=task_brief,
            partial_findings=parsed["findings"],
            new_evidence_cards=sorted(set(after_store.evidence) - before.evidence),
            evidence_refs=sorted(set(after_store.evidence) - before.evidence),
            lead_refs=sorted(set(after_store.research_leads) - before.leads),
            new_registry_entries=new_candidates,
            candidate_updates=[*new_candidates, *changed_candidates],
            open_questions=_dedupe([*parsed["open_questions"], *parsed["remaining_gaps"]]),
            need_more_sources=parsed["need_more_sources"],
            risk_or_conflict=parsed["risks"],
            usage=budget.remaining_summary() if budget is not None else {},
            session_path=session_path,
            error=error,
            evidence_ready_for_judge=parsed["evidence_ready_for_judge"],
            stop_reason=parsed["stop_reason"],
            remaining_gaps=parsed["remaining_gaps"],
            next_round_suggestions=parsed["suggested_next_routes"],
        )
    )


def normalize_worker_report_evidence_policy(report: WorkerReport) -> WorkerReport:
    if report.partial_findings and not report.evidence_refs:
        report.discarded_findings.extend(report.partial_findings)
        report.open_questions.extend(
            f"需要正文证据支撑：{finding}" for finding in report.partial_findings
        )
        report.partial_findings = []
        if "strong finding missing evidence refs" not in report.evidence_quality_notes:
            report.evidence_quality_notes.append("strong finding missing evidence refs")
        if not report.blocked_reason:
            report.blocked_reason = "strong_finding_unreferenced"
        report.need_more_sources = True
    if report.self_check and not report.self_check.allowed_to_finish:
        report.need_more_sources = True
        if not report.blocked_reason:
            report.blocked_reason = report.self_check.follow_up_reason
    return report


def parse_worker_text(text: str) -> dict[str, Any]:
    sections = {
        "findings": [],
        "open_questions": [],
        "risks": [],
        "need_more_sources": False,
        "evidence_ready_for_judge": None,
        "stop_reason": "",
        "remaining_gaps": [],
        "suggested_next_routes": [],
    }
    current = "findings"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = line.rstrip(":").lower()
        if normalized in {"findings", "partial_findings"}:
            current = "findings"
            continue
        if normalized in {"open_questions", "open questions"}:
            current = "open_questions"
            continue
        if normalized in {"risks", "risk_or_conflict", "risk or conflict"}:
            current = "risks"
            continue
        if normalized in {"stop_reason", "stop reason"}:
            current = "stop_reason"
            continue
        if normalized in {"remaining_gaps", "remaining gaps"}:
            current = "remaining_gaps"
            continue
        if normalized in {
            "suggested_next_routes",
            "suggested next routes",
            "next_round_suggestions",
            "next round suggestions",
        }:
            current = "suggested_next_routes"
            continue
        if normalized.startswith("evidence_ready_for_judge"):
            sections["evidence_ready_for_judge"] = _parse_bool(normalized)
            continue
        if normalized.startswith("need_more_sources"):
            sections["need_more_sources"] = "true" in normalized or "yes" in normalized
            continue
        item = line[1:].strip() if line.startswith("-") else line
        if current in {"findings", "open_questions", "risks"}:
            sections[current].append(item)
        elif current == "stop_reason" and not sections["stop_reason"]:
            sections["stop_reason"] = item
        elif current in {"remaining_gaps", "suggested_next_routes"}:
            sections[current].append(item)
    if not sections["findings"] and text.strip():
        sections["findings"].append(text.strip()[:1000])
    return sections


def _message_text(message: AgentMessage | None) -> str:
    if message is None:
        return ""
    if isinstance(message.content, str):
        return message.content
    return "\n".join(block.text for block in message.content if block.type == "text")


def _parse_bool(text: str) -> bool | None:
    if "true" in text or "yes" in text:
        return True
    if "false" in text or "no" in text:
        return False
    return None


def _dedupe(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows
