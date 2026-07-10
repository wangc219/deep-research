"""Stop gate for one worker assignment at apparent-stop time."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.models import DomainTraceEvent, EvidenceCard
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.web_research_session import (
    WebResearchSession,
)
from knowledgegraph.demand_discovery.domain.worker_research import (
    FollowUpInstruction,
    WorkerSelfCheck,
    evaluate_worker_self_check,
)


@dataclass
class WorkerStopPolicyConfig:
    run_id: str
    round_id: str
    assignment_id: str
    source_id: str = ""
    target_source_id: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    query_revisions: list[dict[str, str]] = field(default_factory=list)
    route_revisions: list[str] = field(default_factory=list)
    max_follow_ups_per_assignment: int = 2


@dataclass
class WorkerStopDecision:
    allow_stop: bool
    self_check: WorkerSelfCheck
    follow_up_instruction: FollowUpInstruction | None = None
    blocked_reason: str = ""


class WorkerStopPolicy:
    """Evaluates whether a worker may finish without adding another prompt."""

    def __init__(
        self,
        *,
        store: DomainStore,
        config: WorkerStopPolicyConfig,
    ) -> None:
        self.store = store
        self.config = config
        self.follow_up_attempt_count = 0
        self.follow_up_instruction_ids: list[str] = []
        self.recent_injection_keys: set[str] = set()

    def evaluate(
        self,
        *,
        apparent_stop_context: Any | None = None,
    ) -> WorkerStopDecision:
        session = self._ensure_session()
        facts = self._compute_facts(session)
        check = evaluate_worker_self_check(
            assignment_id=self.config.assignment_id,
            round_id=self.config.round_id,
            topic_alignment=facts["topic_alignment"],
            body_evidence_count=facts["body_evidence_count"],
            direct_evidence_count=facts["direct_evidence_count"],
            partial_evidence_count=facts["partial_evidence_count"],
            adjacent_evidence_count=facts["adjacent_evidence_count"],
            article_body_read_count=facts["article_body_read_count"],
            downloaded_document_read_count=facts["downloaded_document_read_count"],
            listing_or_search_only_count=facts["listing_or_search_only_count"],
            unverified_claims=[],
            strong_finding_count=facts["strong_finding_count"],
            strong_finding_evidence_ref_count=facts["strong_finding_evidence_ref_count"],
            queries_used=facts["queries_used"],
            routes_used=facts["routes_used"],
            source_diversity=facts["source_diversity"],
        )
        self.store.upsert_worker_self_check(check)
        self._update_session_after_check(session, check)
        self._append_trace(
            event_type="worker_self_check_recorded",
            target_type="WorkerSelfCheck",
            target_id=check.check_id,
            input_refs=facts["input_refs"],
            output_refs=[check.check_id],
            summary=f"worker self-check {check.follow_up_reason or 'passed'}",
            decision="allow_stop" if check.allowed_to_finish else "follow_up_required",
            rationale=check.follow_up_reason,
        )

        if check.allowed_to_finish:
            return WorkerStopDecision(True, check)

        blocked_reason = self._blocking_reason(check, apparent_stop_context)
        if blocked_reason:
            blocked = replace(
                check,
                follow_up_required=False,
                follow_up_reason=blocked_reason,
                remaining_blind_spots=[
                    *check.remaining_blind_spots,
                    blocked_reason,
                ],
                allowed_to_finish=False,
            )
            self.store.upsert_worker_self_check(blocked)
            self._append_trace(
                event_type="worker_blocked",
                target_type="WorkerSelfCheck",
                target_id=blocked.check_id,
                input_refs=[check.check_id],
                output_refs=[blocked.check_id],
                summary=f"worker blocked: {blocked_reason}",
                decision="blocked",
                rationale=blocked_reason,
            )
            return WorkerStopDecision(False, blocked, None, blocked_reason)

        instruction = self._make_follow_up_instruction(check)
        self.store.upsert_follow_up_instruction(instruction)
        self.follow_up_attempt_count += 1
        self.follow_up_instruction_ids.append(instruction.instruction_id)
        self.recent_injection_keys.add(self._instruction_key(instruction))
        self._update_session_after_follow_up(instruction)
        self._append_trace(
            event_type="worker_follow_up_planned",
            target_type="FollowUpInstruction",
            target_id=instruction.instruction_id,
            input_refs=[check.check_id],
            output_refs=[instruction.instruction_id],
            summary=f"worker follow-up planned: {instruction.reason}",
            decision="follow_up",
            rationale=instruction.reason,
        )
        return WorkerStopDecision(False, check, instruction, check.follow_up_reason)

    def apparent_stop_follow_up_policy(self, ctx: Any) -> list[str]:
        decision = self.evaluate(apparent_stop_context=ctx)
        if decision.allow_stop or decision.follow_up_instruction is None:
            return []
        return [decision.follow_up_instruction.to_prompt()]

    def _ensure_session(self) -> WebResearchSession:
        sessions = [
            item
            for item in self.store.web_research_sessions.values()
            if item.assignment_id == self.config.assignment_id
        ]
        if sessions:
            return sessions[-1]
        session = WebResearchSession(
            session_id=f"wrs-{uuid4().hex}",
            assignment_id=self.config.assignment_id,
            round_id=self.config.round_id,
            runtime_ref="",
            topic_snapshot="",
            status="running",
            active_acceptance_criteria=[
                "至少读取一篇文章正文或下载文档正文",
                "strong finding 必须引用 evidence refs",
            ],
            allowed_source_refs=(
                [f"source:{self.config.source_id}"] if self.config.source_id else []
            ),
        )
        self.store.upsert_web_research_session(session)
        return session

    def _compute_facts(self, session: WebResearchSession) -> dict[str, Any]:
        body_refs = self._body_artifact_refs(session)
        evidence_ids = {
            str(item.get("id"))
            for item in session.recent_refs
            if item.get("type") == "EvidenceCard" and item.get("id")
        }
        evidence = [
            self.store.evidence[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.store.evidence
        ]
        evidence = [
            card
            for card in evidence
            if (not self.config.source_id or card.source_id == self.config.source_id)
            and self._is_body_location(card.source_location, body_refs)
        ]
        direct = [card for card in evidence if _assessment(card) in {"direct", "strong"}]
        partial = [card for card in evidence if _assessment(card) == "partial"]
        adjacent = [card for card in evidence if _assessment(card) == "adjacent"]
        partial_roots = {_location_root(card.source_location) for card in partial}
        distinct_partial_count = len(partial_roots)
        direct_count = len(direct)
        partial_count = len(partial)
        body_count = len(body_refs)
        listing_count = sum(
            1
            for route in session.attempted_routes
            if str(route.get("outcome", "")).lower()
            in {"listing_only", "search_only", "site_home_only"}
        )
        if direct_count > 0:
            alignment = "direct"
        elif partial_count > 0:
            alignment = "partial"
        elif adjacent:
            alignment = "adjacent"
        else:
            alignment = "weak"
        strong_ref_count = direct_count + (2 if distinct_partial_count >= 2 else 0)
        return {
            "topic_alignment": alignment,
            "body_evidence_count": body_count,
            "direct_evidence_count": direct_count,
            "partial_evidence_count": distinct_partial_count,
            "adjacent_evidence_count": len(adjacent),
            "article_body_read_count": body_count,
            "downloaded_document_read_count": 0,
            "listing_or_search_only_count": listing_count,
            "strong_finding_count": 1 if direct_count > 0 or distinct_partial_count >= 2 else 0,
            "strong_finding_evidence_ref_count": strong_ref_count,
            "source_diversity": len({card.source_id for card in evidence}),
            "queries_used": [
                str(route.get("query"))
                for route in session.attempted_routes
                if route.get("query")
            ],
            "routes_used": [
                str(route.get("route"))
                for route in session.attempted_routes
                if route.get("route")
            ],
            "input_refs": [
                *body_refs,
                *[card.evidence_id for card in evidence],
            ],
        }

    def _blocking_reason(
        self,
        check: WorkerSelfCheck,
        apparent_stop_context: Any | None,
    ) -> str:
        budget_state = str(getattr(apparent_stop_context, "budget_state", "normal"))
        if budget_state in {"wrapping_up", "exhausted"}:
            return "budget_exhausted"
        if self.follow_up_attempt_count >= self.config.max_follow_ups_per_assignment:
            return "budget_exhausted"
        repeated_keys = set(getattr(apparent_stop_context, "repeated_injection_keys", set()))
        delta = dict(getattr(apparent_stop_context, "recent_domain_delta", {}) or {})
        no_new_body = (
            int(delta.get("open_source_body_artifacts", 0) or 0) <= 0
            and int(delta.get("body_artifact_refs", 0) or 0) <= 0
        )
        candidate_key = self._instruction_key_for_reason(check.follow_up_reason)
        if candidate_key in repeated_keys and no_new_body:
            return "no_new_body_artifact"
        return ""

    def _make_follow_up_instruction(
        self,
        check: WorkerSelfCheck,
    ) -> FollowUpInstruction:
        return FollowUpInstruction(
            instruction_id=f"followup-{uuid4().hex}",
            assignment_id=self.config.assignment_id,
            round_id=self.config.round_id,
            trigger_check_id=check.check_id,
            reason=check.follow_up_reason or "direct_evidence_missing",
            allowed_tools=list(self.config.allowed_tools or ["search_sources", "read_document"]),
            target_source_id=self.config.target_source_id or self.config.source_id,
            query_revisions=list(self.config.query_revisions),
            route_revisions=list(self.config.route_revisions),
            expected_outputs=["至少一个正文 artifact", "解释 direct/partial/adjacent 判断"],
            stop_after={
                "max_follow_up_turns": self.config.max_follow_ups_per_assignment,
            },
        )

    def _update_session_after_check(
        self,
        session: WebResearchSession,
        check: WorkerSelfCheck,
    ) -> None:
        updated = replace(session, last_self_check_ref=check.check_id)
        self.store.upsert_web_research_session(updated)

    def _update_session_after_follow_up(self, instruction: FollowUpInstruction) -> None:
        session = self._ensure_session()
        refs = [*session.follow_up_refs, instruction.instruction_id]
        updated = replace(session, follow_up_refs=refs)
        self.store.upsert_web_research_session(updated)

    @staticmethod
    def _body_artifact_refs(session: WebResearchSession) -> list[str]:
        refs: list[str] = []
        for item in session.recent_refs:
            if item.get("type") != "artifact":
                continue
            ref = str(item.get("id", ""))
            if ref and not ref.startswith(("listing:", "search:", "site_home:")):
                refs.append(ref)
        for route in session.attempted_routes:
            outcome = str(route.get("outcome", "")).lower()
            if "body_artifact_read" not in outcome and "body_read" not in outcome:
                continue
            for ref in route.get("output_refs", []) or []:
                text = str(ref)
                if text.startswith("artifact:") and text not in refs:
                    refs.append(text)
        return refs

    @staticmethod
    def _is_body_location(location: str, body_refs: list[str]) -> bool:
        lower = location.lower()
        if lower.startswith(("listing:", "search:", "site_home:", "browser_observation:")):
            return False
        if not body_refs:
            return False
        root = _location_root(location)
        return root in set(body_refs) or any(location.startswith(ref) for ref in body_refs)

    def _instruction_key(self, instruction: FollowUpInstruction) -> str:
        return "|".join(
            [
                instruction.reason,
                instruction.assignment_id,
                instruction.target_source_id,
                ",".join(sorted(instruction.expected_outputs)),
            ]
        )

    def _instruction_key_for_reason(self, reason: str) -> str:
        return "|".join(
            [
                reason,
                self.config.assignment_id,
                self.config.target_source_id or self.config.source_id,
                ",".join(sorted(["至少一个正文 artifact", "解释 direct/partial/adjacent 判断"])),
            ]
        )

    def _append_trace(
        self,
        *,
        event_type: str,
        target_type: str,
        target_id: str,
        input_refs: list[str],
        output_refs: list[str],
        summary: str,
        decision: str,
        rationale: str,
    ) -> DomainTraceEvent:
        return self.store.append_trace(
            DomainTraceEvent(
                domain_trace_id=f"dt-{uuid4().hex}",
                trace_id=self.config.run_id,
                event_type=event_type,
                actor="worker-stop-policy",
                target_type=target_type,
                target_id=target_id,
                input_refs=list(input_refs),
                output_refs=list(output_refs),
                summary=summary,
                decision=decision,
                rationale=rationale,
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )


def _assessment(card: EvidenceCard) -> str:
    return card.evidence_assessment.strip().lower()


def _location_root(location: str) -> str:
    if "#" in location:
        return location.split("#", 1)[0]
    return location
