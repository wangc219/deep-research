"""In-memory demand discovery domain store with JSONL export."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.models import (
    AuditReport,
    CandidateDemand,
    DemandReport,
    DomainTraceEvent,
    EvidenceCard,
    HumanReviewRecord,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.browser_research import (
    BrowserRecipeDraft,
    browser_recipe_draft_from_dict,
)
from knowledgegraph.demand_discovery.domain.open_search import (
    OpenSearchPlan,
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
    open_search_plan_from_dict,
    open_source_body_artifact_from_dict,
    open_source_lead_from_dict,
    quality_level_to_lead_status,
    source_quality_assessment_from_dict,
)
from knowledgegraph.demand_discovery.domain.report_context import (
    ReportContextBundle,
    report_context_bundle_from_dict,
)
from knowledgegraph.demand_discovery.domain.judgement import (
    JudgementReport,
    judgement_report_from_dict,
)
from knowledgegraph.demand_discovery.domain.research_state import (
    ReadingQueue,
    ResearchLead,
    ResearchRound,
    reading_queue_from_dict,
    research_lead_from_dict,
    research_round_from_dict,
)
from knowledgegraph.demand_discovery.domain.source_strategy import (
    SourceStrategy,
    source_strategy_from_dict,
)
from knowledgegraph.demand_discovery.domain.web_research_session import (
    WebResearchSession,
    web_research_session_from_dict,
)
from knowledgegraph.demand_discovery.domain.worker_research import (
    FollowUpInstruction,
    WorkerSelfCheck,
    follow_up_instruction_from_dict,
    worker_self_check_from_dict,
)
from knowledgegraph.demand_discovery.domain.state_machine import (
    status_rank,
    validate_status,
    validate_status_cap,
    validate_transition,
)
from knowledgegraph.demand_discovery.harness.types import (
    DomainTraceProposal,
    DomainWriteProposal,
)


APPROVED_AUDIT_CONCLUSIONS = {"approved", "pass", "通过"}
REPORT_REVIEW_STATUSES = {
    "draft",
    "review_ready",
    "needs_revision",
    "approved",
    "rejected",
    "watchlist",
}
HUMAN_REVIEW_DECISIONS = {
    "approved",
    "approved_with_changes",
    "needs_revision",
    "rejected",
    "watchlist",
}


class DomainStore:
    """Small in-memory domain store for the first runnable harness demo."""

    def __init__(
        self,
        tier_status_cap: Callable[[str], str] | None = None,
    ) -> None:
        self.sources: dict[str, SourceRecord] = {}
        self.evidence: dict[str, EvidenceCard] = {}
        self.candidates: dict[str, CandidateDemand] = {}
        self.audit_reports: dict[str, AuditReport] = {}
        self.demand_reports: dict[str, DemandReport] = {}
        self.report_context_bundles: dict[str, ReportContextBundle] = {}
        self.human_reviews: dict[str, HumanReviewRecord] = {}
        self.source_strategies: dict[str, SourceStrategy] = {}
        self.research_leads: dict[str, ResearchLead] = {}
        self.reading_queues: dict[str, ReadingQueue] = {}
        self.research_rounds: dict[str, ResearchRound] = {}
        self.judgement_reports: dict[str, JudgementReport] = {}
        self.open_search_plans: dict[str, OpenSearchPlan] = {}
        self.open_source_leads: dict[str, OpenSourceLead] = {}
        self.open_source_body_artifacts: dict[str, OpenSourceBodyArtifact] = {}
        self.source_quality_assessments: dict[str, SourceQualityAssessment] = {}
        self.browser_recipe_drafts: dict[str, BrowserRecipeDraft] = {}
        self.web_research_sessions: dict[str, WebResearchSession] = {}
        self.worker_self_checks: dict[str, WorkerSelfCheck] = {}
        self.follow_up_instructions: dict[str, FollowUpInstruction] = {}
        self.trace_events: list[DomainTraceEvent] = []
        self._jsonl_path: Path | None = None
        self._tier_status_cap = tier_status_cap

    def bind_jsonl(self, path: str | Path) -> None:
        """Bind an append-only JSONL file for accepted domain writes."""

        self._jsonl_path = Path(path)
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._jsonl_path.exists():
            self._jsonl_path.write_text("", encoding="utf-8")

    def append_accepted_proposals(
        self, proposals: list[DomainWriteProposal]
    ) -> None:
        for proposal in proposals:
            self._append_jsonl(
                {
                    "kind": "domain",
                    "action": proposal.action,
                    "object_type": proposal.object_type,
                    "payload": self._accepted_payload_for_proposal(proposal),
                }
            )

    def append_accepted_trace_events(
        self, events: list[DomainTraceEvent]
    ) -> None:
        for event in events:
            self._append_jsonl({"kind": "trace_event", "payload": event.to_dict()})

    @classmethod
    def load_jsonl(cls, path: str | Path) -> "DomainStore":
        store = cls()
        input_path = Path(path)
        if not input_path.exists():
            return store
        export_rows: list[tuple[str, dict[str, Any]]] = []
        for line in input_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "domain":
                store.apply_domain_proposal(
                    DomainWriteProposal(
                        action=str(row["action"]),
                        object_type=str(row["object_type"]),
                        payload=dict(row.get("payload", {})),
                    )
                )
            elif row.get("kind") == "trace_event":
                store.append_trace(_trace_event_from_dict(dict(row.get("payload", {}))))
            elif row.get("kind") == "human_review":
                record = _human_review_from_dict(dict(row.get("payload", {})))
                store.human_reviews[record.review_id] = record
            elif row.get("kind") == "web_research_session":
                session = web_research_session_from_dict(
                    dict(row.get("payload", {}))
                )
                store.web_research_sessions[session.session_id] = session
            elif row.get("kind") == "worker_self_check":
                check = worker_self_check_from_dict(dict(row.get("payload", {})))
                store.worker_self_checks[check.check_id] = check
            elif row.get("kind") == "follow_up_instruction":
                instruction = follow_up_instruction_from_dict(
                    dict(row.get("payload", {}))
                )
                store.follow_up_instructions[instruction.instruction_id] = instruction
            elif row.get("type"):
                export_rows.append((str(row["type"]), dict(row.get("payload", {}))))
        for row_type, payload in sorted(export_rows, key=_export_load_priority):
            store._apply_export_row(row_type, payload)
        store.bind_jsonl(input_path)
        return store

    def _append_jsonl(self, row: dict[str, Any]) -> None:
        if self._jsonl_path is None:
            return
        with self._jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _accepted_payload_for_proposal(
        self, proposal: DomainWriteProposal
    ) -> dict[str, Any]:
        payload = dict(proposal.payload)
        if proposal.object_type == "SourceRecord" and proposal.action == "upsert":
            return self.sources[str(payload["source_id"])].to_dict()
        if proposal.object_type == "EvidenceCard" and proposal.action == "upsert":
            return self.evidence[str(payload["evidence_id"])].to_dict()
        if proposal.object_type == "CandidateDemand" and proposal.action == "upsert":
            return self.candidates[str(payload["candidate_id"])].to_dict()
        if proposal.object_type == "AuditReport" and proposal.action == "append":
            return self.audit_reports[str(payload["audit_id"])].to_dict()
        if proposal.object_type == "DemandReport" and proposal.action in {"append", "upsert"}:
            return self.demand_reports[str(payload["report_id"])].to_dict()
        if proposal.object_type == "ReportContextBundle" and proposal.action == "upsert":
            return self.report_context_bundles[str(payload["bundle_id"])].to_dict()
        if proposal.object_type == "SourceStrategy" and proposal.action == "upsert":
            return self.source_strategies[str(payload["strategy_id"])].to_dict()
        if proposal.object_type == "ResearchLead" and proposal.action == "upsert":
            return self.research_leads[str(payload["lead_id"])].to_dict()
        if proposal.object_type == "ReadingQueue" and proposal.action == "upsert":
            return self.reading_queues[str(payload["queue_id"])].to_dict()
        if proposal.object_type == "ResearchRound" and proposal.action == "upsert":
            return self.research_rounds[str(payload["round_id"])].to_dict()
        if proposal.object_type == "JudgementReport" and proposal.action == "upsert":
            return self.judgement_reports[str(payload["judgement_id"])].to_dict()
        if proposal.object_type == "OpenSearchPlan" and proposal.action == "upsert":
            return self.open_search_plans[str(payload["plan_id"])].to_dict()
        if proposal.object_type == "OpenSourceLead" and proposal.action == "upsert":
            return self.open_source_leads[str(payload["lead_id"])].to_dict()
        if proposal.object_type == "OpenSourceBodyArtifact" and proposal.action == "upsert":
            return self.open_source_body_artifacts[str(payload["body_id"])].to_dict()
        if proposal.object_type == "SourceQualityAssessment" and proposal.action == "upsert":
            return self.source_quality_assessments[str(payload["assessment_id"])].to_dict()
        if proposal.object_type == "BrowserRecipeDraft" and proposal.action == "upsert":
            return self.browser_recipe_drafts[str(payload["recipe_id"])].to_dict()
        if proposal.object_type == "WebResearchSession" and proposal.action == "upsert":
            return self.web_research_sessions[str(payload["session_id"])].to_dict()
        if proposal.object_type == "WorkerSelfCheck" and proposal.action == "upsert":
            return self.worker_self_checks[str(payload["check_id"])].to_dict()
        if proposal.object_type == "FollowUpInstruction" and proposal.action == "upsert":
            return self.follow_up_instructions[str(payload["instruction_id"])].to_dict()
        return payload

    def upsert_source(self, record: SourceRecord) -> SourceRecord:
        if record.open_source_lead_id and record.open_source_lead_id not in self.open_source_leads:
            raise ValueError(f"unknown open_source_lead_id: {record.open_source_lead_id}")
        self.sources[record.source_id] = record
        return record

    def upsert_evidence(self, card: EvidenceCard) -> EvidenceCard:
        if card.source_id and card.source_id not in self.sources:
            raise ValueError(f"unknown source_id: {card.source_id}")
        source = self.sources.get(card.source_id)
        if source is not None and source.open_source_lead_id:
            card = self._validate_open_source_evidence(card, source)
        if (
            source is not None
            and source.collection_decision == "use_as_background"
            and _source_location_looks_like_body(str(card.source_location or ""))
        ):
            self.sources[source.source_id] = replace(
                source,
                collection_decision="use_as_evidence",
                updated_at=_now(),
            )
        self.evidence[card.evidence_id] = card
        return card

    def upsert_source_strategy(self, strategy: SourceStrategy) -> SourceStrategy:
        self.source_strategies[strategy.strategy_id] = strategy
        return strategy

    def upsert_report_context_bundle(
        self,
        bundle: ReportContextBundle,
    ) -> ReportContextBundle:
        if bundle.candidate_id not in self.candidates and self.candidates:
            raise ValueError(
                f"unknown candidate_id for ReportContextBundle: {bundle.candidate_id}"
            )
        self.report_context_bundles[bundle.bundle_id] = bundle
        return bundle

    def upsert_open_search_plan(self, plan: OpenSearchPlan) -> OpenSearchPlan:
        self.open_search_plans[plan.plan_id] = plan
        return plan

    def upsert_open_source_lead(self, lead: OpenSourceLead) -> OpenSourceLead:
        if lead.plan_id not in self.open_search_plans:
            raise ValueError(f"unknown open_search_plan_id: {lead.plan_id}")
        self.open_source_leads[lead.lead_id] = lead
        return lead

    def upsert_open_source_body_artifact(
        self,
        body: OpenSourceBodyArtifact,
    ) -> OpenSourceBodyArtifact:
        lead = self.open_source_leads.get(body.lead_id)
        if lead is None:
            raise ValueError(f"unknown open_source_lead_id: {body.lead_id}")
        if body.plan_id != lead.plan_id:
            raise ValueError("OpenSourceBodyArtifact plan_id does not match lead")
        if body.url != lead.url:
            raise ValueError("OpenSourceBodyArtifact url does not match lead")
        self.open_source_body_artifacts[body.body_id] = body
        return body

    def upsert_source_quality_assessment(
        self,
        assessment: SourceQualityAssessment,
    ) -> SourceQualityAssessment:
        if assessment.lead_id not in self.open_source_leads:
            raise ValueError(f"unknown open_source_lead_id: {assessment.lead_id}")
        self._validate_source_quality_body_refs(assessment)
        self.source_quality_assessments[assessment.assessment_id] = assessment
        lead = self.open_source_leads[assessment.lead_id]
        mapped_status = quality_level_to_lead_status(assessment.quality_level)
        if lead.quality_status != mapped_status:
            self.open_source_leads[lead.lead_id] = replace(
                lead,
                quality_status=mapped_status,
                updated_at=_now(),
            )
        return assessment

    def upsert_browser_recipe_draft(
        self,
        draft: BrowserRecipeDraft,
    ) -> BrowserRecipeDraft:
        self.browser_recipe_drafts[draft.recipe_id] = draft
        return draft

    def upsert_web_research_session(
        self,
        session: WebResearchSession,
    ) -> WebResearchSession:
        self.web_research_sessions[session.session_id] = session
        return session

    def upsert_worker_self_check(
        self,
        check: WorkerSelfCheck,
    ) -> WorkerSelfCheck:
        self.worker_self_checks[check.check_id] = check
        return check

    def upsert_follow_up_instruction(
        self,
        instruction: FollowUpInstruction,
    ) -> FollowUpInstruction:
        self.follow_up_instructions[instruction.instruction_id] = instruction
        return instruction

    def _validate_source_quality_body_refs(
        self,
        assessment: SourceQualityAssessment,
    ) -> None:
        bodies = [
            body
            for body in self.open_source_body_artifacts.values()
            if body.lead_id == assessment.lead_id
        ]
        if not bodies:
            raise ValueError("open source body artifact is required before quality assessment")
        artifact_refs = {body.artifact_ref for body in bodies} | {
            body.simplified_ref for body in bodies
        }
        for ref in assessment.basis_artifact_refs:
            if ref not in artifact_refs:
                raise ValueError(f"unknown basis_artifact_ref for lead: {ref}")
        prefixes = [body.body_location_prefix for body in bodies]
        for ref in assessment.body_location_refs:
            if not any(ref.startswith(prefix) for prefix in prefixes):
                raise ValueError(
                    f"body_location_ref is not from lead body artifact: {ref}"
                )

    def _validate_open_source_evidence(
        self,
        card: EvidenceCard,
        source: SourceRecord,
    ) -> EvidenceCard:
        assessment_id = card.source_quality_assessment_id or ""
        if not assessment_id:
            raise ValueError("open source quality assessment is required")
        assessment = self.source_quality_assessments.get(assessment_id)
        if assessment is None:
            raise ValueError(f"unknown source_quality_assessment_id: {assessment_id}")
        if assessment.lead_id != source.open_source_lead_id:
            raise ValueError(
                "source_quality_assessment_id does not belong to source open_source_lead_id"
            )
        if card.source_location not in assessment.body_location_refs:
            raise ValueError(
                "EvidenceCard source_location is not covered by SourceQualityAssessment body_location_refs"
            )
        if assessment.quality_level in {"background_only", "low_quality", "rejected"}:
            raise ValueError(f"open source quality is rejected: {assessment.quality_level}")
        if assessment.quality_level == "provisional" and card.evidence_assessment != "provisional":
            return replace(card, evidence_assessment="provisional")
        return card

    def upsert_research_lead(self, lead: ResearchLead) -> ResearchLead:
        self.research_leads[lead.lead_id] = lead
        return lead

    def upsert_reading_queue(self, queue: ReadingQueue) -> ReadingQueue:
        missing = [
            lead_id
            for lead_id in [
                *queue.lead_ids,
                *queue.selected_lead_ids,
                *queue.skipped_lead_ids,
                *queue.failed_lead_ids,
            ]
            if lead_id not in self.research_leads
        ]
        if missing:
            raise ValueError(f"unknown lead_id: {missing[0]}")
        self.reading_queues[queue.queue_id] = queue
        return queue

    def upsert_research_round(self, research_round: ResearchRound) -> ResearchRound:
        self.research_rounds[research_round.round_id] = research_round
        return research_round

    def upsert_judgement_report(self, report: JudgementReport) -> JudgementReport:
        self.judgement_reports[report.judgement_id] = report
        return report

    def upsert_candidate(self, candidate: CandidateDemand) -> CandidateDemand:
        self._validate_evidence_ids(candidate.evidence_ids)
        self._validate_candidate_status(candidate)
        self.candidates[candidate.candidate_id] = candidate
        return candidate

    def append_audit(self, report: AuditReport) -> AuditReport:
        if report.candidate_id not in self.candidates:
            raise ValueError(f"unknown candidate_id: {report.candidate_id}")
        existing = self.audit_reports.get(report.audit_id)
        if existing is not None:
            if existing.candidate_id != report.candidate_id:
                raise ValueError(
                    "audit_id "
                    f"{report.audit_id} already exists for candidate "
                    f"{existing.candidate_id}"
                )
            if _normalize_audit_conclusion(existing.conclusion) != _normalize_audit_conclusion(
                report.conclusion
            ):
                raise ValueError(
                    "audit_id "
                    f"{report.audit_id} already exists with conclusion "
                    f"{existing.conclusion}; create a new audit_id for revised audits"
                )
            return existing
        self.audit_reports[report.audit_id] = report
        return report

    def append_demand_report(self, report: DemandReport) -> DemandReport:
        if report.candidate_id not in self.candidates:
            raise ValueError(f"unknown candidate_id: {report.candidate_id}")
        if self.candidates[report.candidate_id].status != "demand_report":
            raise ValueError(
                "candidate must be in demand_report status before appending report"
        )
        self._validate_report_review_status(report.review_status)
        strict_report_gate = report.review_status in {"draft", "review_ready"}
        if strict_report_gate:
            try:
                self.validate_demand_report_gate(
                    report.candidate_id,
                    report.audit_id,
                    report.evidence_ids,
                )
            except ValueError as exc:
                if report.review_status == "review_ready":
                    raise ValueError(
                        "review_ready report requires approved audit: " + str(exc)
                    ) from exc
                raise
        else:
            self.validate_demand_report_reference_gate(
                report.candidate_id,
                report.audit_id,
                report.evidence_ids,
                require_minimum_supported_evidence=False,
            )
        resolved = replace(
            report,
            sensitive_review_required=(
                report.sensitive_review_required
                or self._audit_sensitive_flag(report.audit_id)
            ),
        )
        self.demand_reports[resolved.report_id] = resolved
        return resolved

    def update_report_review_status(
        self,
        report_id: str,
        review_status: str,
    ) -> DemandReport:
        self._validate_report_review_status(review_status)
        report = self.demand_reports[report_id]
        updated = replace(report, review_status=review_status)
        self.demand_reports[report_id] = updated
        return updated

    def append_human_review(self, record: HumanReviewRecord) -> HumanReviewRecord:
        return self._append_human_review_record(record, persist=True)

    def latest_human_review(self, report_id: str) -> HumanReviewRecord | None:
        reviews = [
            record
            for record in self.human_reviews.values()
            if record.report_id == report_id
        ]
        if not reviews:
            return None
        return max(reviews, key=lambda item: item.review_time)

    def validate_demand_report_gate(
        self,
        candidate_id: str,
        audit_id: str,
        evidence_ids: list[str],
    ) -> None:
        from knowledgegraph.demand_discovery.domain.evidence_support import (
            review_ready_scorecard_errors,
        )

        if not audit_id:
            raise ValueError("approved audit_id is required before generating report")
        self.validate_demand_report_reference_gate(
            candidate_id,
            audit_id,
            evidence_ids,
            require_minimum_supported_evidence=False,
        )
        audit = self.audit_reports.get(audit_id)
        assert audit is not None
        if audit.conclusion.strip().lower() not in APPROVED_AUDIT_CONCLUSIONS:
            raise ValueError(f"audit {audit_id} is not approved")
        if not any(
            self._evidence_satisfies_minimum_report_gate(evidence_id)
            for evidence_id in evidence_ids
        ):
            raise ValueError(
                "minimum evidence requirement not met: report requires at least one "
                "EvidenceCard from an article body or downloaded document body that "
                "passes minimum source gate with strong or direct support"
            )
        semantic_errors = review_ready_scorecard_errors(
            audit.scorecard,
            evidence_ids=list(evidence_ids),
            evidence_map=self._evidence_map_for_support(evidence_ids),
        )
        if semantic_errors:
            raise ValueError(
                "review_ready audit requires evidence_support semantic review: "
                + "; ".join(semantic_errors)
            )

    def validate_demand_report_reference_gate(
        self,
        candidate_id: str,
        audit_id: str,
        evidence_ids: list[str],
        *,
        require_minimum_supported_evidence: bool = True,
    ) -> None:
        if candidate_id not in self.candidates:
            raise ValueError(f"unknown candidate_id: {candidate_id}")
        if not audit_id:
            raise ValueError("audit_id is required before generating report")
        audit = self.audit_reports.get(audit_id)
        if audit is None:
            raise ValueError(f"unknown audit_id: {audit_id}")
        if audit.candidate_id != candidate_id:
            raise ValueError(
                f"audit {audit_id} does not belong to candidate {candidate_id}"
            )
        if not evidence_ids:
            raise ValueError("at least one evidence_id is required")
        self._validate_evidence_ids(evidence_ids)
        candidate = self.candidates[candidate_id]
        missing_from_candidate = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id not in candidate.evidence_ids
        ]
        if missing_from_candidate:
            raise ValueError(
                "report evidence_id "
                f"{missing_from_candidate[0]} is not attached to candidate {candidate_id}"
            )
        if require_minimum_supported_evidence and not any(
            self._evidence_satisfies_minimum_report_gate(evidence_id)
            for evidence_id in evidence_ids
        ):
            raise ValueError(
                "report requires at least one EvidenceCard from an article body "
                "or downloaded document body that passes minimum source gate "
                "with strong or direct support"
            )

    def get_candidate(self, candidate_id: str) -> CandidateDemand:
        return self.candidates[candidate_id]

    def list_candidates(self, status: str | None = None) -> list[CandidateDemand]:
        candidates = list(self.candidates.values())
        if status is None:
            return candidates
        return [candidate for candidate in candidates if candidate.status == status]

    def list_signals(
        self, statuses: set[str] | None = None
    ) -> list[CandidateDemand]:
        signal_statuses = statuses or {
            "raw_signal",
            "researchable_signal",
            "weak_signal",
            "discarded_signal",
        }
        return [
            candidate
            for candidate in self.candidates.values()
            if candidate.status in signal_statuses
        ]

    def watchlist_view(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for candidate in self.list_signals({"weak_signal"}):
            parked = self._latest_trace_for(candidate.candidate_id, "signal_parked")
            if parked is None:
                continue
            rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "title": candidate.title,
                    "status": candidate.status,
                    "recheck_conditions": list(
                        parked.payload.get("recheck_conditions", [])
                    ),
                    "trace_event_id": parked.domain_trace_id,
                    "summary": parked.summary,
                }
            )
        return rows

    def update_candidate_status(
        self,
        candidate_id: str,
        status: str,
        summary: str,
        actor: str,
    ) -> CandidateDemand:
        candidate = self.candidates[candidate_id]
        validate_transition(candidate.status, status)
        updated = replace(
            candidate,
            status=status,
            updated_at=_now(),
        )
        self._validate_candidate_status(updated)
        self.candidates[candidate_id] = updated
        self.append_trace(
            DomainTraceEvent(
                domain_trace_id=f"dt-{uuid4().hex}",
                trace_id="domain-store",
                event_type="candidate_status_changed",
                actor=actor,
                target_type="CandidateDemand",
                target_id=candidate_id,
                input_refs=list(candidate.evidence_ids),
                output_refs=[candidate_id],
                summary=summary,
                decision=status,
                rationale=summary,
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=_now(),
            )
        )
        return updated

    def merge_candidate(
        self,
        candidate_id: str,
        surviving_candidate_id: str,
        actor: str,
    ) -> CandidateDemand:
        if surviving_candidate_id not in self.candidates:
            raise ValueError(f"unknown surviving_candidate_id: {surviving_candidate_id}")
        candidate = self.candidates[candidate_id]
        superseded = replace(
            candidate,
            superseded_by=surviving_candidate_id,
            superseded_reason="merged",
            updated_at=_now(),
        )
        self.candidates[candidate_id] = superseded
        self.append_trace(
            DomainTraceEvent(
                domain_trace_id=f"dt-{uuid4().hex}",
                trace_id="domain-store",
                event_type="candidate_merged",
                actor=actor,
                target_type="CandidateDemand",
                target_id=surviving_candidate_id,
                input_refs=[candidate_id],
                output_refs=[surviving_candidate_id],
                summary=f"merged {candidate_id} into {surviving_candidate_id}",
                decision="merged",
                rationale="merged",
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=_now(),
            )
        )
        return superseded

    def append_trace(self, event: DomainTraceEvent) -> DomainTraceEvent:
        self.trace_events.append(event)
        return event

    def clone(self) -> "DomainStore":
        staged = DomainStore()
        staged.sources = deepcopy(self.sources)
        staged.evidence = deepcopy(self.evidence)
        staged.candidates = deepcopy(self.candidates)
        staged.audit_reports = deepcopy(self.audit_reports)
        staged.demand_reports = deepcopy(self.demand_reports)
        staged.report_context_bundles = deepcopy(self.report_context_bundles)
        staged.human_reviews = deepcopy(self.human_reviews)
        staged.source_strategies = deepcopy(self.source_strategies)
        staged.research_leads = deepcopy(self.research_leads)
        staged.reading_queues = deepcopy(self.reading_queues)
        staged.research_rounds = deepcopy(self.research_rounds)
        staged.judgement_reports = deepcopy(self.judgement_reports)
        staged.open_search_plans = deepcopy(self.open_search_plans)
        staged.open_source_leads = deepcopy(self.open_source_leads)
        staged.open_source_body_artifacts = deepcopy(self.open_source_body_artifacts)
        staged.source_quality_assessments = deepcopy(self.source_quality_assessments)
        staged.browser_recipe_drafts = deepcopy(self.browser_recipe_drafts)
        staged.web_research_sessions = deepcopy(self.web_research_sessions)
        staged.worker_self_checks = deepcopy(self.worker_self_checks)
        staged.follow_up_instructions = deepcopy(self.follow_up_instructions)
        staged.trace_events = deepcopy(self.trace_events)
        staged._tier_status_cap = self._tier_status_cap
        return staged

    def replace_from(self, other: "DomainStore") -> None:
        jsonl_path = self._jsonl_path
        self.sources = deepcopy(other.sources)
        self.evidence = deepcopy(other.evidence)
        self.candidates = deepcopy(other.candidates)
        self.audit_reports = deepcopy(other.audit_reports)
        self.demand_reports = deepcopy(other.demand_reports)
        self.report_context_bundles = deepcopy(other.report_context_bundles)
        self.human_reviews = deepcopy(other.human_reviews)
        self.source_strategies = deepcopy(other.source_strategies)
        self.research_leads = deepcopy(other.research_leads)
        self.reading_queues = deepcopy(other.reading_queues)
        self.research_rounds = deepcopy(other.research_rounds)
        self.judgement_reports = deepcopy(other.judgement_reports)
        self.open_search_plans = deepcopy(other.open_search_plans)
        self.open_source_leads = deepcopy(other.open_source_leads)
        self.open_source_body_artifacts = deepcopy(other.open_source_body_artifacts)
        self.source_quality_assessments = deepcopy(other.source_quality_assessments)
        self.browser_recipe_drafts = deepcopy(other.browser_recipe_drafts)
        self.web_research_sessions = deepcopy(other.web_research_sessions)
        self.worker_self_checks = deepcopy(other.worker_self_checks)
        self.follow_up_instructions = deepcopy(other.follow_up_instructions)
        self.trace_events = deepcopy(other.trace_events)
        self._jsonl_path = jsonl_path
        self._tier_status_cap = other._tier_status_cap

    def apply_domain_proposal(
        self, proposal: DomainWriteProposal
    ) -> (
        SourceRecord
        | EvidenceCard
        | CandidateDemand
        | AuditReport
        | DemandReport
        | ReportContextBundle
        | SourceStrategy
        | BrowserRecipeDraft
    ):
        payload = dict(proposal.payload)
        if proposal.object_type == "SourceRecord" and proposal.action == "upsert":
            return self.upsert_source(
                SourceRecord(
                    source_id=str(payload["source_id"]),
                    title=str(payload.get("title", "")),
                    source_name=str(payload.get("source_name", "")),
                    source_tier=str(payload.get("source_tier", "")),
                    source_type=str(payload.get("source_type", "")),
                    publish_time=_parse_datetime_or_none(payload.get("publish_time")),
                    url_or_path=str(payload.get("url_or_path", "")),
                    summary_text=payload.get("summary_text"),
                    summary_source=str(payload.get("summary_source", "")),
                    collection_decision=str(payload.get("collection_decision", "")),
                    author_or_org=payload.get("author_or_org"),
                    is_repost=payload.get("is_repost"),
                    original_source=payload.get("original_source"),
                    institutional_stance=payload.get("institutional_stance"),
                    created_at=_parse_datetime(payload.get("created_at")),
                    updated_at=_parse_datetime(payload.get("updated_at")),
                    open_source_lead_id=payload.get("open_source_lead_id"),
                )
            )
        if proposal.object_type == "EvidenceCard" and proposal.action == "upsert":
            return self.upsert_evidence(
                EvidenceCard(
                    evidence_id=str(payload["evidence_id"]),
                    source_id=str(payload.get("source_id", "")),
                    claim=str(payload.get("claim", "")),
                    evidence_summary=str(payload.get("evidence_summary", "")),
                    excerpt=payload.get("excerpt"),
                    source_location=str(payload.get("source_location", "")),
                    evidence_assessment=str(payload.get("evidence_assessment", "")),
                    created_by=str(payload.get("created_by", "")),
                    created_at=_parse_datetime(payload.get("created_at")),
                    source_quality_assessment_id=payload.get(
                        "source_quality_assessment_id"
                    ),
                )
            )
        if proposal.object_type == "CandidateDemand" and proposal.action == "upsert":
            return self.upsert_candidate(
                CandidateDemand(
                    candidate_id=str(payload["candidate_id"]),
                    title=str(payload.get("title", "")),
                    demand_statement=str(payload.get("demand_statement", "")),
                    status=str(payload.get("status", "candidate_demand")),
                    evidence_ids=list(payload.get("evidence_ids", [])),
                    open_questions=list(payload.get("open_questions", [])),
                    solution_signals=list(payload.get("solution_signals", [])),
                    created_by=str(payload.get("created_by", "")),
                    created_at=_parse_datetime(payload.get("created_at")),
                    updated_at=_parse_datetime(payload.get("updated_at")),
                    superseded_by=payload.get("superseded_by"),
                    superseded_reason=payload.get("superseded_reason"),
                )
            )
        if proposal.object_type == "CandidateDemand" and proposal.action == "merge":
            return self.merge_candidate(
                str(payload["candidate_id"]),
                surviving_candidate_id=str(payload["surviving_candidate_id"]),
                actor=str(payload.get("actor", "harness")),
            )
        if proposal.object_type == "AuditReport" and proposal.action == "append":
            return self.append_audit(
                AuditReport(
                    audit_id=str(payload["audit_id"]),
                    candidate_id=str(payload["candidate_id"]),
                    conclusion=str(payload.get("conclusion", "")),
                    scorecard=dict(payload.get("scorecard", {})),
                    comments=str(payload.get("comments", "")),
                    required_rework=list(payload.get("required_rework", [])),
                    created_by=str(payload.get("created_by", "")),
                    created_at=_parse_datetime(payload.get("created_at")),
                )
            )
        if proposal.object_type == "DemandReport" and proposal.action == "append":
            return self.append_demand_report(
                _demand_report_from_dict(payload)
            )
        if proposal.object_type == "DemandReport" and proposal.action == "upsert":
            report = _demand_report_from_dict(payload)
            self._validate_report_review_status(report.review_status)
            self.demand_reports[report.report_id] = report
            return report
        if proposal.object_type == "ReportContextBundle" and proposal.action == "upsert":
            return self.upsert_report_context_bundle(
                report_context_bundle_from_dict(payload)
            )
        if proposal.object_type == "SourceStrategy" and proposal.action == "upsert":
            return self.upsert_source_strategy(source_strategy_from_dict(payload))
        if proposal.object_type == "ResearchLead" and proposal.action == "upsert":
            return self.upsert_research_lead(research_lead_from_dict(payload))
        if proposal.object_type == "ReadingQueue" and proposal.action == "upsert":
            return self.upsert_reading_queue(reading_queue_from_dict(payload))
        if proposal.object_type == "ResearchRound" and proposal.action == "upsert":
            return self.upsert_research_round(research_round_from_dict(payload))
        if proposal.object_type == "JudgementReport" and proposal.action == "upsert":
            return self.upsert_judgement_report(judgement_report_from_dict(payload))
        if proposal.object_type == "OpenSearchPlan" and proposal.action == "upsert":
            return self.upsert_open_search_plan(open_search_plan_from_dict(payload))
        if proposal.object_type == "OpenSourceLead" and proposal.action == "upsert":
            return self.upsert_open_source_lead(open_source_lead_from_dict(payload))
        if proposal.object_type == "OpenSourceBodyArtifact" and proposal.action == "upsert":
            return self.upsert_open_source_body_artifact(
                open_source_body_artifact_from_dict(payload)
            )
        if proposal.object_type == "SourceQualityAssessment" and proposal.action == "upsert":
            return self.upsert_source_quality_assessment(
                source_quality_assessment_from_dict(payload)
            )
        if proposal.object_type == "BrowserRecipeDraft" and proposal.action == "upsert":
            return self.upsert_browser_recipe_draft(
                browser_recipe_draft_from_dict(payload)
            )
        if proposal.object_type == "WebResearchSession" and proposal.action == "upsert":
            return self.upsert_web_research_session(
                web_research_session_from_dict(payload)
            )
        if proposal.object_type == "WorkerSelfCheck" and proposal.action == "upsert":
            return self.upsert_worker_self_check(worker_self_check_from_dict(payload))
        if proposal.object_type == "FollowUpInstruction" and proposal.action == "upsert":
            return self.upsert_follow_up_instruction(
                follow_up_instruction_from_dict(payload)
            )
        raise ValueError(
            f"unsupported domain proposal: {proposal.action} {proposal.object_type}"
        )

    def append_trace_from_proposal(
        self,
        proposal: DomainTraceProposal,
        actor: str = "harness",
        trace_id: str = "domain-store",
    ) -> DomainTraceEvent:
        payload = dict(proposal.payload)
        event = DomainTraceEvent(
            domain_trace_id=f"dt-{uuid4().hex}",
            trace_id=trace_id,
            event_type=proposal.event_type,
            actor=actor,
            target_type=proposal.target_type,
            target_id=proposal.target_id,
            input_refs=list(proposal.input_refs),
            output_refs=list(proposal.output_refs),
            summary=proposal.payload_summary,
            decision=payload.get("decision"),
            rationale=payload.get("rationale"),
            model=payload.get("model"),
            prompt_id=payload.get("prompt_id"),
            tool_refs=list(payload.get("tool_refs", [])),
            runtime_event_id=payload.get("runtime_event_id"),
            created_at=_now(),
            payload=payload,
        )
        return self.append_trace(event)

    def export_jsonl(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        rows.extend(("SourceRecord", item.to_dict()) for item in self.sources.values())
        rows.extend(("EvidenceCard", item.to_dict()) for item in self.evidence.values())
        rows.extend(
            ("CandidateDemand", item.to_dict()) for item in self.candidates.values()
        )
        rows.extend(
            ("AuditReport", item.to_dict()) for item in self.audit_reports.values()
        )
        rows.extend(
            ("DemandReport", item.to_dict()) for item in self.demand_reports.values()
        )
        rows.extend(
            ("ReportContextBundle", item.to_dict())
            for item in self.report_context_bundles.values()
        )
        rows.extend(
            ("HumanReviewRecord", item.to_dict()) for item in self.human_reviews.values()
        )
        rows.extend(
            ("SourceStrategy", item.to_dict()) for item in self.source_strategies.values()
        )
        rows.extend(
            ("ResearchLead", item.to_dict()) for item in self.research_leads.values()
        )
        rows.extend(
            ("ReadingQueue", item.to_dict()) for item in self.reading_queues.values()
        )
        rows.extend(
            ("ResearchRound", item.to_dict()) for item in self.research_rounds.values()
        )
        rows.extend(
            ("JudgementReport", item.to_dict()) for item in self.judgement_reports.values()
        )
        rows.extend(
            ("OpenSearchPlan", item.to_dict()) for item in self.open_search_plans.values()
        )
        rows.extend(
            ("OpenSourceLead", item.to_dict()) for item in self.open_source_leads.values()
        )
        rows.extend(
            ("OpenSourceBodyArtifact", item.to_dict())
            for item in self.open_source_body_artifacts.values()
        )
        rows.extend(
            ("SourceQualityAssessment", item.to_dict())
            for item in self.source_quality_assessments.values()
        )
        rows.extend(
            ("BrowserRecipeDraft", item.to_dict())
            for item in self.browser_recipe_drafts.values()
        )
        rows.extend(
            ("WebResearchSession", item.to_dict())
            for item in self.web_research_sessions.values()
        )
        rows.extend(
            ("WorkerSelfCheck", item.to_dict())
            for item in self.worker_self_checks.values()
        )
        rows.extend(
            ("FollowUpInstruction", item.to_dict())
            for item in self.follow_up_instructions.values()
        )
        rows.extend(
            ("DomainTraceEvent", item.to_dict()) for item in self.trace_events
        )
        with output.open("w", encoding="utf-8") as handle:
            for row_type, payload in rows:
                handle.write(
                    json.dumps(
                        {"type": row_type, "payload": payload},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                handle.write("\n")

    def export_append_only_snapshot(self, path: str | Path | None = None) -> None:
        output = Path(path) if path is not None else self._jsonl_path
        if output is None:
            raise ValueError("path is required when store is not bound to JSONL")
        output.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        for item in self.sources.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "SourceRecord",
                    "payload": item.to_dict(),
                }
            )
        for item in self.evidence.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "EvidenceCard",
                    "payload": item.to_dict(),
                }
            )
        for item in self.candidates.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "CandidateDemand",
                    "payload": item.to_dict(),
                }
            )
        for item in self.audit_reports.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "append",
                    "object_type": "AuditReport",
                    "payload": item.to_dict(),
                }
            )
        for item in self.demand_reports.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "append",
                    "object_type": "DemandReport",
                    "payload": item.to_dict(),
                }
            )
        for item in self.human_reviews.values():
            rows.append({"kind": "human_review", "payload": item.to_dict()})
        for item in self.source_strategies.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "SourceStrategy",
                    "payload": item.to_dict(),
                }
            )
        for item in self.research_leads.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "ResearchLead",
                    "payload": item.to_dict(),
                }
            )
        for item in self.reading_queues.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "ReadingQueue",
                    "payload": item.to_dict(),
                }
            )
        for item in self.research_rounds.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "ResearchRound",
                    "payload": item.to_dict(),
                }
            )
        for item in self.judgement_reports.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "JudgementReport",
                    "payload": item.to_dict(),
                }
            )
        for item in self.report_context_bundles.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "ReportContextBundle",
                    "payload": item.to_dict(),
                }
            )
        for item in self.open_search_plans.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "OpenSearchPlan",
                    "payload": item.to_dict(),
                }
            )
        for item in self.open_source_leads.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "OpenSourceLead",
                    "payload": item.to_dict(),
                }
            )
        for item in self.open_source_body_artifacts.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "OpenSourceBodyArtifact",
                    "payload": item.to_dict(),
                }
            )
        for item in self.source_quality_assessments.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "SourceQualityAssessment",
                    "payload": item.to_dict(),
                }
            )
        for item in self.browser_recipe_drafts.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "BrowserRecipeDraft",
                    "payload": item.to_dict(),
                }
            )
        for item in self.web_research_sessions.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "WebResearchSession",
                    "payload": item.to_dict(),
                }
            )
        for item in self.worker_self_checks.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "WorkerSelfCheck",
                    "payload": item.to_dict(),
                }
            )
        for item in self.follow_up_instructions.values():
            rows.append(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "FollowUpInstruction",
                    "payload": item.to_dict(),
                }
            )
        for item in self.trace_events:
            rows.append({"kind": "trace_event", "payload": item.to_dict()})
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def to_run_state(self) -> dict[str, Any]:
        return {
            "sources": [item.to_dict() for item in self.sources.values()],
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "candidates": [item.to_dict() for item in self.candidates.values()],
            "audits": [item.to_dict() for item in self.audit_reports.values()],
            "reports": [item.to_dict() for item in self.demand_reports.values()],
            "human_reviews": [item.to_dict() for item in self.human_reviews.values()],
            "source_strategies": [
                item.to_dict() for item in self.source_strategies.values()
            ],
            "research_leads": [item.to_dict() for item in self.research_leads.values()],
            "reading_queues": [item.to_dict() for item in self.reading_queues.values()],
            "research_rounds": [item.to_dict() for item in self.research_rounds.values()],
            "judgement_reports": [item.to_dict() for item in self.judgement_reports.values()],
            "report_context_bundles": [
                item.to_dict() for item in self.report_context_bundles.values()
            ],
            "open_search_plans": [item.to_dict() for item in self.open_search_plans.values()],
            "open_source_leads": [item.to_dict() for item in self.open_source_leads.values()],
            "open_source_body_artifacts": [
                item.to_dict() for item in self.open_source_body_artifacts.values()
            ],
            "source_quality_assessments": [
                item.to_dict() for item in self.source_quality_assessments.values()
            ],
            "browser_recipe_drafts": [
                item.to_dict() for item in self.browser_recipe_drafts.values()
            ],
            "web_research_sessions": [
                item.to_dict() for item in self.web_research_sessions.values()
            ],
            "worker_self_checks": [
                item.to_dict() for item in self.worker_self_checks.values()
            ],
            "follow_up_instructions": [
                item.to_dict() for item in self.follow_up_instructions.values()
            ],
            "trace_events": [item.to_dict() for item in self.trace_events],
        }

    def _append_human_review_record(
        self,
        record: HumanReviewRecord,
        *,
        persist: bool,
    ) -> HumanReviewRecord:
        if record.report_id not in self.demand_reports:
            raise ValueError(f"unknown report_id: {record.report_id}")
        decision = record.decision.strip().lower()
        if decision not in HUMAN_REVIEW_DECISIONS:
            raise ValueError(f"unknown human review decision: {record.decision}")
        if record.review_id in self.human_reviews:
            return self.human_reviews[record.review_id]

        report = self.demand_reports[record.report_id]
        candidate = self.candidates[report.candidate_id]
        report_status, candidate_status = _human_review_status_effect(decision)
        updated_report = replace(report, review_status=report_status)
        self.demand_reports[record.report_id] = updated_report
        updated_candidate: CandidateDemand | None = None
        if candidate_status is not None and candidate.status != candidate_status:
            validate_transition(candidate.status, candidate_status)
            updated_candidate = replace(
                candidate,
                status=candidate_status,
                updated_at=_now(),
            )
            self.candidates[candidate.candidate_id] = updated_candidate
            if decision == "needs_revision":
                self.append_trace(
                    DomainTraceEvent(
                        domain_trace_id=f"dt-{uuid4().hex}",
                        trace_id="human-review",
                        event_type="candidate_status_rolled_back",
                        actor=record.reviewer,
                        target_type="CandidateDemand",
                        target_id=candidate.candidate_id,
                        input_refs=[record.report_id],
                        output_refs=[candidate.candidate_id],
                        summary=record.decision_reason,
                        decision=candidate_status,
                        rationale=record.decision_reason,
                        model=None,
                        prompt_id=None,
                        tool_refs=[],
                        runtime_event_id=None,
                        created_at=record.review_time,
                    )
                )

        self.human_reviews[record.review_id] = record
        event = self.append_trace(
            DomainTraceEvent(
                domain_trace_id=f"dt-{uuid4().hex}",
                trace_id="human-review",
                event_type="human_reviewed",
                actor=record.reviewer,
                target_type="DemandReport",
                target_id=record.report_id,
                input_refs=[report.candidate_id, report.audit_id, *report.evidence_ids],
                output_refs=[record.review_id, record.report_id],
                summary=record.decision_reason,
                decision=decision,
                rationale=record.notes or record.decision_reason,
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=record.review_time,
                payload={
                    "accepted_claims": list(record.accepted_claims),
                    "rejected_claims": list(record.rejected_claims),
                    "requested_changes": list(record.requested_changes),
                },
            )
        )
        if persist:
            self._append_jsonl({"kind": "human_review", "payload": record.to_dict()})
            self._append_jsonl(
                {
                    "kind": "domain",
                    "action": "upsert",
                    "object_type": "DemandReport",
                    "payload": updated_report.to_dict(),
                }
            )
            if updated_candidate is not None:
                self._append_jsonl(
                    {
                        "kind": "domain",
                        "action": "upsert",
                        "object_type": "CandidateDemand",
                        "payload": updated_candidate.to_dict(),
                    }
                )
            if decision == "needs_revision" and len(self.trace_events) >= 2:
                self._append_jsonl(
                    {
                        "kind": "trace_event",
                        "payload": self.trace_events[-2].to_dict(),
                    }
                )
            self._append_jsonl({"kind": "trace_event", "payload": event.to_dict()})
        return record

    def _validate_report_review_status(self, status: str) -> None:
        if status not in REPORT_REVIEW_STATUSES:
            raise ValueError(f"unknown report review_status: {status}")

    def _audit_sensitive_flag(self, audit_id: str) -> bool:
        audit = self.audit_reports.get(audit_id)
        if audit is None:
            return False
        row = audit.scorecard.get("sensitive_flag")
        if not isinstance(row, dict):
            return False
        verdict = str(row.get("verdict", "")).strip().lower()
        return verdict in {"fail", "doubt", "yes", "true"}

    def _apply_export_row(self, row_type: str, payload: dict[str, Any]) -> None:
        if row_type == "SourceRecord":
            self.apply_domain_proposal(DomainWriteProposal("upsert", row_type, payload))
        elif row_type == "EvidenceCard":
            self.apply_domain_proposal(DomainWriteProposal("upsert", row_type, payload))
        elif row_type == "CandidateDemand":
            self.apply_domain_proposal(DomainWriteProposal("upsert", row_type, payload))
        elif row_type == "AuditReport":
            self.apply_domain_proposal(DomainWriteProposal("append", row_type, payload))
        elif row_type == "DemandReport":
            self.apply_domain_proposal(DomainWriteProposal("append", row_type, payload))
        elif row_type == "ReportContextBundle":
            self.upsert_report_context_bundle(report_context_bundle_from_dict(payload))
        elif row_type == "HumanReviewRecord":
            record = _human_review_from_dict(payload)
            self.human_reviews[record.review_id] = record
        elif row_type == "SourceStrategy":
            self.upsert_source_strategy(source_strategy_from_dict(payload))
        elif row_type == "ResearchLead":
            self.upsert_research_lead(research_lead_from_dict(payload))
        elif row_type == "ReadingQueue":
            self.upsert_reading_queue(reading_queue_from_dict(payload))
        elif row_type == "ResearchRound":
            self.upsert_research_round(research_round_from_dict(payload))
        elif row_type == "JudgementReport":
            self.upsert_judgement_report(judgement_report_from_dict(payload))
        elif row_type == "OpenSearchPlan":
            self.upsert_open_search_plan(open_search_plan_from_dict(payload))
        elif row_type == "OpenSourceLead":
            self.upsert_open_source_lead(open_source_lead_from_dict(payload))
        elif row_type == "OpenSourceBodyArtifact":
            self.upsert_open_source_body_artifact(
                open_source_body_artifact_from_dict(payload)
            )
        elif row_type == "SourceQualityAssessment":
            self.upsert_source_quality_assessment(
                source_quality_assessment_from_dict(payload)
            )
        elif row_type == "BrowserRecipeDraft":
            self.upsert_browser_recipe_draft(browser_recipe_draft_from_dict(payload))
        elif row_type == "WebResearchSession":
            self.upsert_web_research_session(web_research_session_from_dict(payload))
        elif row_type == "WorkerSelfCheck":
            self.upsert_worker_self_check(worker_self_check_from_dict(payload))
        elif row_type == "FollowUpInstruction":
            self.upsert_follow_up_instruction(follow_up_instruction_from_dict(payload))
        elif row_type == "DomainTraceEvent":
            self.append_trace(_trace_event_from_dict(payload))

    def _validate_evidence_ids(self, evidence_ids: list[str]) -> None:
        missing = [item for item in evidence_ids if item not in self.evidence]
        if missing:
            raise ValueError(f"unknown evidence_id: {missing[0]}")

    def _validate_candidate_status(self, candidate: CandidateDemand) -> None:
        validate_status(candidate.status)
        existing = self.candidates.get(candidate.candidate_id)
        if existing is not None:
            validate_transition(existing.status, candidate.status)
        cap = self._candidate_status_cap(candidate.evidence_ids)
        if cap is not None:
            validate_status_cap(candidate.status, cap)

    def _candidate_status_cap(self, evidence_ids: list[str]) -> str | None:
        if self._tier_status_cap is None:
            return None
        caps: list[str] = []
        for evidence_id in evidence_ids:
            evidence = self.evidence.get(evidence_id)
            if evidence is None:
                continue
            source = self.sources.get(evidence.source_id)
            if source is None:
                continue
            caps.append(self._tier_status_cap(source.source_tier))
        if not caps:
            return None
        return max(caps, key=status_rank)

    def _latest_trace_for(
        self, target_id: str, event_type: str
    ) -> DomainTraceEvent | None:
        for event in reversed(self.trace_events):
            if event.target_id == target_id and event.event_type == event_type:
                return event
        return None

    def _evidence_satisfies_minimum_report_gate(self, evidence_id: str) -> bool:
        from knowledgegraph.demand_discovery.domain.evidence_support import (
            normalize_support_level,
        )

        evidence = self.evidence[evidence_id]
        if not (evidence.excerpt or "").strip():
            return False
        level = normalize_support_level(evidence.evidence_assessment)
        if level in {"weak", "irrelevant", "unassessed"}:
            return False
        location = str(evidence.source_location or "")
        if not _source_location_looks_like_body(location):
            return False
        source = self.sources.get(evidence.source_id)
        if source is None:
            return False
        if source.collection_decision == "use_as_background":
            return False
        if source.open_source_lead_id:
            if evidence.evidence_assessment == "provisional":
                return False
            assessment_id = evidence.source_quality_assessment_id or ""
            assessment = self.source_quality_assessments.get(assessment_id)
            if assessment is None:
                return False
            if assessment.lead_id != source.open_source_lead_id:
                return False
            if evidence.source_location not in assessment.body_location_refs:
                return False
            if assessment.quality_level not in {"trusted", "usable"}:
                return False
        source_tier = source.source_tier.strip().upper()
        return source_tier not in {"", "C", "D"}

    def _evidence_map_for_support(self, evidence_ids: list[str]) -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for evidence_id in evidence_ids:
            evidence = self.evidence.get(evidence_id)
            if evidence is None:
                continue
            rows[evidence_id] = {
                "source_id": evidence.source_id,
                "source_location": evidence.source_location,
            }
        return rows


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _looks_like_legacy_paragraph_ref(value: str) -> bool:
    return value.startswith("p") and value[1:].isdigit()


def _source_location_looks_like_body(value: str) -> bool:
    location = value.strip()
    if not location:
        return False
    lowered = location.lower()
    non_body_prefixes = (
        "listing:",
        "search:",
        "home:",
        "site_home:",
        "browser_observation:",
    )
    if lowered.startswith(non_body_prefixes):
        return False
    return True


def _normalize_audit_conclusion(value: str) -> str:
    return value.strip().lower()


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        text = value.strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for fmt in ("%Y/%m/%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return parsedate_to_datetime(text)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid isoformat string: {value!r}")
    return _now()


def _export_load_priority(row: tuple[str, dict[str, Any]]) -> int:
    priorities = {
        "SourceStrategy": 5,
        "OpenSearchPlan": 10,
        "OpenSourceLead": 20,
        "OpenSourceBodyArtifact": 30,
        "SourceQualityAssessment": 40,
        "BrowserRecipeDraft": 45,
        "WebResearchSession": 47,
        "SourceRecord": 50,
        "ResearchLead": 50,
        "EvidenceCard": 60,
        "ReadingQueue": 60,
        "ResearchRound": 65,
        "WorkerSelfCheck": 66,
        "FollowUpInstruction": 67,
        "CandidateDemand": 70,
        "JudgementReport": 75,
        "AuditReport": 80,
        "ReportContextBundle": 85,
        "DemandReport": 90,
        "HumanReviewRecord": 95,
        "DomainTraceEvent": 100,
    }
    return priorities.get(row[0], 500)


def _parse_datetime_or_none(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return _parse_datetime(value)


def _trace_event_from_dict(data: dict[str, Any]) -> DomainTraceEvent:
    return DomainTraceEvent(
        domain_trace_id=str(data["domain_trace_id"]),
        trace_id=str(data.get("trace_id", "")),
        event_type=str(data.get("event_type", "")),
        actor=str(data.get("actor", "")),
        target_type=str(data.get("target_type", "")),
        target_id=str(data.get("target_id", "")),
        input_refs=list(data.get("input_refs", [])),
        output_refs=list(data.get("output_refs", [])),
        summary=str(data.get("summary", "")),
        decision=data.get("decision"),
        rationale=data.get("rationale"),
        model=data.get("model"),
        prompt_id=data.get("prompt_id"),
        tool_refs=list(data.get("tool_refs", [])),
        runtime_event_id=data.get("runtime_event_id"),
        created_at=_parse_datetime(data.get("created_at")),
        payload=dict(data.get("payload", {})),
    )


def _demand_report_from_dict(data: dict[str, Any]) -> DemandReport:
    return DemandReport(
        report_id=str(data["report_id"]),
        candidate_id=str(data["candidate_id"]),
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        evidence_ids=list(data.get("evidence_ids", [])),
        audit_id=str(data.get("audit_id", "")),
        domain_trace_ids=list(data.get("domain_trace_ids", [])),
        created_at=_parse_datetime(data.get("created_at")),
        review_status=str(data.get("review_status", "draft")),
        sensitive_review_required=bool(data.get("sensitive_review_required", False)),
    )


def _human_review_from_dict(data: dict[str, Any]) -> HumanReviewRecord:
    return HumanReviewRecord(
        review_id=str(data["review_id"]),
        report_id=str(data["report_id"]),
        reviewer=str(data.get("reviewer", "")),
        review_time=_parse_datetime(data.get("review_time")),
        decision=str(data.get("decision", "")),
        decision_reason=str(data.get("decision_reason", "")),
        accepted_claims=list(data.get("accepted_claims", [])),
        rejected_claims=list(data.get("rejected_claims", [])),
        requested_changes=list(data.get("requested_changes", [])),
        notes=str(data.get("notes", "")),
    )


def _human_review_status_effect(decision: str) -> tuple[str, str | None]:
    if decision in {"approved", "approved_with_changes"}:
        return "approved", "human_reviewed"
    if decision == "needs_revision":
        return "draft", "candidate_demand"
    if decision == "rejected":
        return "rejected", None
    if decision == "watchlist":
        return "watchlist", None
    raise ValueError(f"unknown human review decision: {decision}")
